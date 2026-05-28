# BenchForge Adaptive Chunk Generation Agent - Technical Spec v3

## 0. Purpose

This document specifies the implementation plan for a blueprint-guided, mode-rotating, round-plan-based adaptive chunk-sampling candidate generation agent for BenchForge.

v3 fixes the issues identified in v2:

1. Defines `is_initial_breadth_phase` and `state_has_initial_coverage`.
2. Restores correct global consecutive failure tracking.
3. Separates evidence shortage fallback from API/runtime failures.
4. Makes `RoundPlan` truly immutable by using `tuple[str, ...]`.
5. Excludes exhausted topics during topic selection.
6. Makes `EvidenceManager` required for stop-condition checks.

The generation agent builds a candidate question pool. It does not attempt to precisely produce the final benchmark question count. Downstream validation agents handle quality validation, answer checking, deduplication, difficulty calibration, and final benchmark sampling.

---

## 1. Core Principles

### 1.1 Blueprint counts are targets, not per-round generation commands

Blueprint counts such as `qa.count = 30` and `multiple_choice.count = 20` are used for state observation and stopping conditions. They are not used to tell the generator exactly how many questions to produce in a round.

### 1.2 The planner controls chunk sampling

Each round plan decides:

- mode,
- target difficulty,
- selected topics,
- `single_k`,
- `multi_k`,
- action,
- strategy,
- reason.

The generator receives a chunk list and produces candidate questions.

### 1.3 Single/multi chunk mix is primarily difficulty-driven

Difficulty controls the main mix:

- easy: mostly single chunks,
- medium: balanced,
- hard: mostly multi chunks.

Mode is a secondary adjustment:

- QA slightly favors single chunks,
- multiple-choice slightly favors multi chunks.

### 1.4 Round-level planning, topic-level feedback

The planner creates one `RoundPlan` per round. The plan may contain multiple topics. Execution updates state after each topic. Replanning occurs only at the next round.

---

## 2. Blueprint Schema

```yaml
run_id: benchmark_generation_v3
language: en

topics:
  - Biology
  - Climate Change
  - Space Exploration
  - History
  - Economics
  - Medicine
  - Physics

max_rounds: 40

mode_order:
  - qa
  - multiple_choice

modes:
  qa:
    count: 30
    difficulty_distribution:
      easy: 0.3
      medium: 0.4
      hard: 0.3

  multiple_choice:
    count: 20
    difficulty_distribution:
      easy: 0.3
      medium: 0.4
      hard: 0.3

candidate_pool:
  target_multiplier: 2.5
  min_mode_multiplier: 1.5
  min_difficulty_multiplier: 1.2

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

topic_safety:
  max_attempts_per_topic: null
  max_consecutive_failures_per_topic: 3
  cooldown_rounds_after_failure: 2

retrieval_safety:
  max_expansions_per_topic: 3
  chunk_exhaustion_ratio: 0.85

difficulty_policy:
  hard_focus_threshold: 0.15
  max_consecutive_hard_focus_rounds: 2

runtime:
  max_global_consecutive_failures: 3
  max_global_failures: 8
  llm_timeout_seconds: 60
  retrieval_timeout_seconds: 30
  max_used_chunk_combinations: 10000
```

Important: use only `candidate_pool.target_multiplier`. Do not introduce a duplicate stop-policy multiplier.

---

## 3. Data Structures

### 3.1 RoundPlan

`RoundPlan` must be immutable. Use `tuple[str, ...]`, not `list[str]`, for `topics`.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class RoundPlan:
    round_num: int
    action: str
    strategy: str
    mode: str
    difficulty: str
    topics: tuple[str, ...]
    single_k: int
    multi_k: int
    target_candidates_per_topic: int
    retrieval_strategy: str
    reason: str
```

Do not modify a `RoundPlan` during execution.

### 3.2 TopicExecutionPlan

Fallback and topic-level changes must be represented by a separate topic-level plan.

```python
@dataclass(frozen=True)
class TopicExecutionPlan:
    round_plan: RoundPlan
    topic: str
    single_k: int
    multi_k: int
    retrieval_strategy: str
    action: str
    reason: str
