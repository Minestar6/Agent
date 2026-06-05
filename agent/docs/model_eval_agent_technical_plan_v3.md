# 模型评估智能体技术方案 v3

## 1. 设计目标

本方案用于实现 `ModelEvaluationAgent` 的第一版能力，重点包括：

1. **数据集评估**
   - 计算当前验证后题目集的 `citation_score`
   - 计算当前验证后题目集的 `diversity_score`

2. **模型自动评分**
   - 按题目类型执行自动指标
   - 自动指标由统一 registry 调用具体实现函数
   - 自动评分结果以 `metric -> question_mode -> models` 的形式保存

3. **LLM Judge 评分**
   - 按题目类型配置 LLM Judge 维度
   - LLM Judge 指标使用 `name + description`
   - 详细记录 LLM Judge 的输入、prompt、原始输出、解析结果和错误信息

4. **报告输出**
   - 数据集报告和模型报告分开保存
   - 输出多个维度的聚合表格结果
   - 输出目录根据当前运行上下文自动推导，不需要用户手动配置 `output_dir`

第一版暂不实现 pairwise。

---

## 2. 核心原则

### 2.1 不新增独立 BenchmarkQualityAgent

当前需求不是单独实现一个完整的 benchmark 质量评估智能体，而是在模型评估智能体中顺手计算当前数据集的两个数据集级指标：

```text
citation_score
diversity_score
```

因此配置中不使用 `benchmark_quality`，而使用更轻量的：

```yaml
dataset_evaluation:
```

### 2.2 不要求题目验证智能体额外处理数据

模型评估智能体直接消费题目验证智能体的最终输出，例如：

```text
validated_questions.jsonl
accepted_questions.jsonl
accepted_questions.quality.jsonl
```

不要求为了评估智能体单独新增字段或单独生成额外中间文件。

如果验证结果中已经包含 `citation_score`，评估智能体优先复用；如果没有，则在可行时尝试现场计算；如果无法计算，则该题跳过 citation 聚合，并在汇总中记录 missing 数量。

### 2.3 run_id 和输出目录自动推导

`run_id` 不应该要求用户在评估配置里重复填写。应当按照当前项目运行上下文自动获得，优先级如下：

```python
run_id = (
    runtime_context.run_id
    or config.run.get("run_id")
    or infer_run_id_from_input_paths(input_paths)
)
```

输出目录也不要求用户手写，而是根据 `task_id / run_id` 或当前运行目录自动推导。

推荐输出目录：

```text
runs/{task_id}/{run_id}/evaluation/
```

如果当前项目实际目录是：

```text
runs/{run_id}/...
```

则使用：

```text
runs/{run_id}/evaluation/
```

关键是：**输出路径由运行上下文自动生成，而不是 YAML 手动配置。**

### 2.4 模型连接信息不写在评估 YAML 中

候选模型可能有不同的：

```text
provider
base_url
api_key
model_name
deployment
local_path
tokenizer_path
```

这些属于模型连接信息，不应该在每次评估 YAML 中重复配置。

评估 YAML 只写：

```yaml
candidate_model_names:
judge_model_name:
generation_defaults:
judge_defaults:
```

完整模型配置从模型注册表或环境配置中加载。

### 2.5 公共生成参数统一

评估时为了公平性，应尽量使用统一生成参数，例如：

```yaml
generation_defaults:
  temperature: 0.0
  top_p: 1.0
  max_tokens: 1024
```

如果个别模型确实需要特殊设置，可以支持 `overrides`，但第一版可以先不实现或作为可选扩展。

---

## 3. 推荐配置文件

建议新增：

```text
benchforge/config/model_eval_agent.yaml
```

第一版配置如下：

