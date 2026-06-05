"""自动指标抽象基类。"""

from abc import ABC, abstractmethod
from typing import Any


class AutoMetric(ABC):
    name: str

    @abstractmethod
    def compute(
        self,
        question: dict[str, Any],
        prediction: str,
        context: dict[str, Any] | None = None,
    ) -> float | None:
        """计算单题单模型分数，无法计算时返回 None。"""
        raise NotImplementedError
