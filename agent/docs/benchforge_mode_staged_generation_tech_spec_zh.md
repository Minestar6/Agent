# BenchForge 按题型分阶段的自适应 Chunk 生成智能体技术文档（中文版）

> 本文是英文技术方案的中文整理版，并为关键字段补充用途解释。  
> 目标是作为 Claude Code 或开发者实现 MVP 的说明文档。

---

## 0. 总览

本方案将 BenchForge 题目生成器定义为：

**基于蓝图、按题型分阶段、自适应 chunk 采样的候选题生成智能体。**

它不直接产出最终 benchmark，而是为每种题型生成候选题池。后续验证智能体负责质量验证、答案检查、语义去重、难度校准和最终采样。

核心思想：

1. 每种题型单独作为一个阶段运行。
2. 每个题型内部先做 topic 广度覆盖，再做自适应补充。
3. 候选题按题型分开保存。
4. chunk 使用记录全局共享，避免不同题型重复使用完全相同的 evidence 组合。

---

## 1. 设计目标

### 1.1 生成智能体负责什么？

生成智能体负责：

1. 读取 blueprint；
2. 为所有 topics 准备 evidence chunks；
3. 按 `blueprint.modes` 的声明顺序处理题型；
4. 对每个题型执行：
   - initial breadth generation；
   - adaptive supplement rounds；
   - 动态计算 `single_k` 和 `multi_k`；
   - 基于 chunk list 生成候选题；
   - 将候选题保存到该题型目录；
5. 维护全局 chunk combination 去重；
6. 导出 candidate pools、generation traces、mode states 和 global evidence usage。

### 1.2 生成智能体不负责什么？

生成智能体不负责：

1. 精确生成最终题目数；
2. 最终质量验证；
3. 最终语义去重；
4. 最终 benchmark 采样；
5. 完整答案正确性验证。

这些由下游 validation agents 负责。

---

## 2. 关键设计决策

### 2.1 题型按 `modes` 声明顺序分阶段生成

示例：

```yaml
modes:
  qa:
    count: 30
  multiple_choice:
    count: 20
```

执行顺序就是：

```text
Stage 1: qa
Stage 2: multiple_choice
```

不需要额外的 `mode_order` 字段。  
如果想改变题型生成顺序，只需调整 `modes` 的 YAML 声明顺序。

### 2.2 每个题型单独保存

每个题型有自己的：

```text
candidate_pool.json
generation_trace.json
mode_state.json
failures.json
```

这样 QA、MCQ 等题型的 schema、验证逻辑和调试日志不会混在一起。

### 2.3 chunk 使用记录全局共享

虽然题目按题型分开生成，但 chunk combination 去重是全局的。

原因：

- QA 阶段用过的 chunk 组合，不应在 MCQ 阶段完全重复使用；
- 可以提高候选池的知识覆盖多样性；
- 单个 chunk 可以复用，但完全相同的 chunk 组合要尽量避免。

### 2.4 chunk combination 去重粒度

去重 key 使用底层 raw chunk IDs，而不是 multi-unit IDs。

示例：

```text
single_unit: chunk_a
multi_unit_1: [chunk_b, chunk_c]
multi_unit_2: [chunk_d, chunk_e]

global combination key:
(chunk_a, chunk_b, chunk_c, chunk_d, chunk_e)
```

---

## 3. Blueprint Schema 与字段说明

推荐配置：

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
  # min_difficulty_multiplier: Phase 2，MVP 不实现 difficulty floor check。

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

### 3.1 顶层字段

| 字段 | 用途 |
|---|---|
| `task_id` | 任务 ID，用于组织输出目录。一个 task 下可以有多个 run。 |
| `run_id` | 本次运行 ID，用于区分同一任务的不同实验。 |
| `language` | 题目生成语言，例如 `en` 或 `zh`。会传给 generator。 |
| `topics` | 主题列表。每个 mode 的 initial breadth 会对每个 topic 至少尝试一次。 |
| `modes` | 题型配置。声明顺序就是执行顺序。 |

### 3.2 `modes`

