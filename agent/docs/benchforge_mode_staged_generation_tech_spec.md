# BenchForge Mode-Staged Adaptive Chunk Generation Agent - Technical Specification

## 0. Overview

This document describes the final simplified implementation plan for the BenchForge question generation agent.

The agent is a **blueprint-guided, mode-staged, adaptive chunk-sampling candidate generation agent**.

It does **not** directly produce the final benchmark. Instead, it builds candidate question pools for each question type. Downstream validation agents are responsible for strict validation, answer checking, deduplication, difficulty calibration, and final benchmark selection.

Core idea:

> Generate each question type in a separate stage. Within each stage, first perform broad topic coverage, then adaptively supplement weak difficulties and topics. Store candidates by question type, but track evidence/chunk usage globally to avoid repeated chunk combinations across question types.

---

## 1. Design Goals

### 1.1 What this agent does

The generation agent:

1. Reads a benchmark blueprint.
2. Prepares evidence chunks for all topics.
3. Processes question modes in the order they appear in `blueprint.modes`.
4. For each mode:
   - performs initial breadth generation across topics,
   - runs adaptive supplement rounds,
   - dynamically computes how many single/multi chunks to sample,
   - generates candidate questions from chunk lists,
   - stores candidates in a mode-specific output directory.
5. Maintains global chunk-combination deduplication across all modes.
6. Exports candidate pools, traces, mode states, and global evidence usage.

### 1.2 What this agent does not do

The generation agent does not:

1. precisely generate the final benchmark count,
2. do final quality validation,
3. do final semantic deduplication,
4. decide the final benchmark sample,
5. fully verify answer correctness.

Those responsibilities belong to downstream validation agents.

---

## 2. Key Decisions

### 2.1 Question types are generated separately

Modes are processed sequentially according to their declaration order in `blueprint.modes`.

Example:

```yaml
modes:
  qa:
    count: 30
  multiple_choice:
    count: 20
```

Execution order:

```text
Stage 1: qa
Stage 2: multiple_choice
```

There is no separate `mode_order` field. The YAML order of `modes` is the generation order.

### 2.2 Each mode has its own candidate pool and trace

Mode-specific outputs are stored separately:

```text
runs/{task_id}/{run_id}/qa/candidate_pool.json
runs/{task_id}/{run_id}/qa/generation_trace.json
runs/{task_id}/{run_id}/qa/mode_state.json

runs/{task_id}/{run_id}/multiple_choice/candidate_pool.json
runs/{task_id}/{run_id}/multiple_choice/generation_trace.json
runs/{task_id}/{run_id}/multiple_choice/mode_state.json
```

This keeps schemas, validation, and debugging clean.

### 2.3 Chunk usage is globally shared

Although candidate questions are stored by mode, chunk usage is tracked globally.

This prevents QA and multiple-choice stages from repeatedly using the exact same chunk combinations.

Global evidence files:

```text
runs/{task_id}/{run_id}/global_state.json
runs/{task_id}/{run_id}/used_chunks.json
runs/{task_id}/{run_id}/generation_report.json
```

### 2.4 Chunk combination deduplication is global

A chunk combination used in QA should not be reused as the exact same combination in multiple-choice.

However, individual chunks may be reused with a usage penalty.

Recommended rule:

```text
Exact same raw chunk combination: avoid globally.
Individual chunk reuse: allowed, but lower sampling weight.
```

The combination key should be based on raw chunk IDs, not only multi-unit IDs.

Example:

```text
single_unit: chunk_a
multi_unit_1: [chunk_b, chunk_c]
multi_unit_2: [chunk_d, chunk_e]

global combination key:
(chunk_a, chunk_b, chunk_c, chunk_d, chunk_e)
```

---

## 3. Blueprint Schema

Recommended blueprint:

```yaml
task_id: benchmark_generation_v5
run_id: run_001
language: en

topics:
  - Biology
  - Climate Change
  - Space Exploration
  - History
  - Economics
  - Medicine
  - Physics

modes:
  qa:
    count: 30
    max_rounds: 20
    difficulty_distribution:
      easy: 0.3
      medium: 0.4
      hard: 0.3

  multiple_choice:
    count: 20
    max_rounds: 20
    difficulty_distribution:
      easy: 0.3
      medium: 0.4
      hard: 0.3

candidate_pool:
  target_multiplier: 2.5
  # min_difficulty_multiplier: Phase 2 — difficulty floor check not implemented in MVP.

initial_breadth:
  enabled: true
  max_topics_per_round: 10
  difficulty: medium

planner:
  topics_per_round: 3

chunk_mix:
  by_difficulty:
    easy:
      single_ratio: 0.8
      multi_ratio: 0.2
    medium:
      single_ratio: 0.5
      multi_ratio: 0.5
    hard:
      single_ratio: 0.2
      multi_ratio: 0.8

  mode_adjustment:
    qa:
      single_delta: 0.1
    multiple_choice:
      single_delta: -0.1

generation_yield:
  qa:
    single_chunk_avg_questions: 2.0
    multi_chunk_avg_questions: 3.0
  multiple_choice:
    single_chunk_avg_questions: 1.5
    multi_chunk_avg_questions: 2.0

chunk_limits:
  qa:
    single_k:
      min: 1
      max: 4
    multi_k:
      min: 0
      max: 3
  multiple_choice:
    single_k:
      min: 0
      max: 3
    multi_k:
      min: 1
      max: 4

runtime:
  max_consecutive_empty_rounds_per_mode: 3
  max_failures_per_mode: 8
  max_used_chunk_combinations: 10000
  llm_timeout_seconds: 60
  retrieval_timeout_seconds: 30
```

Notes:

- Do not add `mode_order`.
- Use the declaration order of `modes`.
- `count` is not a per-round generation count.
- `count` is used to estimate candidate targets and determine when a mode is sufficiently generated.

---

## 4. Output Directory Structure

Recommended output layout:

```text
runs/{task_id}/{run_id}/
  blueprint.yaml
  generation_report.json
  global_state.json
  used_chunks.json

  qa/
    candidate_pool.json
    generation_trace.json
    mode_state.json
    failures.json

  multiple_choice/
    candidate_pool.json
    generation_trace.json
    mode_state.json
    failures.json
```

### 4.1 candidate_pool.json

Mode-specific candidate questions.

Example for QA:

```json
[
  {
    "id": "qa_0001",
    "topic": "Climate Change",
    "mode": "qa",
    "question": "...",
    "answer": "...",
    "estimated_difficulty": "medium",
    "supporting_chunk_ids": ["chunk_a", "chunk_b"]
  }
]
```

Example for multiple choice:

```json
[
  {
    "id": "mcq_0001",
    "topic": "Climate Change",
    "mode": "multiple_choice",
    "question": "...",
    "options": ["A", "B", "C", "D"],
    "correct_answer": "B",
    "estimated_difficulty": "hard",
    "supporting_chunk_ids": ["chunk_c", "chunk_d"]
  }
]
```

### 4.2 generation_trace.json

Mode-specific per-round trace.

Each round should include:

```json
{
  "mode": "qa",
  "round_in_mode": 3,
  "strategy": "adaptive",
  "difficulty": "hard",
  "topics": ["Climate Change", "History"],
  "single_k": 2,
  "multi_k": 2,
  "target_candidates_per_topic": 6,
  "results": [
    {
      "topic": "Climate Change",
      "generated_count": 5,
      "actual_difficulty_counts": {
        "hard": 3,
        "medium": 2
      },
      "selected_raw_chunk_ids": ["chunk_a", "chunk_b", "chunk_c"]
    }
  ]
}
```

### 4.3 used_chunks.json

Global chunk-combination history.

```json
{
  "used_chunk_combinations": [
    ["chunk_a", "chunk_b"],
    ["chunk_c", "chunk_d", "chunk_e"]
  ],
  "chunk_usage_counts": {
    "chunk_a": 2,
    "chunk_b": 1,
    "chunk_c": 3
  }
}
```

---

## 5. State Model

Use two state levels:

1. `GlobalState`
2. `ModeState`

### 5.1 GlobalState

Global state stores evidence usage shared across modes.

```python
from dataclasses import dataclass, field
from collections import deque


@dataclass
class GlobalState:
    used_chunk_combinations: set[tuple[str, ...]] = field(default_factory=set)
    used_chunk_combination_order: deque[tuple[str, ...]] = field(default_factory=deque)
    chunk_usage_counts: dict[str, int] = field(default_factory=dict)

    # Counts failures across all modes for reporting only.
    # Does NOT participate in any mode stop condition.
    global_failures: int = 0

    # Phase 2: topic_expansion_counts for retrieval expansion tracking.
    # Not used in MVP.
```

Responsibilities:

- prevent exact chunk-combination reuse across modes,
- penalize overused chunks (Phase 2),
- track global failure count for reporting across all modes,
- support global report generation.

### 5.2 ModeState

Each mode has its own state.

