"""测试用假模型客户端。"""

import asyncio
import time
from typing import Any

from benchforge.models.base import BaseModelClient


class FakeModelClient:
    """假模型客户端，用于测试。"""

    def __init__(self, delay: float = 0.1):
        """初始化假客户端。"""
        self.delay = delay
        self.call_count = 0

    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        """返回假的响应。"""
        self.call_count += 1
        await asyncio.sleep(self.delay)

        # 根据输入生成简单的假响应
        user_content = messages[-1].get("content", "") if messages else ""
        chunk_id = user_content.split("chunk_id:")[-1].split("\n")[0].strip() if "chunk_id:" in user_content else f"fake_{self.call_count}"

        fake_response = """[
  {
    "question": "What is the main topic of the provided text?",
    "answer": "The text discusses various aspects of the subject matter.",
    "question_type": "factual",
    "required_capability": "Understanding the main concept",
    "estimated_difficulty": "easy",
    "citations": [
      {
        "chunk_id": \"""" + chunk_id + """\",
        "text": "A sample citation from the source text."
      }
    ]
  }
]"""

        return {
            "text": fake_response,
            "input_tokens": 100,
            "output_tokens": 50,
            "latency": self.delay,
            "raw": {},
        }

    async def batch_complete(
        self,
        model: str,
        messages_list: list[list[dict[str, str]]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        concurrency: int = 5,
    ) -> list[dict[str, Any]]:
        """批量假的响应。"""
        return [
            await self.complete(model, msgs, temperature, max_tokens)
            for msgs in messages_list
        ]

    def reset(self):
        """重置调用计数。"""
        self.call_count = 0