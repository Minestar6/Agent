# QuestionGeneratorAgent 执行计划

# 1. 模块目标

实现：

```text
Topic
  -> Wikipedia Retrieval
  -> SourceDocument
  -> SourceChunk
  -> Prompt Construction
  -> LLM Generation
  -> Structured JSON Parsing
  -> QuestionRecord(status="generated")
```

该模块是整个 BenchForge MVP 的核心。

目标：

- 根据 topic 自动检索 Wikipedia
- 自动构建 chunk
- 自动生成 benchmark 问题
- 自动生成答案
- 自动生成 citation
- 自动生成 capability 描述
- 输出标准化 QuestionRecord

最终输出：

```text
source_documents.jsonl
question_records.jsonl
```

---

# 2. 模块位置

```text
benchforge/agents/question_generator.py
```

依赖：

```text
runtimes/retrieval_runtime.py
runtimes/model_runtime.py
pipelines/chunking.py
pipelines/parsing.py
artifacts/store.py
schemas/document.py
schemas/question.py
```

---

# 3. 输入输出

## 3.1 输入

```python
class QuestionGenerationInput(BaseModel):
    run_id: str
    topic: str
    language: str = "en"
    domain: str | None = None

    retrieval_config: RetrievalConfig
    generation_config: GenerationConfig
```

输入说明：

| 字段 | 作用 |
|---|---|
| `run_id` | 当前运行 ID |
| `topic` | 用户输入主题 |
| `language` | Wikipedia 语言版本 |
| `domain` | 领域标签 |
| `retrieval_config` | Wikipedia 检索参数 |
| `generation_config` | 题目生成参数 |

---

## 3.2 输出

### artifact

```text
artifacts/source_documents.jsonl
artifacts/question_records.jsonl
```

### TaskResult

```python
TaskResult(
    task_name="question_generation",
    status="succeeded",
    metrics={
        "retrieved_page_count": 5,
        "chunk_count": 42,
        "generated_count": 20,
        "parse_failed_count": 1,
        "schema_failed_count": 2,
    }
)
```

---

# 4. 执行流程

# Step 1：Wikipedia Retrieval

## 目标

根据 topic 搜索 Wikipedia 页面。

## 调用

```python
results = retrieval_runtime.search(
    query=topic,
    language=language,
    max_pages=config.max_pages,
)
```

## 参考代码

```text
AutoBencher/tool_util.py
```

重点参考：

```python
search_related_pages
search_step
```

## 输出

```python
list[WikipediaSearchResult]
```

示例：

```python
[
  {
    "title": "Fordism",
    "url": "https://en.wikipedia.org/wiki/Fordism"
  }
]
```

---

# Step 2：Fetch Wikipedia Pages

## 目标

将 Wikipedia 页面抓取并标准化。

## 调用

```python
document = retrieval_runtime.fetch_page(
    result,
    run_id=run_id,
    language=language,
)
```

## 输出

```python
SourceDocument
```

## 要求

必须包含：

```text
page title
page url
summary
page text
metadata
```

## 保存

写入：

```text
source_documents.jsonl
```

---

# Step 3：Chunking

## 目标

将 Wikipedia 页面切分成稳定 chunk。

## 调用

```python
chunks = chunk_document(
    document,
    chunk_size=1200,
    overlap=150,
)
```

## chunk 要求

每个 chunk 必须包含：

```python
chunk_id
text
index
document_id
```

chunk_id 推荐：

```text
{document_id}::chunk_0001
```

## 输出

```python
list[SourceChunk]
```

## 参考

```text
YourBench/pipeline/chunking.py
```

---

# Step 4：Prompt Construction

## 目标

将 chunk 转换为题目生成 prompt。

## Prompt 文件

```text
prompts/question_generation.md
```

## Prompt 输入

```text
Topic
Wikipedia page title
chunk text
question mode
language
```

## Prompt 输出要求

模型必须返回 JSON 数组。

示例：

```json
[
  {
    "question": "What is Fordism?",
    "answer": "Fordism is a system of mass production...",
    "question_type": "factual",
    "required_capability": "Understanding industrial production systems",
    "estimated_difficulty": "easy",
    "citations": [
      {
        "chunk_id": "fordism::chunk_0001",
        "text": "Fordism is a system of mass production..."
      }
    ]
  }
]
```

---

# Step 5：LLM Generation

## 目标

