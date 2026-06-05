# Model Evaluation Agent 技术方案 v2

## 1. 设计目标

本方案用于在现有题目生成智能体和题目验证智能体之后，新增一个 **Model Evaluation Agent**。该智能体不重新处理题目数据，也不要求题目验证智能体为了评估阶段额外改造输出格式，而是直接消费当前验证后的题目集，并完成两类任务：

1. **数据集评估**：计算当前测试集的 `citation_score` 和 `diversity_score`，输出数据集质量报告。
2. **模型评估**：对候选模型在题集上的回答进行自动评分和 LLM Judge 评分，输出模型表现报告。

第一版不实现 pairwise。pairwise 后续可以作为扩展模块加入。

---

## 2. 总体原则

### 2.1 不新增复杂 BenchmarkQualityAgent

本阶段不需要单独设计一个新的 Benchmark Quality Agent。`citation_score` 和 `diversity_score` 只是 Evaluation Agent 内部的数据集级指标，配置中用 `dataset_evaluation` 表示即可。

### 2.2 run_id 自动获得

`run_id` 不应要求用户手动重复填写。应仿照当前题目验证智能体的思路，从当前运行上下文或输入路径中自动推导。

推荐优先级：

```python
run_id = (
    runtime_context.run_id
    or raw_config.get("run", {}).get("run_id")
    or infer_run_id_from_input_paths(input_paths)
)
```

如果项目中已有统一运行上下文，则优先使用上下文中的 `run_id`。如果没有，则从 `run.input_paths` 中推导。

### 2.3 输出目录自动构造

输出目录不应由用户手写完整路径。应根据 `task_id / run_id / agent_name / 参数签名` 自动构造。

推荐结构：

```text
runs/{task_id}/{run_id}/model_eval/{eval_signature}/
```

其中：

```text
eval_signature = metrics 配置 + models 配置 + judge 配置的短哈希
```

例如：

```text
runs/wiki_task/run_001/model_eval/auto_llm_7f3a2c/
```

这样同一题集可以用不同指标、不同模型、不同 judge prompt 多次评估，结果不会互相覆盖。

### 2.4 题目报告和模型报告分开保存

输出目录中应拆成两部分：

```text
model_eval/{eval_signature}/
├── dataset_report/
└── model_report/
```

其中：

```text
dataset_report/  保存 citation_score、diversity_score 和数据集维度聚合结果
model_report/    保存自动评分、LLM Judge 评分和模型维度聚合结果
```

### 2.5 自动评分指标必须有统一接口

所有自动评分指标必须在 Evaluation Agent 中实现对应计算函数，并通过统一 registry 调用。YAML 只负责声明指标名称和阈值。

### 2.6 LLM Judge 需要完整 trace

自动评分只需轻量记录 `question_ids / scores / passed`。LLM Judge 必须像其他智能体一样保存完整中间过程，包括输入、prompt、raw output、parsed output、解析状态、错误信息、重试次数等。

---

## 3. 最终输入 YAML 结构

第一版输入配置建议包含 5 个主要部分：

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
      threshold: null
    - name: "diversity_score"
      threshold: null

models:
  defaults:
    provider: "vllm"
    base_url: "http://localhost:8000/v1"
    api_key: ""
    temperature: 0.0
    max_tokens: 1024

  candidate_models:
    - name: "qwen2.5-7b"
      model_name: "Qwen/Qwen2.5-7B-Instruct"

    - name: "llama3.1-8b"
      model_name: "meta-llama/Llama-3.1-8B-Instruct"

  judge_model:
    provider: "openai"
    model_name: "gpt-4o-mini"
    base_url: "${OPENAI_BASE_URL:https://api.openai.com/v1}"
    api_key: "${OPENAI_API_KEY}"
    temperature: 0.0
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

## 4. 输入字段说明

### 4.1 `run`

```yaml
run:
  task_id: ""
  run_id: ""
  input_paths:
    - "runs/demo_run/validated_questions.jsonl"
```

说明：

- `task_id` 和 `run_id` 可以为空。
- 如果为空，Evaluation Agent 需要从当前运行上下文或 `input_paths` 自动推导。
- `input_paths` 对齐题目验证智能体风格，可以支持一个或多个验证后题目文件。

第一版可以只支持一个输入文件；多文件合并后续扩展。

