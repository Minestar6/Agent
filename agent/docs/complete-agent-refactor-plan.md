# 完整重构方案：从Pipeline到真正的Agent

## 一、工具分类体系

### 1.1 低层工具（原子操作）

**特点**：不需要决策，有明确的输入输出，直接执行

| 工具名 | 功能 | 输入 | 输出 |
|--------|------|------|------|
| `search_documents` | 搜索Wikipedia | query, max_pages | 搜索结果列表 |
| `fetch_document` | 获取文档内容 | page_url | SourceDocument |
| `chunk_document` | 文档分块 | document, chunk_size | SourceChunk列表 |
| `calculate_signals` | 计算信号分数 | text, summary | 分数字典 |
| `filter_questions` | 过滤题目 | 原始题目列表 | (通过, 失败)列表 |
| `parse_llm_response` | 解析LLM响应 | response_text | 结构化数据 |

**示例定义**：
```python
@ToolRegistry.register(
    name="search_documents",
    category="retrieval",
    description="搜索与主题相关的Wikipedia文档。",
    parameters={
        "query": {"type": "string", "required": True},
        "max_pages": {"type": "integer", "default": 5},
        "language": {"type": "string", "default": "en"}
    }
)
async def tool_search_documents(
    query: str,
    max_pages: int = 5,
    language: str = "en"
) -> ToolOutput:
    results = search_wikipedia(query, language, max_pages)
    return ToolOutput(
        success=True,
        result={"results": results, "count": len(results)},
        observation=f"搜索'{query}'找到{len(results)}个结果"
    )
```

---

### 1.2 中层工具（组合操作）

**特点**：有简单参数选择逻辑，但不复杂

| 工具名 | 功能 | 决策点 |
|--------|------|--------|
| `build_evidence_pool` | 构建证据池 | chunk_size, overlap |
| `sample_evidence` | 采样证据单元 | strategy类型, 采样数量 |
| `merge_multi_chunks` | 合并多证据 | 组合大小, max_tokens |
| `generate_document_summary` | 生成文档摘要 | 摘要长度 |

**示例定义**：
```python
@ToolRegistry.register(
    name="sample_evidence",
    category="selection",
    description="从证据池中选择适合当前目标的证据单元。",
    parameters={
        "topic": {"type": "string", "required": True},
        "target_mode": {"type": "string", "enum": ["qa", "multiple_choice"]},
        "target_difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
        "strategy": {"type": "string", "enum": ["broad_exploration", "gap_driven"], "default": "gap_driven"},
        "num_evidence": {"type": "integer", "default": 5},
        "prefer_multi_chunk": {"type": "boolean", "default": False}
    }
)
async def tool_sample_evidence(
    topic: str,
    target_mode: str,
    target_difficulty: str,
    strategy: str = "gap_driven",
    num_evidence: int = 5,
    prefer_multi_chunk: bool = False,
    agent_context: dict = None
) -> ToolOutput:
    pool = agent_context["evidence_pools"][topic]

    # 选择策略（简单的if-else，不需要LLM）
    if strategy == "broad_exploration":
        sampler = BroadExplorationSampling()
    else:
        sampler = GapDrivenSampling()

    batch = sampler.sample(
        pool=pool,
        target_mode=target_mode,
        target_difficulty=target_difficulty,
        num_evidence=num_evidence,
        prefer_multi_chunk=prefer_multi_chunk
    )

    return ToolOutput(
        success=True,
        result={"batch": batch, "selected_count": len(batch.single_chunk_ids) + len(batch.multi_chunk_ids)},
        observation=f"使用{strategy}策略选择了{len(batch.single_chunk_ids)}个单证据和{len(batch.multi_chunk_ids)}个多证据"
    )
```

---

### 1.3 高层工具（决策操作）

**特点**：需要LLM推理来决定关键参数，核心决策点

