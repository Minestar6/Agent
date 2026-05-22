# BenchForge MVP 修订实现计划：Wikipedia 检索 + 题目生成 + 题目验证 + 模型评估

## 0. 修订说明

上一版计划默认支持“用户上传本地文档”，这与你当前目标不一致。

本版修正为：

```text
给定主题 topic
  -> AutoBencher 风格 Wikipedia 检索
  -> 标准化 Wikipedia 页面为 SourceDocument
  -> YourBench 风格基于文档生成题目
  -> YourBench 风格题目验证
  -> ModelEvaluatorAgent 评估目标模型
```

当前阶段不支持用户文档输入。

当前阶段只实现：

```text
RetrievalRuntime
QuestionGeneratorAgent
QuestionValidatorAgent
ModelEvaluatorAgent
```

暂不实现：

```text
PlannerAgent
AnalyzerAgent
WeaknessTree
用户文档 ingest
PDF / HTML / Word 解析
多轮重规划
多语言派生
Dashboard
```

---

# 1. 当前 MVP 的真实工作流

## 1.1 输入

用户或配置文件只提供：

```text
主题 topic
目标题目数量
目标模型列表
生成模型
Judge 模型
Wikipedia 检索参数
```

例如：

```yaml
run:
  topic: "Fordism"
  language: "en"
  target_question_count: 20
```

## 1.2 执行流程

```text
Topic
  -> RetrievalRuntime.search_wikipedia()
  -> RetrievalRuntime.fetch_wikipedia_pages()
  -> SourceDocument[]
  -> QuestionGeneratorAgent
  -> QuestionRecord(status="generated")[]
  -> QuestionValidatorAgent
  -> QuestionRecord(status="validated" / "rejected")[]
  -> ModelEvaluatorAgent
  -> EvaluationRecord[]
  -> report.json / report.md
```

## 1.3 设计定位

- Wikipedia 检索不是单独 agent。
- 检索能力作为公共 runtime：`RetrievalRuntime`。
- `QuestionGeneratorAgent` 调用 `RetrievalRuntime` 获取文档。
- 这符合当前 BenchForge 技术设计：检索能力存在于共享 runtime，由 QuestionGeneratorAgent 执行生成任务时调用。

---

# 2. 推荐目录结构

```text
benchforge/
  __init__.py
  cli.py
  config.py
  orchestrator.py

  agents/
    __init__.py
    question_generator.py
    question_validator.py
    model_evaluator.py

  schemas/
    __init__.py
    config.py
    document.py
    question.py
    evaluation.py
    task.py

  artifacts/
    __init__.py
    store.py

  runtimes/
    __init__.py
    model_runtime.py
    retrieval_runtime.py
    judge_runtime.py
    fake_runtime.py

  pipelines/
    __init__.py
    chunking.py
    parsing.py
    validation.py
    scoring.py
    dedup.py
    reporting.py

  prompts/
    question_generation.md
    answer_judging.md

tests/
  unit/
  integration/

examples/
  configs/
    wikipedia_mvp.yaml
```

---

# 3. 配置文件写在哪里？

配置文件统一放在：

```text
examples/configs/wikipedia_mvp.yaml
```

真实运行时用户可以传入任意 YAML：

```bash
benchforge run examples/configs/wikipedia_mvp.yaml
```

运行时复制一份到：

```text
runs/<run_id>/config.yaml
```

这样每次运行都可复现。

---

# 4. 配置文件设计

文件：`benchforge/schemas/config.py`

## 4.1 YAML 示例

