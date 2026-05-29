# BenchForge Adaptive Chunk Generation Agent - Technical Spec v4

## 0. Purpose and Revision History

This document is the implementation-ready specification for a blueprint-guided, mode-rotating, round-plan-based adaptive chunk-sampling candidate generation agent for BenchForge.

### v4 fixes the following issues identified in v3:

1. **Problem 1 (blocking):** `choose_round_action` was called but never defined. Now defined with full evidence-availability logic.
2. **Problem 2 (blocking):** `classify_failure`, `normalize_mode`, and `normalize_difficulty` were missing. All three are now defined.
3. **Problem 3 (medium):** `build_round_plan` could return a `RoundPlan` with empty `topics` during initial breadth when all topics are in cooldown, causing infinite empty rounds. Fixed by adding empty-topics handling that falls back to adaptive, and ultimately to a stop plan.
4. **Problem 4 (medium):** `used_chunk_combinations` had a configured size cap but no eviction logic. Restored `used_chunk_combination_order: deque` and the `record_used_chunk_combination` function with proper LRU eviction.
5. **Problem 5 (medium):** `execute_topic_plan` and `execute_round_plan` were synchronous, incompatible with the existing async OpenAI client. Both are now `async def`.
6. **Problem 6 (low):** `build_fallback_topic_plans` only reduced `multi_k`, leaving `single_k` shortage unhandled. Updated to cover all shortage cases: reduce multi, reduce single, single-only, multi-only, and minimal fallbacks.

The generation agent builds a candidate question pool. It does not attempt to precisely produce the final benchmark question count. Downstream validation agents handle quality validation, answer checking, deduplication, difficulty calibration, and final benchmark sampling.

---

## 1. Core Principles

### 1.1 Blueprint counts are targets, not per-round generation commands

Blueprint counts such as `qa.count = 30` are used for state observation and stopping conditions only. They do not tell the generator exactly how many questions to produce in a round.

### 1.2 The planner controls chunk sampling

Each round plan decides: mode, target difficulty, selected topics, `single_k`, `multi_k`, action, strategy, and reason. The generator receives a chunk list and produces candidate questions.

### 1.3 Single/multi chunk mix is primarily difficulty-driven

- easy: mostly single chunks
- medium: balanced
- hard: mostly multi chunks

Mode is a secondary adjustment: QA slightly favors single; multiple-choice slightly favors multi.

### 1.4 Round-level planning, topic-level feedback

The planner creates one `RoundPlan` per round. Execution updates state after each topic. Replanning occurs only at the start of the next round.

---

## 2. Blueprint Schema

```yaml
run_id: benchmark_generation_v4
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

Use only `candidate_pool.target_multiplier`. Do not introduce a duplicate stop-policy multiplier.

---

## 3. Data Structures

### 3.1 RoundPlan

`RoundPlan` must be immutable. Use `tuple[str, ...]` for `topics` to prevent mutation.

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

Do not modify a `RoundPlan` during execution. All topic-level changes must use `TopicExecutionPlan`.

### 3.2 TopicExecutionPlan

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

When fallback is needed, create a new `TopicExecutionPlan` with `dataclasses.replace`. Never mutate `RoundPlan`.

### 3.3 GenerationState

```python
from dataclasses import dataclass, field
from collections import defaultdict, deque
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

    # Tracks which (topic, mode) pairs have been attempted in initial breadth.
    initial_coverage: set[tuple[str, str]] = field(default_factory=set)

    topic_attempts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    topic_consecutive_failures: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    topic_cooldown_until_round: dict[str, int] = field(default_factory=dict)
    topic_expansion_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Global failure tracking (restored from v2, fixes v3 issue).
    global_consecutive_failures: int = 0
    global_failures: int = 0

    # Hard-focus tracking.
    consecutive_hard_focus_rounds: int = 0

    # Chunk combination deduplication with LRU cap (restored from v2).
    used_chunk_combinations: set[tuple[str, ...]] = field(default_factory=set)
    used_chunk_combination_order: deque[tuple[str, ...]] = field(default_factory=deque)

    failure_history: list[dict[str, Any]] = field(default_factory=list)
    round_traces: list[dict[str, Any]] = field(default_factory=list)
