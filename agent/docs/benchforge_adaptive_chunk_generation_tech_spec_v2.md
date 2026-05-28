# BenchForge Adaptive Chunk-Sampling Candidate Generation Agent 技术方案 v2

## 0. 本版修订说明

本版本修复 v1 方案中的关键问题：

1. **禁止 fallback 直接修改共享 `RoundPlan` 对象**。所有降级策略必须通过 `dataclasses.replace(...)` 或显式复制创建新的 topic-level execution plan。
2. **补齐 `GenerationState.consecutive_hard_focus_rounds` 字段**，并明确它的更新逻辑。
3. **状态统计必须记录题目实际难度，而不是计划难度**。`mode_difficulty_counts` 应基于解析后的 question 字段。
4. **补齐关键函数定义**：`no_available_topics`、`fallback_chunk_policy`、`build_reason`、`expected_candidates_per_mode/topic`。
5. **让 `generation_yield` 真正参与 Planner 计算**，用于从候选题缺口反推 `single_k` / `multi_k`。
6. **移除重复配置**：统一使用 `candidate_pool.target_multiplier`，删除 `stop_policy.candidate_target_multiplier`。
7. **明确 `used_chunk_combinations` 的 JSON 序列化方式和内存边界**。
8. **明确 `topic_attempts` 的用途**，用于安全阀、日志和降权。
9. **为 initial breadth 增加分批机制**，避免 topic 数量较多时单轮过长。

---

## 1. 设计目标

本方案的目标是将 BenchForge 的题目生成阶段改造为：

> 基于蓝图、题型轮转、动态 chunk 采样、多轮状态反馈的候选题生成 Agent。

生成 Agent 不负责最终 benchmark 的严格质量验证和最终采样。它只负责根据用户蓝图生成一个覆盖尽量充分的候选题池，后续题目验证智能体再负责：

- 答案正确性验证
- 题目质量判断
- 去重
- 难度校准
- 最终采样

生成阶段不追求“精确生成 N 道题”，而是：

- 题目数量用于状态判断和停止条件
- 每轮计划只控制 chunk 采样规模
- 生成器接收 chunk list，然后生成候选题

---

## 2. 核心原则

### 2.1 题目数量不直接控制每轮生成

蓝图里的 `count` 只用于：

- 计算每个 mode 的候选池目标
- 判断当前 mode 是否不足
- 判断当前 difficulty 是否不足
- 估计候选池是否足够进入验证阶段

它不用于直接告诉 LLM 每轮生成几道题。

### 2.2 Planner 控制 chunk，而不是控制题目

Planner 每轮生成 `RoundPlan`，包含：

- 本轮 mode
- 本轮 difficulty
- 本轮 topics
- 每个 topic 采多少 single chunks
- 每个 topic 采多少 multi chunks
- 使用何种策略

### 2.3 single/multi 比例主要由 difficulty 决定

因为：

- easy 更偏直接事实定位，适合 single chunk
- medium 需要一定综合，single/multi 平衡
- hard 更偏比较、综合、多跳推理，适合 multi chunk

题目类型只做轻量修正：

- QA 略偏 single，保留答案锚点
- MCQ 略偏 multi，便于构造干扰项

### 2.4 状态必须记录实际生成结果

生成计划的 difficulty 只是目标难度。实际输出题目的 difficulty 必须从 parsed question 字段读取。如果缺失或非法，再 fallback 到计划难度并记录 warning。

---

## 3. 配置 Schema

推荐配置如下：

```yaml
run_id: benchmark_generation_v2
language: en

max_rounds: 40

mode_order:
  - qa
  - multiple_choice

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

planner:
  topics_per_round: 3
  initial_topics_per_round: 10
  initial_difficulty: medium

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

  limits:
    min_single_ratio: 0.0
    max_single_ratio: 1.0

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
      min: 0
      max: 4
    multi_k:
      min: 0
      max: 3
  multiple_choice:
    single_k:
      min: 0
      max: 3
    multi_k:
      min: 0
      max: 4

difficulty_policy:
  hard_focus_threshold: 0.15
  max_consecutive_hard_focus_rounds: 2

topic_safety:
  max_attempts_per_topic: null
  max_consecutive_failures_per_topic: 3
  cooldown_rounds_after_failure: 2

retrieval_safety:
  max_expansions_per_topic: 3
  chunk_exhaustion_ratio: 0.8

sampling_safety:
  max_sampling_retries: 5
  max_used_chunk_combinations: 5000

runtime:
  llm_timeout_seconds: 60
  max_global_consecutive_failures: 5
```

### 3.1 删除的配置

不要再使用：

```yaml
stop_policy:
  candidate_target_multiplier: 2.5
```

统一使用：

```yaml
candidate_pool:
  target_multiplier: 2.5
```

