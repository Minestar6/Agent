"""BenchForge 数据模式定义。"""

from .core import (
    # 核心枚举
    QuestionMode,
    Difficulty,
    DocumentStatus,
    QuestionStatus,
    QuestionType,
    TopicStatus,
    NextStepAction,

    # 核心模型
    SourceDocument,
    SourceChunk,
    Citation,
    QuestionRecord,
    QuestionModeTarget,
    GenerationPlan,
    TopicState,
    SingleChunkUnit,
    MultiChunkUnit,
    EvidenceTypeStats,
    EvidenceStats,
    EvidencePool,
    GenerationBatch,
    NextStepPlan,
    TaskResult,
    GenerationReport,

    # 旧版兼容配置
    RetrievalConfig,
    GenerationConfig,
    QuestionGenerationInput,
)

__all__ = [
    # 核心枚举
    "QuestionMode",
    "Difficulty",
    "DocumentStatus",
    "QuestionStatus",
    "QuestionType",
    "TopicStatus",
    "NextStepAction",

    # 核心模型
    "SourceDocument",
    "SourceChunk",
    "Citation",
    "QuestionRecord",
    "QuestionModeTarget",
    "GenerationPlan",
    "TopicState",
    "SingleChunkUnit",
    "MultiChunkUnit",
    "EvidenceTypeStats",
    "EvidenceStats",
    "EvidencePool",
    "GenerationBatch",
    "NextStepPlan",
    "TaskResult",
    "GenerationReport",

    # 旧版兼容配置
    "RetrievalConfig",
    "GenerationConfig",
    "QuestionGenerationInput",
]