```

### 3.4 EvidenceAvailability

```python
@dataclass(frozen=True)
class EvidenceAvailability:
    total_single: int
    unused_single: int
    total_multi: int
    unused_multi: int
```

### 3.5 EvidenceShortageError

Carry shortage kind and counts to enable precise fallback decisions.

```python
class EvidenceShortageError(Exception):
    def __init__(self, kind: str, required: int, available: int):
        self.kind = kind        # "single" or "multi"
        self.required = required
        self.available = available
        super().__init__(
            f"{kind} evidence shortage: required={required}, available={available}"
        )
```

### 3.6 APIError

```python
class APIError(Exception):
    pass
```

---

## 4. Normalization and Classification Helpers

These functions must be defined. They were missing in v3.

### 4.1 normalize_mode

```python
def normalize_mode(value: str | None) -> str:
    if not value:
        return "qa"

    value = str(value).strip().lower()

    aliases = {
        "qa": "qa",
        "q&a": "qa",
        "question_answer": "qa",
        "question-answer": "qa",
        "short_answer": "qa",
        "multiple_choice": "multiple_choice",
        "multiple-choice": "multiple_choice",
        "mcq": "multiple_choice",
        "choice": "multiple_choice",
    }

    return aliases.get(value, value)
```

### 4.2 normalize_difficulty

```python
def normalize_difficulty(value: str | None) -> str:
    if not value:
        return "medium"

    value = str(value).strip().lower()

    aliases = {
        "easy": "easy",
        "simple": "easy",
        "low": "easy",
        "medium": "medium",
        "moderate": "medium",
        "normal": "medium",
        "hard": "hard",
        "difficult": "hard",
        "high": "hard",
        "advanced": "hard",
    }

    return aliases.get(value, "medium")
```

### 4.3 classify_failure

```python
import asyncio


def classify_failure(exc: Exception | None) -> str:
    if exc is None:
        return "unknown"

    if isinstance(exc, EvidenceShortageError):
        return "evidence_shortage"

    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"

    if isinstance(exc, ConnectionError):
        return "connection_error"

    if isinstance(exc, APIError):
        return "api_error"

    name = exc.__class__.__name__.lower()
    message = str(exc).lower()

    if "json" in name or "parse" in name or "json" in message:
        return "parse_error"

    if "timeout" in name or "timeout" in message:
        return "timeout"

    if "rate" in message and "limit" in message:
        return "rate_limit"

    return "unknown_error"
```

---

## 5. Initial Breadth Coverage

### 5.1 Semantics

Initial breadth ensures each `(topic, mode)` pair is attempted at least once, batched by `initial_breadth.max_topics_per_round`. An attempt is marked even when zero questions are generated, because the exploration itself matters.

### 5.2 state_has_initial_coverage

```python
def state_has_initial_coverage(state: GenerationState, topic: str, mode: str) -> bool:
    return (topic, mode) in state.initial_coverage
```

### 5.3 mark_initial_coverage

```python
def mark_initial_coverage(state: GenerationState, topic: str, mode: str) -> None:
    state.initial_coverage.add((topic, mode))
```

### 5.4 is_initial_breadth_phase

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

### 5.5 build_initial_breadth_round_plan

Returns a plan with empty `topics` if every topic is currently in cooldown or exhausted. The caller must handle this case.

```python
def build_initial_breadth_round_plan(
    state: GenerationState,
    blueprint,
    config,
) -> RoundPlan:
    mode = choose_mode_by_rotation(state.round_num, blueprint.mode_order)

    uncovered = [
        topic
        for topic in blueprint.topics
        if not state_has_initial_coverage(state, topic, mode)
        and not is_topic_in_cooldown(state, topic)
    ]
    topics = tuple(uncovered[: config.initial_breadth.max_topics_per_round])

    # If rotation mode has nothing, try other modes (skip the already-tried mode).
    if not topics:
        for fallback_mode in blueprint.mode_order:
            if fallback_mode == mode:
                continue
            uncovered = [
                topic
                for topic in blueprint.topics
                if not state_has_initial_coverage(state, topic, fallback_mode)
                and not is_topic_in_cooldown(state, topic)
            ]
            if uncovered:
                mode = fallback_mode
                topics = tuple(uncovered[: config.initial_breadth.max_topics_per_round])
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

