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

# 决策追踪相关Schema
from .agent_decision import ControlDecision, DecisionReasoning, AgentDecision
from .decision_trace import DecisionTrace, EvidenceSummary, GapInfo, GuardReport
from .observation import Observation

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

    # 决策追踪相关Schema
    "ControlDecision",
    "DecisionTrace",
    "EvidenceSummary",
    "GapInfo",
    "GuardReport",
    "Observation",
]