```

If fallback is needed, create a new `TopicExecutionPlan` with `dataclasses.replace`. Do not mutate `RoundPlan`.

### 3.3 GenerationState

```python
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Any

@dataclass
class GenerationState:
    round_num: int = 1

    candidate_questions: list[dict[str, Any]] = field(default_factory=list)

    mode_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    difficulty_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    mode_difficulty_counts: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )

    topic_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    topic_mode_counts: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )

    # Tracks whether a (topic, mode) pair has been attempted during initial breadth.
    initial_coverage: set[tuple[str, str]] = field(default_factory=set)

    topic_attempts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    topic_consecutive_failures: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    topic_cooldown_until_round: dict[str, int] = field(default_factory=dict)
    topic_expansion_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Correct global failure tracking.
    global_consecutive_failures: int = 0
    global_failures: int = 0

    # Hard-focus tracking.
    consecutive_hard_focus_rounds: int = 0

    # Store sorted tuple chunk-combinations for JSON-safe export.
    used_chunk_combinations: set[tuple[str, ...]] = field(default_factory=set)

    failure_history: list[dict[str, Any]] = field(default_factory=list)
    round_traces: list[dict[str, Any]] = field(default_factory=list)
```

### 3.4 State must record actual parsed difficulty

When updating state, use the actual parsed question difficulty, not the planned difficulty.

```python
actual_difficulty = normalize_difficulty(
    q.get("estimated_difficulty") or q.get("difficulty") or round_plan.difficulty
)
```

This is critical because the planner uses these counts to decide future difficulty targets.

---

## 4. Initial Breadth Coverage

### 4.1 Semantics

Initial breadth means each `(topic, mode)` pair should be attempted at least once, unless the topic list is too large and has to be batched.

Do not infer initial coverage from `topic_counts` alone. Track it explicitly with `state.initial_coverage`.

### 4.2 state_has_initial_coverage

```python
def state_has_initial_coverage(state: GenerationState, topic: str, mode: str) -> bool:
    return (topic, mode) in state.initial_coverage
```

### 4.3 mark_initial_coverage

Mark coverage after an initial breadth attempt, even if zero questions were generated. The attempt itself is what matters for initial exploration.

```python
def mark_initial_coverage(state: GenerationState, topic: str, mode: str) -> None:
    state.initial_coverage.add((topic, mode))
```

### 4.4 is_initial_breadth_phase

```python
def is_initial_breadth_phase(state: GenerationState, blueprint, config) -> bool:
    if not config.initial_breadth.enabled:
        return False

    for mode in blueprint.mode_order:
        for topic in blueprint.topics:
            if not state_has_initial_coverage(state, topic, mode):
                return True

    return False
```

### 4.5 Build initial breadth round plan

```python
def build_initial_breadth_round_plan(state, blueprint, config) -> RoundPlan:
    mode = choose_mode_by_rotation(state.round_num, blueprint.mode_order)

    uncovered_topics = [
        topic
        for topic in blueprint.topics
        if not state_has_initial_coverage(state, topic, mode)
        and not is_topic_in_cooldown(state, topic)
    ]

    topics = tuple(uncovered_topics[: config.initial_breadth.max_topics_per_round])

    if not topics:
        for fallback_mode in blueprint.mode_order:
            uncovered_topics = [
                topic
                for topic in blueprint.topics
                if not state_has_initial_coverage(state, topic, fallback_mode)
                and not is_topic_in_cooldown(state, topic)
            ]
            if uncovered_topics:
                mode = fallback_mode
                topics = tuple(uncovered_topics[: config.initial_breadth.max_topics_per_round])
                break

    difficulty = config.initial_breadth.difficulty

    single_k, multi_k, target_candidates_per_topic = compute_dynamic_chunk_k(
        state=state,
        blueprint=blueprint,
        config=config,
        mode=mode,
        difficulty=difficulty,
        selected_topic_count=max(len(topics), 1),
    )

    return RoundPlan(
        round_num=state.round_num,
        action="initial_breadth_generate",
        strategy="initial_breadth",
        mode=mode,
        difficulty=difficulty,
        topics=topics,
        single_k=single_k,
        multi_k=multi_k,
        target_candidates_per_topic=target_candidates_per_topic,
        retrieval_strategy="use_existing_pool",
        reason=build_reason(
            action="initial_breadth_generate",
            mode=mode,
            difficulty=difficulty,
            topics=topics,
            state=state,
            blueprint=blueprint,
            extra="Covering topic/mode pairs not yet explored.",
        ),
    )
