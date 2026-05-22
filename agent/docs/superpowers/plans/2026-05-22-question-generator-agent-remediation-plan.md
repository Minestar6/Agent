# QuestionGeneratorAgent Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current `QuestionGeneratorAgent` behaviorally correct, aligned with the 2026-05-21 design spec, and runnable through the new `GenerationPlan` entrypoint.

**Architecture:** Fix the current state-machine bugs first, then repair data/metrics plumbing, then wire in missing `NextStepPlan` and retrieval-expansion loops. Keep the existing module split (`agents/`, `utils/`, `schemas/`, `prompts/`) and add focused tests around planning, round execution, evidence stats, and global backfill.

**Tech Stack:** Python 3.10+, Pydantic, pytest, pytest-asyncio, OpenAI-compatible chat models, requests, tiktoken

---

## File Map

- Modify: `benchforge/agents/question_generator.py`
  Purpose: main topic loop, round loop, evidence prep, question generation, next-step execution, report/save behavior.
- Modify: `benchforge/utils/planning.py`
  Purpose: plan compilation, gap detection, evidence stats update, request count calculation, next-step planning helpers.
- Modify: `benchforge/utils/multi_chunk.py`
  Purpose: correct summary-aware single-chunk construction and multi-chunk ranking inputs.
- Modify: `benchforge/utils/filter.py`
  Purpose: preserve candidate vs valid counts and normalize parsed outputs consistently.
- Modify: `benchforge/config/config.py`
  Purpose: support the new config surface (`model_list`, `model_roles`) or remove stale config drift.
- Modify: `benchforge/config/question_generator_config.yaml`
  Purpose: align example YAML with actual config model.
- Modify: `benchforge/models/loader.py`
  Purpose: provide the canonical path for constructing multi-model clients from config.
- Modify: `example_run.py`
  Purpose: switch demos to `GenerationPlan` instead of legacy `topic` API.
- Modify: `README.md`
  Purpose: update usage examples to the new API and config.
- Create: `tests/unit/test_question_generator_planning.py`
  Purpose: test plan compilation, round counting, and global backfill gap selection.
- Create: `tests/unit/test_question_generator_stats.py`
  Purpose: test candidate/valid stats separation and single/multi evidence stats updates.
- Create: `tests/unit/test_question_generator_next_step.py`
  Purpose: test `NextStepPlan` candidate-action generation and execution branching.
- Create: `tests/integration/test_question_generator_agent.py`
  Purpose: exercise the topic loop end-to-end with `FakeModelClient`.

### Task 1: Fix Round Counting And New API Surface

**Files:**
- Modify: `benchforge/agents/question_generator.py`
- Modify: `example_run.py`
- Modify: `README.md`
- Test: `tests/unit/test_question_generator_planning.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from benchforge.schemas import GenerationPlan, QuestionModeTarget
from benchforge.utils.planning import compile_generation_plan


def _plan() -> GenerationPlan:
    return GenerationPlan(
        run_id="run_test",
        goal="test",
        topics=["Fordism"],
        mode_targets={
            "qa": QuestionModeTarget(
                count=2,
                difficulty_distribution={"easy": 0.0, "medium": 1.0, "hard": 0.0},
            )
        },
        max_rounds_per_topic=2,
        max_total_rounds=4,
    )


def test_topic_state_starts_at_round_zero():
    states = compile_generation_plan(_plan())
    assert states["Fordism"].current_round == 0


@pytest.mark.asyncio
async def test_single_round_only_increments_once():
    from benchforge.agents.question_generator import QuestionGeneratorAgent
    from benchforge.models.fake import FakeModelClient

    agent = QuestionGeneratorAgent(model_client=FakeModelClient(delay=0))
    plan = _plan()
    agent.topic_states = compile_generation_plan(plan)
    await agent._prepare_evidence("Fordism", plan)
    await agent._run_generation_round("Fordism", plan)

    assert agent.topic_states["Fordism"].current_round == 1
    assert agent.total_rounds == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_question_generator_planning.py -v`
Expected: FAIL because the new tests do not exist yet and/or `current_round` is incremented twice.

- [ ] **Step 3: Implement the minimal fixes**

```python
# benchforge/agents/question_generator.py
# In _run_generation_round(), remove the eager state.current_round increment
# and leave only total_rounds increment here.
state = self.topic_states[topic]
pool = self.evidence_pools.get(topic)

if not pool or not pool.single_chunks:
    logger.warning(f"No evidence pool for topic: {topic}")
    state.current_round += 1
    self.total_rounds += 1
    return

self.total_rounds += 1
```