```yaml
run:
  task_id: ""
  run_id: ""
  input_paths:
    - "runs/demo_run/validated_questions.jsonl"

dataset_evaluation:
  enabled: true
  metrics:
    - name: "citation_score"
      threshold: 0.85
    - name: "diversity_score"
      threshold: null

models:
  candidate_model_names:
    - "qwen2.5-7b"
    - "llama3.1-8b"

  judge_model_name: "gpt-4o-mini-judge"

  generation_defaults:
    temperature: 0.0
    top_p: 1.0
    max_tokens: 1024

  judge_defaults:
    temperature: 0.0
    top_p: 1.0
    max_tokens: 1200

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

judge:
  enabled: true
  prompt_system: "benchforge/prompts/model_eval_agent/judge_system_prompt.md"
  prompt_user: "benchforge/prompts/model_eval_agent/judge_user_prompt.md"
```

---

## 4. 模型注册表设计

建议新增或复用已有模型配置文件：

```text
benchforge/config/model_registry.yaml
```

示例：

```yaml
models:
  qwen2.5-7b:
    provider: "vllm"
    model_name: "Qwen/Qwen2.5-7B-Instruct"
    base_url: "http://localhost:8000/v1"
    api_key: ""

  llama3.1-8b:
    provider: "vllm"
    model_name: "meta-llama/Llama-3.1-8B-Instruct"
    base_url: "http://localhost:8001/v1"
    api_key: ""

  gpt-4o-mini-judge:
    provider: "openai"
    model_name: "gpt-4o-mini"
    base_url: "${OPENAI_BASE_URL:https://api.openai.com/v1}"
    api_key: "${OPENAI_API_KEY}"
```

加载逻辑：

```python
candidate_models = [
    model_registry[name]
    for name in config.models.candidate_model_names
]

for model in candidate_models:
    model.generation_config.update(config.models.generation_defaults)

judge_model = model_registry[config.models.judge_model_name]
judge_model.generation_config.update(config.models.judge_defaults)
```

如果后续需要支持单模型覆盖参数，可以加入：

```yaml
models:
  overrides:
    qwen2.5-7b:
      max_tokens: 2048
```

合并优先级：

```text
model_registry 基础连接配置
< generation_defaults / judge_defaults
< overrides
```

---

## 5. 输出目录设计

输出目录自动推导，例如：

```text
runs/{task_id}/{run_id}/evaluation/
```

报告分为数据集报告和模型报告：

```text
runs/{task_id}/{run_id}/evaluation/
├── dataset_report/
│   ├── dataset_scores.jsonl
│   ├── dataset_quality_summary.json
│   └── dataset_quality_by_group.csv
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
│   └── model_aggregate_report.json
│
└── traces/
    └── llm_judge_traces.jsonl
```

说明：

- `dataset_report/`：只保存测试集级别评估结果
- `model_report/`：保存模型回答、自动评分、LLM 分数和模型聚合报告
- `traces/`：保存 LLM Judge 的完整中间过程

---

## 6. 输出文件格式

### 6.1 dataset_scores.jsonl

#### citation_score

