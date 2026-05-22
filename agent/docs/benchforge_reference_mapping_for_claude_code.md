# BenchForge 参考实现映射（给 Claude Code）

本文件用于告诉 Claude Code：

```text
BenchForge 每个模块应该参考哪个开源项目、哪个文件、哪个函数。
```

否则 Claude Code 不知道应该从哪里复用设计思路。

---

# 1. 总体参考关系

BenchForge MVP 当前只参考三个系统：

| 项目 | 用途 | 当前是否直接参考 |
|---|---|---|
| YourBench | 文档->题目生成流水线、统一模型调用、JSON 解析、schema 驱动生成 | 是（核心参考） |
| AutoBencher | Wikipedia 检索、topic 驱动 benchmark 构建 | 是（检索参考） |
| EvalTree | capability / weakness tree | 暂不实现 |

当前 MVP：

```text
Wikipedia retrieval
  -> document chunking
  -> question generation
  -> question validation
  -> model evaluation
```

因此：

```text
YourBench = generation/evaluation/runtime 参考
AutoBencher = retrieval 参考
EvalTree = 以后再接
```

---

# 2. 本地参考代码目录

Claude Code 应假设仓库目录：

```text
reference/
  code/
    yourbench/
    AutoBencher/
    EvalTree/
```

对应：

```text
reference/code/yourbench
reference/code/AutoBencher
reference/code/EvalTree
```

---

# 3. RetrievalRuntime 应参考哪里？

文件：

```text
benchforge/runtimes/retrieval_runtime.py
```

主要参考：

```text
reference/code/AutoBencher/tool_util.py
reference/code/AutoBencher/wiki_autobencher.py
```

重点参考函数：

---

## 3.1 Wikipedia 搜索

参考：

```python
search_related_pages
search_step
```

位置：

```text
reference/code/AutoBencher/tool_util.py
```

BenchForge 中需要重构为：

```python
class WikipediaRetrievalRuntime:
    async def search(...):
        ...
```

不要照搬：

```text
硬编码路径
os.system
缓存逻辑
全局变量
```

---

## 3.2 页面抓取

参考：

```python
search_step
```

位置：

```text
reference/code/AutoBencher/tool_util.py
```

BenchForge 要做的：

```text
Wikipedia 页面
 -> SourceDocument
 -> SourceChunk
```

不要直接保留 AutoBencher 原始 JSON。

---

## 3.3 Topic 驱动 benchmark 思想

参考：

```python
_generate_categories_targetacc_augmented
_refine_categories_targetacc_augmented
generate_full_qa
```

位置：

```text
reference/code/AutoBencher/wiki_autobencher.py
```

当前 MVP 不实现 target accuracy loop。

只保留：

```text
topic -> wikipedia pages
```

---

# 4. QuestionGeneratorAgent 应参考哪里？

文件：

```text
benchforge/agents/question_generator.py
```

主要参考：

```text
reference/code/yourbench/pipeline/question_generation/
```

尤其：

```text
_core.py
```

---

## 4.1 生成整体流程

参考：

```python
generate_questions
process_chunk
```

位置：

```text
reference/code/yourbench/pipeline/question_generation/_core.py
```

BenchForge 要保留：

```text
chunk -> prompt -> JSON -> QuestionRecord
```

不要保留：

```text
复杂 stage registry
HF dataset
LightEval export
```

---

## 4.2 Prompt schema 驱动

参考：

```python
schema_prompt_generator.py
schema_loader.py
question_schemas.py
```

位置：

```text
reference/code/yourbench/utils/
```

BenchForge 要保留：

```text
结构化 JSON 输出
Pydantic 校验
question schema 驱动
```

---

## 4.3 JSON 解析

参考：

```python
parsing_engine.py
```

位置：

```text
reference/code/yourbench/utils/parsing_engine.py
```

这是 MVP 非常关键的参考。

BenchForge 要支持：

```text
纯 JSON
```json fenced block
<output_json>
```

不要像 AutoBencher 一样只用脆弱 regex。

---

## 4.4 模型调用 Runtime

参考：

```python
utils/inference/inference_core.py
```

位置：

```text
reference/code/yourbench/utils/inference/inference_core.py
```

BenchForge 应学习：

```text
统一 provider 接口
异步调用
retry/backoff
并发控制
token usage
raw response 保存
```

但不要照搬整个实现。

BenchForge MVP 应重构为：

```python
class ModelRuntime:
    async def complete(...):
        ...
