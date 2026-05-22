# BenchForge 技术设计

BenchForge 是一个规划中的多智能体框架，用于自动构建和评测 LLM 基准。本文档在当前 `docs/plan.md` 与 `docs/multi-agent-framework-design.md` 的基础上，进一步细化为面向实现的技术设计。

当前仓库仍然是一个规划与参考工作区，尚不存在生产级代码包。后续实现应当在仓库根目录创建新的 BenchForge 代码库，并将 `reference/` 下的所有代码视为只读参考材料。

## 1. 参考实现审计

### 1.1 YourBench

本地路径：`reference/code/yourbench`

YourBench 是 BenchForge 在“文档到问题生成”流水线方向上最强的实现参考。

可复用思路：

- `conf/schema.py`：基于 Pydantic 的配置模型、默认值与校验。
- `conf/loader.py`：YAML 加载、环境变量展开、按 stage 是否存在启用、prompt 加载、模型角色分配。
- `pipeline/handler.py`：通过 stage registry 执行有序流水线。
- `pipeline/ingestion.py`：Markdown / text / HTML / PDF 摄取、可选的 LLM PDF 提取、文档元数据记录。
- `pipeline/summarization.py`：具备 token 感知能力的层级摘要。
- `pipeline/chunking.py`：token 分块、确定性 chunk ID、多跳 chunk 组合采样。
- `pipeline/question_generation/_core.py`：单跳、多跳、跨文档生成的共享流程。
- `utils/question_schemas.py`：开放问答与选择题的默认 Pydantic schema。
- `utils/schema_loader.py` 与 `utils/schema_prompt_generator.py`：自定义输出 schema 加载与 prompt 指令生成。
- `utils/parsing_engine.py`：从 `<output_json>` 标签、fenced JSON 以及候选 JSON 中进行稳健解析。
- `utils/inference/inference_core.py`：异步模型调用、按模型并发控制、重试/退避、token 统计与指标记录。
- `pipeline/prepare_lighteval.py`：合并不同问题子集，生成可直接评测的数据集，并保留来源追踪。
- `pipeline/citation_score_filtering.py`：基于模糊匹配的引用落地分数。
- `utils/dataset_engine.py`：本地 / Hugging Face 数据集保存与加载、子集管理、JSONL 导出。

需要“适配”而不是直接照搬的部分：

- YourBench 是流水线中心的，而 BenchForge 需要面向规划器驱动的迭代执行。
- YourBench 将 stage 输出存储为数据集子集；BenchForge 应以类型化 artifact 记录输出，并支持任务级引用。
- YourBench 的问题生成 I/O 应当比早期草案设想的更原样复用。BenchForge 应保留其围绕 `question_mode`、prompt template、`question_schema`、解析后的 JSON 行，以及 `QuestionRow` 风格溯源字段的 schema 驱动生成契约，例如 `document_id`、`chunk_ids`、`thought_process`、`raw_response`、`citations`、`generator_model`。
- 若启用弱点分析，生成阶段产生的单个 `required_capability` 能力描述文本，与评估阶段产生的 `failed_capability_description` 应共同作为后续分析基础，以控制成本。Analyzer 默认只做归一化、聚合或嵌入，除非未来扩展开启更重的能力标注流程。
- YourBench 的问题校验主要偏向 schema 与解析；BenchForge 需要一个专门的验证 agent，并输出明确的拒绝原因与批次级指标。

### 1.2 AutoBencher

本地路径：`reference/code/AutoBencher`

AutoBencher 是 BenchForge 在“迭代式主题探索”和“反馈驱动基准生成”方向上最强的实现参考。

可复用思路：

- `wiki_autobencher.py:get_summary_of_results`：按类别聚合评测结果。
- `wiki_autobencher.py:summarize_over_history`：将历史轮次结果整理成 planner 上下文。
- `wiki_autobencher.py:_generate_categories_targetacc_augmented`：围绕目标准确率区间提出候选类别。
- `wiki_autobencher.py:_refine_categories_targetacc_augmented`：结合 Wikipedia 搜索结果扩展和细化 LLM 提议的类别。
- `wiki_autobencher.py:generate_full_qa`：从类别规划到页面检索、显著性排序、QA 生成、模型测试、历史更新的迭代流程。
- `wiki_autobencher.py:saliency_rerank`：使用 pageviews 作为重要性信号。
- `multilingual_autobencher.py`：类别 + 目标语言联合规划与翻译。
- `math_autobencher.py`：面向目标准确率的子类规划与工具辅助答案生成。
- `tool_util.py:search_related_pages` 与 `search_step`：Wikipedia 搜索 / 页面获取模式。
- `tool_util.py:test_taker_inference` 与 `fast_compare_answers`：答题模型评测与 judge-model 比较。