```python
# example_run.py
from benchforge.schemas import GenerationPlan, QuestionModeTarget

plan = GenerationPlan(
    run_id="fake_demo_001",
    goal="demo benchmark generation",
    topics=["Quantum Computing"],
    mode_targets={
        "qa": QuestionModeTarget(
            count=4,
            difficulty_distribution={"easy": 0.25, "medium": 0.5, "hard": 0.25},
        )
    },
    max_rounds_per_topic=2,
    max_total_rounds=4,
)

result = await agent.execute(plan)
```

```python
# README.md
# Replace execute(topic="...") examples with execute(plan)
# and document that QuestionGeneratorAgent now consumes GenerationPlan.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_question_generator_planning.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add benchforge/agents/question_generator.py example_run.py README.md tests/unit/test_question_generator_planning.py
git commit -m "fix: correct round counting and switch demos to generation plan"
```

### Task 2: Repair Evidence Stats And Summary-Aware Chunk Scoring

**Files:**
- Modify: `benchforge/agents/question_generator.py`
- Modify: `benchforge/utils/planning.py`
- Modify: `benchforge/utils/multi_chunk.py`
- Test: `tests/unit/test_question_generator_stats.py`

- [ ] **Step 1: Write the failing tests**

```python
from benchforge.schemas import EvidenceStats
from benchforge.utils.planning import update_evidence_stats


def test_update_evidence_stats_keeps_candidate_and_valid_counts_separate():
    stats = EvidenceStats()
    batch = {
        "candidate_count": 10,
        "valid_count": 4,
        "used_single_chunks": 2,
        "used_multi_chunks": 0,
        "single_mode_counts": {"qa": 4},
        "single_difficulty_counts": {"medium": 4},
        "multi_mode_counts": {},
        "multi_difficulty_counts": {},
    }

    updated = update_evidence_stats(stats, batch)
    assert updated.single_chunk_stats.avg_candidate_count == 5.0
    assert updated.single_chunk_stats.avg_valid_count == 2.0


def test_build_evidence_pool_from_chunks_uses_document_summary():
    from benchforge.schemas import SourceChunk
    from benchforge.utils.multi_chunk import build_evidence_pool_from_chunks

    chunk = SourceChunk(
        chunk_id="doc_1::chunk_0001",
        document_id="doc_1",
        chunk_index=0,
        text="Fordism is a system of mass production using assembly lines.",
        metadata={},
    )
    units = build_evidence_pool_from_chunks([chunk], "Fordism", document_summary="mass production and assembly line")
    assert units[0].mcq_score > 0
    assert units[0].qa_score > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_question_generator_stats.py -v`
Expected: FAIL because the stats path does not distinguish candidate vs valid and the summary is not passed into single-chunk construction.

- [ ] **Step 3: Implement the minimal fixes**

```python
# benchforge/agents/question_generator.py
# In _prepare_evidence(), build single units per document so document_summary is passed through.
single_units = []
for result in search_results:
    ...
    document_summary = await self._generate_document_summary(document, chunks)
    document_units = build_evidence_pool_from_chunks(chunks, topic, document_summary=document_summary)
    single_units.extend(document_units)
```

```python
# benchforge/agents/question_generator.py
# In _build_batch_info(), preserve raw candidate count before filtering
return {
    "candidate_count": raw_candidate_count,
    "valid_count": len(questions),
    "single_mode_counts": single_mode_counts,
    "single_difficulty_counts": single_difficulty_counts,
    "multi_mode_counts": multi_mode_counts,
    "multi_difficulty_counts": multi_difficulty_counts,
}
```

```python
# benchforge/utils/planning.py
# Update single and multi stats independently using separate per-type counts.
if batch.get("used_single_chunks", 0) > 0:
    ...
    stats.single_chunk_stats.mode_distribution[mode] = ...
if batch.get("used_multi_chunks", 0) > 0:
    ...
    stats.multi_chunk_stats.mode_distribution[mode] = ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_question_generator_stats.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add benchforge/agents/question_generator.py benchforge/utils/planning.py benchforge/utils/multi_chunk.py tests/unit/test_question_generator_stats.py
git commit -m "fix: separate evidence stats and pass summaries into chunk scoring"
```

### Task 3: Implement Restricted-Action NextStepPlan

**Files:**
- Modify: `benchforge/agents/question_generator.py`
- Modify: `benchforge/utils/planning.py`
- Test: `tests/unit/test_question_generator_next_step.py`

- [ ] **Step 1: Write the failing tests**