```

If `topics` is empty after this, the caller should stop or skip the round.

---

## 5. Planner

### 5.1 Main planner entry

`evidence_manager` is required.

```python
def build_round_plan(state, blueprint, config, evidence_manager) -> RoundPlan:
    stop, reason = should_stop(state, blueprint, config, evidence_manager)
    if stop:
        return RoundPlan(
            round_num=state.round_num,
            action="stop_generation",
            strategy="stop",
            mode="",
            difficulty="",
            topics=tuple(),
            single_k=0,
            multi_k=0,
            target_candidates_per_topic=0,
            retrieval_strategy="none",
            reason=reason,
        )

    if is_initial_breadth_phase(state, blueprint, config):
        return build_initial_breadth_round_plan(state, blueprint, config)

    mode = choose_mode_by_rotation(state.round_num, blueprint.mode_order)
    difficulty = choose_difficulty(state, blueprint, mode)
    strategy = choose_chunk_strategy(state, blueprint, config, mode, difficulty)

    topics = choose_adaptive_topics(
        state=state,
        blueprint=blueprint,
        config=config,
        evidence_manager=evidence_manager,
        mode=mode,
    )

    single_k, multi_k, target_candidates_per_topic = compute_dynamic_chunk_k(
        state=state,
        blueprint=blueprint,
        config=config,
        mode=mode,
        difficulty=difficulty,
        selected_topic_count=max(len(topics), 1),
    )

    action = choose_round_action(
        topics=topics,
        state=state,
        blueprint=blueprint,
        config=config,
        evidence_manager=evidence_manager,
        single_k=single_k,
        multi_k=multi_k,
    )

    return RoundPlan(
        round_num=state.round_num,
        action=action,
        strategy=strategy,
        mode=mode,
        difficulty=difficulty,
        topics=topics,
        single_k=single_k,
        multi_k=multi_k,
        target_candidates_per_topic=target_candidates_per_topic,
        retrieval_strategy="use_existing_pool" if action == "generate_with_existing_chunks" else "adaptive",
        reason=build_reason(
            action=action,
            mode=mode,
            difficulty=difficulty,
            topics=topics,
            state=state,
            blueprint=blueprint,
            extra=f"strategy={strategy}, single_k={single_k}, multi_k={multi_k}",
        ),
    )
```

### 5.2 Mode selection

```python
def choose_mode_by_rotation(round_num: int, mode_order: list[str]) -> str:
    return mode_order[(round_num - 1) % len(mode_order)]
```

### 5.3 Difficulty selection

Use actual generated difficulty counts.

```python
def choose_difficulty(state: GenerationState, blueprint, mode: str) -> str:
    target_dist = blueprint.modes[mode].difficulty_distribution
    total_for_mode = max(1, state.mode_counts.get(mode, 0))

    current_ratio = {
        d: state.mode_difficulty_counts[mode].get(d, 0) / total_for_mode
        for d in target_dist
    }

    return max(
        target_dist.keys(),
        key=lambda d: target_dist[d] - current_ratio.get(d, 0.0),
    )
