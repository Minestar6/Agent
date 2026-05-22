# BenchForge MVP 实现计划：题目生成 + 题目验证 + 模型评估

## 0. 当前阶段目标

本阶段只实现三个 worker agent：

```text
QuestionGeneratorAgent
  -> QuestionValidatorAgent
  -> ModelEvaluatorAgent
```

暂不实现：

```text
PlannerAgent
AnalyzerAgent
WeaknessTree
多轮重规划
Web Retrieval
多语言派生
```

目标是先跑通一个稳定的本地单轮流水线：

```text
本地 .md/.txt 文档
  -> SourceDocument
  -> QuestionRecord(status=generated)
  -> QuestionRecord(status=validated/rejected)
  -> EvaluationRecord
  -> 简单 JSON/Markdown 运行摘要
```

---

## 1. 推荐目录结构

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

  artifacts/
    __init__.py
    store.py

  schemas/
    __init__.py
    artifact.py
    document.py
    question.py
    evaluation.py
    task.py
    config.py

  runtimes/
    __init__.py
    model_runtime.py
    judge_runtime.py
    fake_runtime.py

  pipelines/
    __init__.py
    documents.py
    chunking.py
    parsing.py
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
    local_mvp.yaml
  documents/
    sample.md
```

---

## 2. 核心设计原则

### 2.1 本阶段不用 Planner

第一阶段用 `orchestrator.py` 固定执行：

```text
load config
 -> ingest documents
 -> generate questions
 -> validate questions
 -> evaluate models
 -> write summary
```

这样可以避免过早引入多轮状态机。

### 2.2 Artifact 本地存储

所有产物保存到：

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

### 2.3 QuestionRecord 是统一问题池

不要拆：

```text
GeneratedQuestion
ValidatedQuestion
RejectedQuestion
```

统一使用：

```text
QuestionRecord.status
```

状态：

```python
draft
generated
validated
rejected
archived
```

### 2.4 EvaluationRecord 独立保存

不要把评测结果写回 `QuestionRecord`。

一题可以对应：

```text
多个模型
多次运行
多次 judge
多次 retry
```

所以评测结果必须独立为 `EvaluationRecord`，通过 `question_id` 关联。

---

## 3. Pydantic Schema 设计

### 3.1 SourceDocument

文件：`benchforge/schemas/document.py`

```python
class SourceChunk(BaseModel):
    chunk_id: str
    document_id: str
    index: int
    text: str
    token_count: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceDocument(BaseModel):
    document_id: str
    run_id: str
    source_path: str
    title: str | None = None
    text: str
    chunks: list[SourceChunk] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
```

第一阶段只支持：

```text
.md
.txt
```

---

### 3.2 QuestionRecord

文件：`benchforge/schemas/question.py`

```python
class QuestionStatus(str, Enum):
    DRAFT = "draft"
    GENERATED = "generated"
    VALIDATED = "validated"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class QuestionMode(str, Enum):
    OPEN_QA = "open_qa"
    MULTI_CHOICE = "multi_choice"


class Citation(BaseModel):
    document_id: str
    chunk_id: str
    text: str | None = None


class GenerationMetadata(BaseModel):
    prompt_template_id: str
    generator_model: str
    question_type: str | None = None
    thought_process: str | None = None
    additional_instructions: str | None = None
    raw_response: str | None = None


class Lineage(BaseModel):
    parent_question_id: str | None = None
    relation_type: str = "canonical"


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"


class ValidationResult(BaseModel):
    status: Literal["passed", "failed", "not_checked"] = "not_checked"
    issues: list[ValidationIssue] = Field(default_factory=list)
    validated_at: datetime | None = None


class QuestionRecord(BaseModel):
    question_id: str
    run_id: str
    created_round: int = 1
    updated_round: int = 1
    status: QuestionStatus

    question: str
    question_mode: QuestionMode
    choices: list[str] | None = None
    answer: str

    language: str = "en"
    domain: str | None = None

    document_id: str
    chunk_ids: list[str]
    citations: list[Citation]

    required_capability: str
    estimated_difficulty: Literal["easy", "medium", "hard"] | None = None

    generation_metadata: GenerationMetadata
    lineage: Lineage = Field(default_factory=Lineage)
    validation: ValidationResult = Field(default_factory=ValidationResult)

    created_at: datetime
    updated_at: datetime
