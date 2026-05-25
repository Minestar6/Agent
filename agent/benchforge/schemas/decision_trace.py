"""决策追踪和相关Schema（Plan-Driven 版本）。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceSummary:
    """证据摘要信息。"""
    evidence_count: int = 0
    single_chunk_count: int = 0
    multi_chunk_count: int = 0
    used_evidence_count: int = 0

    def to_dict(self) -> dict[str, int]:
        """转换为字典。"""
        return {
            "evidence_count": self.evidence_count,
            "single_chunk_count": self.single_chunk_count,
            "multi_chunk_count": self.multi_chunk_count,
            "used_evidence_count": self.used_evidence_count,
        }


@dataclass
class GapInfo:
    """缺口信息。"""
    key: str  # 如 "qa:hard"
    mode: str
    difficulty: str
    remaining: int

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "key": self.key,
            "mode": self.mode,
            "difficulty": self.difficulty,
            "remaining": self.remaining,
        }


@dataclass
class GuardReport:
    """循环守护报告。"""
    is_stuck: bool = False
    stuck_rounds: int = 0
    suggested_actions: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "is_stuck": self.is_stuck,
            "stuck_rounds": self.stuck_rounds,
            "suggested_actions": self.suggested_actions,
            "reason": self.reason,
        }


@dataclass
class DecisionTrace:
    """单次决策追踪记录（执行后写入）。"""
    timestamp: str           # ISO 格式时间戳
    step_id: int            # 步骤编号
    round_num: int          # 轮次编号
    topic: str              # 当前主题
    gap_key: str | None     # 目标缺口键
    action: str             # 选择的动作
    note: str               # 决策原因
    priority: int = 0       # 动作优先级
    progress_before: float = 0.0     # 决策前进度
    progress_after: float | None = None  # 决策后进度
    num_candidates: int = 0  # 候选数量
    num_accepted: int = 0    # 接受数量
    num_rejected: int = 0    # 拒绝数量

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "timestamp": self.timestamp,
            "step_id": self.step_id,
            "round_num": self.round_num,
            "topic": self.topic,
            "gap_key": self.gap_key,
            "action": self.action,
            "note": self.note,
            "priority": self.priority,
            "progress_before": self.progress_before,
            "progress_after": self.progress_after,
            "num_candidates": self.num_candidates,
            "num_accepted": self.num_accepted,
            "num_rejected": self.num_rejected,
        }