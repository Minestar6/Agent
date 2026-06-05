# QuestionValidatorAgent 技术设计

日期：2026-06-03

## 1. 目标

实现一个独立的 `QuestionValidatorAgent`，接收题目生成智能体输出的候选题集合，按固定顺序执行三阶段质量验证：

1. 引用验证
2. LLM 验证
3. 分组整编 / 去重 / 加权采样

输出一个带完整验证元数据、可追踪、可下游消费的高质量题目集合。

该智能体是下游筛选与重排器，不负责生成新题，不负责修题，不负责重新检索证据。

## 2. 推荐执行顺序

推荐顺序：

1. `Citation Validation`
2. `LLM Validation`
3. `Grouping + Dedup + Weighted Selection`

原因：

1. 引用验证是硬门槛，失败题无需进入后续昂贵阶段。
2. LLM 验证用于做语义质量判断，前提是题目至少可追溯。
3. 分组整编和最终去重应基于“已通过验证”的题，而不是原始脏集合。

可选优化版本：

1. 引用验证
2. 轻量近重复去重
3. LLM 验证
4. 分组整编
5. 最终去重与加权采样

MVP 可以先按主顺序实现。

## 3. 非目标

第一版不做：

1. 自动改写失败题
2. 自动补题
3. 自动重检索
4. 人工审核工作流
5. 多轮 validator self-reflection
6. 多模型投票式验证

## 4. 与现有系统的关系

当前题目生成链已经产出这些关键字段：

1. `question`
2. `answer`
3. `question_mode`
4. `citations`
5. `document_id`
6. `chunk_ids`
7. `required_capability`
8. `estimated_difficulty`
9. `topic`

质量验证智能体应尽量复用这些字段语义，而不是重新定义一套题目格式。

### 4.1 当前 BenchForge 代码接缝

为了让实现方直接接到现有仓库，而不是重新设计一套链路，`QuestionValidatorAgent` 需要和当前 `benchforge` 的以下模块对齐：

1. 题目生成主链
   - `benchforge/agents/qa_agent/executor.py`
   - `benchforge/agents/question_generator/modules/generator.py`
2. 证据与摘要链
   - `benchforge/agents/question_generator/modules/evidence_manager.py`
3. 过滤逻辑
   - `benchforge/utils/filter.py`
4. 模型调用与通用追踪
   - `benchforge/models/base.py`
   - `benchforge/models/openai_client.py`
   - `benchforge/models/local_client.py`
   - `benchforge/models/fake.py`

需要明确的现状约束：

1. 题目生成阶段已经支持 `llm_call_id` 落盘和 `llm_calls.jsonl` 记录。
2. `qa_agent` 的运行结果里已经有 `raw_count`、`filtered_count`、`filter_rejected`、`filter_failures` 等最小诊断字段。
3. 因此验证智能体不应再发明另一套 LLM 追踪机制，而应复用现有 `llm_call_id + llm_calls.jsonl` 方案。

### 4.2 与运行目录的集成原则

验证智能体应被视为同一个 `task_id/run_id` 下的后处理阶段，而不是另起一个孤立运行单元。

推荐目录约定：

```text
runs/{task_id}/{run_id}/
├── llm_calls.jsonl
├── qa/
├── multiple_choice/
└── validation/
```

实现要求：

1. 验证智能体继续向同一个 `runs/{task_id}/{run_id}/llm_calls.jsonl` 追加 LLM 调用记录。
2. 验证产物统一写到 `runs/{task_id}/{run_id}/validation/`。
3. 验证智能体不得复制一份新的 `llm_calls.jsonl` 到 `validation/` 子目录，避免同一 run 内调用轨迹分裂。

### 4.3 `run_id` 与 `validation_session_id`

为避免验证阶段和题目生成阶段断链，ID 规则应明确如下：

1. `task_id` 表示整次 benchmark 任务。
2. `run_id` 表示该任务下的一次主运行。
3. 如果验证智能体是接在题目生成之后运行，则必须继承上游的 `task_id/run_id`。
4. 不应在这种链路里重新生成新的主 `run_id`，否则：
   - `llm_calls.jsonl` 无法连续追踪
   - `chunk_index.jsonl` 无法稳定复用
   - `validation/` 结果会和原候选题 run 脱节
5. 验证智能体需要有自己的 `validation_session_id`，用于标识“同一个 run 下的第几次验证执行”。
6. `validation_session_id` 可以由调用方显式传入；若未传入，则由验证智能体自行生成。
7. 只有在验证智能体被独立运行、且没有上游运行上下文时，才自动生成新的 `run_id`。