```yaml
run:
  run_id: null
  topic: "Fordism"
  language: "en"
  domain: "economics"
  output_dir: "runs"

retrieval:
  provider: "wikipedia"
  search_query: null
  max_pages: 5
  max_sections_per_page: 20
  include_page_summary: true
  include_pageviews: true
  user_agent: "BenchForge/0.1"

generation:
  question_mode: "open_qa"
  target_count: 20
  questions_per_chunk: 2
  generator_model:
    provider: "openai_compatible"
    model_id: "generator"
    model_name: "gpt-4o-mini"
    base_url: null
    api_key_env: "OPENAI_API_KEY"
    temperature: 0.2
    max_tokens: 4096

validation:
  min_citation_overlap: 0.65
  enable_duplicate_check: true
  duplicate_similarity_threshold: 0.9
  require_citation_text: true
  require_required_capability: true
  reject_if_answer_empty: true
  reject_if_no_valid_source: true

evaluation:
  scoring_mode: "auto"
  target_models:
    - provider: "openai_compatible"
      model_id: "target_gpt4o_mini"
      model_name: "gpt-4o-mini"
      base_url: null
      api_key_env: "OPENAI_API_KEY"
      temperature: 0.0
      max_tokens: 2048
  judge_model:
    provider: "openai_compatible"
    model_id: "judge"
    model_name: "gpt-4o-mini"
    base_url: null
    api_key_env: "OPENAI_API_KEY"
    temperature: 0.0
    max_tokens: 2048
```

## 4.2 配置字段中文解释

### `run`

| 字段 | 类型 | 中文解释 | 作用 |
|---|---|---|---|
| `run_id` | `str | None` | 运行 ID | 为空时自动生成，用于创建 `runs/<run_id>/` |
| `topic` | `str` | 用户给定主题 | Wikipedia 检索与题目生成的起点 |
| `language` | `str` | 语言 | Wikipedia 语言版本与题目语言 |
| `domain` | `str | None` | 领域标签 | 写入题目元数据，例如 economics/history/science |
| `output_dir` | `str` | 输出目录 | 默认 `runs` |

### `retrieval`

| 字段 | 类型 | 中文解释 | 作用 |
|---|---|---|---|
| `provider` | `str` | 检索来源 | 当前固定为 `wikipedia` |
| `search_query` | `str | None` | 自定义搜索 query | 为空时使用 `run.topic` |
| `max_pages` | `int` | 最大页面数 | 控制 Wikipedia 页面数量 |
| `max_sections_per_page` | `int` | 每页最大 section 数 | 防止页面过长 |
| `include_page_summary` | `bool` | 是否抓取页面摘要 | 用于题目生成上下文 |
| `include_pageviews` | `bool` | 是否抓取浏览量 | 后续可做 AutoBencher saliency rerank |
| `user_agent` | `str` | 请求 User-Agent | Wikipedia API 要求最好提供 |

### `generation`

| 字段 | 类型 | 中文解释 | 作用 |
|---|---|---|---|
| `question_mode` | `open_qa | multi_choice` | 题型 | 第一版建议先只做 `open_qa` |
| `target_count` | `int` | 目标题目数 | Generator 最多生成多少题 |
| `questions_per_chunk` | `int` | 每个 chunk 生成几题 | 控制覆盖范围 |
| `generator_model` | `ModelConfig` | 生成模型配置 | 用于生成题目、答案、引用、能力描述 |

### `validation`

| 字段 | 类型 | 中文解释 | 作用 |
|---|---|---|---|
| `min_citation_overlap` | `float` | 引用重叠阈值 | 检查 citation 是否真的来自 chunk |
| `enable_duplicate_check` | `bool` | 是否去重 | 防止重复题 |
| `duplicate_similarity_threshold` | `float` | 重复阈值 | 第一版用字符串相似度 |
| `require_citation_text` | `bool` | 是否要求引用文本 | 确保可追溯 |
| `require_required_capability` | `bool` | 是否要求能力描述 | 为后续 weakness tree 准备 |
| `reject_if_answer_empty` | `bool` | 空答案是否拒绝 | 防止无效题 |
| `reject_if_no_valid_source` | `bool` | 无有效来源是否拒绝 | 保证文档 grounded |

