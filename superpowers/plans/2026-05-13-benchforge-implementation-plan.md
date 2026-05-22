# BenchForge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first BenchForge MVP that turns local documents into validated benchmark questions, evaluates target models, analyzes capability weaknesses, and records all work through planner-owned blueprints and task results.

**Architecture:** Create a new Python package at `benchforge/`. Use a strong central `PlannerAgent` that owns `Blueprint` state, dispatches typed `TaskSpec` objects, and accepts typed `TaskResult` objects from worker agents. Store every intermediate output as typed local artifacts under `runs/<run_id>/artifacts/`.

**Tech Stack:** Python 3.12, Pydantic v2, Typer, PyYAML, pytest, Ruff, local JSON/JSONL artifact storage, OpenAI-compatible model client abstraction, deterministic fake model for tests.

---

## Source References

- Current project intent: `docs/plan.md`
- Refined architecture: `docs/multi-agent-framework-design.md`
- Detailed technical design: `docs/benchforge-technical-design.md`
- YourBench reference: `reference/code/yourbench`
- AutoBencher reference: `reference/code/AutoBencher`
- EvalTree reference: `reference/code/EvalTree`

Do not modify files under `reference/`.

## Planned File Structure

- Create: `pyproject.toml`
- Create: `benchforge/__init__.py`
- Create: `benchforge/cli.py`
- Create: `benchforge/config.py`
- Create: `benchforge/orchestrator.py`
- Create: `benchforge/agents/__init__.py`
- Create: `benchforge/agents/planner.py`
- Create: `benchforge/agents/question_generator.py`
- Create: `benchforge/agents/question_validator.py`
- Create: `benchforge/agents/model_evaluator.py`
- Create: `benchforge/agents/analyzer.py`
- Create: `benchforge/artifacts/__init__.py`
- Create: `benchforge/artifacts/store.py`
- Create: `benchforge/models/__init__.py`
- Create: `benchforge/models/client.py`
- Create: `benchforge/models/fake.py`
- Create: `benchforge/pipelines/__init__.py`
- Create: `benchforge/pipelines/documents.py`
- Create: `benchforge/pipelines/questions.py`
- Create: `benchforge/pipelines/evaluation.py`
- Create: `benchforge/pipelines/analysis.py`
- Create: `benchforge/schemas/__init__.py`
- Create: `benchforge/schemas/artifact.py`
- Create: `benchforge/schemas/blueprint.py`
- Create: `benchforge/schemas/question.py`
- Create: `benchforge/schemas/task.py`
- Create: `benchforge/prompts/question_generation.md`
- Create: `benchforge/prompts/question_validation.md`
- Create: `benchforge/prompts/answer_judging.md`
- Create: `benchforge/prompts/capability_annotation.md`
- Create: `tests/unit/test_schemas.py`
- Create: `tests/unit/test_artifact_store.py`
- Create: `tests/unit/test_planner.py`
- Create: `tests/unit/test_documents.py`
- Create: `tests/unit/test_questions.py`
- Create: `tests/unit/test_validator.py`
- Create: `tests/unit/test_evaluator.py`
- Create: `tests/unit/test_analyzer.py`
- Create: `tests/integration/test_local_run.py`
- Create: `examples/local_mvp/config.yaml`
- Create: `examples/local_mvp/docs/history.md`
- Modify: `AGENTS.md`
- Modify: `docs/benchforge-technical-design.md` only if implementation discovers a necessary contract correction.

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `benchforge/__init__.py`
- Create: `benchforge/cli.py`
- Create: `benchforge/config.py`
- Create: `tests/unit/test_schemas.py`

- [ ] **Step 1: Create package directories**

Run:

```bash
mkdir -p benchforge/{agents,artifacts,models,pipelines,schemas,prompts} tests/unit tests/integration examples/local_mvp/docs
```

Expected: directories exist.

- [ ] **Step 2: Create `pyproject.toml`**

Use this content:

```toml
[project]
name = "benchforge"
version = "0.1.0"
description = "Multi-agent framework for automatic LLM benchmark generation and evaluation."
requires-python = ">=3.12,<3.13"
dependencies = [
    "pydantic>=2.11",
    "typer>=0.15",
    "pyyaml>=6.0",
    "loguru>=0.7",
    "tiktoken>=0.9",
    "numpy>=1.24",
    "scikit-learn>=1.5",
    "statsmodels>=0.14",
    "thefuzz>=0.22",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.4",
    "ruff>=0.12",
]

[project.scripts]
benchforge = "benchforge.cli:app"

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["benchforge*"]

[tool.ruff]
line-length = 119
target-version = "py312"

[tool.ruff.lint]
select = ["C", "E", "F", "I", "W"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
line-ending = "auto"
```

- [ ] **Step 3: Create minimal package files**

`benchforge/__init__.py`:

```python
"""BenchForge package."""

__version__ = "0.1.0"
```

Create empty subpackage markers:

```bash
touch benchforge/agents/__init__.py benchforge/artifacts/__init__.py benchforge/models/__init__.py benchforge/pipelines/__init__.py benchforge/schemas/__init__.py
```

`benchforge/cli.py`:

```python
from pathlib import Path

import typer

from benchforge.config import load_config


app = typer.Typer(name="benchforge", help="BenchForge local benchmark generation and evaluation CLI.")


@app.command()
def validate_config(config_path: Path) -> None:
    """Validate a BenchForge YAML config."""
    config = load_config(config_path)
    typer.echo(f"Config valid for run: {config.run_name}")


if __name__ == "__main__":
    app()
```

`benchforge/config.py`:

```python
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class BenchForgeConfig(BaseModel):
    run_name: str = "local-mvp"
    output_dir: str = "runs"
    source_documents_dir: str = "examples/local_mvp/docs"
    target_models: list[str] = Field(default_factory=lambda: ["fake-model"])
    domains: list[str] = Field(default_factory=lambda: ["general"])
    languages: list[str] = Field(default_factory=lambda: ["en"])
    target_question_count: int = 5
    per_round_question_count: int = 5
    max_rounds: int = 1


def load_config(path: str | Path) -> BenchForgeConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    data: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return BenchForgeConfig.model_validate(data)
```

- [ ] **Step 4: Add first schema smoke test**

`tests/unit/test_schemas.py`:

```python
from benchforge.config import BenchForgeConfig


def test_config_defaults_are_valid():
    config = BenchForgeConfig()

    assert config.run_name == "local-mvp"
    assert config.target_models == ["fake-model"]
    assert config.target_question_count == 5
```

- [ ] **Step 5: Run the smoke test**

Run:

```bash
pytest tests/unit/test_schemas.py -v
```

Expected: one passing test.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml benchforge tests/unit/test_schemas.py
git commit -m "chore: scaffold BenchForge package"
```

## Task 2: Core Schemas

**Files:**
- Create: `benchforge/schemas/artifact.py`
- Create: `benchforge/schemas/question.py`
- Create: `benchforge/schemas/blueprint.py`
- Create: `benchforge/schemas/task.py`
- Modify: `benchforge/schemas/__init__.py`
- Modify: `tests/unit/test_schemas.py`

- [ ] **Step 1: Implement artifact schemas**

`benchforge/schemas/artifact.py`:

```python
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ArtifactType(StrEnum):
    SOURCE_DOCUMENT = "source_document"
    DOCUMENT_CHUNK = "document_chunk"
    TOPIC_PLAN = "topic_plan"
    CANDIDATE_QUESTION = "candidate_question"
    VALIDATED_QUESTION = "validated_question"
    REJECTED_QUESTION = "rejected_question"
    EVALUATION_RECORD = "evaluation_record"
    CAPABILITY_TREE = "capability_tree"
    WEAKNESS_PROFILE = "weakness_profile"
    RUN_REPORT = "run_report"