避免两处配置含义重复。

---

## 4. 数据结构

### 4.1 RoundPlan

`RoundPlan` 是每一轮的整体计划。一轮只包含一个 mode、一个 difficulty 和若干 topics。

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass(frozen=True)
class RoundPlan:
    round_num: int
    action: str
    strategy: str
    mode: str
    difficulty: str
    topics: list[str]
    single_k: int
    multi_k: int
    retrieval_strategy: str = "use_existing_pool"
    reason: str = ""
    expected_candidates_per_topic: float | None = None
```

建议 `RoundPlan` 使用 `frozen=True`，避免执行阶段意外修改共享对象。

### 4.2 TopicExecutionPlan

为了避免共享 `RoundPlan` 被污染，执行每个 topic 时应创建 topic-level plan。

```python
@dataclass(frozen=True)
class TopicExecutionPlan:
    round_num: int
    action: str
    strategy: str
    topic: str
    mode: str
    difficulty: str
    single_k: int
    multi_k: int
    retrieval_strategy: str
    reason: str
```

构造方式：

```python
def make_topic_execution_plan(round_plan: RoundPlan, topic: str) -> TopicExecutionPlan:
    return TopicExecutionPlan(
        round_num=round_plan.round_num,
        action=round_plan.action,
        strategy=round_plan.strategy,
        topic=topic,
        mode=round_plan.mode,
        difficulty=round_plan.difficulty,
        single_k=round_plan.single_k,
        multi_k=round_plan.multi_k,
        retrieval_strategy=round_plan.retrieval_strategy,
        reason=round_plan.reason,
    )
```

### 4.3 GenerationState

```python
from dataclasses import dataclass, field
from collections import defaultdict, deque
from typing import Any

@dataclass
class GenerationState:
    round_num: int = 1

    candidate_questions: list[dict[str, Any]] = field(default_factory=list)

    mode_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    mode_difficulty_counts: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )

    topic_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    topic_mode_counts: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    topic_difficulty_counts: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )

    topic_attempts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    topic_successes: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    topic_consecutive_failures: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    topic_cooldown_until_round: dict[str, int] = field(default_factory=dict)

    topic_expansion_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Tracks how many hard-focus rounds have been used consecutively.
    consecutive_hard_focus_rounds: int = 0

    # Chunk usage state.
    used_chunk_combinations: set[frozenset[str]] = field(default_factory=set)
    used_chunk_combination_order: deque[frozenset[str]] = field(default_factory=deque)

    # Optional diagnostics.
    failure_history: list[dict[str, Any]] = field(default_factory=list)
    round_traces: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
```

### 4.4 topic_attempts 的用途

`topic_attempts` 不用于强制均衡，而用于：

- 日志统计
- 计算 topic 成功率
- 防止某 topic 被无限尝试
- 作为 scoring 中的轻微降权项

如果配置 `topic_safety.max_attempts_per_topic` 不为 null，则：

```python
if state.topic_attempts[topic] >= config.topic_safety.max_attempts_per_topic:
    topic 不再进入候选 topics
```

---

## 5. Planner 逻辑

### 5.1 主入口

```python
def build_round_plan(state: GenerationState, blueprint, config) -> RoundPlan | None:
    if should_stop(state, blueprint, config):
        return None

    mode = choose_mode(state.round_num, blueprint.mode_order)

    if is_initial_breadth_phase(state, blueprint, config):
        return build_initial_breadth_round_plan(state, blueprint, config, mode)

    difficulty = choose_difficulty(state, blueprint, mode)
    strategy = choose_chunk_strategy(state, blueprint, config, mode, difficulty)
    topics = choose_topics(state, blueprint, config, mode, difficulty)

    if not topics:
        return None

    target_candidates_per_topic = compute_target_candidates_per_topic(
        state=state,
        blueprint=blueprint,
        config=config,
        mode=mode,
        topics=topics,
    )

    single_k, multi_k = compute_dynamic_chunk_k(
        mode=mode,
        difficulty=difficulty,
        strategy=strategy,
        target_candidates_per_topic=target_candidates_per_topic,
        config=config,
    )

    action = decide_round_action(state, config, topics, single_k, multi_k)

    return RoundPlan(
        round_num=state.round_num,
        action=action,
        strategy=strategy,
        mode=mode,
        difficulty=difficulty,
        topics=topics,
        single_k=single_k,
        multi_k=multi_k,
        retrieval_strategy="use_existing_pool",
        expected_candidates_per_topic=target_candidates_per_topic,
        reason=build_reason(
            state=state,
            blueprint=blueprint,
            mode=mode,
            difficulty=difficulty,
            topics=topics,
            strategy=strategy,
            single_k=single_k,
            multi_k=multi_k,
        ),
    )
