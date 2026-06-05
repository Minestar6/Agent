"""自动指标 registry。"""

from .accuracy import AccuracyMetric, InvalidRateMetric
from .base import AutoMetric
from .exact_match import ExactMatchMetric, PrecisionMetric, TokenF1Metric, TokenRecallMetric
from .rouge_l import RougeLMetric
from .semantic import BertScoreMetric, BleuMetric, SemanticSimilarityMetric

AUTO_METRIC_REGISTRY: dict[str, AutoMetric] = {
    "accuracy": AccuracyMetric(),
    "invalid_rate": InvalidRateMetric(),
    "exact_match": ExactMatchMetric(),
    "f1": TokenF1Metric(),
    "precision": PrecisionMetric(),
    "recall": TokenRecallMetric(),
    "rouge_l": RougeLMetric(),
    "bleu": BleuMetric(),
    "bertscore": BertScoreMetric(),
    "semantic_similarity": SemanticSimilarityMetric(),
}
