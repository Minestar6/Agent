"""Validator 模块：解析、过滤、去重、状态更新。"""

from typing import Any


class Validator:
    """题目验证器。

    职责：
    - 解析 LLM 响应
    - 过滤无效题目
    - 去重
    - 统计完成计数
    """

    def __init__(self):
        """初始化验证器。"""
        pass

    def validate_questions(
        self,
        questions: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        """验证题目。

        Args:
            questions: 候选题目列表

        Returns:
            (有效题目列表, 拒绝数量)
        """
        valid_questions = []

        for q in questions:
            if self._is_valid(q):
                valid_questions.append(q)

        num_rejected = len(questions) - len(valid_questions)

        return valid_questions, num_rejected

    def _is_valid(self, question: dict[str, Any]) -> bool:
        """检查单个题目是否有效。

        验证规则：
        1. 必须有 question 字段
        2. question 长度 > 10
        3. 必须有 answer 字段

        Args:
            question: 题目字典

        Returns:
            是否有效
        """
        # 规则 1: 必须有 question 字段
        if "question" not in question:
            return False

        # 规则 2: question 长度 > 10
        if len(question["question"]) < 10:
            return False

        # 规则 3: 必须有 answer 字段
        if "answer" not in question:
            return False

        return True

    def apply_result(
        self,
        result: Any,
        planner: Any,
        state: Any,
    ) -> None:
        """应用执行结果到状态。

        Args:
            result: 执行结果
            planner: Planner 实例
            state: 当前状态
        """
        if not result.success:
            return

        output = result.output
        questions = output.get("questions", [])
        topic = output.get("topic", "")
        completed_counts = output.get("completed_counts", {})

        # 更新 planner 状态
        if topic and completed_counts:
            planner.update_state(topic, completed_counts)

        # 更新 accepted 计数
        state.accepted_count = state.accepted_count + len(questions)