```

---

## 6. 初始广度阶段

### 6.1 目标

初始阶段确保每个 topic 至少被每种 mode 探索一次。

如果有两个 mode：

- Round 1: QA + medium + topics batch
- Round 2: MCQ + medium + topics batch

如果 topic 数量较多，则使用分批机制。

### 6.2 分批机制

```python
def get_initial_topic_batch(state, blueprint, config, mode: str) -> list[str]:
    batch_size = config.planner.initial_topics_per_round

    # Track initial coverage per mode/topic in state if needed.
    uncovered = [
        topic for topic in blueprint.topics
        if not state_has_initial_coverage(state, topic, mode)
        and not is_topic_in_cooldown(state, topic)
    ]

    return uncovered[:batch_size]
```

### 6.3 initial breadth 结束条件

当所有 mode/topic 都完成初始覆盖，或者所有可用 topic 已进入 cooldown / exhausted，则退出 initial breadth。

```python
def initial_breadth_complete(state, blueprint) -> bool:
    for mode in blueprint.mode_order:
        for topic in blueprint.topics:
            if not state_has_initial_coverage(state, topic, mode):
                return False
    return True
```

### 6.4 构建初始计划

```python
def build_initial_breadth_round_plan(state, blueprint, config, mode: str) -> RoundPlan | None:
    topics = get_initial_topic_batch(state, blueprint, config, mode)
    if not topics:
        return None

    difficulty = config.planner.initial_difficulty
    strategy = "initial_breadth"

    # Initial breadth uses dynamic k too, but with a conservative target.
    target_candidates_per_topic = compute_initial_target_candidates_per_topic(
        mode=mode,
        blueprint=blueprint,
        config=config,
    )

    single_k, multi_k = compute_dynamic_chunk_k(
        mode=mode,
        difficulty=difficulty,
        strategy=strategy,
        target_candidates_per_topic=target_candidates_per_topic,
        config=config,
    )

    return RoundPlan(
        round_num=state.round_num,
        action="initial_breadth_generate",
        strategy=strategy,
        mode=mode,
        difficulty=difficulty,
        topics=topics,
        single_k=single_k,
        multi_k=multi_k,
        retrieval_strategy="use_existing_pool",
        expected_candidates_per_topic=target_candidates_per_topic,
        reason=f"Initial breadth generation for mode={mode}, difficulty={difficulty}.",
    )
```

---

## 7. 动态 single_k / multi_k 计算

这是本方案的关键修订点。

`single_k` 和 `multi_k` 不应固定，而应根据：

- 蓝图目标数量
- 当前候选数量
- 剩余轮次
- 当前选中的 topics 数
- difficulty 对 single/multi 的比例偏好
- generation_yield 平均产题系数
- chunk_limits 上下限

动态计算。

### 7.1 计算 mode candidate target

```python
def mode_candidate_target(blueprint, config, mode: str) -> float:
    return blueprint.modes[mode].count * config.candidate_pool.target_multiplier
```

### 7.2 估算某 mode 剩余轮次数

```python
def estimate_remaining_mode_rounds(state, blueprint, mode: str) -> int:
    remaining_rounds = max(0, blueprint.max_rounds - state.round_num + 1)
    mode_order = blueprint.mode_order
    current_round = state.round_num

    count = 0
    for offset in range(remaining_rounds):
        simulated_round = current_round + offset
        simulated_mode = mode_order[(simulated_round - 1) % len(mode_order)]
        if simulated_mode == mode:
            count += 1

    return max(1, count)
```

### 7.3 计算每个 topic 本轮预期候选题数

```python
def compute_target_candidates_per_topic(state, blueprint, config, mode: str, topics: list[str]) -> float:
    target = mode_candidate_target(blueprint, config, mode)
    current = state.mode_counts.get(mode, 0)
    gap = max(0.0, target - current)

    remaining_mode_rounds = estimate_remaining_mode_rounds(state, blueprint, mode)
    target_this_mode_round = gap / remaining_mode_rounds

    if not topics:
        return 0.0

    return max(1.0, target_this_mode_round / len(topics))
```

### 7.4 根据 difficulty + mode 解析 single/multi 比例

```python
def resolve_chunk_mix(mode: str, difficulty: str, config) -> tuple[float, float]:
    base = config.chunk_mix.by_difficulty[difficulty]
    single_ratio = base.single_ratio

    adjustment = config.chunk_mix.mode_adjustment.get(mode)
    if adjustment:
        single_ratio += adjustment.single_delta

    single_ratio = max(
        config.chunk_mix.limits.min_single_ratio,
        min(config.chunk_mix.limits.max_single_ratio, single_ratio),
    )
    multi_ratio = 1.0 - single_ratio
    return single_ratio, multi_ratio
