# BenchForge Adaptive Chunk-Based Candidate Generation Agent 技术方案

## 0. 文档目的

本文档用于指导 Claude Code 对当前 BenchForge 题目生成模块进行重构。

本次重构目标不是让生成器精确生成最终 benchmark 题目，而是将生成阶段改造成一个 **Blueprint-guided、mode-rotating、adaptive chunk-sampling candidate generation agent**。

生成 Agent 的职责是：

1. 读取用户给定的 benchmark blueprint。
2. 观察当前候选题池状态。
3. 按题型轮转生成每轮计划。
4. 根据当前状态决定本轮 mode、difficulty、topics、chunk sampling policy。
5. 基于 single chunks 和 multi chunks 采样 evidence。
6. 将 chunk list 输入 QuestionGenerator 生成候选题。
7. 输出 candidate pool 和 generation trace，供后续题目验证智能体处理。

生成 Agent **不负责**：

- 精确补齐题目数量。
- 判断最终题目质量。
- 最终 benchmark 采样。
- 复杂题目去重与难度校准。

这些由后续验证智能体完成。

---

## 1. 背景与现有问题

当前生成逻辑更接近 gap-driven exact generation：

```text
目标题数 → 计算 remaining gap → 根据 remaining 决定本轮 evidence 数量 → 生成题目 → validator 接受后加入 all_questions
```

这种机制有几个问题：

1. LLM 每轮输出数量不稳定。
2. 当前 prompt / evidence 采样存在冗余生成，容易超过目标题数。
3. validator 接收全部有效题后，没有按 remaining 截断。
4. `remaining` 被用于决定 evidence 数量，导致题目数量和 chunk 检索耦合过紧。
5. 达到某些局部轮次或状态后，如果外层循环不检查，可能反复生成。
6. 生成 Agent 和后续验证 Agent 职责边界不清。

本方案将其改为：

```text
Blueprint → Observation → RoundPlan → Chunk Sampling → Candidate Generation → State Update
```

题目数量只作为 blueprint 目标和状态观察依据，不作为每轮精确补题依据。

---

## 2. 核心设计原则

### 2.1 题目数量不控制每轮生成

Blueprint 中的题目数量，例如：

```yaml
modes:
  qa:
    count: 30
  multiple_choice:
    count: 20
```

只用于：

- 判断当前 QA / MCQ 候选池比例。
- 判断当前 difficulty 分布偏差。
- 判断 candidate pool 是否足够进入验证阶段。
- 生成报告。

不用于：

- 本轮必须生成几题。
- 还差几题就补几题。
- 根据 remaining 计算 evidence 数量。

### 2.2 每轮只计划 chunk 采样，不计划题目数

每轮计划只关心：

```text
mode

difficulty

topics

single_k

multi_k

strategy

action
```

不应在 RoundPlan 中加入：

```text
questions_per_round
single_chunk_questions
multi_chunk_questions
```

### 2.3 题型轮转

QA 和 multiple_choice 依次进行，减少 prompt 混乱，也避免某个题型长期压制另一个题型。

默认：

```text
Round 1: qa
Round 2: multiple_choice
Round 3: qa
Round 4: multiple_choice
...
```

### 2.4 初始广度覆盖 + 后续自适应补充

前两个 mode 轮次用于 initial breadth：

```text
Round 1: qa + medium + all topics
Round 2: multiple_choice + medium + all topics
```

后续轮次进入 adaptive supplement：

```text
Round 3+: mode rotation + underrepresented difficulty + top-N weak topics
```

### 2.5 不强制主题均衡

不使用 `max_rounds_per_topic` 作为强制均衡机制。

主题不要求每个都生成相同数量。第一阶段保证最低探索，之后由状态决定哪些 topic 需要继续生成。

为了防止某个 topic 因低覆盖或失败被反复选择，使用 topic-level safety controls：

- failure penalty
- cooldown
- chunk exhaustion detection
- retrieval expansion limit
- fallback policy

---

## 3. 推荐 Blueprint Schema

建议新增或改造配置文件，例如：

```text
benchforge/config/adaptive_generation_blueprint.yaml
```