### `evaluation`

| 字段 | 类型 | 中文解释 | 作用 |
|---|---|---|---|
| `scoring_mode` | `exact_match | llm_judge | auto` | 评分模式 | open_qa 用 judge，选择题可 exact match |
| `target_models` | `list[ModelConfig]` | 待评估模型 | 每个 validated question 都会发给这些模型 |
| `judge_model` | `ModelConfig | None` | 裁判模型 | 用于开放问答语义评分 |

---

# 5. 类型数量压缩原则

你担心类型太多是对的。

MVP 阶段只保留 7 个核心类型：

```text
RunConfig
ModelConfig
SourceDocument
SourceChunk
QuestionRecord
EvaluationRecord
TaskResult
```

暂时不要实现：

```text
BlueprintSpec
RunState
TopicPlan
AnalysisReport
RunReport
LanguageVariant
Lineage 独立类
复杂 ArtifactRef
复杂 TaskSpec
```

这些以后接 Planner 时再补。

当前阶段的原则：

```text
能用 dict 表达的辅助信息，不要提前抽象成复杂类型。
只把跨 agent 流转的核心数据建模成 Pydantic 类型。
```

---

# 6. 核心 Schema 设计：带中文注释版

## 6.1 `ModelConfig`

用途：统一管理所有模型调用配置。

```python
class ModelConfig(BaseModel):
    """模型配置。

    作用：
    - 统一生成模型、目标模型、judge 模型的配置格式。
    - 避免 agent 内部直接写死 provider、model_name、api_key。
    """

    model_id: str
    """模型在本次运行中的逻辑 ID，例如 generator、judge、target_gpt4o。"""

    provider: Literal["fake", "openai_compatible"]
    """模型提供方类型。MVP 支持 fake 和 openai_compatible。"""

    model_name: str
    """真实模型名，例如 gpt-4o-mini、claude-sonnet-4、qwen-plus。"""

    base_url: str | None = None
    """OpenAI-compatible API 地址。为空时使用默认 OpenAI 地址。"""

    api_key_env: str | None = None
    """环境变量名，例如 OPENAI_API_KEY。不要把 key 写入配置文件。"""

    temperature: float = 0.0
    """采样温度。评估和 judge 建议 0，生成可略高。"""

    max_tokens: int = 2048
    """最大输出 token。"""
```

---

## 6.2 `SourceChunk`

用途：Wikipedia 页面分块后的最小证据单位。

```python
class SourceChunk(BaseModel):
    """来源文档分块。

    作用：
    - 题目必须引用 chunk，而不是只引用整篇页面。
    - Validator 根据 chunk 检查 citation 是否落地。
    """

    chunk_id: str
    """chunk 唯一 ID，建议格式：doc_id::chunk_0001。"""

    document_id: str
    """所属 Wikipedia 页面文档 ID。"""

    index: int
    """chunk 在文档中的序号。"""

    title: str | None = None
    """chunk 所属 section 标题。"""

    text: str
    """chunk 正文。"""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """附加信息，例如 section path、字符数、来源 URL。"""
```

---

## 6.3 `SourceDocument`

用途：标准化后的 Wikipedia 页面。

```python
class SourceDocument(BaseModel):
    """标准化后的 Wikipedia 来源文档。

    作用：
    - 表示一个被检索到的 Wikipedia 页面。
    - QuestionGenerator 基于它生成题目。
    - QuestionValidator 基于它验证 citation。
    """

    document_id: str
    """文档唯一 ID，建议由 wikipedia page_id 或 title hash 生成。"""

    run_id: str
    """所属运行 ID。"""

    source: Literal["wikipedia"] = "wikipedia"
    """来源类型。MVP 固定为 wikipedia。"""

    title: str
    """Wikipedia 页面标题。"""

    url: str
    """Wikipedia 页面 URL。"""

    page_id: int | None = None
    """Wikipedia page ID。"""

    language: str = "en"
    """Wikipedia 语言版本。"""

    summary: str | None = None
    """页面摘要。"""

    text: str
    """页面正文。"""

    chunks: list[SourceChunk] = Field(default_factory=list)
    """页面分块。"""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """附加信息，例如 pageviews、retrieval_score、revision_id。"""

    created_at: datetime
    """抓取并标准化的时间。"""
```