---

## 6. Planner

### 6.1 build_stop_plan

Used in any branch that needs to terminate generation.

```python
def build_stop_plan(state: GenerationState, reason: str) -> RoundPlan:
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
```

### 6.2 build_adaptive_round_plan

Extracted from `build_round_plan` to allow fallback from blocked initial breadth.

```python
def build_adaptive_round_plan(
    state: GenerationState,
    blueprint,
    config,
    evidence_manager,
) -> RoundPlan:
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

### 6.3 build_round_plan

`evidence_manager` is required. Handles the initial-breadth empty-topics case.

```python
def build_round_plan(
    state: GenerationState,
    blueprint,
    config,
    evidence_manager,
) -> RoundPlan:
    stop, reason = should_stop(state, blueprint, config, evidence_manager)
    if stop:
        return build_stop_plan(state, reason)

    if is_initial_breadth_phase(state, blueprint, config):
        plan = build_initial_breadth_round_plan(state, blueprint, config)

        if plan.topics:
            return plan

        # Initial breadth is still incomplete but all uncovered topics are in
        # cooldown or exhausted. Fall back to adaptive rather than returning an
        # empty plan that would cause a silent empty round.
        adaptive_plan = build_adaptive_round_plan(
            state=state,
            blueprint=blueprint,
            config=config,
            evidence_manager=evidence_manager,
        )

        if adaptive_plan.topics:
            return adaptive_plan

        # No topics available anywhere. Stop.
        return build_stop_plan(state, "initial_breadth_blocked_no_available_topics")

    return build_adaptive_round_plan(
        state=state,
        blueprint=blueprint,
        config=config,
        evidence_manager=evidence_manager,
    )
```

### 6.4 choose_mode_by_rotation

```python
def choose_mode_by_rotation(round_num: int, mode_order: list[str]) -> str:
    return mode_order[(round_num - 1) % len(mode_order)]
```

### 6.5 choose_difficulty

Uses actual generated difficulty counts.

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

### 6.6 choose_chunk_strategy

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
        and state.consecutive_hard_focus_rounds
            < config.difficulty_policy.max_consecutive_hard_focus_rounds
    ):
        return "hard_focus"

    return "default"
```

### 6.7 choose_round_action

Determines round action based on evidence availability across selected topics.

```python
def choose_round_action(
    topics: tuple[str, ...],
    state: GenerationState,
    blueprint,
    config,
    evidence_manager,
    single_k: int,
    multi_k: int,
) -> str:
    if not topics:
        return "skip_round"

    any_need_expansion = False
    any_need_supplement = False

    for topic in topics:
        available = evidence_manager.available_counts(topic)

        if available.unused_single < single_k:
            any_need_expansion = True

        if available.unused_multi < multi_k:
            if available.total_single > 0:
                any_need_supplement = True
            else:
                any_need_expansion = True

    if any_need_expansion:
        return "expand_retrieval_then_generate"

    if any_need_supplement:
        return "supplement_chunks_then_generate"

    return "generate_with_existing_chunks"
```

### 6.8 choose_adaptive_topics

```python
def choose_adaptive_topics(
    state: GenerationState,
    blueprint,
    config,
    evidence_manager,
    mode: str,
) -> tuple[str, ...]:
    scored = []

    for topic in blueprint.topics:
        score = score_topic(topic, mode, state, blueprint, config, evidence_manager)
        if score != float("-inf"):
            scored.append((score, topic))

    scored.sort(key=lambda x: x[0], reverse=True)
    return tuple(topic for _, topic in scored[: config.planner.topics_per_round])
```

### 6.9 score_topic

Exhausted topics are excluded at scoring time, not only at execution time.

