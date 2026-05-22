"""BenchForge - 基准测试问题自动生成框架。"""

from benchforge.schemas import (
    SourceDocument,
    SourceChunk,
    QuestionRecord,
    TaskResult,
    QuestionType,
    Difficulty,
    QuestionStatus,
)
from benchforge.utils import chunk_document, extract_json_array, search_wikipedia, fetch_wikipedia_page
from benchforge.artifacts import ArtifactStore
from benchforge.agents import QuestionGeneratorAgent
from benchforge.models import (
    BaseModelClient,
    OpenAIClient,
    OllamaClient,
    VLLMClient,
    TransformersClient,
    FakeModelClient,
)
from benchforge.config import QuestionGeneratorConfig

__all__ = [
    # Schemas
    "SourceDocument",
    "SourceChunk",
    "QuestionRecord",
    "TaskResult",
    "QuestionType",
    "Difficulty",
    "QuestionStatus",
    # Utils
    "chunk_document",
    "extract_json_array",
    "search_wikipedia",
    "fetch_wikipedia_page",
    # Artifacts
    "ArtifactStore",
    # Agents
    "QuestionGeneratorAgent",
    # Models
    "BaseModelClient",
    "OpenAIClient",
    "OllamaClient",
    "VLLMClient",
    "TransformersClient",
    "FakeModelClient",
    # Config
    "QuestionGeneratorConfig",
]

__version__ = "0.2.0"