---

### 4.2 `dataset_evaluation`

```yaml
dataset_evaluation:
  enabled: true
  metrics:
    - name: "citation_score"
      threshold: 0.85
    - name: "diversity_score"
      threshold: null
```

说明：

- 这里只表示是否在评估过程中计算当前数据集质量指标。
- 不再使用 `benchmark_quality` 这个名称，避免误解为独立 agent。
- `citation_score` 是单题级指标，可输出 `question_ids / scores / passed`。
- `diversity_score` 是集合级指标，输出整体和分组结果。

---

### 4.3 `models`

```yaml
models:
  defaults:
    provider: "vllm"
    base_url: "http://localhost:8000/v1"
    api_key: ""
    temperature: 0.0
    max_tokens: 1024

  candidate_models:
    - name: "qwen2.5-7b"
      model_name: "Qwen/Qwen2.5-7B-Instruct"

  judge_model:
    provider: "openai"
    model_name: "gpt-4o-mini"
    base_url: "${OPENAI_BASE_URL:https://api.openai.com/v1}"
    api_key: "${OPENAI_API_KEY}"
    temperature: 0.0
    max_tokens: 1200
```

说明：

- `models.defaults` 是候选模型的公共配置。
- `candidate_models` 只写模型差异字段，例如 `name / model_name`。
- 加载时执行：

```python
candidate_model_config = {**models.defaults, **candidate_model}
```

- 这样保证所有候选模型使用一致的 temperature、max_tokens 等推理参数，评估更公平。
- `judge_model` 单独配置，因为 judge 可能使用不同 provider、base_url、max_tokens。

---

### 4.4 `metrics`

```yaml
metrics:
  <question_mode>:
    automatic_metrics:
      - name: "f1"
        threshold: 0.7
    llm_judge_metrics:
      - name: "correctness"
        description: "..."
```

说明：

- `metrics` 是按 `question_mode` 分配的指标计划。
- 不写死只有 `multiple_choice / qa`，可以扩展到 `summarization / reasoning / instruction_following / evidence_grounded_qa` 等。
- 某道题是否运行 LLM Judge 由两个条件决定：

```python
judge.enabled is True and len(metrics[question_mode].llm_judge_metrics) > 0
```

---

### 4.5 `judge`

```yaml
judge:
  enabled: true
  prompt_system: "benchforge/prompts/model_eval_agent/judge_system_prompt.md"
  prompt_user: "benchforge/prompts/model_eval_agent/judge_user_prompt.md"
```

说明：

- `judge` 是全局开关和 prompt 模板配置。
- 不在这里区分题型。
- 具体评分维度来自 `metrics.<question_mode>.llm_judge_metrics`。

---

## 5. 自动评分统一接口

### 5.1 自动指标 Registry

所有自动指标需要统一注册：

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

DATASET_METRIC_REGISTRY = {
    "citation_score": CitationScoreMetric(),
    "diversity_score": DiversityScoreMetric(),
}
```

### 5.2 单题模型指标接口

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

适用于：

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

### 5.3 数据集级指标接口

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

适用于：

```text
citation_score
diversity_score
```

---

## 6. 数据集指标实现

### 6.1 citation_score

目标：计算当前验证后题目集中的 citation 质量。

优先复用题目验证智能体已有结果，不要求验证智能体额外处理数据。

解析优先级：

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

如果无法获得或现场计算，返回 `None`，不参与平均。

输出轻量记录：

```json
{
  "type": "dataset_metric",
  "metric_name": "citation_score",
  "threshold": 0.85,
  "question_ids": ["q_001", "q_002", "q_003"],
  "scores": [0.93, 0.88, 0.61],
  "passed": [true, true, false],
  "mean": 0.8067,
  "pass_rate": 0.6667
}
```

---

### 6.2 diversity_score

目标：衡量当前题目集整体的语义多样性。

计算对象：

```python
texts = [question["question"] for question in questions]
```

计算步骤：

1. 使用配置的 embedding model 编码题目文本。
2. 计算 embedding dispersion。
3. 对 embedding 聚类，计算 cluster entropy。
4. 加权得到 diversity_score。

公式：

```text
embedding_dispersion = mean(1 - cosine_similarity(e_i, e_j))

cluster_entropy = -sum(p_k * log(p_k)) / log(K)