应避免的部分：

- `tool_util.py` 包含硬编码的 Wikimedia 凭据。不要复用密钥，也不要原样复制这部分代码。
- 这些脚本依赖硬编码缓存路径、临时输出文件，以及直接使用 `os.system` 进行调度。
- JSON 解析依赖脆弱的代码块提取。BenchForge 应使用 Pydantic 校验与结构化 LLM 输出。
- 模型 / provider 处理与实验逻辑混杂。BenchForge 应通过统一模型客户端接口隔离 provider 调用。

### 1.3 EvalTree

本地路径：`reference/code/EvalTree`

EvalTree 是 BenchForge 在 capability 标注、capability tree 构建、置信区间与 weakness profile 提取方向上最强的实现参考。

可复用思路：

- `EvalTree/stage1-CapabilityAnnotation/annotate.py`：为每个 benchmark 实例标注 capability 描述。
- `EvalTree/stage2-CapabilityEmbedding/embedding.py`：对 capability 描述做 embedding。
- `EvalTree/stage3-RecursiveClustering/build.py`：递归聚类 capability embedding，并通过 cosine silhouette score 选择聚类数。
- `EvalTree/stage4-CapabilityDescription/describe.py`：递归汇总子 capability，生成父 capability 描述。
- `EvalTree/WeaknessProfile/confidence_interval.py`：计算节点级性能与二项分布置信区间。
- `EvalTree/WeaknessProfile/extract_subtrees.py`：提取表现最差的细粒度子树节点。
- `EvalTree/WeaknessProfile/profile-generation_varying-threshold.py`：在不同阈值下生成 weakness profile。
- `EvalTree/stage3-RecursiveClustering/locate.py`：将新实例通过 embedding 与聚类预测定位到已有 capability tree 中。

需要适配的部分：

- EvalTree 假定 benchmark 实例与结果已经存在于固定数据集目录中；BenchForge 应在执行过程中生成这些 artifact。
- EvalTree 的 tree node 以原始嵌套 dict 与 pickled KMeans 对象存储；BenchForge 应使用显式的类型模型封装 tree，并保持序列化元数据可预测。
- EvalTree 的分析是事后分析；BenchForge 应将分析结果回传给 planner，作为覆盖缺口与后续任务建议。

### 1.4 BenchAgents

本地路径：`reference/paper/BenchAgents.pdf`

本仓库中没有 BenchAgents 的本地代码实现。在当前环境下，应将 BenchAgents 视为“多智能体、多轮基准构建”的概念性参考，而不是可直接复用代码的来源。

本地环境当前既没有 `pdftotext`，也没有 Python PDF 解析库；可用工具也未能从 `BenchAgents.pdf` 中提取出有效纯文本。因此，实现规划应仅将 BenchAgents 作为概念参考，而具体工程决策则应扎根于可检查代码的 YourBench、AutoBencher 与 EvalTree。

## 2. 目标架构

BenchForge 应采用“强中心规划器 + 有界局部自治 worker agent”的架构。

```text
UserRequest
  -> PlannerAgent 创建或更新 Blueprint
  -> Orchestrator 分发 TaskSpec
  -> Worker agents 返回 TaskResult
  -> PlannerAgent 更新 Blueprint
  -> 重复，直到满足停止条件或生成最终报告
```

核心架构规则：

- `Blueprint` 是唯一的全局状态来源。
- 只有 `PlannerAgent` 可以修改 `Blueprint`。
- Worker agent 仅接收任务作用域输入与 artifact 引用。
- Worker agent 返回 `TaskResult`；它们可以建议后续动作，但不能直接调度全局工作。

### 2.1 基于参考实现的修正

早期草案的方向是对的，但在若干点上过于泛化。以下修正应视为权威设计：

