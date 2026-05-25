"""观察构建器：构建摘要化的Agent观察。"""

from typing import Any

from benchforge.schemas import Observation, TopicState, EvidencePool
from benchforge.utils.planning import identify_main_gap


class ObservationBuilder:
    """构建Agent观察（摘要化）。

    核心原则：
    - 不直接喂完整数据
    - 压缩历史为模式摘要
    - 控制Prompt长度
    """

    def build(
        self,
        state: dict[str, Any],
        topic: str
    ) -> Observation:
        """构建观察对象。

        Args:
            state: 包含topic_states、evidence_pools、history等
            topic: 当前主题

        Returns:
            摘要化的观察对象
        """
        topic_state = state.get("topic_states", {}).get(topic)
        evidence_pool = state.get("evidence_pools", {}).get(topic)
        history = state.get("history", [])

        if not topic_state:
            raise ValueError(f"Topic state not found: {topic}")

        # 计算覆盖率摘要
        coverage_summary = self._summarize_coverage(topic_state)

        # 识别主缺口
        primary_gap, gap_remaining = self._identify_primary_gap(topic_state)

        # 压缩历史
        compressed_history = self._compress_history(history)

        # 摘要化证据状态
        evidence_sufficiency = self._assess_evidence_sufficiency(evidence_pool)
        single_eff, multi_eff = self._get_efficiency_scores(evidence_pool)

        return Observation(
            topic=topic,
            coverage_summary=coverage_summary,
            primary_gap=primary_gap,
            gap_remaining=gap_remaining,
            compressed_history=compressed_history,
            round=topic_state.current_round,
            max_rounds=state.get("max_rounds_per_topic", 10),
            evidence_sufficiency=evidence_sufficiency,
            single_evidence_efficiency=single_eff,
            multi_evidence_efficiency=multi_eff,
            constraints={
                "max_rounds_per_topic": state.get("max_rounds_per_topic", 10),
                "max_total_rounds": state.get("max_total_rounds", 50),
            },
        )

    def _summarize_coverage(self, state: TopicState) -> str:
        """计算覆盖率摘要。

        Args:
            state: 主题状态

        Returns:
            摘要文本，如"已完成75%，主要缺口qa:hard"
        """
        if not state.target_counts:
            return "无目标"

        total_target = sum(state.target_counts.values())
        total_completed = sum(state.completed_counts.values())

        if total_target == 0:
            return "无目标"

        progress = total_completed / total_target

        # 找出主要缺口
        gaps = [
            (key, state.remaining_counts.get(key, 0))
            for key in state.target_counts
            if state.remaining_counts.get(key, 0) > 0
        ]

        if gaps:
            # 按剩余数量排序
            gaps.sort(key=lambda x: -x[1])
            main_gap = gaps[0][0]
            return f"已完成{progress:.0%}，主要缺口{main_gap}"
        else:
            return f"已完成{progress:.0%}，无缺口"

    def _identify_primary_gap(self, state: TopicState) -> tuple[str, int]:
        """识别主缺口。

        Args:
            state: 主题状态

        Returns:
            (缺口键, 剩余数量)
        """
        # 使用原有的识别逻辑
        main_gap = identify_main_gap(state)

        if main_gap:
            return main_gap

        # 没有缺口
        return ("", 0)

    def _compress_history(self, history: list[dict]) -> list[str]:
        """压缩历史为摘要。

        不是直接history[-3:]，而是分析模式。

        Args:
            history: 历史决策列表

        Returns:
            摘要列表，如["连续3轮qa:hard生成不足", "多证据成功率高"]
        """
        if not history:
            return []

        compressed = []
        recent_decisions = history[-5:] if len(history) >= 5 else history

        # 检测连续失败模式
        failure_streak = self._detect_failure_streak(recent_decisions)
        if failure_streak > 0:
            compressed.append(f"连续{failure_streak}轮生成不足")

        # 检测高效策略模式
        high_efficiency_strategies = self._detect_high_efficiency(recent_decisions)
        if high_efficiency_strategies:
            compressed.append(f"{high_efficiency_strategies}策略成功率较高")

        # 检测证据模式
        evidence_pattern = self._detect_evidence_pattern(recent_decisions)
        if evidence_pattern:
            compressed.append(evidence_pattern)

        return compressed if compressed else ["历史正常"]

    def _detect_failure_streak(self, decisions: list[dict]) -> int:
        """检测连续失败轮数。

        Args:
            decisions: 最近几轮决策

        Returns:
            连续失败的轮数
        """
        streak = 0
        for decision in reversed(decisions):
            # 检查是否有结果信息
            if isinstance(decision, dict):
                # 如果是ControlDecision，检查action_parameters
                params = decision.get("action_parameters", {})
                if params.get("valid_count", 1) == 0:
                    streak += 1
                else:
                    break
        return streak

    def _detect_high_efficiency(self, decisions: list[dict]) -> str:
        """检测高效策略。

        Args:
            decisions: 最近几轮决策

        Returns:
            高效策略名称，或空字符串
        """
        # 简化实现：检查是否有多证据成功的历史
        multi_chunk_success = 0
        single_chunk_success = 0

        for decision in decisions:
            if isinstance(decision, dict):
                params = decision.get("action_parameters", {})
                if params.get("prefer_multi_chunk"):
                    multi_chunk_success += params.get("valid_count", 0)
                else:
                    single_chunk_success += params.get("valid_count", 0)

        if multi_chunk_success > single_chunk_success * 1.5:
            return "多证据"
        elif single_chunk_success > multi_chunk_success * 1.5:
            return "单证据"

        return ""

    def _detect_evidence_pattern(self, decisions: list[dict]) -> str:
        """检测证据使用模式。

        Args:
            decisions: 最近几轮决策

        Returns:
            模式描述，或空字符串
        """
        # 简化实现
        return ""

    def _assess_evidence_sufficiency(self, pool: EvidencePool | None) -> str:
        """评估证据充足度。

        Args:
            pool: 证据池

        Returns:
            "sufficient" | "partial" | "insufficient"
        """
        if not pool:
            return "insufficient"

        single_count = len(pool.single_chunks)
        multi_count = len(pool.multi_chunks)

        total = single_count + multi_count

        if total >= 10:
            return "sufficient"
        elif total >= 5:
            return "partial"
        else:
            return "insufficient"

    def _get_efficiency_scores(self, pool: EvidencePool | None) -> tuple[float, float]:
        """获取效率分数。

        Args:
            pool: 证据池

        Returns:
            (单证据效率, 多证据效率)
        """
        if not pool:
            return (0.0, 0.0)

        single_eff = pool.stats.single_chunk_stats.avg_valid_count if pool.stats else 0.0
        multi_eff = pool.stats.multi_chunk_stats.avg_valid_count if pool.stats else 0.0

        return (single_eff, multi_eff)