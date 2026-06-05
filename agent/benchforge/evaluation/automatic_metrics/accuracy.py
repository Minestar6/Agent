"""accuracy 和 invalid_rate 指标（选择题）。"""

import re
from typing import Any

from .base import AutoMetric


def _parse_choice(question: dict[str, Any], prediction: str) -> str | None:
    """将模型原始输出解析为规范化选项标签（A/B/C/D），无法唯一定位时返回 None。"""
    choices = question.get("choices") or question.get("options") or {}
    if isinstance(choices, list):
        choices = {chr(65 + i): v for i, v in enumerate(choices)}

    labels = list(choices.keys()) if choices else ["A", "B", "C", "D"]
    pred = prediction.strip()

    # 直接单标签匹配（A / a / A. / Answer: B）
    for label in labels:
        if re.fullmatch(rf"(?:Answer\s*:\s*)?{re.escape(label)}\.?", pred, re.IGNORECASE):
            return label.upper()

    # JSON 格式 {"answer": "B"} / {"choice": "B"}
    json_match = re.search(r'"(?:answer|choice)"\s*:\s*"([^"]+)"', pred, re.IGNORECASE)
    if json_match:
        val = json_match.group(1).strip().upper()
        if val in [l.upper() for l in labels]:
            return val

    # 全文唯一匹配选项内容
    if choices:
        matched = [
            label for label, text in choices.items()
            if isinstance(text, str) and text.strip() and text.strip() in pred
        ]
        if len(matched) == 1:
            return matched[0].upper()

    return None


class AccuracyMetric(AutoMetric):
    name = "accuracy"

    def compute(self, question: dict, prediction: str, context: dict | None = None) -> float | None:
        gold = str(question.get("answer", "")).strip().upper()
        parsed = _parse_choice(question, prediction)
        if parsed is None:
            return None
        return 1.0 if parsed == gold else 0.0


class InvalidRateMetric(AutoMetric):
    name = "invalid_rate"

    def compute(self, question: dict, prediction: str, context: dict | None = None) -> float | None:
        parsed = _parse_choice(question, prediction)
        return 1.0 if parsed is None else 0.0