| 字段 | 用途 |
|---|---|
| `qa` / `multiple_choice` | 题型名称，每个题型单独运行一个生成阶段。 |
| `count` | 最终 benchmark 期望该题型采用的题目数。不是每轮生成数量。 |
| `max_rounds` | 当前题型最大生成轮数，防止无限循环。 |
| `difficulty_distribution` | 当前题型的目标难度分布，用于判断哪个难度不足。 |

`count` 的实际用途：

```text
candidate_target = count * candidate_pool.target_multiplier
```

例如：

```text
qa.count = 30
target_multiplier = 2.5
QA 候选池目标 = 75
```

### 3.3 `candidate_pool`

| 字段 | 用途 |
|---|---|
| `target_multiplier` | 候选池倍率。生成阶段通常生成比最终题数更多的候选题，供后续验证智能体筛选。 |
| `min_difficulty_multiplier` | Phase 2 字段。MVP 不启用。 |

### 3.4 `initial_breadth`

| 字段 | 用途 |
|---|---|
| `enabled` | 是否开启 initial breadth。建议 MVP 开启。 |
| `max_topics_per_round` | initial breadth 每轮最多处理多少 topic，避免 topic 很多时单轮过长。 |
| `difficulty` | initial breadth 使用的默认难度，建议 `medium`。 |

initial breadth 语义：

```text
当前 mode 下，每个 topic 至少尝试一次。
尝试过就算 coverage，不要求成功生成题目。
```

### 3.5 `planner`

| 字段 | 用途 |
|---|---|
| `topics_per_round` | adaptive 阶段每轮选择多少个低覆盖 topic。 |

### 3.6 `chunk_mix`

`chunk_mix` 决定当前难度和题型下 single/multi chunks 的比例。

| 字段 | 用途 |
|---|---|
| `by_difficulty.easy.single_ratio` | easy 题更偏 single chunk。 |
| `by_difficulty.easy.multi_ratio` | easy 题少量使用 multi chunk。 |
| `by_difficulty.medium.single_ratio` | medium 题 single/multi 平衡。 |
| `by_difficulty.medium.multi_ratio` | medium 题 single/multi 平衡。 |
| `by_difficulty.hard.single_ratio` | hard 题保留少量 single chunk 作为答案锚点。 |
| `by_difficulty.hard.multi_ratio` | hard 题更多使用 multi chunk，支持综合、比较和多跳推理。 |
| `mode_adjustment.qa.single_delta` | QA 稍微提高 single 比例，因为 QA 需要明确答案锚点。 |
| `mode_adjustment.multiple_choice.single_delta` | MCQ 稍微降低 single 比例，也就是提高 multi 比例，因为 MCQ 需要更强干扰项。 |

### 3.7 `generation_yield`

`generation_yield` 将“候选题缺口”换算为“需要多少 chunks”。

| 字段 | 用途 |
|---|---|
| `single_chunk_avg_questions` | 一个 single chunk 平均能生成多少候选题的估计值。 |
| `multi_chunk_avg_questions` | 一个 multi chunk unit 平均能生成多少候选题的估计值。 |

这是估算，不是硬约束。后续可以根据真实日志更新。

### 3.8 `chunk_limits`

`chunk_limits` 给动态计算出的 `single_k` 和 `multi_k` 加上下界和上界。

| 字段 | 用途 |
|---|---|
| `single_k.min` | 每个 topic 最少采多少 single chunks。 |
| `single_k.max` | 每个 topic 最多采多少 single chunks，防止 prompt 过长。 |
| `multi_k.min` | 每个 topic 最少采多少 multi chunks。 |
| `multi_k.max` | 每个 topic 最多采多少 multi chunks，防止上下文过长或生成不稳定。 |

### 3.9 `runtime`

| 字段 | 用途 |
|---|---|
| `max_consecutive_empty_rounds_per_mode` | 当前 mode 连续多少轮没有生成任何题时停止。按 round 统计。 |
| `max_failures_per_mode` | 当前 mode 最多允许多少 topic-level 执行失败。 |
| `max_used_chunk_combinations` | 全局最多保存多少已用 chunk combinations，防止内存无限增长。 |
| `llm_timeout_seconds` | LLM 调用超时时间。 |
| `retrieval_timeout_seconds` | 检索超时时间，Phase 2 检索扩展可使用。 |