```

---

### 3.3 EvaluationRecord

文件：`benchforge/schemas/evaluation.py`

```python
class ErrorType(str, Enum):
    INCORRECT_FACT = "incorrect_fact"
    PARTIAL_ANSWER = "partial_answer"
    HALLUCINATION = "hallucination"
    REASONING_ERROR = "reasoning_error"
    FORMAT_ERROR = "format_error"
    REFUSAL = "refusal"
    UNKNOWN = "unknown"
    NONE = "none"


class EvaluationRecord(BaseModel):
    evaluation_id: str
    run_id: str
    question_id: str
    model_id: str

    prompt: str
    model_answer: str

    is_correct: bool
    score: float

    judge_model: str | None = None
    failed_capability_description: str | None = None
    error_type: ErrorType = ErrorType.NONE
    judge_rationale: str | None = None
    confidence: float | None = None

    evaluated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

### 3.4 TaskSpec / TaskResult

文件：`benchforge/schemas/task.py`

```python
class TaskStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class TaskSpec(BaseModel):
    task_id: str
    task_type: str
    run_id: str
    round_id: int = 1
    input_refs: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria: dict[str, Any] = Field(default_factory=dict)


class ArtifactRef(BaseModel):
    artifact_type: str
    path: str
    count: int | None = None


class TaskError(BaseModel):
    code: str
    message: str
    recoverable: bool = True


class TaskResult(BaseModel):
    task_result_id: str
    task_id: str
    status: TaskStatus
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    errors: list[TaskError] = Field(default_factory=list)
    created_at: datetime
```

---

## 4. Config 设计

文件：`benchforge/schemas/config.py`

```python
class ModelConfig(BaseModel):
    model_id: str
    provider: Literal["fake", "openai_compatible"]
    model_name: str
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: float = 0.0
    max_tokens: int = 2048


class GenerationConfig(BaseModel):
    generator_model: ModelConfig
    question_mode: QuestionMode = QuestionMode.OPEN_QA
    target_count: int = 20
    questions_per_chunk: int = 3
    prompt_template_id: str = "question_generation_v1"
    require_citations: bool = True
    require_required_capability: bool = True


class ValidationConfig(BaseModel):
    min_citation_overlap: float = 0.65
    enable_duplicate_check: bool = True
    duplicate_similarity_threshold: float = 0.9
    require_answer_in_citation: bool = False


class EvaluationConfig(BaseModel):
    target_models: list[ModelConfig]
    judge_model: ModelConfig | None = None
    scoring_mode: Literal["exact_match", "llm_judge", "auto"] = "auto"
    prompt_template_id: str = "answer_judging_v1"


class RunConfig(BaseModel):
    run_id: str | None = None
    input_documents: list[str]
    output_dir: str = "runs"
    language: str = "en"
    domain: str | None = None
    generation: GenerationConfig
    validation: ValidationConfig
    evaluation: EvaluationConfig
```

示例配置：`examples/configs/local_mvp.yaml`

```yaml
input_documents:
  - examples/documents/sample.md

output_dir: runs
language: zh
domain: ai_evaluation

generation:
  question_mode: open_qa
  target_count: 10
  questions_per_chunk: 2
  generator_model:
    provider: openai_compatible
    model_id: generator
    model_name: gpt-4o-mini
    api_key_env: OPENAI_API_KEY

validation:
  min_citation_overlap: 0.65
  enable_duplicate_check: true
  duplicate_similarity_threshold: 0.9

evaluation:
  scoring_mode: auto
  target_models:
    - provider: fake
      model_id: fake_baseline
      model_name: fake
  judge_model:
    provider: openai_compatible
    model_id: judge
    model_name: gpt-4o-mini
    api_key_env: OPENAI_API_KEY
```

---

## 5. ArtifactStore 设计

文件：`benchforge/artifacts/store.py`

```python
class ArtifactStore:
    def __init__(self, run_dir: Path): ...

    def append_jsonl(self, name: str, records: list[BaseModel]) -> Path: ...

    def read_jsonl(self, name: str, model_cls: type[T]) -> list[T]: ...

    def overwrite_jsonl(self, name: str, records: list[BaseModel]) -> Path: ...

    def write_json(self, name: str, obj: BaseModel | dict) -> Path: ...

    def read_json(self, name: str) -> dict: ...

    def write_text(self, name: str, text: str) -> Path: ...
```

固定 artifact 文件名：

```text
source_documents.jsonl
question_records.jsonl
evaluation_records.jsonl
task_results.jsonl
report.json
report.md
```

---

