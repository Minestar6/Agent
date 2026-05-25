"""Generator 模块：prompt 拼接、LLM 调用。"""

from typing import Any
from pathlib import Path

from benchforge.utils.filter import parse_llm_response
from benchforge.utils.planning import format_evidence_texts


class Generator:
    """题目生成器。

    职责：
    - 拼接 prompt（支持系统 prompt + 用户 prompt）
    - 调用 LLM
    - 解析响应
    """

    def __init__(self):
        """初始化生成器。"""
        pass

    async def generate(
        self,
        batch: Any,
        model_client: Any,
        evidence_pool: Any,
        document_summary: str,
        language: str = "en",
    ) -> tuple[list[dict[str, Any]], int]:
        """生成题目。

        使用 yourbench 风格的 prompt 模板。

        Args:
            batch: 生成批次
            model_client: 模型客户端
            evidence_pool: 证据池
            document_summary: 文档摘要
            language: 语言

        Returns:
            (有效题目列表, 原始候选数量)
        """
        # 获取证据单元
        single_units = [
            u for u in evidence_pool.single_chunks
            if u.chunk_id in batch.single_chunk_ids
        ]
        multi_units = [
            u for u in evidence_pool.multi_chunks
            if u.unit_id in batch.multi_chunk_ids
        ]

        # 格式化证据文本
        evidence_text = format_evidence_texts(single_units, multi_units)

        # 构建 system prompt
        system_prompt = self._load_system_prompt(batch.target_mode)

        # 构建 user prompt
        user_prompt = self._build_user_prompt(
            batch=batch,
            document_summary=document_summary,
            evidence_text=evidence_text,
            language=language,
        )

        # 调用 LLM
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

        return raw_items, len(raw_items)

    def _load_system_prompt(self, mode: str) -> str:
        """从文件加载系统 prompt。

        Args:
            mode: 模式

        Returns:
            系统 prompt
        """
        prompt_files = {
            "multiple_choice": "prompts/question_generator/mcq_system_prompt.md",
            "qa": "prompts/question_generator/qa_system_prompt.md",
        }

        prompt_file = prompt_files.get(mode, "prompts/question_generator/qa_system_prompt.md")
        # 路径：benchforge/agents/question_generator/plan_driven.py → benchforge/prompts/
        prompt_path = Path(__file__).parent.parent.parent.parent / prompt_file

        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            if mode == "multiple_choice":
                return "You are a document comprehension specialist who creates insightful multiple-choice questions."
            else:
                return "You are a document comprehension specialist who creates insightful question-answer pairs."

    def _build_user_prompt(
        self,
        batch: Any,
        document_summary: str,
        evidence_text: str,
        language: str,
    ) -> str:
        """构建用户 prompt。

        从文件加载模板，然后填充参数。

        Args:
            batch: 生成批次
            document_summary: 文档摘要
            evidence_text: 证据文本
            language: 语言

        Returns:
            用户 prompt
        """
        prompt_files = {
            "multiple_choice": "prompts/question_generator/mcq_user_prompt.md",
            "qa": "prompts/question_generator/qa_user_prompt.md",
        }

        prompt_file = prompt_files.get(batch.target_mode, "prompts/question_generator/qa_user_prompt.md")
        prompt_path = Path(__file__).parent.parent.parent.parent / prompt_file

        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                template = f.read()
        else:
            # 默认模板
            template = (
                "<additional_instructions>\n{additional_instructions}\n</additional_instructions>\n\n"
                "<title>\n{doc_title}\n</title>\n\n"
                "<document_summary>\n{doc_summary}\n</document_summary>\n\n"
                "<text_chunk>\n{evidence_text}\n</text_chunk>\n\n"
                "Generate {requested_target_questions} questions."
            )

        # 难度要求
        difficulty_requirements = {
            "easy": "Focus on basic recall and surface comprehension - answers should be directly found in the text.",
            "medium": "Focus on application, analysis, and synthesis - needs some reasoning to connect concepts.",
            "hard": "Focus on deep insights, connections, and expert-level understanding - requires multi-step reasoning.",
        }
        difficulty_req = difficulty_requirements.get(batch.target_difficulty, "")

        additional_instructions = f"Difficulty: {batch.target_difficulty}\n{difficulty_req}"

        return template.format(
            additional_instructions=additional_instructions,
            doc_title=batch.topic,
            doc_summary=document_summary,
            evidence_text=evidence_text,
            requested_target_questions=batch.requested_target_questions,
        )