```python
def score_topic(
    topic: str,
    mode: str,
    state: GenerationState,
    blueprint,
    config,
    evidence_manager,
) -> float:
    if is_topic_in_cooldown(state, topic):
        return float("-inf")

    if is_topic_exhausted(topic, state, config, evidence_manager):
        return float("-inf")

    max_attempts = config.topic_safety.max_attempts_per_topic
    if max_attempts is not None and state.topic_attempts.get(topic, 0) >= max_attempts:
        return float("-inf")

    topic_gap = (
        expected_candidates_per_topic(state, blueprint)
        - state.topic_counts.get(topic, 0)
    )
    topic_mode_gap = (
        expected_candidates_per_topic_mode(state, blueprint, mode)
        - state.topic_mode_counts[topic].get(mode, 0)
    )

    failure_penalty = state.topic_consecutive_failures.get(topic, 0) * 2.0
    expansion_penalty = state.topic_expansion_counts.get(topic, 0) * 0.5

    return topic_gap + topic_mode_gap - failure_penalty - expansion_penalty
```

---

## 7. Dynamic single_k and multi_k Calculation

### 7.1 mode_candidate_target

```python
import math


def mode_candidate_target(blueprint, mode: str) -> int:
    return math.ceil(
        blueprint.modes[mode].count * blueprint.candidate_pool.target_multiplier
    )
```

### 7.2 estimate_remaining_rounds_for_mode

```python
def estimate_remaining_rounds_for_mode(state, blueprint, mode: str) -> int:
    remaining_rounds = max(1, blueprint.max_rounds - state.round_num + 1)
    mode_count = len(blueprint.mode_order)
    return max(1, math.ceil(remaining_rounds / mode_count))
```

### 7.3 resolve_chunk_mix

```python
def resolve_chunk_mix(mode: str, difficulty: str, config) -> tuple[float, float]:
    base = config.chunk_mix.by_difficulty[difficulty]
    single_ratio = base.single_ratio

    mode_delta = config.chunk_mix.mode_adjustment.get(mode, {}).get("single_delta", 0.0)
    single_ratio += mode_delta
    single_ratio = max(0.0, min(1.0, single_ratio))

    return single_ratio, 1.0 - single_ratio
```

### 7.4 compute_dynamic_chunk_k

```python
def compute_dynamic_chunk_k(
    state: GenerationState,
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

    target_this_round = max(1, math.ceil(gap / remaining_mode_rounds))
    target_per_topic = max(1, math.ceil(target_this_round / max(1, selected_topic_count)))

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

## 8. Required Helper Functions

### 8.1 expected_candidates_per_topic

```python
def expected_candidates_per_topic(state, blueprint) -> float:
    total_target = sum(m.count for m in blueprint.modes.values())
    candidate_target = total_target * blueprint.candidate_pool.target_multiplier
    return candidate_target / max(1, len(blueprint.topics))
```

### 8.2 expected_candidates_per_topic_mode

```python
def expected_candidates_per_topic_mode(state, blueprint, mode: str) -> float:
    mode_target = blueprint.modes[mode].count * blueprint.candidate_pool.target_multiplier
    return mode_target / max(1, len(blueprint.topics))
```

### 8.3 is_topic_in_cooldown

```python
def is_topic_in_cooldown(state: GenerationState, topic: str) -> bool:
    until_round = state.topic_cooldown_until_round.get(topic)
    return until_round is not None and state.round_num < until_round
```

### 8.4 is_topic_exhausted

```python
def is_topic_exhausted(topic: str, state, config, evidence_manager) -> bool:
    available = evidence_manager.available_counts(topic)

    total_available = available.total_single + available.total_multi
    total_unused = available.unused_single + available.unused_multi

    if total_available <= 0:
        return (
            state.topic_expansion_counts.get(topic, 0)
            >= config.retrieval_safety.max_expansions_per_topic
        )

    used_ratio = 1.0 - (total_unused / max(1, total_available))

    return (
        used_ratio >= config.retrieval_safety.chunk_exhaustion_ratio
        and state.topic_expansion_counts.get(topic, 0)
            >= config.retrieval_safety.max_expansions_per_topic
    )