class ArtifactRef(BaseModel):
    artifact_id: str
    artifact_type: ArtifactType
    uri: str
    description: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 2: Implement question schemas**

`benchforge/schemas/question.py`:

```python
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class QuestionType(StrEnum):
    OPEN_ENDED = "open_ended"
    MULTIPLE_CHOICE = "multiple_choice"
    SHORT_ANSWER = "short_answer"


class ValidationDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REPAIRABLE = "repairable"


class SourceEvidence(BaseModel):
    document_id: str
    chunk_id: str | None = None
    quote: str


class CandidateQuestion(BaseModel):
    question_id: str
    question: str
    answer: str
    question_type: QuestionType = QuestionType.OPEN_ENDED
    choices: list[str] = Field(default_factory=list)
    domain: str
    language: str = "en"
    difficulty: int = Field(default=5, ge=1, le=10)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    candidate_capabilities: list[str] = Field(default_factory=list)
    generating_model: str = ""

    @model_validator(mode="after")
    def validate_choices(self) -> "CandidateQuestion":
        if self.question_type == QuestionType.MULTIPLE_CHOICE and len(self.choices) != 4:
            raise ValueError("multiple_choice questions must have exactly four choices")
        if self.question_type != QuestionType.MULTIPLE_CHOICE and self.choices:
            raise ValueError("non-multiple-choice questions must not include choices")
        return self


class ValidationRecord(BaseModel):
    decision: ValidationDecision
    reasons: list[str] = Field(default_factory=list)
    citation_score: float | None = None
    duplicate_of: str | None = None


class ValidatedQuestion(BaseModel):
    candidate: CandidateQuestion
    validation: ValidationRecord
```

- [ ] **Step 3: Implement task and blueprint schemas**

`benchforge/schemas/task.py`:

```python
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from benchforge.schemas.artifact import ArtifactRef


class AgentType(StrEnum):
    PLANNER = "planner"
    QUESTION_GENERATOR = "question_generator"
    QUESTION_VALIDATOR = "question_validator"
    MODEL_EVALUATOR = "model_evaluator"
    ANALYZER = "analyzer"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class BudgetPolicy(BaseModel):
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    max_wall_time_seconds: int | None = None
    max_model_calls: int | None = None
    per_task_timeout_seconds: int | None = None


class TaskSpec(BaseModel):
    task_id: str
    blueprint_id: str
    blueprint_version: int
    round_id: int
    agent_type: AgentType
    objective: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    budget: BudgetPolicy | None = None
    priority: TaskPriority = TaskPriority.NORMAL
    depends_on: list[str] = Field(default_factory=list)
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    return_requirements: list[str] = Field(default_factory=list)


class TaskIssue(BaseModel):
    severity: str
    code: str
    message: str
    affected_items: list[str] = Field(default_factory=list)
    suggested_fix: str | None = None


class TaskResult(BaseModel):
    task_id: str
    blueprint_id: str
    blueprint_version: int
    round_id: int
    agent_type: AgentType
    status: TaskStatus
    summary: str
    produced_artifacts: list[ArtifactRef] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    issues: list[TaskIssue] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    needs_replan: bool = False
    suggested_next_tasks: list[TaskSpec] = Field(default_factory=list)
```

`benchforge/schemas/blueprint.py`:

```python
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from benchforge.schemas.artifact import ArtifactRef
from benchforge.schemas.task import BudgetPolicy


class BlueprintStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class EvaluationScope(BaseModel):
    domains: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=lambda: ["en"])
    target_models: list[str] = Field(default_factory=list)
    allow_multihop: bool = True
    allow_cross_document: bool = True


class SourcePolicy(BaseModel):
    source_documents_dir: str
    source_strategy: str = "local_documents"
    max_documents: int | None = None
    max_chunks_per_document: int | None = None


class DatasetPolicy(BaseModel):
    target_question_count: int
    per_round_question_count: int
    min_valid_question_rate: float = Field(default=0.6, ge=0.0, le=1.0)
    deduplication_required: bool = True


class IterationPolicy(BaseModel):
    max_rounds: int
    stop_when_target_count_reached: bool = True
    stop_when_budget_exhausted: bool = True
    allow_topic_expansion: bool = True
    allow_topic_pruning: bool = True


class DecisionRecord(BaseModel):
    blueprint_version: int
    reason: str
    input_task_ids: list[str] = Field(default_factory=list)


class Blueprint(BaseModel):
    blueprint_id: str
    version: int = 1
    status: BlueprintStatus = BlueprintStatus.DRAFT
    user_goal: str
    evaluation_scope: EvaluationScope
    source_policy: SourcePolicy
    dataset_policy: DatasetPolicy
    budget_policy: BudgetPolicy = Field(default_factory=BudgetPolicy)
    iteration_policy: IterationPolicy
    topic_state: dict[str, Any] = Field(default_factory=dict)
    shared_artifacts: list[ArtifactRef] = Field(default_factory=list)
    global_metrics: dict[str, Any] = Field(default_factory=dict)
    decision_log: list[DecisionRecord] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Export schemas**

`benchforge/schemas/__init__.py`:

```python
from benchforge.schemas.artifact import ArtifactRef, ArtifactType
from benchforge.schemas.blueprint import Blueprint, BlueprintStatus
from benchforge.schemas.question import CandidateQuestion, QuestionType, ValidatedQuestion, ValidationDecision
from benchforge.schemas.task import AgentType, BudgetPolicy, TaskResult, TaskSpec, TaskStatus

__all__ = [
    "AgentType",
    "ArtifactRef",
    "ArtifactType",
    "Blueprint",
    "BlueprintStatus",
    "BudgetPolicy",
    "CandidateQuestion",
    "QuestionType",
    "TaskResult",
    "TaskSpec",
    "TaskStatus",
    "ValidatedQuestion",
    "ValidationDecision",
]
```

- [ ] **Step 5: Extend schema tests**

Append to `tests/unit/test_schemas.py`:

```python
import pytest

from benchforge.schemas.blueprint import DatasetPolicy, EvaluationScope, IterationPolicy, SourcePolicy, Blueprint
from benchforge.schemas.question import CandidateQuestion, QuestionType


def test_candidate_question_rejects_bad_multiple_choice():
    with pytest.raises(ValueError, match="exactly four choices"):
        CandidateQuestion(
            question_id="q1",
            question="Pick one",
            answer="A",
            question_type=QuestionType.MULTIPLE_CHOICE,
            choices=["A", "B"],
            domain="history",
        )