示例：

```yaml
run_id: benchmark_generation_v1
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

retrieval:
  source: wikipedia
  max_pages: 5
  chunk_size: 2048
  overlap: 300
  summarization_chunk_size: 8192
  summarization_overlap: 512

chunk_policy:
  default:
    qa:
      single_k: 2
      multi_k: 1
    multiple_choice:
      single_k: 1
      multi_k: 2

  hard_focus:
    qa:
      single_k: 1
      multi_k: 2
    multiple_choice:
      single_k: 0
      multi_k: 3

generation_yield:
  qa:
    single_chunk_avg_questions: 2.0
    multi_chunk_avg_questions: 3.0
  multiple_choice:
    single_chunk_avg_questions: 1.5
    multi_chunk_avg_questions: 2.0

planner:
  topics_per_round: 3
  initial_difficulty: medium

coverage_policy:
  require_initial_topic_coverage: true
  enforce_topic_balance_after_initial: false

mode_policy:
  strict_rotation: true
  mode_gap_override_threshold: 0.20

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

stop_policy:
  candidate_target_multiplier: 2.5
  min_mode_candidate_multiplier: 1.5
  min_difficulty_candidate_multiplier: 1.2
  max_global_consecutive_failures: 5
```

---

## 4. 关键配置解释

### 4.1 `chunk_policy`

`chunk_policy` 决定每个 topic 在一次 RoundPlan 执行中，从 evidence pool 中采多少 single units 和 multi units。

它不是题目数量策略。

默认策略：

```yaml
chunk_policy:
  default:
    qa:
      single_k: 2
      multi_k: 1
    multiple_choice:
      single_k: 1
      multi_k: 2
```

解释：

- QA 更依赖明确答案锚点，所以 single chunks 多一点。
- MCQ 更需要构造干扰项，所以 multi chunks 多一点。

Hard-focused 策略：

```yaml
chunk_policy:
  hard_focus:
    qa:
      single_k: 1
      multi_k: 2
    multiple_choice:
      single_k: 0
      multi_k: 3
```

解释：

- Hard 题通常需要比较、综合、多步推理，因此提高 multi-chunk 比例。
- Hard QA 仍保留 1 个 single chunk 作为答案锚点。
- Hard MCQ 可以 multi-only，因为它更依赖相近概念和对比信息生成干扰项。

### 4.2 `generation_yield`

用于估算候选题产出，不用于强制控制生成题数。

示例：

```yaml
generation_yield:
  qa:
    single_chunk_avg_questions: 2.0
    multi_chunk_avg_questions: 3.0
  multiple_choice:
    single_chunk_avg_questions: 1.5
    multi_chunk_avg_questions: 2.0
```

如果本轮是 QA，`single_k=2`，`multi_k=1`：

```text
expected_questions = 2 * 2.0 + 1 * 3.0 = 7
```

这只用于：

- 估计候选池增长速度。
- 日志报告。
- 判断 candidate pool 是否接近目标。

不要把该数作为 prompt 中的硬性生成数量。

---

## 5. 数据结构设计

### 5.1 RoundPlan

建议每轮只生成一个 `RoundPlan`，里面包含多个 topics。这样比生成复杂的 plan list 更容易实现。

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class RoundPlan:
    round_num: int
    action: str
    strategy: str
    mode: str
    difficulty: str
    topics: List[str]
    single_k: int
    multi_k: int
    retrieval_strategy: str
    reason: str
    retrieval_queries: Optional[dict[str, list[str]]] = None
```

示例：

```json
{
  "round_num": 4,
  "action": "adaptive_generate",
  "strategy": "hard_focus",
  "mode": "multiple_choice",
  "difficulty": "hard",
  "topics": ["Climate Change", "History", "Medicine"],
  "single_k": 0,
  "multi_k": 3,
  "retrieval_strategy": "use_existing_pool",
  "reason": "Multiple-choice hard candidates are underrepresented; selected topics have low MCQ coverage."
}
```

执行时对 `topics` 展开：

```python
for topic in round_plan.topics:
    execute_topic_plan(round_plan, topic)