推荐格式：

1. `run_id = run_YYYYMMDD_HHMMSS_xxxx`
2. `validation_session_id = validation_YYYYMMDD_HHMMSS_xxxx`

### 4.4 为什么这里是“智能体”而不是普通 pipeline

本设计将验证阶段定义为受限执行智能体，而不是一组无状态函数。

它的“智能体性”体现在：

1. 有明确输入边界
   - `blueprint`
   - `candidates`
   - `config`
   - `model_client`
2. 有显式内部状态
   - `ValidationRunState`
   - 逐题状态流转
3. 有有限但明确的决策点
   - 是否进入下一阶段
   - 是否触发 LLM 重试
   - 是否进入 `reserve`
   - 是否进入最终 `selected`
4. 有自己的执行会话标识
   - `validation_session_id`
5. 有可追踪记忆
   - `question_id`
   - `llm_call_id`
   - `final_status`
   - `failed_reasons`

这个智能体不会修改全局蓝图，也不会自主生成新题，它的自治边界仅限于验证、筛选和状态推进。

## 5. 输入与输出

### 5.1 输入

建议支持两类输入源：

1. `qa_agent` 输出
   - `runs/{task_id}/{run_id}/{mode}/candidate_pool.json`
2. `question_generator` 输出
   - `runs/{task_id}/{run_id}/accepted_questions.jsonl`

第一步先做一个输入归一化层，把不同来源统一成内部 `QuestionCandidate`。

### 5.2 内部标准输入结构

建议定义：

```python
class QuestionCandidate(BaseModel):
    question_id: str
    task_id: str
    run_id: str
    topic: str
    question: str
    answer: str
    question_mode: str
    question_type: str = ""
    required_capability: str = ""
    estimated_difficulty: str | int | None = None
    citations: list[Any] = Field(default_factory=list)
    document_id: str = ""
    chunk_ids: list[str] = Field(default_factory=list)
    chunks: list[str] = Field(default_factory=list)
    generation_metadata: dict[str, Any] = Field(default_factory=dict)
```

说明：

1. `chunks` 是原始 chunk 文本列表，若存在可直接用于引用验证。
2. `chunk_ids` 是真相源。
3. `document_id` 可为空，但 `chunk_ids` 不应为空。
4. `question_id` 若上游没有，validator 入口补发稳定 id。
5. `question_mode` 表示高层输出模式，例如 `qa`、`multiple_choice`。
6. `question_type` 表示细粒度题型或推理类型，例如 `factoid`、`comparison`、`multi_hop`；它不参与 MVP 第三阶段分桶。

### 5.2.1 chunk 文本回查规则

`QuestionCandidate.chunks` 可以为空，但 validator 不允许在缺少证据文本的情况下继续 Stage 1 或 Stage 2。

规范要求：

1. 若 `candidate.chunks` 非空，直接使用。
2. 若 `candidate.chunks` 为空，则必须使用 `candidate.chunk_ids` 从 `chunk_index.jsonl` 回查。
3. 推荐标准路径：
   - `runs/{task_id}/{run_id}/chunk_index.jsonl`
4. `chunk_index.jsonl` 每条建议至少包含：
   - `chunk_id`
   - `document_id`
   - `text`
5. normalizer 负责在进入 Stage 1 前完成 chunk hydrate。
6. 若 `chunk_ids` 无法解析出任何文本，则该题直接标记：
   - `final_status = rejected_citation`
   - failure reason: `missing_source_chunks`

### 5.3 输出

输出应分两层：

1. 逐题验证结果
2. 最终保留题集合

建议输出文件：

```text
runs/{task_id}/{run_id}/validation/
├── normalized_candidates.jsonl
├── citation_validation.jsonl
├── llm_validation.jsonl
├── clustering.json
├── deduplication.json
├── weighted_selection.json
├── validated_questions.jsonl
└── validation_report.json
```

## 6. 三阶段架构

### 6.1 Stage 1: 引用验证

职责：

1. 判断题目引用是否真实落在来源 chunk 中
2. 计算 citation support score
3. 给出 pass / fail / warning

输入：

1. `QuestionCandidate`
2. 题目关联的 chunk 文本
3. citation policy config

输出：

```python
class CitationValidationResult(BaseModel):
    question_id: str
    passed: bool
    answer_citation_score: float
    chunk_citation_score: float
    citation_score: float
    citation_count: int
    matched_citation_count: int
    failed_reasons: list[str]
    matched_spans: list[dict[str, Any]] = Field(default_factory=list)
```