---

## 4. 输出目录结构与文件用途

推荐输出结构：

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

| 文件 | 用途 |
|---|---|
| `blueprint.yaml` | 保存本次运行配置，便于复现。 |
| `generation_report.json` | 全局报告，汇总各题型结果。 |
| `global_state.json` | 全局状态摘要，例如 global failures。 |
| `used_chunks.json` | 全局 chunk combination 和 chunk usage 记录。 |
| `{mode}/candidate_pool.json` | 当前题型候选题池。 |
| `{mode}/generation_trace.json` | 当前题型每轮计划和执行结果。 |
| `{mode}/mode_state.json` | 当前题型统计状态。 |
| `{mode}/failures.json` | 当前题型失败记录。 |

---

## 5. 状态模型

系统有两层状态：

1. `GlobalState`
2. `ModeState`

### 5.1 GlobalState

```python
@dataclass
class GlobalState:
    used_chunk_combinations: set[tuple[str, ...]] = field(default_factory=set)
    used_chunk_combination_order: deque[tuple[str, ...]] = field(default_factory=deque)
    chunk_usage_counts: dict[str, int] = field(default_factory=dict)
    global_failures: int = 0
```

| 字段 | 用途 |
|---|---|
| `used_chunk_combinations` | 全局已使用 raw chunk combination 集合。用于跨题型避免相同 evidence 组合。 |
| `used_chunk_combination_order` | 记录 combination 插入顺序，用于超过上限时淘汰旧记录。 |
| `chunk_usage_counts` | 单个 chunk 使用次数。MVP 主要用于报告，Phase 2 可用于 usage penalty。 |
| `global_failures` | 全局失败次数，仅用于报告，不参与 mode 停止条件。 |

### 5.2 ModeState

```python
@dataclass
class ModeState:
    mode: str
    round_in_mode: int = 1
    candidate_questions: list[dict] = field(default_factory=list)
    difficulty_counts: dict[str, int] = field(default_factory=dict)
    topic_counts: dict[str, int] = field(default_factory=dict)
    initial_coverage: set[str] = field(default_factory=set)
    consecutive_empty_rounds: int = 0
    failures: list[dict] = field(default_factory=list)
    failures_count: int = 0
    stopped_reason: str | None = None
```

| 字段 | 用途 |
|---|---|
| `mode` | 当前题型。 |
| `round_in_mode` | 当前题型内部轮次。 |
| `candidate_questions` | 当前题型已生成候选题。 |
| `difficulty_counts` | 当前题型内各难度候选题数量。 |
| `topic_counts` | 当前题型内各 topic 候选题数量。 |
| `initial_coverage` | 当前题型已尝试过的 topics。 |
| `consecutive_empty_rounds` | 当前题型连续空轮次数。空轮指整轮所有 topic 总生成数为 0。 |
| `failures` | 当前题型失败记录。 |
| `failures_count` | 当前题型失败次数。达到上限后停止该 mode。 |
| `stopped_reason` | 当前题型停止原因。 |

---

## 6. 执行流程

### 6.1 总体流程

```python
async def run_generation_agent(blueprint, config, evidence_manager, generator):
    global_state = GlobalState()

    await evidence_manager.prepare_all_topics(blueprint.topics)

    for mode, mode_cfg in blueprint.modes.items():
        mode_state = ModeState(mode=mode)

        await run_mode_generation(...)

        save_mode_outputs(blueprint.task_id, blueprint.run_id, mode, mode_state)

    save_global_outputs(blueprint.task_id, blueprint.run_id, global_state)
    save_generation_report(blueprint.task_id, blueprint.run_id, global_state)
```

说明：