- `PlannerAgent` 负责主题优化、轮次推进、预算控制与停止条件，不直接执行页面检索。
- 在当前设计中，检索不是一个独立的一等 agent。相反，检索能力存在于共享的 `retrieval_runtime` 中，由 `QuestionGeneratorAgent` 在执行生成任务时调用。
- `QuestionGeneratorAgent` 的输入应组织为结构化对象，而不是一组平铺顶层字段。这是为了更贴近 YourBench 的 `stage_cfg + dataset subset` 模式，并让 schema 校验保持可管理。
- `QuestionGeneratorAgent` 的输出应复用 YourBench `QuestionRow` 已有字段语义。题目来源应尽量直接沿用 YourBench 风格的 `document_id`、`chunk_ids` 与 `citations`；BenchForge 只额外增加最小的 `generation_metadata` 与 `lineage`，而不是再维护一套宽泛的 `provenance` 真相源。
- `ModelEvaluatorAgent` 在答案错误时，应输出结构化的 `failed_capability_description`，作为后续弱点画像与弱点树解释层的主要输入。
- `ModelEvaluatorAgent` 负责收集模型答案并调用共享的 `judge_runtime`。judge 层必须被视为可复用基础设施，而不是临时嵌入 evaluator 逻辑中的实现。
- 受 EvalTree 启发的分析仍然是事后、聚合式的。BenchForge 应适配其 tree 构建与 weakness 提取逻辑，但为了控制成本，默认不再增加独立的逐题 capability annotation 调用，而是在生成阶段直接产出单个 `required_capability` 能力描述文本，并在评估阶段补充失败能力描述。

推荐包结构：

```text
benchforge/
  __init__.py
  cli.py
  config.py
  orchestrator.py
  agents/
    __init__.py
    planner.py
    question_generator.py
    question_validator.py
    model_evaluator.py
    analyzer.py
  artifacts/
    __init__.py
    store.py
  models/
    __init__.py
    client.py
    fake.py
  pipelines/
    __init__.py
    documents.py
    questions.py
    evaluation.py
    analysis.py
  schemas/
    __init__.py
    artifact.py
    blueprint.py
    question.py
    task.py
  prompts/
    question_generation.md
    question_validation.md
    answer_judging.md
    capability_annotation.md
tests/
  unit/
  integration/
```

## 3. 核心数据契约

BenchForge 应使用 Pydantic v2 实现这些契约，并通过显式 enum 提供稳定的机器可读值。

### 3.1 BlueprintSpec

`BlueprintSpec` 是单次运行的固定计划规格。MVP 中它应尽量小，只保留真正影响运行边界与最终输出的配置。

建议字段：

- `blueprint_spec_id`：稳定的 spec ID。
- `goal`：用户目标的简洁规范化描述。
- `source_documents`：输入文档或输入数据源引用。MVP 先支持本地文档列表。
- `target_models`：待评估模型列表。这是顶层显式字段，而不是埋在 `evaluation_scope` 中。
- `dataset_policy`：目标问题总量、每轮生成量、分布约束与去重要求。
- `question_policy`：允许的问题类型、答案格式、引用要求、长度限制。
- `validation_policy`：schema 校验、证据校验、近重复检查与失败阈值。
- `evaluation_policy`：评分方式、judge model、重试策略与失败处理。
- `multilingual`：多语言配置，仅在启用时才基于 canonical 问题派生多语言版本。
- `weakness_tree`：弱点树配置，仅在启用时才在最终基准集合上构建能力树 / 弱点树。
- `budget_policy`：token、成本、时间或调用次数上限。
- `max_rounds`：最大轮次。
- `stop_conditions`：停止条件定义。

推荐子结构：

- `multilingual.enabled`
- `multilingual.target_languages`
- `multilingual.strategy`
- `weakness_tree.enabled`
- `weakness_tree.build_timing`

约束规则：

- `multilingual.enabled == false` 时，只生成 canonical 问题，不生成多语言变体。
- `multilingual.enabled == true` 时，先生成 canonical 问题，再参考 AutoBencher 思路派生多语言版本。
- `weakness_tree.enabled == true` 且 `weakness_tree.build_timing == "final_only"` 时，能力树与弱点树仅在蓝图达到终止条件后构建。

### 3.2 RunState

`RunState` 是一次运行中唯一可变的全局状态。MVP 不应让它承担大量可从 artifact 反查的派生摘要。

建议字段：

- `run_id`：稳定的运行 ID。
- `blueprint_spec_id`：指向固定 `BlueprintSpec` 的引用。
- `status`：`draft`、`running`、`paused`、`completed` 或 `failed`。
- `current_round`：当前轮次编号。
- `planner_state`：planner 私有状态，例如 `topic_queue`、已探索主题、轻量 coverage summary。
- `artifact_refs`：当前运行下可用 artifact 的引用索引。
- `budget_usage`：已消耗的 token、成本、时间与调用次数。
- `active_task_batch_id`：恢复执行时当前关注的任务批次指针，例如最近一次发出且尚未完全整合的任务批次。
- `decision_log`：planner 决策及其理由。

设计规则：

- `BlueprintSpec` 是固定真相源。
- `RunState` 只记录恢复运行所必需的可变状态。
- `TaskResult` 应通过任务日志或 artifact 存储按 `run_id` / `round_id` / `task_id` 反查，而不是作为“最近结果引用”缓存进 `RunState`。
- 覆盖率、评测汇总、弱点分析等默认从 artifact 重建，不作为 `RunState` 主字段常驻。

