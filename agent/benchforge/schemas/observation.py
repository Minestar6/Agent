"""Agent观察相关Schema。"""

from dataclasses import dataclass, field
from typing import Any
import json


@dataclass
class Observation:
    """Agent观察到的状态（摘要化）。

    关键原则：
    - 不直接喂完整数据
    - 压缩历史为模式摘要
    - 控制Prompt长度
    """
    topic: str

    # 摘要化的覆盖率
    coverage_summary: str          # "已完成75%，主要缺口qa:hard"
    primary_gap: str               # "qa:hard"
    gap_remaining: int             # 5

    # 摘要化的历史（不是完整history）
    compressed_history: list[str]  # ["连续3轮qa:hard生成不足", "多证据成功率高"]

    # 关键指标
    round: int
    max_rounds: int
    evidence_sufficiency: str      # "sufficient" | "partial" | "insufficient"
    single_evidence_efficiency: float
    multi_evidence_efficiency: float

    # 可选的约束信息
    constraints: dict[str, Any] = field(default_factory=dict)

    def to_prompt_text(self) -> str:
        """转换为Prompt文本（控制长度）。

        Returns:
            适合直接喂给LLM的文本。
        """
        history_text = "; ".join(self.compressed_history[-3:]) if self.compressed_history else "无"

        return f"""主题: {self.topic}
轮数: {self.round}/{self.max_rounds}
覆盖率: {self.coverage_summary}
主缺口: {self.primary_gap} (剩余{self.gap_remaining}题)
证据状态: {self.evidence_sufficiency}
单证据效率: {self.single_evidence_efficiency:.2f}
多证据效率: {self.multi_evidence_efficiency:.2f}
历史摘要: {history_text}"""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "topic": self.topic,
            "coverage_summary": self.coverage_summary,
            "primary_gap": self.primary_gap,
            "gap_remaining": self.gap_remaining,
            "compressed_history": self.compressed_history,
            "round": self.round,
            "max_rounds": self.max_rounds,
            "evidence_sufficiency": self.evidence_sufficiency,
            "single_evidence_efficiency": self.single_evidence_efficiency,
            "multi_evidence_efficiency": self.multi_evidence_efficiency,
            "constraints": self.constraints,
        }