| 工具名 | 功能 | 需要LLM决策的参数 |
|--------|------|-------------------|
| `analyze_generation_gap` | 分析当前缺口 | 哪个缺口最紧急？为什么？ |
| `decide_retrieval_action` | 决定检索策略 | 需要扩展吗？用什么查询？ |
| `decide_generation_batch` | 决定生成批次 | 生成多少题？用多少证据？ |
| `evaluate_quality` | 评估生成质量 | 质量如何？什么原因？ |
| `plan_next_action` | 规划下一步行动 | 应该做什么？为什么？ |

**示例定义**：
```python
@ToolRegistry.register(
    name="analyze_generation_gap",
    category="analysis",
    description="深入分析当前缺口，识别最需要补充的题目类型及其原因。",
    parameters={
        "topic": {"type": "string", "required": True},
        "current_state": {"type": "object", "required": True},
        "evidence_stats": {"type": "object", "required": True},
        "history": {"type": "array", "default": []}
    }
)
async def tool_analyze_generation_gap(
    topic: str,
    current_state: dict,
    evidence_stats: dict,
    history: list = None,
    model_client = None
) -> ToolOutput:
    """这个工具内部使用LLM进行深度分析。"""

    prompt = f"""分析当前主题 {topic} 的缺口情况。

## 当前状态
- 剩余缺口: {current_state['remaining_counts']}
- 已完成: {current_state['completed_counts']}
- 当前轮数: {current_state['current_round']}

## 证据统计
- 单证据有效率: {evidence_stats.get('single_chunk_stats', {}).get('avg_valid_count', 0):.2f}
- 多证据有效率: {evidence_stats.get('multi_chunk_stats', {}).get('avg_valid_count', 0):.2f}

## 历史行动（最近3次）
{json.dumps(history[-3:], indent=2, ensure_ascii=False)}

## 分析要求
1. 识别最紧急的缺口（模式+难度组合）
2. 分析为什么这个缺口存在（证据不足？生成质量低？）
3. 评估当前证据是否足够支持填补该缺口
4. 给出具体建议

## 输出格式
```json
{{
  "primary_gap": "qa:hard",
  "gap_reason": "单证据的hard_score低(0.3)，但多证据有效率更优(0.8)",
  "evidence_sufficiency": "partial",
  "suggested_actions": [
    "使用多证据单元生成hard题目",
    "考虑扩展检索获取更复杂的证据"
  ],
  "confidence": 0.85
}}
```
"""

    response = await model_client.complete(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    analysis = parse_llm_response(response["text"])[0]

    return ToolOutput(
        success=True,
        result=analysis,
        observation=f"主缺口为{analysis['primary_gap']}，原因：{analysis['gap_reason']}"
    )
```

---

## 二、决策框架设计

### 2.1 三层决策架构

```
┌─────────────────────────────────────────────────────────┐
│                    任务分解器 (L1)                       │
│  输入：GenerationPlan（目标）                            │
│  输出：子任务列表 [任务1, 任务2, ...]                    │
│  工具：analyze_task_breakdown                           │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                    策略选择器 (L2)                       │
│  输入：子任务 + 当前状态 + 证据统计                       │
│  输出：执行策略 + 关键参数                                │
│  工具：decide_strategy_for_task                         │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                    参数优化器 (L3)                       │
│  输入：策略 + 历史表现 + 约束条件                         │
│  输出：优化后的参数配置                                   │
│  工具：optimize_parameters                              │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                    执行层                               │
│  调用中层和低层工具执行                                   │
└─────────────────────────────────────────────────────────┘
```

---

### 2.2 L1 任务分解器

**Prompt设计**：

```python
SYSTEM_PROMPT_TASK_DECOMPOSER = """你是问题生成任务分解专家。

## 你的职责
将整体生成目标分解为可执行的子任务序列。

## 输入
- GenerationPlan: 包含目标模式、难度分布、主题列表
- 约束条件: 最大轮数、预算等

## 输出格式
```json
{{
  "decomposition": [
    {{
      "task_id": "T1",
      "task_type": "retrieval",
      "description": "为主题'quantum_physics'检索初始文档",
      "depends_on": [],
      "estimated_cost": "low",
      "priority": 1
    }},
    {{
      "task_id": "T2",
      "task_type": "evidence_building",
      "description": "为'quantum_physics'构建证据池",
      "depends_on": ["T1"],
      "estimated_cost": "medium",
      "priority": 1
    }},
    {{
      "task_id": "T3",
      "task_type": "generation",
      "description": "生成easy题目",
      "depends_on": ["T2"],
      "estimated_cost": "medium",
      "priority": 2
    }}
  ],
  "rationale": "先获取证据，再按难度逐步生成"
}}
```

## 任务类型
- `retrieval`: 检索文档
- `evidence_building`: 构建证据池
- `generation`: 生成题目
- `analysis`: 分析缺口
- `adjustment`: 策略调整
"""
```