### 3.3 TaskSpec

`TaskSpec` 是 PlannerAgent 分发给某个 worker 的最小可执行任务描述。MVP 不需要把它设计成通用工作流引擎协议。

建议字段：

- `task_id`
- `task_type`
- `run_id`
- `round_id`
- `input_refs`
- `params`
- `acceptance_criteria`

简化规则：

- `agent_type` 与 `task_type` 高度重合，MVP 先只保留 `task_type`。
- `constraints`、`objective`、`retry_policy` 等大多可以折叠进 `params` 或全局默认策略。
- `depends_on` 先通过 `input_refs` 间接表达。

### 3.4 TaskResult

`TaskResult` 是 worker 返回给 planner 的最小反馈对象。

建议字段：

- `task_result_id`
- `task_id`
- `status`
- `artifact_refs`
- `metrics`
- `errors`

设计规则：

- `task_result_id` 是单次结果实例的稳定主键，用于区分同一 `task_id` 的多次重试或重复执行结果。
- `run_id`、`round_id`、`blueprint_spec_id` 等可通过 `task_id` 反查，不必在结果里重复。
- `needs_replan` 不必作为显式布尔字段，planner 应根据 `metrics` 与 `errors` 自行判断是否重规划。
- `suggested_next_tasks` 不作为核心协议字段，后续若需要可作为调试信息追加。

## 4. Artifact 模型

BenchForge 应将任务输出存储为少量高价值 artifact。MVP 中不必将每个阶段都拆成独立顶层类型。

单机实现可将 JSON 与 JSONL 文件保存在 `runs/<run_id>/artifacts/` 下。

推荐 MVP artifact 类型：

| Artifact | Producer | Consumer | Notes |
| --- | --- | --- | --- |
| `SourceDocument` | ingestion / retrieval pipeline | QuestionGenerator, QuestionValidator | 标准化后的来源文档，chunk 可作为内嵌字段 |
| `QuestionRecord` | QuestionGenerator, QuestionValidator | 全流程 | 统一问题池中的核心对象，覆盖生成、验证与题目生命周期状态 |
| `EvaluationRecord` | ModelEvaluator | Analyzer, PlannerAgent | 独立的逐题、逐模型评测结果，适配大规模评测 |
| `AnalysisReport` | Analyzer | PlannerAgent, User | 轻量覆盖分析，或最终能力树 / 弱点树结果 |
| `RunReport` | PlannerAgent | User | 运行总结 |

### 4.1 统一问题池

BenchForge 的核心数据对象应是统一的问题池，而不是按阶段拆成 `CandidateQuestion`、`ValidatedQuestion`、`RejectedQuestion` 等多个平行 artifact。

建议使用统一的 `QuestionRecord`：

- `question_id`
- `run_id`
- `created_round`
- `updated_round`
- `status`
- `question`
- `question_mode`
- `choices`
- `answer`
- `language`
- `domain`
- `document_id`
- `chunk_ids`
- `citations`
- `required_capability`
- `estimated_difficulty`
- `language_variants`
- `generation_metadata`
- `lineage`
- `validation`

推荐状态枚举：

- `draft`
- `generated`
- `validated`
- `rejected`
- `archived`

设计规则：

- 新题、待验证题、已验证题、被拒题都属于同一个 `QuestionRecord`，区别只在于 `status` 与嵌套字段内容。
- `created_round` / `updated_round` 用于追踪题目生命周期，不再额外设计独立轮次归属表。
- `QuestionRecord` 不直接内嵌评测结果；大规模评测场景下，逐题、逐模型结果应独立存储为 `EvaluationRecord`，并通过 `question_id` 关联。
- YourBench 风格的 `document_id`、`chunk_ids` 与 `citations` 是题目来源真相源；下游组件不再同时依赖另一套并行来源字段。
- `required_capability` 在生成阶段与题目一并产出，但它只表示单个题目的能力描述文本，用作后续归一化、embedding 与聚类的原始信号，而不是最终能力标签。
- `failed_capability_description` 不在生成阶段写入 `QuestionRecord` 主字段，而是在评估阶段按模型、按错误样本写入独立的 `EvaluationRecord`。
- 多语言题目不应被视作全新问题；应作为 canonical 问题的 `language_variants` 或等价嵌套结构存在。

推荐 `language_variants` 子字段：

- `language`
- `question`
- `choices`
- `answer`
- `citations`

推荐 `generation_metadata` 子字段：