```

### 5.4 Chunk strategy

```python
def choose_chunk_strategy(state, blueprint, config, mode: str, difficulty: str) -> str:
    if difficulty != "hard":
        return "default"

    target_hard_ratio = blueprint.modes[mode].difficulty_distribution.get("hard", 0.0)
    total_for_mode = max(1, state.mode_counts.get(mode, 0))
    current_hard_ratio = state.mode_difficulty_counts[mode].get("hard", 0) / total_for_mode
    hard_gap = target_hard_ratio - current_hard_ratio

    if (
        hard_gap >= config.difficulty_policy.hard_focus_threshold
        and state.consecutive_hard_focus_rounds < config.difficulty_policy.max_consecutive_hard_focus_rounds
    ):
        return "hard_focus"

    return "default"
```

Update `consecutive_hard_focus_rounds` once per round after the round completes.

### 5.5 Topic scoring must exclude exhausted topics

```python
def score_topic(topic, mode, state, blueprint, config, evidence_manager) -> float:
    if is_topic_in_cooldown(state, topic):
        return float("-inf")

    if is_topic_exhausted(topic, state, config, evidence_manager):
        return float("-inf")

    max_attempts = config.topic_safety.max_attempts_per_topic
    if max_attempts is not None and state.topic_attempts.get(topic, 0) >= max_attempts:
        return float("-inf")

    topic_gap = expected_candidates_per_topic(state, blueprint) - state.topic_counts.get(topic, 0)
    topic_mode_gap = expected_candidates_per_topic_mode(state, blueprint, mode) - state.topic_mode_counts[topic].get(mode, 0)

    failure_penalty = state.topic_consecutive_failures.get(topic, 0) * 2.0
    expansion_penalty = state.topic_expansion_counts.get(topic, 0) * 0.5

    return topic_gap + topic_mode_gap - failure_penalty - expansion_penalty
```

### 5.6 choose_adaptive_topics

```python
def choose_adaptive_topics(state, blueprint, config, evidence_manager, mode: str) -> tuple[str, ...]:
    scored = []

    for topic in blueprint.topics:
        score = score_topic(topic, mode, state, blueprint, config, evidence_manager)
        if score != float("-inf"):
            scored.append((score, topic))

    scored.sort(key=lambda x: x[0], reverse=True)
    return tuple(topic for _, topic in scored[: config.planner.topics_per_round])
```

---

## 6. Dynamic single_k and multi_k Calculation

### 6.1 Overview

The planner dynamically computes `single_k` and `multi_k` from:

1. blueprint target count,
2. current candidate counts,
3. remaining rounds for the current mode,
4. selected topic count,
5. difficulty-driven chunk mix,
6. mode adjustment,
7. generation yield,
8. chunk limits.

### 6.2 mode_candidate_target

```python
def mode_candidate_target(blueprint, mode: str) -> int:
    return math.ceil(
        blueprint.modes[mode].count * blueprint.candidate_pool.target_multiplier
    )
```

### 6.3 estimate_remaining_rounds_for_mode

```python
def estimate_remaining_rounds_for_mode(state, blueprint, mode: str) -> int:
    remaining_rounds = max(1, blueprint.max_rounds - state.round_num + 1)
    mode_count = len(blueprint.mode_order)
    return max(1, math.ceil(remaining_rounds / mode_count))
```

### 6.4 resolve_chunk_mix

```python
def resolve_chunk_mix(mode: str, difficulty: str, config) -> tuple[float, float]:
    base = config.chunk_mix.by_difficulty[difficulty]
    single_ratio = base.single_ratio

    mode_delta = config.chunk_mix.mode_adjustment.get(mode, {}).get("single_delta", 0.0)
    single_ratio += mode_delta

    single_ratio = max(0.0, min(1.0, single_ratio))
    multi_ratio = 1.0 - single_ratio

    return single_ratio, multi_ratio