**工具实现**：
```python
@ToolRegistry.register(
    name="decompose_generation_task",
    category="planning",
    description="将整体生成目标分解为可执行的子任务序列。",
    parameters={
        "plan": {"type": "object", "required": True},
        "constraints": {"type": "object", "default": {}}
    }
)
async def tool_decompose_generation_task(
    plan: GenerationPlan,
    constraints: dict = None,
    model_client = None
) -> ToolOutput:
    user_prompt = f"""分解以下生成任务：

## 目标
- 主题: {plan.topics}
- 模式目标: {plan.mode_targets}
- 总目标: {plan.goal}

## 约束
- 最大总轮数: {plan.max_total_rounds}
- 每主题最大轮数: {plan.max_rounds_per_topic}
"""

    response = await model_client.complete(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_TASK_DECOMPOSER},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.2
    )

    decomposition = parse_llm_response(response["text"])[0]

    return ToolOutput(
        success=True,
        result=decomposition,
        observation=f"分解为{len(decomposition['decomposition'])}个子任务"
    )
```

---

### 2.3 L2 策略选择器

**Prompt设计**：

```python
SYSTEM_PROMPT_STRATEGY_SELECTOR = """你是问题生成策略选择专家。

## 你的职责
根据当前状态和子任务，选择最优的执行策略。

## 可用策略
**检索策略**:
- `initial_search`: 初始检索，查询词=主题名
- `expanded_search`: 扩展检索，查询词=相关概念
- `deep_search`: 深度检索，查询词=子主题

**采样策略**:
- `broad_exploration`: 广度探索，适合首轮或无明确缺口
- `gap_driven`: 缺口驱动，适合有明确主缺口
- `quality_focused`: 质量优先，优先高分证据

**生成策略**:
- `conservative`: 保守生成，请求数=剩余数
- `aggressive`: 激进生成，请求数=剩余数+50%
- `adaptive`: 自适应生成，根据历史有效率调整

## 决策因素
1. **当前轮数**: 早期用exploration，后期用gap_driven
2. **缺口类型**: hard缺口优先多证据，easy缺口用单证据
3. **历史效率**: 有效率低时调整策略或扩展检索
4. **证据质量**: 高质量证据优先
5. **剩余轮数**: 轮数少时用aggressive

## 输出格式
```json
{{
  "selected_strategy": "gap_driven",
  "strategy_parameters": {{
    "num_evidence": 5,
    "prefer_multi_chunk": true,
    "requested_questions": 8
  }},
  "rationale": "当前处于第3轮，有明确的hard缺口(qa:hard剩5)，历史显示多证据hard题目有效率高(0.8)，故选择gap_driven+多证据策略",
  "confidence": 0.85,
  "alternatives": [
    {{
      "strategy": "expanded_search",
      "reason": "如果生成失败，考虑扩展检索"
    }}
  ]
}}
```
"""
```

