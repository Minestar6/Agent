"""Scheduler 模块：规则驱动决策（硬编码规则链）。"""

from typing import Any

from benchforge.schemas import (
    ControlDecision,
    Observation,
    GapInfo,
    GuardReport,
)


class Scheduler:
    """规则驱动决策器。

    职责：
    - 基于规则链选择 gap 和 action
    - 提供 fallback 决策（LoopGuard 触发时）
    - 不涉及 LLM，完全硬编码

    硬编码规则链：
    1. 无缺口 → finish_topic
    2. hard 缺口 + 证据不足 → expand_retrieval
    3. hard 缺口 + 未启用多 chunk → enable_multi_chunk
    4. 默认 → continue_generation
    """

    # 阈值常量
    MIN_HARD_EVIDENCE = 5  # hard 缺口需要的最小证据数量
    STUCK_FALLBACK_ACTIONS = ["expand_retrieval", "defer_topic"]

    def decide(self, observation: Observation) -> ControlDecision:
        """基于规则链选择下一步动作。

        Args:
            observation: 观察摘要

        Returns:
            控制决策
        """
        gap = observation.main_gap
        state = observation.topic_state
        evidence = observation.evidence_summary

        # 规则 1: 无缺口 → 完成
        if gap is None:
            return ControlDecision(
                action="finish_topic",
                params={},
                note="all gaps filled",
                priority=10,
            )

        # 规则 2: hard 缺口 + 证据不足 → 扩展检索
        if (
            gap.difficulty == "hard"
            and evidence.evidence_count < self.MIN_HARD_EVIDENCE
        ):
            return ControlDecision(
                action="expand_retrieval",
                params={"topic": state.topic},
                note=f"hard gap '{gap.key}' needs more evidence (current: {evidence.evidence_count})",
                priority=5,
            )

        # 规则 3: hard 缺口 + 多 chunk 不足 → 启用多 chunk
        if (
            gap.difficulty == "hard"
            and evidence.multi_chunk_count == 0
            and evidence.single_chunk_count > 0
        ):
            return ControlDecision(
                action="enable_multi_chunk",
                params={"topic": state.topic},
                note=f"hard gap '{gap.key}' needs multi-chunk evidence",
                priority=4,
            )

        # 规则 4: 达到最大轮数 → defer
        if observation.round_num >= observation.max_rounds:
            return ControlDecision(
                action="defer_topic",
                params={"topic": state.topic},
                note=f"max rounds reached ({observation.max_rounds})",
                priority=3,
            )

        # 规则 5: 默认 → 继续生成
        return ControlDecision(
            action="continue_generation",
            params={
                "topic": state.topic,
                "gap_key": gap.key,
                "target_mode": gap.mode,
                "target_difficulty": gap.difficulty,
                "remaining": gap.remaining,
            },
            note=f"targeting gap '{gap.key}' (remaining: {gap.remaining})",
            priority=1,
        )

    def fallback_decision(
        self,
        observation: Observation,
        guard_report: GuardReport,
    ) -> ControlDecision:
        """LoopGuard 触发时的 fallback 决策。

        Args:
            observation: 观察摘要
            guard_report: 守护报告

        Returns:
            fallback 控制决策
        """
        state = observation.topic_state

        # 选择第一个建议动作
        action = guard_report.suggested_actions[0]

        return ControlDecision(
            action=action,
            params={"topic": state.topic},
            note=f"fallback due to stuck loop: {guard_report.reason}",
            priority=20,
        )

    def is_valid_action(self, action: str) -> bool:
        """检查动作是否在允许列表中。

        Args:
            action: 动作名称

        Returns:
            是否有效
        """
        valid_actions = {
            "finish_topic",
            "expand_retrieval",
            "enable_multi_chunk",
            "continue_generation",
            "defer_topic",
        }
        return action in valid_actions