---

## 6.4 `QuestionRecord`

用途：统一问题池的核心对象。

```python
class QuestionRecord(BaseModel):
    """题目记录。

    作用：
    - 贯穿生成、验证、评估全流程。
    - 不要拆成 GeneratedQuestion / ValidatedQuestion / RejectedQuestion。
    - 通过 status 表示生命周期。
    """

    question_id: str
    """题目唯一 ID。"""

    run_id: str
    """所属运行 ID。"""

    status: Literal["generated", "validated", "rejected"]
    """题目状态：已生成、已验证、已拒绝。MVP 不需要 draft/archived。"""

    question: str
    """题干。"""

    answer: str
    """标准答案，由生成模型基于 Wikipedia 证据给出。"""

    question_mode: Literal["open_qa", "multi_choice"] = "open_qa"
    """题型。MVP 建议优先 open_qa。"""

    choices: list[str] | None = None
    """选择题选项。open_qa 时为空。"""

    language: str = "en"
    """题目语言。"""

    domain: str | None = None
    """领域标签。"""

    document_id: str
    """主要来源文档 ID。"""

    chunk_ids: list[str]
    """题目依赖的 chunk ID。"""

    citations: list[dict[str, str]]
    """引用证据。

    推荐格式：
    [
      {
        "document_id": "...",
        "chunk_id": "...",
        "text": "exact supporting span"
      }
    ]
    """

    required_capability: str
    """该题测试的能力描述。

    作用：
    - 不是最终能力标签。
    - 是后续能力聚类、弱点树、错误分析的原始信号。
    """

    estimated_difficulty: Literal["easy", "medium", "hard"] | None = None
    """生成模型估计的难度。"""

    generation_metadata: dict[str, Any] = Field(default_factory=dict)
    """生成元数据。

    建议包含：
    - prompt_template_id
    - generator_model
    - question_type
    - thought_process
    - raw_response
    """

    validation: dict[str, Any] = Field(default_factory=dict)
    """验证结果。

    建议格式：
    {
      "status": "passed" | "failed",
      "issues": [
        {"code": "...", "message": "...", "severity": "error"}
      ],
      "validated_at": "..."
    }
    """

    created_at: datetime
    """创建时间。"""

    updated_at: datetime
    """更新时间。"""
```

---

## 6.5 `EvaluationRecord`

用途：逐题、逐模型的评估事实表。

```python
class EvaluationRecord(BaseModel):
    """模型评估记录。

    作用：
    - 一条记录表示：某个模型回答某一道题后的评分结果。
    - 不写回 QuestionRecord，避免题目对象膨胀。
    """

    evaluation_id: str
    """评估记录唯一 ID。"""

    run_id: str
    """所属运行 ID。"""

    question_id: str
    """被评估的题目 ID。"""

    model_id: str
    """目标模型 ID。"""

    prompt: str
    """实际发给目标模型的 prompt。"""

    model_answer: str
    """目标模型原始回答。"""

    is_correct: bool
    """是否正确。"""

    score: float
    """分数，范围通常为 0 到 1。"""

    judge_model: str | None = None
    """使用的 judge 模型 ID。exact_match 时可为空。"""

    failed_capability_description: str | None = None
    """错误时的失败能力描述。

    作用：
    - 为后续 weakness tree 提供解释层。
    - 正确时为空。
    """

    error_type: str = "none"
    """错误类型，例如 incorrect_fact、partial_answer、hallucination、reasoning_error。"""

    judge_rationale: str | None = None
    """judge 给出的评分理由。"""

    confidence: float | None = None
    """judge 置信度。"""

    evaluated_at: datetime
    """评估时间。"""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """附加信息，例如 latency、token_usage、retry_count。"""
```

