# BenchForge Technical Design

BenchForge is a planned multi-agent framework for automatically building and evaluating LLM benchmarks. This document refines the current `docs/plan.md` and `docs/multi-agent-framework-design.md` into an implementation-oriented technical design.

The current repository is still a planning and reference workspace. There is no production package yet. The implementation should create a new BenchForge codebase at the repository root and treat all code under `reference/` as read-only reference material.

## 1. Reference Implementation Audit

### 1.1 YourBench

Local path: `reference/code/yourbench`

YourBench is the strongest implementation reference for BenchForge's document-to-question pipeline.

Reusable ideas:

- `conf/schema.py`: Pydantic configuration models with defaults and validation.
- `conf/loader.py`: YAML loading, environment expansion, stage enablement by presence, prompt loading, and model-role assignment.
- `pipeline/handler.py`: ordered stage execution through a stage registry.
- `pipeline/ingestion.py`: Markdown/text/HTML/PDF ingestion, optional LLM PDF extraction, and document metadata capture.
- `pipeline/summarization.py`: token-aware hierarchical summarization.
- `pipeline/chunking.py`: token chunking, deterministic chunk IDs, and multi-hop chunk combination sampling.
- `pipeline/question_generation/_core.py`: shared single-hop, multi-hop, and cross-document generation flow.
- `utils/question_schemas.py`: default Pydantic schemas for open-ended and multiple-choice questions.
- `utils/schema_loader.py` and `utils/schema_prompt_generator.py`: custom output schema loading and prompt instruction generation.
- `utils/parsing_engine.py`: robust parsing from `<output_json>` tags, fenced JSON, and best-effort JSON candidates.
- `utils/inference/inference_core.py`: async model calls, per-model concurrency, retry/backoff, token accounting, and metrics.
- `pipeline/prepare_lighteval.py`: merge question subsets into one evaluation-ready dataset with source traceability.
- `pipeline/citation_score_filtering.py`: fuzzy citation grounding score.
- `utils/dataset_engine.py`: local/Hugging Face dataset save/load, subset management, and JSONL export.

Parts to adapt, not copy directly:

- YourBench is pipeline-centric, while BenchForge needs planner-driven iterative execution.
- YourBench stores stage output as dataset subsets. BenchForge should store artifacts as typed records and allow task-level references.
- YourBench question generation I/O should be reused more literally than the earlier draft assumed. BenchForge should preserve the schema-driven generation contract built around `question_mode`, prompt templates, `question_schema`, parsed JSON rows, and `QuestionRow`-style provenance fields such as `document_id`, `chunk_id` or `source_chunk_ids`, `thought_process`, `raw_response`, `citations`, and `generating_model`.
- Generation-time capability labels should be preserved as the primary basis for later analysis to control cost. Analyzer should only normalize or aggregate them unless a future extension explicitly enables relabeling.
- YourBench question validation is mostly schema and parsing oriented. BenchForge needs a dedicated validation agent with explicit rejection reasons and batch metrics.

### 1.2 AutoBencher

Local path: `reference/code/AutoBencher`

AutoBencher is the strongest implementation reference for iterative topic exploration and feedback-driven benchmark generation.

Reusable ideas:

- `wiki_autobencher.py:get_summary_of_results`: aggregate evaluation results by category.
- `wiki_autobencher.py:summarize_over_history`: turn previous rounds into planner context.
- `wiki_autobencher.py:_generate_categories_targetacc_augmented`: propose categories aimed at a target accuracy band.
- `wiki_autobencher.py:_refine_categories_targetacc_augmented`: expand LLM-proposed categories through Wikipedia search results and refine them.
- `wiki_autobencher.py:generate_full_qa`: iterative flow from category plan to page retrieval, salience ranking, QA generation, model testing, and history update.
- `wiki_autobencher.py:saliency_rerank`: use pageviews as an importance signal.
- `multilingual_autobencher.py`: category plus target-language planning and translation.
- `math_autobencher.py`: target-accuracy subcategory planning and tool-assisted answer generation.
- `tool_util.py:search_related_pages` and `search_step`: Wikipedia search/page retrieval pattern.
- `tool_util.py:test_taker_inference` and `fast_compare_answers`: test-taker evaluation plus judge-model comparison.

Parts to avoid:

