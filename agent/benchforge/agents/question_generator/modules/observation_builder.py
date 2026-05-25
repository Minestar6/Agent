"""ObservationBuilder 模块：构造当前观察摘要。"""

from dataclasses import dataclass
from typing import Any

from benchforge.schemas import (
    Observation,
    EvidenceSummary,
    GapInfo,
    TopicState,
    TopicStatus,
)


class ObservationBuilder:
    """观察摘要构造器。

    职责：
    - 从 plan、state、evidence pool 提取核心信息
    - 构建 Observation（4 个核心字段 + evidence_summary）
    """

    def build(
        self,
        plan: Any,
        topic: str,
        topic_state: TopicState,
        evidence_pool: Any,
        evidence_stats: Any,
        progress: float,
    ) -> Observation:
        """构建观察摘要。

        Args:
            plan: 生成计划
            topic: 当前主题
            topic_state: 主题状态
            evidence_pool: 证据池
            evidence_stats: 证据统计
            progress: 整体完成进度

        Returns:
            观察摘要
        """
        # 识别主缺口
        main_gap = self._identify_main_gap(topic_state)

        # 构建证据摘要
        evidence_summary = self._build_evidence_summary(
            evidence_pool, evidence_stats
        )

        return Observation(
            plan=plan,
            topic_state=topic_state,
            main_gap=main_gap,
            progress=progress,
            evidence_summary=evidence_summary,
            round_num=topic_state.current_round,
            max_rounds=plan.max_rounds_per_topic if plan else 10,
            language=plan.language if plan else "en",
        )

    def _identify_main_gap(self, state: TopicState) -> GapInfo | None:
        """识别当前主题的主缺口。

        优先级：
        1. hard 优先
        2. 剩余数量大的优先

        Args:
            state: 主题状态

        Returns:
            缺口信息或 None
        """
        gaps = []

        for key, remaining in state.remaining_counts.items():
            if remaining > 0:
                gaps.append((key, remaining))

        if not gaps:
            return None

        # 解析 key
        def parse_key(key: str) -> tuple[str, str]:
            parts = key.split(":")
            if len(parts) == 2:
                return parts
            return "qa", "medium"

        # hard 优先排序
        gaps.sort(
            key=lambda x: (
                0 if ":hard" in x[0] else (1 if ":medium" in x[0] else 2),
                -x[1],  # 剩余数量降序
            )
        )

        gap_key, remaining = gaps[0]
        mode, difficulty = parse_key(gap_key)

        return GapInfo(
            key=gap_key,
            mode=mode,
            difficulty=difficulty,
            remaining=remaining,
        )

    def _build_evidence_summary(
        self,
        evidence_pool: Any,
        evidence_stats: Any,
    ) -> EvidenceSummary:
        """构建证据摘要。

        Args:
            evidence_pool: 证据池
            evidence_stats: 证据统计

        Returns:
            证据摘要
        """
        single_count = len(evidence_pool.single_chunks) if evidence_pool else 0
        multi_count = len(evidence_pool.multi_chunks) if evidence_pool else 0

        # 计算已使用数量
        used_single = sum(
            chunk.usage_count for chunk in evidence_pool.single_chunks
        ) if evidence_pool else 0
        used_multi = sum(
            unit.usage_count for unit in evidence_pool.multi_chunks
        ) if evidence_pool else 0

        return EvidenceSummary(
            evidence_count=single_count + multi_count,
            single_chunk_count=single_count,
            multi_chunk_count=multi_count,
            used_evidence_count=used_single + used_multi,
        )