**工具实现**：
```python
@ToolRegistry.register(
    name="decide_strategy",
    category="planning",
    description="根据当前状态选择最优的执行策略。",
    parameters={
        "current_task": {"type": "object", "required": True},
        "state": {"type": "object", "required": True},
        "evidence_stats": {"type": "object", "required": True},
        "history": {"type": "array", "default": []},
        "constraints": {"type": "object", "default": {}}
    }
)
async def tool_decide_strategy(
    current_task: dict,
    state: dict,
    evidence_stats: dict,
    history: list = None,
    constraints: dict = None,
    model_client = None
) -> ToolOutput:
    user_prompt = f"""为以下任务选择策略：

## 当前任务
- 任务类型: {current_task['task_type']}
- 描述: {current_task['description']}

## 当前状态
- 剩余缺口: {state['remaining_counts']}
- 当前轮数: {state['current_round']}

## 证据统计
- 单证据有效率: {evidence_stats.get('single_chunk_stats', {}).get('avg_valid_count', 0):.2f}
- 多证据有效率: {evidence_stats.get('multi_chunk_stats', {}).get('avg_valid_count', 0):.2f}

## 约束
- 剩余轮数: {constraints.get('remaining_rounds', 'N/A')}
"""

    response = await model_client.complete(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_STRATEGY_SELECTOR},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3
    )

    strategy = parse_llm_response(response["text"])[0]

    return ToolOutput(
        success=True,
        result=strategy,
        observation=f"选择策略: {strategy['selected_strategy']}"
    )
```

---

### 2.4 L3 参数优化器

**Prompt设计**：

```python
SYSTEM_PROMPT_PARAMETER_OPTIMIZER = """你是问题生成参数优化专家。

## 你的职责
根据历史表现和约束条件，优化生成参数。

## 可优化参数
1. **请求数量**: 根据历史有效率调整
2. **证据数量**: 根据题目复杂度调整
3. **温度参数**: 根据题目难度调整
4. **多证据比例**: 根据目标难度调整

## 优化规则
1. **请求数量优化**:
   - 如果历史有效率 > 0.8: requested = remaining + 1
   - 如果历史有效率 0.5-0.8: requested = remaining + 2
   - 如果历史有效率 < 0.5: requested = remaining + 3

2. **证据数量优化**:
   - easy题目: 3-5个证据
   - medium题目: 4-6个证据
   - hard题目: 5-8个证据

3. **多证据比例优化**:
   - easy题目: 0-20%
   - medium题目: 20-40%
   - hard题目: 40-60%

## 输出格式
```json
{{
  "optimized_parameters": {{
    "requested_questions": 7,
    "num_evidence": 6,
    "multi_chunk_ratio": 0.5,
    "temperature": 0.7
  }},
  "optimization_rationale": {{
    "requested_questions": "历史有效率0.75(中等)，故请求量=剩余5+2",
    "num_evidence": "hard题目需要更多证据支撑",
    "multi_chunk_ratio": "hard题目优先多证据"
  }},
  "expected_improvement": "预测有效率提升至0.85"
}}
```
"""
```

---

## 三、完整工具清单

### 3.1 检索类工具

| 工具名 | 类别 | 决策层级 | 是否LLM |
|--------|------|----------|---------|
| `search_documents` | 低层 | L0 | 否 |
| `fetch_document` | 低层 | L0 | 否 |
| `chunk_document` | 低层 | L0 | 否 |
| `generate_document_summary` | 中层 | L1 | 是 |
| `decide_retrieval_action` | 高层 | L2 | 是 |

**`decide_retrieval_action` Prompt**：
```python
SYSTEM_PROMPT_RETRIEVAL_DECIDER = """你是检索决策专家。

## 你的职责
决定是否需要扩展检索，以及使用什么查询词。

## 决策条件
1. **证据不足**: 硬缺口且有效率低时扩展
2. **主题狭窄**: 检索结果少时使用相关概念查询
3. **历史失败**: 连续3轮生成失败时扩展

## 输出格式
```json
{{
  "should_expand": true,
  "expansion_queries": ["量子力学原理", "波粒二象性", "量子纠缠"],
  "expansion_reason": "hard题目有效率仅0.2，需要获取更复杂的跨文档证据",
  "max_pages": 3
}}
```
"""
```

---

### 3.2 证据类工具

| 工具名 | 类别 | 决策层级 | 是否LLM |
|--------|------|----------|---------|
| `build_evidence_pool` | 中层 | L1 | 否 |
| `calculate_signals` | 低层 | L0 | 否 |
| `merge_multi_chunks` | 中层 | L1 | 否 |
| `sample_evidence` | 中层 | L1 | 否 |
| `decide_evidence_strategy` | 高层 | L2 | 是 |