### 6.2 Stage 2: LLM 验证

职责：

1. 判断题目是否符合蓝图要求
2. 判断问题是否清晰、可答、无歧义、答案与问题匹配
3. 输出结构化评分和 rejection reason

输入：

1. 仅通过引用验证的题
2. validator prompt 文件
3. blueprint constraints

输出：

```python
class LLMValidationResult(BaseModel):
    question_id: str
    passed: bool
    overall_score: float
    dimensions: dict[str, float]
    failed_reasons: list[str]
    judge_summary: str
    llm_call_id: str | None = None
    attempt_count: int = 1
    latency_ms: int | None = None
    error: str | None = None
```

### 6.3 Stage 3: 分组整编 / 去重 / 加权选择

职责：

1. 对通过前两阶段的题按 blueprint 维度做分组整编
2. 去除近重复
3. 按 blueprint 分布做加权采样
4. 产出最终集合

输入：

1. 通过题集合
2. blueprint 分布约束
3. grouping / selection config

输出：

```python
class FinalSelectionResult(BaseModel):
    selected_question_ids: list[str]
    dropped_as_duplicate: list[str]
    dropped_as_overquota: list[str]
    group_assignments: dict[str, str]
    sampling_weights: dict[str, float]
```

其中：

1. `sampling_weights` 的 key 为 `question_id`
2. value 为该题在最终选择阶段使用的 `final_weight`
3. 如果实现方认为该字段与 `ValidatedQuestionRecord.final_weight` 冗余，也可以在实现时省略它，只保留逐题 `final_weight`

## 7. Stage 1 详细设计：引用验证

### 7.1 核心策略

Phase 1 直接采用 `yourbench` 的 `citation_score_filtering` 方案，避免在 citation scoring 上再发明一套算法。

建议验证逻辑：

1. 题目必须有 `citations`
2. 对每条 citation，分别计算：
   - 与 source chunks 的最佳模糊匹配分数
   - 与 answer 的模糊匹配分数
3. 聚合得到：
   - `chunk_citation_score`
   - `answer_citation_score`
   - `citation_score`
4. 若低于阈值则失败

### 7.2 规范化规则

为了尽量贴近 `yourbench`，Phase 1 不引入复杂的句子级或 token 级标准化，只做轻量清洗：

1. `strip()` 去掉首尾空白
2. collapse whitespace
3. 保持 citation、chunk、answer 的原始文本顺序与内容

实际匹配函数直接复用 `yourbench` 的核心思路：

```python
from thefuzz import fuzz

ratio = fuzz.partial_ratio(a, b) / 100.0
```

### 7.3 评分建议

建议直接复用 `yourbench` 的线性组合思路：

1. `chunk_citation_score`
2. `answer_citation_score`

示意：

```python
citation_score = alpha * chunk_citation_score + beta * answer_citation_score
```

建议默认：

1. `alpha = 0.7`
2. `beta = 0.3`

明确计算定义：

1. `total_citation_count = len(citations)`
2. 对每条 citation 计算：
   - `chunk_score_i = max(fuzz.partial_ratio(citation, chunk) / 100.0 for chunk in chunks)`
   - 若 `chunks` 为空，则 `chunk_score_i = 0.0`
   - `answer_score_i = fuzz.partial_ratio(citation, answer) / 100.0`
   - 若 `answer` 为空，则 `answer_score_i = 0.0`
3. `chunk_citation_score = mean(chunk_score_i for each citation)`
4. `answer_citation_score = mean(answer_score_i for each citation)`
5. `citation_score = alpha * chunk_citation_score + beta * answer_citation_score`
6. `matched_citation_count = count(chunk_score_i >= citation_match_threshold)`

建议默认：

1. `citation_match_threshold = 0.8`
2. `chunk_citation_score`、`answer_citation_score`、`citation_score` 都限制在 `[0, 1]`

这样定义后：

1. `chunk_citation_score` 反映 citation 与来源 chunks 的整体贴合程度
2. `answer_citation_score` 反映 citation 与答案文本的一致性
3. `citation_score` 与 `yourbench` 的计算逻辑保持一致，只是归一化到 `[0, 1]`

### 7.4 判定规则

建议：

1. `citations` 为空：直接 fail
2. `matched_citation_count == 0`：直接 fail
3. `citation_score < min_citation_score`：fail
4. 否则 pass

建议配置：

```yaml
citation_validation:
  enabled: true
  min_citation_score: 0.65
  alpha: 0.7
  beta: 0.3
  citation_match_threshold: 0.8
  require_all_citations_supported: false
```

