"""OpenAI 兼容 API 客户端。"""

import time
from typing import Any

import openai

from benchforge.models.base import BaseModelClient


class OpenAIClient(BaseModelClient):
    """OpenAI 兼容 API 客户端。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        max_retries: int = 3,
    ):
        """初始化客户端。"""
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
        )

    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """完成对话。"""
        start_time = time.time()

        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        latency = time.time() - start_time
        text = response.choices[0].message.content or ""
        raw = response.model_dump()

        return {
            "text": text,
            "input_tokens": raw.get("usage", {}).get("prompt_tokens", 0),
            "output_tokens": raw.get("usage", {}).get("completion_tokens", 0),
            "latency": latency,
            "raw": raw,
        }

    async def batch_complete(
        self,
        model: str,
        messages_list: list[list[dict[str, str]]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        concurrency: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """批量完成对话。"""
        import asyncio

        semaphore = asyncio.Semaphore(concurrency)

        async def single_call(messages):
            async with semaphore:
                return await self.complete(model, messages, temperature, max_tokens, **kwargs)

        return await asyncio.gather(*[single_call(msgs) for msgs in messages_list])