```python
@dataclass
class ModeState:
    mode: str
    round_in_mode: int = 1
    candidate_questions: list[dict] = field(default_factory=list)

    difficulty_counts: dict[str, int] = field(default_factory=dict)
    topic_counts: dict[str, int] = field(default_factory=dict)

    initial_coverage: set[str] = field(default_factory=set)  # topics attempted for this mode

    consecutive_empty_rounds: int = 0
    failures: list[dict] = field(default_factory=list)
    failures_count: int = 0  # incremented per-topic failure; used for mode stop condition
    stopped_reason: str | None = None
```

Responsibilities:

- track candidate count for this mode,
- track difficulty distribution for this mode,
- track topic coverage for this mode,
- decide when this mode should stop.

---

## 6. Execution Flow

### 6.1 High-level flow

```python
async def run_generation_agent(blueprint, config, evidence_manager, generator):
    global_state = GlobalState()

    await evidence_manager.prepare_all_topics(blueprint.topics)

    for mode, mode_cfg in blueprint.modes.items():
        mode_state = ModeState(mode=mode)

        await run_mode_generation(
            mode=mode,
            mode_cfg=mode_cfg,
            blueprint=blueprint,
            config=config,
            global_state=global_state,
            mode_state=mode_state,
            evidence_manager=evidence_manager,
            generator=generator,
        )

        save_mode_outputs(blueprint.task_id, blueprint.run_id, mode, mode_state)

    save_global_outputs(blueprint.task_id, blueprint.run_id, global_state)
    save_generation_report(blueprint.task_id, blueprint.run_id, global_state)
```

### 6.2 Mode generation flow

```python
async def run_mode_generation(
    mode,
    mode_cfg,
    blueprint,
    config,
    global_state,
    mode_state,
    evidence_manager,
    generator,
):
    while True:
        # Stop check at the top of each iteration, with no side effects.
        should_stop, reason = mode_should_stop(
            mode_cfg=mode_cfg,
            mode_state=mode_state,
            global_state=global_state,
            blueprint=blueprint,
            config=config,
        )
        if should_stop:
            mode_state.stopped_reason = reason
            break

        round_plan = build_mode_round_plan(
            mode=mode,
            mode_cfg=mode_cfg,
            blueprint=blueprint,
            config=config,
            global_state=global_state,
            mode_state=mode_state,
            evidence_manager=evidence_manager,
        )

        if not round_plan.topics:
            mode_state.consecutive_empty_rounds += 1
            mode_state.round_in_mode += 1
            continue

        round_results = await execute_mode_round_plan(
            round_plan=round_plan,
            blueprint=blueprint,
            config=config,
            global_state=global_state,
            mode_state=mode_state,
            evidence_manager=evidence_manager,
            generator=generator,
        )

        # Round-level empty tracking: count generated across all topics.
        total_generated = sum(
            result.get("generated_count", 0)
            for result in round_results
        )
        if total_generated == 0:
            mode_state.consecutive_empty_rounds += 1
        else:
            mode_state.consecutive_empty_rounds = 0

        update_mode_trace(mode_state, round_plan, round_results)
        mode_state.round_in_mode += 1
```

---

## 7. ModeRoundPlan

Since modes are processed separately, each round plan belongs to a single mode.

```python
@dataclass(frozen=True)
class ModeRoundPlan:
    mode: str
    round_in_mode: int
    strategy: str
    difficulty: str
    topics: tuple[str, ...]
    single_k: int
    multi_k: int
    target_candidates_per_topic: int
    reason: str
```

`frozen=True` prevents accidental mutation during execution. Always construct `topics` as `tuple(selected_topics)`.

Example:

```json
{
  "mode": "multiple_choice",
  "round_in_mode": 4,
  "strategy": "adaptive",
  "difficulty": "hard",
  "topics": ["Climate Change", "History", "Medicine"],
  "single_k": 1,
  "multi_k": 3,
  "target_candidates_per_topic": 7,
  "reason": "multiple_choice hard is underrepresented; selected topics have low coverage."
}
```

---

## 8. Planning Logic

Each mode has two phases:

1. initial breadth
2. adaptive supplement

### 8.1 Initial breadth

Initial breadth ensures every topic is attempted at least once for the current mode.

If many topics exist, process them in batches.

```python
def mode_initial_breadth_not_done(mode_state, blueprint):
    return any(topic not in mode_state.initial_coverage for topic in blueprint.topics)
```

Build plan:

