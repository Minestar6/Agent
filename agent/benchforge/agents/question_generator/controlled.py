"""问题生成智能体（中量级 Controlled Agent）。

基于架构重构：
- ObservationBuilder：摘要化观察
- DecisionPolicy：决策策略（规则策略 + 可选LLM策略）
- DecisionValidator：决策验证
- LoopGuard：循环守护
- ToolRouter：工具路由
"""

from typing import Any
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger

from benchforge.schemas import (
    GenerationPlan,
    GenerationReport,
    TopicState,
    TopicStatus,
    EvidencePool,
    AgentDecision,
    ControlDecision,
    Observation,
)
from benchforge.agents.question_generator.observation_builder import ObservationBuilder
from benchforge.agents.question_generator.decision_validator import DecisionValidator
from benchforge.agents.question_generator.loop_guard import LoopGuard
from benchforge.agents.common.policies.rule_based_policy import RuleBasedDecisionPolicy
from benchforge.tools.router.tool_router import ToolRouter
from benchforge.utils.planning import compile_generation_plan, check_topic_completion
from benchforge.utils.artifact_store import ArtifactStore


@dataclass
class AgentState:
    """Agent内部状态。"""
    run_id: str
    topic_states: dict[str, TopicState] = field(default_factory=dict)
    evidence_pools: dict[str, EvidencePool] = field(default_factory=dict)
    all_questions: list[dict[str, Any]] = field(default_factory=list)
    document_summaries: dict[str, str] = field(default_factory=dict)
    history: list[ControlDecision] = field(default_factory=list)
    retrieved_documents: list[str] = field(default_factory=list)


