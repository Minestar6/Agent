"""Agent决策相关Schema（Plan-Driven 版本）。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ControlDecision:
    """控制决策：只包含执行所需的信息，进入长期状态。

    注意：这是规则驱动的决策，不是 LLM 推理的结果。
    note 字段仅用于日志说明，而非推理链。
    """
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "action": self.action,
            "params": self.params,
            "note": self.note,
            "priority": self.priority,
        }