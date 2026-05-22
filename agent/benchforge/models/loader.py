"""统一模型加载和管理模块。"""

from typing import Any
from dataclasses import dataclass, field

import os

from benchforge.models.base import BaseModelClient
from benchforge.models import OpenAIClient, OllamaClient, VLLMClient


@dataclass
class ModelConfig:
    """模型配置（统一格式）。"""
    model_name: str
    provider: str = "openai"  # openai, ollama, vllm
    base_url: str | None = None
    api_key: str | None = None
    max_concurrent_requests: int = 4
    temperature: float = 0.7
    max_tokens: int = 2000
    extra_parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """后处理：从环境变量获取默认值。"""
        # provider 默认值
        if self.provider is None:
            self.provider = "openai"

        # OpenAI 默认值
        if self.provider == "openai":
            if self.api_key is None:
                self.api_key = os.getenv("OPENAI_API_KEY", "")
            if self.base_url is None:
                self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

        # Ollama 默认值
        elif self.provider == "ollama":
            if self.base_url is None:
                self.base_url = "http://localhost:11434"

        # vLLM 默认值
        elif self.provider == "vllm":
            if self.base_url is None:
                self.base_url = "http://localhost:8000"


class ModelLoader:
    """统一模型加载器。"""

    _provider_map = {
        "openai": OpenAIClient,
        "ollama": OllamaClient,
        "vllm": VLLMClient,
    }

    @classmethod
    def load_model(cls, config: ModelConfig) -> BaseModelClient:
        """加载单个模型。

        Args:
            config: 模型配置

        Returns:
            模型客户端实例
        """
        provider = config.provider.lower()
        client_class = cls._provider_map.get(provider)

        if client_class is None:
            raise ValueError(f"不支持的 provider: {provider}")

        client = client_class(
            api_key=config.api_key or "",
            base_url=config.base_url or "",
        )

        # 设置模型名称（用于日志）
        client.model_name = config.model_name

        # 设置并发数
        client.max_concurrent = config.max_concurrent_requests

        # 设置温度和最大 token
        client.temperature = config.temperature
        client.max_tokens = config.max_tokens

        # 设置额外参数
        client.extra_parameters = config.extra_parameters

        return client

    @classmethod
    def load_models(
        cls,
        configs: list[ModelConfig],
        step_name: str | None = None,
    ) -> list[BaseModelClient]:
        """加载多个模型。

        Args:
            configs: 模型配置列表
            step_name: 步骤名称（用于日志）

        Returns:
            模型客户端列表
        """
        clients = []
        for config in configs:
            try:
                client = cls.load_model(config)
                clients.append(client)
            except Exception as e:
                print(f"加载模型 {config.model_name} 失败: {e}")

        if step_name:
            model_names = [getattr(c, 'model_name', 'unknown') for c in clients]
            print(f"步骤 '{step_name}' 加载了 {len(clients)} 个模型: {model_names}")

        return clients

    @classmethod
    def load_from_dict(cls, data: dict[str, Any]) -> BaseModelClient:
        """从字典加载模型。

        Args:
            data: 模型配置字典

        Returns:
            模型客户端实例
        """
        config = ModelConfig(**data)
        return cls.load_model(config)

    @classmethod
    def load_list_from_dict(cls, data_list: list[dict[str, Any]]) -> list[BaseModelClient]:
        """从字典列表加载多个模型。

        Args:
            data_list: 模型配置字典列表

        Returns:
            模型客户端列表
        """
        configs = [ModelConfig(**d) for d in data_list]
        return cls.load_models(configs)


def create_default_models() -> list[BaseModelClient]:
    """创建默认模型列表（从环境变量）。

    Returns:
        模型客户端列表
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    if not api_key:
        raise ValueError("未设置 OPENAI_API_KEY 环境变量")

    client = OpenAIClient(api_key=api_key, base_url=base_url)
    client.model_name = "default-gpt"
    client.temperature = 0.7
    client.max_tokens = 2000

    return [client]