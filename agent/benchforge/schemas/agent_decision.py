"""Agent决策相关Schema。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ControlDecision:
    """控制决策：只包含执行所需的信息，进入长期状态。

    只存储必要的状态信息，避免状态膨胀。
    """
    next_action: str
    action_parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "next_action": self.next_action,
            "action_parameters": self.action_parameters,
        }


@dataclass
class DecisionReasoning:
    """决策推理：只写日志，不进入长期状态。

    包含LLM的推理过程，用于日志和调试。
    """
    summary: str           # 一句话总结
    primary_gap: str       # 主缺口
    selected_strategy: str # 选择的策略
    confidence: float      # 置信度 0-1

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "summary": self.summary,
            "primary_gap": self.primary_gap,
            "selected_strategy": self.selected_strategy,
            "confidence": self.confidence,
        }


@dataclass
class AgentDecision:
    """完整决策 = 控制 + 推理。"""

    control: ControlDecision
    reasoning: DecisionReasoning

    # 便捷属性
    @property
    def next_action(self) -> str:
        return self.control.next_action

    @property
    def action_parameters(self) -> dict[str, Any]:
        return self.control.action_parameters

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "control": self.control.to_dict(),
            "reasoning": self.reasoning.to_dict(),
        }