### 7.5 输出保留的诊断信息

每题至少记录：

1. 原始 citations
2. `answer_citation_score`
3. `chunk_citation_score`
4. 哪几条 citation 达到 `citation_match_threshold`
5. score
6. failure reasons

这样后续人工排查不需要重跑。

## 8. Stage 2 详细设计：LLM 验证

### 8.1 目的

这里不是再做引用真实性判断，而是检查：

1. 问题是否清晰
2. 答案是否正确且与问题匹配
3. 问题是否确实可由证据回答
4. 是否符合题型要求
5. 是否满足蓝图目标

### 8.2 LLM 输入

建议每题单独验证，一题一调，便于追踪和复核。

输入 prompt 组成：

1. `system prompt`: validator role + 输出 schema
2. `user prompt`: 单题信息 + source evidence + blueprint constraints

输入内容建议包含：

1. `topic`
2. `question_mode`
3. `question`
4. `answer`
5. `question_type`
6. `required_capability`
7. `estimated_difficulty`
8. `citations`
9. 对应 `chunks`
10. 当前 blueprint 对该题的约束摘要

### 8.3 输出 schema

强制 LLM 返回 JSON：

```json
{
  "passed": true,
  "overall_score": 0.87,
  "dimensions": {
    "clarity": 0.9,
    "answerability": 0.85,
    "faithfulness": 0.9,
    "difficulty_alignment": 0.8,
    "mode_alignment": 0.9
  },
  "failed_reasons": [],
  "judge_summary": "..."
}
```

### 8.4 判定维度

建议固定 5 维：

1. `clarity`
2. `answerability`
3. `faithfulness`
4. `difficulty_alignment`
5. `mode_alignment`

可选增加：

1. `blueprint_relevance`
2. `interestingness`

MVP 不建议太多维度。

### 8.5 判定规则

建议：

1. 任一关键维度低于 `hard_floor` 直接 fail
2. `overall_score < min_overall_score` fail
3. 否则 pass

示例配置：

```yaml
llm_validation:
  enabled: true
  model: gpt-4o-mini
  temperature: 0.0
  max_tokens: 800
  min_overall_score: 0.75
  max_concurrency: 8
  max_retries: 2
  hard_floor:
    clarity: 0.6
    answerability: 0.7
    faithfulness: 0.7
    mode_alignment: 0.7
```

### 8.6 可观测性

这里应强制记录：

1. `llm_call_id`
2. prompt 文件名
3. 原始 response
4. 解析后的结构结果

并复用当前已实现的：

1. `runs/{task_id}/{run_id}/llm_calls.jsonl`

### 8.6.1 并发与重试策略

LLM 验证虽然是一题一调，但实现上不应串行执行。

推荐实现：

1. 使用 `asyncio.gather(...)` 并发调度单题验证任务
2. 使用 `asyncio.Semaphore(max_concurrency)` 限制最大并发
3. `max_concurrency` 默认建议 `8`
4. `max_retries` 默认建议 `2`
5. 仅对以下错误重试：
   - timeout
   - rate limit / `429`
   - 临时网络错误
6. 重试使用指数退避，例如 `1s -> 2s`
7. 若底层 `model_client.complete()` 是同步方法，则使用 `asyncio.to_thread()` 包装

每题验证的最终结果应记录：

1. `attempt_count`
2. `latency_ms`
3. `llm_call_id`
4. `error` 或结构化评分结果

### 8.7 `llm_call_id` 关联规则

这一条是实现时必须遵守的关联契约，否则后续无法从失败题目精确反查 prompt。

规则如下：

1. 每次单题 LLM 验证调用都由 `model_client.complete()` 生成唯一 `llm_call_id`。
2. 该次调用的 `request`、`response`、`error` 统一写入 `runs/{task_id}/{run_id}/llm_calls.jsonl`。
3. `LLMValidationResult` 必须保存对应 `llm_call_id`。
4. `validated_questions.jsonl` 中每条题目最终记录也必须包含该 `llm_call_id`。
5. 若单题触发多次验证调用，例如重试或二次裁判，需改为：
   - `primary_llm_call_id`
   - `llm_call_ids: list[str]`

排障时的标准反查路径：

1. 在 `validated_questions.jsonl` 或 `llm_validation.jsonl` 找到失败题目的 `llm_call_id`
2. 到同 run 的 `llm_calls.jsonl` 中按 `llm_call_id` 精确匹配
3. 查看该次 `messages` 与原始 `response`