```

### 5.2 GenerationState

```python
@dataclass
class GenerationState:
    round_num: int
    candidate_questions: list

    mode_counts: dict[str, int]
    mode_difficulty_counts: dict[str, dict[str, int]]

    topic_counts: dict[str, int]
    topic_mode_counts: dict[str, dict[str, int]]
    topic_difficulty_counts: dict[str, dict[str, int]]

    topic_attempts: dict[str, int]
    topic_consecutive_failures: dict[str, int]
    topic_cooldown_until_round: dict[str, int]

    topic_expansion_counts: dict[str, int]

    used_chunk_combinations: set[frozenset[str]]
    global_consecutive_failures: int

    round_traces: list
```

### 5.3 Observation

Observation 可由 `GenerationState` 动态计算，不一定要持久化。

建议包含：

```python
@dataclass
class Observation:
    round_num: int
    total_candidates: int

    mode_counts: dict[str, int]
    mode_ratios: dict[str, float]
    mode_difficulty_ratios: dict[str, dict[str, float]]

    topic_counts: dict[str, int]
    topic_mode_counts: dict[str, dict[str, int]]

    weak_topics: list[str]
    underrepresented_mode: str | None
    underrepresented_difficulty_by_mode: dict[str, str]

    available_chunks: dict[str, dict[str, int]]
    exhausted_topics: list[str]
    cooldown_topics: list[str]
```

---

## 6. Planner 设计

### 6.1 总体流程

```python
def build_round_plan(state, blueprint, config):
    observation = observe(state, blueprint)

    if should_stop(state, observation, blueprint, config):
        return RoundPlan(
            round_num=state.round_num,
            action="stop_generation",
            strategy="stop",
            mode="",
            difficulty="",
            topics=[],
            single_k=0,
            multi_k=0,
            retrieval_strategy="none",
            reason="Stop condition reached.",
        )

    mode = choose_mode(state.round_num, blueprint.mode_order, state, blueprint, config)

    if is_initial_breadth_round(state.round_num, blueprint.mode_order):
        return build_initial_breadth_plan(state, blueprint, config, mode)

    difficulty = choose_difficulty(state, blueprint, mode)
    strategy = choose_chunk_strategy(state, blueprint, mode, difficulty, config)
    single_k, multi_k = resolve_chunk_k(config, mode, strategy)
    topics = choose_topics(state, blueprint, mode, difficulty, config)
    action, retrieval_strategy, retrieval_queries = decide_action_and_retrieval(
        state, blueprint, topics, mode, difficulty, single_k, multi_k, config
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
        retrieval_strategy=retrieval_strategy,
        retrieval_queries=retrieval_queries,
        reason=build_reason(...),
    )
```

### 6.2 选择 mode

默认严格轮转：

```python
def choose_mode(round_num, mode_order, state, blueprint, config):
    if config.mode_policy.strict_rotation:
        return mode_order[(round_num - 1) % len(mode_order)]

    # Optional override if one mode is severely underrepresented.
    rotation_mode = mode_order[(round_num - 1) % len(mode_order)]
    most_underrepresented = compute_most_underrepresented_mode(state, blueprint)
    if mode_gap(most_underrepresented, state, blueprint) > config.mode_policy.mode_gap_override_threshold:
        return most_underrepresented
    return rotation_mode
```

第一版建议使用 strict rotation。

### 6.3 判断 initial breadth

```python
def is_initial_breadth_round(round_num, mode_order):
    return round_num <= len(mode_order)
```

如果 mode_order 是 `[qa, multiple_choice]`：

```text
Round 1: qa + all topics
Round 2: multiple_choice + all topics
```

### 6.4 构建 initial breadth plan

```python
def build_initial_breadth_plan(state, blueprint, config, mode):
    single_k, multi_k = resolve_chunk_k(config, mode, strategy="default")

    return RoundPlan(
        round_num=state.round_num,
        action="initial_breadth_generate",
        strategy="initial_breadth",
        mode=mode,
        difficulty=config.planner.initial_difficulty,
        topics=blueprint.topics,
        single_k=single_k,
        multi_k=multi_k,
        retrieval_strategy="use_existing_pool",
        reason=f"Initial breadth generation for {mode} across all topics.",
    )