```python
def build_initial_breadth_plan(mode, mode_cfg, blueprint, config, mode_state):
    topics = tuple(
        t for t in blueprint.topics
        if t not in mode_state.initial_coverage
    )[: config.initial_breadth.max_topics_per_round]

    difficulty = config.initial_breadth.difficulty

    single_k, multi_k, target_candidates_per_topic = compute_dynamic_chunk_k(
        mode=mode,
        mode_cfg=mode_cfg,
        difficulty=difficulty,
        selected_topic_count=max(1, len(topics)),
        mode_state=mode_state,
        blueprint=blueprint,
        config=config,
    )

    return ModeRoundPlan(
        mode=mode,
        round_in_mode=mode_state.round_in_mode,
        strategy="initial_breadth",
        difficulty=difficulty,
        topics=tuple(topics),
        single_k=single_k,
        multi_k=multi_k,
        target_candidates_per_topic=target_candidates_per_topic,
        reason=f"Initial breadth for mode={mode}.",
    )
```

### 8.2 Adaptive supplement

After initial breadth, select difficulty and topics based on current mode state.

```python
def build_adaptive_plan(mode, mode_cfg, blueprint, config, mode_state):
    difficulty = choose_difficulty_for_mode(mode_cfg, mode_state)

    topics = tuple(choose_low_coverage_topics_for_mode(
        blueprint=blueprint,
        mode_state=mode_state,
        k=config.planner.topics_per_round,
    ))

    single_k, multi_k, target_candidates_per_topic = compute_dynamic_chunk_k(
        mode=mode,
        mode_cfg=mode_cfg,
        difficulty=difficulty,
        selected_topic_count=max(1, len(topics)),
        mode_state=mode_state,
        blueprint=blueprint,
        config=config,
    )

    return ModeRoundPlan(
        mode=mode,
        round_in_mode=mode_state.round_in_mode,
        strategy="adaptive",
        difficulty=difficulty,
        topics=topics,
        single_k=single_k,
        multi_k=multi_k,
        target_candidates_per_topic=target_candidates_per_topic,
        reason=f"Adaptive supplement for mode={mode}, difficulty={difficulty}.",
    )
```

### 8.3 Top-level mode plan builder

```python
def build_mode_round_plan(
    mode,
    mode_cfg,
    blueprint,
    config,
    global_state,
    mode_state,
    evidence_manager,
):
    if config.initial_breadth.enabled and mode_initial_breadth_not_done(mode_state, blueprint):
        return build_initial_breadth_plan(
            mode=mode,
            mode_cfg=mode_cfg,
            blueprint=blueprint,
            config=config,
            mode_state=mode_state,
        )

    return build_adaptive_plan(
        mode=mode,
        mode_cfg=mode_cfg,
        blueprint=blueprint,
        config=config,
        mode_state=mode_state,
    )
```

---

## 9. Difficulty Selection

Difficulty is selected within the current mode only.

```python
def choose_difficulty_for_mode(mode_cfg, mode_state):
    total = max(1, len(mode_state.candidate_questions))

    current_ratio = {
        d: mode_state.difficulty_counts.get(d, 0) / total
        for d in mode_cfg.difficulty_distribution
    }

    return max(
        mode_cfg.difficulty_distribution.keys(),
        key=lambda d: mode_cfg.difficulty_distribution[d] - current_ratio.get(d, 0.0),
    )
```

If hard is underrepresented, the planner will select `hard`.

---

## 10. Topic Selection

Topic selection is also mode-specific.

```python
def choose_low_coverage_topics_for_mode(blueprint, mode_state, k):
    scored = []

    expected_per_topic = len(mode_state.candidate_questions) / max(1, len(blueprint.topics))

    for topic in blueprint.topics:
        current = mode_state.topic_counts.get(topic, 0)
        score = expected_per_topic - current
        scored.append((score, topic))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [topic for _, topic in scored[:k]]
```

This does not force final topic balance. It only prevents some topics from being ignored.

---

## 11. Dynamic Chunk Count Calculation

### 11.1 Candidate target for mode

```python
def mode_candidate_target(mode_cfg, config):
    return math.ceil(mode_cfg.count * config.candidate_pool.target_multiplier)
```

### 11.2 Remaining rounds for mode

```python
def remaining_mode_rounds(mode_cfg, mode_state):
    return max(1, mode_cfg.max_rounds - mode_state.round_in_mode + 1)
```

### 11.3 Resolve chunk mix

Difficulty is primary. Mode adjustment is secondary.

```python
def resolve_chunk_mix(mode, difficulty, config):
    base = config.chunk_mix.by_difficulty[difficulty]
    single_ratio = base.single_ratio

    mode_delta = config.chunk_mix.mode_adjustment.get(mode, {}).get("single_delta", 0.0)
    single_ratio += mode_delta
    single_ratio = max(0.0, min(1.0, single_ratio))

    return single_ratio, 1.0 - single_ratio
```

