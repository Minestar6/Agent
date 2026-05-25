"""Agent意图相关Schema（Phase 2使用）。"""

from dataclasses import dataclass
from typing import Any


@dataclass
class AgentIntent:
    """Agent意图：LLM输出，包含高层意图但不直接控制action。

    LLM只负责"方向"，Rule Layer负责"控制"。
    """
    intent: str              # "increase_hard_questions" | "increase_coverage" | "expand_evidence" | "adjust_strategy" | "complete_topic"
    reason: str              # 为什么选择这个意图
    target_gap: str          # 目标缺口（如"qa:hard"）
    suggested_strategy: str  # 建议的策略（如"gap_driven"）
    confidence: float        # 置信度 0-1

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "intent": self.intent,
            "reason": self.reason,
            "target_gap": self.target_gap,
            "suggested_strategy": self.suggested_strategy,
            "confidence": self.confidence,
        }