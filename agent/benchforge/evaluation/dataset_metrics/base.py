"""数据集级指标抽象基类。"""

from abc import ABC, abstractmethod
from typing import Any


class DatasetMetric(ABC):
    name: str

    @abstractmethod
    def compute(
        self,
        questions: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError
