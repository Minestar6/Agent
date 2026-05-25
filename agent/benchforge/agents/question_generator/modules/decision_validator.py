"""DecisionValidator 模块：验证动作合法性。"""

from typing import Any

from benchforge.schemas import ControlDecision, Observation


class DecisionValidator:
    """决策验证器。

    职责：
    - 检查动作是否合法
    - 检查是否越界
    - 检查是否重复无效

    验证规则：
    1. 动作必须在允许列表中
    2. 轮数不能超过最大值（已由 Scheduler 处理）
    3. finish_topic 必须在所有缺口填满后
    """

    VALID_ACTIONS = {
        "finish_topic",
        "expand_retrieval",
        "enable_multi_chunk",
        "continue_generation",
        "defer_topic",
    }

    def validate(
        self,
        decision: ControlDecision,
        observation: Observation,
    ) -> list[str]:
        """验证决策。

        Args:
            decision: 控制决策
            observation: 观察摘要

        Returns:
            问题列表（空表示验证通过）
        """
        issues = []

        # 规则 1: 动作合法性
        if decision.action not in self.VALID_ACTIONS:
            issues.append(
                f"invalid action: '{decision.action}', must be one of {self.VALID_ACTIONS}"
            )

        # 规则 2: finish_topic 必须在所有缺口填满后
        if decision.action == "finish_topic" and observation.main_gap is not None:
            issues.append(
                f"finish_topic called but gap remains: '{observation.main_gap.key}'"
            )

        # 规则 3: defer_topic 只能在达到最大轮数后
        if decision.action == "defer_topic":
            if observation.round_num < observation.max_rounds:
                issues.append(
                    f"defer_topic called at round {observation.round_num}, "
                    f"but max_rounds is {observation.max_rounds}"
                )

        return issues

    def is_valid(self, issues: list[str]) -> bool:
        """检查是否有效（无严重错误）。

        Args:
            issues: 问题列表

        Returns:
            是否有效
        """
        return len(issues) == 0