```

### 8.5 no_available_topics

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

### 8.6 build_reason

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

## 9. EvidenceManager Requirements

### 9.1 Required methods

```python
class EvidenceManager:
    def sample_single(
        self,
        topic: str,
        target_mode: str,
        target_difficulty: str,
        k: int,
    ) -> list: ...

    def sample_multi(
        self,
        topic: str,
        target_mode: str,
        target_difficulty: str,
        k: int,
    ) -> list: ...

    async def expand_retrieval(self, topic: str, queries: list[str]) -> None: ...

    async def supplement_multi_chunks(self, topic: str) -> None: ...

    def available_counts(self, topic: str) -> EvidenceAvailability: ...
```

`sample_single` and `sample_multi` are synchronous because they operate on an in-memory pool; they raise `EvidenceShortageError(kind, required, available)` when the pool cannot satisfy the request.

`expand_retrieval` and `supplement_multi_chunks` are `async` because they perform network I/O (external retrieval). `available_counts` is synchronous because it reads local metadata only.

---

## 10. Executor

### 10.1 execute_round_plan

```python
async def execute_round_plan(
    round_plan: RoundPlan,
    state: GenerationState,
    blueprint,
    config,
    evidence_manager,
    generator,
) -> list[dict] | None:
    if round_plan.action == "stop_generation":
        return None

    if not round_plan.topics:
        # Explicit guard: never silently loop over an empty plan.
        return []

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

        result = await execute_topic_plan(
            topic_plan=topic_plan,
            state=state,
            blueprint=blueprint,
            config=config,
            evidence_manager=evidence_manager,
            generator=generator,
        )

        topic_results.append(result)
        update_state_from_result(state, round_plan, topic, result, config)

    update_round_level_state_after_round(state, round_plan)

    return topic_results
```

### 10.2 execute_topic_plan

Only `EvidenceShortageError` triggers evidence fallback. API timeouts and connection errors do not trigger evidence fallback loops.

Retrieval actions (`expand_retrieval_then_generate`, `supplement_chunks_then_generate`) are dispatched **once** before the first sampling attempt. If the retrieval itself raises a non-evidence error, execution breaks immediately. Subsequent fallback plans (which reduce k) do not re-trigger retrieval.

```python
async def execute_topic_plan(
    topic_plan: TopicExecutionPlan,
    state: GenerationState,
    blueprint,
    config,
    evidence_manager,
    generator,
) -> dict:
    fallback_plans = build_fallback_topic_plans(topic_plan, config)
    last_error = None

    # Dispatch retrieval action once, before the fallback loop.
    # Only EvidenceShortageError from sampling triggers fallback plans;
    # errors raised during retrieval dispatch break out immediately.
    try:
        if topic_plan.action == "expand_retrieval_then_generate":
            await evidence_manager.expand_retrieval(
                topic=topic_plan.topic,
                queries=[topic_plan.topic],
            )
        elif topic_plan.action == "supplement_chunks_then_generate":
            await evidence_manager.supplement_multi_chunks(
                topic=topic_plan.topic,
            )
    except (asyncio.TimeoutError, APIError, ConnectionError) as exc:
        return {
            "success": False,
            "topic": topic_plan.topic,
            "executed_strategy": topic_plan.retrieval_strategy,
            "chunks": [],
            "raw_output": None,
            "parsed_questions": [],
            "error": str(exc),
            "failure_type": classify_failure(exc),
        }

    for candidate_plan in fallback_plans:
        try:
            single_units = (
                evidence_manager.sample_single(
                    topic=candidate_plan.topic,
                    target_mode=candidate_plan.round_plan.mode,
                    target_difficulty=candidate_plan.round_plan.difficulty,
                    k=candidate_plan.single_k,
                )
                if candidate_plan.single_k > 0
                else []
            )

            multi_units = (
                evidence_manager.sample_multi(
                    topic=candidate_plan.topic,
                    target_mode=candidate_plan.round_plan.mode,
                    target_difficulty=candidate_plan.round_plan.difficulty,
                    k=candidate_plan.multi_k,
                )
                if candidate_plan.multi_k > 0
                else []
            )

            chunks = single_units + multi_units

            raw_output = await generator.generate(
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
                "executed_strategy": candidate_plan.retrieval_strategy,
                "chunks": chunks,
                "raw_output": raw_output,
                "parsed_questions": parsed_questions,
                "error": None,
                "failure_type": None,
            }

        except EvidenceShortageError as exc:
            # Evidence problem: try the next fallback plan.
            last_error = exc
            continue

        except (asyncio.TimeoutError, APIError, ConnectionError) as exc:
            # API/network problem: do not retry with smaller evidence.
            last_error = exc
            break

        except Exception as exc:
            last_error = exc
            break

    return {
        "success": False,
        "topic": topic_plan.topic,
        "executed_strategy": topic_plan.retrieval_strategy,
        "chunks": [],
        "raw_output": None,
        "parsed_questions": [],
        "error": str(last_error),
        "failure_type": classify_failure(last_error),
    }