---

## 6.6 `TaskResult`

用途：agent 执行后的统一返回摘要。

```python
class TaskResult(BaseModel):
    """任务执行结果。

    作用：
    - 每个 agent run() 都返回 TaskResult。
    - Orchestrator 用它记录日志、判断是否继续。
    """

    task_name: str
    """任务名，例如 question_generation、question_validation、model_evaluation。"""

    status: Literal["succeeded", "failed", "partial"]
    """执行状态。"""

    metrics: dict[str, Any] = Field(default_factory=dict)
    """任务指标，例如 generated_count、validated_count、accuracy_by_model。"""

    errors: list[dict[str, Any]] = Field(default_factory=list)
    """错误列表。"""

    artifact_paths: list[str] = Field(default_factory=list)
    """本任务写出的 artifact 文件路径。"""

    created_at: datetime
    """任务完成时间。"""
```

---

# 7. 每个智能体的输入输出

## 7.1 QuestionGeneratorAgent

### 职责

```text
主题 -> Wikipedia 检索 -> SourceDocument -> 题目生成 -> QuestionRecord
```

### 输入

```python
class QuestionGenerationInput(BaseModel):
    run_id: str
    topic: str
    language: str
    domain: str | None
    retrieval_config: RetrievalConfig
    generation_config: GenerationConfig
```

中文解释：

| 字段 | 作用 |
|---|---|
| `run_id` | 当前运行 ID |
| `topic` | 用户给定主题，例如 Fordism |
| `language` | Wikipedia 语言版本与题目语言 |
| `domain` | 领域标签 |
| `retrieval_config` | Wikipedia 检索配置 |
| `generation_config` | 题目生成配置 |

### 输出

写入：

```text
runs/<run_id>/artifacts/source_documents.jsonl
runs/<run_id>/artifacts/question_records.jsonl
```

返回：

```python
TaskResult(
  task_name="question_generation",
  status="succeeded",
  metrics={
    "retrieved_page_count": 5,
    "chunk_count": 38,
    "generated_count": 20,
    "parse_failed_count": 0,
    "schema_failed_count": 1
  },
  artifact_paths=[
    "artifacts/source_documents.jsonl",
    "artifacts/question_records.jsonl"
  ]
)
```

### 内部流程

```text
1. 使用 topic 搜索 Wikipedia 页面
2. 抓取页面摘要和正文
3. 转成 SourceDocument
4. 分块成 SourceChunk
5. 对 chunk 调用生成模型
6. 解析 JSON 数组
7. 转成 QuestionRecord(status="generated")
8. 保存 artifact
```

---

## 7.2 QuestionValidatorAgent

### 职责

```text
QuestionRecord(status="generated")
  -> 质量验证
  -> QuestionRecord(status="validated" / "rejected")
```

### 输入

```python
class QuestionValidationInput(BaseModel):
    run_id: str
    questions: list[QuestionRecord]
    source_documents: list[SourceDocument]
    validation_config: ValidationConfig
```

### 输出

覆盖写入：

```text
runs/<run_id>/artifacts/question_records.jsonl
```

返回：

```python
TaskResult(
  task_name="question_validation",
  status="succeeded",
  metrics={
    "total_count": 20,
    "validated_count": 16,
    "rejected_count": 4,
    "citation_failed_count": 2,
    "duplicate_count": 1,
    "schema_failed_count": 1
  }
)
```

### 验证内容

题目验证智能体主要仿照 YourBench 的质量过滤思想，但要比 YourBench 更明确地输出拒绝原因。

MVP 验证项：