- `tool_util.py` contains hardcoded Wikimedia credentials. Do not reuse secrets or copy that code as-is.
- Scripts rely on hardcoded cache paths, ad hoc output files, and direct `os.system` orchestration.
- JSON parsing relies on brittle code-block extraction. BenchForge should use Pydantic validation and structured LLM outputs.
- Model/provider handling is mixed with experiment logic. BenchForge should isolate provider calls behind a model client interface.

### 1.3 EvalTree

Local path: `reference/code/EvalTree`

EvalTree is the strongest implementation reference for capability annotation, capability tree construction, confidence intervals, and weakness profile extraction.

Reusable ideas:

- `EvalTree/stage1-CapabilityAnnotation/annotate.py`: annotate each benchmark instance with a capability description.
- `EvalTree/stage2-CapabilityEmbedding/embedding.py`: embed capability descriptions.
- `EvalTree/stage3-RecursiveClustering/build.py`: recursively cluster capability embeddings into a tree, selecting cluster count by cosine silhouette score.
- `EvalTree/stage4-CapabilityDescription/describe.py`: recursively summarize child capabilities into parent capability descriptions.
- `EvalTree/WeaknessProfile/confidence_interval.py`: compute node-level performance and binomial confidence intervals.
- `EvalTree/WeaknessProfile/extract_subtrees.py`: extract the most specific low-performing subtree nodes.
- `EvalTree/WeaknessProfile/profile-generation_varying-threshold.py`: generate weakness profiles across thresholds.
- `EvalTree/stage3-RecursiveClustering/locate.py`: locate new instances in an existing capability tree by embedding and cluster prediction.

Parts to adapt:

- EvalTree assumes benchmark instances and results already exist in fixed dataset folders. BenchForge should generate these artifacts during execution.
- EvalTree tree nodes are stored as raw nested dicts with pickled KMeans objects. BenchForge should wrap the tree in explicit typed models and keep serialized metadata predictable.
- EvalTree's analysis is post-hoc. BenchForge should expose analysis results back to the planner as coverage gaps and recommended next tasks.

### 1.4 BenchAgents

Local path: `reference/paper/BenchAgents.pdf`

No local BenchAgents code implementation is present. In this repository, BenchAgents should be treated as the conceptual reference for multi-agent, multi-round benchmark construction rather than a source of reusable code.

The local environment does not currently include `pdftotext` or Python PDF parsing libraries, and `BenchAgents.pdf` did not expose useful plaintext through the available local tooling. Implementation planning should therefore treat BenchAgents as a conceptual reference only, while grounding actual engineering decisions in the inspectable code from YourBench, AutoBencher, and EvalTree.

## 2. Target Architecture

BenchForge should use a strong central planner with bounded local autonomy for worker agents.

```text
UserRequest
  -> PlannerAgent creates or updates Blueprint
  -> Orchestrator dispatches TaskSpec
  -> Worker agents return TaskResult
  -> PlannerAgent updates Blueprint
  -> Repeat until stop conditions or final report
```

Core architectural rule:

- `Blueprint` is the only global state source.
- Only `PlannerAgent` can mutate `Blueprint`.
- Worker agents receive task-scoped inputs and artifact references.
- Worker agents return `TaskResult`; they may recommend next actions but cannot directly schedule global work.

### 2.1 Reference-Grounded Corrections

The earlier draft was directionally correct but too generic in several places. The following corrections should be treated as authoritative:

- `PlannerAgent` owns topic optimization, round advancement, budget control, and stop conditions. It does not retrieve pages directly.
- Retrieval is not a standalone first-class agent in the current design. Instead, retrieval lives in a shared `retrieval_runtime`, and `QuestionGeneratorAgent` invokes it while executing a generation task.
- `QuestionGeneratorAgent` inputs should be grouped into structured objects rather than a flat collection of top-level fields. This is necessary to stay close to YourBench's `stage_cfg + dataset subset` pattern and to keep schema validation manageable.
- `QuestionGeneratorAgent` outputs should reuse the field semantics already present in YourBench `QuestionRow`, then add BenchForge-specific provenance and capability fields on top.
- Generation-time capability labels are the default basis for later analysis. `AnalyzerAgent` should aggregate and normalize those labels, not re-annotate every question by default.
- `ModelEvaluatorAgent` is responsible for collecting model answers and invoking a shared `judge_runtime`. The judge layer must be treated as reusable infrastructure, not embedded ad hoc inside evaluator logic.
- EvalTree-inspired analysis remains post-hoc and aggregate. BenchForge should adapt its tree construction and weakness extraction logic, but not impose a second full per-question capability-labeling pass by default.