```

### 10.3 build_fallback_topic_plans

Covers both single and multi shortage cases. Uses `dataclasses.replace` to create new immutable plans.

```python
from dataclasses import replace


def build_fallback_topic_plans(
    topic_plan: TopicExecutionPlan,
    config,
) -> list[TopicExecutionPlan]:
    plans = [topic_plan]
    seen = {(topic_plan.single_k, topic_plan.multi_k)}

    def add(single_k: int, multi_k: int, strategy: str) -> None:
        single_k = max(0, single_k)
        multi_k = max(0, multi_k)
        key = (single_k, multi_k)
        if key in seen or (single_k == 0 and multi_k == 0):
            return
        seen.add(key)
        plans.append(
            replace(
                topic_plan,
                single_k=single_k,
                multi_k=multi_k,
                retrieval_strategy=strategy,
                reason=topic_plan.reason + f"; fallback: {strategy}",
            )
        )

    # 1. Reduce multi_k first (multi shortage is most common).
    if topic_plan.multi_k > 0:
        add(topic_plan.single_k, topic_plan.multi_k - 1, "fallback_reduce_multi")

    # 2. Reduce single_k (single shortage).
    if topic_plan.single_k > 0:
        add(topic_plan.single_k - 1, topic_plan.multi_k, "fallback_reduce_single")

    # 3. Single-only.
    if topic_plan.single_k > 0:
        add(topic_plan.single_k, 0, "fallback_single_only")

    # 4. Multi-only.
    if topic_plan.multi_k > 0:
        add(0, topic_plan.multi_k, "fallback_multi_only")

    # 5. Minimal one-chunk fallback.
    add(1, 0, "fallback_minimal_single")
    add(0, 1, "fallback_minimal_multi")

    return plans
```

---

## 11. State Update

### 11.1 update_state_from_result

State is updated using actual parsed question fields, not planned fields.

```python
def update_state_from_result(
    state: GenerationState,
    round_plan: RoundPlan,
    topic: str,
    result: dict,
    config,
) -> None:
    state.topic_attempts[topic] += 1

    if result["success"]:
        for q in result["parsed_questions"]:
            mode = normalize_mode(
                q.get("mode") or q.get("question_mode") or round_plan.mode
            )
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

        record_used_chunk_combination(
            state=state,
            chunk_ids=[getattr(c, "chunk_id", getattr(c, "unit_id", str(c))) for c in result["chunks"]],
            max_size=config.runtime.max_used_chunk_combinations,
        )

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

        if (
            state.topic_consecutive_failures[topic]
            >= config.topic_safety.max_consecutive_failures_per_topic
        ):
            state.topic_cooldown_until_round[topic] = (
                state.round_num + config.topic_safety.cooldown_rounds_after_failure
            )

    # Mark initial breadth coverage regardless of success/failure.
    if round_plan.action == "initial_breadth_generate":
        mark_initial_coverage(state, topic, round_plan.mode)
```

### 11.2 update_round_level_state_after_round

Called once per round, after all topics are processed.

```python
def update_round_level_state_after_round(
    state: GenerationState,
    round_plan: RoundPlan,
) -> None:
    if round_plan.strategy == "hard_focus":
        state.consecutive_hard_focus_rounds += 1
    else:
        state.consecutive_hard_focus_rounds = 0

    state.round_num += 1
