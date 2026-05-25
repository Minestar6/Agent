"""决策验证器：验证决策的合法性（代码实现）。"""

from dataclasses import dataclass
from typing import Any

from benchforge.schemas import ControlDecision, Observation


@dataclass
class ValidationIssue:
    """验证问题。"""
    severity: str  # "error" | "warning"
    field: str
    message: str


class DecisionValidator:
    """决策验证器（纯代码实现，确定性）。

    检查：
    1. action是否存在
    2. 参数是否符合schema
    3. target_gap是否真的存在
    4. requested_questions是否超限
    5. 是否会导致无效循环
    """

    MAX_REQUESTED_QUESTIONS = 20  # 最大请求数

    def validate(
        self,
        decision: ControlDecision,
        observation: Observation,
        tool_registry: dict[str, Any]
    ) -> list[ValidationIssue]:
        """验证决策。

        Args:
            decision: 控制决策
            observation: 观察
            tool_registry: 工具注册表

        Returns:
            验证问题列表
        """
        issues = []

        # 1. 检查action是否存在
        if decision.next_action not in tool_registry:
            issues.append(ValidationIssue(
                severity="error",
                field="next_action",
                message=f"Unknown action: {decision.next_action}"
            ))

        # 2. 检查参数是否符合schema
        if decision.next_action in tool_registry:
            tool = tool_registry[decision.next_action]
            # 调用工具的validate_input方法
            if hasattr(tool, "validate_input"):
                if not tool.validate_input(decision.action_parameters):
                    issues.append(ValidationIssue(
                        severity="error",
                        field="action_parameters",
                        message="Input validation failed"
                    ))

        # 3. 检查target_gap是否真的存在
        target_gap = decision.action_parameters.get("target_gap")
        if target_gap:
            # target_gap格式应该是 "qa:hard"
            # 检查是否在observation.gaps中
            # 但Observation没有直接提供gaps字典，需要从其他方式获取
            # 这里简化处理：只检查格式是否正确
            if not self._is_valid_gap_format(target_gap):
                issues.append(ValidationIssue(
                    severity="warning",
                    field="target_gap",
                    message=f"Invalid gap format: {target_gap}, expected format: mode:difficulty"
                ))

        # 4. 检查requested_questions是否超限
        requested = decision.action_parameters.get("requested_questions", 0)
        if requested > self.MAX_REQUESTED_QUESTIONS:
            issues.append(ValidationIssue(
                severity="warning",
                field="requested_questions",
                message=f"Requested {requested} questions exceeds max {self.MAX_REQUESTED_QUESTIONS}"
            ))

        # 5. 检查是否会导致无效循环
        if decision.next_action == "generate_questions":
            requested = decision.action_parameters.get("requested_questions", 0)
            if requested <= 0:
                issues.append(ValidationIssue(
                    severity="warning",
                    field="requested_questions",
                    message="Zero requested questions may cause ineffective loop"
                ))

        return issues

    def is_valid(self, issues: list[ValidationIssue]) -> bool:
        """是否有严重错误。

        Args:
            issues: 验证问题列表

        Returns:
            是否有效（无严重错误）
        """
        return all(issue.severity != "error" for issue in issues)

    def _is_valid_gap_format(self, gap: str) -> bool:
        """检查gap格式是否有效。

        Args:
            gap: 缺口字符串

        Returns:
            是否有效
        """
        if not gap:
            return False

        parts = gap.split(":")
        if len(parts) != 2:
            return False

        mode, difficulty = parts

        valid_modes = ["qa", "multiple_choice"]
        valid_difficulties = ["easy", "medium", "hard"]

        return mode in valid_modes and difficulty in valid_difficulties