### 11.4 Compute dynamic single_k and multi_k

```python
def compute_dynamic_chunk_k(
    mode,
    mode_cfg,
    difficulty,
    selected_topic_count,
    mode_state,
    blueprint,
    config,
):
    target = mode_candidate_target(mode_cfg, config)
    current = len(mode_state.candidate_questions)
    gap = max(0, target - current)

    rounds_left = remaining_mode_rounds(mode_cfg, mode_state)
    target_this_round = max(1, math.ceil(gap / rounds_left))
    target_per_topic = max(1, math.ceil(target_this_round / selected_topic_count))

    single_ratio, multi_ratio = resolve_chunk_mix(mode, difficulty, config)

    yield_cfg = config.generation_yield[mode]

    single_k = math.ceil(
        (target_per_topic * single_ratio) / max(0.1, yield_cfg.single_chunk_avg_questions)
    )
    multi_k = math.ceil(
        (target_per_topic * multi_ratio) / max(0.1, yield_cfg.multi_chunk_avg_questions)
    )

    limits = config.chunk_limits[mode]

    single_k = max(limits.single_k.min, min(limits.single_k.max, single_k))
    multi_k = max(limits.multi_k.min, min(limits.multi_k.max, multi_k))

    return single_k, multi_k, target_per_topic
```

---

## 12. Chunk Sampling

For each selected topic:

1. Sample `single_k` single chunk units.
2. Sample `multi_k` multi chunk units.
3. Combine them into a chunk list.
4. Check global chunk combination dedup.
5. Generate candidate questions from this chunk list.

### 12.1 Combination key

Use raw chunk IDs.

```python
def raw_chunk_ids(chunks):
    ids = []
    for unit in chunks:
        if hasattr(unit, "raw_chunk_ids"):
            ids.extend(unit.raw_chunk_ids)
        elif hasattr(unit, "chunk_id"):
            ids.append(unit.chunk_id)
        else:
            ids.append(str(unit))
    return sorted(set(ids))
```

### 12.2 Global combination dedup

```python
def is_new_global_combination(global_state, chunks):
    combo = tuple(raw_chunk_ids(chunks))
    return combo not in global_state.used_chunk_combinations
```

### 12.3 Record global usage

```python
def record_global_chunk_usage(global_state, chunks, max_size):
    chunk_ids = raw_chunk_ids(chunks)
    combo = tuple(chunk_ids)

    if combo not in global_state.used_chunk_combinations:
        global_state.used_chunk_combinations.add(combo)
        global_state.used_chunk_combination_order.append(combo)

    for cid in chunk_ids:
        global_state.chunk_usage_counts[cid] = global_state.chunk_usage_counts.get(cid, 0) + 1

    while len(global_state.used_chunk_combinations) > max_size:
        oldest = global_state.used_chunk_combination_order.popleft()
        global_state.used_chunk_combinations.discard(oldest)
```

### 12.4 Individual chunk usage penalty

Sampling should apply a soft usage penalty to avoid overusing the same chunks.

Example:

```python
score = base_score / (1 + global_state.chunk_usage_counts.get(chunk_id, 0))
```

For multi chunks, use the average or max usage count of underlying raw chunks.

### 12.5 sample_chunks wrapper

`EvidenceManager` exposes separate `sample_single` / `sample_multi` methods (compatible with v4). Use the following wrapper to bridge them into the unified interface required by `execute_mode_round_plan`. It also enforces global combination deduplication at the sampling layer (up to 5 retries before accepting a duplicate).

Returns `(chunks, duplicate_combination: bool)`. The caller includes `duplicate_combination` in the trace result so repeated chunk usage is visible during debugging.

Note: `global_chunk_usage_counts` is accepted as a parameter but **not yet used for sampling weight**. Individual chunk usage penalty is Phase 2. In MVP, deduplication is at the combination level only.

```python
def sample_chunks(
    evidence_manager,
    topic,
    mode,
    difficulty,
    single_k,
    multi_k,
    global_used_combinations,
    global_chunk_usage_counts,  # Phase 2: will be used for per-chunk sampling weight
) -> tuple[list, bool]:
    last_chunks = []

    for _ in range(5):
        single_units = (
            evidence_manager.sample_single(
                topic=topic,
                target_mode=mode,
                target_difficulty=difficulty,
                k=single_k,
            )
            if single_k > 0
            else []
        )

        multi_units = (
            evidence_manager.sample_multi(
                topic=topic,
                target_mode=mode,
                target_difficulty=difficulty,
                k=multi_k,
            )
            if multi_k > 0
            else []
        )

        chunks = single_units + multi_units
        combo = tuple(raw_chunk_ids(chunks))

        if combo not in global_used_combinations:
            return chunks, False

        last_chunks = chunks

    # Fallback: return last sampled chunks with duplicate flag set.
    return last_chunks, True
```


