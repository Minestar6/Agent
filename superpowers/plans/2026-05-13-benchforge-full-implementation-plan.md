# BenchForge Full Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first single-machine CLI implementation of full BenchForge: an external-retrieval-first, multi-round, multi-model benchmark construction and evaluation system grounded in Wikipedia/Wikimedia retrieval, schema-driven question generation, judge-model-first scoring, and EvalTree-inspired weakness analysis.

**Architecture:** Use `Strong Planner + Typed Workers`. `BlueprintSpec` is the fixed run specification, `RunState` is the only mutable global run state, and `PlannerAgent` is the only component allowed to mutate `RunState`. Worker agents operate on typed `TaskSpec` inputs, write typed artifacts, and return typed `TaskResult` outputs. Retrieval is implemented as a shared runtime used by `QuestionGeneratorAgent`, not as a standalone agent.

**Scope Decision:** This plan supersedes the earlier local MVP plan at `docs/superpowers/plans/2026-05-13-benchforge-implementation-plan.md` when the target is full BenchForge rather than a local-documents-only prototype.

---

## Reference Grounding

Use these sources as the engineering baseline:

- `docs/benchforge-technical-design.md`
- `reference/code/yourbench`
- `reference/code/AutoBencher`
- `reference/code/EvalTree`
- `reference/paper/autobencher.pdf`
- `reference/paper/evaltree.pdf`
- `reference/paper/yourbench.pdf`
- `reference/paper/BenchAgents.pdf`

Reference-specific rules:

- Reuse YourBench's question-generation contract more literally than before:
  - grouped stage configs
  - schema-driven prompts
  - parsed JSON arrays
  - `QuestionRow`-style provenance fields
- Reuse AutoBencher's planning loop and category refinement ideas:
  - summary over history
  - target-accuracy category planning
  - Wikipedia search and page retrieval
  - saliency reranking
- Reuse EvalTree's post-hoc analysis flow:
  - capability annotation
  - capability embedding
  - recursive clustering
  - hierarchical description
  - confidence-interval subtree extraction
- Treat BenchAgents as conceptual only in this repository, because no local code exists and the paper text is only partially inspectable with the current tooling.

Do not modify files under `reference/`.

## Authoritative Corrections

These points override assumptions in the earlier MVP plan:

- `PlannerAgent` owns topic optimization and round control.
- `QuestionGeneratorAgent` performs retrieval through `retrieval_runtime`.
- `QuestionGeneratorAgent` input must be grouped, not a flat bag of fields.
- Generation-stage capability labels are the default basis for analysis.
- `AnalyzerAgent` should not re-label every question by default.
- `judge_runtime` is shared infrastructure, not evaluator-local logic.
- The implementation target is no longer local-documents-first; it is external-retrieval-first.
- `BlueprintSpec` should stay fixed after initialization; all changing execution facts belong in `RunState`.

## Planned File Structure

- Create: `pyproject.toml`
- Create: `benchforge/__init__.py`
- Create: `benchforge/cli.py`
- Create: `benchforge/config.py`
- Create: `benchforge/orchestrator.py`
- Create: `benchforge/runtime/model_runtime.py`
- Create: `benchforge/runtime/retrieval_runtime.py`
- Create: `benchforge/runtime/judge_runtime.py`
- Create: `benchforge/runtime/metrics.py`
- Create: `benchforge/runtime/__init__.py`
- Create: `benchforge/agents/planner.py`
- Create: `benchforge/agents/question_generator.py`
- Create: `benchforge/agents/question_validator.py`
- Create: `benchforge/agents/model_evaluator.py`
- Create: `benchforge/agents/analyzer.py`
- Create: `benchforge/agents/__init__.py`
- Create: `benchforge/artifacts/store.py`
- Create: `benchforge/artifacts/__init__.py`
- Create: `benchforge/pipelines/topic_planning.py`
- Create: `benchforge/pipelines/question_generation.py`
- Create: `benchforge/pipelines/validation.py`
- Create: `benchforge/pipelines/evaluation.py`
- Create: `benchforge/pipelines/analysis.py`
- Create: `benchforge/pipelines/__init__.py`
- Create: `benchforge/schemas/blueprint.py`
- Create: `benchforge/schemas/task.py`
- Create: `benchforge/schemas/artifact.py`
- Create: `benchforge/schemas/question.py`
- Create: `benchforge/schemas/evaluation.py`
- Create: `benchforge/schemas/analysis.py`
- Create: `benchforge/schemas/runtime.py`
- Create: `benchforge/schemas/__init__.py`
- Create: `benchforge/prompts/`
- Create: `tests/unit/`
- Create: `tests/integration/`
- Modify: `AGENTS.md`
- Modify: `docs/benchforge-technical-design.md` only when implementation reveals a concrete contract mismatch

## Task 1: Project Skeleton And Dependency Baseline