```

如果 topics 很多，未来可加入 `max_initial_topics_per_round`，但第一版可以先全覆盖。

### 6.5 选择 difficulty

在当前 mode 下，根据目标难度分布和当前候选池分布选择最不足的难度。

```python
def choose_difficulty(state, blueprint, mode):
    target_dist = blueprint.modes[mode].difficulty_distribution
    current_dist = state.current_difficulty_ratio(mode)

    return max(
        target_dist.keys(),
        key=lambda d: target_dist[d] - current_dist.get(d, 0.0),
    )
```

### 6.6 选择 chunk strategy

```python
def choose_chunk_strategy(state, blueprint, mode, difficulty, config):
    if difficulty != "hard":
        return "default"

    target_hard_ratio = blueprint.modes[mode].difficulty_distribution.get("hard", 0.0)
    current_hard_ratio = state.current_difficulty_ratio(mode).get("hard", 0.0)
    hard_gap = target_hard_ratio - current_hard_ratio

    if hard_gap >= config.difficulty_policy.hard_focus_threshold:
        if state.consecutive_hard_focus_rounds < config.difficulty_policy.max_consecutive_hard_focus_rounds:
            return "hard_focus"

    return "default"
```

### 6.7 解析 single_k / multi_k

```python
def resolve_chunk_k(config, mode, strategy):
    policy = config.chunk_policy[strategy][mode]
    return policy.single_k, policy.multi_k
```

### 6.8 选择 topics

不强制主题均衡。主题选择基于：

- topic overall undercoverage
- topic-mode undercoverage
- failure penalty
- cooldown
- chunk exhaustion

```python
def score_topic(topic, mode, state, blueprint, config):
    if state.is_topic_in_cooldown(topic):
        return float("-inf")

    if state.is_topic_exhausted(topic):
        return float("-inf")

    expected_topic_candidates = state.expected_candidates_per_topic(blueprint)
    expected_topic_mode_candidates = state.expected_candidates_per_topic_mode(blueprint, mode)

    topic_gap = expected_topic_candidates - state.topic_counts.get(topic, 0)
    topic_mode_gap = expected_topic_mode_candidates - state.topic_mode_counts.get(topic, {}).get(mode, 0)

    failure_penalty = state.topic_consecutive_failures.get(topic, 0) * 2.0
    expansion_penalty = state.topic_expansion_counts.get(topic, 0) * 0.5

    return topic_gap + topic_mode_gap - failure_penalty - expansion_penalty
```

选择 top-N：

```python
def choose_topics(state, blueprint, mode, difficulty, config):
    scored = []
    for topic in blueprint.topics:
        score = score_topic(topic, mode, state, blueprint, config)
        if score != float("-inf"):
            scored.append((score, topic))

    scored.sort(reverse=True)
    return [topic for score, topic in scored[:config.planner.topics_per_round]]
```

### 6.9 决定 action 和 retrieval strategy

对每个 selected topic 检查 chunk 可用性。如果同一个 RoundPlan 中不同 topic 需要不同 action，第一版可以拆成多个 RoundPlan 或采取保守策略。

为了保持实现简单，建议第一版：

- 如果所有 selected topics 现有 chunk 足够：`adaptive_generate`
- 如果部分 topic chunk 不足：对不足 topic 执行 expand/supplement 后再生成；RoundPlan action 可以标为 `adaptive_generate_with_retrieval_recovery`

也可以在 executor 中逐 topic 判断。

推荐 executor 逐 topic 决定具体 evidence action：

```python
def execute_topic(round_plan, topic):
    required_single = round_plan.single_k
    required_multi = round_plan.multi_k

    available = evidence_manager.available_counts(topic)

    if not available.enough(required_single, required_multi):
        if available.can_supplement_multi(required_multi):
            evidence_manager.supplement_multi_chunks(topic)
        elif can_expand_retrieval(topic):
            evidence_manager.expand_retrieval(topic, build_expansion_queries(topic, round_plan))
        else:
            return fallback_or_fail(topic, round_plan)

    single_units = evidence_manager.sample_single(topic, round_plan.mode, round_plan.difficulty, required_single)
    multi_units = evidence_manager.sample_multi(topic, round_plan.mode, round_plan.difficulty, required_multi)
    chunks = single_units + multi_units

    return generator.generate(topic, round_plan.mode, round_plan.difficulty, chunks)
