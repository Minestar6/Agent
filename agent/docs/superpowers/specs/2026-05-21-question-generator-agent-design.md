# QuestionGeneratorAgent 设计说明

日期：2026-05-21

## 1. 目标

设计一个轻量状态机式的 `QuestionGeneratorAgent`，用于根据上游 `PlannerAgent` 下发的生成计划，围绕给定主题集合自动完成：

1. 检索主题相关文档
2. 生成文档摘要
3. 构建单 chunk 与多 chunk 证据池
4. 根据题目类型与难度缺口调度证据单元
5. 调用统一 prompt 模板生成候选题
6. 进行轻量格式过滤
7. 更新当前主题状态与全局状态
8. 在轮次限制内尽量满足计划目标

该设计不追求“重型智能体”，而是以低成本、可解释、可实现为优先，参考 `yourbench` 的 prompt 与文档处理思路，但在调度层加入显式状态与缺口驱动逻辑。

## 2. 设计原则

1. 上游负责定义目标，生成器负责调度与执行。
2. `multiple_choice` 与 `qa` 使用不同主 prompt。
3. `easy / medium / hard` 不拆成三套主 prompt，而通过附加要求、chunk 选择、多 chunk 组合与题目复杂化调节。
4. 主题按顺序推进，但允许最终全局补题时跨主题补缺口。
5. 只做轻量格式过滤，不在生成器中做正式质量验证。
6. 生成时允许冗余，不追求精确估算 chunk 产出。
7. 调度优先基于证据单元经验统计，而不是手工写死每批次恰好生成多少题。

## 3. 非目标

本设计当前不包含以下能力：

1. 正式的 `QuestionValidatorAgent` 语义验证
2. 跨文档多 chunk 组合
3. LLM 驱动的 chunk 打分
4. 基于模型反馈自动改写检索查询
5. 难度真实性判定
6. 去重后的全局 benchmark 分析

## 4. 上游输入契约

生成器接收 `GenerationPlan`，该对象由 `PlannerAgent` 生成。

```python
class QuestionModeTarget(BaseModel):
    count: int
    difficulty_distribution: dict[str, float]


class GenerationPlan(BaseModel):
    run_id: str
    goal: str
    topics: list[str]
    mode_targets: dict[str, QuestionModeTarget]
    max_rounds_per_topic: int
    max_total_rounds: int
    language: str = "en"
    retrieval_policy: str = "wikipedia_first"
```

约束说明：

1. `mode_targets` 的 key 仅允许：
   - `multiple_choice`
   - `qa`
2. `difficulty_distribution` 的 key 仅允许：
   - `easy`
   - `medium`
   - `hard`
3. 每个 `mode` 的难度分布由上游给出比例，生成器内部使用最大余数法转为精确目标数。

示例：

```python
GenerationPlan(
    run_id="run_001",
    goal="生成历史与产业制度相关评测题",
    topics=["Fordism", "Taylorism"],
    mode_targets={
        "multiple_choice": QuestionModeTarget(
            count=12,
            difficulty_distribution={"easy": 0.25, "medium": 0.5, "hard": 0.25},
        ),
        "qa": QuestionModeTarget(
            count=8,
            difficulty_distribution={"easy": 0.125, "medium": 0.5, "hard": 0.375},
        ),
    },
    max_rounds_per_topic=4,
    max_total_rounds=12,
    language="en",
)
```

## 5. 内部核心对象

### 5.1 TopicState

`TopicState` 表示当前主题的局部执行状态。

```python
class TopicState(BaseModel):
    topic: str
    status: str  # pending / active / completed / deferred
    current_round: int
    target_counts: dict[str, int]
    completed_counts: dict[str, int]
    remaining_counts: dict[str, int]
    retrieved_documents: list[str]
    available_single_chunk_ids: list[str]
    available_multi_chunk_ids: list[str]
```

计数字段建议统一使用 `mode:difficulty` 形式，例如：

```python
{
    "multiple_choice:easy": 2,
    "multiple_choice:medium": 3,
    "multiple_choice:hard": 1,
    "qa:easy": 1,
    "qa:medium": 2,
    "qa:hard": 1,
}
```

### 5.2 EvidencePool

证据池分为单 chunk 与多 chunk 两类。