- `prompt_template_id`
- `generator_model`
- `question_type`
- `thought_process`
- `additional_instructions`
- `raw_response`

推荐 `lineage` 子字段：

- `parent_question_id`
- `relation_type`

推荐 `lineage.relation_type` 枚举：

- `canonical`
- `translation`
- `repair`
- `regeneration`

推荐 `validation` 子字段：

- `status`
- `issues`
- `validated_at`

### 4.2 独立评测记录

建议使用独立的 `EvaluationRecord`：

- `evaluation_id`
- `run_id`
- `question_id`
- `model_id`
- `model_answer`
- `is_correct`
- `score`
- `judge_model`
- `prompt`
- `failed_capability_description`
- `error_type`
- `judge_rationale`
- `confidence`
- `evaluated_at`

设计规则：

- `EvaluationRecord` 是大规模评测场景下的独立事实表；同一题目可对应多个模型、多个批次或重试产生的多条记录。
- `QuestionRecord` 不缓存 `evaluations` 或 `evaluation_refs`，避免题目对象膨胀、并发写冲突与双写一致性问题。
- 某题是否已被完整评测，应由 `run_id + question_id + target_models` 对应的 `EvaluationRecord` 集合派生，而不是回写到 `QuestionRecord.status`。
- 模型原始回答、judge 模型、评分结果与评测 prompt 都属于 `EvaluationRecord` 的职责范围。
- Judge 相关输出，包括 `failed_capability_description`、`error_type`、`judge_rationale` 与 `confidence`，都属于 `EvaluationRecord` 的职责范围。

### 4.3 最终树分析

`AnalysisReport` 分两类：

- 运行中轻量分析：覆盖率、难度分布、问题类型分布、归一化后的 `required_capability` 分布与错误率分布。
- 终局重分析：仅在 `weakness_tree.enabled == true` 时，先基于归一化后的 `required_capability` 文本构建稳定的能力树，再结合评估失败样本中的 `failed_capability_description` 形成弱点解释层。
- 当蓝图达到终止条件后，Planner 必须显式发出一次最终 `TaskSpec(analyzer, mode="final")`；该任务产出的最终 `AnalysisReport` 应作为 `RunReport` 的核心输入之一，而不是由 Planner 跳过 Analyzer 直接生成最终用户报告。

推荐最小 `AnalysisReport` 字段：

- `report_id`
- `run_id`
- `mode`
- `coverage_summary`
- `capability_distribution`
- `error_summary`
- `recommendations`
- `capability_tree`
- `weakness_profile`

推荐最小 `RunReport` 字段：

- `run_id`
- `blueprint_spec_id`
- `final_status`
- `stop_reason`
- `dataset_summary`
- `evaluation_summary`
- `analysis_report_ref`
- `budget_summary`
- `decision_summary`

## 5. Agent 职责与 I/O

### 5.1 PlannerAgent

目的：

- 将用户请求转化为 `BlueprintSpec` 与初始 `RunState`。
- 维护统一问题池的轮次推进。
- 选择下一组任务序列。
- 将 `TaskResult` 融入更新后的 `RunState`。
- 决定继续、重试、再生成、评测、轻量分析还是停止。

输入：

- 用户请求。
- 当前 `BlueprintSpec`。
- 若为续跑，则包含当前 `RunState`。
- 新产生的 `TaskResult` 对象。

输出：

- 首次初始化时输出 `BlueprintSpec`。
- 更新后的 `RunState`。
- 一个或多个 `TaskSpec`。
- 停止时输出最终 `RunReport`。

核心流程：

1. 将用户请求规范化为 `BlueprintSpec`。
2. 创建初始 `RunState`：轮次为 `1`，预算消耗清零，初始化 `planner_state`。
3. 基于 `goal`、`source_documents`、`target_models` 与当前覆盖情况创建初始 topic plan。
4. 为第一轮分发问题生成任务。
5. 在验证结束后，更新问题池中相应 `QuestionRecord` 的 `status` 与 `validation` 字段。
6. 在评测结束后，接收独立的 `EvaluationRecord` 结果，并据此判断哪些题目、哪些模型已经完成评测。
7. 在每轮结束时仅执行轻量分析，并更新 `planner_state` 与 `budget_usage`。
8. 当达到目标题量、覆盖要求、预算上限或停止条件时，先将运行状态切换到终局收尾阶段，而不是立即返回最终报告。
9. 在终局收尾阶段，由 Planner 显式发出 `TaskSpec(analyzer, mode="final")`，将最终问题池、验证结果、全部模型评测结果与分析配置送入 Analyzer。
10. Planner 接收最终 `AnalysisReport` 后，再整合运行摘要、预算消耗、覆盖统计、能力树 / 弱点树结果与后续建议，输出最终 `RunReport`。