Recommended package layout:

```text
benchforge/
  __init__.py
  cli.py
  config.py
  orchestrator.py
  agents/
    __init__.py
    planner.py
    question_generator.py
    question_validator.py
    model_evaluator.py
    analyzer.py
  artifacts/
    __init__.py
    store.py
  models/
    __init__.py
    client.py
    fake.py
  pipelines/
    __init__.py
    documents.py
    questions.py
    evaluation.py
    analysis.py
  schemas/
    __init__.py
    artifact.py
    blueprint.py
    question.py
    task.py
  prompts/
    question_generation.md
    question_validation.md
    answer_judging.md
    capability_annotation.md
tests/
  unit/
  integration/
```

## 3. Core Data Contracts

BenchForge should implement the contracts with Pydantic v2. Use explicit enums for stable machine-readable values.

### 3.1 BlueprintSpec

`BlueprintSpec` is the fixed plan specification for one run. It should be treated as nearly immutable after initialization and should contain only user intent, system policies, and upper-bound constraints.

Required sections:

- `blueprint_spec_id`: stable spec ID.
- `user_goal`: normalized user goal.
- `evaluation_scope`: domains, target languages, target models, source strategy, and allowed reasoning types.
- `source_policy`: web retrieval mode, retrieval limits, allowlist/denylist, and source ranking policy.
- `dataset_policy`: target question count, per-round count, distributions, deduplication, and minimum pass rate.
- `question_policy`: allowed question types, answer format, citation rules, rubric requirements, and length limits.
- `capability_policy`: taxonomy source, label granularity, label normalization rules, and minimum samples per capability.
- `validation_policy`: schema, answerability, uniqueness, citation, deduplication, and repair rules.
- `evaluation_policy`: metrics, judge model, repetitions, generation parameters, and failure handling.
- `analysis_policy`: tree construction, weakness extraction, thresholds, and report formats.
- `budget_policy`: token, cost, wall-clock, model call, and per-task upper limits.
- `iteration_policy`: maximum rounds, topic expansion/pruning, stop-condition rules, and information-gain threshold.
- `stop_conditions`: machine-readable stop-condition definitions.

### 3.2 RunState

`RunState` is the only mutable global state for a run. It records everything that changes as the system executes.

Required sections:

- `run_id`: stable run ID.
- `blueprint_spec_id`: reference to the fixed `BlueprintSpec`.
- `status`: `draft`, `running`, `paused`, `completed`, or `failed`.
- `current_round`: current round number.
- `explored_topics`: structured records of explored topics, not just strings.
- `excluded_topics`: topics pruned or blocked from further exploration.
- `topic_queue`: planner-selected future topic candidates.
- `retrieved_pages`: retrieved-page summaries or refs.
- `shared_artifacts`: artifact references visible to future tasks.
- `global_metrics`: coverage, validation, evaluation, cost, latency, and error metrics.
- `weak_capabilities`: currently identified weak capability areas.
- `budget_usage`: tokens, cost, time, and call counts consumed so far.
- `decision_log`: planner decisions with rationale and input result IDs.
- `latest_task_results`: refs or summaries for the latest worker outputs.
- `next_actions`: planner-selected upcoming actions.

Recommended supporting sub-objects:

- `ExploredTopic`
- `CoverageSummary`
- `BudgetUsage`
- `DecisionRecord`

Design rule:

- `BlueprintSpec` is the fixed truth for policies and target constraints.
- `RunState` is the mutable truth for execution progress.
- `PlannerAgent` reads `BlueprintSpec + RunState + TaskResult` and emits `TaskSpec + updated RunState`.

### 3.3 TaskSpec

`TaskSpec` is a single executable assignment from PlannerAgent to one worker.

Required fields:

- `task_id`
- `run_id`
- `blueprint_spec_id`
- `round_id`
- `agent_type`
- `objective`
- `inputs`
- `constraints`
- `acceptance_criteria`
- `output_schema`
- `budget`
- `priority`
- `depends_on`
- `retry_policy`
- `return_requirements`

TaskSpec should include only the data needed for that task. It should use artifact IDs instead of embedding full datasets whenever possible.

