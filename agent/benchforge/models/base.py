"""模型抽象基类。"""

from abc import ABC, abstractmethod
from typing import Any


class BaseModelClient(ABC):
    """模型客户端抽象基类。"""

    @abstractmethod
    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """完成对话。

        Returns:
            {
                "text": str,          # 模型响应文本
                "input_tokens": int,  # 输入 token 数
                "output_tokens": int, # 输出 token 数
                "latency": float,     # 延迟（秒）
                "raw": Any,           # 原始响应
            }
        """
        pass

    @abstractmethod
    async def batch_complete(
        self,
        model: str,
        messages_list: list[list[dict[str, str]]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """批量完成对话。"""
        pass