**`decide_evidence_strategy` Prompt**：
```python
SYSTEM_PROMPT_EVIDENCE_STRATEGIST = """你是证据策略专家。

## 你的职责
根据缺口类型选择最优的证据策略。

## 策略选择规则
1. **qa:hard** → 优先多证据(60%) + 长证据
2. **multiple_choice:hard** → 优先高mcq_score证据
3. **easy** → 单证据为主(80%)
4. **有效率低** → 减少请求数，提升证据质量

## 输出格式
```json
{{
  "evidence_strategy": {{
    "strategy_type": "gap_driven",
    "num_evidence": 6,
    "multi_chunk_ratio": 0.6,
    "min_score_threshold": 0.6,
    "prefer_high_scoring": true
  }},
  "rationale": "hard题目需要多证据支持，历史显示高分证据质量更好"
}}
```
"""
```

---

### 3.3 生成类工具

| 工具名 | 类别 | 决策层级 | 是否LLM |
|--------|------|----------|---------|
| `generate_questions_batch` | 中层 | L1 | 是(内部LLM) |
| `filter_questions` | 低层 | L0 | 否 |
| `parse_llm_response` | 低层 | L0 | 否 |
| `decide_generation_batch` | 高层 | L2 | 是 |

**`decide_generation_batch` Prompt**：
```python
SYSTEM_PROMPT_BATCH_DECIDER = """你是生成批次决策专家。

## 你的职责
决定当前批次应该生成多少题目、使用什么配置。

## 决策因素
1. **剩余数量**: 不超额太多，避免浪费
2. **历史效率**: 效率高时减少冗余，效率低时增加冗余
3. **证据质量**: 证据好时可以多生成
4. **轮数约束**: 接近上限时提高请求数

## 输出格式
```json
{{
  "batch_config": {{
    "requested_questions": 7,
    "min_questions": 5,
    "temperature": 0.7,
    "max_tokens": 2000,
    "include_quality_hints": true
  }},
  "rationale": {{
    "requested_questions": "剩余5题，历史有效率0.7，故请求7题确保完成",
    "temperature": "hard题目需要一定创造性"
  }}
}}
```
"""
```

---

### 3.4 分析类工具

| 工具名 | 类别 | 决策层级 | 是否LLM |
|--------|------|----------|---------|
| `analyze_generation_gap` | 高层 | L2 | 是 |
| `evaluate_quality` | 高层 | L2 | 是 |
| `identify_failure_patterns` | 高层 | L2 | 是 |

**`evaluate_quality` Prompt**：
```python
SYSTEM_PROMPT_QUALITY_EVALUATOR = """你是生成质量评估专家。

## 你的职责
评估最近一轮生成的题目质量。

## 评估维度
1. **目标达成度**: 生成的题目是否符合目标模式和难度
2. **资源效率**: 使用的资源 vs 生成数量
3. **质量表现**: 题目通过过滤的有效率
4. **多样性**: 题目是否重复或相似

## 输出格式
```json
{{
  "effectiveness": "acceptable",
  "scores": {{
    "goal_achievement": 0.8,
    "resource_efficiency": 0.6,
    "quality_performance": 0.75,
    "diversity": 0.7
  }},
  "analysis": "生成了5题，其中3题通过过滤。目标类型覆盖尚可，但有效率偏低，原因是prompt不够明确。",
  "suggestions": [
    "在prompt中增加难度要求的具体说明",
    "提高温度参数增加多样性"
  ],
  "next_action": "continue_generation"
}}
```
"""
```

---

### 3.5 规划类工具

| 工具名 | 类别 | 决策层级 | 是否LLM |
|--------|------|----------|---------|
| `decompose_generation_task` | 高层 | L1 | 是 |
| `decide_strategy` | 高层 | L2 | 是 |
| `optimize_parameters` | 高层 | L3 | 是 |
| `plan_next_action` | 高层 | L2 | 是 |
| `reflect_on_execution` | 高层 | L2 | 是 |

---

## 四、Agent执行流程

### 4.1 完整循环