这一契约比依赖 `topic/mode/round` 模糊匹配更稳，也天然支持并发调用。

## 9. Stage 3 详细设计：分组整编 / 去重 / 加权选择

### 9.1 输入集合

只处理通过：

1. 引用验证
2. LLM 验证

的题目。

### 9.2 设计基准：以 yourbench 思路为主

这一阶段应参考 `yourbench` 的实际做法，而不是默认上一个通用 embedding 聚类器。

`yourbench` 更接近以下思路：

1. 先按数据结构和任务模式进行分组
2. 对每组做采样和组合构造
3. 对生成结果做规则级去重
4. 最后形成面向下游评测的稳定子集

相关参考位置：

1. `reference/code/yourbench/yourbench/utils/chunking_utils.py`
2. `reference/code/yourbench/yourbench/utils/cross_document_utils.py`
3. `reference/code/yourbench/yourbench/utils/parsing_engine.py`
4. `reference/code/yourbench/yourbench/pipeline/question_generation/_core.py`

因此，本文这里所说的“聚类”，在 MVP 里更准确应理解为：

1. 基于 `question_mode` 和 `estimated_difficulty` 的分桶
2. 桶内聚类或近重复去重
3. 桶间按蓝图配额进行保留

而不是默认要求无监督语义聚类。

### 9.3 分组目标

分组整编的目标不是学术展示，而是为了最终控制集合分布：

1. 难度分布
2. 题型分布
3. 重复度

### 9.4 分组信号

MVP 默认只使用两层主键：

1. `question_mode`
2. `estimated_difficulty`

建议分组顺序：

1. 先按 `question_mode`
2. mode 内再按 `estimated_difficulty`

如果 `estimated_difficulty` 缺失，可回退到：

1. `easy`
2. `medium`
3. `hard`
4. `unknown`

### 9.5 与 yourbench 对齐的实现方式

建议实现顺序：

1. 先按 `question_mode` 和 `difficulty` 做规则分桶
2. 在每个桶内做 exact duplicate 去重
3. 对每个桶内剩余题做语义聚类或近重复压缩
4. 再按每个桶的 blueprint 配额做保留

也就是说：

1. `mode + difficulty bucket` 是默认骨架
2. `semantic clustering` 是桶内去重手段

### 9.6 去重策略

分两层：

1. 规则去重
   - exact normalized question text
   - exact `(question, answer)` pair
2. 语义近重复
   - embedding similarity > threshold

建议阈值：

1. `duplicate_similarity_threshold = 0.92`

这里和 `yourbench` 的 `_remove_duplicate_questions()` 思路一致，第一优先级是稳定的规则去重；聚类只用于桶内压缩近重复题。

### 9.7 加权选择

目标是按 blueprint 目标保留最终题集。

建议权重由以下项线性组合：

1. citation score
2. llm overall score

示意：

```python
final_weight = (
    w1 * citation_score
    + w2 * llm_score
)
```

建议默认：

```yaml
selection:
  score_weights:
    citation: 0.45
    llm: 0.55
```

这里明确采用静态排序语义，而不是 greedy 动态重算：

1. 在每个 `mode + difficulty` 桶内，先为所有候选题计算一次 `final_weight`
2. 再按 `final_weight` 降序排序
3. 最后按该桶的 `target_count` 截取保留

因此：

1. `final_weight` 不依赖动态变化的 `current_selected_count`
2. bucket 配额由截取逻辑保证，而不是通过 bonus 间接表达

### 9.8 最终采样逻辑

建议：

1. 先按 mode 分桶
2. mode 内按 difficulty 分桶
3. 每个桶内先去重再做聚类压缩
4. 每个桶按目标数量保留
5. 超额时按最终权重降序保留

### 9.9 可选增强：语义聚类

如果后续确实需要更强的多样性控制，可以在上述主链之上，再额外增加：

1. embedding model
2. cosine similarity
3. agglomerative clustering 或 HDBSCAN

但第一版里，它只需要服务于“桶内近重复压缩”，不需要演化成全局复杂聚类器。

## 10. Blueprint 结合方式

质量验证智能体必须读取 blueprint，而不是只做“质量好坏”判断。

至少要读这些字段：

1. `topics`
2. `modes`
3. 每 mode 的 `count`
4. 每 mode 的 `difficulty_distribution`

分组整编与最终采样时使用 blueprint 做配额控制。

建议定义：

```python
class ModeCfg(BaseModel):
    count: int
    difficulty_distribution: dict[str, int]

class ValidationBlueprintView(BaseModel):
    topics: list[str]
    modes: dict[str, ModeCfg]
```