def test_blueprint_minimal_contract():
    blueprint = Blueprint(
        blueprint_id="bp1",
        user_goal="Evaluate a model on local history docs",
        evaluation_scope=EvaluationScope(domains=["history"], target_models=["fake-model"]),
        source_policy=SourcePolicy(source_documents_dir="examples/local_mvp/docs"),
        dataset_policy=DatasetPolicy(target_question_count=5, per_round_question_count=5),
        iteration_policy=IterationPolicy(max_rounds=1),
    )

    assert blueprint.version == 1
    assert blueprint.evaluation_scope.domains == ["history"]
```

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/unit/test_schemas.py -v
```

Expected: all schema tests pass.

- [ ] **Step 7: Commit**

```bash
git add benchforge/schemas tests/unit/test_schemas.py
git commit -m "feat: define BenchForge core schemas"
```

## Task 3: Artifact Store

**Files:**
- Create: `benchforge/artifacts/store.py`
- Modify: `benchforge/artifacts/__init__.py`
- Create: `tests/unit/test_artifact_store.py`

- [ ] **Step 1: Write failing artifact store tests**

`tests/unit/test_artifact_store.py`:

```python
from benchforge.artifacts.store import ArtifactStore
from benchforge.schemas.artifact import ArtifactType


def test_artifact_store_writes_and_reads_json(tmp_path):
    store = ArtifactStore(tmp_path)
    ref = store.write_json(ArtifactType.TOPIC_PLAN, "topic-plan-1", {"domain": "history"})

    assert ref.artifact_type == ArtifactType.TOPIC_PLAN
    assert store.read_json(ref) == {"domain": "history"}


def test_artifact_store_appends_jsonl(tmp_path):
    store = ArtifactStore(tmp_path)
    ref = store.write_jsonl(
        ArtifactType.CANDIDATE_QUESTION,
        "candidate-questions",
        [{"question_id": "q1"}, {"question_id": "q2"}],
    )

    assert store.read_jsonl(ref) == [{"question_id": "q1"}, {"question_id": "q2"}]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/unit/test_artifact_store.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `benchforge.artifacts.store`.

- [ ] **Step 3: Implement artifact store**

`benchforge/artifacts/store.py`:

```python
import json
from pathlib import Path
from typing import Any

from benchforge.schemas.artifact import ArtifactRef, ArtifactType


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, artifact_type: ArtifactType, artifact_id: str, suffix: str) -> Path:
        directory = self.root / artifact_type.value
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{artifact_id}{suffix}"

    def write_json(self, artifact_type: ArtifactType, artifact_id: str, payload: dict[str, Any]) -> ArtifactRef:
        path = self._path(artifact_type, artifact_id, ".json")
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return ArtifactRef(artifact_id=artifact_id, artifact_type=artifact_type, uri=str(path))

    def read_json(self, ref: ArtifactRef) -> dict[str, Any]:
        return json.loads(Path(ref.uri).read_text(encoding="utf-8"))

    def write_jsonl(
        self,
        artifact_type: ArtifactType,
        artifact_id: str,
        rows: list[dict[str, Any]],
    ) -> ArtifactRef:
        path = self._path(artifact_type, artifact_id, ".jsonl")
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return ArtifactRef(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            uri=str(path),
            metadata={"row_count": len(rows)},
        )

    def read_jsonl(self, ref: ArtifactRef) -> list[dict[str, Any]]:
        rows = []
        with Path(ref.uri).open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
        return rows
```

`benchforge/artifacts/__init__.py`:

```python
from benchforge.artifacts.store import ArtifactStore

__all__ = ["ArtifactStore"]
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/unit/test_artifact_store.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add benchforge/artifacts tests/unit/test_artifact_store.py
git commit -m "feat: add local artifact store"
```

## Task 4: Fake And Real Model Client Interfaces

**Files:**
- Create: `benchforge/models/client.py`
- Create: `benchforge/models/fake.py`
- Modify: `benchforge/models/__init__.py`
- Create: `tests/unit/test_questions.py`

- [ ] **Step 1: Define model protocol**

`benchforge/models/client.py`:

```python
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ModelMessage:
    role: str
    content: str


@dataclass
class ModelRequest:
    messages: list[ModelMessage]
    model_name: str = "fake-model"
    temperature: float = 0.0
    tags: list[str] = field(default_factory=list)


@dataclass
class ModelResponse:
    text: str
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0


class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse:
        """Return one completion for one request."""
```

- [ ] **Step 2: Add deterministic fake client**

`benchforge/models/fake.py`:

```python
import json

from benchforge.models.client import ModelRequest, ModelResponse


class FakeModelClient:
    def __init__(self, response_text: str | None = None):
        self.response_text = response_text
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        text = self.response_text
        if text is None:
            text = "<output_json>" + json.dumps([
                {
                    "question": "What is the main topic of the document?",
                    "answer": "The document discusses history.",
                    "question_type": "factual",
                    "estimated_difficulty": 2,
                    "citations": ["history"],
                    "candidate_capabilities": ["reading comprehension"],
                }
            ]) + "</output_json>"
        return ModelResponse(text=text, model_name=request.model_name)
```

`benchforge/models/__init__.py`:

```python
from benchforge.models.client import ModelClient, ModelMessage, ModelRequest, ModelResponse
from benchforge.models.fake import FakeModelClient

__all__ = ["FakeModelClient", "ModelClient", "ModelMessage", "ModelRequest", "ModelResponse"]
```

- [ ] **Step 3: Add a fake client test**

`tests/unit/test_questions.py`:

```python
from benchforge.models.client import ModelMessage, ModelRequest
from benchforge.models.fake import FakeModelClient


def test_fake_model_client_records_requests():
    client = FakeModelClient(response_text="ok")
    response = client.complete(ModelRequest(messages=[ModelMessage(role="user", content="hello")]))

    assert response.text == "ok"
    assert len(client.requests) == 1
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/unit/test_questions.py -v
```

Expected: fake client test passes.

- [ ] **Step 5: Commit**

```bash
git add benchforge/models tests/unit/test_questions.py
git commit -m "feat: add model client interface"
```

## Task 5: PlannerAgent

**Files:**
- Create: `benchforge/agents/planner.py`
- Modify: `benchforge/agents/__init__.py`
- Create: `tests/unit/test_planner.py`

- [ ] **Step 1: Write planner tests**

`tests/unit/test_planner.py`:

```python
from benchforge.agents.planner import PlannerAgent
from benchforge.config import BenchForgeConfig
from benchforge.schemas.task import AgentType, TaskStatus, TaskResult


def test_planner_creates_initial_blueprint_and_generation_task():
    planner = PlannerAgent()
    blueprint, tasks = planner.create_initial_plan(BenchForgeConfig(run_name="demo"))

    assert blueprint.blueprint_id == "demo"
    assert blueprint.status == "running"
    assert len(tasks) == 1
    assert tasks[0].agent_type == AgentType.QUESTION_GENERATOR
    assert tasks[0].round_id == 1


def test_planner_updates_after_successful_task_result():
    planner = PlannerAgent()
    blueprint, tasks = planner.create_initial_plan(BenchForgeConfig(run_name="demo"))
    result = TaskResult(
        task_id=tasks[0].task_id,
        blueprint_id=blueprint.blueprint_id,
        blueprint_version=blueprint.version,
        round_id=1,
        agent_type=AgentType.QUESTION_GENERATOR,
        status=TaskStatus.SUCCEEDED,
        summary="Generated candidates",
        metrics={"candidate_question_count": 5},
    )

    updated, next_tasks = planner.apply_result(blueprint, result)

    assert updated.version == 2
    assert updated.global_metrics["candidate_question_count"] == 5
    assert next_tasks[0].agent_type == AgentType.QUESTION_VALIDATOR
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/unit/test_planner.py -v
```

Expected: FAIL with missing `PlannerAgent`.

- [ ] **Step 3: Implement planner**

`benchforge/agents/planner.py`:

```python
from dataclasses import dataclass