```

### 6.5 compute_dynamic_chunk_k

```python
def compute_dynamic_chunk_k(
    state,
    blueprint,
    config,
    mode: str,
    difficulty: str,
    selected_topic_count: int,
) -> tuple[int, int, int]:
    target = mode_candidate_target(blueprint, mode)
    current = state.mode_counts.get(mode, 0)
    gap = max(0, target - current)

    remaining_mode_rounds = estimate_remaining_rounds_for_mode(state, blueprint, mode)

    target_candidates_this_mode_round = max(
        1,
        math.ceil(gap / remaining_mode_rounds),
    )

    target_candidates_per_topic = max(
        1,
        math.ceil(target_candidates_this_mode_round / max(1, selected_topic_count)),
    )

    single_ratio, multi_ratio = resolve_chunk_mix(mode, difficulty, config)

    single_candidate_target = target_candidates_per_topic * single_ratio
    multi_candidate_target = target_candidates_per_topic * multi_ratio

    yield_cfg = config.generation_yield[mode]

    single_k = math.ceil(single_candidate_target / yield_cfg.single_chunk_avg_questions)
    multi_k = math.ceil(multi_candidate_target / yield_cfg.multi_chunk_avg_questions)

    limits = config.chunk_limits[mode]

    single_k = max(limits.single_k.min, min(limits.single_k.max, single_k))
    multi_k = max(limits.multi_k.min, min(limits.multi_k.max, multi_k))

    return single_k, multi_k, target_candidates_per_topic
```

---

## 7. Required Helper Functions

### 7.1 expected_candidates_per_topic

This is a soft coverage score, not a hard balancing rule.

```python
def expected_candidates_per_topic(state, blueprint) -> float:
    total_target = sum(m.count for m in blueprint.modes.values())
    candidate_target = total_target * blueprint.candidate_pool.target_multiplier
    return candidate_target / max(1, len(blueprint.topics))
```

### 7.2 expected_candidates_per_topic_mode

```python
def expected_candidates_per_topic_mode(state, blueprint, mode: str) -> float:
    mode_target = blueprint.modes[mode].count * blueprint.candidate_pool.target_multiplier
    return mode_target / max(1, len(blueprint.topics))
```

### 7.3 no_available_topics

```python
def no_available_topics(state, blueprint, config, evidence_manager) -> bool:
    for topic in blueprint.topics:
        if is_topic_in_cooldown(state, topic):
            continue

        if is_topic_exhausted(topic, state, config, evidence_manager):
            continue

        max_attempts = config.topic_safety.max_attempts_per_topic
        if max_attempts is not None and state.topic_attempts.get(topic, 0) >= max_attempts:
            continue

        return False

    return True
```

### 7.4 is_topic_in_cooldown

```python
def is_topic_in_cooldown(state, topic: str) -> bool:
    until_round = state.topic_cooldown_until_round.get(topic)
    return until_round is not None and state.round_num < until_round
```

### 7.5 is_topic_exhausted

```python
def is_topic_exhausted(topic, state, config, evidence_manager) -> bool:
    available = evidence_manager.available_counts(topic)

    total_available = available.total_single + available.total_multi
    total_unused = available.unused_single + available.unused_multi

    if total_available <= 0:
        return state.topic_expansion_counts.get(topic, 0) >= config.retrieval_safety.max_expansions_per_topic

    used_ratio = 1.0 - (total_unused / max(1, total_available))

    return (
        used_ratio >= config.retrieval_safety.chunk_exhaustion_ratio
        and state.topic_expansion_counts.get(topic, 0) >= config.retrieval_safety.max_expansions_per_topic
    )
```

### 7.6 build_reason

```python
def build_reason(action, mode, difficulty, topics, state, blueprint, extra="") -> str:
    topic_preview = ", ".join(topics[:5])
    if len(topics) > 5:
        topic_preview += f", ... (+{len(topics) - 5} more)"

    mode_count = state.mode_counts.get(mode, 0) if mode else 0
    difficulty_count = (
        state.mode_difficulty_counts[mode].get(difficulty, 0)
        if mode and difficulty
        else 0
    )

    return (
        f"Action={action}. "
        f"Mode={mode}, difficulty={difficulty}. "
        f"Selected topics=[{topic_preview}]. "
        f"Current mode count={mode_count}, "
        f"current mode-difficulty count={difficulty_count}. "
        f"{extra}"
    ).strip()