```python
class SingleChunkUnit(BaseModel):
    chunk_id: str
    document_id: str
    topic: str
    text: str
    tags: list[str]
    mcq_score: float
    qa_score: float
    hard_score: float
    usage_count: int = 0


class MultiChunkUnit(BaseModel):
    unit_id: str
    document_id: str
    topic: str
    chunk_ids: list[str]
    texts: list[str]
    tags: list[str]
    mcq_score: float
    qa_score: float
    hard_score: float
    usage_count: int = 0


class EvidencePool(BaseModel):
    topic: str
    single_chunks: list[SingleChunkUnit]
    multi_chunks: list[MultiChunkUnit]
```

第一版 `multi_chunks` 仅支持同文档 chunk 组合，不支持跨文档组合。

### 5.3 EvidenceStats

`EvidenceStats` 用于维护证据单元的经验产出统计。

```python
class EvidenceTypeStats(BaseModel):
    avg_candidate_count: float
    avg_valid_count: float
    mode_distribution: dict[str, float]
    difficulty_distribution: dict[str, float]


class EvidenceStats(BaseModel):
    single_chunk_stats: EvidenceTypeStats
    multi_chunk_stats: EvidenceTypeStats
```

设计意图：

1. 统计单 chunk 平均产出多少候选题与有效题
2. 统计多 chunk 平均产出多少候选题与有效题
3. 统计两类证据单元更容易产出哪种 `mode`
4. 统计两类证据单元更容易产出哪种难度

### 5.4 GenerationBatch

`GenerationBatch` 是每轮送给大模型的生成单元。

```python
class GenerationBatch(BaseModel):
    topic: str
    target_mode: str
    target_difficulty: str
    remaining_count: int
    single_chunk_ids: list[str]
    multi_chunk_ids: list[str]
    prompt_template_id: str
    additional_instructions: str = ""
    requested_min_questions: int
    requested_target_questions: int
```

关键点：

1. `remaining_count` 表示真实缺口
2. `requested_min_questions` 表示最低希望模型返回的候选题数
3. `requested_target_questions` 表示带 buffer 的目标候选题数
4. `single_chunk_ids` 与 `multi_chunk_ids` 可以同时存在
5. 最终送入模型的是“目标缺口 + 证据列表 + prompt”

## 6. 计划编译规则

### 6.1 mode 内部难度目标数展开

对每个 `QuestionModeTarget.count`：

1. 按难度比例计算浮点目标数
2. 先对各项向下取整
3. 使用最大余数法分配余数

示例：

```python
multiple_choice.count = 12
difficulty_distribution = {"easy": 0.25, "medium": 0.5, "hard": 0.25}
```

展开后：

```python
{
    "multiple_choice:easy": 3,
    "multiple_choice:medium": 6,
    "multiple_choice:hard": 3,
}
```

### 6.2 按主题进行初始均分

将全局 `mode:difficulty` 目标数对主题进行尽量平均分配。

规则：

1. 默认均分
2. 无法整除时，余数继续用最大余数法或顺序补给部分主题
3. 这只是初始局部目标，不是最终硬约束
4. 运行中允许偏离，后续允许跨主题转移补题

### 6.3 初始化 TopicState

每个主题初始化为：

1. `status = pending`
2. `current_round = 0`
3. `completed_counts = 0`
4. `remaining_counts = target_counts`
5. `retrieved_documents = []`
6. `available_single_chunk_ids = []`
7. `available_multi_chunk_ids = []`

## 7. 主题级状态机

主题级执行顺序如下：

1. 取下一个 `pending` 主题
2. 进入 `active`
3. 执行 `prepare_evidence`
4. 在 `max_rounds_per_topic` 内循环生成
5. 如果该主题初始目标达标，则标记 `completed`
6. 如果达到 `max_rounds_per_topic` 仍未达标，则标记 `deferred`
7. 切换到下一个主题
8. 所有主题结束后，若全局缺口未满足，则进入全局补题阶段

## 8. Evidence Preparation

每个主题首次进入 `active` 时执行一次 `prepare_evidence`。

步骤：

1. 检索主题相关文档
2. 生成每个文档的 `document_summary`
3. 基于文档正文切出正式 question chunks
4. 基于正式 question chunks 构建 `single_chunk_pool`
5. 基于正式 question chunks 构建 `multi_chunk_pool`
6. 对单 chunk 与多 chunk 单元打规则标签与规则分数

说明：

1. 文档总结可参考 `yourbench` 的分块总结再合并思路
2. 但调度用标签与分数应打在最终 question chunk 上，而不是总结阶段的临时 chunk 上
3. `single_chunk_pool` 与 `multi_chunk_pool` 在主题内部多轮复用