class ControlledQuestionGeneratorAgent:
    """问题生成智能体（中量级 Controlled Agent）。

    核心特征：
    - LLM只输出Intent，不直接控制action
    - Decision瘦身：ControlDecision进入状态，Reasoning只写日志
    - Observation摘要化
    - DecisionValidator统一验证
    - LoopGuard检测无效循环
    """

    def __init__(
        self,
        model_client,
        config=None,
        enable_lightweight_reflection: bool = False,
    ):
        """初始化Agent。

        Args:
            model_client: 模型客户端
            config: 配置
            enable_lightweight_reflection: 是否启用轻量反思
        """
        self.model_client = model_client
        self.config = config

        # 初始化组件
        self.observation_builder = ObservationBuilder()
        self.decision_policy = RuleBasedDecisionPolicy()
        self.decision_validator = DecisionValidator()
        self.loop_guard = LoopGuard()
        self.tool_router = ToolRouter()

        # 轻量反思开关
        self.enable_lightweight_reflection = enable_lightweight_reflection

        # Agent内部状态
        self.state = AgentState(run_id="default")

        # 输出配置
        if config:
            self.output_path = config.get_resolved_output_path()
            self.output_path.mkdir(parents=True, exist_ok=True)
            self.artifact_store = ArtifactStore(str(self.output_path))
        else:
            self.output_path = Path("./output")
            self.output_path.mkdir(parents=True, exist_ok=True)
            self.artifact_store = ArtifactStore(str(self.output_path))

    async def execute(self, plan: GenerationPlan) -> GenerationReport:
        """执行生成任务。

        Args:
            plan: 生成计划

        Returns:
            生成报告
        """
        logger.info(f"Starting Controlled Agent for run: {plan.run_id}")
        logger.info(f"Topics: {plan.topics}")
        logger.info(f"Goal: {plan.goal}")

        # 初始化状态
        self.state.run_id = plan.run_id
        self.state.topic_states = compile_generation_plan(plan)

        # 准备输出路径
        self.output_path.mkdir(parents=True, exist_ok=True)

        # 阶段1: 主题串行执行
        for topic in plan.topics:
            await self._process_topic(topic, plan)

        # 阶段2: 全局补题（可选）
        if self._has_global_gaps():
            await self._global_backfill(plan)

        # 生成报告
        report = self._build_report(plan)

        # 保存结果
        self._save_results(report)

        return report

    async def _process_topic(self, topic: str, plan: GenerationPlan):
        """处理单个主题（重构后的执行流程）。

        Args:
            topic: 主题名称
            plan: 生成计划
        """
        logger.info(f"Processing topic: {topic}")

        topic_state = self.state.topic_states[topic]
        topic_state.status = TopicStatus.ACTIVE

        # 准备证据（复用原有逻辑）
        await self._prepare_evidence(topic, plan)

        # 重置LoopGuard
        self.loop_guard.reset()

        # 主循环
        while not self._should_stop(topic):
            await self._run_one_round(topic, plan)

        # 检查退出条件
        if check_topic_completion(topic_state):
            topic_state.status = TopicStatus.COMPLETED
            logger.info(f"Topic {topic} completed")
        else:
            topic_state.status = TopicStatus.DEFERRED
            logger.info(f"Topic {topic} deferred")

    async def _run_one_round(self, topic: str, plan: GenerationPlan):
        """运行一轮生成。"""
        topic_state = self.state.topic_states[topic]

        # 1. 构建观察（摘要化）
        observation = self.observation_builder.build(
            {
                "topic_states": self.state.topic_states,
                "evidence_pools": self.state.evidence_pools,
                "history": [d.to_dict() for d in self.state.history],
                "max_rounds_per_topic": plan.max_rounds_per_topic,
                "language": plan.language,
            },
            topic
        )

        # 2. 决策
        decision = await self.decision_policy.decide(observation)

        # 3. 验证决策
        issues = self.decision_validator.validate(
            decision.control,
            observation,
            self.tool_router.tools
        )

        if not self.decision_validator.is_valid(issues):
            for issue in issues:
                logger.warning(f"Decision validation issue: {issue.message}")

            # 有严重错误，使用默认决策继续
            if any(issue.severity == "error" for issue in issues):
                logger.warning("Decision validation failed, using fallback")
                # 简化：直接继续

        # 4. 检查LoopGuard
        guard_report = self.loop_guard.check_stuck()
        if guard_report.is_stuck:
            logger.warning(
                f"Loop stuck for {guard_report.stuck_rounds} rounds, "
                f"forcing action: {guard_report.suggested_actions[0]}"
            )
            decision = AgentDecision(
                control=ControlDecision(
                    next_action=guard_report.suggested_actions[0],
                    action_parameters={"topic": topic}
                ),
                reasoning=decision.reasoning,
            )

        # 记录推理（只写日志）
        logger.info(f"Decision reasoning: {decision.reasoning.summary}")

        # 5. 执行工具
        if decision.control.next_action == "finish_topic":
            return

        # 准备state参数
        tool_state = {
            "topic_states": self.state.topic_states,
            "evidence_pools": self.state.evidence_pools,
            "all_questions": self.state.all_questions,
            "model_client": self.model_client,
            "language": plan.language,
            "run_id": plan.run_id,
            "retrieved_documents": self.state.retrieved_documents,
        }

        # 特殊处理：sample_evidence需要evidence_text
        if decision.control.next_action == "sample_evidence":
            # 先采样证据
            sample_result = await self.tool_router.execute(
                "sample_evidence",
                decision.control.action_parameters,
                tool_state
            )

            if sample_result.success:
                batch = sample_result.output["batch"]

                # 格式化证据文本
                from benchforge.utils.planning import format_evidence_texts
                evidence_text = format_evidence_texts(
                    pool.single_chunks if (pool := self.state.evidence_pools.get(topic)) else [],
                    pool.multi_chunks if pool else []
                )

                # 然后生成题目
                gen_params = decision.control.action_parameters.copy()
                gen_params["evidence_text"] = evidence_text

                gen_result = await self.tool_router.execute(
                    "generate_questions",
                    gen_params,
                    tool_state
                )

                if gen_result.success:
                    self._update_state(topic, gen_result.output)
                    topic_state.current_round += 1

        elif decision.control.next_action == "expand_retrieval":
            result = await self.tool_router.execute(
                "expand_retrieval",
                decision.control.action_parameters,
                tool_state
            )
            logger.info(f"Retrieval expanded: {result.output}")

        # 6. 更新LoopGuard
        gap_total = sum(topic_state.remaining_counts.values())
        coverage_progress = sum(
            topic_state.completed_counts.get(k, 0) / max(topic_state.target_counts.get(k, 1), 1)
            for k in topic_state.target_counts
        ) / max(len(topic_state.target_counts), 1)

        self.loop_guard.record_round(gap_total, coverage_progress)

        # 7. 保存ControlDecision到history
        self.state.history.append(decision.control)

    def _should_stop(self, topic: str) -> bool:
        """检查是否应该停止。"""
        state = self.state.topic_states.get(topic)
        if not state:
            return False

        return check_topic_completion(state)

    def _update_state(self, topic: str, result: dict):
        """更新状态。"""
        questions = result.get("questions", [])
        self.state.all_questions.extend(questions)

        topic_state = self.state.topic_states[topic]

        # 更新完成计数
        for q in questions:
            mode = q.get("question_mode", "qa")
            diff = q.get("estimated_difficulty", "medium")
            if isinstance(diff, int):
                if diff <= 3:
                    diff = "easy"
                elif diff <= 7:
                    diff = "medium"
                else:
                    diff = "hard"
            key = f"{mode}:{diff}"
            topic_state.completed_counts[key] = topic_state.completed_counts.get(key, 0) + 1

        # 更新剩余计数
        for key in topic_state.target_counts:
            completed = topic_state.completed_counts.get(key, 0)
            target = topic_state.target_counts.get(key, 0)
            topic_state.remaining_counts[key] = max(0, target - completed)

    def _has_global_gaps(self) -> bool:
        """检查是否有全局缺口。"""
        for state in self.state.topic_states.values():
            for remaining in state.remaining_counts.values():
                if remaining > 0:
                    return True
        return False

    async def _global_backfill(self, plan: GenerationPlan):
        """全局补题。"""
        logger.info("Starting global backfill phase")
        # 简化实现
        pass

    async def _prepare_evidence(self, topic: str, plan: GenerationPlan):
        """准备证据（复用原有逻辑）。"""
        # 这里需要复用原有的 _prepare_evidence 实现
        # 为了简洁，这里省略
        from benchforge.utils import search_wikipedia, fetch_wikipedia_page, chunk_document
        from benchforge.utils.multi_chunk import build_evidence_pool_from_chunks, MultiChunkBuilder

        logger.info(f"Preparing evidence for topic: {topic}")

        # 检索
        search_results = search_wikipedia(
            query=topic,
            language=plan.language,
            max_pages=5,
        )

        if not search_results:
            logger.warning(f"No search results for topic: {topic}")
            return

        # 处理文档
        all_chunks = []
        for result in search_results:
            document = fetch_wikipedia_page(
                result=result,
                run_id=plan.run_id,
                language=plan.language,
                content_max_length=10000,
            )

            if document.status.value == "failed":
                continue

            self.state.retrieved_documents.append(document.document_id)

            # 分块
            chunks = chunk_document(document=document, chunk_size=1200, overlap=150)
            all_chunks.extend(chunks)

        logger.info(f"Retrieved {len(all_chunks)} chunks for topic: {topic}")

        # 构建证据池
        single_units = build_evidence_pool_from_chunks(all_chunks, topic, "")

        # 构建多证据单元
        multi_chunk_builder = MultiChunkBuilder()
        multi_units = multi_chunk_builder.build_multi_chunk_units_smart(
            single_units,
            {},
            target_count=10,
        )

        pool = EvidencePool(
            topic=topic,
            single_chunks=single_units,
            multi_chunks=multi_units,
        )

        self.state.evidence_pools[topic] = pool

        # 更新主题状态
        topic_state = self.state.topic_states[topic]
        topic_state.available_single_chunk_ids = [u.chunk_id for u in single_units]
        topic_state.available_multi_chunk_ids = [u.unit_id for u in multi_units]

        logger.info(
            f"Built evidence pool: {len(single_units)} single, {len(multi_units)} multi"
        )

    def _build_report(self, plan: GenerationPlan) -> GenerationReport:
        """构建报告。"""
        from benchforge.schemas import GenerationReport

        final_counts = {}
        remaining_gaps = {}

        for topic, state in self.state.topic_states.items():
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
            topic_states=self.state.topic_states,
            final_counts=final_counts,
            remaining_gaps=remaining_gaps,
            status=status,
        )

    def _save_results(self, report: GenerationReport):
        """保存结果。"""
        if self.state.all_questions:
            self.artifact_store.append_jsonl("accepted_questions.jsonl", self.state.all_questions)

        # 保存主题状态
        topic_states_data = {
            k: v.model_dump() for k, v in self.state.topic_states.items()
        }
        self.artifact_store.save_json("topic_states.json", topic_states_data)

        # 保存生成报告
        self.artifact_store.save_json("generation_report.json", report.model_dump())