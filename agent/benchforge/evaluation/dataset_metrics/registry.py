"""数据集指标 registry。"""

from .base import DatasetMetric
from .citation_score import CitationScoreMetric
from .diversity_score import DiversityScoreMetric

DATASET_METRIC_REGISTRY: dict[str, DatasetMetric] = {
    "citation_score": CitationScoreMetric(),
    "diversity_score": DiversityScoreMetric(),
}
