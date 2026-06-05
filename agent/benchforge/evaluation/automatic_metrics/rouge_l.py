"""rouge_l 指标。"""

from .base import AutoMetric


def _lcs_length(a: list[str], b: list[str]) -> int:
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(2)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i % 2][j] = dp[(i - 1) % 2][j - 1] + 1
            else:
                dp[i % 2][j] = max(dp[(i - 1) % 2][j], dp[i % 2][j - 1])
    return dp[m % 2][n]


class RougeLMetric(AutoMetric):
    name = "rouge_l"

    def compute(self, question: dict, prediction: str, context: dict | None = None) -> float | None:
        ref = str(question.get("answer", "")).lower().split()
        pred = prediction.lower().split()
        if not ref or not pred:
            return 0.0
        lcs = _lcs_length(pred, ref)
        precision = lcs / len(pred)
        recall = lcs / len(ref)
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)