```

---

# 5. QuestionValidatorAgent 应参考哪里？

文件：

```text
benchforge/agents/question_validator.py
```

主要参考：

```text
reference/code/yourbench/pipeline/citation_score_filtering.py
reference/code/yourbench/utils/parsing_engine.py
```

---

## 5.1 Citation grounding

参考：

```python
citation_score_filtering.py
```

位置：

```text
reference/code/yourbench/pipeline/citation_score_filtering.py
```

BenchForge MVP 要保留：

```text
citation text 与 source chunk overlap 检查
```

MVP 可以先：

```text
字符串 overlap
fuzzy match
```

后续再 embedding。

---

## 5.2 Schema validation

参考：

```python
question_schemas.py
```

位置：

```text
reference/code/yourbench/utils/question_schemas.py
```

BenchForge 要做：

```text
Pydantic QuestionRecord 校验
required fields 检查
```

---

## 5.3 Duplicate check

YourBench 没有特别强的 dedup。

BenchForge MVP：

```text
normalized text
Jaccard similarity
```

不要一开始就 embedding dedup。

---

# 6. ModelEvaluatorAgent 应参考哪里？

文件：

```text
benchforge/agents/model_evaluator.py
```

主要参考：

```text
reference/code/AutoBencher/tool_util.py
```

尤其：

```python
test_taker_inference
fast_compare_answers
```

---

## 6.1 模型答题

参考：

```python
test_taker_inference
```

位置：

```text
reference/code/AutoBencher/tool_util.py
```

BenchForge 要重构为：

```text
validated questions
 -> target model answer
 -> EvaluationRecord
```

不要保留：

```text
脚本式调用
全局变量
os.system
```

---

## 6.2 judge compare

参考：

```python
fast_compare_answers
```

位置：

```text
reference/code/AutoBencher/tool_util.py
```

BenchForge MVP 要做：

```text
judge output:
- is_correct
- score
- rationale
- error_type
- failed_capability_description
```

不要只返回 yes/no。

---

# 7. Chunking 应参考哪里？

文件：

```text
benchforge/pipelines/chunking.py
```

参考：

```text
reference/code/yourbench/pipeline/chunking.py
```

BenchForge MVP 要保留：

```text
稳定 chunk_id
chunk overlap
chunk metadata
```

不要保留：

```text
复杂 multi-hop chunk sampling
```

---

# 8. 配置系统应参考哪里？

文件：

```text
benchforge/schemas/config.py
benchforge/config.py
```

参考：

```text
reference/code/yourbench/conf/schema.py
reference/code/yourbench/conf/loader.py
```

BenchForge MVP 要保留：

```text
Pydantic config
YAML loader
环境变量 API key
默认值
```

不要保留：

```text
复杂 stage config
多层 registry
```

---

# 9. ArtifactStore 应参考哪里？

参考：

```text
reference/code/yourbench/utils/dataset_engine.py
```

BenchForge MVP 不使用 HF dataset。

只学习：

```text
统一 artifact IO
JSONL 保存
子集概念
```

BenchForge MVP：

```text
runs/<run_id>/artifacts/*.jsonl
```

---

# 10. 当前 MVP 不要参考 EvalTree

当前阶段：

```text
不要实现 capability tree
不要实现 recursive clustering
不要实现 weakness profile
```

因此：

```text
reference/code/EvalTree
```

当前只作为未来参考。

---

# 11. 给 Claude Code 的最终指令

Claude Code 实现时必须遵守：

```text
1. RetrievalRuntime 参考 AutoBencher。
2. Question generation/runtime/parsing 参考 YourBench。
3. Evaluation/judge 思路参考 AutoBencher。
4. 不要直接复制原项目结构。
5. 不要复制硬编码路径。
6. 不要复制 os.system 调度。
7. 不要复制 HF dataset pipeline。
8. 所有核心类型使用 Pydantic v2。
9. 所有模型调用统一经过 ModelRuntime。
10. 所有 Wikipedia 调用统一经过 RetrievalRuntime。
11. 当前不要实现 Planner。
12. 当前不要实现 EvalTree。
13. 当前不要实现多轮 loop。
14. 当前目标只是：

Wikipedia topic
 -> documents
 -> questions
 -> validation
 -> evaluation
```