from benchforge.config import BenchForgeConfig
from benchforge.schemas.blueprint import (
    Blueprint,
    BlueprintStatus,
    DatasetPolicy,
    DecisionRecord,
    EvaluationScope,
    IterationPolicy,
    SourcePolicy,
)
from benchforge.schemas.task import AgentType, TaskResult, TaskSpec, TaskStatus


@dataclass
class PlannerAgent:
    def create_initial_plan(self, config: BenchForgeConfig) -> tuple[Blueprint, list[TaskSpec]]:
        blueprint = Blueprint(
            blueprint_id=config.run_name,
            status=BlueprintStatus.RUNNING,
            user_goal=f"Generate and evaluate {config.target_question_count} questions.",
            evaluation_scope=EvaluationScope(
                domains=config.domains,
                languages=config.languages,
                target_models=config.target_models,
            ),
            source_policy=SourcePolicy(source_documents_dir=config.source_documents_dir),
            dataset_policy=DatasetPolicy(
                target_question_count=config.target_question_count,
                per_round_question_count=config.per_round_question_count,
            ),
            iteration_policy=IterationPolicy(max_rounds=config.max_rounds),
            next_actions=["generate_questions"],
            decision_log=[DecisionRecord(blueprint_version=1, reason="Created initial local MVP plan.")],
        )
        return blueprint, [self._question_generation_task(blueprint)]

    def apply_result(self, blueprint: Blueprint, result: TaskResult) -> tuple[Blueprint, list[TaskSpec]]:
        data = blueprint.model_copy(deep=True)
        data.version += 1
        data.global_metrics.update(result.metrics)
        data.decision_log.append(
            DecisionRecord(
                blueprint_version=data.version,
                reason=f"Accepted result from {result.agent_type.value}: {result.summary}",
                input_task_ids=[result.task_id],
            )
        )
        if result.status in {TaskStatus.FAILED, TaskStatus.PARTIAL} or result.needs_replan:
            data.next_actions = ["replan"]
            return data, [self._question_generation_task(data)]
        if result.agent_type == AgentType.QUESTION_GENERATOR:
            data.next_actions = ["validate_questions"]
            return data, [self._question_validation_task(data)]
        if result.agent_type == AgentType.QUESTION_VALIDATOR:
            data.next_actions = ["evaluate_models"]
            return data, [self._model_evaluation_task(data)]
        if result.agent_type == AgentType.MODEL_EVALUATOR:
            data.next_actions = ["analyze_results"]
            return data, [self._analysis_task(data)]
        data.status = BlueprintStatus.COMPLETED
        data.next_actions = []
        return data, []

    def _question_generation_task(self, blueprint: Blueprint) -> TaskSpec:
        return TaskSpec(
            task_id=f"{blueprint.blueprint_id}-r{blueprint.version}-generate",
            blueprint_id=blueprint.blueprint_id,
            blueprint_version=blueprint.version,
            round_id=max(1, blueprint.global_metrics.get("round_id", 1)),
            agent_type=AgentType.QUESTION_GENERATOR,
            objective="Generate candidate questions from local source documents.",
            inputs={"source_documents_dir": blueprint.source_policy.source_documents_dir},
            constraints={"per_round_question_count": blueprint.dataset_policy.per_round_question_count},
            acceptance_criteria=["candidate_question_count >= 1"],
            return_requirements=["candidate_question_count", "produced artifact refs"],
        )

    def _question_validation_task(self, blueprint: Blueprint) -> TaskSpec:
        return TaskSpec(
            task_id=f"{blueprint.blueprint_id}-r{blueprint.version}-validate",
            blueprint_id=blueprint.blueprint_id,
            blueprint_version=blueprint.version,
            round_id=1,
            agent_type=AgentType.QUESTION_VALIDATOR,
            objective="Validate candidate questions.",
            acceptance_criteria=["validated_question_count >= 1"],
            return_requirements=["validated_question_count", "rejected_question_count"],
        )

    def _model_evaluation_task(self, blueprint: Blueprint) -> TaskSpec:
        return TaskSpec(
            task_id=f"{blueprint.blueprint_id}-r{blueprint.version}-evaluate",
            blueprint_id=blueprint.blueprint_id,
            blueprint_version=blueprint.version,
            round_id=1,
            agent_type=AgentType.MODEL_EVALUATOR,
            objective="Evaluate target models on validated questions.",
            inputs={"target_models": blueprint.evaluation_scope.target_models},
            acceptance_criteria=["evaluation_record_count >= 1"],
        )

    def _analysis_task(self, blueprint: Blueprint) -> TaskSpec:
        return TaskSpec(
            task_id=f"{blueprint.blueprint_id}-r{blueprint.version}-analyze",
            blueprint_id=blueprint.blueprint_id,
            blueprint_version=blueprint.version,
            round_id=1,
            agent_type=AgentType.ANALYZER,
            objective="Analyze capability coverage and weakness profile.",
            acceptance_criteria=["analysis_complete == true"],
        )
```

`benchforge/agents/__init__.py`:

```python
from benchforge.agents.planner import PlannerAgent

__all__ = ["PlannerAgent"]
```

- [ ] **Step 4: Run planner tests**

Run:

```bash
pytest tests/unit/test_planner.py -v
```

Expected: planner tests pass.

- [ ] **Step 5: Commit**

```bash
git add benchforge/agents tests/unit/test_planner.py
git commit -m "feat: add planner agent"
```

## Task 6: Local Document Pipeline

**Files:**
- Create: `benchforge/pipelines/documents.py`
- Create: `tests/unit/test_documents.py`

- [ ] **Step 1: Write document pipeline tests**

`tests/unit/test_documents.py`:

```python
from benchforge.pipelines.documents import load_local_documents, chunk_document