| 步骤 | 用途 |
|---|---|
| `prepare_all_topics` | 准备所有主题的 evidence chunks。 |
| 遍历 `blueprint.modes.items()` | 按声明顺序依次处理题型。 |
| `run_mode_generation` | 运行某个题型的完整生成阶段。 |
| `save_mode_outputs` | 保存题型级输出。 |
| `save_global_outputs` | 保存全局 chunk 使用状态。 |
| `save_generation_report` | 保存总报告。 |

### 6.2 单个 mode 的流程

核心循环：

```text
检查是否停止
→ 构建本轮计划
→ 如果没有 topics，记为空轮
→ 执行本轮 topic 生成
→ 统计整轮生成数量
→ 更新 trace
→ round_in_mode + 1
```

关键要求：

- `consecutive_empty_rounds` 按 round 更新，不按 topic 更新；
- 单个 topic 失败不会打断整轮；
- 每个 mode 独立停止。

---

## 7. ModeRoundPlan：每轮计划

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

| 字段 | 用途 |
|---|---|
| `mode` | 当前题型。 |
| `round_in_mode` | 当前题型内轮次。 |
| `strategy` | 当前策略，通常是 `initial_breadth` 或 `adaptive`。 |
| `difficulty` | 当前轮目标难度。 |
| `topics` | 当前轮处理的 topics。使用 tuple 防止执行中被修改。 |
| `single_k` | 每个 topic 采样多少 single chunk units。 |
| `multi_k` | 每个 topic 采样多少 multi chunk units。 |
| `target_candidates_per_topic` | 估算每个 topic 本轮应贡献多少候选题。不是硬约束。 |
| `reason` | 计划原因，用于 trace 和调试。 |

---

## 8. 规划逻辑

每个 mode 有两个阶段：

1. `initial_breadth`
2. `adaptive`

### 8.1 Initial Breadth

目标：

```text
当前 mode 下，每个 topic 至少尝试一次。
```

特点：

- 按 `initial_breadth.max_topics_per_round` 分批；
- 使用默认难度 `initial_breadth.difficulty`；
- 尝试过就加入 `initial_coverage`，不要求生成成功。

### 8.2 Adaptive Supplement

当 initial breadth 完成后：

1. 选择当前 mode 下最缺的 difficulty；
2. 选择当前 mode 下低覆盖 topics；
3. 动态计算 `single_k` / `multi_k`；
4. 生成候选题。

---

## 9. 难度选择

选择当前 mode 中最缺的 difficulty。

依据：

| 字段 | 用途 |
|---|---|
| `mode_cfg.difficulty_distribution` | 目标难度分布。 |
| `mode_state.difficulty_counts` | 当前实际难度计数。 |
| `candidate_questions` | 当前 mode 候选题总数。 |

逻辑：

```text
目标比例 - 当前比例 最大的 difficulty，就是下一轮目标难度。
```

---

## 10. Topic 选择

选择当前 mode 下候选题较少的 topics。

核心思想：

```text
expected_per_topic = 当前 mode 候选题总数 / topics 数量
score = expected_per_topic - 当前 topic 候选题数量
```

score 越大，说明该 topic 覆盖越少，越优先。

注意：

- 这不是强制 topic 均衡；
- 只是避免某些 topic 完全被忽略；
- 最终采样和去重仍由 downstream validation 处理。

---

## 11. 动态计算 single_k / multi_k

计算流程：

```text
mode 目标候选数
→ 当前已有候选数
→ 候选缺口
→ 剩余轮次
→ 本轮目标候选数
→ 每个 topic 目标候选数
→ 按 difficulty/mode 分配 single/multi 比例
→ 用 generation_yield 换算 chunk 数
→ 用 chunk_limits 限制上下界
```

### 11.1 mode 候选目标

```python
mode_candidate_target = ceil(mode_cfg.count * target_multiplier)
```

### 11.2 剩余轮次

```python
remaining_rounds = max(1, mode_cfg.max_rounds - mode_state.round_in_mode + 1)
```

### 11.3 single/multi 比例

difficulty 决定主比例，mode 做轻微修正：

```text
easy: single 多
medium: single/multi 平衡
hard: multi 多

QA: single 稍多
MCQ: multi 稍多
```

