"""问题生成代理（基于设计文档 2026-05-21 重构版）。"""

import random
from pathlib import Path
from typing import Any
from datetime import datetime

from loguru import logger

from benchforge.schemas import (
    SourceDocument,
    SourceChunk,
    QuestionRecord,
    Citation,
    QuestionMode,
    Difficulty,
    TopicStatus,
    NextStepAction,
    GenerationPlan,
    TopicState,
    EvidencePool,
    SingleChunkUnit,
    MultiChunkUnit,
    GenerationBatch,
    NextStepPlan,
    GenerationReport,
    QuestionModeTarget,
)
from benchforge.config import QuestionGeneratorConfig
from benchforge.models.base import BaseModelClient
from benchforge.models import OpenAIClient
from benchforge.utils import (
    chunk_document,
    search_wikipedia,
    fetch_wikipedia_page,
)
from benchforge.utils.signals import SignalCalculator
from benchforge.utils.multi_chunk import MultiChunkBuilder, build_evidence_pool_from_chunks
from benchforge.utils.sampling import BroadExplorationSampling, GapDrivenSampling
from benchforge.utils.filter import LightweightFilter, parse_llm_response
from benchforge.utils.planning import (
    compile_generation_plan,
    update_topic_state,
    identify_main_gap,
    update_evidence_stats,
    check_topic_completion,
    calculate_batch_request_counts,
    format_evidence_texts,
    build_allowed_actions,
    build_next_step_plan,
    identify_global_gap,
)
from benchforge.artifacts.store import ArtifactStore