```python
from benchforge.schemas import NextStepAction, TopicState, TopicStatus
from benchforge.utils.planning import build_allowed_actions, build_next_step_plan


def test_allowed_actions_include_expand_retrieval_for_hard_gap():
    state = TopicState(
        topic="Fordism",
        status=TopicStatus.ACTIVE,
        current_round=1,
        target_counts={"qa:hard": 3},
        completed_counts={"qa:hard": 0},
        remaining_counts={"qa:hard": 3},
        retrieved_documents=["doc_1"],
        available_single_chunk_ids=["c1"],
        available_multi_chunk_ids=[],
    )
    actions = build_allowed_actions(state, max_rounds_per_topic=4)
    assert NextStepAction.EXPAND_RETRIEVAL in actions


def test_build_next_step_plan_returns_structured_action():
    plan = build_next_step_plan(
        topic="Fordism",
        target_gap="qa:hard",
        allowed_actions=["continue_generation", "expand_retrieval"],
        prefer_multi_chunk=False,
    )
    assert plan.action in {"continue_generation", "expand_retrieval"}
    assert plan.topic == "Fordism"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_question_generator_next_step.py -v`
Expected: FAIL because no next-step planning helpers exist yet.

- [ ] **Step 3: Implement the minimal planning loop**

```python
# benchforge/utils/planning.py
from benchforge.schemas import NextStepAction, NextStepPlan


def build_allowed_actions(state: TopicState, max_rounds_per_topic: int) -> list[NextStepAction]:
    actions = [NextStepAction.CONTINUE_GENERATION]
    if any(key.endswith(":hard") and value > 0 for key, value in state.remaining_counts.items()):
        actions.append(NextStepAction.INCREASE_MULTI_CHUNK_RATIO)
        actions.append(NextStepAction.ENABLE_HARDENING)
        actions.append(NextStepAction.EXPAND_RETRIEVAL)
    if state.current_round + 1 >= max_rounds_per_topic:
        actions.append(NextStepAction.DEFER_TOPIC)
    return actions


def build_next_step_plan(topic: str, target_gap: str, allowed_actions: list[str], prefer_multi_chunk: bool) -> NextStepPlan:
    if "expand_retrieval" in allowed_actions and target_gap.endswith(":hard") and not prefer_multi_chunk:
        return NextStepPlan(topic=topic, action=NextStepAction.EXPAND_RETRIEVAL, target_gap=target_gap, reason="hard gap persists")
    return NextStepPlan(topic=topic, action=NextStepAction.CONTINUE_GENERATION, target_gap=target_gap, reason="continue with current evidence")
```

```python
# benchforge/agents/question_generator.py
# After stats update, build and execute next plan before leaving the round.
allowed_actions = build_allowed_actions(state, plan.max_rounds_per_topic)
next_plan = build_next_step_plan(topic, gap_key, [a.value for a in allowed_actions], prefer_multi_chunk=False)
await self._execute_next_step_plan(next_plan, plan)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_question_generator_next_step.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add benchforge/agents/question_generator.py benchforge/utils/planning.py tests/unit/test_question_generator_next_step.py
git commit -m "feat: add restricted-action next step planning"
```

### Task 4: Add Retrieval Expansion And Hardening Execution

**Files:**
- Modify: `benchforge/agents/question_generator.py`
- Modify: `benchforge/utils/retrieval.py`
- Test: `tests/integration/test_question_generator_agent.py`

- [ ] **Step 1: Write the failing integration test**

```python
import pytest

from benchforge.agents.question_generator import QuestionGeneratorAgent
from benchforge.models.fake import FakeModelClient
from benchforge.schemas import GenerationPlan, QuestionModeTarget


@pytest.mark.asyncio
async def test_agent_can_finish_topics_with_generation_plan():
    agent = QuestionGeneratorAgent(model_client=FakeModelClient(delay=0))
    plan = GenerationPlan(
        run_id="run_it",
        goal="integration",
        topics=["Fordism"],
        mode_targets={
            "qa": QuestionModeTarget(
                count=2,
                difficulty_distribution={"easy": 0.5, "medium": 0.5, "hard": 0.0},
            )
        },
        max_rounds_per_topic=2,
        max_total_rounds=4,
    )

    report = await agent.execute(plan)
    assert report.status in {"completed", "partial"}
    assert "qa:easy" in report.final_counts or "qa:medium" in report.final_counts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_question_generator_agent.py -v`
Expected: FAIL until the new plan-based execution path, retrieval fallback, and hardening hooks are stable enough to complete the loop.

- [ ] **Step 3: Implement retrieval expansion and hardening execution**

```python
# benchforge/agents/question_generator.py
async def _execute_next_step_plan(self, next_plan: NextStepPlan, plan: GenerationPlan) -> None:
    if next_plan.action == NextStepAction.EXPAND_RETRIEVAL:
        await self._expand_retrieval(next_plan.topic, next_plan.retrieval_expansion_queries or [next_plan.topic], plan)
    elif next_plan.action == NextStepAction.INCREASE_MULTI_CHUNK_RATIO:
        self._topic_preferences[next_plan.topic]["prefer_multi_chunk"] = True
    elif next_plan.action == NextStepAction.ENABLE_HARDENING:
        self._topic_preferences[next_plan.topic]["additional_instructions"] = next_plan.additional_instructions
```