```

---

## 8. EvidenceManager Requirements

### 8.1 Required methods

```python
class EvidenceManager:
    def sample_single(self, topic: str, target_mode: str, target_difficulty: str, k: int) -> list:
        ...

    def sample_multi(self, topic: str, target_mode: str, target_difficulty: str, k: int) -> list:
        ...

    def expand_retrieval(self, topic: str, queries: list[str]) -> None:
        ...

    def supplement_multi_chunks(self, topic: str) -> None:
        ...

    def available_counts(self, topic: str) -> EvidenceAvailability:
        ...
```

### 8.2 EvidenceAvailability

```python
@dataclass(frozen=True)
class EvidenceAvailability:
    total_single: int
    unused_single: int
    total_multi: int
    unused_multi: int
```

### 8.3 EvidenceShortageError

```python
class EvidenceShortageError(Exception):
    pass
```

`sample_single` and `sample_multi` should raise `EvidenceShortageError` when not enough evidence is available.

---

## 9. Executor

### 9.1 execute_round_plan

```python
def execute_round_plan(round_plan, state, blueprint, config, evidence_manager, generator):
    if round_plan.action == "stop_generation":
        return

    topic_results = []

    for topic in round_plan.topics:
        topic_plan = TopicExecutionPlan(
            round_plan=round_plan,
            topic=topic,
            single_k=round_plan.single_k,
            multi_k=round_plan.multi_k,
            retrieval_strategy=round_plan.retrieval_strategy,
            action=round_plan.action,
            reason=round_plan.reason,
        )

        result = execute_topic_plan(topic_plan, state, blueprint, config, evidence_manager, generator)
        topic_results.append(result)

        update_state_from_result(state, round_plan, topic, result, config)

    update_round_level_state_after_round(state, round_plan)

    return topic_results
```

### 9.2 execute_topic_plan

Only evidence shortage should trigger fallback. API timeouts and network/API errors should not trigger evidence fallback loops.

```python
import asyncio

class APIError(Exception):
    pass

def execute_topic_plan(topic_plan, state, blueprint, config, evidence_manager, generator):
    fallback_plans = build_fallback_topic_plans(topic_plan, config)
    last_error = None

    for candidate_plan in fallback_plans:
        try:
            single_units = evidence_manager.sample_single(
                topic=candidate_plan.topic,
                target_mode=candidate_plan.round_plan.mode,
                target_difficulty=candidate_plan.round_plan.difficulty,
                k=candidate_plan.single_k,
            )

            multi_units = evidence_manager.sample_multi(
                topic=candidate_plan.topic,
                target_mode=candidate_plan.round_plan.mode,
                target_difficulty=candidate_plan.round_plan.difficulty,
                k=candidate_plan.multi_k,
            )

            chunks = single_units + multi_units

            raw_output = generator.generate(
                topic=candidate_plan.topic,
                mode=candidate_plan.round_plan.mode,
                difficulty=candidate_plan.round_plan.difficulty,
                chunks=chunks,
                language=blueprint.language,
            )

            parsed_questions = parse_questions(raw_output)

            return {
                "success": True,
                "topic": candidate_plan.topic,
                "chunks": chunks,
                "raw_output": raw_output,
                "parsed_questions": parsed_questions,
                "error": None,
                "failure_type": None,
            }

        except EvidenceShortageError as exc:
            last_error = exc
            continue

        except (asyncio.TimeoutError, APIError, ConnectionError) as exc:
            last_error = exc
            break

        except Exception as exc:
            last_error = exc
            break

    return {
        "success": False,
        "topic": topic_plan.topic,
        "chunks": [],
        "raw_output": None,
        "parsed_questions": [],
        "error": str(last_error),
        "failure_type": classify_failure(last_error),
    }
```

### 9.3 build_fallback_topic_plans

```python
from dataclasses import replace

