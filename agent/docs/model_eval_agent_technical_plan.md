# 模型评估智能体技术方案（自动评分 + LLM 评分版）

## 1. 设计目标

模型评估智能体第一版只实现两类能力：

1. **题目集质量评估**
   - `citation_score`
   - `diversity_score`

2. **模型表现评估**
   - 自动评分指标，例如 `accuracy`、`exact_match`、`f1`、`precision`、`recall`、`rouge_l`、`bleu`、`bertscore`、`semantic_similarity`
   - LLM Judge 维度评分，例如 `correctness`、`completeness`、`faithfulness`、`hallucination`

第一版不实现 `pairwise`。

该智能体不要求题目验证智能体额外处理数据，而是直接消费当前验证智能体输出的题目文件。题目报告和模型报告分开保存。

---

## 2. 核心原则

### 2.1 `run_id` 自动推导

`run_id` 不应该在 YAML 中手动配置，而应该根据当前运行环境自动得到。

推荐优先级：

```python
run_id = (
    cli_args.run_id
    or infer_run_id_from_questions_path(questions_path)
    or timestamp_run_id()
)
```

其中：

```python
def infer_run_id_from_questions_path(path: str) -> str:
    # 例如：runs/wiki_eval_001/validated_questions.jsonl
    # 返回：wiki_eval_001
    return Path(path).parent.name
```

如果无法从路径推导，则生成时间戳：

```text
model_eval_20260605_153012
```

---

### 2.2 输出目录由参数化目录生成

不建议在 YAML 中直接写死 `output_dir`。应该根据输入题集、运行参数和评估配置自动构造。

推荐输出目录规则：

```text
{output_root}/{run_id}/evaluation/{eval_tag}/
```

其中：

```text
output_root：默认 runs，也可由 CLI 或 YAML 指定
run_id：自动推导
_eval_tag：由本次评估配置自动生成
```

`eval_tag` 可以由以下内容生成：

```text
auto_llm
auto_only
auto_llm_<config_hash>
```

推荐实现：

```python
eval_tag = config.eval_tag or build_eval_tag(config)
output_dir = Path(output_root) / run_id / "evaluation" / eval_tag
```

例如：

```text
runs/wiki_eval_001/evaluation/auto_llm_8f3a2c/
```

这样同一个题集可以多次用不同指标、不同 Judge 配置运行，不会互相覆盖。

---

## 3. 最终 YAML 输入设计

第一版 YAML 不包含 `run_id`，只包含输入路径、模型配置、题目集质量评估配置、按题型分配的指标、Judge 配置。

```yaml
input:
  questions_path: "runs/wiki_eval_001/validated_questions.jsonl"
  output_root: "runs"
  eval_tag: null   # null 表示自动根据配置生成

models:
  candidate_models:
    - name: "qwen2.5-7b"
      provider: "vllm"
      model_name: "Qwen/Qwen2.5-7B-Instruct"
      base_url: "http://localhost:8000/v1"
      api_key: ""
      temperature: 0.0
      max_tokens: 1024

    - name: "llama3.1-8b"
      provider: "vllm"
      model_name: "meta-llama/Llama-3.1-8B-Instruct"
      base_url: "http://localhost:8001/v1"
      api_key: ""
      temperature: 0.0
      max_tokens: 1024

  judge_model:
    name: "gpt-4o-mini-judge"
    provider: "openai"
    model_name: "gpt-4o-mini"
    base_url: "${OPENAI_BASE_URL:https://api.openai.com/v1}"
    api_key: "${OPENAI_API_KEY}"
    temperature: 0.0
    max_tokens: 1200

benchmark_quality:
  enabled: true

  citation_score:
    enabled: true
    threshold: 0.85

  diversity_score:
    enabled: true
    embedding_model: "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dispersion_weight: 0.5
    cluster_entropy_weight: 0.5

metrics:
  multiple_choice:
    automatic_metrics:
      - name: "accuracy"
        threshold: 1.0
      - name: "invalid_rate"
        threshold: null

    llm_judge_metrics: []

  qa:
    automatic_metrics:
      - name: "accuracy"
        threshold: 1.0
      - name: "exact_match"
        threshold: 1.0
      - name: "f1"
        threshold: 0.7
      - name: "precision"
        threshold: null
      - name: "recall"
        threshold: null
      - name: "rouge_l"
        threshold: 0.35
      - name: "bleu"
        threshold: 0.2
      - name: "bertscore"
        threshold: 0.85
      - name: "semantic_similarity"
        threshold: 0.85

    llm_judge_metrics:
      - name: "correctness"
        description: "判断模型回答是否正确回答了问题，是否与参考答案表达的核心事实一致。"
      - name: "completeness"
        description: "判断模型回答是否覆盖了参考答案中的关键信息，是否遗漏必要事实。"
      - name: "faithfulness"
        description: "判断模型回答是否被给定证据支持，是否没有引入未被支持的事实。"
      - name: "hallucination"
        description: "判断模型回答是否包含与参考答案或证据矛盾、无法由证据支持的内容。"

  summarization:
    automatic_metrics:
      - name: "rouge_l"
        threshold: 0.35
      - name: "bertscore"
        threshold: 0.85
      - name: "semantic_similarity"
        threshold: 0.85

    llm_judge_metrics:
      - name: "coverage"
        description: "判断摘要是否覆盖原文或参考答案中的主要信息。"
      - name: "faithfulness"
        description: "判断摘要是否忠实于原文，没有添加原文不支持的信息。"
      - name: "coherence"
        description: "判断摘要是否结构清晰、表达连贯。"
      - name: "non_redundancy"
        description: "判断摘要是否避免重复表达。"

judge:
  enabled: true
  prompt_path: "benchforge/prompts/model_eval_agent/pointwise_judge.md"
```