```

这样 RoundPlan 保持简单，executor 处理细节。

---

## 7. EvidenceManager 改造

### 7.1 当前机制

当前 EvidenceManager 采样是 mixed sampling：

```text
sample(...) → single units 和 multi units 混合，根据 num_evidence 加权采样
```

新方案需要明确控制：

```text
single_k
multi_k
```

因此新增：

```python
sample_single(topic, target_mode, target_difficulty, k)
sample_multi(topic, target_mode, target_difficulty, k)
available_counts(topic)
supplement_multi_chunks(topic)
```

### 7.2 sample_single

只从 single units 中采样。

伪代码：

```python
def sample_single(self, topic, target_mode, target_difficulty, k):
    pool = self.evidence_pools[topic]
    candidates = pool.single_chunks
    selected = self._weighted_sample_units(
        candidates=candidates,
        target_mode=target_mode,
        target_difficulty=target_difficulty,
        k=k,
        unit_type="single",
    )
    self._mark_usage(selected)
    return selected
```

### 7.3 sample_multi

只从 multi units 中采样。

```python
def sample_multi(self, topic, target_mode, target_difficulty, k):
    pool = self.evidence_pools[topic]
    candidates = pool.multi_chunks
    selected = self._weighted_sample_units(
        candidates=candidates,
        target_mode=target_mode,
        target_difficulty=target_difficulty,
        k=k,
        unit_type="multi",
    )
    self._mark_usage(selected)
    return selected
```

### 7.4 打分逻辑

复用现有 scoring：

- `qa_score`
- `mcq_score`
- `hard_score`
- `usage_count` penalty

推荐统一函数：

```python
def score_unit(unit, target_mode, target_difficulty):
    if target_mode == "multiple_choice":
        base_score = unit.mcq_score
    else:
        base_score = unit.qa_score

    if target_difficulty == "hard":
        base_score = base_score * 0.5 + unit.hard_score * 0.5

    usage_penalty = 1.0 / (1.0 + unit.usage_count)
    return max(base_score * usage_penalty, 1e-6)
```

### 7.5 去重

保留组合级去重：

```python
combo_key = frozenset(single_ids + multi_ids)
```

如果重复，最多重试 N 次。

如果仍然重复，使用 force unique：

- 优先使用未用过的 single/multi units。
- 如果 multi 不足，返回不足并让 executor 执行 supplement 或 expand。

### 7.6 available_counts

```python
@dataclass
class AvailableChunkCounts:
    total_single: int
    total_multi: int
    unused_single: int
    unused_multi: int
    used_ratio: float

    def enough(self, single_k, multi_k):
        return self.unused_single >= single_k and self.unused_multi >= multi_k
```

### 7.7 supplement_multi_chunks

如果已有 source chunks 足够，但 multi units 不足，调用 smart multi chunk builder 生成更多 multi units。

```python
def supplement_multi_chunks(self, topic):
    pool = self.evidence_pools[topic]
    new_multi_units = build_smart_multi_units(
        single_units=pool.single_chunks,
        target_count=...,  # e.g. min(10, len(pool.single_chunks) // 2)
        exclude_existing=True,
    )
    pool.multi_chunks.extend(new_multi_units)
```

---

## 8. Executor 设计

### 8.1 执行 RoundPlan

```python
def execute_round_plan(round_plan, state, evidence_manager, generator):
    results = []

    for topic in round_plan.topics:
        result = execute_topic_plan(round_plan, topic, state, evidence_manager, generator)
        state.update_from_topic_result(topic, round_plan, result)
        results.append(result)

    return results