| 检查项 | 是否仿照 YourBench | 说明 |
|---|---:|---|
| Schema 检查 | 是 | 题目 JSON 是否能解析成 QuestionRecord |
| 必需字段检查 | 是 | question、answer、citations、document_id、chunk_ids 是否存在 |
| citation 落地检查 | 是 | citation text 是否能在来源 chunk 中找到或高度重叠 |
| 语义去重 | 是 | 第一版用字符串相似度，后续换 embedding |
| 选择题格式检查 | 部分 | 如果是 multi_choice，必须有选项和合法答案 |
| 答案非空检查 | 补充 | 防止空答案 |
| 来源存在检查 | 补充 | document_id/chunk_id 必须存在 |
| capability 非空检查 | BenchForge 补充 | required_capability 必须存在 |
| 题目是否可从证据回答 | 建议后续 LLM check | MVP 可先不做，或作为可选 judge check |

---

## 7.3 ModelEvaluatorAgent

### 职责

```text
QuestionRecord(status="validated")
  -> 目标模型答题
  -> judge / exact match 评分
  -> EvaluationRecord
```

### 输入

```python
class ModelEvaluationInput(BaseModel):
    run_id: str
    questions: list[QuestionRecord]
    evaluation_config: EvaluationConfig
```

### 输出

写入：

```text
runs/<run_id>/artifacts/evaluation_records.jsonl
```

返回：

```python
TaskResult(
  task_name="model_evaluation",
  status="succeeded",
  metrics={
    "evaluated_question_count": 16,
    "target_model_count": 1,
    "evaluation_record_count": 16,
    "accuracy_by_model": {
      "target_gpt4o_mini": 0.62
    },
    "judge_failed_count": 0
  }
)
```

### 内部流程

```text
1. 过滤 status == validated 的题目
2. 对每道题和每个 target model 构造答题 prompt
3. 调用统一 ModelRuntime
4. 得到 model_answer
5. 如果是选择题，优先 exact_match
6. 如果是开放问答，调用 JudgeRuntime
7. judge 输出 is_correct、score、rationale、error_type
8. 如果错误，judge 同时输出 failed_capability_description
9. 保存 EvaluationRecord
```

---

# 8. 公共函数与 runtime 设计

你这里必须要有公共函数，否则三个 agent 会重复写大量逻辑。

## 8.1 统一模型调用接口是否参照 YourBench？

是，应该参照 YourBench 的 `utils/inference/inference_core.py` 思路，但不要照搬。

保留思想：

```text
异步调用
统一 provider 接口
并发控制
重试 / 退避
token / latency 统计
raw_response 保留
```

MVP 先做最小版：

```python
class ModelRuntime:
    async def complete(
        self,
        model: ModelConfig,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        ...
```

```python
class ModelResponse(BaseModel):
    text: str
    model_id: str
    provider: str
    raw_response: dict[str, Any] | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
```

## 8.2 公共模块清单

### `runtimes/model_runtime.py`

公共能力：

```text
统一模型调用
OpenAI-compatible API
fake model
重试
超时
响应结构化
```

### `runtimes/retrieval_runtime.py`

公共能力：

```text
Wikipedia search
Wikipedia page fetch
page summary
page sections
pageviews 可选
```

核心接口：

```python
class RetrievalRuntime:
    async def search_wikipedia(
        self,
        query: str,
        language: str,
        max_pages: int,
    ) -> list[WikipediaSearchResult]:
        ...

    async def fetch_wikipedia_page(
        self,
        title: str,
        language: str,
    ) -> SourceDocument:
        ...
```

### `runtimes/judge_runtime.py`

公共能力：

```text
开放问答评分
错误类型分类
失败能力描述生成
```

### `pipelines/chunking.py`

公共能力：

```text
Wikipedia 页面切 chunk
稳定 chunk_id
```

### `pipelines/parsing.py`

公共能力：