- [ ] Create the package and test directory skeleton listed above.
- [ ] Define `pyproject.toml` for Python 3.12 with at least:
  - `pydantic`
  - `typer`
  - `pyyaml`
  - `requests`
  - `beautifulsoup4`
  - `numpy`
  - `scikit-learn`
  - `statsmodels`
  - `pytest`
  - `ruff`
- [ ] Add package markers and a minimal CLI bootstrap.
- [ ] Add a root config loader that can read YAML plus environment variables.
- [ ] Add a smoke test proving the package imports and config validation works.

Acceptance:

- `pytest tests/unit/test_config.py -v` passes.
- `python -m benchforge.cli --help` runs.

## Task 2: Core Schemas And Artifact Contracts

- [ ] Implement the run-level contracts:
  - `BlueprintSpec`
  - `RunState`
  - `TaskSpec`
  - `TaskResult`
  - `ArtifactRef`
  - `DecisionRecord`
- [ ] Implement grouped generator input schemas:
  - `TopicContext`
  - `RetrievalInput`
  - `EvidenceInput`
  - `GenerationInput`
  - `OutputControl`
  - `QuestionGenerationInput`
- [ ] Implement question schemas aligned with YourBench semantics:
  - `question`
  - `answer` or `self_answer`
  - `estimated_difficulty`
  - `question_type` or `self_assessed_question_type`
  - `question_mode`
  - `thought_process`
  - `citations`
  - `choices`
  - `document_id`
  - `chunk_id`
  - `source_chunk_ids`
  - `generating_model`
  - `raw_response`
  - `additional_instructions`
  - BenchForge additions for capability seeds and retrieval provenance
- [ ] Implement evaluation and judge schemas:
  - `ModelAnswer`
  - `JudgeRequest`
  - `JudgeResult`
  - `EvaluationRecord`
- [ ] Implement analysis schemas:
  - `CapabilityAnnotation`
  - `CapabilityTreeNode`
  - `WeaknessProfile`

Acceptance:

- Schema tests cover valid and invalid open-ended and multi-choice records.
- Multi-hop questions require `source_chunk_ids`; single-hop questions require `chunk_id`.

## Task 3: Artifact Store And Audit Layer

- [ ] Implement `ArtifactStore` for JSON and JSONL artifacts.
- [ ] Store artifact metadata consistently:
  - `artifact_id`
  - `artifact_type`
  - `producer`
  - `created_at`
  - `schema_version`
  - `upstream_refs`
- [ ] Implement a lightweight audit log for:
  - `run_id`
  - `round_id`
  - `task_id`
  - `agent_type`
  - `input_artifact_refs`
  - `output_artifact_refs`
  - token, latency, and cost summaries

Acceptance:

- Unit tests prove artifacts round-trip cleanly.
- A worker can append audit information without mutating prior artifacts.

## Task 4: Shared Runtime Layer

- [ ] Implement `model_runtime`:
  - request model
  - response model
  - retry and timeout handling
  - token and cost accounting hooks
- [ ] Implement `retrieval_runtime`:
  - Wikipedia search
  - page fetch
  - paragraph extraction
  - page metadata capture
  - saliency signals
- [ ] Implement `judge_runtime`:
  - judge prompt builder
  - structured output parsing
  - confidence field
  - second-review hook
- [ ] Implement `metrics` helpers for per-task aggregation.

Acceptance:

- Runtime unit tests mock provider calls and retrieval responses.
- Retrieval returns normalized `RetrievalDocument` records.
- Judge returns a typed `JudgeResult`, not raw free-form text.

## Task 5: PlannerAgent And Topic Planning

- [ ] Implement `PlannerAgent.create_initial_plan`.
- [ ] Implement `PlannerAgent.apply_result`.
- [ ] Make `create_initial_plan` return:
  - `BlueprintSpec`
  - initial `RunState`
  - initial `TaskSpec[]`
- [ ] Make `apply_result` consume:
  - `BlueprintSpec`
  - current `RunState`
  - `TaskResult`
  and emit:
  - updated `RunState`
  - next `TaskSpec[]`
- [ ] Implement topic-state tracking inspired by AutoBencher:
  - explored categories
  - excluded categories
  - target accuracy band
  - per-round summaries
- [ ] Implement `topic_planning.py` helpers for:
  - summarize-over-history input preparation
  - category proposal prompt preparation
  - category refinement prompt preparation
  - topic pruning and replay protection
- [ ] Ensure planner emits exactly these worker types:
  - `question_generator`
  - `question_validator`
  - `model_evaluator`
  - `analyzer`

Acceptance:

- Planner tests prove that generation follows planning, validation follows generation, evaluation follows validation, and analysis follows evaluation.
- Planner never retrieves documents directly.

## Task 6: QuestionGeneratorAgent And Retrieval-Driven Generation