### 3.4 TaskResult

`TaskResult` is the only worker-to-planner feedback object.

Required fields:

- `task_id`
- `run_id`
- `blueprint_spec_id`
- `round_id`
- `agent_type`
- `status`
- `summary`
- `produced_artifacts`
- `metrics`
- `issues`
- `recommendations`
- `evidence`
- `needs_replan`
- `suggested_next_tasks`

`needs_replan` should be true when the worker believes the planner should reconsider the current route. Examples include low validation pass rate, exhausted source documents, failed model calls, insufficient capability coverage, or low-confidence weakness analysis.

## 4. Artifact Model

BenchForge should store task outputs as typed artifacts. The single-machine implementation can use JSON and JSONL files under `runs/<run_id>/artifacts/`.

Recommended artifact types:

| Artifact | Producer | Consumer | Notes |
| --- | --- | --- | --- |
| `RetrievalDocument` | `retrieval_runtime` via QuestionGenerator | QuestionGenerator, Validator | Normalized Wikipedia page content, metadata, and saliency |
| `DocumentChunk` | QuestionGenerator document pipeline | QuestionGenerator | Deterministic chunk with source trace |
| `TopicPlan` | PlannerAgent | QuestionGenerator | AutoBencher-style category, target-accuracy, language, and exclusion instructions |
| `CandidateQuestion` | QuestionGenerator | QuestionValidator, Analyzer | YourBench-like question row plus capability seed labels |
| `ValidatedQuestion` | QuestionValidator | ModelEvaluator, Analyzer | Accepted question with validation record |
| `RejectedQuestion` | QuestionValidator | PlannerAgent | Rejection reason and repairability |
| `EvaluationRecord` | ModelEvaluator | Analyzer, PlannerAgent | Per-model, per-question answer and judge result |
| `JudgeRecord` | `judge_runtime` via ModelEvaluator | ModelEvaluator, Analyzer | Structured judge verdict, rationale, and confidence |
| `CapabilityAnnotation` | Analyzer | Analyzer | Aggregate capability mapping or normalized label set |
| `CapabilityTree` | Analyzer | PlannerAgent, report output | Typed tree model |
| `WeaknessProfile` | Analyzer | PlannerAgent, report output | Low-performing capability nodes |
| `RunReport` | PlannerAgent or Analyzer | User | Final summary |

## 5. Agent Responsibilities And I/O

### 5.1 PlannerAgent

Purpose:

- Convert user request into `BlueprintSpec` and initial `RunState`.
- Select the next task sequence.
- Incorporate `TaskResult` into updated `RunState`.
- Decide whether to continue, retry, regenerate, evaluate, analyze, or stop.

Inputs:

- User request.
- Current `BlueprintSpec`.
- Current `RunState`, if continuing a run.
- New `TaskResult` objects.

Outputs:

- `BlueprintSpec` on first initialization.
- Updated `RunState`.
- One or more `TaskSpec` objects.
- Final `RunReport` when stopping.

Core workflow:

1. Normalize user request into `BlueprintSpec`.
2. Create initial `RunState` with round `1`, empty explored-topic history, zeroed budget usage, and initial next actions.
3. Create initial topic plan using domains, target models, target languages, and source policy.
4. Dispatch question generation for the first round.
5. After validation, compare accepted question metrics against dataset policy and write results into `RunState`.
6. After evaluation and analysis, update explored-topic history, weak-capability summaries, budget usage, and next topic targets in `RunState`.
7. Stop when target count, coverage, budget, or information-gain conditions are met.

### 5.2 QuestionGeneratorAgent

Purpose:

- Execute the retrieval-plus-generation task for the current topic plan.
- Retrieve Wikipedia content through shared runtime utilities.
- Normalize source text, select evidence, and generate candidate questions.
- Produce standard answers, source evidence, and capability seed labels in one pass.

Inputs:

- `TopicPlan` artifact ID.
- `QuestionGenerationInput`, grouped into:
  - `topic_context`: target categories, target accuracy band, excluded topics, planner hints.
  - `retrieval_input`: language, max pages, saliency policy, excluded page titles, source policy.
  - `evidence_input`: chunking policy, cross-document policy, max chunks, evidence selection strategy.
  - `generation_input`: question mode, target count, question schema, prompt template IDs, additional instructions.
  - `output_control`: required evidence, required capability labels, structured-output requirement.