diversity_score =
    embedding_dispersion_weight * normalized_embedding_dispersion
  + cluster_entropy_weight * normalized_cluster_entropy
```

输出：

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

分组计算时可按：

```text
question_mode
topic
estimated_difficulty
question_mode + estimated_difficulty
topic + question_mode
```

组内题目数小于 3 时，`diversity_score = null`。

---

## 7. 模型自动评分输出

自动评分按如下格式保存：

```text
model_report/automatic_scores.jsonl
```

每一行代表一个 `question_mode + metric_name`，其中 `models` 的 key 是模型名，value 是该模型的得分列表、通过列表和均值。

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

这种结构便于后续聚合：

```text
metric → question_mode → models → scores
```

---

## 8. LLM Judge 评分实现

### 8.1 执行条件

对每个 question：

```python
mode = question["question_mode"]
metric_plan = config.metrics[mode]

should_run_judge = (
    config.judge.enabled
    and len(metric_plan.llm_judge_metrics) > 0
)
```

如果某题型的 `llm_judge_metrics` 为空，则不执行 LLM Judge。

### 8.2 Judge Prompt

Judge prompt 由 system prompt 和 user prompt 组成。

输入字段包括：

```text
question
reference_answer
model_answer
citations / evidence
llm_judge_metrics
```

其中 `llm_judge_metrics` 由 YAML 提供：

```yaml
llm_judge_metrics:
  - name: "correctness"
    description: "判断模型回答是否正确回答了问题。"
```

LLM 输出格式要求：

```json
{
  "scores": {
    "correctness": 0.8,
    "completeness": 0.7,
    "faithfulness": 1.0,
    "hallucination": 0.0
  },
  "reason": "答案核心事实正确，但遗漏一个细节。"
}
```

---

### 8.3 LLM Judge 轻量分数文件

保存路径：

```text
model_report/llm_judge_scores.jsonl
```

格式：

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

### 8.4 LLM Judge Trace

保存路径：

```text
model_report/traces/llm_judge_traces.jsonl
```

每次 judge 调用记录完整中间过程：

```json
{
  "trace_id": "judge_q001_qwen2.5-7b",
  "question_id": "q_001",
  "question_mode": "qa",
  "model_name": "qwen2.5-7b",
  "judge_model": "gpt-4o-mini",
  "prompt_system_path": "benchforge/prompts/model_eval_agent/judge_system_prompt.md",
  "prompt_user_path": "benchforge/prompts/model_eval_agent/judge_user_prompt.md",
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
  "prompt": "完整发送给 judge 的 prompt",
  "raw_output": "{...}",
  "parsed_output": {
    "scores": {
      "correctness": 0.8,
      "completeness": 0.7
    },
    "reason": "..."
  },
  "parse_success": true,
  "error": null,
  "retry_count": 0,
  "latency_seconds": 2.31
}
```

---

## 9. 输出目录结构

最终输出目录由运行上下文自动推导：

```text
runs/{task_id}/{run_id}/model_eval/{eval_signature}/
```

建议结构：

```text
runs/{task_id}/{run_id}/model_eval/{eval_signature}/
├── resolved_config.yaml
│
├── dataset_report/
│   ├── dataset_scores.jsonl
│   ├── dataset_quality_summary.json
│   └── dataset_quality_by_group.csv
│
└── model_report/
    ├── model_responses.jsonl
    ├── automatic_scores.jsonl
    ├── llm_judge_scores.jsonl
    ├── model_overall_report.csv
    ├── model_by_question_mode.csv
    ├── model_by_topic.csv
    ├── model_by_difficulty.csv
    ├── model_by_question_mode_and_difficulty.csv
    ├── model_by_topic_and_question_mode.csv
    ├── model_aggregate_report.json
    └── traces/
        └── llm_judge_traces.jsonl
```

说明：

- `dataset_report/`：只保存数据集自身指标。
- `model_report/`：保存候选模型输出、自动评分、LLM Judge、模型聚合报告。
- `resolved_config.yaml`：保存环境变量展开、defaults merge 后的最终配置，保证复现。

---

## 10. 聚合报告

### 10.1 数据集报告

#### `dataset_quality_summary.json`

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
    "cluster_entropy": 0.83,
    "num_questions": 1000
  }
}
```