### 5.2 QuestionGeneratorAgent

目的：

- 执行当前 topic plan 下的“检索 + 生成”任务。
- 通过共享 runtime 工具检索 Wikipedia 内容。
- 标准化来源文本、选择证据，并生成候选问题。
- 一次性产出 canonical 问题、标准答案与来源证据；题目来源字段尽量直接沿用 YourBench，BenchForge 只额外补充最小 `generation_metadata` 与 `lineage`，生成模型只额外产出单个 `required_capability` 能力描述文本。
- 若 `multilingual.enabled == true`，再基于 canonical 问题派生多语言版本。

输入：

- `TopicPlan` artifact ID。
- `QuestionGenerationInput`，组织为以下分组：
  - `topic_context`：目标类别、目标准确率区间、排除主题、planner 提示。
  - `retrieval_input`：语言、最大页面数、显著性策略、排除页面标题、source policy。
  - `evidence_input`：chunking 策略、跨文档策略、最大 chunks、证据选择策略。
  - `generation_input`：question mode、目标数量、question schema、prompt template ID、额外指令。
  - `output_control`：是否必须提供证据、是否必须提供 `required_capability` 能力描述文本、是否必须结构化输出。
- 来自 `BlueprintSpec` 的共享生成策略，以及来自 `RunState` 的当前上下文。

输出：

- `SourceDocument` artifacts。
- `QuestionRecord` artifacts。
- 生成指标与问题列表。

推荐流程：

1. 读取当前 `TopicPlan` 与任务输入中的 retrieval 配置。
2. 调用 `retrieval_runtime` 搜索并抓取与规划类别相关的 Wikipedia 页面。
3. 将页面标准化为 `SourceDocument` artifact，并附加如 pageviews 等显著性信号。
4. 以确定性方式对证据分块，并将 chunk 信息内嵌到文档或问题来源引用中。
5. 使用 YourBench 风格的 `question_mode`、prompt template 与 `question_schema` 构建 schema 驱动 prompt。
6. 调用 `model_runtime` 并解析其 JSON 数组输出。
7. 将每一行解析结果转换为统一的 `QuestionRecord`，并保留 YourBench 风格字段：
   - `question`
   - `answer` 或 `self_answer`
   - `language`
   - `domain`
   - `estimated_difficulty`
   - `question_type` 或 `self_assessed_question_type`
   - `question_mode`
   - `thought_process`
   - `citations`
   - 当 `question_mode == "multi-choice"` 时包含 `choices`
   - `document_id`
   - `chunk_ids`
   - `generator_model`
   - `raw_response`
   - `additional_instructions`
8. 将 `prompt_template_id`、`generator_model`、`question_type`、`thought_process`、`additional_instructions` 与 `raw_response` 归入 `generation_metadata`；将父题关系与 translation / repair / regeneration 关系归入最小 `lineage`；生成模型只需同时输出单个 `required_capability` 能力描述文本。
9. 若启用多语言，则参考 AutoBencher 的多语言思路为 canonical 问题生成 `language_variants`，而不是生成另一套独立题目。
10. 保存 artifact，并返回 `TaskResult`，其中包括已检索页面数、生成问题数与失败原因。

参考映射：

- 文档处理：YourBench `ingestion.py`。
- 摘要 / 分块：YourBench `summarization.py` 与 `chunking.py`。
- 生成 prompt 与 schema：YourBench `question_schemas.py`、`schema_prompt_generator.py` 与 `question_generation/_core.py`。
- 主题 / 来源扩展：AutoBencher `wiki_autobencher.py` 与 `tool_util.py`。

### 5.3 QuestionValidatorAgent

目的：

- 作为问题质量闸门。
- 更新问题池中题目的验证状态，而不是产出新的问题类型。

输入：

- `QuestionRecord` artifact ID 列表。
- 当前 `validation_policy`。
- 已接受问题的摘要。
- 用于证据检查的来源文档 / chunk。

输出：

- 更新后的 `QuestionRecord` artifacts。
- 批次验证指标。
- 当通过率或覆盖不足时的重规划建议。

验证检查项：

- 必需字段是否齐全。
- 问题模式是否符合允许类型。
- 选择题是否恰好有四个选项，且答案字母合法。
- 开放问答答案是否非空，且不只是一个选择题字母。
- 来源证据是否存在，且与来源 chunk 有重叠。
- 问题是否可以从提供的证据中回答。
- 问题是否不是近重复。
- 难度、语言、领域与 `required_capability` 能力描述文本是否满足任务约束，且不与题目语义明显冲突。