```python
async def _run_agent_loop(self, topic: str, plan: GenerationPlan) -> None:
    """完整的Agent执行循环。"""

    # === 初始化阶段 ===
    await self._initial_retrieval(topic, plan)  # 低层工具

    # === 任务分解 ===
    decomposition = await self.tool_decompose_generation_task(plan)  # L1

    # === 主循环 ===
    while not self._check_completion(topic):
        # 1. 分析当前状态
        gap_analysis = await self.tool_analyze_generation_gap(
            topic,
            self.topic_states[topic],
            self.evidence_pools[topic].stats
        )  # L2

        # 2. 选择策略
        strategy = await self.tool_decide_strategy(
            current_task=gap_analysis,
            state=self.topic_states[topic],
            evidence_stats=self.evidence_pools[topic].stats,
            history=self.memory[topic].actions
        )  # L2

        # 3. 优化参数
        params = await self.tool_optimize_parameters(
            strategy,
            history=self.memory[topic].performance_metrics
        )  # L3

        # 4. 执行采样（中层工具）
        sample_result = await self.tool_sample_evidence(
            topic=topic,
            target_mode=strategy['strategy_parameters']['target_mode'],
            target_difficulty=strategy['strategy_parameters']['target_difficulty'],
            strategy=strategy['selected_strategy'],
            num_evidence=params['num_evidence'],
            prefer_multi_chunk=params['multi_chunk_ratio'] > 0.3,
            agent_context=self._get_agent_context()
        )  # L1

        # 5. 生成题目（中层工具）
        generation_result = await self.tool_generate_questions_batch(
            topic=topic,
            batch=sample_result['batch'],
            requested_questions=params['requested_questions'],
            temperature=params['temperature']
        )  # L1

        # 6. 过滤题目（低层工具）
        filtered_result = await self.tool_filter_questions(
            generation_result['raw_questions']
        )  # L0

        # 7. 更新状态
        self._update_state(topic, filtered_result)

        # 8. 评估质量
        quality_eval = await self.tool_evaluate_quality(
            generation_result,
            filtered_result,
            state=self.topic_states[topic]
        )  # L2

        # 9. 反思与调整
        reflection = await self.tool_reflect_on_execution(
            strategy,
            generation_result,
            quality_eval
        )  # L2

        # 10. 应用反思
        await self._apply_reflection(topic, reflection)

        # 11. 更新记忆
        self._update_memory(topic, {
            "strategy": strategy,
            "result": generation_result,
            "quality": quality_eval,
            "reflection": reflection
        })
```

---

### 4.2 决策流程图

```
开始
  │
  ├─> 初始检索 (L0工具)
  │
  ├─> 任务分解 (L1工具 + LLM)
  │   └─> 输出: [检索任务, 证据构建任务, 生成任务...]
  │
  └─> 进入主循环
       │
       ├─> 分析缺口 (L2工具 + LLM)
       │   ├─> 输入: 当前状态, 证据统计, 历史行动
       │   └─> 输出: 主缺口, 原因, 建议行动
       │
       ├─> 选择策略 (L2工具 + LLM)
       │   ├─> 输入: 缺口分析, 当前状态, 约束
       │   └─> 输出: 策略类型 + 初始参数
       │
       ├─> 优化参数 (L3工具 + LLM)
       │   ├─> 输入: 策略, 历史效率, 约束
       │   └─> 输出: 优化后的参数
       │
       ├─> 执行采样 (L1工具，无LLM)
       │   └─> 输出: 选中的证据单元
       │
       ├─> 生成题目 (L1工具，内部LLM)
       │   └─> 输出: 原始题目列表
       │
       ├─> 过滤题目 (L0工具，无LLM)
       │   └─> 输出: 有效题目列表
       │
       ├─> 评估质量 (L2工具 + LLM)
       │   ├─> 输入: 生成结果, 过滤结果, 状态
       │   └─> 输出: 质量评分, 分析, 建议
       │
       ├─> 反思执行 (L2工具 + LLM)
       │   ├─> 输入: 策略, 结果, 评估
       │   └─> 输出: 效果判断, 改进建议
       │
       ├─> 应用反思 (内部逻辑)
       │   └─> 更新: 策略偏好, 参数设置
       │
       └─> 检查完成 → 是则退出，否则继续循环
```