def test_load_local_documents_reads_markdown_and_text(tmp_path):
    (tmp_path / "a.md").write_text("# History\n\nAncient history matters.", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Modern history matters.", encoding="utf-8")

    docs = load_local_documents(tmp_path)

    assert len(docs) == 2
    assert {doc["document_filename"] for doc in docs} == {"a.md", "b.txt"}


def test_chunk_document_creates_stable_chunk_ids():
    chunks = chunk_document("doc1", "one two three four five six", max_words=3)

    assert chunks == [
        {"chunk_id": "doc1_0", "chunk_text": "one two three"},
        {"chunk_id": "doc1_1", "chunk_text": "four five six"},
    ]
```

- [ ] **Step 2: Implement local document utilities**

`benchforge/pipelines/documents.py`:

```python
import hashlib
from pathlib import Path


def _document_id(path: Path, text: str) -> str:
    digest = hashlib.sha1(f"{path.name}:{text}".encode("utf-8")).hexdigest()[:12]
    return f"doc_{digest}"


def load_local_documents(source_dir: str | Path) -> list[dict]:
    root = Path(source_dir)
    documents = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        documents.append({
            "document_id": _document_id(path, text),
            "document_filename": path.name,
            "document_text": text,
            "document_metadata": {"relative_path": str(path.relative_to(root))},
        })
    return documents


def chunk_document(document_id: str, text: str, max_words: int = 180) -> list[dict]:
    words = text.split()
    chunks = []
    for index in range(0, len(words), max_words):
        chunk_text = " ".join(words[index:index + max_words]).strip()
        if chunk_text:
            chunks.append({"chunk_id": f"{document_id}_{len(chunks)}", "chunk_text": chunk_text})
    return chunks
```

- [ ] **Step 3: Run document tests**

Run:

```bash
pytest tests/unit/test_documents.py -v
```

Expected: document tests pass.

- [ ] **Step 4: Commit**

```bash
git add benchforge/pipelines/documents.py tests/unit/test_documents.py
git commit -m "feat: add local document pipeline"
```

## Task 7: QuestionGeneratorAgent

**Files:**
- Create: `benchforge/pipelines/questions.py`
- Create: `benchforge/agents/question_generator.py`
- Modify: `tests/unit/test_questions.py`

- [ ] **Step 1: Add JSON parsing and generation tests**

Append to `tests/unit/test_questions.py`:

```python
from benchforge.agents.question_generator import QuestionGeneratorAgent
from benchforge.artifacts.store import ArtifactStore
from benchforge.models.fake import FakeModelClient
from benchforge.pipelines.questions import parse_output_json
from benchforge.schemas.task import AgentType, TaskSpec


def test_parse_output_json_reads_tagged_array():
    rows = parse_output_json('<output_json>[{"question": "Q?", "answer": "A"}]</output_json>')

    assert rows == [{"question": "Q?", "answer": "A"}]


def test_question_generator_writes_candidate_artifacts(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "history.md").write_text("history is a field of study", encoding="utf-8")
    store = ArtifactStore(tmp_path / "artifacts")
    agent = QuestionGeneratorAgent(store=store, model_client=FakeModelClient())
    task = TaskSpec(
        task_id="t1",
        blueprint_id="bp1",
        blueprint_version=1,
        round_id=1,
        agent_type=AgentType.QUESTION_GENERATOR,
        objective="Generate",
        inputs={"source_documents_dir": str(docs_dir)},
        constraints={"per_round_question_count": 1, "domain": "history", "language": "en"},
    )

    result = agent.run(task)

    assert result.metrics["candidate_question_count"] == 1
    assert result.produced_artifacts[0].artifact_id == "t1-candidate-questions"
```

- [ ] **Step 2: Implement question parsing**

`benchforge/pipelines/questions.py`:

```python
import json
import re
from typing import Any

from benchforge.schemas.question import CandidateQuestion, QuestionType, SourceEvidence


def parse_output_json(text: str) -> list[dict[str, Any]]:
    tag_match = re.search(r"<output_json>(.*?)</output_json>", text, re.DOTALL)
    candidate = tag_match.group(1) if tag_match else text
    return json.loads(candidate)


def build_candidate_question(
    row: dict[str, Any],
    *,
    question_id: str,
    document_id: str,
    chunk_id: str,
    chunk_text: str,
    domain: str,
    language: str,
    model_name: str,
) -> CandidateQuestion:
    question_type = QuestionType.MULTIPLE_CHOICE if row.get("choices") else QuestionType.OPEN_ENDED
    evidence = [
        SourceEvidence(
            document_id=document_id,
            chunk_id=chunk_id,
            quote=str(quote),
        )
        for quote in row.get("citations", [])
    ]
    if not evidence and chunk_text:
        evidence = [SourceEvidence(document_id=document_id, chunk_id=chunk_id, quote=chunk_text[:200])]
    return CandidateQuestion(
        question_id=question_id,
        question=str(row.get("question", "")).strip(),
        answer=str(row.get("answer", "")).strip(),
        question_type=question_type,
        choices=[str(choice) for choice in row.get("choices", [])],
        domain=domain,
        language=language,
        difficulty=int(row.get("estimated_difficulty", row.get("difficulty", 5))),
        source_evidence=evidence,
        candidate_capabilities=[str(x) for x in row.get("candidate_capabilities", [])],
        generating_model=model_name,
    )
```

- [ ] **Step 3: Implement question generator agent**

`benchforge/agents/question_generator.py`:

```python
from benchforge.artifacts.store import ArtifactStore
from benchforge.models.client import ModelClient, ModelMessage, ModelRequest
from benchforge.pipelines.documents import chunk_document, load_local_documents
from benchforge.pipelines.questions import build_candidate_question, parse_output_json
from benchforge.schemas.artifact import ArtifactType
from benchforge.schemas.task import AgentType, TaskResult, TaskSpec, TaskStatus


class QuestionGeneratorAgent:
    def __init__(self, store: ArtifactStore, model_client: ModelClient):
        self.store = store
        self.model_client = model_client

    def run(self, task: TaskSpec) -> TaskResult:
        source_dir = task.inputs["source_documents_dir"]
        domain = task.constraints.get("domain", "general")
        language = task.constraints.get("language", "en")
        target_count = int(task.constraints.get("per_round_question_count", 5))

        documents = load_local_documents(source_dir)
        candidate_questions = []
        for document in documents:
            chunks = chunk_document(document["document_id"], document["document_text"])
            for chunk in chunks:
                if len(candidate_questions) >= target_count:
                    break
                request = ModelRequest(
                    model_name="fake-model",
                    messages=[
                        ModelMessage(role="system", content="Generate grounded benchmark questions."),
                        ModelMessage(role="user", content=chunk["chunk_text"]),
                    ],
                    tags=["question_generation", domain, language],
                )
                response = self.model_client.complete(request)
                for row in parse_output_json(response.text):
                    if len(candidate_questions) >= target_count:
                        break
                    question = build_candidate_question(
                        row,
                        question_id=f"{task.task_id}-q{len(candidate_questions) + 1}",
                        document_id=document["document_id"],
                        chunk_id=chunk["chunk_id"],
                        chunk_text=chunk["chunk_text"],
                        domain=domain,
                        language=language,
                        model_name=response.model_name,
                    )
                    candidate_questions.append(question.model_dump(mode="json"))

        ref = self.store.write_jsonl(
            ArtifactType.CANDIDATE_QUESTION,
            f"{task.task_id}-candidate-questions",
            candidate_questions,
        )
        return TaskResult(
            task_id=task.task_id,
            blueprint_id=task.blueprint_id,
            blueprint_version=task.blueprint_version,
            round_id=task.round_id,
            agent_type=AgentType.QUESTION_GENERATOR,
            status=TaskStatus.SUCCEEDED if candidate_questions else TaskStatus.FAILED,
            summary=f"Generated {len(candidate_questions)} candidate questions.",
            produced_artifacts=[ref],
            metrics={"candidate_question_count": len(candidate_questions)},
            needs_replan=len(candidate_questions) == 0,
        )
```

- [ ] **Step 4: Run question tests**

Run:

```bash
pytest tests/unit/test_questions.py -v
```

Expected: all question tests pass.

- [ ] **Step 5: Commit**

```bash
git add benchforge/pipelines/questions.py benchforge/agents/question_generator.py tests/unit/test_questions.py
git commit -m "feat: add question generator agent"
```

## Task 8: QuestionValidatorAgent

**Files:**
- Create: `benchforge/agents/question_validator.py`
- Create: `tests/unit/test_validator.py`

- [ ] **Step 1: Write validator tests**

`tests/unit/test_validator.py`:

```python
from benchforge.agents.question_validator import QuestionValidatorAgent
from benchforge.artifacts.store import ArtifactStore
from benchforge.schemas.artifact import ArtifactType
from benchforge.schemas.question import CandidateQuestion, SourceEvidence
from benchforge.schemas.task import AgentType, TaskSpec


def test_validator_accepts_grounded_question(tmp_path):
    store = ArtifactStore(tmp_path)
    candidate = CandidateQuestion(
        question_id="q1",
        question="What does the document discuss?",
        answer="history",
        domain="history",
        source_evidence=[SourceEvidence(document_id="doc1", chunk_id="doc1_0", quote="history")],
    )
    ref = store.write_jsonl(ArtifactType.CANDIDATE_QUESTION, "candidates", [candidate.model_dump(mode="json")])
    agent = QuestionValidatorAgent(store)
    task = TaskSpec(
        task_id="validate",
        blueprint_id="bp1",
        blueprint_version=1,
        round_id=1,
        agent_type=AgentType.QUESTION_VALIDATOR,
        objective="Validate",
        inputs={"candidate_question_refs": [ref.model_dump(mode="json")]},
    )

    result = agent.run(task)

    assert result.metrics["validated_question_count"] == 1
    assert result.metrics["rejected_question_count"] == 0
```

- [ ] **Step 2: Implement validator**

`benchforge/agents/question_validator.py`:

```python
from benchforge.artifacts.store import ArtifactStore
from benchforge.schemas.artifact import ArtifactRef, ArtifactType
from benchforge.schemas.question import CandidateQuestion, ValidatedQuestion, ValidationDecision, ValidationRecord
from benchforge.schemas.task import AgentType, TaskResult, TaskSpec, TaskStatus


class QuestionValidatorAgent:
    def __init__(self, store: ArtifactStore):
        self.store = store

    def run(self, task: TaskSpec) -> TaskResult:
        candidates = []
        for ref_data in task.inputs.get("candidate_question_refs", []):
            ref = ArtifactRef.model_validate(ref_data)
            candidates.extend(self.store.read_jsonl(ref))

        accepted = []
        rejected = []
        seen = set()
        for raw in candidates:
            candidate = CandidateQuestion.model_validate(raw)
            reasons = []
            normalized_question = " ".join(candidate.question.lower().split())
            if normalized_question in seen:
                reasons.append("duplicate_question")
            if not candidate.question:
                reasons.append("empty_question")
            if not candidate.answer:
                reasons.append("empty_answer")
            if not candidate.source_evidence:
                reasons.append("missing_source_evidence")
            seen.add(normalized_question)

            if reasons:
                rejected.append({"candidate": candidate.model_dump(mode="json"), "reasons": reasons})
            else:
                accepted.append(
                    ValidatedQuestion(
                        candidate=candidate,
                        validation=ValidationRecord(decision=ValidationDecision.ACCEPTED),
                    ).model_dump(mode="json")
                )

        refs = [
            self.store.write_jsonl(ArtifactType.VALIDATED_QUESTION, f"{task.task_id}-validated", accepted),
            self.store.write_jsonl(ArtifactType.REJECTED_QUESTION, f"{task.task_id}-rejected", rejected),
        ]
        return TaskResult(
            task_id=task.task_id,
            blueprint_id=task.blueprint_id,
            blueprint_version=task.blueprint_version,
            round_id=task.round_id,
            agent_type=AgentType.QUESTION_VALIDATOR,
            status=TaskStatus.SUCCEEDED if accepted else TaskStatus.PARTIAL,
            summary=f"Accepted {len(accepted)} questions and rejected {len(rejected)} questions.",
            produced_artifacts=refs,
            metrics={"validated_question_count": len(accepted), "rejected_question_count": len(rejected)},
            needs_replan=len(accepted) == 0,
        )
```

- [ ] **Step 3: Run validator tests**

Run:

```bash
pytest tests/unit/test_validator.py -v
```

Expected: validator tests pass.

- [ ] **Step 4: Commit**

```bash
git add benchforge/agents/question_validator.py tests/unit/test_validator.py
git commit -m "feat: add question validator agent"
```

## Task 9: ModelEvaluatorAgent

**Files:**
- Create: `benchforge/pipelines/evaluation.py`
- Create: `benchforge/agents/model_evaluator.py`
- Create: `tests/unit/test_evaluator.py`

- [ ] **Step 1: Write evaluator tests**

`tests/unit/test_evaluator.py`:

```python
from benchforge.agents.model_evaluator import ModelEvaluatorAgent
from benchforge.artifacts.store import ArtifactStore
from benchforge.models.fake import FakeModelClient
from benchforge.schemas.artifact import ArtifactType
from benchforge.schemas.question import CandidateQuestion, ValidatedQuestion, ValidationDecision, ValidationRecord
from benchforge.schemas.task import AgentType, TaskSpec


def test_evaluator_scores_exact_match(tmp_path):
    store = ArtifactStore(tmp_path)
    question = ValidatedQuestion(
        candidate=CandidateQuestion(question_id="q1", question="Answer?", answer="history", domain="history"),
        validation=ValidationRecord(decision=ValidationDecision.ACCEPTED),
    )
    ref = store.write_jsonl(ArtifactType.VALIDATED_QUESTION, "validated", [question.model_dump(mode="json")])
    agent = ModelEvaluatorAgent(store=store, model_client=FakeModelClient(response_text="history"))
    task = TaskSpec(
        task_id="evaluate",
        blueprint_id="bp1",
        blueprint_version=1,
        round_id=1,
        agent_type=AgentType.MODEL_EVALUATOR,
        objective="Evaluate",
        inputs={"validated_question_refs": [ref.model_dump(mode="json")], "target_models": ["fake-model"]},
    )

    result = agent.run(task)

    assert result.metrics["evaluation_record_count"] == 1
    assert result.metrics["accuracy"] == 1.0
```

- [ ] **Step 2: Implement evaluation scoring**

`benchforge/pipelines/evaluation.py`:

```python
def exact_match_score(prediction: str, answer: str) -> int:
    return int(prediction.strip().lower() == answer.strip().lower())
```

`benchforge/agents/model_evaluator.py`:

```python
from benchforge.artifacts.store import ArtifactStore
from benchforge.models.client import ModelClient, ModelMessage, ModelRequest
from benchforge.pipelines.evaluation import exact_match_score
from benchforge.schemas.artifact import ArtifactRef, ArtifactType
from benchforge.schemas.question import ValidatedQuestion
from benchforge.schemas.task import AgentType, TaskResult, TaskSpec, TaskStatus


class ModelEvaluatorAgent:
    def __init__(self, store: ArtifactStore, model_client: ModelClient):
        self.store = store
        self.model_client = model_client

    def run(self, task: TaskSpec) -> TaskResult:
        questions = []
        for ref_data in task.inputs.get("validated_question_refs", []):
            ref = ArtifactRef.model_validate(ref_data)
            questions.extend(self.store.read_jsonl(ref))

        records = []
        for raw in questions:
            validated = ValidatedQuestion.model_validate(raw)
            candidate = validated.candidate
            response = self.model_client.complete(
                ModelRequest(
                    model_name=task.inputs.get("target_models", ["fake-model"])[0],
                    messages=[ModelMessage(role="user", content=candidate.question)],
                    tags=["model_evaluation", candidate.domain, candidate.language],
                )
            )
            score = exact_match_score(response.text, candidate.answer)
            records.append({
                "question_id": candidate.question_id,
                "model_name": response.model_name,
                "prediction": response.text,
                "answer": candidate.answer,
                "score": score,
                "domain": candidate.domain,
                "language": candidate.language,
                "candidate_capabilities": candidate.candidate_capabilities,
            })

        ref = self.store.write_jsonl(ArtifactType.EVALUATION_RECORD, f"{task.task_id}-evaluation-records", records)
        accuracy = sum(row["score"] for row in records) / len(records) if records else 0.0
        return TaskResult(
            task_id=task.task_id,
            blueprint_id=task.blueprint_id,
            blueprint_version=task.blueprint_version,
            round_id=task.round_id,
            agent_type=AgentType.MODEL_EVALUATOR,
            status=TaskStatus.SUCCEEDED if records else TaskStatus.FAILED,
            summary=f"Evaluated {len(records)} model-question pairs.",
            produced_artifacts=[ref],
            metrics={"evaluation_record_count": len(records), "accuracy": accuracy},
            needs_replan=len(records) == 0,
        )
```

- [ ] **Step 3: Run evaluator tests**

Run:

```bash
pytest tests/unit/test_evaluator.py -v
```

Expected: evaluator tests pass.

- [ ] **Step 4: Commit**

```bash
git add benchforge/pipelines/evaluation.py benchforge/agents/model_evaluator.py tests/unit/test_evaluator.py
git commit -m "feat: add model evaluator agent"
```

## Task 10: AnalyzerAgent

**Files:**
- Create: `benchforge/pipelines/analysis.py`
- Create: `benchforge/agents/analyzer.py`
- Create: `tests/unit/test_analyzer.py`

- [ ] **Step 1: Write analyzer tests**

`tests/unit/test_analyzer.py`:

```python
from benchforge.agents.analyzer import AnalyzerAgent
from benchforge.artifacts.store import ArtifactStore
from benchforge.schemas.artifact import ArtifactType
from benchforge.schemas.task import AgentType, TaskSpec


def test_analyzer_builds_simple_weakness_profile(tmp_path):
    store = ArtifactStore(tmp_path)
    ref = store.write_jsonl(
        ArtifactType.EVALUATION_RECORD,
        "eval",
        [
            {"question_id": "q1", "score": 0, "candidate_capabilities": ["dates"]},
            {"question_id": "q2", "score": 1, "candidate_capabilities": ["events"]},
        ],
    )
    agent = AnalyzerAgent(store)
    task = TaskSpec(
        task_id="analyze",
        blueprint_id="bp1",
        blueprint_version=1,
        round_id=1,
        agent_type=AgentType.ANALYZER,
        objective="Analyze",
        inputs={"evaluation_record_refs": [ref.model_dump(mode="json")]},
    )

    result = agent.run(task)

    assert result.metrics["analysis_complete"] is True
    assert result.metrics["weak_capability_count"] == 1
```

- [ ] **Step 2: Implement simple analysis pipeline**

`benchforge/pipelines/analysis.py`:

```python
from collections import defaultdict


def summarize_capability_performance(records: list[dict]) -> list[dict]:
    scores = defaultdict(list)
    for record in records:
        capabilities = record.get("candidate_capabilities") or ["uncategorized"]
        for capability in capabilities:
            scores[capability].append(int(record.get("score", 0)))

    summary = []
    for capability, values in scores.items():
        accuracy = sum(values) / len(values)
        summary.append({"capability": capability, "count": len(values), "accuracy": accuracy})
    return sorted(summary, key=lambda row: row["accuracy"])
```

`benchforge/agents/analyzer.py`:

```python
from benchforge.artifacts.store import ArtifactStore
from benchforge.pipelines.analysis import summarize_capability_performance
from benchforge.schemas.artifact import ArtifactRef, ArtifactType
from benchforge.schemas.task import AgentType, TaskResult, TaskSpec, TaskStatus


class AnalyzerAgent:
    def __init__(self, store: ArtifactStore):
        self.store = store

    def run(self, task: TaskSpec) -> TaskResult:
        records = []
        for ref_data in task.inputs.get("evaluation_record_refs", []):
            ref = ArtifactRef.model_validate(ref_data)
            records.extend(self.store.read_jsonl(ref))

        capability_summary = summarize_capability_performance(records)
        weakness_profile = [row for row in capability_summary if row["accuracy"] < 0.5]
        tree_ref = self.store.write_json(
            ArtifactType.CAPABILITY_TREE,
            f"{task.task_id}-capability-summary",
            {"capabilities": capability_summary},
        )
        weakness_ref = self.store.write_json(
            ArtifactType.WEAKNESS_PROFILE,
            f"{task.task_id}-weakness-profile",
            {"weaknesses": weakness_profile},
        )
        return TaskResult(
            task_id=task.task_id,
            blueprint_id=task.blueprint_id,
            blueprint_version=task.blueprint_version,
            round_id=task.round_id,
            agent_type=AgentType.ANALYZER,
            status=TaskStatus.SUCCEEDED,
            summary=f"Analyzed {len(records)} evaluation records.",
            produced_artifacts=[tree_ref, weakness_ref],
            metrics={
                "analysis_complete": True,
                "capability_count": len(capability_summary),
                "weak_capability_count": len(weakness_profile),
            },
            recommendations=[row["capability"] for row in weakness_profile],
        )
```

- [ ] **Step 3: Run analyzer tests**

Run:

```bash
pytest tests/unit/test_analyzer.py -v
```

Expected: analyzer tests pass.

- [ ] **Step 4: Commit**

```bash
git add benchforge/pipelines/analysis.py benchforge/agents/analyzer.py tests/unit/test_analyzer.py
git commit -m "feat: add analyzer agent"
```

## Task 11: Orchestrator And CLI Run Command

**Files:**
- Create: `benchforge/orchestrator.py`
- Modify: `benchforge/cli.py`
- Create: `tests/integration/test_local_run.py`
- Create: `examples/local_mvp/config.yaml`
- Create: `examples/local_mvp/docs/history.md`

- [ ] **Step 1: Add local example config and document**

`examples/local_mvp/config.yaml`:

```yaml
run_name: local-mvp
output_dir: runs
source_documents_dir: examples/local_mvp/docs
target_models:
  - fake-model
domains:
  - history
languages:
  - en
target_question_count: 1
per_round_question_count: 1
max_rounds: 1
```

`examples/local_mvp/docs/history.md`:

```markdown
# History

History is the study of past events, people, institutions, and societies.
```

- [ ] **Step 2: Write integration test**

`tests/integration/test_local_run.py`:

```python
from pathlib import Path

from benchforge.config import BenchForgeConfig
from benchforge.orchestrator import run_local


def test_local_run_completes(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "history.md").write_text("history is the study of past events", encoding="utf-8")
    config = BenchForgeConfig(
        run_name="it-run",
        output_dir=str(tmp_path / "runs"),
        source_documents_dir=str(docs),
        target_question_count=1,
        per_round_question_count=1,
        max_rounds=1,
    )

    result = run_local(config)

    assert result.status == "completed"
    assert Path(result.report_uri).exists()
```

- [ ] **Step 3: Implement orchestrator**

`benchforge/orchestrator.py`:

```python
from pathlib import Path

from pydantic import BaseModel

from benchforge.agents.analyzer import AnalyzerAgent
from benchforge.agents.model_evaluator import ModelEvaluatorAgent
from benchforge.agents.planner import PlannerAgent
from benchforge.agents.question_generator import QuestionGeneratorAgent
from benchforge.agents.question_validator import QuestionValidatorAgent
from benchforge.artifacts.store import ArtifactStore
from benchforge.config import BenchForgeConfig
from benchforge.models.fake import FakeModelClient
from benchforge.schemas.artifact import ArtifactType
from benchforge.schemas.task import AgentType


class RunSummary(BaseModel):
    status: str
    blueprint_id: str
    report_uri: str


def run_local(config: BenchForgeConfig) -> RunSummary:
    run_root = Path(config.output_dir) / config.run_name
    store = ArtifactStore(run_root / "artifacts")
    planner = PlannerAgent()
    fake_client = FakeModelClient(response_text="history")

    agents = {
        AgentType.QUESTION_GENERATOR: QuestionGeneratorAgent(store=store, model_client=FakeModelClient()),
        AgentType.QUESTION_VALIDATOR: QuestionValidatorAgent(store=store),
        AgentType.MODEL_EVALUATOR: ModelEvaluatorAgent(store=store, model_client=fake_client),
        AgentType.ANALYZER: AnalyzerAgent(store=store),
    }

    blueprint, tasks = planner.create_initial_plan(config)
    task_results = []
    while tasks:
        task = tasks.pop(0)
        result = agents[task.agent_type].run(task)
        task_results.append(result.model_dump(mode="json"))
        blueprint, tasks = planner.apply_result(blueprint, result)

    report_ref = store.write_json(
        ArtifactType.RUN_REPORT,
        "run-report",
        {
            "blueprint": blueprint.model_dump(mode="json"),
            "task_results": task_results,
        },
    )
    return RunSummary(status="completed", blueprint_id=blueprint.blueprint_id, report_uri=report_ref.uri)
```

- [ ] **Step 4: Add CLI run command**

Modify `benchforge/cli.py`:

```python
from pathlib import Path

import typer

from benchforge.config import load_config
from benchforge.orchestrator import run_local


app = typer.Typer(name="benchforge", help="BenchForge local benchmark generation and evaluation CLI.")


@app.command()
def validate_config(config_path: Path) -> None:
    """Validate a BenchForge YAML config."""
    config = load_config(config_path)
    typer.echo(f"Config valid for run: {config.run_name}")


@app.command()
def run(config_path: Path) -> None:
    """Run the local BenchForge MVP."""
    config = load_config(config_path)
    summary = run_local(config)
    typer.echo(f"Run {summary.status}: {summary.report_uri}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 5: Run integration test**

Run:

```bash
pytest tests/integration/test_local_run.py -v
```

Expected: integration test passes and creates a report JSON under the temporary run directory.

- [ ] **Step 6: Run CLI manually**

Run:

```bash
python -m benchforge.cli run examples/local_mvp/config.yaml
```

Expected: command prints `Run completed:` followed by a report path.

- [ ] **Step 7: Commit**

```bash
git add benchforge/orchestrator.py benchforge/cli.py tests/integration/test_local_run.py examples/local_mvp
git commit -m "feat: wire local BenchForge run"
```

## Task 12: Documentation And Repo Guidance

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/benchforge-technical-design.md`
- Create: `README.md`

- [ ] **Step 1: Create README**

`README.md`:

```markdown
# BenchForge

BenchForge is a local-first multi-agent framework for generating and evaluating LLM benchmarks.

## Current MVP

- Planner-owned `Blueprint`
- Typed `TaskSpec` and `TaskResult`
- Local `.md` and `.txt` document ingestion
- Candidate question generation
- Deterministic question validation
- Fake-model evaluation for tests
- Simple capability weakness analysis
- Local artifact storage under `runs/<run_id>/artifacts/`

## Run

```bash
python -m benchforge.cli validate-config examples/local_mvp/config.yaml
python -m benchforge.cli run examples/local_mvp/config.yaml
```

## Test

```bash
pytest
ruff format --check .
ruff check .
```

## Reference Material

Implementation reference code lives under `reference/` and should remain read-only unless a task explicitly says otherwise.
```

- [ ] **Step 2: Update AGENTS.md**

Add a new section near "Workspace Summary":

```markdown
## BenchForge Implementation Status

- BenchForge now has a root Python package under `benchforge/`.
- The first MVP is local-first and uses fake model clients for deterministic tests.
- Reference code under `reference/` remains read-only.
- Use `docs/benchforge-technical-design.md` for architecture and data contracts.
- Use `docs/superpowers/plans/2026-05-13-benchforge-implementation-plan.md` for task execution order.
```

- [ ] **Step 3: Run full verification**

Run:

```bash
pytest
ruff format --check .
ruff check .
```

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md docs/benchforge-technical-design.md
git commit -m "docs: document BenchForge MVP"
```

## Task 13: Post-MVP Extension Notes

**Files:**
- Modify: `docs/benchforge-technical-design.md`

- [ ] **Step 1: Add post-MVP section**

Append this section to `docs/benchforge-technical-design.md`:

```markdown
## 9. Post-MVP Extensions

After the local MVP passes tests, extend BenchForge in this order:

1. Replace the fake client with an OpenAI-compatible async client modeled after YourBench `inference_core.py`.
2. Add HTML/PDF ingestion after local Markdown/text ingestion is stable.
3. Add AutoBencher-style web retrieval with explicit source allowlists and no hardcoded credentials.
4. Add target-accuracy topic planning using `topic_state` and round-level model performance.
5. Add EvalTree-style embedding, recursive clustering, and confidence interval weakness extraction.
6. Add Hugging Face dataset export only after local artifact contracts are stable.
```

- [ ] **Step 2: Commit**

```bash
git add docs/benchforge-technical-design.md
git commit -m "docs: add BenchForge post-MVP roadmap"
```

## Final Verification

- [ ] Run all tests:

```bash
pytest
```

Expected: all tests pass.

- [ ] Run lint:

```bash
ruff format --check .
ruff check .
```

Expected: no formatting or lint errors.

- [ ] Run local example:

```bash
python -m benchforge.cli run examples/local_mvp/config.yaml
```

Expected: command prints `Run completed:` and the report path exists.

## Self-Review Checklist

- [ ] Every agent has typed input through `TaskSpec`.
- [ ] Every agent returns `TaskResult`.
- [ ] Only `PlannerAgent` mutates `Blueprint`.
- [ ] Every produced dataset is stored through `ArtifactStore`.
- [ ] Reference code under `reference/` was not modified.
- [ ] Tests cover schemas, artifact storage, planner, generation, validation, evaluation, analysis, and local orchestration.
- [ ] `AGENTS.md` reflects the new implementation status.