## 9. 规则标签与分数

### 9.1 标签

建议至少维护以下规则标签：

1. `definition`
2. `comparison`
3. `causal`
4. `mechanism`
5. `timeline`
6. `numeric_dense`
7. `entity_dense`

### 9.2 分数

每个证据单元维护：

1. `mcq_score`
2. `qa_score`
3. `hard_score`

分数目标不是判断真值，而是支持排序与调度。

### 9.3 规则特征

可用特征包括：

1. `definition_signal`
2. `enumeration_signal`
3. `comparison_signal`
4. `causal_signal`
5. `mechanism_signal`
6. `conditional_signal`
7. `numeric_signal`
8. `entity_density_signal`
9. `summary_alignment_signal`
10. `ambiguity_penalty`
11. `usage_penalty`

### 9.4 基础信号计算

第一版不使用 LLM 对 chunk 打分，而是直接从 `chunk text + document_summary` 中提取规则特征。

建议计算方式：

1. `definition_signal`
   - 命中 `is a`、`refers to`、`defined as`、`means` 等定义模式
   - 命中次数归一化到 `0~1`
2. `enumeration_signal`
   - 命中 `first`、`second`、`includes`、`consists of`、列表符号等结构
   - 命中越多分越高
3. `comparison_signal`
   - 命中 `compared to`、`unlike`、`whereas`、`in contrast` 等比较模式
4. `causal_signal`
   - 命中 `because`、`therefore`、`led to`、`resulted in`、`due to` 等因果模式
5. `mechanism_signal`
   - 命中 `process`、`mechanism`、`works by`、`through which` 等机制解释模式
6. `conditional_signal`
   - 命中 `if`、`unless`、`under`、`depends on` 等条件模式
7. `numeric_signal`
   - 统计数字、年份、比例、百分比、区间表达式密度
8. `entity_density_signal`
   - 统计专有名词、多实体共现、名词短语密度
9. `summary_alignment_signal`
   - 计算 chunk 与 `document_summary` 的词重合度或轻量相似度
   - 可采用 Jaccard 或 BM25-lite 近似
10. `length_signal`
   - 基于 token 数与句子数计算
   - 过短或过长都降权，中间区间得分最高
11. `ambiguity_penalty`
   - 代词比例高、上下文依赖强、残句明显时提高惩罚值
12. `usage_penalty`
   - 基于证据单元已使用次数计算
   - 使用次数越多惩罚越高

第一版目标不是获得语义“真分数”，而是生成可用于排序的稳定近似分数。

### 9.5 分数组合思路

推荐组合方式：

```python
mcq_score =
  0.25 * definition_signal +
  0.20 * enumeration_signal +
  0.20 * numeric_signal +
  0.15 * summary_alignment_signal +
  0.10 * length_signal +
  0.10 * entity_density_signal -
  0.15 * ambiguity_penalty
```

```python
qa_score =
  0.25 * causal_signal +
  0.25 * mechanism_signal +
  0.20 * summary_alignment_signal +
  0.15 * entity_density_signal +
  0.10 * conditional_signal +
  0.05 * comparison_signal -
  0.10 * ambiguity_penalty
```

```python
hard_score =
  0.22 * causal_signal +
  0.20 * comparison_signal +
  0.18 * mechanism_signal +
  0.12 * conditional_signal +
  0.10 * entity_density_signal +
  0.08 * numeric_signal +
  0.10 * summary_alignment_signal -
  0.10 * ambiguity_penalty -
  0.08 * usage_penalty
```

### 9.6 分数使用方式

分数使用原则如下：

1. `mcq_score` 用于选择更适合 `multiple_choice` 的证据单元
2. `qa_score` 用于选择更适合 `qa` 的证据单元
3. `hard_score` 用于筛选更适合 `hard` 题的证据单元
4. 分数主要用于排序和加权采样，不作为硬阈值
5. 运行中可叠加 `EvidenceStats` 的经验统计对排序进行轻量修正

## 10. NextStepPlan

### 10.1 作用

`NextStepPlan` 用于在每轮生成结束后，基于当前状态自动决定下一轮动作。

它不负责改变正式 `topic` 集合，而是负责：

1. 是否继续当前主题生成
2. 是否扩充资料
3. 是否提高多 chunk 比例
4. 是否启用 hardening
5. 是否启用题目复杂化
6. 是否切换主题
7. 是否将当前主题标记为 `deferred`

### 10.2 结构