```

### 7.5 由预期候选数反推 chunk k

```python
import math


def clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, value))


def compute_dynamic_chunk_k(
    mode: str,
    difficulty: str,
    strategy: str,
    target_candidates_per_topic: float,
    config,
) -> tuple[int, int]:
    single_ratio, multi_ratio = resolve_chunk_mix(mode, difficulty, config)

    single_target = target_candidates_per_topic * single_ratio
    multi_target = target_candidates_per_topic * multi_ratio

    yields = config.generation_yield[mode]

    single_avg = max(0.1, yields.single_chunk_avg_questions)
    multi_avg = max(0.1, yields.multi_chunk_avg_questions)

    single_k = math.ceil(single_target / single_avg)
    multi_k = math.ceil(multi_target / multi_avg)

    limits = config.chunk_limits[mode]
    single_k = clamp(single_k, limits.single_k.min, limits.single_k.max)
    multi_k = clamp(multi_k, limits.multi_k.min, limits.multi_k.max)

    # Ensure at least one evidence unit is sampled.
    if single_k == 0 and multi_k == 0:
        if multi_ratio >= single_ratio:
            multi_k = max(1, limits.multi_k.min)
        else:
            single_k = max(1, limits.single_k.min)

    return single_k, multi_k
```

---

## 8. Difficulty 与 hard-focus 策略

### 8.1 选择 difficulty

```python
def current_difficulty_ratio(state, mode: str) -> dict[str, float]:
    counts = state.mode_difficulty_counts.get(mode, {})
    total = sum(counts.values())
    if total <= 0:
        return {"easy": 0.0, "medium": 0.0, "hard": 0.0}
    return {difficulty: count / total for difficulty, count in counts.items()}


def choose_difficulty(state, blueprint, mode: str) -> str:
    target_dist = blueprint.modes[mode].difficulty_distribution
    current_dist = current_difficulty_ratio(state, mode)

    return max(
        target_dist.keys(),
        key=lambda d: target_dist[d] - current_dist.get(d, 0.0),
    )
```

### 8.2 hard-focus 判断

```python
def hard_gap_score(state, blueprint, mode: str) -> float:
    target = blueprint.modes[mode].difficulty_distribution.get("hard", 0.0)
    current = current_difficulty_ratio(state, mode).get("hard", 0.0)
    return target - current


def choose_chunk_strategy(state, blueprint, config, mode: str, difficulty: str) -> str:
    if difficulty != "hard":
        return "default"

    gap = hard_gap_score(state, blueprint, mode)
    if (
        gap >= config.difficulty_policy.hard_focus_threshold
        and state.consecutive_hard_focus_rounds < config.difficulty_policy.max_consecutive_hard_focus_rounds
    ):
        return "hard_focus"

    return "default"
```

### 8.3 更新 hard-focus 连续轮数

```python
def update_round_strategy_state(state: GenerationState, round_plan: RoundPlan) -> None:
    if round_plan.strategy == "hard_focus":
        state.consecutive_hard_focus_rounds += 1
    else:
        state.consecutive_hard_focus_rounds = 0
```

注意：当前 v2 的 `compute_dynamic_chunk_k` 通过 difficulty 决定比例。`strategy='hard_focus'` 主要用于日志与连续轮数控制。如果需要更激进的 hard-focus，可在 `resolve_chunk_mix` 中根据 strategy 选择不同 mix 表。

---

## 9. Topic 选择与安全机制

### 9.1 topic 是否可用

```python
def is_topic_in_cooldown(state: GenerationState, topic: str) -> bool:
    return state.round_num < state.topic_cooldown_until_round.get(topic, -1)


def topic_attempt_limit_reached(state, config, topic: str) -> bool:
    limit = config.topic_safety.max_attempts_per_topic
    if limit is None:
        return False
    return state.topic_attempts.get(topic, 0) >= limit


def is_topic_exhausted(state, evidence_manager, config, topic: str) -> bool:
    stats = evidence_manager.get_topic_chunk_stats(topic)
    total = max(1, stats.total_single + stats.total_multi)
    used = stats.used_single + stats.used_multi
    used_ratio = used / total
    return used_ratio >= config.retrieval_safety.chunk_exhaustion_ratio
```

### 9.2 no_available_topics

```python
def no_available_topics(state, blueprint, config, evidence_manager) -> bool:
    for topic in blueprint.topics:
        if is_topic_in_cooldown(state, topic):
            continue
        if topic_attempt_limit_reached(state, config, topic):
            continue
        if is_topic_exhausted(state, evidence_manager, config, topic):
            continue
        return False
    return True
```

### 9.3 Topic scoring

```python
def expected_candidates_per_topic(state, blueprint, config) -> float:
    total_target = sum(m.count for m in blueprint.modes.values()) * config.candidate_pool.target_multiplier
    return total_target / max(1, len(blueprint.topics))