---

## 4. 输入字段说明

### 4.1 `input`

```yaml
input:
  questions_path: "runs/wiki_eval_001/validated_questions.jsonl"
  output_root: "runs"
  eval_tag: null
```

字段含义：

| 字段 | 说明 |
|---|---|
| `questions_path` | 题目验证智能体输出的最终题目文件 |
| `output_root` | 输出根目录，默认 `runs` |
| `eval_tag` | 本次评估目录标签，空则自动生成 |

`questions_path` 是唯一必须依赖的题目输入。不额外要求 `source_evidence_path`。

---

### 4.2 `models`

包含：

```text
candidate_models：被评估模型
judge_model：LLM Judge 模型
```

如果所有题型的 `llm_judge_metrics` 都为空，`judge_model` 可以为空。

代码中应该检查：

```python
need_judge = any(plan.llm_judge_metrics for plan in config.metrics.values())
if config.judge.enabled and need_judge and config.models.judge_model is None:
    raise ValueError("judge_model is required when llm_judge_metrics are configured.")
```

---

### 4.3 `benchmark_quality`

用于控制题目集质量评估。

```yaml
benchmark_quality:
  enabled: true
  citation_score:
    enabled: true
    threshold: 0.85
  diversity_score:
    enabled: true
    embedding_model: "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dispersion_weight: 0.5
    cluster_entropy_weight: 0.5
```

第一版只支持：

```text
citation_score
diversity_score
```

---

### 4.4 `metrics`

`metrics` 按 `question_mode` 分配指标。

结构固定为：

```yaml
metrics:
  <question_mode>:
    automatic_metrics:
      - name: <metric_name>
        threshold: <float|null>

    llm_judge_metrics:
      - name: <dimension_name>
        description: <natural_language_description>
```

执行逻辑：

```python
mode = question["question_mode"]
metric_plan = config.metrics[mode]
```

如果某个题目的 `question_mode` 不存在于 YAML 中，应直接报错，不做默认 fallback。

---

### 4.5 `judge`

```yaml
judge:
  enabled: true
  prompt_path: "benchforge/prompts/model_eval_agent/pointwise_judge.md"
```

这里不区分题型。它是全局 Judge 能力开关和默认 prompt 模板。

真正是否执行 LLM Judge，由以下条件决定：

```python
should_run_judge = (
    config.judge.enabled
    and len(config.metrics[question_mode].llm_judge_metrics) > 0
)
```

---

## 5. 输出目录设计

题目报告和模型报告必须分开保存。

推荐目录结构：

```text
runs/{run_id}/evaluation/{eval_tag}/
├── resolved_config.yaml
├── dataset_report/
│   ├── benchmark_quality_scores.jsonl
│   ├── benchmark_quality_summary.json
│   ├── benchmark_quality_by_question_mode.csv
│   ├── benchmark_quality_by_topic.csv
│   ├── benchmark_quality_by_difficulty.csv
│   └── benchmark_quality_by_group.csv
│
├── model_report/
│   ├── model_responses.jsonl
│   ├── automatic_scores.jsonl
│   ├── llm_judge_scores.jsonl
│   ├── model_overall_report.csv
│   ├── model_by_question_mode.csv
│   ├── model_by_topic.csv
│   ├── model_by_difficulty.csv
│   ├── model_by_question_mode_and_difficulty.csv
│   ├── model_by_topic_and_question_mode.csv
│   └── aggregate_model_report.json
│
└── traces/
    └── llm_judge_traces.jsonl
```