## 11. 内部状态与数据结构

建议核心状态对象：

```python
class ValidationRunState(BaseModel):
    task_id: str
    run_id: str
    validation_session_id: str
    total_candidates: int
    citation_passed: int = 0
    llm_passed: int = 0
    final_selected: int = 0
    failed_by_stage: dict[str, int] = Field(default_factory=dict)
```

建议再定义一层智能体执行结果：

```python
class ValidationTaskResult(BaseModel):
    task_id: str
    run_id: str
    validation_session_id: str
    report_path: str
    selected_question_ids: list[str]
    failed_by_stage: dict[str, int]
```

逐题最终结构：

```python
class ValidatedQuestionRecord(BaseModel):
    question_id: str
    candidate: QuestionCandidate
    citation_validation: CitationValidationResult | None = None
    llm_validation: LLMValidationResult | None = None
    group_id: str | None = None
    cluster_id: str | None = None
    duplicate_of: str | None = None
    final_weight: float | None = None
    final_status: str
```

`final_status` 建议枚举值：

1. `rejected_citation`
2. `rejected_llm`
3. `validator_error`
4. `duplicate`
5. `selected`
6. `reserve`

其中：

1. `reserve` 表示该题已通过 citation validation 和 llm validation，也未被 dedup 淘汰
2. 但它因所在 bucket 超配额而未进入最终 `selected`
3. `reserve` 是候补池，可在后续 `selected` 被移除时按 `final_weight` 递补
4. `validator_error` 表示 LLM 验证阶段调用失败、重试耗尽或响应不可解析

### 11.1 逐题状态机

每道题在验证智能体内部应经历显式状态流转。

建议初始状态：

1. `pending_validation`

状态转移规则：

1. `pending_validation -> rejected_citation`
   - citation validation 失败
2. `pending_validation -> validator_error`
   - LLM 验证调用失败、重试耗尽或响应不可解析
3. `pending_validation -> rejected_llm`
   - LLM 成功返回，但判题不通过
4. `pending_validation -> duplicate`
   - 通过前两阶段，但在 dedup 阶段被淘汰
5. `pending_validation -> reserve`
   - 通过前两阶段，也未被 dedup 淘汰，但因 bucket 超配额未入选
6. `pending_validation -> selected`
   - 通过前两阶段，且最终入选

注意：

1. `pending_validation` 是内部过程状态，不属于最终落盘的 `final_status` 枚举。
2. `reserve` 和 `selected` 都表示题目质量达标，只是配额位置不同。

## 12. 目录结构建议

```text
benchforge/
  agents/
    verify_agent/
      __init__.py
      agent.py
      schema.py
      config_loader.py
      normalizer.py
      citation_validator.py
      llm_validator.py
      clusterer.py
      deduplicator.py
      selector.py
      storage.py
  prompts/
    verify_agent/
      quality_system_prompt.md
      quality_user_prompt.md
  config/
    verify_agent.yaml
  test/
    test_verify_agent_units.py
    test_verify_agent_e2e.py
```

如果实现方希望先做最小版本，可以先只落这 5 个文件：

```text
benchforge/
  agents/
    verify_agent/
      agent.py
      schema.py
      normalizer.py
      citation_validator.py
      llm_validator.py
```

其余 `clusterer.py`、`deduplicator.py`、`selector.py`、`storage.py` 可以在第二阶段补齐。

## 13. 执行主流程

建议主流程：

```python
async def run_verify_agent(
    input_paths: list[str],
    blueprint: Any,
    config: Any,
    model_client: Any | None = None,
) -> dict:
    candidates = load_and_normalize_candidates(input_paths)

    citation_results = run_citation_validation(candidates, config.citation_validation)

    citation_passed = [q for q in candidates if citation_results[q.question_id].passed]

    # Internally uses asyncio.gather + semaphore-limited concurrency.
    llm_results = await run_llm_validation(
        citation_passed,
        blueprint=blueprint,
        config=config.llm_validation,
        model_client=model_client,
    )

    llm_passed = [q for q in citation_passed if llm_results[q.question_id].passed]

    grouping_result = run_grouping(llm_passed, config.grouping)

    dedup_result = run_deduplication(llm_passed, grouping_result, config.deduplication)

    final_selection = run_weighted_selection(
        questions=llm_passed,
        blueprint=blueprint,
        citation_results=citation_results,
        llm_results=llm_results,
        grouping_result=grouping_result,
        dedup_result=dedup_result,
        config=config.selection,
    )

    save_outputs(...)
    return validation_report
```