## 6. Document Pipeline

文件：`benchforge/pipelines/documents.py`

职责：

```text
读取 .md/.txt
生成 SourceDocument
调用 chunk_text
保存 source_documents.jsonl
```

实现：

```python
def load_local_documents(
    run_id: str,
    paths: list[str],
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
) -> list[SourceDocument]:
    ...
```

文件：`benchforge/pipelines/chunking.py`

```python
def chunk_text(
    document_id: str,
    text: str,
    chunk_size: int = 1200,
    overlap: int = 150,
) -> list[SourceChunk]:
    ...
```

第一版不用 token tokenizer，直接按字符切分即可，但函数名保留 token 扩展空间。

---

## 7. Runtime 设计

### 7.1 ModelRuntime

文件：`benchforge/runtimes/model_runtime.py`

```python
class ModelRuntime(Protocol):
    async def complete(
        self,
        model: ModelConfig,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        ...
```

实现两个 runtime：

```text
FakeModelRuntime
OpenAICompatibleRuntime
```

文件：`benchforge/runtimes/fake_runtime.py`

```python
class FakeModelRuntime:
    async def complete(...):
        return deterministic_response
```

### 7.2 JudgeRuntime

文件：`benchforge/runtimes/judge_runtime.py`

```python
class JudgeVerdict(BaseModel):
    is_correct: bool
    score: float
    failed_capability_description: str | None = None
    error_type: ErrorType = ErrorType.NONE
    judge_rationale: str
    confidence: float


class JudgeRuntime:
    async def judge(
        self,
        question: QuestionRecord,
        model_answer: str,
        judge_model: ModelConfig,
    ) -> JudgeVerdict:
        ...
```

要求：

```text
一次 judge 调用同时完成：
1. 正误判断
2. score
3. rationale
4. 如果错误，输出 failed_capability_description
5. 如果错误，输出 error_type
```

---

## 8. JSON 解析与 Prompt

### 8.1 JSON 解析

文件：`benchforge/pipelines/parsing.py`

实现：

