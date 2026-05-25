"""ActionExecutor 模块：薄封装执行层。

职责：
- action → 调用对应模块方法
- 不做决策，只执行

映射关系：
expand_retrieval → EvidenceManager.expand()
enable_multi_chunk → TopicState.prefer_multi_chunk = True
continue_generation → EvidenceManager.sample() → Generator.generate() → Validator.validate()
finish_topic → TopicState.status = COMPLETED
defer_topic → TopicState.status = DEFERRED
"""

from typing import Any
from dataclasses import dataclass


@dataclass
class ActionResult:
    """动作执行结果。"""
    success: bool
    error: str | None = None
    output: dict[str, Any] = None

    def __post_init__(self):
        if self.output is None:
            self.output = {}


class ActionExecutor:
    """动作执行器（薄封装）。

    职责：
    - 将动作路由到对应模块
    - 不做决策，只执行
    """

    def __init__(
        self,
        evidence_manager: Any,
        generator: Any,
        validator: Any,
    ):
        """初始化执行器。

        Args:
            evidence_manager: 证据管理器
            generator: 生成器
            validator: 验证器
        """
        self.evidence_manager = evidence_manager
        self.generator = generator
        self.validator = validator

    async def execute(
        self,
        decision: Any,
        context: dict[str, Any],
    ) -> ActionResult:
        """执行决策。

        Args:
            decision: 控制决策
            context: 执行上下文 {
                topic: str,
                planner: Planner,
                evidence_pool: EvidencePool,
                model_client: BaseModelClient,
                run_id: str,
                language: str,
                round_num: int,
                state: AgentRuntimeState,
            }

        Returns:
            执行结果
        """
        action = decision.action
        params = decision.params

        try:
            if action == "finish_topic":
                result = await self._execute_finish_topic(context, params)
            elif action == "expand_retrieval":
                result = await self._execute_expand_retrieval(context, params)
            elif action == "enable_multi_chunk":
                result = self._execute_enable_multi_chunk(context, params)
            elif action == "continue_generation":
                result = await self._execute_continue_generation(context, params)
            elif action == "defer_topic":
                result = self._execute_defer_topic(context, params)
            else:
                result = ActionResult(
                    success=False,
                    error=f"unknown action: {action}",
                )

        except Exception as e:
            result = ActionResult(
                success=False,
                error=str(e),
            )

        return result

    async def _execute_finish_topic(
        self,
        context: dict[str, Any],
        params: dict[str, Any],
    ) -> ActionResult:
        """执行 finish_topic。"""
        from benchforge.schemas import TopicStatus

        topic = params.get("topic", "")
        planner = context.get("planner")

        if not planner:
            return ActionResult(success=False, error="planner not found in context")

        state = planner.topic_states.get(topic)
        if not state:
            return ActionResult(success=False, error=f"topic state not found: {topic}")

        state.status = TopicStatus.COMPLETED

        return ActionResult(success=True, output={"topic": topic, "status": "completed"})

    async def _execute_expand_retrieval(
        self,
        context: dict[str, Any],
        params: dict[str, Any],
    ) -> ActionResult:
        """执行 expand_retrieval。"""
        topic = params.get("topic", "")
        queries = params.get("queries", [topic])
        language = context.get("language", "en")
        run_id = context.get("run_id", "")
        evidence_pool = context.get("evidence_pool")

        # 调用 evidence_manager
        expand_result = await self.evidence_manager.expand_retrieval(
            topic=topic,
            queries=queries,
            language=language,
            run_id=run_id,
            evidence_pool=evidence_pool,
        )

        return ActionResult(
            success=True,
            output={
                "topic": topic,
                "new_chunks": expand_result.new_chunks,
                "new_single_units": expand_result.new_single_units,
                "new_multi_units": expand_result.new_multi_units,
            },
        )

    def _execute_enable_multi_chunk(
        self,
        context: dict[str, Any],
        params: dict[str, Any],
    ) -> ActionResult:
        """执行 enable_multi_chunk。"""
        topic = params.get("topic", "")
        planner = context.get("planner")

        if not planner:
            return ActionResult(success=False, error="planner not found in context")

        state = planner.topic_states.get(topic)
        if not state:
            return ActionResult(success=False, error=f"topic state not found: {topic}")

        # 在 state 中标记偏好多 chunk
        state.prefer_multi_chunk = True

        return ActionResult(success=True, output={"topic": topic, "prefer_multi_chunk": True})

    async def _execute_continue_generation(
        self,
        context: dict[str, Any],
        params: dict[str, Any],
    ) -> ActionResult:
        """执行 continue_generation。

        步骤：
        1. 采样证据
        2. 生成题目
        3. 验证题目
        4. 返回结果
        """
        topic = params.get("topic", "")
        gap_key = params.get("gap_key", "")
        target_mode = params.get("target_mode", "qa")
        target_difficulty = params.get("target_difficulty", "medium")
        remaining = params.get("remaining", 1)

        evidence_pool = context.get("evidence_pool")
        model_client = context.get("model_client")
        language = context.get("language", "en")
        round_num = context.get("round_num", 1)
        planner = context.get("planner")

        # 1. 采样证据
        batch = self.evidence_manager.sample(
            evidence_pool=evidence_pool,
            topic=topic,
            target_mode=target_mode,
            target_difficulty=target_difficulty,
            prefer_multi_chunk=self._get_prefer_multi_chunk(topic, planner),
            round_num=round_num,
            remaining=remaining,
        )

        # 2. 获取文档摘要
        document_summary = self.evidence_manager.get_document_summary(batch, evidence_pool)

        # 3. 生成题目
        questions, raw_candidate_count = await self.generator.generate(
            batch=batch,
            model_client=model_client,
            evidence_pool=evidence_pool,
            document_summary=document_summary,
            language=language,
        )

        # 4. 验证题目
        validated_questions, num_rejected = self.validator.validate_questions(
            questions=questions,
        )

        # 5. 统计完成计数
        completed_counts = self._count_by_key(validated_questions)

        return ActionResult(
            success=True,
            output={
                "topic": topic,
                "gap_key": gap_key,
                "num_candidates": raw_candidate_count,
                "num_accepted": len(validated_questions),
                "num_rejected": num_rejected,
                "questions": validated_questions,
                "completed_counts": completed_counts,
            },
        )

    def _execute_defer_topic(
        self,
        context: dict[str, Any],
        params: dict[str, Any],
    ) -> ActionResult:
        """执行 defer_topic。"""
        from benchforge.schemas import TopicStatus

        topic = params.get("topic", "")
        planner = context.get("planner")

        if not planner:
            return ActionResult(success=False, error="planner not found in context")

        state = planner.topic_states.get(topic)
        if not state:
            return ActionResult(success=False, error=f"topic state not found: {topic}")

        state.status = TopicStatus.DEFERRED

        return ActionResult(success=True, output={"topic": topic, "status": "deferred"})

    def _get_prefer_multi_chunk(self, topic: str, planner: Any) -> bool:
        """获取主题是否偏好多 chunk。"""
        if not planner:
            return False

        state = planner.topic_states.get(topic)
        if not state:
            return False

        return getattr(state, "prefer_multi_chunk", False)

    def _count_by_key(self, questions: list[dict[str, Any]]) -> dict[str, int]:
        """统计题目完成计数。"""
        counts: dict[str, int] = {}

        for q in questions:
            mode = q.get("question_mode", "qa")
            diff = self._normalize_difficulty(q.get("estimated_difficulty", "medium"))
            key = f"{mode}:{diff}"
            counts[key] = counts.get(key, 0) + 1

        return counts

    def _normalize_difficulty(self, diff: Any) -> str:
        """标准化难度。"""
        if isinstance(diff, int):
            if diff <= 3:
                return "easy"
            elif diff <= 7:
                return "medium"
            else:
                return "hard"
        return str(diff).lower()