说明：

| 目录 | 作用 |
|---|---|
| `dataset_report/` | 题目集质量报告，只和测试集有关 |
| `model_report/` | 模型表现报告，只和 candidate models 有关 |
| `traces/` | LLM Judge 的完整中间过程 |

---

## 6. 题目集质量评估实现

### 6.1 citation_score

#### 6.1.1 分数来源

模型评估智能体不要求验证智能体额外处理数据，而是做兼容式读取。

优先级：

```python
def resolve_citation_score(question: dict) -> float | None:
    if "citation_score" in question:
        return question["citation_score"]

    if "citation_validation" in question:
        obj = question["citation_validation"]
        if "citation_score" in obj:
            return obj["citation_score"]
        if "score" in obj:
            return obj["score"]

    if "validation_result" in question:
        obj = question["validation_result"]
        if "citation_score" in obj:
            return obj["citation_score"]

    return compute_citation_score_if_possible(question)
```

如果无法得到或计算 citation score，则该题跳过 citation 聚合，计入 `num_missing`。

#### 6.1.2 计算方式

如果题目中有 citation text 和 source chunk text，则现场计算：

```text
citation_score(q) = mean(partial_ratio(citation_i, source_chunk_i) / 100)
```

无 citation 时：

```text
citation_score = None
```

#### 6.1.3 输出格式

`dataset_report/benchmark_quality_scores.jsonl` 中写入：

```json
{
  "type": "benchmark_quality_metric",
  "metric_name": "citation_score",
  "threshold": 0.85,
  "question_ids": ["q_001", "q_002", "q_003"],
  "scores": [0.93, 0.88, 0.61],
  "passed": [true, true, false],
  "mean": 0.8067,
  "pass_rate": 0.6667,
  "num_scored": 3,
  "num_missing": 0
}
```

---

### 6.2 diversity_score

`diversity_score` 是集合级指标，不是单题指标。

#### 6.2.1 输入文本

第一版使用题目文本：

```python
texts = [q["question"] for q in questions]
```

不拼接答案，避免答案长度影响语义空间。

#### 6.2.2 embedding_dispersion

```text
embedding_dispersion = mean(1 - cosine_similarity(e_i, e_j))
```

如果题目数量较大，可以随机采样 pair：

```python
if n <= 2000:
    use_all_pairs()
else:
    sample_100000_pairs()
```

归一化：

```python
normalized_dispersion = min(max(embedding_dispersion, 0.0), 1.0)
```

#### 6.2.3 cluster_entropy

先对 embedding 聚类，得到 cluster 分布：

```text
p_k = n_k / N
```

计算归一化熵：

```text
cluster_entropy = -sum(p_k * log(p_k)) / log(K)
```

如果 `K <= 1`：

```text
cluster_entropy = 0
```

#### 6.2.4 综合分数

```text
diversity_score =
    embedding_dispersion_weight * normalized_dispersion
    + cluster_entropy_weight * cluster_entropy
```

默认：

```text
0.5 * normalized_dispersion + 0.5 * cluster_entropy
```

#### 6.2.5 输出格式

整体分数：

```json
{
  "type": "benchmark_quality_metric",
  "metric_name": "diversity_score",
  "scope": "all",
  "score": 0.76,
  "components": {
    "embedding_dispersion": 0.69,
    "cluster_entropy": 0.83
  },
  "num_questions": 1000
}
```

分组分数：

```json
{
  "type": "benchmark_quality_metric",
  "metric_name": "diversity_score",
  "scope": "question_mode",
  "group_value": "qa",
  "score": 0.74,
  "components": {
    "embedding_dispersion": 0.68,
    "cluster_entropy": 0.80
  },
  "num_questions": 600
}
```

---

## 7. 模型自动评分实现

### 7.1 自动指标注册表

```python
AUTO_METRIC_REGISTRY = {
    "accuracy": AccuracyMetric(),
    "invalid_rate": InvalidRateMetric(),
    "exact_match": ExactMatchMetric(),
    "f1": TokenF1Metric(),
    "precision": PrecisionMetric(),
    "recall": RecallMetric(),
    "rouge_l": RougeLMetric(),
    "bleu": BleuMetric(),
    "bertscore": BertScoreMetric(),
    "semantic_similarity": SemanticSimilarityMetric(),
}
```