def expected_candidates_per_topic_mode(state, blueprint, config, mode: str) -> float:
    target = mode_candidate_target(blueprint, config, mode)
    return target / max(1, len(blueprint.topics))


def score_topic(topic: str, mode: str, state, blueprint, config) -> float:
    if is_topic_in_cooldown(state, topic):
        return float("-inf")
    if topic_attempt_limit_reached(state, config, topic):
        return float("-inf")

    topic_gap = expected_candidates_per_topic(state, blueprint, config) - state.topic_counts.get(topic, 0)
    topic_mode_gap = expected_candidates_per_topic_mode(state, blueprint, config, mode) - state.topic_mode_counts[topic].get(mode, 0)

    failure_penalty = state.topic_consecutive_failures.get(topic, 0) * 2.0
    expansion_penalty = state.topic_expansion_counts.get(topic, 0) * 0.5
    attempt_penalty = state.topic_attempts.get(topic, 0) * 0.1

    return topic_gap + topic_mode_gap - failure_penalty - expansion_penalty - attempt_penalty
```

### 9.4 选择 topics

```python
def choose_topics(state, blueprint, config, mode: str, difficulty: str) -> list[str]:
    scored = []
    for topic in blueprint.topics:
        score = score_topic(topic, mode, state, blueprint, config)
        if score != float("-inf"):
            scored.append((score, topic))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [topic for _, topic in scored[: config.planner.topics_per_round]]
```

---

## 10. Action 决策

### 10.1 round action

RoundPlan 的 action 可为：

- `initial_breadth_generate`
- `adaptive_generate`
- `expand_retrieval_then_generate`
- `supplement_chunks_then_generate`
- `recover_generation`

第一版可以让 `RoundPlan.action` 只表达默认倾向，具体每个 topic 是否需要 fallback 由 executor 判断。

```python
def decide_round_action(state, config, topics: list[str], single_k: int, multi_k: int) -> str:
    # If many selected topics are likely short on chunks, use expansion-oriented action.
    # Otherwise normal adaptive generation.
    return "adaptive_generate"
```

### 10.2 topic-level evidence shortage recovery

**严禁直接修改共享 `round_plan`。**

错误写法：

```python
round_plan.single_k = fallback_single_k
round_plan.multi_k = fallback_multi_k
```

正确写法：

```python
from dataclasses import replace

fallback_plan = replace(
    topic_plan,
    single_k=fallback_single_k,
    multi_k=fallback_multi_k,
    strategy="fallback_chunk_policy",
    reason=topic_plan.reason + " Fallback: evidence shortage.",
)
```

因为一个 `RoundPlan` 会应用到多个 topic。如果第一个 topic 失败时修改共享对象，后续 topic 会被隐式污染。

---

## 11. fallback_chunk_policy 定义

当 evidence 不足或采样失败时，按以下顺序降级。

```python
def fallback_chunk_policy(topic_plan: TopicExecutionPlan, config) -> list[tuple[int, int]]:
    """Return fallback (single_k, multi_k) candidates in order."""
    original = (topic_plan.single_k, topic_plan.multi_k)

    candidates = []

    # 1. Reduce multi_k first, because multi chunks are more expensive and more failure-prone.
    if topic_plan.multi_k > 0:
        candidates.append((topic_plan.single_k, max(0, topic_plan.multi_k - 1)))

    # 2. If still not enough, use single-only fallback when allowed.
    if topic_plan.single_k > 0:
        candidates.append((topic_plan.single_k, 0))

    # 3. Minimal one-unit fallback.
    candidates.append((1, 0))
    candidates.append((0, 1))

    # Remove duplicates and values outside limits.
    seen = set()
    cleaned = []
    limits = config.chunk_limits[topic_plan.mode]
    for single_k, multi_k in candidates:
        single_k = clamp(single_k, limits.single_k.min, limits.single_k.max)
        multi_k = clamp(multi_k, limits.multi_k.min, limits.multi_k.max)
        if single_k == 0 and multi_k == 0:
            continue
        key = (single_k, multi_k)
        if key not in seen and key != original:
            seen.add(key)
            cleaned.append(key)

    return cleaned
```

Executor 使用方式：

```python
def recover_evidence_shortage(topic_plan, config):
    for fallback_single_k, fallback_multi_k in fallback_chunk_policy(topic_plan, config):
        fallback_plan = replace(
            topic_plan,
            single_k=fallback_single_k,
            multi_k=fallback_multi_k,
            strategy="fallback_chunk_policy",
            reason=topic_plan.reason + " Fallback due to evidence shortage.",
        )
        yield fallback_plan