```text
解析 <output_json>
解析 ```json fenced block
解析裸 JSON
Pydantic 校验
```

### `pipelines/validation.py`

公共能力：

```text
required fields check
citation check
choice check
answer check
capability check
```

### `pipelines/scoring.py`

公共能力：

```text
normalize_answer
exact_match_score
choice_match_score
```

### `pipelines/dedup.py`

公共能力：

```text
normalize_text
jaccard_similarity
near_duplicate_check
```

### `pipelines/reporting.py`

公共能力：

```text
生成 report.json
生成 report.md
```

---

# 9. Wikipedia RetrievalRuntime 设计

文件：`benchforge/runtimes/retrieval_runtime.py`

## 9.1 数据结构

```python
class WikipediaSearchResult(BaseModel):
    """Wikipedia 搜索结果。"""

    title: str
    """页面标题。"""

    page_id: int | None = None
    """Wikipedia page ID。"""

    snippet: str | None = None
    """搜索结果摘要。"""

    url: str | None = None
    """页面 URL。"""

    score: float | None = None
    """检索分数。MVP 可为空。"""
```

## 9.2 检索接口

```python
class WikipediaRetrievalRuntime:
    async def search(
        self,
        query: str,
        *,
        language: str = "en",
        max_pages: int = 5,
    ) -> list[WikipediaSearchResult]:
        """搜索 Wikipedia 页面。"""

    async def fetch_page(
        self,
        result: WikipediaSearchResult,
        *,
        run_id: str,
        language: str = "en",
    ) -> SourceDocument:
        """抓取 Wikipedia 页面并转换为 SourceDocument。"""
```

## 9.3 API 建议

MVP 可使用 MediaWiki API：

```text
https://{language}.wikipedia.org/w/api.php
```

搜索：

```text
action=query
list=search
srsearch={query}
format=json
```

页面内容：

```text
action=query
prop=extracts|info
explaintext=1
inprop=url
titles={title}
format=json
```

页面摘要也可用 REST API：

```text
https://{language}.wikipedia.org/api/rest_v1/page/summary/{title}
```

注意：

```text
不要复用 AutoBencher 里的硬编码 Wikimedia 凭据。
```

---

# 10. Orchestrator 设计

文件：`benchforge/orchestrator.py`

```python
async def run_wikipedia_mvp(config: RunConfig) -> Path:
    run_id = config.run.run_id or generate_run_id()
    run_dir = create_run_dir(config.run.output_dir, run_id)
    store = ArtifactStore(run_dir)

    store.write_yaml("config.yaml", config)

    generator = QuestionGeneratorAgent(
        store=store,
        retrieval_runtime=WikipediaRetrievalRuntime(),
        model_runtime=ModelRuntime(),
    )
    gen_result = await generator.run(
        QuestionGenerationInput(
            run_id=run_id,
            topic=config.run.topic,
            language=config.run.language,
            domain=config.run.domain,
            retrieval_config=config.retrieval,
            generation_config=config.generation,
        )
    )
    store.append_jsonl("logs/task_results.jsonl", [gen_result])

    questions = store.read_jsonl("artifacts/question_records.jsonl", QuestionRecord)
    documents = store.read_jsonl("artifacts/source_documents.jsonl", SourceDocument)

    validator = QuestionValidatorAgent(store=store)
    val_result = await validator.run(
        QuestionValidationInput(
            run_id=run_id,
            questions=questions,
            source_documents=documents,
            validation_config=config.validation,
        )
    )
    store.append_jsonl("logs/task_results.jsonl", [val_result])

    questions = store.read_jsonl("artifacts/question_records.jsonl", QuestionRecord)

    evaluator = ModelEvaluatorAgent(
        store=store,
        model_runtime=ModelRuntime(),
        judge_runtime=JudgeRuntime(),
    )
    eval_result = await evaluator.run(
        ModelEvaluationInput(
            run_id=run_id,
            questions=questions,
            evaluation_config=config.evaluation,
        )
    )
    store.append_jsonl("logs/task_results.jsonl", [eval_result])

    write_report(run_id=run_id, store=store)

    return run_dir