```python
def extract_json_array(text: str) -> list[dict[str, Any]]:
    """
    支持：
    1. 纯 JSON array
    2. ```json fenced block
    3. <output_json>...</output_json>
    """
```

### 8.2 题目生成 Prompt

文件：`benchforge/prompts/question_generation.md`

要求模型输出 JSON 数组：

```json
[
  {
    "question": "...",
    "answer": "...",
    "question_type": "factual|reasoning|comparison|multi_hop",
    "estimated_difficulty": "easy|medium|hard",
    "required_capability": "...",
    "citations": [
      {
        "chunk_id": "...",
        "text": "exact supporting span"
      }
    ],
    "thought_process": "brief explanation of why this question tests the capability"
  }
]
```

选择题模式额外输出：

```json
"choices": ["A. ...", "B. ...", "C. ...", "D. ..."]
```

### 8.3 Judge Prompt

文件：`benchforge/prompts/answer_judging.md`

要求模型输出：

```json
{
  "is_correct": true,
  "score": 1.0,
  "error_type": "none",
  "failed_capability_description": null,
  "judge_rationale": "...",
  "confidence": 0.95
}
```

---

## 9. QuestionGeneratorAgent

文件：`benchforge/agents/question_generator.py`

### 输入

```python
class QuestionGenerationInput(BaseModel):
    run_id: str
    round_id: int = 1
    source_documents: list[SourceDocument]
    generation_config: GenerationConfig
    language: str
    domain: str | None = None
```

### 输出

```text
TaskResult
question_records.jsonl
```

### 流程

```text
1. 遍历 SourceDocument.chunks
2. 按 target_count 控制总量
3. 为每个 chunk 构造 prompt
4. 调用 model_runtime.complete
5. extract_json_array
6. 每个 item 用 Pydantic 校验
7. 转换为 QuestionRecord(status=generated)
8. 保存到 question_records.jsonl
9. 返回 TaskResult
```

### 生成指标

```python
metrics = {
    "generated_count": 10,
    "raw_response_count": 5,
    "parse_failed_count": 0,
    "schema_failed_count": 1,
    "missing_citation_count": 0,
}
```

---

## 10. QuestionValidatorAgent

文件：`benchforge/agents/question_validator.py`

### 输入

```python
class QuestionValidationInput(BaseModel):
    run_id: str
    questions: list[QuestionRecord]
    source_documents: list[SourceDocument]
    validation_config: ValidationConfig
```

### 输出

```text
更新后的 question_records.jsonl
```

### 验证规则

必须实现这些 deterministic checks：

```text
required_fields_check
question_mode_check
answer_non_empty_check
multi_choice_check
citation_exists_check
citation_overlap_check
duplicate_check
capability_non_empty_check
```

### 具体规则

#### required_fields_check

检查：

```text
question
answer
document_id
chunk_ids
citations
required_capability
generation_metadata
```

#### multi_choice_check

当 `question_mode == multi_choice`：

```text
choices 必须是 4 个
answer 必须能映射到选项
```

#### citation_exists_check

每个 citation 的：

```text
document_id
chunk_id
```

必须存在于 SourceDocument。

#### citation_overlap_check

用简单 fuzzy overlap：

```python
overlap = len(common_words(citation_text, chunk_text)) / len(words(citation_text))
```

小于 `min_citation_overlap` 则 reject。

#### duplicate_check

第一版可以用 normalized string Jaccard：

```python
normalize(question)
```

后续再替换 embedding。

### 状态更新

通过：

```python
question.status = QuestionStatus.VALIDATED
question.validation.status = "passed"
```

失败：

```python
question.status = QuestionStatus.REJECTED
question.validation.status = "failed"
question.validation.issues = [...]
```

---

## 11. ModelEvaluatorAgent

文件：`benchforge/agents/model_evaluator.py`

### 输入

```python
class ModelEvaluationInput(BaseModel):
    run_id: str
    questions: list[QuestionRecord]
    evaluation_config: EvaluationConfig
```

只评估：

```python
question.status == QuestionStatus.VALIDATED
```

### 输出

```text
evaluation_records.jsonl
```

### 流程

```text
1. 过滤 validated questions
2. 对每个 target_model + question 构造答题 prompt
3. 调用 model_runtime.complete 得到 model_answer
4. 如果 scoring_mode == exact_match：
     直接比较 normalized answer
5. 如果 scoring_mode == llm_judge：
     调用 JudgeRuntime
6. 如果 scoring_mode == auto：
     multi_choice 优先 exact_match
     open_qa 使用 llm_judge
7. 写 EvaluationRecord
8. 返回 TaskResult
```

### 答题 Prompt

```text
Answer the following question.

Question:
{question}

Return only the answer. Do not include explanation unless necessary.
```

选择题：

```text
Question:
{question}

Choices:
{choices}

Return the best option letter and answer text.
```

### 评估指标

```python
metrics = {
    "evaluated_count": 20,
    "target_model_count": 2,
    "accuracy_by_model": {
        "fake_baseline": 0.4
    },
    "judge_failed_count": 0,
    "inference_failed_count": 0,
}
```

---

## 12. Orchestrator

文件：`benchforge/orchestrator.py`

```python
async def run_mvp(config: RunConfig) -> Path:
    run_id = config.run_id or generate_run_id()
    run_dir = create_run_dir(config.output_dir, run_id)
    store = ArtifactStore(run_dir)

    documents = load_local_documents(run_id, config.input_documents)
    store.overwrite_jsonl("source_documents.jsonl", documents)

    generator = QuestionGeneratorAgent(...)
    gen_result = await generator.run(...)

    questions = store.read_jsonl("question_records.jsonl", QuestionRecord)

    validator = QuestionValidatorAgent(...)
    val_result = await validator.run(...)

    questions = store.read_jsonl("question_records.jsonl", QuestionRecord)

    evaluator = ModelEvaluatorAgent(...)
    eval_result = await evaluator.run(...)

    evaluations = store.read_jsonl("evaluation_records.jsonl", EvaluationRecord)

    write_simple_report(...)
    return run_dir
```

---

## 13. CLI

文件：`benchforge/cli.py`

使用 Typer：

```bash
benchforge run examples/configs/local_mvp.yaml
```

命令：

```python
@app.command()
def run(config_path: Path):
    config = load_run_config(config_path)
    asyncio.run(run_mvp(config))
```

输出：

```text
Run completed: runs/run_20260520_...
Questions: 10 generated, 8 validated, 2 rejected
Evaluations: 8 completed
Report: runs/.../report.md
```

---

## 14. Report

第一阶段不要做 AnalyzerAgent，但可以写一个简单函数：

文件：`benchforge/pipelines/reporting.py`

输出 `report.json`：

```json
{
  "run_id": "...",
  "questions": {
    "generated": 10,
    "validated": 8,
    "rejected": 2
  },
  "evaluation": {
    "accuracy_by_model": {
      "fake_baseline": 0.5
    }
  }
}
```

输出 `report.md`：

```md
# BenchForge MVP Report

## Question Summary

- Generated: 10
- Validated: 8
- Rejected: 2

## Evaluation Summary

| Model | Accuracy | Count |
|---|---:|---:|
| fake_baseline | 0.50 | 8 |
```

---

## 15. 测试计划

### 15.1 Unit Tests

```text
tests/unit/test_chunking.py
tests/unit/test_parsing.py
tests/unit/test_artifact_store.py
tests/unit/test_question_validation.py
tests/unit/test_exact_match_scoring.py
```

必须覆盖：

```text
JSON fenced block 解析
<output_json> 解析
invalid JSON 失败
QuestionRecord Pydantic 校验
citation overlap
duplicate detection
multi-choice validation
EvaluationRecord 写入
```

### 15.2 Integration Test

```text
tests/integration/test_mvp_pipeline_fake.py
```

使用：

```text
FakeModelRuntime
sample.md
target_count=3
fake target model
fake judge
```

断言：

```python
assert source_documents exists
assert question_records exists
assert evaluation_records exists
assert report.md exists
assert at least one validated question
```

---

## 16. 实施步骤

### Step 1：项目骨架

创建：

```text
benchforge/
tests/
examples/
pyproject.toml
```

依赖：

```toml
pydantic>=2
typer
pyyaml
httpx
rich
pytest
pytest-asyncio
```

### Step 2：Schema

实现：

```text
schemas/document.py
schemas/question.py
schemas/evaluation.py
schemas/task.py
schemas/config.py
```

完成所有 Pydantic 测试。

### Step 3：ArtifactStore

实现：

```text
artifacts/store.py
```

支持：

```text
append_jsonl
read_jsonl
overwrite_jsonl
write_json
write_text
```

### Step 4：Document Pipeline

实现：

```text
pipelines/documents.py
pipelines/chunking.py
```

只支持：

```text
.md
.txt
```

### Step 5：Runtime

实现：

```text
runtimes/model_runtime.py
runtimes/fake_runtime.py
runtimes/judge_runtime.py
```

OpenAI-compatible runtime 可以只做最小版：

```text
POST {base_url}/chat/completions
```

### Step 6：QuestionGeneratorAgent

实现：

```text
agents/question_generator.py
prompts/question_generation.md
pipelines/parsing.py
```

先用 fake runtime 跑通，再接真实模型。

### Step 7：QuestionValidatorAgent

实现：

```text
agents/question_validator.py
pipelines/dedup.py
pipelines/scoring.py
```

只做 deterministic validation。

### Step 8：ModelEvaluatorAgent

实现：

```text
agents/model_evaluator.py
prompts/answer_judging.md
```

支持：

```text
exact_match
llm_judge
auto
```

### Step 9：Orchestrator + CLI

实现：

```text
orchestrator.py
cli.py
config.py
```

跑通：

```bash
benchforge run examples/configs/local_mvp.yaml
```

### Step 10：报告与集成测试

实现：

```text
pipelines/reporting.py
tests/integration/test_mvp_pipeline_fake.py
```

---

## 17. 明确不要做的东西

第一阶段不要做：

```text
PlannerAgent
AnalyzerAgent
EvalTree
Web retrieval
PDF parsing
HTML parsing
Hugging Face upload
dashboard
distributed execution
多轮补题
AutoBencher target accuracy loop
embedding dedup
```

这些全部等到三个 worker 稳定后再加。

---

## 18. 完成标准

第一阶段完成标准：

```bash
benchforge run examples/configs/local_mvp.yaml
```

能够生成：

```text
runs/<run_id>/artifacts/source_documents.jsonl
runs/<run_id>/artifacts/question_records.jsonl
runs/<run_id>/artifacts/evaluation_records.jsonl
runs/<run_id>/report.json
runs/<run_id>/report.md
```

并且满足：

```text
1. 至少能从本地文档生成题目
2. 每道题有 document_id、chunk_ids、citations
3. 每道题有 required_capability
4. Validator 能把问题标为 validated 或 rejected
5. Evaluator 只评估 validated 问题
6. EvaluationRecord 独立保存，不回写 QuestionRecord
7. fake runtime 下集成测试稳定通过
8. 真实 OpenAI-compatible runtime 可选运行
```

这版做好之后，再接 Planner 就会很顺。