```

### 8.2 执行单个 topic

```python
def execute_topic_plan(round_plan, topic, state, evidence_manager, generator):
    single_k = round_plan.single_k
    multi_k = round_plan.multi_k

    available = evidence_manager.available_counts(topic)

    if not available.enough(single_k, multi_k):
        recovery_result = recover_evidence_shortage(
            topic=topic,
            round_plan=round_plan,
            available=available,
            evidence_manager=evidence_manager,
            state=state,
        )
        if not recovery_result.success:
            return TopicExecutionResult.failed(
                topic=topic,
                reason=recovery_result.reason,
            )

    single_units = evidence_manager.sample_single(
        topic=topic,
        target_mode=round_plan.mode,
        target_difficulty=round_plan.difficulty,
        k=single_k,
    )

    multi_units = evidence_manager.sample_multi(
        topic=topic,
        target_mode=round_plan.mode,
        target_difficulty=round_plan.difficulty,
        k=multi_k,
    )

    chunk_list = single_units + multi_units

    raw_output = generator.generate(
        topic=topic,
        mode=round_plan.mode,
        difficulty=round_plan.difficulty,
        chunks=chunk_list,
    )

    parsed_questions = parse_generated_questions(raw_output)

    return TopicExecutionResult.success(
        topic=topic,
        selected_single=[u.id for u in single_units],
        selected_multi=[u.id for u in multi_units],
        raw_output=raw_output,
        parsed_questions=parsed_questions,
    )
```

### 8.3 Evidence shortage recovery

```python
def recover_evidence_shortage(topic, round_plan, available, evidence_manager, state):
    # 1. If multi is insufficient but single chunks are available, supplement multi chunks.
    if available.unused_multi < round_plan.multi_k and available.total_single >= 2:
        evidence_manager.supplement_multi_chunks(topic)
        available = evidence_manager.available_counts(topic)
        if available.enough(round_plan.single_k, round_plan.multi_k):
            return RecoveryResult.success("supplemented_multi_chunks")

    # 2. If still insufficient, expand retrieval if allowed.
    if state.topic_expansion_counts.get(topic, 0) < config.retrieval_safety.max_expansions_per_topic:
        queries = build_expansion_queries(topic, round_plan)
        evidence_manager.expand_retrieval(topic, queries)
        state.topic_expansion_counts[topic] += 1
        available = evidence_manager.available_counts(topic)
        if available.enough(round_plan.single_k, round_plan.multi_k):
            return RecoveryResult.success("expanded_retrieval")

    # 3. Fallback to smaller policy if possible.
    fallback_single_k, fallback_multi_k = fallback_chunk_policy(round_plan)
    if available.enough(fallback_single_k, fallback_multi_k):
        round_plan.single_k = fallback_single_k
        round_plan.multi_k = fallback_multi_k
        return RecoveryResult.success("fallback_chunk_policy")

    return RecoveryResult.failure("insufficient_evidence_after_recovery")
```

---

## 9. Generator 接口

生成器保持 chunk-list based，不需要 `questions_per_round`。

```python
questions = question_generator.generate(
    topic=topic,
    mode=mode,
    difficulty=difficulty,
    chunks=chunk_list,
    language=language,
)
```

Prompt 应强调：

```text
Generate candidate questions based only on the provided chunks.
Mode: {mode}
Target difficulty: {difficulty}
Topic: {topic}
Language: {language}
Return structured JSON.
Each question should include support_chunk_ids.
```

如果当前模板必须传数量：

- 不要放进 RoundPlan。
- 可以在 generator 内部基于 `len(chunks)` 和 `generation_yield` 得到一个 soft target。
- 该 soft target 仅用于 prompt wording，不作为硬性校验。

---

## 10. 状态更新

每个 topic 执行后立即更新状态，但重新规划只发生在下一轮。

```python
def update_from_topic_result(state, topic, round_plan, result):
    state.topic_attempts[topic] += 1

    if result.success:
        state.topic_consecutive_failures[topic] = 0
        state.global_consecutive_failures = 0

        for q in result.parsed_questions:
            state.candidate_questions.append(q)
            state.mode_counts[round_plan.mode] += 1
            state.mode_difficulty_counts[round_plan.mode][round_plan.difficulty] += 1
            state.topic_counts[topic] += 1
            state.topic_mode_counts[topic][round_plan.mode] += 1
            state.topic_difficulty_counts[topic][round_plan.difficulty] += 1

        state.record_used_chunks(result.selected_single, result.selected_multi)

    else:
        state.topic_consecutive_failures[topic] += 1
        state.global_consecutive_failures += 1

        if state.topic_consecutive_failures[topic] >= config.topic_safety.max_consecutive_failures_per_topic:
            state.topic_cooldown_until_round[topic] = (
                state.round_num + config.topic_safety.cooldown_rounds_after_failure
            )