def build_fallback_topic_plans(topic_plan: TopicExecutionPlan, config) -> list[TopicExecutionPlan]:
    plans = [topic_plan]

    if topic_plan.multi_k > 0:
        plans.append(
            replace(
                topic_plan,
                multi_k=max(0, topic_plan.multi_k - 1),
                retrieval_strategy="fallback_reduce_multi",
                reason=topic_plan.reason + "; fallback: reduce multi_k by 1",
            )
        )

    if topic_plan.single_k > 0 and topic_plan.multi_k > 0:
        plans.append(
            replace(
                topic_plan,
                multi_k=0,
                retrieval_strategy="fallback_single_only",
                reason=topic_plan.reason + "; fallback: single-only",
            )
        )

    return plans
```

---

## 10. State Update

### 10.1 update_state_from_result

```python
def update_state_from_result(state, round_plan, topic, result, config):
    state.topic_attempts[topic] += 1

    if result["success"]:
        parsed_questions = result["parsed_questions"]

        for q in parsed_questions:
            mode = normalize_mode(q.get("mode") or q.get("question_mode") or round_plan.mode)
            actual_difficulty = normalize_difficulty(
                q.get("estimated_difficulty") or q.get("difficulty") or round_plan.difficulty
            )

            state.candidate_questions.append(q)
            state.mode_counts[mode] += 1
            state.difficulty_counts[actual_difficulty] += 1
            state.mode_difficulty_counts[mode][actual_difficulty] += 1
            state.topic_counts[topic] += 1
            state.topic_mode_counts[topic][mode] += 1

        state.topic_consecutive_failures[topic] = 0
        state.global_consecutive_failures = 0

        if round_plan.action == "initial_breadth_generate":
            mark_initial_coverage(state, topic, round_plan.mode)

    else:
        state.topic_consecutive_failures[topic] += 1
        state.global_consecutive_failures += 1
        state.global_failures += 1

        state.failure_history.append({
            "round": state.round_num,
            "topic": topic,
            "mode": round_plan.mode,
            "difficulty": round_plan.difficulty,
            "error": result.get("error"),
            "failure_type": result.get("failure_type"),
        })

        if state.topic_consecutive_failures[topic] >= config.topic_safety.max_consecutive_failures_per_topic:
            state.topic_cooldown_until_round[topic] = (
                state.round_num + config.topic_safety.cooldown_rounds_after_failure
            )

        if round_plan.action == "initial_breadth_generate":
            mark_initial_coverage(state, topic, round_plan.mode)
```

### 10.2 update_round_level_state_after_round

```python
def update_round_level_state_after_round(state, round_plan):
    if round_plan.strategy == "hard_focus":
        state.consecutive_hard_focus_rounds += 1
    else:
        state.consecutive_hard_focus_rounds = 0

    state.round_num += 1
```

---

## 11. Stop Conditions

### 11.1 should_stop

`evidence_manager` is required. Do not make it optional.

```python
def should_stop(state, blueprint, config, evidence_manager) -> tuple[bool, str | None]:
    if candidate_pool_sufficient(state, blueprint, config):
        return True, "candidate_pool_sufficient"

    if state.round_num > blueprint.max_rounds:
        return True, "max_rounds_reached"

    if no_available_topics(state, blueprint, config, evidence_manager):
        return True, "no_available_topics"

    if state.global_consecutive_failures >= config.runtime.max_global_consecutive_failures:
        return True, "global_consecutive_failures_reached"

    if state.global_failures >= config.runtime.max_global_failures:
        return True, "global_failure_limit_reached"

    return False, None
```

### 11.2 candidate_pool_sufficient

```python
def candidate_pool_sufficient(state, blueprint, config) -> bool:
    total_target = sum(m.count for m in blueprint.modes.values())
    target_candidates = math.ceil(total_target * blueprint.candidate_pool.target_multiplier)

    if len(state.candidate_questions) < target_candidates:
        return False

    for mode, mode_cfg in blueprint.modes.items():
        min_mode_candidates = math.ceil(
            mode_cfg.count * blueprint.candidate_pool.min_mode_multiplier
        )

        if state.mode_counts.get(mode, 0) < min_mode_candidates:
            return False

    difficulty_targets = compute_expected_difficulty_targets(blueprint)

    for difficulty, target_count in difficulty_targets.items():
        min_difficulty_candidates = math.ceil(
            target_count * blueprint.candidate_pool.min_difficulty_multiplier
        )

        if state.difficulty_counts.get(difficulty, 0) < min_difficulty_candidates:
            return False

    return True