这里的契约需要明确：

1. 传入 `run_weighted_selection()` 的 `questions=llm_passed` 仍然可能包含重复题
2. `run_weighted_selection()` 内部必须先根据 `dedup_result.dropped_as_duplicate` 过滤掉重复题
3. 只有剩余题目才能参与 `final_weight` 计算、排序和 bucket 截取
4. 调用方不应假设 `questions` 已经是去重后的列表

如果要明确体现智能体接口，建议最终落成类接口，而不是只保留裸函数：

```python
class VerifyAgent:
    def __init__(self, config: Any, model_client: Any | None = None):
        self.config = config
        self.model_client = model_client

    async def run(
        self,
        task_id: str,
        run_id: str,
        validation_session_id: str | None,
        blueprint: ValidationBlueprintView,
        candidates: list[QuestionCandidate],
    ) -> ValidationTaskResult:
        ...
```

设计决策：

1. 上层编排器或 CLI 负责准备 `task_id/run_id`
2. `VerifyAgent` 接收调用方传入的 `validation_session_id`，或在缺失时自行生成
3. `VerifyAgent.run()` 负责驱动三阶段执行、状态推进和落盘
4. `ValidationTaskResult` 作为对上层的结构化回执

## 14. 配置建议

建议 `verify_agent.yaml`：

```yaml
run:
  task_id: "task_001"
  run_id: "run_001"
  chunk_index_path: "./runs/task_001/run_001/chunk_index.jsonl"
  input_paths:
    - "./runs/task_001/run_001/qa/candidate_pool.json"
    - "./runs/task_001/run_001/multiple_choice/candidate_pool.json"

citation_validation:
  enabled: true
  min_citation_score: 0.65
  alpha: 0.7
  beta: 0.3
  citation_match_threshold: 0.8
  require_all_citations_supported: false

llm_validation:
  enabled: true
  prompt_system: "benchforge/prompts/verify_agent/quality_system_prompt.md"
  prompt_user: "benchforge/prompts/verify_agent/quality_user_prompt.md"
  min_overall_score: 0.75
  max_concurrency: 8
  max_retries: 2
  hard_floor:
    clarity: 0.6
    answerability: 0.7
    faithfulness: 0.7
    mode_alignment: 0.7

grouping:
  enabled: true
  keys:
    - question_mode
    - estimated_difficulty

deduplication:
  enabled: true
  exact_text: true
  semantic: true
  embedding_model: "text-embedding-3-small"
  duplicate_similarity_threshold: 0.92

selection:
  enabled: true
  final_count_by_bucket:
    qa:
      easy: 6
      medium: 8
      hard: 6
    multiple_choice:
      easy: 3
      medium: 4
      hard: 3
  score_weights:
    citation: 0.45
    llm: 0.55
```

## 15. 落盘文件定义

### 15.1 `citation_validation.jsonl`

每行：

```json
{
  "question_id": "...",
  "passed": true,
  "answer_citation_score": 0.74,
  "chunk_citation_score": 0.86,
  "citation_score": 0.81,
  "citation_count": 2,
  "matched_citation_count": 2,
  "failed_reasons": []
}
```

### 15.2 `llm_validation.jsonl`

每行：

```json
{
  "question_id": "...",
  "passed": true,
  "overall_score": 0.84,
  "dimensions": {
    "clarity": 0.9,
    "answerability": 0.8,
    "faithfulness": 0.85,
    "difficulty_alignment": 0.75,
    "mode_alignment": 0.9
  },
  "failed_reasons": [],
  "judge_summary": "...",
  "llm_call_id": "llm_xxx",
  "attempt_count": 1,
  "latency_ms": 842,
  "error": null
}
```

### 15.3 `validated_questions.jsonl`

每行是最终逐题完整记录，包含 candidate 原始内容和所有验证结果。

建议最少包含：

```json
{
  "question_id": "...",
  "final_status": "rejected_llm",
  "candidate": { "...": "..." },
  "citation_validation": { "...": "..." },
  "llm_validation": {
    "passed": false,
    "failed_reasons": ["clarity_too_low"],
    "llm_call_id": "llm_xxx"
  }
}
```

### 15.4 `validation_report.json`

汇总：