- [ ] Implement `QuestionGeneratorAgent` around grouped input objects, not flat fields.
- [ ] Inside the agent, execute the retrieval-plus-generation flow:
  - read `TopicPlan`
  - retrieve Wikipedia pages
  - saliency rerank
  - normalize paragraphs
  - chunk evidence
  - optional multi-hop or cross-document combination
  - schema-driven LLM generation
  - structured parsing
  - candidate artifact writing
- [ ] Reuse YourBench-style prompt behavior:
  - `question_mode`
  - prompt template selection
  - optional `question_schema`
  - JSON array inside `<output_json>` tags
- [ ] Preserve YourBench-style output provenance fields in candidate records.
- [ ] Add BenchForge-specific fields:
  - `capability_seed_labels`
  - `capability_seed_description`
  - `retrieval_document_refs`
  - `saliency`

Acceptance:

- Unit tests cover single-hop and multi-hop generation paths.
- Candidate artifacts contain the required provenance fields and a standard answer.

## Task 7: QuestionValidatorAgent

- [ ] Implement deterministic schema validation.
- [ ] Implement answerability and evidence-grounding checks.
- [ ] Implement duplicate detection.
- [ ] Implement rejection taxonomy:
  - schema invalid
  - missing evidence
  - empty answer
  - duplicate
  - ambiguous
  - unsupported mode
- [ ] Optionally invoke `judge_runtime` only for ambiguity or answerability checks that cannot be resolved deterministically.

Acceptance:

- Validator tests distinguish accepted, rejected, and repairable cases.
- Rejection reasons are machine-readable enums, not free-form strings only.

## Task 8: Multi-Model Evaluation And Judge-First Scoring

- [ ] Implement `ModelEvaluatorAgent` for multiple target models per run.
- [ ] Separate model answering from judge scoring.
- [ ] Record:
  - raw model answer
  - judge verdict
  - judge confidence
  - exact-match result when applicable
  - latency
  - token usage
  - estimated cost
- [ ] Add per-model and cross-model aggregations:
  - accuracy
  - refusal rate
  - average judge score
  - disagreement rate

Acceptance:

- Unit tests show at least two models can be evaluated over the same validated questions.
- Judge artifacts are stored separately from evaluation artifacts.

## Task 9: AnalyzerAgent With EvalTree-Inspired Aggregation

- [ ] Implement `AnalyzerAgent` so that it does not re-label every question by default.
- [ ] Normalize generation-stage capability labels only as needed for aggregation.
- [ ] Implement an analysis pipeline inspired by EvalTree:
  - capability text preparation
  - optional embedding generation
  - recursive clustering
  - hierarchical description
  - per-node metric propagation
  - confidence interval computation
  - weak-subtree extraction
- [ ] Produce planner-facing recommendations:
  - weak capabilities
  - under-covered topic areas
  - low-discrimination regions

Acceptance:

- Analyzer tests verify tree construction over synthetic capability labels.
- Weakness extraction respects a minimum sample threshold and confidence-interval rule.

## Task 10: Orchestrator, CLI, And Full-Run Integration

- [ ] Implement `run_local` orchestration for the full worker loop.
- [ ] Add CLI commands for:
  - config validation
  - run execution
  - run summary inspection
- [ ] Support single-machine execution with controlled local concurrency.
- [ ] Write an integration test that exercises:
  - planner
  - retrieval-backed generation
  - validation
  - multi-model evaluation
  - analysis

Acceptance:

- Integration test writes a complete run report.
- CLI run produces a directory of artifacts and a summary report.

## Task 11: Verification, Docs, And Handoff

- [ ] Update `AGENTS.md` so the new full plan is the preferred implementation plan for BenchForge.
- [ ] Update `README.md` or add one if it does not exist.
- [ ] Verify the implementation with:
  - `pytest`
  - `ruff format --check .`
  - `ruff check .`
- [ ] Run one end-to-end example using a stubbed or fake runtime where external APIs are not available.
- [ ] Document any remaining gaps between the full design and the first executable version.

Acceptance:

- The repository contains a clear distinction between the old MVP plan and the new full implementation plan.
- The verification commands and end-to-end example are documented and reproducible.

## Final Verification Checklist

- [ ] `BlueprintSpec` remains fixed after initialization.
- [ ] `RunState` is the only mutable global run state.
- [ ] `PlannerAgent` is the only writer of `RunState`.
- [ ] Retrieval happens inside `QuestionGeneratorAgent` through `retrieval_runtime`.
- [ ] Question generation I/O preserves YourBench-style schema semantics.
- [ ] Topic planning reuses AutoBencher-style history summaries and category refinement ideas.
- [ ] Analysis reuses EvalTree-style tree construction and weakness extraction logic.
- [ ] Judge scoring is a shared runtime, not embedded ad hoc in evaluator logic.
- [ ] The plan does not require modifying `reference/`.