```json
{
  "type": "dataset_metric",
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

#### diversity_score

`diversity_score` 是集合级指标，不是逐题指标：

```json
{
  "type": "dataset_metric",
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

分组 diversity 也可以写入同一个文件：

```json
{
  "type": "dataset_metric",
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

### 6.2 automatic_scores.jsonl

自动评分结果按：

```text
metric_name -> question_mode -> models
```

组织。每一行对应一个题型下的一个自动指标。

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

选择题 accuracy：

```json
{
  "type": "model_auto_metric",
  "question_mode": "multiple_choice",
  "metric_name": "accuracy",
  "threshold": 1.0,
  "question_ids": ["q_101", "q_102", "q_103"],
  "models": {
    "qwen2.5-7b": {
      "scores": [1, 0, 1],
      "passed": [true, false, true],
      "mean": 0.6667,
      "pass_rate": 0.6667
    },
    "llama3.1-8b": {
      "scores": [1, 1, 1],
      "passed": [true, true, true],
      "mean": 1.0,
      "pass_rate": 1.0
    }
  }
}
```

---

### 6.3 llm_judge_scores.jsonl

LLM Judge 的轻量分数也按：

```text
metric_name -> question_mode -> models
```

组织。

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

### 6.4 llm_judge_traces.jsonl

LLM Judge 必须详细记录中间过程，风格应和现有智能体保持一致。

```json
{
  "trace_id": "judge_q001_qwen2.5-7b",
  "question_id": "q_001",
  "question_mode": "qa",
  "model_name": "qwen2.5-7b",

  "judge_model": "gpt-4o-mini-judge",
  "prompt_system": "benchforge/prompts/model_eval_agent/judge_system_prompt.md",
  "prompt_user": "benchforge/prompts/model_eval_agent/judge_user_prompt.md",

  "input": {
    "question": "...",
    "reference_answer": "...",
    "model_answer": "...",
    "citations": [],
    "metrics": [
      {
        "name": "correctness",
        "description": "判断模型回答是否正确回答了问题，是否与参考答案表达的核心事实一致。"
      },
      {
        "name": "completeness",
        "description": "判断模型回答是否覆盖参考答案中的关键信息。"
      }
    ]
  },

  "prompt": {
    "system": "...完整 system prompt...",
    "user": "...完整 user prompt..."
  },

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

## 7. 自动指标统一接口

自动指标必须由评估智能体实现统一接口，而不是只在 YAML 中声明名称。

### 7.1 单题 / 单模型自动指标接口

```python
class AutoMetric:
    name: str

    def compute(
        self,
        question: dict,
        prediction: str,
        context: dict | None = None,
    ) -> float:
        raise NotImplementedError
```

适用指标：

```text
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
```

### 7.2 数据集级指标接口

```python
class DatasetMetric:
    name: str

    def compute(
        self,
        questions: list[dict],
        context: dict | None = None,
    ) -> dict:
        raise NotImplementedError
```

适用指标：

```text
citation_score
diversity_score
```

### 7.3 Registry

```python
AUTO_METRIC_REGISTRY = {
    "accuracy": AccuracyMetric(),
    "invalid_rate": InvalidRateMetric(),
    "exact_match": ExactMatchMetric(),
    "f1": TokenF1Metric(),
    "precision": PrecisionMetric(),
    "recall": TokenRecallMetric(),
    "rouge_l": RougeLMetric(),
    "bleu": BleuMetric(),
    "bertscore": BertScoreMetric(),
    "semantic_similarity": SemanticSimilarityMetric(),
}

DATASET_METRIC_REGISTRY = {
    "citation_score": CitationScoreMetric(),
    "diversity_score": DiversityScoreMetric(),
}
```

执行时：

```python
for metric_spec in metric_plan.automatic_metrics:
    metric = AUTO_METRIC_REGISTRY[metric_spec.name]
    score = metric.compute(question, prediction, context)
```

---

## 8. 数据集指标实现

### 8.1 citation_score

优先复用题目验证智能体已有结果。

```python
def resolve_citation_score(question: dict) -> float | None:
    if "citation_score" in question:
        return question["citation_score"]

    if "citation_validation" in question:
        obj = question["citation_validation"]
        if "score" in obj:
            return obj["score"]
        if "citation_score" in obj:
            return obj["citation_score"]

    if "validation_result" in question:
        obj = question["validation_result"]
        if "citation_score" in obj:
            return obj["citation_score"]

    return compute_citation_score_if_possible(question)
```

如果无法计算，则返回 `None`，不参与平均。

聚合：

```python
mean = sum(scores) / len(scores)
pass_rate = sum(score >= threshold for score in scores) / len(scores)
```

### 8.2 diversity_score

基于题目文本计算集合级 diversity。

推荐使用：

```python
text = question["question"]
```

计算：

```python
embedding_dispersion = mean(1 - cosine_similarity(e_i, e_j))
cluster_entropy = -sum(p_k * log(p_k)) / log(K)

diversity_score = (
    embedding_dispersion_weight * normalized_embedding_dispersion
    + cluster_entropy_weight * normalized_cluster_entropy
)
```

分组聚合时，对每个 group 重新计算 diversity：

```text
question_mode
topic
estimated_difficulty
question_mode + estimated_difficulty
topic + question_mode
```

如果 group 内题目数量少于 3，则 diversity 记为 `null`。

---

## 9. LLM Judge 实现

### 9.1 触发条件

```python
should_run_judge = (
    config.judge.enabled
    and len(metric_plan.llm_judge_metrics) > 0
)
```

某个题型如果 `llm_judge_metrics: []`，即使全局 `judge.enabled: true`，也不执行 LLM Judge。

### 9.2 Prompt 模板

建议拆成：

```text
judge_system_prompt.md
judge_user_prompt.md
```

`judge_user_prompt.md` 示例：

```jinja2
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

Return JSON only:
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

## 10. 模块结构建议

新增：

```text
benchforge/
└── agents/
    └── model_eval_agent/
        ├── agent.py
        ├── schema.py
        ├── config_loader.py
        ├── model_registry_loader.py
        ├── model_runner.py
        ├── dataset_metric_executor.py
        ├── auto_metric_executor.py
        ├── llm_judge_executor.py
        ├── aggregator.py
        └── report_writer.py
```

通用指标目录：

```text
benchforge/
└── evaluation/
    ├── automatic_metrics/
    │   ├── registry.py
    │   ├── accuracy.py
    │   ├── exact_match.py
    │   ├── token_f1.py
    │   ├── rouge_l.py
    │   ├── bleu.py
    │   ├── bertscore.py
    │   └── semantic_similarity.py
    └── dataset_metrics/
        ├── registry.py
        ├── citation_score.py
        └── diversity_score.py
```

---

## 11. Schema 设计

```python
from dataclasses import dataclass, field


@dataclass
class DatasetMetricSpec:
    name: str
    threshold: float | None = None


@dataclass
class DatasetEvaluationConfig:
    enabled: bool = True
    metrics: list[DatasetMetricSpec] = field(default_factory=list)


@dataclass
class AutoMetricSpec:
    name: str
    threshold: float | None = None


@dataclass
class JudgeMetricSpec:
    name: str
    description: str


@dataclass
class QuestionModeMetricPlan:
    automatic_metrics: list[AutoMetricSpec] = field(default_factory=list)
    llm_judge_metrics: list[JudgeMetricSpec] = field(default_factory=list)


@dataclass
class ModelsConfig:
    candidate_model_names: list[str] = field(default_factory=list)
    judge_model_name: str | None = None
    generation_defaults: dict = field(default_factory=dict)
    judge_defaults: dict = field(default_factory=dict)


@dataclass
class JudgeConfig:
    enabled: bool = False
    prompt_system: str = ""
    prompt_user: str = ""


@dataclass
class ModelEvalAgentConfig:
    run: dict
    dataset_evaluation: DatasetEvaluationConfig
    models: ModelsConfig
    metrics: dict[str, QuestionModeMetricPlan]
    judge: JudgeConfig
```

---

## 12. 执行流程

```python
class ModelEvaluationAgent:
    def run(self, config_path: str, runtime_context: dict | None = None):
        config = load_model_eval_config(config_path)

        task_id, run_id = resolve_run_identity(config.run, runtime_context)
        input_paths = resolve_input_paths(config.run, runtime_context)
        output_root = resolve_output_root(task_id, run_id, runtime_context)

        questions = load_questions(input_paths)

        candidate_models = resolve_models(
            names=config.models.candidate_model_names,
            defaults=config.models.generation_defaults,
        )

        judge_model = None
        if config.judge.enabled:
            judge_model = resolve_model(
                name=config.models.judge_model_name,
                defaults=config.models.judge_defaults,
            )

        dataset_scores = run_dataset_metrics(
            questions=questions,
            metric_specs=config.dataset_evaluation.metrics,
            output_dir=output_root / "dataset_report",
        )

        model_responses = run_candidate_models(
            questions=questions,
            models=candidate_models,
            output_dir=output_root / "model_report",
        )

        automatic_scores = run_automatic_metrics(
            questions=questions,
            model_responses=model_responses,
            metric_plans=config.metrics,
            output_dir=output_root / "model_report",
        )

        llm_judge_scores = {}
        if judge_model is not None:
            llm_judge_scores = run_llm_judge(
                questions=questions,
                model_responses=model_responses,
                metric_plans=config.metrics,
                judge_model=judge_model,
                judge_config=config.judge,
                output_dir=output_root,
            )

        write_reports(
            questions=questions,
            dataset_scores=dataset_scores,
            automatic_scores=automatic_scores,
            llm_judge_scores=llm_judge_scores,
            output_root=output_root,
        )
```

---

## 13. 聚合报告

### 13.1 数据集报告

`dataset_report/dataset_quality_summary.json`

```json
{
  "num_questions": 1000,
  "citation_score": {
    "mean": 0.91,
    "threshold": 0.85,
    "pass_rate": 0.87,
    "num_scored": 980,
    "num_missing": 20
  },
  "diversity_score": {
    "score": 0.76,
    "embedding_dispersion": 0.69,
    "cluster_entropy": 0.83
  }
}
```

`dataset_report/dataset_quality_by_group.csv`

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

### 13.2 模型报告

`model_report/model_overall_report.csv`

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

`model_report/model_by_question_mode.csv`

```text
model_name
question_mode
num_questions
accuracy
exact_match
f1
semantic_similarity
judge_correctness
judge_faithfulness
```

`model_report/model_by_topic.csv`

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

`model_report/model_by_difficulty.csv`

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

`model_report/model_by_question_mode_and_difficulty.csv`

```text
model_name
question_mode
estimated_difficulty
num_questions
accuracy
f1
semantic_similarity
judge_correctness
judge_faithfulness
```

`model_report/model_by_topic_and_question_mode.csv`

```text
model_name
topic
question_mode
num_questions
accuracy
f1
semantic_similarity
judge_correctness
judge_faithfulness
```

---

## 14. 第一版实现顺序

### Step 1：配置加载

实现：

```text
schema.py
config_loader.py
model_registry_loader.py
```

### Step 2：数据集指标

实现：

```text
dataset_metric_executor.py
citation_score.py
diversity_score.py
dataset_report 输出
```

### Step 3：模型调用

实现：

```text
model_runner.py
model_responses.jsonl
```

### Step 4：自动评分

实现：

```text
auto_metric_executor.py
automatic_scores.jsonl
AUTO_METRIC_REGISTRY
```

### Step 5：LLM Judge

实现：

```text
llm_judge_executor.py
llm_judge_scores.jsonl
traces/llm_judge_traces.jsonl
```

### Step 6：聚合报告

实现：

```text
aggregator.py
report_writer.py
dataset_report/*
model_report/*
```

---

## 15. 第一版暂不实现

第一版先不做：

```text
pairwise
sampling
复杂 runtime 配置
复杂 output save flags
多 judge ensemble
claim-level judge
人工校准阈值
```

---

## 16. 总结

最终第一版模型评估智能体配置应收敛为：

```text
run
dataset_evaluation
models
metrics
judge
```

其中：

- `run`：从当前运行上下文获得 `task_id / run_id / input_paths`
- `dataset_evaluation`：只负责计算当前数据集的 `citation_score / diversity_score`
- `models`：只写模型 name 列表和公共生成参数
- `metrics`：按 `question_mode` 配置自动指标和 LLM Judge 指标
- `judge`：只配置是否启用和 prompt 路径

模型连接信息通过 `model_registry.yaml` 或环境配置加载。

输出目录自动推导，并拆分为：

```text
dataset_report/
model_report/
traces/
```