```json
{
  "task_id": "...",
  "run_id": "...",
  "total_candidates": 120,
  "citation_passed": 96,
  "llm_passed": 71,
  "final_selected": 30,
  "stage_latencies_ms": {
    "citation_validation": 420,
    "llm_validation": 18230,
    "selection": 190
  },
  "llm_usage": {
    "calls": 71,
    "input_tokens": 40210,
    "output_tokens": 16784
  },
  "failed_by_stage": {
    "citation": 24,
    "llm": 25,
    "validator_error": 3,
    "duplicate": 16
  }
}
```

## 16. 异常与失败策略

### 16.1 引用验证失败

1. 单题拒绝
2. 不中断整个 run

### 16.2 LLM 验证失败

1. 单题记为 `rejected_llm`
2. 若调用失败可重试
3. 重试后仍失败可记为 `validator_error`

### 16.3 分组或语义去重失败

若 `grouping` 或 `deduplication.semantic` 运行失败：

1. 回退到更粗粒度分桶
2. 使用简单分桶采样

### 16.4 全局终止条件

仅在这些情况下终止整个验证 run：

1. 输入文件无法读取
2. 归一化后 0 题
3. 配置非法
4. LLM validator 必开且模型客户端不可用

## 17. 测试策略

### 17.1 单元测试

建议覆盖：

1. 输入归一化
2. citation score 计算
3. citation pass/fail 边界
4. llm validator JSON 解析
5. exact duplicate
6. semantic duplicate 判定包装层
7. blueprint quota selection
8. `chunks` 为空时的 `chunk_index.jsonl` hydrate
9. bucket 内静态排序与配额截取边界

模型调用测试建议：

1. 优先复用 `benchforge/models/fake.py`
2. 对 `llm_validator.py` 的单测使用 fake client 固定返回结构化 JSON
3. 避免每个实现者自造 mock 协议，减少测试接口漂移

### 17.2 集成测试

最少两组：

1. 小规模 happy path
2. 混合失败集
   - 无 citations
   - citation 不匹配
   - LLM 判失败
   - 重复题
   - 超配额题

### 17.3 回归测试

至少保留：

1. `llm_call_id` 落盘
2. `llm_calls.jsonl` 可反查
3. 引用验证分数阈值行为稳定
4. 最终模式数量满足 blueprint

## 18. MVP 实现建议

推荐分三步做：

### Phase 1

1. 输入归一化
2. 引用验证
3. 落盘结果
4. validation report

### Phase 2

1. LLM 验证
2. `llm_call_id` 追踪
3. 逐题最终状态

### Phase 3

1. 分组整编
2. 去重
3. 加权采样
4. 最终输出集

## 19. 实现优先级建议

如果只做最小可用版本，优先实现：

1. `normalizer.py`
2. `citation_validator.py`
3. `llm_validator.py`
4. `storage.py`
5. `agent.py`

`grouping.py`、`deduplicator.py`、`selector.py` 可以第二批补。

### 19.1 基于当前仓库的最小接入顺序

如果目标是尽快在现有 `benchforge` 中落地，而不是先做完全部设计，建议顺序是：

1. 新建 `benchforge/agents/verify_agent/schema.py`
   - 定义 `QuestionCandidate`
   - 定义 `CitationValidationResult`
   - 定义 `LLMValidationResult`
   - 定义 `ValidatedQuestionRecord`
2. 新建 `normalizer.py`
   - 读取 `candidate_pool.json` / `accepted_questions.jsonl`
   - 统一补齐 `question_id`、`task_id`、`run_id`
3. 新建 `citation_validator.py`
   - 先实现可离线运行的引用验证
   - 不依赖模型客户端
4. 新建 `llm_validator.py`
   - 复用现有 `model_client.complete()`
   - 强制要求写 `llm_call_id`
   - 调用时传入当前 run 的 `llm_trace_path`
5. 新建 `agent.py`
   - 串联前两阶段
   - 落盘 `validation/` 目录下的 JSONL 与汇总报告
6. 最后再补 `grouping.py / deduplicator.py / selector.py`

## 20. 对 Claude Code 的实现摘要

可直接交付的实现摘要：

1. 新建 `benchforge/agents/verify_agent/`
2. 输入支持 `candidate_pool.json` 和 `accepted_questions.jsonl`
3. 统一归一化成 `QuestionCandidate`
4. Stage 1 复用 yourbench citation score 思路做引用验证
5. Stage 2 使用单题单调 LLM 验证，输出结构化 JSON
6. Stage 3 优先按 yourbench 风格做分组整编、近重复去重、按 blueprint 配额和分布加权选题
7. 所有阶段都落盘
8. LLM 验证必须写 `llm_call_id`
9. 最终输出 `validated_questions.jsonl` 与 `validation_report.json`