---

## 13. Generation Execution

Each topic is wrapped in a `try/except` to prevent a single failure from aborting the entire round. Failures are recorded in `mode_state.failures`, `mode_state.failures_count` is incremented for the mode stop condition, and `global_state.global_failures` is incremented for reporting only.

```python
async def execute_mode_round_plan(
    round_plan,
    blueprint,
    config,
    global_state,
    mode_state,
    evidence_manager,
    generator,
):
    round_results = []

    for topic in round_plan.topics:
        try:
            chunks, duplicate_combination = sample_chunks(
                evidence_manager=evidence_manager,
                topic=topic,
                mode=round_plan.mode,
                difficulty=round_plan.difficulty,
                single_k=round_plan.single_k,
                multi_k=round_plan.multi_k,
                global_used_combinations=global_state.used_chunk_combinations,
                global_chunk_usage_counts=global_state.chunk_usage_counts,
            )

            raw_output = await generator.generate(
                topic=topic,
                mode=round_plan.mode,
                difficulty=round_plan.difficulty,
                chunks=chunks,
                language=blueprint.language,
            )

            parsed_questions = parse_questions(raw_output)

            update_mode_state(
                mode_state=mode_state,
                topic=topic,
                round_plan=round_plan,
                parsed_questions=parsed_questions,
            )

            # Record chunk usage regardless of whether parsed_questions is empty.
            # A zero-yield attempt still consumed this combination; marking it used
            # prevents repeated sampling of the same low-quality chunk set.
            record_global_chunk_usage(
                global_state=global_state,
                chunks=chunks,
                max_size=config.runtime.max_used_chunk_combinations,
            )

            result = {
                "topic": topic,
                "success": True,
                "generated_count": len(parsed_questions),
                "chunks": raw_chunk_ids(chunks),
                "duplicate_combination": duplicate_combination,
                "error": None,
            }

        except Exception as exc:
            mode_state.failures_count += 1       # used for mode stop condition
            global_state.global_failures += 1    # reporting only

            mode_state.failures.append({
                "mode": round_plan.mode,
                "round_in_mode": round_plan.round_in_mode,
                "topic": topic,
                "difficulty": round_plan.difficulty,
                "error": str(exc),
                "error_type": exc.__class__.__name__,
            })

            result = {
                "topic": topic,
                "success": False,
                "generated_count": 0,
                "chunks": [],
                "duplicate_combination": False,
                "error": str(exc),
                "error_type": exc.__class__.__name__,
            }

        finally:
            # Mark initial breadth coverage regardless of success or failure.
            # An attempt counts as coverage — we do not require successful generation.
            if round_plan.strategy == "initial_breadth":
                mode_state.initial_coverage.add(topic)

        round_results.append(result)

    return round_results
```

---

## 14. Mode State Update

Use actual parsed question fields.

```python
def normalize_difficulty(value):
    if not value:
        return "medium"
    value = str(value).lower().strip()
    if value in ["easy", "simple", "low"]:
        return "easy"
    if value in ["hard", "difficult", "advanced", "high"]:
        return "hard"
    return "medium"
```

```python
def update_mode_state(mode_state, topic, round_plan, parsed_questions):
    # initial_coverage is marked in execute_mode_round_plan's finally block.
    for q in parsed_questions:
        actual_difficulty = normalize_difficulty(
            q.get("estimated_difficulty") or q.get("difficulty") or round_plan.difficulty
        )

        mode_state.candidate_questions.append(q)
        mode_state.difficulty_counts[actual_difficulty] = (
            mode_state.difficulty_counts.get(actual_difficulty, 0) + 1
        )
        mode_state.topic_counts[topic] = mode_state.topic_counts.get(topic, 0) + 1
```

`consecutive_empty_rounds` is updated at round level in `run_mode_generation`, not here.


---

## 15. Mode Stop Conditions

Each mode stops independently. The function returns `(bool, reason)` — it does **not** mutate `mode_state`. The caller sets `mode_state.stopped_reason`.