```

---

## 11. 停止条件

停止条件不再依赖每主题轮次。推荐：

```python
def should_stop(state, observation, blueprint, config):
    if state.round_num > blueprint.max_rounds:
        return True

    if state.global_consecutive_failures >= config.stop_policy.max_global_consecutive_failures:
        return True

    if candidate_pool_sufficient(state, blueprint, config):
        return True

    if no_available_topics(state, blueprint):
        return True

    return False
```

### 11.1 candidate_pool_sufficient

```python
def candidate_pool_sufficient(state, blueprint, config):
    final_total = sum(mode.count for mode in blueprint.modes.values())
    total_target = final_total * config.stop_policy.candidate_target_multiplier

    if len(state.candidate_questions) < total_target:
        return False

    # mode minimum coverage
    for mode, mode_cfg in blueprint.modes.items():
        mode_target = mode_cfg.count * config.stop_policy.min_mode_candidate_multiplier
        if state.mode_counts.get(mode, 0) < mode_target:
            return False

    # difficulty minimum coverage across all modes
    for mode, mode_cfg in blueprint.modes.items():
        for diff, ratio in mode_cfg.difficulty_distribution.items():
            final_diff_target = mode_cfg.count * ratio
            candidate_diff_target = final_diff_target * config.stop_policy.min_difficulty_candidate_multiplier
            if state.mode_difficulty_counts.get(mode, {}).get(diff, 0) < candidate_diff_target:
                return False

    return True
```

这不是精确补题，只是防止候选池严重偏斜。

---

## 12. 风险与解决方案

### 12.1 风险：某个低覆盖 topic 被反复选择

解决：

- failure penalty
- cooldown
- topic expansion penalty

```python
topic_score = coverage_need + mode_need - failure_penalty - expansion_penalty
```

连续失败达到阈值后进入 cooldown。

### 12.2 风险：topic 检索重复严重

解决：

- 记录 used chunk combinations。
- 记录 used ratio。
- 如果 used_ratio 超过 `chunk_exhaustion_ratio`，先 expand retrieval。
- expand 次数达到上限后进入 fallback 或 cooldown。

### 12.3 风险：hard-focus 过度使用

解决：

- `hard_focus_threshold`
- `max_consecutive_hard_focus_rounds`

只有 hard 缺口超过阈值才 hard-focus。

### 12.4 风险：multi chunks 不足

解决：三段降级：

1. `supplement_chunks_then_generate`
2. `expand_retrieval_then_generate`
3. fallback to smaller chunk policy

### 12.5 风险：候选池总数足够但分布偏斜

解决：停止条件加入：

- min mode candidate multiplier
- min difficulty candidate multiplier

### 12.6 风险：主题不均衡

本方案不强制主题均衡。解决方式不是后续强制均衡，而是：

- initial breadth 保证每个 topic 至少被探索。
- 后续由验证智能体和最终采样阶段决定最终分布。
- 生成阶段只避免完全遗漏 topic。

---

## 13. 输出文件

建议输出目录：

```text
runs/{run_id}/
  candidate_pool.json
  generation_trace.json
  generation_state.json
  generation_report.json
  used_chunks.json
