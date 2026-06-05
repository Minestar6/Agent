"""exact_match、token_f1、precision、recall 指标（QA）。"""

import re
from typing import Any

from .base import AutoMetric


def _normalize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^a-z0-9一-鿿\s]", " ", text)
    return text.split()


def _token_stats(prediction: str, reference: str) -> tuple[float, float, float]:
    pred_tokens = _normalize(prediction)
    ref_tokens = _normalize(reference)
    if not pred_tokens or not ref_tokens:
        return 0.0, 0.0, 0.0
    pred_set = {}
    for t in pred_tokens:
        pred_set[t] = pred_set.get(t, 0) + 1
    ref_set = {}
    for t in ref_tokens:
        ref_set[t] = ref_set.get(t, 0) + 1
    common = sum(min(pred_set.get(t, 0), ref_set.get(t, 0)) for t in ref_set)
    precision = common / len(pred_tokens)
    recall = common / len(ref_tokens)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return f1, precision, recall


class ExactMatchMetric(AutoMetric):
    name = "exact_match"

    def compute(self, question: dict, prediction: str, context: dict | None = None) -> float | None:
        gold = str(question.get("answer", "")).strip().lower()
        pred = prediction.strip().lower()
        return 1.0 if pred == gold else 0.0


class TokenF1Metric(AutoMetric):
    name = "f1"

    def compute(self, question: dict, prediction: str, context: dict | None = None) -> float | None:
        f1, _, _ = _token_stats(prediction, str(question.get("answer", "")))
        return f1


class PrecisionMetric(AutoMetric):
    name = "precision"

    def compute(self, question: dict, prediction: str, context: dict | None = None) -> float | None:
        _, precision, _ = _token_stats(prediction, str(question.get("answer", "")))
        return precision


class TokenRecallMetric(AutoMetric):
    name = "recall"

    def compute(self, question: dict, prediction: str, context: dict | None = None) -> float | None:
        _, _, recall = _token_stats(prediction, str(question.get("answer", "")))
        return recall
