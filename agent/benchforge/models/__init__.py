"""BenchForge 模型模块。"""

from benchforge.models.base import BaseModelClient
from benchforge.models.openai_client import OpenAIClient
from benchforge.models.local_client import OllamaClient, VLLMClient, TransformersClient
from benchforge.models.fake import FakeModelClient
from benchforge.models.loader import ModelConfig, ModelLoader, create_default_models

__all__ = [
    "BaseModelClient",
    "OpenAIClient",
    "OllamaClient",
    "VLLMClient",
    "TransformersClient",
    "FakeModelClient",
    "ModelConfig",
    "ModelLoader",
    "create_default_models",
]

# 向后兼容别名
ModelClient = OpenAIClient