```

### 13.1 candidate_pool.json

保存所有解析成功的候选题。

### 13.2 generation_trace.json

记录每轮：

- observation summary
- RoundPlan
- 每个 topic 的 selected chunks
- raw output metadata
- parsed question count
- failure reason

示例：

```json
{
  "round": 4,
  "observation": {
    "mode": "multiple_choice",
    "underrepresented_difficulty": "hard",
    "weak_topics": ["Climate Change", "History", "Medicine"]
  },
  "round_plan": {
    "mode": "multiple_choice",
    "difficulty": "hard",
    "strategy": "hard_focus",
    "topics": ["Climate Change", "History", "Medicine"],
    "single_k": 0,
    "multi_k": 3
  },
  "results": [
    {
      "topic": "Climate Change",
      "selected_single": [],
      "selected_multi": ["multi_7", "multi_8", "multi_9"],
      "generated_count": 5,
      "parse_success": true
    }
  ]
}
```

### 13.3 generation_report.json

包含：

- total candidates
- mode distribution
- difficulty distribution
- topic distribution
- action distribution
- retrieval expansions
- cooldown topics
- failure reasons
- stop reason

---

## 14. 建议代码改动清单

### 14.1 新增模块

```text
benchforge/agents/question_generator/modules/adaptive_planner.py
benchforge/agents/question_generator/modules/generation_state.py
benchforge/agents/question_generator/modules/round_plan.py
```

### 14.2 改造 EvidenceManager

新增：

```python
sample_single(...)
sample_multi(...)
available_counts(...)
supplement_multi_chunks(...)
```

保留：

```python
prepare_evidence(...)
expand_retrieval(...)
used_chunk_combinations
usage_count scoring
```

### 14.3 改造主 Agent

新增或替换为：

```text
AdaptiveChunkGenerationAgent
```

核心循环：

```python
while not should_stop:
    observation = state.observe()
    round_plan = planner.build_round_plan(observation)
    results = executor.execute_round_plan(round_plan)
    state.update(results)
    reporter.log(...)
```

### 14.4 改造 ActionExecutor

从“执行一个 gap action”改成“执行 RoundPlan 中的多个 topic”。

### 14.5 改造 Reporter

新增 generation trace 输出。

---

## 15. 验收标准

### 15.1 功能验收

1. 能读取新的 blueprint 配置。
2. Round 1 自动生成 QA + medium + all topics 的 RoundPlan。
3. Round 2 自动生成 MCQ + medium + all topics 的 RoundPlan。
4. Round 3 以后按 mode rotation 生成 adaptive RoundPlan。
5. Planner 不再根据 remaining 精确补题。
6. RoundPlan 不包含 `questions_per_round`。
7. EvidenceManager 支持 `sample_single` 和 `sample_multi`。
8. 生成器接收 chunk list 生成候选题。
9. 输出 candidate_pool 和 generation_trace。
10. 达到 stop condition 后停止。

### 15.2 稳定性验收

1. 某 topic 连续失败后进入 cooldown。
2. chunk 不足时先 supplement，再 expand，再 fallback。
3. expand retrieval 有上限。
4. hard-focus 不会无限连续触发。
5. 候选池达到目标倍率后停止。

### 15.3 设计验收

1. 生成阶段不保证最终题目数精确。
2. 生成阶段不做最终 benchmark sampling。
3. 生成阶段不与后续验证智能体职责重叠。
4. 题目数量只用于 observation 和 stop condition。
5. 主题不强制均衡，但 initial breadth 保证每个 topic 被探索。

---

## 16. 最终结论

本方案是合理的，建议实现。

最终架构可描述为：

```text
Blueprint-guided, mode-rotating, round-plan-based, adaptive chunk-sampling candidate generation agent.
```

中文表述：

```text
基于蓝图、题型轮转、轮次计划驱动、自适应 chunk 采样的候选题生成智能体。
```

核心边界：

```text
Blueprint 提供目标
Planner 产生 RoundPlan
EvidenceManager 按 single_k / multi_k 采样 chunks
Generator 基于 chunk list 生成候选题
State 记录当前分布和失败情况
Validation Agent 后续负责质量验证和最终采用
```

不要再引入：

```text
hard_multi_bonus
questions_per_round
single_chunk_questions
multi_chunk_questions
max_rounds_per_topic as topic balancing control
```

保留并强化：

```text
initial breadth
mode rotation
hard_focus chunk policy
sample_single/sample_multi
topic safety cooldown
retrieval expansion limit
generation trace
```