---

## 五、成本优化策略

### 5.1 LLM调用优化

| 策略 | 说明 | 预期节省 |
|------|------|----------|
| **规划缓存** | 相似状态复用决策 | 20-30% |
| **小模型做L2** | 规划用GPT-4o-mini | 50-70% |
| **降级机制** | LLM失败用规则 | 可靠性+∞ |
| **批量反思** | 每3轮反思一次 | 66% |

**代码示例**：
```python
class LLMPlanner:
    def __init__(self, model_client, enable_cache=True, fallback_to_rules=True):
        self.model_client = model_client
        self.enable_cache = enable_cache
        self.fallback_to_rules = fallback_to_rules
        self.cache = {}  # 状态哈希 -> 决策

    def plan(self, context: dict) -> AgentPlan:
        # 1. 尝试缓存
        if self.enable_cache:
            cache_key = self._hash_state(context)
            if cache_key in self.cache:
                logger.info("Using cached plan")
                return self.cache[cache_key]

        # 2. LLM决策
        try:
            plan = self._llm_plan(context)
            if self.enable_cache:
                self.cache[cache_key] = plan
            return plan
        except Exception as e:
            logger.warning(f"LLM planning failed: {e}")

        # 3. 降级到规则
        if self.fallback_to_rules:
            logger.info("Falling back to rule-based planning")
            return self._rule_based_plan(context)
        else:
            raise e

    def _hash_state(self, context: dict) -> str:
        """生成状态哈希用于缓存。"""
        # 只保留关键状态字段
        key_state = {
            "remaining_counts": context["topic_state"].remaining_counts,
            "current_round": context["topic_state"].current_round,
            "evidence_quality": context["evidence_stats"].get("avg_valid_count", 0),
        }
        return json.dumps(key_state, sort_keys=True)
```

---

## 六、实施路线图

### Phase 1: 工具标准化 (Week 1-2)
- [ ] 实现所有低层工具
- [ ] 实现所有中层工具
- [ ] 建立工具注册表
- [ ] 编写工具测试

### Phase 2: LLM决策层 (Week 2-3)
- [ ] 实现任务分解器
- [ ] 实现策略选择器
- [ ] 实现参数优化器
- [ ] 设计所有Prompt模板

### Phase 3: Agent核心 (Week 3-4)
- [ ] 实现Plan-Act-Observe-Reflect循环
- [ ] 实现记忆系统
- [ ] 实现降级机制
- [ ] 实现缓存优化

### Phase 4: 测试与优化 (Week 4-6)
- [ ] A/B测试：Pipeline vs Agent
- [ ] Prompt调优
- [ ] 性能监控
- [ ] 成本优化

---

## 七、关键Prompt模板汇总

所有Prompt模板应该存储在独立的文件中，便于管理和版本控制：

```
benchforge/prompts/
├── agent/
│   ├── task_decomposer_system.md
│   ├── task_decomposer_user.md
│   ├── strategy_selector_system.md
│   ├── strategy_selector_user.md
│   ├── parameter_optimizer_system.md
│   ├── parameter_optimizer_user.md
│   ├── retrieval_decider_system.md
│   ├── retrieval_decider_user.md
│   ├── evidence_strategist_system.md
│   ├── evidence_strategist_user.md
│   ├── batch_decider_system.md
│   ├── batch_decider_user.md
│   ├── quality_evaluator_system.md
│   ├── quality_evaluator_user.md
│   ├── gap_analyzer_system.md
│   └── gap_analyzer_user.md
└── question_generator/
    └── (现有prompt)
```

---

## 八、成功指标

| 指标 | Pipeline | Agent目标 | 提升 |
|------|----------|-----------|------|
| 目标达成率 | 85% | 95% | +10% |
| 硬题成功率 | 60% | 80% | +20% |
| 平均轮数 | 8 | 6 | -25% |
| LLM调用成本 | 1x | 1.5x | +50% |
| 可解释性 | 低 | 高 | 质的飞跃 |