```

---

## 12. Executor 流程

### 12.1 执行 RoundPlan

```python
def execute_round_plan(round_plan: RoundPlan, state, evidence_manager, generator, config):
    results = []

    for topic in round_plan.topics:
        topic_plan = make_topic_execution_plan(round_plan, topic)
        result = execute_topic_plan(topic_plan, state, evidence_manager, generator, config)
        update_state_from_result(state, topic_plan, result, config)
        results.append(result)

    update_round_strategy_state(state, round_plan)
    return results
```

### 12.2 执行单个 topic

```python
def execute_topic_plan(topic_plan, state, evidence_manager, generator, config):
    candidate_plans = [topic_plan]
    candidate_plans.extend(list(recover_evidence_shortage(topic_plan, config)))

    last_error = None

    for plan in candidate_plans:
        try:
            if plan.single_k > 0:
                single_units = evidence_manager.sample_single(
                    topic=plan.topic,
                    target_mode=plan.mode,
                    target_difficulty=plan.difficulty,
                    k=plan.single_k,
                )
            else:
                single_units = []

            if plan.multi_k > 0:
                multi_units = evidence_manager.sample_multi(
                    topic=plan.topic,
                    target_mode=plan.mode,
                    target_difficulty=plan.difficulty,
                    k=plan.multi_k,
                )
            else:
                multi_units = []

            chunks = single_units + multi_units
            if not chunks:
                raise EvidenceShortageError("No chunks sampled")

            raw_output = generator.generate(
                topic=plan.topic,
                mode=plan.mode,
                difficulty=plan.difficulty,
                chunks=chunks,
            )

            parsed_questions = parse_questions(raw_output)

            return GenerationResult(
                success=True,
                topic=plan.topic,
                executed_plan=plan,
                chunks=chunks,
                parsed_questions=parsed_questions,
                raw_output=raw_output,
                error=None,
            )

        except Exception as exc:
            last_error = exc
            continue

    return GenerationResult(
        success=False,
        topic=topic_plan.topic,
        executed_plan=topic_plan,
        chunks=[],
        parsed_questions=[],
        raw_output=None,
        error=str(last_error),
    )
```

---

## 13. 状态更新：必须使用实际题目难度

### 13.1 难度归一化

```python
def normalize_difficulty(value: str | None, fallback: str) -> tuple[str, bool]:
    valid = {"easy", "medium", "hard"}
    if value is None:
        return fallback, True
    normalized = str(value).strip().lower()
    if normalized in valid:
        return normalized, False
    return fallback, True
```

### 13.2 mode 归一化

```python
def normalize_mode(value: str | None, fallback: str) -> tuple[str, bool]:
    valid = {"qa", "multiple_choice"}
    if value is None:
        return fallback, True
    normalized = str(value).strip().lower()
    if normalized in valid:
        return normalized, False
    return fallback, True
```

### 13.3 状态更新

```python
def update_state_from_result(state: GenerationState, topic_plan: TopicExecutionPlan, result, config) -> None:
    state.topic_attempts[topic_plan.topic] += 1

    if not result.success:
        state.topic_consecutive_failures[topic_plan.topic] += 1
        state.failure_history.append({
            "round": state.round_num,
            "topic": topic_plan.topic,
            "mode": topic_plan.mode,
            "difficulty": topic_plan.difficulty,
            "error": result.error,
        })

        if state.topic_consecutive_failures[topic_plan.topic] >= config.topic_safety.max_consecutive_failures_per_topic:
            state.topic_cooldown_until_round[topic_plan.topic] = (
                state.round_num + config.topic_safety.cooldown_rounds_after_failure
            )
        return

    state.topic_successes[topic_plan.topic] += 1
    state.topic_consecutive_failures[topic_plan.topic] = 0

    for q in result.parsed_questions:
        actual_mode, mode_fallback_used = normalize_mode(q.get("mode") or q.get("question_mode"), topic_plan.mode)
        actual_difficulty, difficulty_fallback_used = normalize_difficulty(
            q.get("difficulty") or q.get("estimated_difficulty"),
            topic_plan.difficulty,
        )

        if mode_fallback_used:
            state.warnings.append(
                f"Question missing/invalid mode; fallback to plan mode={topic_plan.mode}."
            )
        if difficulty_fallback_used:
            state.warnings.append(
                f"Question missing/invalid difficulty; fallback to plan difficulty={topic_plan.difficulty}."
            )

        q["normalized_mode"] = actual_mode
        q["normalized_difficulty"] = actual_difficulty
        q["topic"] = q.get("topic") or topic_plan.topic

        state.candidate_questions.append(q)
        state.mode_counts[actual_mode] += 1
        state.mode_difficulty_counts[actual_mode][actual_difficulty] += 1
        state.topic_counts[topic_plan.topic] += 1
        state.topic_mode_counts[topic_plan.topic][actual_mode] += 1
        state.topic_difficulty_counts[topic_plan.topic][actual_difficulty] += 1

    record_used_chunks(state, result.chunks, config)