```

---

# 11. Artifact 输出

每次运行生成：

```text
runs/<run_id>/
  config.yaml
  artifacts/
    source_documents.jsonl
    question_records.jsonl
    evaluation_records.jsonl
  logs/
    task_results.jsonl
  report.json
  report.md
```

---

# 12. 测试计划

## 12.1 单元测试

```text
tests/unit/test_wikipedia_retrieval.py
tests/unit/test_chunking.py
tests/unit/test_parsing.py
tests/unit/test_validation.py
tests/unit/test_dedup.py
tests/unit/test_scoring.py
tests/unit/test_artifact_store.py
```

## 12.2 集成测试

```text
tests/integration/test_wikipedia_mvp_fake.py
```

使用 fake retrieval + fake model，避免测试依赖外网。

断言：

```python
assert source_documents.jsonl exists
assert question_records.jsonl exists
assert evaluation_records.jsonl exists
assert report.md exists
assert at least one validated question
```

---

# 13. 实施顺序

## Step 1：缩减 Schema

只实现：

```text
RunConfig
ModelConfig
SourceDocument
SourceChunk
QuestionRecord
EvaluationRecord
TaskResult
```

不要实现复杂 Planner 相关类型。

## Step 2：ArtifactStore

实现 JSONL 读写。

## Step 3：WikipediaRetrievalRuntime

实现：

```text
search
fetch_page
to SourceDocument
```

## Step 4：Chunking

实现稳定 chunk_id。

## Step 5：ModelRuntime

实现：

```text
fake
openai_compatible
```

## Step 6：QuestionGeneratorAgent

实现：

```text
topic -> retrieval -> documents -> chunks -> questions
```

## Step 7：QuestionValidatorAgent

实现 deterministic validation。

## Step 8：JudgeRuntime + ModelEvaluatorAgent

实现答题与评分。

## Step 9：CLI + Orchestrator

跑通：

```bash
benchforge run examples/configs/wikipedia_mvp.yaml
```

## Step 10：报告与测试

输出 report，补齐测试。

---

# 14. 本阶段不做什么

明确不做：

```text
用户本地文档输入
PDF/HTML/Word ingest
PlannerAgent
AnalyzerAgent
EvalTree
多轮 topic 优化
AutoBencher target accuracy loop
embedding dedup
多语言题目派生
dashboard
HF dataset upload
```

---

# 15. 完成标准

运行：

```bash
benchforge run examples/configs/wikipedia_mvp.yaml
```

能够完成：

```text
1. 根据 topic 搜索 Wikipedia
2. 抓取页面为 SourceDocument
3. 切分 SourceChunk
4. 基于 chunk 生成 QuestionRecord
5. 每题包含 document_id、chunk_ids、citations、required_capability
6. Validator 将题目标为 validated 或 rejected
7. Evaluator 只评估 validated 题目
8. EvaluationRecord 独立保存
9. report.md 输出生成数、验证数、拒绝数、模型准确率
10. fake runtime 下集成测试稳定通过
```

---

# 16. 给 Claude Code 的关键提醒

请 Claude Code 注意：

```text
1. 不要实现用户文档 ingest。
2. 文档来源只来自 Wikipedia RetrievalRuntime。
3. 不要实现 PlannerAgent。
4. 不要实现 AnalyzerAgent。
5. Schema 要少，不要过度抽象。
6. 每个字段必须写中文 docstring 或注释。
7. 所有模型调用必须通过 ModelRuntime。
8. 所有 Wikipedia 调用必须通过 RetrievalRuntime。
9. Validator 不生成新题，只更新 QuestionRecord.status 和 validation。
10. EvaluationRecord 不要写回 QuestionRecord。
11. 测试优先使用 fake runtime。
```