参考映射：

- Schema 与解析检查：YourBench `QuestionRow`、`parsing_engine.py`。
- 引用落地：YourBench `citation_score_filtering.py`。

### 5.4 ModelEvaluatorAgent

目的：

- 在已验证问题上运行目标模型。
- 对预测结果打分。
- 在答案错误时生成结构化失败能力描述。
- 将逐题、逐模型评测结果写入独立的 `EvaluationRecord`。

输入：

- `QuestionRecord` artifact ID 列表，且仅选择 `status == validated` 的题目。
- 目标模型配置。
- Evaluation policy。
- 若有需要，包含 judge prompt 与 rubric。

输出：

- `EvaluationRecord` artifacts。
- 每模型指标。
- 按领域、语言、问题类型、归一化后的 `required_capability`、错误类型与失败能力描述的汇总。
- 成本、token、延迟与失败统计。

推荐流程：

1. 基于已验证问题构建模型输入 prompt。
2. 结合并发与重试策略执行目标模型推理。
3. 对可直接精确匹配的题目优先进行直接评分。
4. 对开放问答使用 judge model 做语义评分。
5. 若答案错误，则要求 judge 额外输出结构化失败分析，包括：
   - `failed_capability_description`
   - `error_type`
   - `judge_rationale`
   - `confidence`
6. 将结果写入独立的 `EvaluationRecord`，其中包含 `is_correct`、judge verdict、rationale、confidence 与失败能力描述；该步骤与正确性判定使用同一次 judge 调用完成。
7. 聚合指标并返回给 planner 与 analyzer。

参考映射：

- 模型调用与指标：YourBench `inference_core.py`。
- 答案判定与历史汇总：AutoBencher `fast_compare_answers`、`get_summary_of_results`。

### 5.5 AnalyzerAgent

目的：

- 在运行中执行轻量分析。
- 在终局阶段基于归一化后的 `required_capability` 文本构建能力树，并结合失败能力描述生成 weakness tree。
- 在蓝图达到终止条件后，消费最终问题池与全部评测结果，生成面向用户的最终评估分析结果。
- 向 PlannerAgent 推荐下一轮主题或覆盖不足区域。

输入：

- `QuestionRecord` artifact ID 列表。
- `EvaluationRecord` artifact ID 列表，或可按 `run_id` / `question_id` 查询到的评测结果集合。
- 当前蓝图中的 `weakness_tree` 配置。
- 生成阶段产生的 `required_capability` 能力描述文本，以及评估阶段产生的失败能力描述与独立评测结果。
- 若为终局分析，则额外输入完整的运行级上下文，包括最终 `RunState`、覆盖摘要、预算使用情况与目标模型汇总指标。

输出：

- 运行中输出轻量 `AnalysisReport`。
- 终局时可输出包含 `CapabilityTree` 与 `WeaknessProfile` 的 `AnalysisReport`。
- 若为终局分析，还应输出可直接并入 `RunReport` 的评估结论摘要，包括总体表现、主要薄弱能力、主要错误类型、覆盖缺口与建议后续补题区域。
- 覆盖缺口与后续关注区域建议。

推荐流程：

1. 读取问题池中的 `required_capability` 能力描述文本，以及与之关联的 `EvaluationRecord` 结果集合。
2. 对 `required_capability` 做归一化、embedding 与聚类，构建稳定的 capability tree。
3. 在运行过程中，只输出覆盖率、难度分布、语言分布、问题类型分布、归一化后的 `required_capability` 分布与错误率分布等轻量摘要。
4. 仅当 `weakness_tree.enabled == true` 且运行已终止时，将最终评测结果附着到 capability tree 节点，并计算每个节点的错误率与置信区间。
5. 同时聚合错误样本中的 `failed_capability_description` 与 `error_type`，作为弱点节点的解释层。
6. 使用基于阈值的置信区间逻辑提取低表现或高风险子树，形成最终 weakness tree。
7. 若为终局分析，进一步生成面向用户报告的评估结论摘要，明确总体表现、主要薄弱能力、主要错误类型、覆盖缺口与后续建议。
8. 返回面向 planner 或用户的建议，包括薄弱能力节点、主要错误类型与高频失败能力描述。

参考映射：

- Capability 标注：EvalTree `stage1-CapabilityAnnotation/annotate.py`。
- Embedding：EvalTree `stage2-CapabilityEmbedding/embedding.py`。
- Tree 构建：EvalTree `stage3-RecursiveClustering/build.py`。
- 节点描述：EvalTree `stage4-CapabilityDescription/describe.py`。
- 置信区间与 weakness 提取：EvalTree `WeaknessProfile`。

