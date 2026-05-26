"""LoopGuard 模块：防止无进展循环。"""

from typing import Any


class LoopGuard:
    """循环守护器。

    职责：
    - 检测无进展循环
    - 提供分级 fallback 建议

    触发条件：
    连续 N 轮：
      gap_total 没减少
      且 accepted_count = 0

    N 默认为 3

    Fallback 策略（由 Scheduler 实现）:
    第 1 次: expand_retrieval（扩展检索）
    第 2 次: enable_multi_chunk（启用多 chunk）
    第 3 次: defer_gap（跳过缺口）
    """

    def __init__(self, stuck_threshold: int = 3):
        """初始化守护器。

        Args:
            stuck_threshold: 卡死检测阈值（轮数）
        """
        self.stuck_threshold = stuck_threshold
        self.gap_history: list[int] = []
        self.accepted_history: list[int] = []

    def reset(self) -> None:
        """重置守护器状态。"""
        self.gap_history = []
        self.accepted_history = []

    def record_round(
        self,
        gap_total: int,
        accepted_count: int,
    ) -> None:
        """记录一轮的状态。

        Args:
            gap_total: 当前 gap 总数
            accepted_count: 本轮接受的题目数量
        """
        self.gap_history.append(gap_total)
        self.accepted_history.append(accepted_count)

    def check(self, observation: Any) -> Any:
        """检查是否卡死。

        Args:
            observation: 观察摘要（未使用，但保持接口一致）

        Returns:
            守护报告
        """
        from benchforge.schemas import GuardReport

        if len(self.gap_history) < self.stuck_threshold:
            return GuardReport(
                is_stuck=False,
                stuck_rounds=0,
                suggested_actions=[],
                reason="",
            )

        recent_gaps = self.gap_history[-self.stuck_threshold:]
        recent_accepted = self.accepted_history[-self.stuck_threshold:]

        # 检查条件：gap 没减少 且 accepted_count = 0
        gap_not_decreased = all(g == recent_gaps[0] for g in recent_gaps)
        no_accepted = all(a == 0 for a in recent_accepted)

        if gap_not_decreased and no_accepted:
            return GuardReport(
                is_stuck=True,
                stuck_rounds=len(recent_gaps),
                suggested_actions=[],  # 不再使用，分级逻辑在 Scheduler 中
                reason=f"stuck for {len(recent_gaps)} rounds: gap_total={recent_gaps[0]}, accepted_count=0",
            )

        return GuardReport(
            is_stuck=False,
            stuck_rounds=0,
            suggested_actions=[],
            reason="",
        )