```

---

## 12. Chunk Combination Tracking

### 12.1 record_used_chunk_combination

LRU eviction is enforced by `used_chunk_combination_order`. This is the implementation that makes `runtime.max_used_chunk_combinations` actually work.

```python
def record_used_chunk_combination(
    state: GenerationState,
    chunk_ids: list[str],
    max_size: int,
) -> None:
    if not chunk_ids:
        return

    combo = tuple(sorted(set(chunk_ids)))

    if combo in state.used_chunk_combinations:
        return

    state.used_chunk_combinations.add(combo)
    state.used_chunk_combination_order.append(combo)

    while len(state.used_chunk_combinations) > max_size:
        oldest = state.used_chunk_combination_order.popleft()
        state.used_chunk_combinations.discard(oldest)
```

### 12.2 serialize_used_chunk_combinations

```python
def serialize_used_chunk_combinations(state: GenerationState) -> list[list[str]]:
    return [list(combo) for combo in state.used_chunk_combination_order]
```

---

## 13. Stop Conditions

### 13.1 should_stop

`evidence_manager` is required. Do not make it optional.

```python
def should_stop(
    state: GenerationState,
    blueprint,
    config,
    evidence_manager,
) -> tuple[bool, str | None]:
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

### 13.2 candidate_pool_sufficient

```python
def candidate_pool_sufficient(
    state: GenerationState,
    blueprint,
    config,
) -> bool:
    total_target = sum(m.count for m in blueprint.modes.values())
    target_candidates = math.ceil(total_target * blueprint.candidate_pool.target_multiplier)

    if len(state.candidate_questions) < target_candidates:
        return False

    for mode, mode_cfg in blueprint.modes.items():
        min_mode = math.ceil(mode_cfg.count * blueprint.candidate_pool.min_mode_multiplier)
        if state.mode_counts.get(mode, 0) < min_mode:
            return False

    difficulty_targets = compute_expected_difficulty_targets(blueprint)

    for difficulty, target_count in difficulty_targets.items():
        min_diff = math.ceil(target_count * blueprint.candidate_pool.min_difficulty_multiplier)
        if state.difficulty_counts.get(difficulty, 0) < min_diff:
            return False

    return True


def compute_expected_difficulty_targets(blueprint) -> dict[str, float]:
    from collections import defaultdict
    targets: dict[str, float] = defaultdict(float)
    for mode_cfg in blueprint.modes.values():
        for difficulty, ratio in mode_cfg.difficulty_distribution.items():
            targets[difficulty] += mode_cfg.count * ratio
    return dict(targets)
```

---

## 14. Main Agent Loop

```python
async def run_generation_agent(
    blueprint,
    config,
    evidence_manager,
    generator,
) -> GenerationState:
    state = GenerationState()

    while True:
        round_plan = build_round_plan(
            state=state,
            blueprint=blueprint,
            config=config,
            evidence_manager=evidence_manager,
        )

        if round_plan.action == "stop_generation":
            break

        # build_round_plan must not return empty-topics non-stop plans.
        # This guard is a second line of defence.
        if not round_plan.topics:
            state.global_consecutive_failures += 1
            state.round_num += 1
            continue

        await execute_round_plan(
            round_plan=round_plan,
            state=state,
            blueprint=blueprint,
            config=config,
            evidence_manager=evidence_manager,
            generator=generator,
        )

    return state
```

Note: `update_round_level_state_after_round` (which increments `state.round_num`) is called inside `execute_round_plan`. The only exception is the empty-topics guard above: when `round_plan.topics` is empty but `action != "stop_generation"`, the main loop manually increments `state.round_num` to prevent an infinite loop, since `execute_round_plan` is bypassed. Do not add any other `state.round_num` increments outside these two locations.

---

## 15. Serialization

### 15.1 generation_state.json

Convert non-JSON-serializable fields before writing:

- `defaultdict` → `dict`
- `set[tuple[str, ...]]` → skip; use `used_chunk_combination_order` via `serialize_used_chunk_combinations`
- `deque` → `list`

### 15.2 used_chunks.json