统一接口：

```python
class AutoMetric:
    def compute(self, question: dict, prediction: str) -> float:
        raise NotImplementedError
```

---

### 7.2 自动评分输出格式

`model_report/automatic_scores.jsonl` 中每一行表示：

```text
一个 question_mode 下，一个自动指标，在所有模型上的表现
```

示例：

```json
{
  "type": "model_auto_metric",
  "question_mode": "qa",
  "metric_name": "f1",
  "threshold": 0.7,
  "question_ids": ["q_001", "q_002", "q_003"],
  "models": {
    "qwen2.5-7b": {
      "scores": [0.73, 1.0, 0.42],
      "passed": [true, true, false],
      "mean": 0.7167,
      "pass_rate": 0.6667
    },
    "llama3.1-8b": {
      "scores": [0.61, 0.85, 0.30],
      "passed": [false, true, false],
      "mean": 0.5867,
      "pass_rate": 0.3333
    }
  }
}
```

---

## 8. LLM Judge 实现

### 8.1 触发条件

```python
should_run_judge = (
    config.judge.enabled
    and len(metric_plan.llm_judge_metrics) > 0
)
```

选择题通常不配置 `llm_judge_metrics`，因此不会执行 LLM Judge。

---

### 8.2 Judge Prompt 模板

`benchforge/prompts/model_eval_agent/pointwise_judge.md`：

```jinja2
You are an impartial evaluator.

Evaluate the model answer using only the provided question, reference answer, and evidence.
Do not use external knowledge.

Question:
{{ question }}

Reference Answer:
{{ reference_answer }}

Evidence / Citations:
{{ evidence }}

Model Answer:
{{ model_answer }}

Evaluation dimensions:
{% for metric in metrics %}
- {{ metric.name }}:
  {{ metric.description }}
{% endfor %}

Return JSON only in the following format:
{
  "scores": {
    {% for metric in metrics %}
    "{{ metric.name }}": <number from 0 to 1>,
    {% endfor %}
  },
  "reason": "<brief explanation>"
}
```

---

### 8.3 LLM Judge 轻量分数文件

`model_report/llm_judge_scores.jsonl`：

```json
{
  "type": "llm_judge_metric",
  "question_mode": "qa",
  "metric_name": "correctness",
  "question_ids": ["q_001", "q_002", "q_003"],
  "models": {
    "qwen2.5-7b": {
      "scores": [0.8, 1.0, 0.4],
      "mean": 0.7333
    },
    "llama3.1-8b": {
      "scores": [0.7, 0.9, 0.3],
      "mean": 0.6333
    }
  }
}
```

---

### 8.4 LLM Judge Trace 文件

LLM Judge 必须像其他智能体一样保存完整中间过程。

`traces/llm_judge_traces.jsonl`：

```json
{
  "trace_id": "judge_q001_qwen2.5-7b",
  "question_id": "q_001",
  "question_mode": "qa",
  "model_name": "qwen2.5-7b",
  "judge_model": "gpt-4o-mini-judge",
  "prompt_path": "benchforge/prompts/model_eval_agent/pointwise_judge.md",
  "input": {
    "question": "...",
    "reference_answer": "...",
    "model_answer": "...",
    "citations": [],
    "metrics": [
      {
        "name": "correctness",
        "description": "判断模型回答是否正确回答了问题。"
      }
    ]
  },
  "prompt": "...完整 prompt...",
  "raw_output": "{... judge 原始输出 ...}",
  "parsed_output": {
    "scores": {
      "correctness": 0.8,
      "completeness": 0.7,
      "faithfulness": 1.0,
      "hallucination": 0.0
    },
    "reason": "答案核心事实正确，但遗漏一个细节。"
  },
  "parse_success": true,
  "error": null,
  "retry_count": 0,
  "latency_seconds": 2.31
}
```

---

## 9. 报告聚合设计

### 9.1 题目报告

题目报告只保存到：

```text
dataset_report/
```

包括：

```text
benchmark_quality_summary.json
benchmark_quality_by_question_mode.csv
benchmark_quality_by_topic.csv
benchmark_quality_by_difficulty.csv
benchmark_quality_by_group.csv
```

#### benchmark_quality_summary.json

