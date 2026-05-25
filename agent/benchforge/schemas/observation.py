"""Observation Schema（Plan-Driven 简化版）。"""

from dataclasses import dataclass, field
from typing import Any

from benchforge.schemas.decision_trace import EvidenceSummary, GapInfo


@dataclass
class Observation:
    """摘要化观察（核心字段）。

    不直接喂完整数据，只提取决策所需的关键信息。
    """
    # 核心字段
    plan: Any  # GenerationPlan（避免循环导入）
    topic_state: Any  # TopicState
    main_gap: GapInfo | None
    progress: float  # 整体完成进度 0.0-1.0

    # 证据摘要
    evidence_summary: EvidenceSummary = field(default_factory=EvidenceSummary)

    # 附加信息
    round_num: int = 0
    max_rounds: int = 10
    language: str = "en"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "topic": self.topic_state.topic if self.topic_state else None,
            "progress": self.progress,
            "main_gap": self.main_gap.to_dict() if self.main_gap else None,
            "evidence_summary": self.evidence_summary.to_dict(),
            "round_num": self.round_num,
            "max_rounds": self.max_rounds,
        }