```json
{
  "used_chunk_combinations": [
    ["chunk_a", "multi_1"],
    ["chunk_b", "multi_3", "multi_4"]
  ],
  "count": 2
}
```

---

## 16. Output Files

```text
runs/{run_id}/candidate_pool.json
runs/{run_id}/generation_trace.json
runs/{run_id}/generation_state.json
runs/{run_id}/generation_report.json
runs/{run_id}/used_chunks.json
```

`generation_trace.json` must include per round: observation summary, round plan, per-topic executed plan, fallback usage, selected chunk ids, generated count, actual difficulty distribution, and failure reasons.

---

## 17. Implementation Checklist

All items must be complete before the first run.

**Data structures**
- [ ] `GenerationState` with `initial_coverage`, `global_consecutive_failures`, `global_failures`, `consecutive_hard_focus_rounds`, `used_chunk_combination_order`
- [ ] `RoundPlan(frozen=True)` with `topics: tuple[str, ...]`
- [ ] `TopicExecutionPlan(frozen=True)`
- [ ] `EvidenceAvailability(frozen=True)`
- [ ] `EvidenceShortageError(kind, required, available)`
- [ ] `APIError`

**Normalization and classification (new in v4)**
- [ ] `normalize_mode`
- [ ] `normalize_difficulty`
- [ ] `classify_failure`

**Planner**
- [ ] `build_stop_plan`
- [ ] `build_adaptive_round_plan`
- [ ] `build_round_plan` with empty-topics fallback
- [ ] `build_initial_breadth_round_plan`
- [ ] `is_initial_breadth_phase`, `state_has_initial_coverage`, `mark_initial_coverage`
- [ ] `choose_round_action` (new in v4)
- [ ] `choose_mode_by_rotation`, `choose_difficulty`, `choose_chunk_strategy`
- [ ] `choose_adaptive_topics`, `score_topic` (excludes exhausted topics)
- [ ] `compute_dynamic_chunk_k`, `resolve_chunk_mix`, `estimate_remaining_rounds_for_mode`
- [ ] `build_reason`

**Helpers**
- [ ] `expected_candidates_per_topic`, `expected_candidates_per_topic_mode`
- [ ] `is_topic_in_cooldown`, `is_topic_exhausted`, `no_available_topics`

**Executor (async)**
- [ ] `async execute_round_plan` with explicit empty-topics guard
- [ ] `async execute_topic_plan` with separated EvidenceShortageError vs API error handling
- [ ] `build_fallback_topic_plans` covering single_k and multi_k shortage

**State update**
- [ ] `update_state_from_result` using actual parsed difficulty
- [ ] `update_round_level_state_after_round`
- [ ] `record_used_chunk_combination` with LRU eviction

**Stop conditions**
- [ ] `should_stop` (required `evidence_manager`)
- [ ] `candidate_pool_sufficient`
- [ ] `compute_expected_difficulty_targets`

**Main loop**
- [ ] `async run_generation_agent`

**Serialization**
- [ ] `serialize_used_chunk_combinations`
- [ ] State serialization with `defaultdict` → `dict` and `deque` → `list` conversion

---

## 18. Acceptance Criteria

The implementation is acceptable when:

1. All functions referenced in pseudocode are implemented and callable.
2. Initial breadth covers every `(topic, mode)` pair, or logs a clear reason why it could not.
3. When initial breadth has no available topics, execution falls back to adaptive or stops cleanly — it does not loop with empty plans.
4. `RoundPlan` is never mutated during execution; all fallback creates new `TopicExecutionPlan` objects.
5. API timeout does not trigger evidence fallback loops.
6. State records actual parsed difficulty, not only planned difficulty.
7. Stop conditions correctly handle: candidate sufficiency, max rounds, no available topics, global consecutive failures, and global failure limit.
8. `generation_yield` is used to compute dynamic `single_k` and `multi_k`.
9. `used_chunk_combinations` can be exported as valid JSON and does not grow beyond `max_used_chunk_combinations`.
10. Large topic lists are batched during initial breadth.
11. `execute_round_plan` and `execute_topic_plan` are `async def` and compatible with the existing async model client.