```json
{
  "num_questions": 1000,
  "citation": {
    "avg_citation_score": 0.91,
    "citation_threshold": 0.85,
    "citation_pass_rate": 0.87,
    "num_scored": 980,
    "num_missing": 20
  },
  "diversity": {
    "diversity_score": 0.76,
    "embedding_dispersion": 0.69,
    "cluster_entropy": 0.83,
    "num_questions_used": 1000
  }
}
```

#### benchmark_quality_by_group.csv

字段：

```text
group_type
group_value
num_questions
avg_citation_score
citation_pass_rate
diversity_score
embedding_dispersion
cluster_entropy
```

---

### 9.2 模型报告

模型报告只保存到：

```text
model_report/
```

包括：

```text
model_overall_report.csv
model_by_question_mode.csv
model_by_topic.csv
model_by_difficulty.csv
model_by_question_mode_and_difficulty.csv
model_by_topic_and_question_mode.csv
aggregate_model_report.json
```

#### model_overall_report.csv

字段：

```text
model_name
num_questions
accuracy
accuracy_pass_rate
invalid_rate
exact_match
f1
f1_pass_rate
precision
recall
rouge_l
bleu
bertscore
semantic_similarity
judge_correctness
judge_completeness
judge_faithfulness
judge_hallucination
```

#### model_by_question_mode.csv

字段：

```text
model_name
question_mode
num_questions
accuracy
invalid_rate
exact_match
f1
precision
recall
rouge_l
bleu
bertscore
semantic_similarity
judge_correctness
judge_completeness
judge_faithfulness
judge_hallucination
```

#### model_by_topic.csv

字段：

```text
model_name
topic
num_questions
accuracy
exact_match
f1
semantic_similarity
judge_correctness
judge_faithfulness
```

#### model_by_difficulty.csv

字段：

```text
model_name
estimated_difficulty
num_questions
accuracy
exact_match
f1
semantic_similarity
judge_correctness
judge_faithfulness
```

---

## 10. 推荐代码结构

```text
benchforge/
└── agents/
    └── model_eval_agent/
        ├── agent.py
        ├── schema.py
        ├── config_loader.py
        ├── run_context.py
        ├── output_paths.py
        ├── benchmark_quality.py
        ├── model_runner.py
        ├── auto_metric_executor.py
        ├── llm_judge_executor.py
        ├── aggregator.py
        └── report_writer.py
```

### 10.1 `run_context.py`

负责自动推导：

```text
run_id
eval_tag
output_dir
```

### 10.2 `output_paths.py`

负责统一生成输出路径：

```python
class EvalOutputPaths:
    root: Path
    dataset_report_dir: Path
    model_report_dir: Path
    traces_dir: Path
```

---

## 11. 执行流程

```text
1. load config
2. infer run_id from questions_path
3. build eval_tag and output_dir
4. save resolved_config.yaml
5. load validated_questions.jsonl
6. run benchmark quality evaluation
   - citation_score
   - diversity_score
   - write dataset_report
7. run candidate models
   - write model_report/model_responses.jsonl
8. run automatic metrics
   - write model_report/automatic_scores.jsonl
9. run LLM Judge if enabled
   - write model_report/llm_judge_scores.jsonl
   - write traces/llm_judge_traces.jsonl
10. aggregate model reports
    - write model_report/*.csv
    - write model_report/aggregate_model_report.json
```

---

## 12. 第一版不实现内容

第一版不实现：

```text
pairwise
sampling
manual eval_id
runtime yaml 配置
复杂 output flags
多 judge ensemble
claim-level judge
position bias correction
```

这些后续可以作为 v2 扩展。

---

## 13. 最终结论

第一版模型评估智能体应实现为：

```text
输入：
  questions_path
  output_root / eval_tag
  candidate_models
  judge_model
  benchmark_quality 配置
  metrics.<question_mode>.automatic_metrics
  metrics.<question_mode>.llm_judge_metrics
  judge.prompt_path

自动推导：
  run_id
  output_dir

输出分离：
  dataset_report/ 题目集质量报告
  model_report/ 模型表现报告
  traces/ LLM Judge 中间过程
```

这套设计满足：

```text
1. run_id 根据当前运行自动得到；
2. 输出文件进入带参数的目录；
3. 题目报告和模型报告分开保存；
4. 自动评分轻量记录 question_id list + models 分数；
5. LLM 评分完整记录输入、prompt、输出和解析结果；
6. 第一版只实现自动评分 + LLM 评分，不实现 pairwise。
```