调用统一 ModelRuntime 生成问题。

## 调用

```python
response = await model_runtime.complete(
    model=config.generator_model,
    messages=messages,
)
```

## Runtime 参考

```text
YourBench/utils/inference/inference_core.py
```

## 要求

必须支持：

```text
OpenAI-compatible API
async
retry
raw response 保存
```

## 输出

```python
ModelResponse
```

包含：

```python
text
raw_response
latency
input_tokens
output_tokens
```

---

# Step 6：JSON Parsing

## 目标

解析模型输出。

## 调用

```python
items = extract_json_array(response.text)
```

## 必须支持

```text
纯 JSON
```json fenced block
<output_json>
```

## 参考

```text
YourBench/utils/parsing_engine.py
```

## 错误处理

如果解析失败：

```python
parse_failed_count += 1
```

并跳过当前 chunk。

---

# Step 7：Schema Validation

## 目标

将 JSON item 转为 QuestionRecord。

## 调用

```python
question = QuestionRecord.model_validate(item)
```

## 必需字段

```text
question
answer
required_capability
citations
```

## 失败处理

如果 schema 校验失败：

```python
schema_failed_count += 1
```

并跳过当前 item。

---

# Step 8：QuestionRecord Construction

## 目标

补充系统字段。

## 必须补充

```python
question_id
run_id
status
created_at
updated_at
language
domain
document_id
chunk_ids
generation_metadata
```

## status

固定：

```python
status="generated"
```

## generation_metadata

建议包含：

```python
{
  "generator_model": "gpt-4o-mini",
  "prompt_template_id": "question_generation_v1",
  "raw_response": response.text,
}
```

---

# Step 9：Artifact Save

## 目标

保存问题结果。

## 调用

```python
artifact_store.append_jsonl(
    "question_records.jsonl",
    questions,
)
```

## 保存位置

```text
runs/<run_id>/artifacts/question_records.jsonl
```

---

# Step 10：TaskResult

## 目标

返回任务统计。

## 指标

```python
metrics = {
    "retrieved_page_count": 5,
    "chunk_count": 42,
    "generated_count": 20,
    "parse_failed_count": 1,
    "schema_failed_count": 2,
}
```

---

# 5. QuestionRecord 最低要求

每道题必须包含：

```text
question
answer
required_capability
citation
chunk_id
document_id
status
```

不满足则 reject。

---

# 6. 需要实现的公共函数

# 6.1 chunk_document

文件：

```text
pipelines/chunking.py
```

接口：

```python
def chunk_document(document, chunk_size, overlap):
    ...
```

---

# 6.2 extract_json_array

文件：

```text
pipelines/parsing.py
```

接口：

```python
def extract_json_array(text):
    ...
```

---

# 6.3 build_generation_prompt

文件：

```text
pipelines/prompting.py
```

接口：

```python
def build_generation_prompt(...):
    ...
```

---

# 6.4 normalize_text

文件：

```text
pipelines/text_utils.py
```

接口：

```python
def normalize_text(text):
    ...
```

---

# 7. 推荐实现顺序

## Step 1

实现：

```text
SourceDocument
SourceChunk
QuestionRecord
```

---

## Step 2

实现：

```text
WikipediaRetrievalRuntime
```

---

## Step 3

实现：

```text
chunk_document
```

---

## Step 4

实现：

```text
ModelRuntime
```

---

## Step 5

实现：

```text
extract_json_array
```

---

## Step 6

实现：

```text
QuestionGeneratorAgent
```

---

## Step 7

实现：

```text
artifact save
TaskResult
```

---

# 8. 测试

## 单元测试

```text
test_retrieval.py
test_chunking.py
test_parsing.py
test_question_generation.py
```

## 集成测试

```text
test_generator_fake_runtime.py
```

使用：

```text
fake retrieval
fake model
```

断言：

```python
assert generated_count > 0
assert question_records.jsonl exists
assert all(question.status == "generated")
```

---

# 9. 完成标准

QuestionGeneratorAgent 能够：

```text
1. 根据 topic 检索 Wikipedia
2. 自动抓取页面
3. 自动切 chunk
4. 自动生成题目
5. 自动生成答案
6. 自动生成 citation
7. 自动生成 capability 描述
8. 输出 QuestionRecord
9. 保存 question_records.jsonl
10. fake runtime 测试通过
11. OpenAI-compatible API 可运行
```