```python
# benchforge/agents/question_generator.py
async def _expand_retrieval(self, topic: str, queries: list[str], plan: GenerationPlan) -> None:
    collected_chunks = []
    for query in queries:
        results = search_wikipedia(query=query, language=plan.language, max_pages=2)
        for result in results:
            document = fetch_wikipedia_page(result=result, run_id=plan.run_id, language=plan.language, content_max_length=self.config.retrieval.content_max_length)
            if document.status.value == "failed":
                continue
            chunks = chunk_document(document=document, chunk_size=self.config.chunking.chunk_size, overlap=self.config.chunking.overlap)
            summary = await self._generate_document_summary(document, chunks)
            collected_chunks.extend(build_evidence_pool_from_chunks(chunks, topic, document_summary=summary))
    self.evidence_pools[topic].single_chunks.extend(collected_chunks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_question_generator_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add benchforge/agents/question_generator.py benchforge/utils/retrieval.py tests/integration/test_question_generator_agent.py
git commit -m "feat: execute retrieval expansion and hardening plans"
```

### Task 5: Fix Global Backfill And Persist Agent Artifacts

**Files:**
- Modify: `benchforge/agents/question_generator.py`
- Modify: `benchforge/utils/planning.py`
- Test: `tests/unit/test_question_generator_planning.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_global_backfill_should_choose_largest_mode_difficulty_gap():
    from benchforge.schemas import TopicState, TopicStatus
    from benchforge.utils.planning import identify_global_gap

    states = {
        "Fordism": TopicState(
            topic="Fordism",
            status=TopicStatus.DEFERRED,
            target_counts={"qa:hard": 3},
            completed_counts={"qa:hard": 1},
            remaining_counts={"qa:hard": 2},
        ),
        "Taylorism": TopicState(
            topic="Taylorism",
            status=TopicStatus.DEFERRED,
            target_counts={"multiple_choice:medium": 5},
            completed_counts={"multiple_choice:medium": 4},
            remaining_counts={"multiple_choice:medium": 1},
        ),
    }

    gap_key, topics = identify_global_gap(states)
    assert gap_key == "qa:hard"
    assert topics == ["Fordism"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_question_generator_planning.py::test_global_backfill_should_choose_largest_mode_difficulty_gap -v`
Expected: FAIL because current backfill uses total topic gap only.

- [ ] **Step 3: Implement the backfill selector and artifact persistence**

```python
# benchforge/utils/planning.py
def identify_global_gap(topic_states: dict[str, TopicState]) -> tuple[str | None, list[str]]:
    gap_totals: dict[str, int] = {}
    gap_topics: dict[str, list[str]] = {}
    for topic, state in topic_states.items():
        for key, remaining in state.remaining_counts.items():
            if remaining <= 0:
                continue
            gap_totals[key] = gap_totals.get(key, 0) + remaining
            gap_topics.setdefault(key, []).append(topic)
    if not gap_totals:
        return None, []
    best_key = sorted(gap_totals.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return best_key, gap_topics[best_key]
```

```python
# benchforge/agents/question_generator.py
# Save additional artifacts
self.artifact_store.save_json("topic_states.json", {k: v.model_dump() for k, v in self.topic_states.items()})
self.artifact_store.save_json("evidence_stats.json", {k: v.stats.model_dump() for k, v in self.evidence_pools.items()})
self.artifact_store.save_json("generation_report.json", report.model_dump())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_question_generator_planning.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add benchforge/agents/question_generator.py benchforge/utils/planning.py tests/unit/test_question_generator_planning.py
git commit -m "fix: drive global backfill by mode difficulty gaps and persist agent artifacts"
```

## Self-Review

- Spec coverage:
  - Round-count bug: covered by Task 1.
  - New `GenerationPlan` API drift: covered by Task 1.
  - Evidence stats correctness and summary-aware scoring: covered by Task 2.
  - `NextStepPlan` loop integration: covered by Task 3.
  - Retrieval expansion / hardening execution: covered by Task 4.
  - Global backfill and spec artifacts: covered by Task 5.
- Placeholder scan:
  - No `TODO/TBD` placeholders remain in task steps.
  - Each task includes concrete files, tests, commands, and code snippets.
- Type consistency:
  - `GenerationPlan`, `QuestionModeTarget`, `TopicState`, `NextStepPlan`, and `GenerationReport` naming matches the current codebase and spec.

Plan complete and saved to `docs/superpowers/plans/2026-05-22-question-generator-agent-remediation-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