```python
def mode_should_stop(mode_cfg, mode_state, global_state, blueprint, config):
    # candidate_pool_sufficient must not fire before initial breadth is complete.
    # Stopping early would leave some topics never attempted.
    initial_done = not mode_initial_breadth_not_done(mode_state, blueprint)
    target = mode_candidate_target(mode_cfg, config)

    if initial_done and len(mode_state.candidate_questions) >= target:
        return True, "candidate_pool_sufficient"

    if mode_state.round_in_mode > mode_cfg.max_rounds:
        return True, "max_rounds_reached"

    if (
        mode_state.consecutive_empty_rounds
        >= config.runtime.max_consecutive_empty_rounds_per_mode
    ):
        return True, "consecutive_empty_rounds_reached"

    if mode_state.failures_count >= config.runtime.max_failures_per_mode:
        return True, "mode_failure_limit_reached"

    return False, None
```

`global_state.global_failures` is incremented alongside `mode_state.failures_count` for reporting, but does **not** participate in stop conditions. This ensures QA-stage failures do not prevent the MCQ stage from running.

The caller sets `stopped_reason` when the loop exits:

```python
should_stop, reason = mode_should_stop(mode_cfg, mode_state, global_state, blueprint, config)
if should_stop:
    mode_state.stopped_reason = reason
    break
```

---

## 16. Mode-Specific Storage

After each mode finishes, write:

```text
runs/{task_id}/{run_id}/{mode}/candidate_pool.json
runs/{task_id}/{run_id}/{mode}/generation_trace.json
runs/{task_id}/{run_id}/{mode}/mode_state.json
runs/{task_id}/{run_id}/{mode}/failures.json
```

### 16.1 candidate_pool.json

Contains only candidates for that mode.

### 16.2 generation_trace.json

Contains only generation rounds for that mode.

### 16.3 mode_state.json

Contains summary counts:

```json
{
  "mode": "qa",
  "candidate_count": 76,
  "target_candidate_count": 75,
  "difficulty_counts": {
    "easy": 22,
    "medium": 31,
    "hard": 23
  },
  "topic_counts": {
    "Biology": 11,
    "Climate Change": 9
  },
  "stopped_reason": "candidate_pool_sufficient"
}
```

---

## 17. Helper Function Interfaces

These functions are called in execution code but not fully defined elsewhere. Implement them according to the contracts below. Do not invent a different schema.

### 17.1 parse_questions

```python
def parse_questions(raw_output: str) -> list[dict]:
    """Parse LLM output into a list of question dicts.

    Each dict must contain at minimum:
      - "question": str
      - "mode": str (optional; used by update_mode_state via normalize_mode if present)
      - "estimated_difficulty": str | None
      - "difficulty": str | None

    Returns [] on parse error (do not raise).
    """
    ...
```

### 17.2 update_mode_trace

```python
def update_mode_trace(
    mode_state: ModeState,
    round_plan: ModeRoundPlan,
    round_results: list[dict],
) -> None:
    """Append a round entry to mode_state trace for generation_trace.json.

    Each entry must include:
      - mode, round_in_mode, strategy, difficulty
      - topics (list)
      - single_k, multi_k, target_candidates_per_topic
      - per-topic results: topic, success, generated_count, chunks, duplicate_combination, error
    """
    ...
```

### 17.3 save_mode_outputs

```python
def save_mode_outputs(task_id: str, run_id: str, mode: str, mode_state: ModeState) -> None:
    """Write mode-specific files to runs/{task_id}/{run_id}/{mode}/:
      - candidate_pool.json   — mode_state.candidate_questions
      - generation_trace.json — mode_state trace entries
      - mode_state.json       — summary counts (candidate_count, difficulty_counts, topic_counts, stopped_reason)
      - failures.json         — mode_state.failures
    """
    ...
```

### 17.4 save_global_outputs

```python
def save_global_outputs(task_id: str, run_id: str, global_state: GlobalState) -> None:
    """Write global files to runs/{task_id}/{run_id}/:
      - used_chunks.json — used_chunk_combinations (as list[list[str]]) and chunk_usage_counts
      - global_state.json — global_failures count and any other GlobalState fields
    """
    ...
```

### 17.5 save_generation_report

```python
def save_generation_report(task_id: str, run_id: str, global_state: GlobalState) -> None:
    """Write runs/{task_id}/{run_id}/generation_report.json.

    Must include:
      - task_id
      - run_id
      - per-mode summary: candidate_count, target_candidate_count, stopped_reason
      - total_candidates
      - global_used_chunk_combinations count
      - global_failures count
    """
    ...
```

---

## 18. Global Report

At the end, write:

```text
runs/{task_id}/{run_id}/generation_report.json
```

Example:

```json
{
  "task_id": "benchmark_generation_v5",
  "run_id": "run_001",
  "modes": {
    "qa": {
      "candidate_count": 76,
      "target_candidate_count": 75,
      "stopped_reason": "candidate_pool_sufficient"
    },
    "multiple_choice": {
      "candidate_count": 52,
      "target_candidate_count": 50,
      "stopped_reason": "candidate_pool_sufficient"
    }
  },
  "total_candidates": 128,
  "global_used_chunk_combinations": 84
}
```

---

## 19. Implementation Phases

### Phase 1: MVP

Implement only:

1. mode-staged generation,
2. mode-specific output folders,
3. initial breadth per mode,
4. adaptive supplement per mode,
5. dynamic single_k/multi_k,
6. global chunk combination dedup,
7. mode-specific stop conditions.

Do not implement yet:

1. complex cooldown,
2. complex API error taxonomy,
3. multi-step fallback tree,
4. LLM strategy advisor,
5. downstream validation.

### Phase 2: Robustness

Add later:

1. evidence shortage fallback,
2. retrieval expansion,
3. chunk exhaustion detection,
4. cooldown,
5. timeout-specific handling,
6. richer failure reports.

### Phase 3: Intelligence Upgrade

Add later:

1. strategy memory,
2. LLM strategy advisor,
3. chunk strategy types:
   - direct factual,
   - contrastive,
   - multi-hop,
   - rare subtopic,
4. plan candidate scoring.

---

## 20. Acceptance Criteria for MVP

The MVP implementation is acceptable if:

1. Modes are processed in the declaration order of `blueprint.modes`.
2. Each mode writes candidates to its own directory.
3. QA and multiple-choice are not mixed in the same candidate file.
4. Initial breadth attempts every topic at least once for each mode.
5. Adaptive rounds select under-covered difficulty and topics within the current mode.
6. `single_k` and `multi_k` are dynamically computed from:
   - candidate gap,
   - remaining mode rounds,
   - selected topic count,
   - difficulty-based chunk mix,
   - mode adjustment,
   - generation yield,
   - chunk limits.
7. Chunk combinations are deduplicated globally across modes.
8. Individual chunk usage penalty is Phase 2. MVP only enforces global combination-level deduplication via `used_chunk_combinations`.
9. Each mode stops independently.
10. A global report summarizes all modes.
11. `consecutive_empty_rounds` is incremented once per round (after all topics complete), not once per topic. An empty round means `total_generated == 0` across all topics in that round.
12. `mode_should_stop` does not mutate `mode_state`. It returns `(bool, reason)`. The caller sets `mode_state.stopped_reason` when the loop exits.
13. `execute_mode_round_plan` catches exceptions per topic, appends to `mode_state.failures`, increments `mode_state.failures_count` (for stop) and `global_state.global_failures` (for reporting), then continues to the next topic.
14. `ModeRoundPlan` is `frozen=True` and its `topics` field is `tuple[str, ...]`. No code mutates a plan after creation.
15. `mode_state.failures_count >= config.runtime.max_failures_per_mode` triggers `mode_should_stop` to return `True` with reason `"mode_failure_limit_reached"`. `global_state.global_failures` is for reporting only and does not stop any mode.
16. `GlobalState` in MVP does not contain `topic_expansion_counts`. That field is reserved for Phase 2.
17. `build_initial_breadth_plan` returns a complete `ModeRoundPlan` with all 9 fields: `mode`, `round_in_mode`, `strategy`, `difficulty`, `topics`, `single_k`, `multi_k`, `target_candidates_per_topic`, `reason`.
18. In `execute_mode_round_plan`, a `finally` block marks `initial_coverage.add(topic)` after every topic execution when `round_plan.strategy == "initial_breadth"`, regardless of success or failure. An attempt counts as coverage.
19. `sample_chunks` returns `(chunks, duplicate_combination: bool)`. The `duplicate_combination` flag is included in each topic's result dict and propagated to `generation_trace.json`.
20. `candidate_pool.min_difficulty_multiplier` does not exist in MVP blueprint. Difficulty floor check is Phase 2.

---

## 21. Summary

Final architecture:

> Blueprint modes-ordered, mode-staged, adaptive chunk-sampling candidate generation agent.

Simplified principle:

```text
For each question mode:
  1. Explore all topics once.
  2. Observe current candidates for this mode.
  3. Select weak difficulty and weak topics.
  4. Dynamically compute single_k and multi_k.
  5. Sample globally deduplicated chunks.
  6. Generate candidates.
  7. Save candidates under this mode.
```

Important separation:

```text
Question candidates: stored by mode.
Mode progress: tracked by mode.
Chunk usage: tracked globally.
Final validation: handled downstream.
```

This design keeps generation clean, debuggable, and compatible with downstream validation agents.