- Shared generation policies from `BlueprintSpec` and current context from `RunState`.

Outputs:

- `RetrievalDocument` artifacts.
- `DocumentChunk` artifacts.
- `CandidateQuestion` artifacts.
- Generation metrics and issue list.

Recommended workflow:

1. Read the current `TopicPlan` and retrieval settings from the task input.
2. Use `retrieval_runtime` to search and fetch Wikipedia pages relevant to the planned categories.
3. Normalize pages into `RetrievalDocument` artifacts and attach saliency signals such as pageviews.
4. Chunk evidence deterministically and, when enabled, build multi-hop or cross-document combinations.
5. Build schema-driven prompts using YourBench-style `question_mode`, prompt templates, and `question_schema`.
6. Call `model_runtime` and parse the JSON array output.
7. Convert each parsed row into a BenchForge candidate question record that preserves YourBench-style fields:
   - `question`
   - `answer` or `self_answer`
   - `estimated_difficulty`
   - `question_type` or `self_assessed_question_type`
   - `question_mode`
   - `thought_process`
   - `citations`
   - `choices` when `question_mode == "multi-choice"`
   - `document_id`
   - `chunk_id` or `source_chunk_ids`
   - `generating_model`
   - `raw_response`
   - `additional_instructions`
8. Add BenchForge-specific fields such as `capability_seed_labels`, `capability_seed_description`, retrieval provenance, and artifact lineage.
9. Save artifacts and return a `TaskResult` with retrieved-page counts, generated-question counts, and failure reasons.

Reference mapping:

- Document processing: YourBench `ingestion.py`.
- Summarization/chunking: YourBench `summarization.py` and `chunking.py`.
- Generation prompts and schemas: YourBench `question_schemas.py`, `schema_prompt_generator.py`, and `question_generation/_core.py`.
- Topic/source expansion: AutoBencher `wiki_autobencher.py` and `tool_util.py`.

### 5.3 QuestionValidatorAgent

Purpose:

- Serve as the question quality gate.
- Produce accepted, rejected, and repairable question sets.

Inputs:

- `CandidateQuestion` artifact IDs.
- Current `validation_policy`.
- Existing accepted question summaries.
- Source documents/chunks needed for evidence checks.

Outputs:

- `ValidatedQuestion` artifacts.
- `RejectedQuestion` artifacts.
- Batch validation metrics.
- Replan recommendations if pass rate or coverage is poor.

Validation checks:

- Required fields present.
- Question mode matches allowed type.
- Multiple choice questions have exactly four choices and a valid answer letter.
- Open-ended answers are non-empty and not just a multiple-choice label.
- Source evidence exists and overlaps with source chunks.
- Question is answerable from supplied evidence.
- Question is not a near-duplicate.
- Difficulty, language, domain, and candidate capabilities match task constraints.

Reference mapping:

- Schema and parsing checks: YourBench `QuestionRow`, `parsing_engine.py`.
- Citation grounding: YourBench `citation_score_filtering.py`.

### 5.4 ModelEvaluatorAgent

Purpose:

- Run target models on validated questions.
- Score predictions.
- Return per-question and aggregate metrics.

Inputs:

- `ValidatedQuestion` artifact IDs.
- Target model configs.
- Evaluation policy.
- Judge prompt and rubric, if needed.

Outputs:

- `EvaluationRecord` artifacts.
- Per-model metrics.
- Per-domain, per-language, per-question-type, and per-candidate-capability summaries.
- Cost, token, latency, and failure statistics.

Recommended workflow:

1. Build model prompts from validated questions.
2. Run target model inference with concurrency and retry policy.
3. Score exact-match questions directly where possible.
4. Use judge model for semantic open-ended scoring.
5. Normalize outcomes into `EvaluationRecord`.
6. Aggregate metrics for the planner and analyzer.

Reference mapping:

- Model calls and metrics: YourBench `inference_core.py`.
- Answer judging and history summary: AutoBencher `fast_compare_answers`, `get_summary_of_results`.

### 5.5 AnalyzerAgent

Purpose:

- Aggregate evaluation results over the capability labels produced during generation.
- Build capability trees and weakness profiles using EvalTree-inspired logic.
- Recommend next topics, capability slices, or under-covered areas to PlannerAgent.

Inputs:

- `ValidatedQuestion` artifact IDs.
- `EvaluationRecord` artifact IDs.
- Candidate capability labels from generation.
- Current `analysis_policy`.

Outputs:

- `CapabilityAnnotation` artifacts.
- `CapabilityTree` artifact.
- `WeaknessProfile` artifact.
- Coverage gaps and recommended next focus areas.

Recommended workflow:

1. Read validated questions, evaluation records, and generation-stage capability labels.
2. Normalize capability labels only as needed for aggregation, such as synonym collapse, casing normalization, or planner-specified taxonomy mapping.
3. Build capability-description and capability-embedding artifacts if tree construction is enabled.
4. Reuse EvalTree-style recursive clustering and hierarchical description generation to build a typed capability tree.
5. Attach evaluation outcomes to leaves and propagate metrics up the tree.
6. Compute per-node performance and confidence intervals.
7. Extract low-performing or low-coverage subtrees using thresholded confidence-interval logic.
8. Return planner-facing recommendations about weak capabilities, over-sampled areas, and under-covered topic regions.

Reference mapping:

- Capability annotation: EvalTree `stage1-CapabilityAnnotation/annotate.py`.
- Embedding: EvalTree `stage2-CapabilityEmbedding/embedding.py`.
- Tree construction: EvalTree `stage3-RecursiveClustering/build.py`.
- Node description: EvalTree `stage4-CapabilityDescription/describe.py`.
- Confidence intervals and weakness extraction: EvalTree `WeaknessProfile`.

## 6. End-To-End Workflow

### 6.1 Initial Run

```text
UserRequest
  -> PlannerAgent creates Blueprint v1
  -> PlannerAgent emits TaskSpec(question_generator)
  -> QuestionGeneratorAgent produces CandidateQuestion artifacts
  -> PlannerAgent emits TaskSpec(question_validator)
  -> QuestionValidatorAgent produces ValidatedQuestion and RejectedQuestion artifacts
  -> PlannerAgent decides whether enough valid questions exist
  -> PlannerAgent emits TaskSpec(model_evaluator)
  -> ModelEvaluatorAgent produces EvaluationRecord artifacts
  -> PlannerAgent emits TaskSpec(analyzer)
  -> AnalyzerAgent produces CapabilityTree and WeaknessProfile artifacts
  -> PlannerAgent updates Blueprint and either starts next round or emits RunReport
```

### 6.2 Replanning Loop

PlannerAgent should replan when any of these happen:

- Valid question count is below the per-round target.
- Validation pass rate is below `validation_policy.min_batch_pass_rate`.
- Source retrieval produces too few usable documents.
- Evaluation failure rate exceeds policy.
- A domain/language/question-type distribution misses target ratios.
- Analyzer finds capability nodes with too few samples.
- Weakness profile indicates a target area for more probing.
- Budget is close to exhaustion.

AutoBencher-style target accuracy bands should live in `topic_state`. For example, the planner may request more questions in domains where observed accuracy is above target by raising difficulty, or below target by narrowing to easier subtopics.

## 7. Implementation Principles

- Keep reference code read-only.
- Use Pydantic v2 for every cross-agent contract.
- Store artifacts locally first; add Hugging Face integration after the MVP.
- Use deterministic fake model clients in unit and integration tests.
- Keep LLM prompts versioned in `benchforge/prompts/`.
- Separate model-provider code from agent logic.
- Do not copy AutoBencher's hardcoded credentials, direct output file conventions, or shell orchestration.
- Treat generation-time capability labels as candidates.
- Make every planner update auditable through `decision_log`.
- Prefer small, typed modules over one large orchestration script.

## 8. MVP Scope

The first implementation should build a local-only MVP:

- CLI accepts a YAML config and local documents.
- Planner creates a `Blueprint`.
- QuestionGenerator supports local `.md` and `.txt` documents.
- QuestionValidator performs deterministic schema, citation, and duplicate checks.
- ModelEvaluator supports fake models for tests and an OpenAI-compatible client interface for real runs.
- Analyzer produces simple capability coverage and weakness summaries, then extends to EvalTree-like clustering in a later task.
- Artifacts are saved under `runs/<run_id>/artifacts/`.

Defer until after MVP:

- Full web retrieval.
- Hugging Face dataset upload.
- PDF/HTML/Word ingestion.
- Full EvalTree KMeans persistence and cross-run tree location.
- UI or dashboard.
- Distributed execution.