class QuestionGeneratorAgent:
    """问题生成代理。

    实现基于设计文档的状态机和调度逻辑。
    """

    def __init__(
        self,
        config: QuestionGeneratorConfig | None = None,
        config_path: str | Path | None = None,
        model_client: BaseModelClient | None = None,
        model_clients: list[BaseModelClient] | None = None,
    ):
        """初始化代理。

        Args:
            config: 配置对象
            config_path: 配置文件路径
            model_client: 单个模型客户端（向后兼容）
            model_clients: 多个模型客户端列表（新功能）
        """
        if config is not None:
            self.config = config
        elif config_path is not None:
            self.config = QuestionGeneratorConfig.from_yaml(config_path)
        else:
            self.config = QuestionGeneratorConfig()

        self.output_path = self.config.get_resolved_output_path()
        self.output_path.mkdir(parents=True, exist_ok=True)

        # 支持单模型或多模型
        if model_clients:
            self.model_clients = model_clients
        elif model_client:
            self.model_clients = [model_client]
        else:
            self.model_clients = [OpenAIClient(
                api_key=self.config.generation.model.api_key,
                base_url=self.config.generation.model.base_url,
            )]

        self.artifact_store = ArtifactStore(str(self.output_path))

        # 工具初始化
        self.signal_calculator = SignalCalculator()
        self.multi_chunk_builder = MultiChunkBuilder()
        self.filter = LightweightFilter()

        # 状态变量
        self.topic_states: dict[str, TopicState] = {}
        self.evidence_pools: dict[str, EvidencePool] = {}
        self.all_questions: list[dict[str, Any]] = []
        self.document_summaries: dict[str, str] = {}
        self._topic_preferences: dict[str, dict[str, Any]] = {}

        # 统计
        self.total_rounds = 0

    async def execute(self, plan: GenerationPlan) -> GenerationReport:
        """执行问题生成任务。

        Args:
            plan: 生成计划

        Returns:
            生成报告
        """
        logger.info(f"Starting question generation for run: {plan.run_id}")
        logger.info(f"Topics: {plan.topics}")
        logger.info(f"Goal: {plan.goal}")

        # 编译计划
        self.topic_states = compile_generation_plan(plan)

        # 阶段 1: 主题串行执行
        for topic in plan.topics:
            await self._process_topic(topic, plan)

        # 阶段 2: 全局补题
        if self._has_global_gaps() and self.total_rounds < plan.max_total_rounds:
            await self._global_backfill(plan)

        # 生成报告
        report = self._build_report(plan)

        # 保存结果
        self._save_results(report)

        return report

    async def _process_topic(self, topic: str, plan: GenerationPlan) -> None:
        """处理单个主题。

        Args:
            topic: 主题名称
            plan: 生成计划
        """
        logger.info(f"Processing topic: {topic}")

        state = self.topic_states[topic]
        state.status = TopicStatus.ACTIVE

        # 准备证据
        await self._prepare_evidence(topic, plan)

        # 多轮生成循环
        while (
            state.current_round < plan.max_rounds_per_topic
            and not check_topic_completion(state)
            and self.total_rounds < plan.max_total_rounds
        ):
            await self._run_generation_round(topic, plan)

        # 检查退出条件
        if check_topic_completion(state):
            state.status = TopicStatus.COMPLETED
            logger.info(f"Topic {topic} completed")
        else:
            state.status = TopicStatus.DEFERRED
            logger.info(f"Topic {topic} deferred")

    async def _prepare_evidence(self, topic: str, plan: GenerationPlan) -> None:
        """准备证据池。

        步骤：
        1. 检索主题相关文档
        2. 生成文档摘要（使用 LLM，复用 Yourbench prompts）
        3. 切分 chunk
        4. 构建证据池

        Args:
            topic: 主题名称
            plan: 生成计划
        """
        logger.info(f"Preparing evidence for topic: {topic}")

        state = self.topic_states[topic]

        # 检索文档
        search_results = search_wikipedia(
            query=topic,
            language=plan.language,
            max_pages=self.config.retrieval.max_pages,
        )

        if not search_results:
            logger.warning(f"No search results for topic: {topic}")
            return

        # 抓取并处理文档
        all_chunks: list[SourceChunk] = []

        for result in search_results:
            document = fetch_wikipedia_page(
                result=result,
                run_id=plan.run_id,
                language=plan.language,
                content_max_length=self.config.retrieval.content_max_length,
            )

            if document.status.value == "failed":
                continue

            # 保存文档
            if self.config.output.save_source_documents:
                self.artifact_store.append_jsonl("source_documents.jsonl", [document])

            # 分块
            chunks = chunk_document(
                document=document,
                chunk_size=self.config.chunking.chunk_size,
                overlap=self.config.chunking.overlap,
            )

            # 生成文档摘要（使用 LLM，复用 Yourbench prompts）
            document_summary = await self._generate_document_summary(document, chunks)

            self.document_summaries[document.document_id] = document_summary
            state.retrieved_documents.append(document.document_id)

            all_chunks.extend(chunks)

        logger.info(f"Retrieved {len(all_chunks)} chunks for topic: {topic}")

        # 构建证据池
        await self._build_evidence_pool(topic, all_chunks)

    async def _generate_document_summary(
        self,
        document: SourceDocument,
        chunks: list[SourceChunk],
    ) -> str:
        """生成文档摘要（复用 Yourbench summarization prompts）。

        步骤：
        1. 对每个 chunk 生成摘要
        2. 如果有多个 chunk，合并摘要

        Args:
            document: 源文档
            chunks: chunk 列表

        Returns:
            文档摘要
        """
        if not chunks:
            return document.summary or ""

        # Stage 1: 生成 chunk summaries
        chunk_summaries = []

        for chunk in chunks:
            try:
                response = await self.model_clients[0].complete(
                    model=getattr(self.model_clients[0], 'model_name', 'gpt-4o'),
                    messages=[
                        {"role": "user", "content": self._get_summarization_prompt(chunk.text)},
                    ],
                    temperature=0.3,
                    max_tokens=300,
                )

                # 提取摘要
                import re
                summary_match = re.search(r'<final_summary>(.*?)</final_summary>',
                                         response["text"], re.DOTALL | re.IGNORECASE)
                if summary_match:
                    summary = summary_match.group(1).strip()
                else:
                    summary = response["text"].strip()[:200]

                chunk_summaries.append(summary)

            except Exception as e:
                logger.warning(f"Failed to summarize chunk {chunk.chunk_id}: {e}")
                chunk_summaries.append("")

        # Stage 2: 如果有多个 chunk，合并摘要
        if len(chunk_summaries) > 1:
            try:
                bullet_list = "\n".join(f"- {s}" for s in chunk_summaries if s)

                # 从文件加载合并摘要 prompt
                combine_prompt_path = Path(__file__).parent.parent / "prompts" / "question_generator" / "combine_summaries_user_prompt.md"
                if combine_prompt_path.exists():
                    with open(combine_prompt_path, "r", encoding="utf-8") as f:
                        template = f.read()
                    combine_prompt = template.replace("{chunk_summaries}", bullet_list)
                else:
                    combine_prompt = f"""<chunk_summaries>
{bullet_list}
</chunk_summaries>

Provide a concise overview in <final_summary> tags."""

                response = await self.model_clients[0].complete(
                    model=getattr(self.model_clients[0], 'model_name', 'gpt-4o'),
                    messages=[
                        {"role": "user", "content": combine_prompt},
                    ],
                    temperature=0.3,
                    max_tokens=500,
                )

                import re
                final_match = re.search(r'<final_summary>(.*?)</final_summary>',
                                         response["text"], re.DOTALL | re.IGNORECASE)
                if final_match:
                    return final_match.group(1).strip()
                else:
                    return response["text"].strip()
            except Exception as e:
                logger.warning(f"Failed to combine summaries: {e}")

        # 如果只有一个 chunk 或合并失败，返回第一个摘要
        return chunk_summaries[0] if chunk_summaries else document.summary or ""

    def _get_summarization_prompt(self, text: str) -> str:
        """获取 summarization prompt（从文件加载）。

        Args:
            text: 文本内容

        Returns:
            prompt
        """
        prompt_path = Path(__file__).parent.parent / "prompts" / "question_generator" / "summarization_user_prompt.md"

        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                template = f.read()
            return template.replace("{document}", text)
        else:
            return f"""<document>
{text}
</document>

Provide a concise summary in <final_summary> tags."""

    async def _build_evidence_pool(
        self,
        topic: str,
        chunks: list[SourceChunk],
    ) -> None:
        """构建证据池。

        Args:
            topic: 主题名称
            chunks: chunk 列表
        """
        # 按文档分组 chunks，以便正确传递文档摘要
        chunks_by_doc: dict[str, list[SourceChunk]] = {}
        for chunk in chunks:
            if chunk.document_id not in chunks_by_doc:
                chunks_by_doc[chunk.document_id] = []
            chunks_by_doc[chunk.document_id].append(chunk)

        # 构建单证据单元（按文档分组以传递摘要）
        single_units = []
        for doc_id, doc_chunks in chunks_by_doc.items():
            doc_summary = self.document_summaries.get(doc_id, "")
            doc_units = build_evidence_pool_from_chunks(
                doc_chunks,
                topic,
                document_summary=doc_summary
            )
            single_units.extend(doc_units)

        # 构建多证据单元
        doc_summaries = {}
        for chunk in chunks:
            if chunk.document_id not in doc_summaries:
                doc_summaries[chunk.document_id] = self.document_summaries.get(
                    chunk.document_id, ""
                )

        multi_units = self.multi_chunk_builder.build_multi_chunk_units_smart(
            single_units,
            doc_summaries,
            target_count=min(10, len(single_units) // 2),
        )

        # 创建证据池
        pool = EvidencePool(
            topic=topic,
            single_chunks=single_units,
            multi_chunks=multi_units,
        )

        self.evidence_pools[topic] = pool

        # 更新状态
        state = self.topic_states[topic]
        state.available_single_chunk_ids = [u.chunk_id for u in single_units]
        state.available_multi_chunk_ids = [u.unit_id for u in multi_units]

        logger.info(
            f"Built evidence pool: {len(single_units)} single, {len(multi_units)} multi"
        )

    async def _run_generation_round(
        self,
        topic: str,
        plan: GenerationPlan,
    ) -> None:
        """执行一轮生成。

        Args:
            topic: 主题名称
            plan: 生成计划
        """
        state = self.topic_states[topic]
        pool = self.evidence_pools.get(topic)

        if not pool or not pool.single_chunks:
            logger.warning(f"No evidence pool for topic: {topic}")
            state.current_round += 1
            self.total_rounds += 1
            return

        self.total_rounds += 1

        # 识别主缺口
        main_gap = identify_main_gap(state)
        if not main_gap:
            logger.info(f"No gaps for topic: {topic}")
            return

        gap_key, remaining = main_gap
        target_mode, target_difficulty = gap_key.split(":")

        logger.info(
            f"Round {state.current_round}: targeting {gap_key}, remaining {remaining}"
        )

        # 选择采样策略
        if state.current_round == 1:
            sampler = BroadExplorationSampling()
        else:
            sampler = GapDrivenSampling()

        # 计算请求数量
        min_questions, target_questions = calculate_batch_request_counts(remaining)

        # 执行采样
        batch = sampler.sample(
            pool=pool,
            target_mode=target_mode,
            target_difficulty=target_difficulty,
            num_evidence=min(5, remaining + 2),
        )

        batch.requested_min_questions = min_questions
        batch.requested_target_questions = target_questions

        # 生成题目
        questions, raw_candidate_count = await self._generate_questions(batch, plan)

        # 更新状态
        batch_info = self._build_batch_info(questions, raw_candidate_count, batch)
        update_topic_state(state, batch_info)
        update_evidence_stats(pool.stats, batch_info)

        # 更新证据单元使用计数
        self._update_evidence_usage(batch, pool)

        # 构建并执行下一步计划
        allowed_actions = build_allowed_actions(state, plan.max_rounds_per_topic)
        prefer_multi = self._topic_preferences.get(topic, {}).get("prefer_multi_chunk", False)
        next_plan = build_next_step_plan(
            topic,
            gap_key,
            [a.value for a in allowed_actions],
            prefer_multi,
        )
        await self._execute_next_step_plan(next_plan, plan)

        state.current_round += 1

        logger.info(
            f"Generated {len(questions)} questions, "
            f"round {state.current_round}, total rounds {self.total_rounds}"
        )

    async def _generate_questions(
        self,
        batch: GenerationBatch,
        plan: GenerationPlan,
    ) -> tuple[list[dict[str, Any]], int]:
        """调用 LLM 生成题目（支持多模型并行）。

        使用 yourbench 风格的 prompt 模板。

        Args:
            batch: 生成批次
            plan: 生成计划

        Returns:
            (有效题目列表, 原始候选数量)
        """
        pool = self.evidence_pools.get(batch.topic)
        if not pool:
            return [], 0

        # 获取证据单元
        single_units = [
            u for u in pool.single_chunks
            if u.chunk_id in batch.single_chunk_ids
        ]
        multi_units = [
            u for u in pool.multi_chunks
            if u.unit_id in batch.multi_chunk_ids
        ]

        # 格式化证据文本
        evidence_text = format_evidence_texts(single_units, multi_units)

        # 获取文档标题和摘要
        doc_title = batch.topic
        doc_summary = ""
        if single_units and single_units[0].document_id in self.document_summaries:
            doc_summary = self.document_summaries[single_units[0].document_id]

        # 难度要求
        difficulty_requirements = {
            "easy": "Focus on basic recall and surface comprehension - answers should be directly found in the text.",
            "medium": "Focus on application, analysis, and synthesis - needs some reasoning to connect concepts.",
            "hard": "Focus on deep insights, connections, and expert-level understanding - requires multi-step reasoning.",
        }
        difficulty_req = difficulty_requirements.get(batch.target_difficulty, "")

        # 构建 system prompt（从文件加载）
        system_prompt = self._load_system_prompt(batch.target_mode)

        # 加载 user prompt 模板
        user_template = self._load_user_prompt(batch.target_mode)

        # 构建 user prompt（yourbench 风格 XML 格式）
        additional_instructions = f"Difficulty: {batch.target_difficulty}\n{difficulty_req}"
        if batch.additional_instructions:
            additional_instructions += f"\n{batch.additional_instructions}"

        user_prompt = user_template.format(
            additional_instructions=additional_instructions,
            doc_title=doc_title,
            doc_summary=doc_summary,
            evidence_text=evidence_text,
            requested_target_questions=batch.requested_target_questions,
        )

        # 并行调用所有模型
        all_questions = []
        total_raw_candidates = 0
        for idx, model_client in enumerate(self.model_clients):
            model_name = getattr(model_client, 'model_name', f'model_{idx}')
            logger.info(f"Using model: {model_name}")

            try:
                response = await model_client.complete(
                    model=getattr(model_client, 'model_name', 'gpt-4o'),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=getattr(model_client, 'temperature', 0.7),
                    max_tokens=getattr(model_client, 'max_tokens', 2000),
                )

                # 解析响应
                raw_items = parse_llm_response(response["text"])
                total_raw_candidates += len(raw_items)

                # 过滤
                passed_items, _ = self.filter.filter_questions(raw_items)

                # 标记模型来源
                for item in passed_items:
                    item["_source_model"] = model_name

                logger.info(f"Model {model_name}: {len(passed_items)}/{len(raw_items)} valid questions")
                all_questions.extend(passed_items)

            except Exception as e:
                logger.error(f"Error with model {model_name}: {e}")

        logger.info(f"Total: {len(all_questions)}/{total_raw_candidates} valid questions")

        return all_questions, total_raw_candidates

    def _load_user_prompt(self, mode: str) -> str:
        """从文件加载 user prompt。

        Args:
            mode: 模式 (qa 或 multiple_choice)

        Returns:
            用户 prompt 模板
        """
        prompt_files = {
            "multiple_choice": "prompts/question_generator/mcq_user_prompt.md",
            "qa": "prompts/question_generator/qa_user_prompt.md",
        }

        prompt_file = prompt_files.get(mode, "prompts/question_generator/qa_user_prompt.md")
        prompt_path = Path(__file__).parent.parent / prompt_file

        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            return "<additional_instructions>\n{additional_instructions}\n</additional_instructions>\n\n<title>\n{doc_title}\n</title>\n\n<document_summary>\n{doc_summary}\n</document_summary>\n\n<text_chunk>\n{evidence_text}\n</text_chunk>\n\nGenerate {requested_target_questions} questions."

    def _load_system_prompt(self, mode: str) -> str:
        """从文件加载 system prompt。

        Args:
            mode: 模式 (qa 或 multiple_choice)

        Returns:
            系统 prompt
        """
        prompt_files = {
            "multiple_choice": "prompts/question_generator/mcq_system_prompt.md",
            "qa": "prompts/question_generator/qa_system_prompt.md",
        }

        prompt_file = prompt_files.get(mode, "prompts/question_generator/qa_system_prompt.md")
        prompt_path = Path(__file__).parent.parent / prompt_file

        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            if mode == "multiple_choice":
                return "You are a document comprehension specialist who creates insightful multiple-choice questions."
            else:
                return "You are a document comprehension specialist who creates insightful question-answer pairs."

    def _build_batch_info(
        self,
        questions: list[dict[str, Any]],
        raw_candidate_count: int,
        batch: GenerationBatch,
    ) -> dict[str, Any]:
        """构建批次信息。

        Args:
            questions: 有效题目列表（已过滤）
            raw_candidate_count: 原始候选数量（过滤前）
            batch: 生成批次

        Returns:
            批次信息字典
        """
        completed_counts: dict[str, int] = {}
        single_mode_counts: dict[str, int] = {}
        single_difficulty_counts: dict[str, int] = {}
        multi_mode_counts: dict[str, int] = {}
        multi_difficulty_counts: dict[str, int] = {}

        # 转换 1-10 难度到 easy/medium/hard
        def map_difficulty(diff: Any) -> str:
            if isinstance(diff, int):
                if diff <= 3:
                    return "easy"
                elif diff <= 7:
                    return "medium"
                else:
                    return "hard"
            return str(diff).lower()

        # 分别统计单 chunk 和多 chunk 生成的题目
        for q in questions:
            diff = map_difficulty(q.get('estimated_difficulty', 'medium'))
            mode = q.get("question_mode", "qa")

            key = f"{mode}:{diff}"
            completed_counts[key] = completed_counts.get(key, 0) + 1

            # 根据 chunk 数量分类统计
            chunk_count = len(q.get("chunk_ids", []))
            if chunk_count > 1:
                # 多 chunk 生成的题目
                multi_mode_counts[mode] = multi_mode_counts.get(mode, 0) + 1
                multi_difficulty_counts[diff] = multi_difficulty_counts.get(diff, 0) + 1
            else:
                # 单 chunk 生成的题目
                single_mode_counts[mode] = single_mode_counts.get(mode, 0) + 1
                single_difficulty_counts[diff] = single_difficulty_counts.get(diff, 0) + 1

        # 保存到全局题目列表
        self.all_questions.extend(questions)

        return {
            "completed_counts": completed_counts,
            "candidate_count": raw_candidate_count,
            "valid_count": len(questions),
            "used_single_chunks": len(batch.single_chunk_ids),
            "used_multi_chunks": len(batch.multi_chunk_ids),
            "single_mode_counts": single_mode_counts,
            "single_difficulty_counts": single_difficulty_counts,
            "multi_mode_counts": multi_mode_counts,
            "multi_difficulty_counts": multi_difficulty_counts,
        }

    def _update_evidence_usage(
        self,
        batch: GenerationBatch,
        pool: EvidencePool,
    ) -> None:
        """更新证据单元使用计数。

        Args:
            batch: 生成批次
            pool: 证据池
        """
        for unit in pool.single_chunks:
            if unit.chunk_id in batch.single_chunk_ids:
                unit.usage_count += 1

        for unit in pool.multi_chunks:
            if unit.unit_id in batch.multi_chunk_ids:
                unit.usage_count += 1

    async def _execute_next_step_plan(
        self,
        next_plan: NextStepPlan,
        plan: GenerationPlan,
    ) -> None:
        """执行下一步计划。

        Args:
            next_plan: 下一步计划
            plan: 生成计划
        """
        if next_plan.topic not in self._topic_preferences:
            self._topic_preferences[next_plan.topic] = {}

        if next_plan.action == NextStepAction.INCREASE_MULTI_CHUNK_RATIO:
            self._topic_preferences[next_plan.topic]["prefer_multi_chunk"] = True
            logger.info(f"Enabled multi-chunk preference for {next_plan.topic}")

        elif next_plan.action == NextStepAction.ENABLE_HARDENING:
            self._topic_preferences[next_plan.topic]["additional_instructions"] = next_plan.additional_instructions
            logger.info(f"Enabled hardening for {next_plan.topic}: {next_plan.reason}")

        elif next_plan.action == NextStepAction.EXPAND_RETRIEVAL:
            await self._expand_retrieval(
                next_plan.topic,
                next_plan.retrieval_expansion_queries or [next_plan.topic],
                plan
            )

    async def _expand_retrieval(
        self,
        topic: str,
        queries: list[str],
        plan: GenerationPlan,
    ) -> None:
        """扩展检索。

        Args:
            topic: 主题名称
            queries: 查询列表
            plan: 生成计划
        """
        logger.info(f"Expanding retrieval for topic {topic} with queries: {queries}")

        state = self.topic_states.get(topic)
        if not state:
            logger.warning(f"Topic state not found: {topic}")
            return

        collected_chunks: list[SourceChunk] = []

        for query in queries:
            results = search_wikipedia(
                query=query,
                language=plan.language,
                max_pages=2,
            )
            for result in results:
                document = fetch_wikipedia_page(
                    result=result,
                    run_id=plan.run_id,
                    language=plan.language,
                    content_max_length=self.config.retrieval.content_max_length,
                )
                if document.status.value == "failed":
                    continue

                chunks = chunk_document(
                    document=document,
                    chunk_size=self.config.chunking.chunk_size,
                    overlap=self.config.chunking.overlap,
                )
                summary = await self._generate_document_summary(document, chunks)
                self.document_summaries[document.document_id] = summary

                if document.document_id not in state.retrieved_documents:
                    state.retrieved_documents.append(document.document_id)

                collected_chunks.extend(chunks)

        if collected_chunks:
            # 添加新 chunks 到证据池
            new_single_units = build_evidence_pool_from_chunks(
                collected_chunks,
                topic,
                document_summary="",
            )
            pool = self.evidence_pools.get(topic)
            if pool:
                pool.single_chunks.extend(new_single_units)
                # 更新可用 chunk ids
                state.available_single_chunk_ids.extend(
                    [u.chunk_id for u in new_single_units]
                )
                # 重新构建多 chunk 单元（包含新 chunks）
                doc_summaries = {}
                for chunk in collected_chunks:
                    doc_summaries[chunk.document_id] = self.document_summaries.get(
                        chunk.document_id, ""
                    )
                new_multi_units = self.multi_chunk_builder.build_multi_chunk_units_smart(
                    new_single_units,
                    doc_summaries,
                    target_count=5,
                )
                pool.multi_chunks.extend(new_multi_units)
                state.available_multi_chunk_ids.extend(
                    [u.unit_id for u in new_multi_units]
                )

            logger.info(f"Added {len(new_single_units)} new chunks to evidence pool")

    def _has_global_gaps(self) -> bool:
        """检查是否有全局缺口。

        Returns:
            是否有缺口
        """
        for state in self.topic_states.values():
            for remaining in state.remaining_counts.values():
                if remaining > 0:
                    return True
        return False

    async def _global_backfill(self, plan: GenerationPlan) -> None:
        """全局补题阶段。

        Args:
            plan: 生成计划
        """
        logger.info("Starting global backfill phase")

        while self._has_global_gaps() and self.total_rounds < plan.max_total_rounds:
            # 使用 identify_global_gap 找出最大的模式难度缺口
            gap_key, gap_topics = identify_global_gap(self.topic_states)

            if not gap_key or not gap_topics:
                break

            # 选择第一个缺口主题
            target_topic = gap_topics[0]
            logger.info(f"Global backfill targeting {gap_key} on {target_topic}")

            # 尝试继续生成
            await self._run_generation_round(target_topic, plan)

    def _build_report(self, plan: GenerationPlan) -> GenerationReport:
        """构建生成报告。

        Args:
            plan: 生成计划

        Returns:
            生成报告
        """
        final_counts: dict[str, int] = {}
        remaining_gaps: dict[str, int] = {}

        for topic, state in self.topic_states.items():
            for key, completed in state.completed_counts.items():
                final_counts[key] = final_counts.get(key, 0) + completed

            for key, remaining in state.remaining_counts.items():
                remaining_gaps[key] = remaining_gaps.get(key, 0) + remaining

        status = "completed" if not self._has_global_gaps() else "partial"

        return GenerationReport(
            run_id=plan.run_id,
            goal=plan.goal,
            topics=plan.topics,
            mode_targets=plan.mode_targets,
            topic_states=self.topic_states,
            final_counts=final_counts,
            remaining_gaps=remaining_gaps,
            status=status,
        )

    def _save_results(self, report: GenerationReport) -> None:
        """保存结果。

        Args:
            report: 生成报告
        """
        if self.all_questions:
            self.artifact_store.append_jsonl("accepted_questions.jsonl", self.all_questions)

        # 保存主题状态
        topic_states_data = {
            k: v.model_dump() for k, v in self.topic_states.items()
        }
        self.artifact_store.save_json("topic_states.json", topic_states_data)

        # 保存证据统计
        evidence_stats_data = {
            k: v.stats.model_dump() for k, v in self.evidence_pools.items()
        }
        self.artifact_store.save_json("evidence_stats.json", evidence_stats_data)

        # 保存生成报告
        self.artifact_store.save_json("generation_report.json", report.model_dump())

        # 保存证据池
        for topic, pool in self.evidence_pools.items():
            # 保存单 chunk
            for chunk in pool.single_chunks:
                self.artifact_store.append_jsonl(
                    f"single_chunk_pool_{topic}.jsonl",
                    [chunk.model_dump()],
                )

            # 保存多 chunk
            for unit in pool.multi_chunks:
                self.artifact_store.append_jsonl(
                    f"multi_chunk_pool_{topic}.jsonl",
                    [unit.model_dump()],
                )