```

---

## 14. used_chunk_combinations 序列化与内存控制

### 14.1 记录 chunk 组合

```python
def chunk_ids_from_units(units) -> list[str]:
    ids = []
    for unit in units:
        if hasattr(unit, "unit_id"):
            ids.append(unit.unit_id)
        elif hasattr(unit, "chunk_id"):
            ids.append(unit.chunk_id)
        else:
            ids.append(str(unit))
    return ids


def record_used_chunks(state: GenerationState, chunks, config) -> None:
    ids = chunk_ids_from_units(chunks)
    if not ids:
        return

    combo = frozenset(ids)
    if combo in state.used_chunk_combinations:
        return

    state.used_chunk_combinations.add(combo)
    state.used_chunk_combination_order.append(combo)

    max_size = config.sampling_safety.max_used_chunk_combinations
    while len(state.used_chunk_combinations) > max_size:
        old = state.used_chunk_combination_order.popleft()
        state.used_chunk_combinations.discard(old)
```

### 14.2 JSON 序列化

`set[frozenset[str]]` 不能直接 JSON 序列化。输出时必须转换为 list。

```python
def serialize_used_chunk_combinations(state: GenerationState) -> list[list[str]]:
    return [sorted(list(combo)) for combo in state.used_chunk_combinations]
```

输出 `used_chunks.json`：

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

## 15. 停止条件

### 15.1 candidate_pool_sufficient

`generation_yield` 用于动态 k 计算，停止条件使用实际生成候选数量。

```python
def candidate_pool_sufficient(state: GenerationState, blueprint, config) -> bool:
    total_target = sum(mode.count for mode in blueprint.modes.values())
    candidate_target = total_target * config.candidate_pool.target_multiplier

    if len(state.candidate_questions) < candidate_target:
        return False

    # Mode minimum coverage.
    for mode_name, mode_cfg in blueprint.modes.items():
        min_mode_target = mode_cfg.count * config.candidate_pool.min_mode_multiplier
        if state.mode_counts.get(mode_name, 0) < min_mode_target:
            return False

    # Difficulty minimum coverage across all modes.
    total_final_by_difficulty = {"easy": 0.0, "medium": 0.0, "hard": 0.0}
    current_by_difficulty = {"easy": 0, "medium": 0, "hard": 0}

    for mode_name, mode_cfg in blueprint.modes.items():
        for difficulty, ratio in mode_cfg.difficulty_distribution.items():
            total_final_by_difficulty[difficulty] += mode_cfg.count * ratio
        for difficulty, count in state.mode_difficulty_counts.get(mode_name, {}).items():
            current_by_difficulty[difficulty] = current_by_difficulty.get(difficulty, 0) + count

    for difficulty, final_target in total_final_by_difficulty.items():
        min_target = final_target * config.candidate_pool.min_difficulty_multiplier
        if current_by_difficulty.get(difficulty, 0) < min_target:
            return False

    return True
```

### 15.2 should_stop

```python
def should_stop(state: GenerationState, blueprint, config, evidence_manager=None) -> bool:
    if state.round_num > blueprint.max_rounds:
        return True

    if candidate_pool_sufficient(state, blueprint, config):
        return True

    if evidence_manager is not None and no_available_topics(state, blueprint, config, evidence_manager):
        return True

    recent_failures = state.failure_history[-config.runtime.max_global_consecutive_failures:]
    if len(recent_failures) >= config.runtime.max_global_consecutive_failures:
        recent_rounds = {f["round"] for f in recent_failures}
        if len(recent_rounds) >= config.runtime.max_global_consecutive_failures:
            return True

    return False
```

---

## 16. build_reason 定义

`build_reason(...)` 必须有明确输入，不能写成 `...`。

```python
def build_reason(state, blueprint, mode, difficulty, topics, strategy, single_k, multi_k) -> str:
    mode_count = state.mode_counts.get(mode, 0)
    difficulty_count = state.mode_difficulty_counts.get(mode, {}).get(difficulty, 0)
    weak_topics = ", ".join(topics[:5])

    return (
        f"Selected mode={mode}, difficulty={difficulty}, strategy={strategy}. "
        f"Current mode candidate count={mode_count}; "
        f"current {mode}/{difficulty} count={difficulty_count}. "
        f"Selected topics: {weak_topics}. "
        f"Chunk plan per topic: single_k={single_k}, multi_k={multi_k}."
    )
```

---

## 17. EvidenceManager 改造

当前 `EvidenceManager.sample(...)` 是 single/multi 混合采样。v2 需要增加两个接口：

```python
def sample_single(topic: str, target_mode: str, target_difficulty: str, k: int):
    ...


