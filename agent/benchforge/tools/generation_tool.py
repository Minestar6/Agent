"""生成工具。"""

from typing import Any

from benchforge.tools.base_tool import BaseTool, ToolSpec, ToolResult
from benchforge.utils.filter import parse_llm_response, LightweightFilter


class GenerationTool(BaseTool):
    """生成工具。"""

    def __init__(self, model_client=None):
        """初始化。"""
        super().__init__()
        self.model_client = model_client
        self.filter = LightweightFilter()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="generate_questions",
            description="调用LLM生成题目",
            input_schema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "主题名称"},
                    "target_mode": {
                        "type": "string",
                        "enum": ["qa", "multiple_choice"],
                        "description": "目标模式"
                    },
                    "target_difficulty": {
                        "type": "string",
                        "enum": ["easy", "medium", "hard"],
                        "description": "目标难度"
                    },
                    "requested_questions": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "description": "请求数量"
                    },
                    "evidence_text": {"type": "string", "description": "证据文本"},
                    "temperature": {
                        "type": "number",
                        "default": 0.7,
                        "description": "温度参数"
                    },
                },
                "required": [
                    "topic",
                    "target_mode",
                    "target_difficulty",
                    "requested_questions",
                    "evidence_text"
                ],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "requested_count": {"type": "integer"},
                    "raw_count": {"type": "integer"},
                    "valid_count": {"type": "integer"},
                    "valid_rate": {"type": "number"},
                    "questions": {"type": "array"},
                },
            },
            retryable=True,
            max_retries=2,
            timeout=120,
        )

    async def execute(self, parameters: dict[str, Any], state: dict[str, Any]) -> ToolResult:
        """执行生成。

        Args:
            parameters: 输入参数
            state: 当前状态

        Returns:
            执行结果
        """
        if not self.model_client:
            # 从state获取model_client
            self.model_client = state.get("model_client")
            if not self.model_client:
                return ToolResult(
                    success=False,
                    output={},
                    error="No model client available"
                )

        topic = parameters["topic"]
        target_mode = parameters["target_mode"]
        target_difficulty = parameters["target_difficulty"]
        requested_questions = parameters["requested_questions"]
        evidence_text = parameters["evidence_text"]
        temperature = parameters.get("temperature", 0.7)

        # 构建system prompt
        system_prompt = self._load_system_prompt(target_mode)

        # 构建user prompt
        user_prompt = self._build_user_prompt(
            topic,
            target_mode,
            target_difficulty,
            requested_questions,
            evidence_text
        )

        try:
            # 调用LLM
            response = await self.model_client.complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=2000,
            )

            # 解析响应
            raw_questions = parse_llm_response(response["text"])

            # 过滤题目
            passed, _ = self.filter.filter_questions(raw_questions)

            # 计算有效率
            valid_rate = len(passed) / len(raw_questions) if raw_questions else 0

            return ToolResult(
                success=True,
                output={
                    "requested_count": requested_questions,
                    "raw_count": len(raw_questions),
                    "valid_count": len(passed),
                    "valid_rate": valid_rate,
                    "questions": passed,
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output={},
                error=f"Generation failed: {e}"
            )

    def _load_system_prompt(self, mode: str) -> str:
        """加载system prompt。"""
        prompt_files = {
            "multiple_choice": "prompts/question_generator/mcq_system_prompt.md",
            "qa": "prompts/question_generator/qa_system_prompt.md",
        }

        prompt_file = prompt_files.get(mode, "prompts/question_generator/qa_system_prompt.md")

        try:
            from pathlib import Path
            prompt_path = Path(__file__).parent.parent.parent / prompt_file
            if prompt_path.exists():
                with open(prompt_path, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception:
            pass

        # 默认prompt
        if mode == "multiple_choice":
            return "You are a document comprehension specialist who creates insightful multiple-choice questions."
        else:
            return "You are a document comprehension specialist who creates insightful question-answer pairs."

    def _build_user_prompt(
        self,
        topic: str,
        target_mode: str,
        target_difficulty: str,
        requested_questions: int,
        evidence_text: str
    ) -> str:
        """构建user prompt。"""
        difficulty_requirements = {
            "easy": "Focus on basic recall and surface comprehension.",
            "medium": "Focus on application, analysis, and synthesis.",
            "hard": "Focus on deep insights, connections, and expert-level understanding.",
        }

        user_prompt = f"""Generate {requested_questions} {target_difficulty} {target_mode} questions about: {topic}

Difficulty requirements:
{difficulty_requirements[target_difficulty]}

Evidence:
<text_chunk>
{evidence_text}
</text_chunk>

Please output the questions in JSON format, each with:
- question
- answer
- question_mode: "{target_mode}"
- estimated_difficulty: "{target_difficulty}"
- citations: [{"text": "...", "chunk_id": "..."}]
"""

        return user_prompt