### 11.4 yield 换算

示例：

```text
target_candidates_per_topic = 6
QA hard single_ratio = 0.3
QA hard multi_ratio = 0.7

single 目标候选 = 1.8
multi 目标候选 = 4.2

single yield = 2.0
multi yield = 3.0

single_k = ceil(1.8 / 2.0) = 1
multi_k = ceil(4.2 / 3.0) = 2
```

---

## 12. Chunk Sampling

每个 topic 的采样流程：

1. 采 `single_k` 个 single chunk units；
2. 采 `multi_k` 个 multi chunk units；
3. 合并成 chunk list；
4. 展开成 raw chunk IDs；
5. 检查全局 combination 是否重复；
6. 返回 `(chunks, duplicate_combination)`。

### 12.1 `raw_chunk_ids`

用途：

```text
将 single/multi units 展开为底层 raw chunk IDs，用于全局组合去重。
```

### 12.2 `sample_chunks`

返回值：

| 返回值 | 用途 |
|---|---|
| `chunks` | 本次采样得到的 chunk list。 |
| `duplicate_combination` | 是否因 5 次重试都重复而接受了重复组合。需要写入 trace。 |

MVP 只做 combination-level dedup。  
individual chunk usage penalty 放到 Phase 2。

---

## 13. Generation Execution

每个 topic 单独 try/except。

成功时：

1. sample chunks；
2. 调用 generator；
3. parse questions；
4. 更新 mode state；
5. 记录 chunk usage；
6. 写入 topic result。

失败时：

1. `mode_state.failures_count += 1`；
2. `global_state.global_failures += 1`；
3. 写入 `mode_state.failures`；
4. 当前 topic result 标记失败；
5. 继续下一个 topic。

finally：

```text
如果是 initial_breadth，则无论成功失败，都将 topic 加入 initial_coverage。
```

这样避免坏 topic 卡住 initial breadth。

---

## 14. Mode State Update

状态更新必须使用题目实际解析出的 difficulty，而不是计划 difficulty。

```python
actual_difficulty = normalize_difficulty(
    q.get("estimated_difficulty") or q.get("difficulty") or round_plan.difficulty
)
```

更新字段：

| 字段 | 用途 |
|---|---|
| `candidate_questions` | 保存候选题。 |
| `difficulty_counts` | 更新实际难度分布。 |
| `topic_counts` | 更新 topic 覆盖数量。 |

---

## 15. Mode Stop Conditions

停止条件：

| 条件 | 含义 |
|---|---|
| `initial_done and candidate_count >= target` | initial breadth 完成后，候选池达到目标，正常停止。 |
| `round_in_mode > max_rounds` | 当前题型达到最大轮次，保护性停止。 |
| `consecutive_empty_rounds >= max_consecutive_empty_rounds_per_mode` | 连续多轮没有生成题，停止。 |
| `failures_count >= max_failures_per_mode` | 当前题型失败次数过多，停止。 |

重要：

```text
candidate_pool_sufficient 不允许在 initial breadth 完成前触发。
```

---

## 16. 辅助函数接口

### 16.1 `parse_questions`

用途：

```text
将 LLM 原始输出解析成候选题列表。
解析失败时返回 []，不要抛异常。
```

### 16.2 `update_mode_trace`

用途：

```text
把当前 round 的 plan 和结果写入 mode_state trace，用于导出 generation_trace.json。
```

trace 至少应包含：

- mode；
- round_in_mode；
- strategy；
- difficulty；
- topics；
- single_k；
- multi_k；
- target_candidates_per_topic；
- 每个 topic 的 result；
- duplicate_combination；
- error。

### 16.3 `save_mode_outputs`

用途：

```text
保存当前 mode 的 candidate_pool、generation_trace、mode_state、failures。
```

### 16.4 `save_global_outputs`

用途：

```text
保存 used_chunks.json 和 global_state.json。
```

### 16.5 `save_generation_report`

用途：

```text
保存全局 generation_report.json。
```

---

## 17. Global Report