def sample_multi(topic: str, target_mode: str, target_difficulty: str, k: int):
    ...
```

内部可复用原有 scoring 逻辑：

- `qa_score`
- `mcq_score`
- `hard_score`
- `usage_count` penalty
- weighted sampling
- retry 去重
- force unique fallback

### 17.1 scoring

```python
def score_evidence_unit(unit, target_mode: str, target_difficulty: str) -> float:
    if target_mode == "multiple_choice":
        base = getattr(unit, "mcq_score", 0.5)
    else:
        base = getattr(unit, "qa_score", 0.5)

    if target_difficulty == "hard":
        hard_score = getattr(unit, "hard_score", 0.5)
        base = 0.5 * base + 1.5 * hard_score

    usage = getattr(unit, "usage_count", 0)
    usage_penalty = 1.0 / (1.0 + usage)
    return max(1e-6, base * usage_penalty)
```

---

## 18. 输出文件

生成阶段输出：

```text
runs/{run_id}/candidate_pool.json
runs/{run_id}/generation_trace.json
runs/{run_id}/generation_state.json
runs/{run_id}/generation_report.json
runs/{run_id}/used_chunks.json
```

### 18.1 generation_trace.json

每轮记录：

- observation summary
- round plan
- topic-level executed plan
- fallback 是否发生
- selected chunk ids
- generated count
- parse success
- failure reason

### 18.2 generation_state.json

注意转换不可序列化字段：

- `defaultdict` 转 dict
- `set[frozenset]` 转 list[list[str]]
- `deque` 转 list

---

## 19. 实现任务清单

### Phase 1: Schema 与配置

1. 新增配置 schema。
2. 删除重复的 `stop_policy.candidate_target_multiplier`。
3. 添加 `chunk_mix`、`generation_yield`、`chunk_limits`。
4. 添加 `difficulty_policy`、`topic_safety`、`retrieval_safety`。

### Phase 2: State 与 Planner

1. 实现 `GenerationState`，补齐 `consecutive_hard_focus_rounds`。
2. 实现 `RoundPlan` 和 `TopicExecutionPlan`。
3. 实现 `build_round_plan`。
4. 实现动态 `single_k` / `multi_k` 计算。
5. 实现 initial breadth 分批。
6. 实现 topic scoring。
7. 实现 `build_reason`。

### Phase 3: EvidenceManager

1. 新增 `sample_single`。
2. 新增 `sample_multi`。
3. 复用现有 scoring 和去重。
4. 增加 topic chunk stats API：`get_topic_chunk_stats(topic)`。

### Phase 4: Executor

1. 实现 topic-level execution plan。
2. fallback 时使用 `dataclasses.replace`，禁止修改共享 plan。
3. 实现 `fallback_chunk_policy`。
4. 实现超时、解析失败、evidence shortage 的失败记录。

### Phase 5: State Update 与输出

1. 状态统计使用实际题目 difficulty。
2. 序列化 `used_chunk_combinations`。
3. 输出 generation trace / state / report。

---

## 20. 验收标准

### 20.1 功能验收

- 能基于 blueprint 运行完整生成流程。
- Round 1/2 能执行 initial breadth。
- topic 多于 `initial_topics_per_round` 时会分批执行。
- Round 3+ 能根据状态选择 mode/difficulty/topics。
- `single_k` / `multi_k` 会随目标数量、剩余轮次和 generation_yield 动态变化。
- hard 缺口较大时会触发 hard-focus 控制，但不会超过最大连续轮数。
- fallback 不会污染后续 topic 的 plan。
- 状态统计使用实际题目难度。

### 20.2 稳定性验收

- 没有 `AttributeError: consecutive_hard_focus_rounds`。
- `used_chunks.json` 可以正常 JSON 序列化。
- 单个 topic 连续失败后进入 cooldown。
- candidate target 达成后停止。
- max_rounds 达成后停止。

### 20.3 日志验收

`generation_trace.json` 中每轮必须包含：

- round number
- selected mode
- selected difficulty
- selected topics
- single_k / multi_k
- reason
- executed topic plans
- fallback usage
- selected chunk ids
- generated count
- failure reasons

---

## 21. 总结

v2 方案保留原始设计理念：

> 生成 Agent 不精确补题，而是根据蓝图和当前状态动态采样 chunks，生成候选题池。

但修复了 v1 中会导致实现错误和状态污染的问题：

- RoundPlan 不可变
- fallback 使用副本
- 状态记录实际题目难度
- generation_yield 参与动态 k 计算
- target_multiplier 配置统一
- initial breadth 支持分批
- used_chunk_combinations 可序列化且有上限
- 缺失函数全部补齐

该版本可以交给 Claude Code 作为实现依据。