```

### 11.3 compute_expected_difficulty_targets

```python
def compute_expected_difficulty_targets(blueprint) -> dict[str, float]:
    targets = defaultdict(float)

    for mode_cfg in blueprint.modes.values():
        for difficulty, ratio in mode_cfg.difficulty_distribution.items():
            targets[difficulty] += mode_cfg.count * ratio

    return dict(targets)
```

---

## 12. Serialization

### 12.1 used_chunk_combinations

Do not directly JSON serialize `set[frozenset[str]]`.

Preferred internal representation:

```python
set[tuple[str, ...]]
```

Normalize before storing:

```python
combo = tuple(sorted(chunk_ids))
state.used_chunk_combinations.add(combo)
```

Export:

```python
def serialize_used_chunk_combinations(state):
    return [list(combo) for combo in sorted(state.used_chunk_combinations)]
```

### 12.2 Size cap

Use a cap to avoid unbounded memory growth:

```yaml
runtime:
  max_used_chunk_combinations: 10000
```

---

## 13. Output Files

Write:

```text
runs/{run_id}/candidate_pool.json
runs/{run_id}/generation_trace.json
runs/{run_id}/generation_state.json
runs/{run_id}/generation_report.json
runs/{run_id}/used_chunks.json
```

`generation_trace.json` should include each round's observation, round plan, topic results, and actual generated difficulty distribution.

---

## 14. Implementation Checklist

Must implement before running:

- [ ] `GenerationState.initial_coverage`
- [ ] `state_has_initial_coverage`
- [ ] `is_initial_breadth_phase`
- [ ] `mark_initial_coverage`
- [ ] `global_consecutive_failures`
- [ ] `RoundPlan.topics: tuple[str, ...]`
- [ ] `TopicExecutionPlan`
- [ ] `EvidenceShortageError`
- [ ] exception-specific fallback behavior
- [ ] `score_topic` excludes exhausted topics
- [ ] `should_stop(..., evidence_manager)` with required evidence manager
- [ ] state update uses actual parsed question difficulty
- [ ] dynamic `single_k` / `multi_k` computation using `generation_yield`
- [ ] JSON-safe serialization for used chunk combinations

---

## 15. Acceptance Criteria

The implementation is acceptable if:

1. Initial breadth covers every `(topic, mode)` pair at least once, or logs why it could not.
2. No function referenced in pseudocode is undefined.
3. `RoundPlan` is not mutated during execution.
4. Fallback creates new `TopicExecutionPlan` objects.
5. API timeout does not trigger evidence fallback loops.
6. State records actual parsed difficulty, not only planned difficulty.
7. Stop conditions correctly handle candidate sufficiency, max rounds, no available topics, global consecutive failures, and global failure limit.
8. `generation_yield` is used to compute dynamic `single_k` and `multi_k`.
9. `used_chunk_combinations` can be exported as valid JSON.
10. Large topic lists are batched during initial breadth by `initial_breadth.max_topics_per_round`.

---

## 16. Summary

v3 finalizes the design as:

> Blueprint-guided, mode-rotating, round-plan-based adaptive chunk sampling for candidate benchmark generation.

The generation agent:

1. uses blueprint counts only for observation and candidate-pool sufficiency,
2. rotates QA and multiple-choice modes,
3. performs initial breadth over topic/mode pairs,
4. computes `single_k` and `multi_k` dynamically from candidate gaps and generation yield,
5. samples single and multi chunks separately,
6. generates candidate questions from the resulting chunk list,
7. updates state using actual parsed question fields,
8. stops when the candidate pool is sufficient or protective limits are reached.