示例：

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
  "global_used_chunk_combinations": 84,
  "global_failures": 2
}
```

字段说明：

| 字段 | 用途 |
|---|---|
| `task_id` | 任务 ID。 |
| `run_id` | 运行 ID。 |
| `modes` | 各题型汇总信息。 |
| `candidate_count` | 当前题型候选题数量。 |
| `target_candidate_count` | 当前题型候选池目标数量。 |
| `stopped_reason` | 当前题型停止原因。 |
| `total_candidates` | 所有题型候选题总数。 |
| `global_used_chunk_combinations` | 全局使用过的 chunk 组合数量。 |
| `global_failures` | 全局失败次数，仅用于报告。 |

---

## 18. 实施阶段

### Phase 1：MVP

实现：

1. mode-staged generation；
2. mode-specific output folders；
3. initial breadth per mode；
4. adaptive supplement per mode；
5. dynamic single_k / multi_k；
6. global chunk combination dedup；
7. mode-specific stop conditions。

暂不实现：

1. complex cooldown；
2. complex API error taxonomy；
3. multi-step fallback tree；
4. LLM strategy advisor；
5. downstream validation。

### Phase 2：鲁棒性增强

后续添加：

1. evidence shortage fallback；
2. retrieval expansion；
3. chunk exhaustion detection；
4. cooldown；
5. timeout-specific handling；
6. richer failure reports；
7. individual chunk usage penalty。

### Phase 3：智能化增强

后续添加：

1. strategy memory；
2. LLM strategy advisor；
3. chunk strategy types；
4. plan candidate scoring。

---

## 19. MVP 验收标准

MVP 需要满足：

1. 按 `blueprint.modes` 声明顺序处理题型；
2. 每个 mode 写入自己的输出目录；
3. QA 和 multiple-choice 不混在同一个 candidate 文件；
4. 每个 mode 下 initial breadth 至少尝试每个 topic 一次；
5. adaptive rounds 在当前 mode 内选择低覆盖 difficulty 和 topics；
6. `single_k` 和 `multi_k` 根据候选缺口、剩余轮次、topic 数、chunk mix、yield、limits 动态计算；
7. chunk combinations 跨 mode 全局去重；
8. individual chunk usage penalty 是 Phase 2；MVP 只做 combination-level dedup；
9. 每个 mode 独立停止；
10. 生成全局 report；
11. `consecutive_empty_rounds` 按 round 更新，不按 topic 更新；
12. `mode_should_stop` 无副作用，只返回 `(bool, reason)`；
13. `execute_mode_round_plan` 捕获 topic 级异常并继续执行后续 topic；
14. `ModeRoundPlan` 使用 `frozen=True`，`topics` 为 tuple；
15. `mode_state.failures_count >= max_failures_per_mode` 会停止当前 mode；
16. `GlobalState` MVP 中不包含 `topic_expansion_counts`；
17. `build_initial_breadth_plan` 返回完整的 9 个 ModeRoundPlan 字段；
18. initial breadth 中 topic 无论成功失败，只要尝试过就加入 `initial_coverage`；
19. `sample_chunks` 返回 `(chunks, duplicate_combination)`，并写入 trace；
20. MVP blueprint 中不启用 `candidate_pool.min_difficulty_multiplier`。

---

## 20. 总结

最终架构：

> **按 blueprint.modes 顺序执行、按题型分阶段、自适应 chunk 采样的候选题生成智能体。**

简化流程：

```text
For each question mode:
  1. 对所有 topics 做一次初始探索。
  2. 观察当前 mode 的候选题池。
  3. 选择薄弱 difficulty 和薄弱 topics。
  4. 动态计算 single_k 和 multi_k。
  5. 采样全局去重的 chunks。
  6. 生成候选题。
  7. 将候选题保存到该 mode 的目录。
```

关键分离：

```text
候选题：按 mode 分开保存。
mode 进度：按 mode 单独统计。
chunk 使用：全局共享去重。
最终验证：交给后续 validation agents。
```

该设计让生成阶段更清晰、可调试、可扩展，也方便后续验证智能体按题型分别消费候选池。