```python
class NextStepPlan(BaseModel):
    topic: str
    action: str
    target_gap: str | None
    retrieval_expansion_queries: list[str] = []
    sampling_mode: str | None = None
    prefer_multi_chunk: bool = False
    hardening_enabled: bool = False
    complexity_evolution_enabled: bool = False
    additional_instructions: str = ""
    reason: str
```

### 10.3 动作集合

第一版建议仅允许以下动作：

1. `continue_generation`
2. `expand_retrieval`
3. `increase_multi_chunk_ratio`
4. `enable_hardening`
5. `enable_complexity_evolution`
6. `switch_topic`
7. `defer_topic`
8. `global_backfill`

### 10.4 生成方式

`NextStepPlan` 不应通过自然语言计划解析得到。

推荐方式是：

1. 代码先根据硬约束生成“允许动作集合”
2. 代码提供当前状态摘要与主缺口
3. LLM 在受限动作空间内输出结构化 JSON
4. 代码对 JSON 再做 schema 校验与约束检查

不推荐方式：

1. 让 LLM 先输出一段自然语言计划
2. 再从自然语言中解析出动作

原因：

1. 成本更高
2. 稳定性更差
3. 调试更困难
4. 更容易绕过轮次与配额约束

### 10.5 LLM 与代码的职责划分

代码负责：

1. 维护 `TopicState`
2. 维护 `EvidenceStats`
3. 强制 `max_rounds_per_topic`
4. 强制 `max_total_rounds`
5. 过滤不合法动作
6. 更新计数与状态

LLM 负责：

1. 在允许动作集合中选择下一步动作
2. 选择是否扩检索
3. 生成 `retrieval_expansion_queries`
4. 生成 hardening 的附加要求
5. 生成复杂化附加要求
6. 给出结构化 `reason`

### 10.6 检索扩充的位置

本设计不采用 AutoBencher 那种基于评测结果重写正式 topic 的方式。

取而代之的是：

1. 正式 `topic` 由上游 `PlannerAgent` 定义
2. `QuestionGeneratorAgent` 在主题内部多轮循环中维护 `retrieval_frontier`
3. 当证据池不足以补齐主缺口时，通过 `NextStepPlan(action="expand_retrieval")` 扩充资料

也就是说，动态变化的是检索前沿，而不是正式主题本身。

## 11. 主题内轮次循环

每轮固定做以下步骤：

1. 查看 `remaining_counts`
2. 识别当前主题主缺口
3. 选择采样模式
4. 生成 `GenerationBatch`
5. 调用模型生成候选题
6. 做轻量格式过滤
7. 更新 `TopicState`、证据使用状态与 `EvidenceStats`
8. 生成 `NextStepPlan`
9. 根据 `NextStepPlan` 判断继续当前主题、扩资料、切下一个主题或标记 `deferred`

## 12. 采样模式

### 12.1 broad_exploration_sampling

用途：

1. 主题第一轮
2. 主题内部尚未出现明显主缺口时

特点：

1. 进行广覆盖加权采样，不是纯随机
2. 优先低使用、高 summary 对齐、高基础分数的证据单元
3. 目标是快速摸清主题内部的证据结构

### 12.2 gap_driven_sampling

用途：

1. 主题内部已经出现明确主缺口时

特点：

1. 缺 `multiple_choice` 时提高 `mcq_score` 权重
2. 缺 `qa` 时提高 `qa_score` 权重
3. 缺 `hard` 时提高 `hard_score` 权重
4. hard 不足时优先提高 `multi_chunks` 占比

## 13. 难题策略

生成 hard 题不能简化成“随机 chunk + hard prompt”。

正确顺序：

1. 先选择更适合 hard 的证据单元
2. 再在 prompt 中追加 hard-oriented 附加要求
3. 若仍不足，再从多余的 medium 候选题中做复杂化
4. 若仍不足，再通过下一轮提高多 chunk 占比或扩检索

该顺序优于“直接将 medium prompt 改成 hard prompt”，因为证据本身的复杂性是 hard 题质量的前提。

## 14. GenerationBatch 生成规则

### 14.1 确定目标缺口

从当前主题的 `remaining_counts` 中找出主缺口。

优先级：

1. `hard` 优先
2. 剩余数量大的优先
3. 其次考虑当前主题的 `mode` 平衡

第一版建议每轮主要补前 1 到 2 个主缺口。

### 14.2 选择证据类型

根据 `EvidenceStats` 决定优先使用：

1. `single_chunks`
2. `multi_chunks`
3. 或少量混合