## 6. 端到端工作流

### 6.1 初始运行

```text
UserRequest
  -> PlannerAgent 创建 Blueprint v1
  -> PlannerAgent 发出 TaskSpec(question_generator)
  -> QuestionGeneratorAgent 产出 SourceDocument 与 QuestionRecord artifacts
  -> PlannerAgent 发出 TaskSpec(question_validator)
  -> QuestionValidatorAgent 更新 QuestionRecord 的 validation 与 status
  -> PlannerAgent 判断是否已有足够的有效问题
  -> PlannerAgent 发出 TaskSpec(model_evaluator)
  -> ModelEvaluatorAgent 产出独立 EvaluationRecord artifacts
  -> PlannerAgent 发出 TaskSpec(analyzer)
  -> AnalyzerAgent 产出轻量 AnalysisReport
  -> PlannerAgent 更新 RunState，并决定开始下一轮或进入终局收尾阶段
  -> PlannerAgent 发出 TaskSpec(analyzer, mode=final)
  -> AnalyzerAgent 消费最终问题池、验证结果、全部 EvaluationRecord 与运行摘要，产出最终 AnalysisReport
  -> PlannerAgent 将最终 AnalysisReport 整合进 RunReport
  -> PlannerAgent 输出 RunReport
```

### 6.2 重规划循环

当出现以下任一情况时，PlannerAgent 应重新规划：

- 有效问题数量低于每轮目标值。
- 验证通过率低于 `validation_policy.min_batch_pass_rate`。
- 来源检索产生的可用文档过少。
- 评测失败率超过策略阈值。
- 某个领域 / 语言 / 问题类型分布未达到目标比例。
- 轻量分析发现某些主题、语言或问题类型覆盖不足。
- 预算接近耗尽。

AutoBencher 风格的目标准确率区间应存在于 `topic_state` 中。例如，当某个领域的观测准确率高于目标时，planner 可通过提升难度生成更多题目；当准确率低于目标时，可收窄到更容易的子主题。

## 7. 实现原则

- 保持参考代码只读。
- 所有跨 agent 契约都使用 Pydantic v2。
- 先做本地 artifact 存储，Hugging Face 集成放在 MVP 之后。
- 单元测试与集成测试中使用确定性的 fake model client。
- 将 LLM prompt 版本化，存放在 `benchforge/prompts/`。
- 模型 provider 代码与 agent 逻辑分离。
- 不要复制 AutoBencher 中硬编码的凭据、直接输出文件约定或 shell 编排方式。
- 将生成期产生的单个 `required_capability` 能力描述文本视为能力树主信号，将评估期产生的 `failed_capability_description` 视为弱点解释层主信号。
- 每次 planner 更新都应通过 `decision_log` 保持可审计。
- 优先采用小而类型明确的模块，而不是一个巨大的编排脚本。

## 8. MVP 范围

第一版实现应构建一个仅本地运行的 MVP：

- CLI 接受 YAML 配置与本地文档。
- Planner 创建一个 `Blueprint`。
- QuestionGenerator 支持本地 `.md` 与 `.txt` 文档，并先生成 canonical 问题。
- 当 `multilingual.enabled == true` 时，再为 canonical 问题派生多语言版本。
- QuestionValidator 执行确定性的 schema、引用与重复检查，并更新统一问题池中的状态。
- QuestionGenerator 在生成题目时应同时输出单个 `required_capability` 能力描述文本，不额外增加独立 annotation 调用。
- ModelEvaluator 在测试中支持 fake model，并在真实运行中提供兼容 OpenAI 的客户端接口；同一次 judge 调用中应完成 `is_correct` 判定，并在答案错误时输出 `failed_capability_description`、`error_type` 与 `judge_rationale`。
- 大规模评测结果以独立 `EvaluationRecord` 保存，通过 `question_id` 与问题池关联，而不回写进 `QuestionRecord`。
- Analyzer 在运行中只生成轻量覆盖摘要；若 `weakness_tree.enabled == true`，则在终局基于归一化后的 `required_capability` 文本建能力树，并结合失败能力描述生成弱点树。
- Artifact 保存在 `runs/<run_id>/artifacts/` 下，问题主对象统一为 `QuestionRecord`。

推迟到 MVP 之后的能力：

- 完整的 web retrieval。
- Hugging Face 数据集上传。
- PDF / HTML / Word 摄取。
- 完整的 EvalTree KMeans 持久化与跨运行 tree 定位。
- UI 或 dashboard。
- 分布式执行。