#### `dataset_quality_by_group.csv`

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

### 10.2 模型报告

#### `model_overall_report.csv`

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

#### `model_by_question_mode.csv`

字段：

```text
model_name
question_mode
num_questions
accuracy
exact_match
f1
precision
recall
semantic_similarity
judge_correctness
judge_faithfulness
judge_hallucination
```

#### `model_by_topic.csv`

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

#### `model_by_difficulty.csv`

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

#### 交叉维度报告

```text
model_by_question_mode_and_difficulty.csv
model_by_topic_and_question_mode.csv
```

---

## 11. 模块设计

建议新增：

```text
benchforge/agents/model_eval_agent/
├── agent.py
├── schema.py
├── config_loader.py
├── run_context.py
├── output_resolver.py
├── dataset_metric_executor.py
├── model_runner.py
├── auto_metric_executor.py
├── llm_judge_executor.py
├── aggregator.py
└── report_writer.py
```

自动指标放在：

```text
benchforge/evaluation/metrics/
├── registry.py
├── accuracy.py
├── exact_match.py
├── token_f1.py
├── rouge_l.py
├── bleu.py
├── bertscore.py
├── semantic_similarity.py
├── citation_score.py
└── diversity_score.py
```

---

## 12. 执行流程

```text
1. load config
2. expand env vars
3. infer task_id / run_id
4. merge model defaults
5. build eval_signature
6. resolve output_dir
7. save resolved_config.yaml
8. load validated questions
9. run dataset metrics
   - citation_score
   - diversity_score
10. run candidate models
11. run automatic metrics by question_mode
12. run LLM Judge by question_mode
13. aggregate dataset report
14. aggregate model report
15. write CSV / JSON reports
```

伪代码：

```python
class ModelEvaluationAgent:
    def run(self, config_path: str, runtime_context: RuntimeContext | None = None):
        config = load_model_eval_config(config_path)
        run_context = resolve_run_context(config.run, runtime_context)
        output_dir = resolve_model_eval_output_dir(config, run_context)
        save_resolved_config(config, output_dir)

        questions = load_validated_questions(config.run.input_paths)

        dataset_scores = self.dataset_metric_executor.evaluate(
            questions=questions,
            metric_specs=config.dataset_evaluation.metrics,
            output_dir=output_dir / "dataset_report",
        )

        model_responses = self.model_runner.run_all(
            questions=questions,
            models=config.models.candidate_models,
            output_dir=output_dir / "model_report",
        )

        auto_scores = self.auto_metric_executor.evaluate(
            questions=questions,
            model_responses=model_responses,
            metric_plans=config.metrics,
            output_dir=output_dir / "model_report",
        )

        judge_scores = None
        if config.judge.enabled:
            judge_scores = self.llm_judge_executor.evaluate(
                questions=questions,
                model_responses=model_responses,
                metric_plans=config.metrics,
                judge_model=config.models.judge_model,
                prompt_system=config.judge.prompt_system,
                prompt_user=config.judge.prompt_user,
                output_dir=output_dir / "model_report",
            )

        self.aggregator.write_dataset_reports(
            questions=questions,
            dataset_scores=dataset_scores,
            output_dir=output_dir / "dataset_report",
        )

        self.aggregator.write_model_reports(
            questions=questions,
            auto_scores=auto_scores,
            judge_scores=judge_scores,
            output_dir=output_dir / "model_report",
        )
```

---

## 13. 第一版不实现的内容

第一版暂不实现：

```text
pairwise
sampling
多 judge ensemble
claim-level judge
复杂人工校准阈值
可选保存开关
复杂运行时配置
```

这些可以后续作为 v2 扩展。

---

## 14. 最终结论

新的评估智能体第一版应实现：

```text
输入：
  run
  dataset_evaluation
  models
  metrics
  judge

核心能力：
  1. 自动推导 run_id 和输出目录
  2. 自动计算当前数据集 citation_score / diversity_score
  3. 使用统一 Metric Registry 执行自动评分
  4. 按 question_mode 执行 LLM Judge
  5. 自动评分记录 question_ids + scores + models
  6. LLM Judge 记录完整 trace
  7. dataset_report 和 model_report 分开保存
  8. 输出多维聚合表格
```

这个方案比之前更贴近你现有的题目验证智能体风格，也避免了过度设计。