经验规则：

1. `easy` 优先单 chunk
2. `medium` 以单 chunk 为主，必要时补少量多 chunk
3. `hard` 优先查看多 chunk 是否有更高有效产出；若是，则优先多 chunk

### 14.3 使用冗余而非精算

不追求精确估算每批应抽取多少证据单元，而采用带 buffer 的过量生成策略。

示例：

1. 若 `remaining_count <= 2`
   - `requested_min_questions = remaining_count + 1`
   - `requested_target_questions = remaining_count + 2`
2. 若 `remaining_count <= 5`
   - `requested_min_questions = remaining_count + 1`
   - `requested_target_questions = remaining_count + 3`
3. 否则
   - `requested_min_questions = remaining_count + 2`
   - `requested_target_questions = remaining_count + 4`

证据单元列表同样采用富余策略，而不是精确计算每个 chunk 理应产出多少题。

## 15. Prompt 策略

### 15.1 主模板

仅维护两套主模板：

1. `multiple_choice`
2. `qa`

### 15.2 难度通过附加要求调节

建议：

1. `easy`
   - 强调单 chunk、直接可回答、不要复杂推断
2. `medium`
   - 强调同一证据单元中的多事实整合
3. `hard`
   - 强调比较、因果、机制、约束、非显式推断

这样可以最大限度复用 `yourbench` 风格 prompt，只在 `additional_instructions` 上进行差异化。

## 16. 轻量过滤规则

生成器内部只做结构级过滤，不做正式验证。

过滤条件：

1. JSON 解析失败
2. 缺字段
3. `question_mode` 不符
4. 难度字段非法
5. `citation` 为空
6. 题目为空
7. 答案为空
8. 若为 `multiple_choice`，则选项数量不对或答案格式非法

## 17. 状态更新

每轮生成后执行：

1. 统计本批候选题数
2. 统计过滤后有效题数
3. 更新 `TopicState.completed_counts`
4. 更新 `TopicState.remaining_counts`
5. 更新证据单元 `usage_count`
6. 更新 `EvidenceStats`
7. `TopicState.current_round += 1`

## 18. 主题退出条件

当前主题出现以下情况之一时退出：

1. 当前主题初始分配目标已达标，标记为 `completed`
2. 已达到 `max_rounds_per_topic` 仍未达标，标记为 `deferred`

`deferred` 只表示该主题在局部轮次限制内未完成，不表示全局补题时必须优先回到该主题。

## 19. 全局补题阶段

所有主题结束后，若全局目标仍未满足，则进入全局补题阶段。

规则：

1. 优先看全局 `mode × difficulty` 缺口
2. 不强制回补原主题
3. 优先从最容易补当前全局缺口的主题继续生成
4. 达到 `max_total_rounds` 仍未达标，则返回当前最好结果与缺口报告

## 20. 输出与产物

建议生成以下 artifact：

1. `source_documents.jsonl`
2. `document_summaries.jsonl`
3. `single_chunk_pool.jsonl`
4. `multi_chunk_pool.jsonl`
5. `candidate_questions.jsonl`
6. `accepted_questions.jsonl`
7. `topic_states.json`
8. `evidence_stats.json`
9. `generation_report.json`

## 21. 与 yourbench 的关系

本设计参考 `yourbench` 的以下思想：

1. 文档总结阶段先于 question generation
2. question generation 使用 `document_summary + chunk` 作为上下文
3. single-shot 与 multi-hop 分别处理不同粒度的证据单元
4. prompt 层采用 mode 驱动而非复杂类型驱动

本设计相较 `yourbench` 新增的核心能力：

1. 显式 `TopicState`
2. 显式单主题轮次状态机
3. 显式 `single_chunk_pool / multi_chunk_pool`
4. 基于缺口的证据调度
5. 基于经验统计的证据类型选择

## 22. 最终结论

`QuestionGeneratorAgent` 的推荐实现形态不是简单流水线，而是：

1. 上游目标驱动
2. 主题串行推进
3. 主题内部多轮状态更新
4. 基于单 chunk 与多 chunk 证据池的缺口驱动生成
5. 基于轻量统计与轻量规则的低成本调度

该方案具备以下优点：

1. 比固定流水线更能体现“智能体”的调度属性
2. 比重型多智能体方案更便宜、更稳
3. 与 `yourbench` 的现有 prompt 与文档处理思路兼容
4. 便于后续接入独立 `QuestionValidatorAgent`
