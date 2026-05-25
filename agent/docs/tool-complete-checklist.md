# 工具完整清单与决策映射

## 完整工具清单

### 0. 基础工具层（L0）

这些工具不需要任何决策，纯函数，直接执行。

| 工具名 | 功能 | 输入 | 输出 | 代码位置 |
|--------|------|------|------|----------|
| `search_documents` | 搜索Wikipedia | query, max_pages, language | 搜索结果列表 | `utils/retrieval.py` |
| `fetch_wikipedia_page` | 获取页面内容 | page_url, run_id, language | SourceDocument | `utils/retrieval.py` |
| `chunk_document` | 文档分块 | document, chunk_size, overlap | SourceChunk列表 | `utils/chunking.py` |
| `calculate_signals` | 计算信号分数 | text, summary, usage_count | 分数字典 | `utils/signals.py` |
| `filter_questions` | 过滤题目 | 原始题目列表 | (通过, 失败)列表 | `utils/filter.py` |
| `parse_llm_response` | 解析LLM响应 | response_text | 结构化数据 | `utils/filter.py` |

**代码示例**：
```python
@ToolRegistry.register(
    name="search_documents",
    category="retrieval",
    layer="L0",
    description="搜索与主题相关的Wikipedia文档。",
    parameters={
        "query": {"type": "string", "required": True, "description": "搜索查询词"},
        "max_pages": {"type": "integer", "default": 5, "description": "最大页面数"},
        "language": {"type": "string", "default": "en", "description": "语言"}
    }
)
async def tool_search_documents(
    query: str,
    max_pages: int = 5,
    language: str = "en"
) -> ToolOutput:
    """L0工具：纯函数，无决策逻辑。"""
    results = search_wikipedia(query=query, language=language, max_pages=max_pages)
    return ToolOutput(
        success=True,
        result={"results": results, "count": len(results)},
        observation=f"搜索'{query}'找到{len(results)}个结果"
    )
```

---

### 1. 中层工具（L1）

这些工具有简单的参数选择逻辑，但不复杂，可以规则化。

| 工具名 | 功能 | 决策点 | 代码位置 |
|--------|------|--------|----------|
| `build_evidence_pool` | 构建证据池 | chunk_size, overlap | `utils/multi_chunk.py` |
| `sample_evidence` | 采样证据单元 | strategy类型, 采样数量 | `utils/sampling.py` |
| `merge_multi_chunks` | 合并多证据 | 组合大小, max_tokens | `utils/multi_chunk.py` |
| `generate_document_summary` | 生成文档摘要 | 摘要长度 | `agents/question_generator.py` |
| `update_evidence_stats` | 更新证据统计 | alpha系数 | `utils/planning.py` |

**代码示例**：
```python
@ToolRegistry.register(
    name="sample_evidence",
    category="selection",
    layer="L1",
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
    """L1工具：简单if-else逻辑，无需LLM。"""
    pool = agent_context["evidence_pools"][topic]

    # 简单的策略选择（if-else，不需要LLM）
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

### 2. 高层工具（L2）

这些工具需要LLM推理来决定关键参数，核心决策点。

| 工具名 | 功能 | 需要LLM决策的参数 | Prompt文件 |
|--------|------|-------------------|------------|
| `decompose_generation_task` | 任务分解 | 子任务序列、依赖关系 | `agent/task_decomposer_system.md` |
| `analyze_generation_gap` | 分析缺口 | 哪个缺口最紧急？为什么？ | `agent/gap_analyzer_system.md` |
| `decide_retrieval_action` | 决定检索 | 需要扩展吗？用什么查询？ | `agent/retrieval_decider_system.md` |
| `decide_strategy` | 选择策略 | 用什么策略？为什么？ | `agent/strategy_selector_system.md` |
| `decide_evidence_strategy` | 证据策略 | 多证据比例？分数阈值？ | `agent/evidence_strategist_system.md` |
| `decide_generation_batch` | 批次决策 | 生成多少题？用什么配置？ | `agent/batch_decider_system.md` |
| `evaluate_quality` | 评估质量 | 质量如何？什么原因？ | `agent/quality_evaluator_system.md` |
| `reflect_on_execution` | 反思执行 | 效果如何？如何改进？ | `agent/reflector_system.md` |
| `plan_next_action` | 规划下一步 | 应该做什么？为什么？ | `agent/next_action_planner_system.md` |

**代码示例**：
```python
@ToolRegistry.register(
    name="decide_strategy",
    category="planning",
    layer="L2",
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
    """L2工具：需要LLM推理。"""
    # 加载Prompt
    system_prompt = load_prompt("agent/strategy_selector_system.md")

    # 构建用户输入
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

## 历史行动（最近3次）
{json.dumps(history[-3:], indent=2, ensure_ascii=False)}

## 输出要求
以JSON格式输出，包含：
- selected_strategy: 选择的策略
- strategy_parameters: 策略参数
- rationale: 选择理由
- confidence: 置信度
"""

    # 调用LLM
    response = await model_client.complete(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,
        response_format={"type": "json_object"}  # 如果支持
    )

    # 解析响应
    strategy = parse_llm_response(response["text"])[0]

    return ToolOutput(
        success=True,
        result=strategy,
        observation=f"选择策略: {strategy['selected_strategy']}，理由：{strategy.get('rationale', 'N/A')}"
    )
```

---

### 3. 参数优化层（L3）

这些工具是专门的参数优化器，根据历史表现和约束条件调整参数。

| 工具名 | 功能 | 优化目标 | Prompt文件 |
|--------|------|----------|------------|
| `optimize_parameters` | 优化生成参数 | 提升目标达成率 | `agent/parameter_optimizer_system.md` |
| `adjust_temperature` | 调整温度参数 | 平衡创造性与准确性 | `agent/temperature_optimizer_system.md` |
| `adjust_redundancy` | 调整冗余策略 | 平衡效率与完成率 | `agent/redundancy_optimizer_system.md` |

**代码示例**：
```python
@ToolRegistry.register(
    name="optimize_parameters",
    category="optimization",
    layer="L3",
    description="根据历史表现和约束条件优化生成参数。",
    parameters={
        "strategy": {"type": "object", "required": True},
        "history_performance": {"type": "object", "required": True},
        "constraints": {"type": "object", "default": {}}
    }
)
async def tool_optimize_parameters(
    strategy: dict,
    history_performance: dict,
    constraints: dict = None,
    model_client = None
) -> ToolOutput:
    """L3工具：专门的参数优化器。"""
    # 加载Prompt
    system_prompt = load_prompt("agent/parameter_optimizer_system.md")

    # 构建用户输入
    user_prompt = f"""优化以下策略的参数：

## 当前策略
- 策略类型: {strategy['selected_strategy']}
- 基础参数: {json.dumps(strategy.get('strategy_parameters', {}), ensure_ascii=False)}

## 历史表现
- 平均有效率: {history_performance.get('avg_valid_rate', 0):.2f}
- 近5轮有效率: {history_performance.get('recent_valid_rates', [])}
- 目标达成进度: {history_performance.get('goal_progress', 0):.1%}

## 约束条件
- 剩余轮数: {constraints.get('remaining_rounds', 'N/A')}
- 预算限制: {constraints.get('budget', 'N/A')}

## 输出要求
以JSON格式输出：
- optimized_parameters: 优化后的参数
- optimization_rationale: 优化理由（每个参数单独说明）
- expected_improvement: 预期改进效果
"""

    # 调用LLM
    response = await model_client.complete(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.2  # 参数优化需要确定性
    )

    # 解析响应
    optimization = parse_llm_response(response["text"])[0]

    return ToolOutput(
        success=True,
        result=optimization,
        observation=f"优化后参数：{json.dumps(optimization['optimized_parameters'], ensure_ascii=False)}"
    )
```

---

## 决策映射表

### 场景1: 第一轮生成

| 状态 | 决策 | 工具调用 | 参数 |
|------|------|----------|------|
| current_round = 0 | 使用广度探索 | `sample_evidence` | strategy="broad_exploration" |
| 剩余缺口多 | 请求较多题目 | `decide_generation_batch` | requested = remaining + 2 |
| 无历史数据 | 使用默认参数 | `optimize_parameters` | 基于目标类型优化 |

**决策流**：
```
1. analyze_generation_gap → 找最大缺口
2. decide_strategy → 选择broad_exploration
3. optimize_parameters → 根据缺口大小设置请求数
4. sample_evidence → 广度采样
5. generate_questions_batch → 生成
```

---

### 场景2: Hard题目缺口且有效率低

| 状态 | 决策 | 工具调用 | 参数 |
|------|------|----------|------|
| gap = qa:hard | 扩展检索 | `decide_retrieval_action` | 应该扩展，查询相关概念 |
| 单证据有效率 < 0.3 | 偏好多证据 | `decide_evidence_strategy` | multi_chunk_ratio=0.6 |
| 已有2轮历史 | 调整策略 | `reflect_on_execution` | 建议改进方向 |

**决策流**：
```
1. analyze_generation_gap → 识别qa:hard为主缺口
2. decide_retrieval_action → 决定扩展检索
3. expand_retrieval → 获取新文档
4. rebuild_evidence_pool → 更新证据池
5. decide_evidence_strategy → 提高多证据比例
6. sample_evidence → 采样高质量证据
7. generate_questions_batch → 生成
```

---

### 场景3: 接近轮数上限

| 状态 | 决策 | 工具调用 | 参数 |
|------|------|----------|------|
| current_round = 8 | 激进策略 | `decide_strategy` | aggressive |
| max_rounds = 10 | 提高请求数 | `decide_generation_batch` | requested = remaining + 3 |
| 多个缺口未填 | 优先大缺口 | `analyze_generation_gap` | 找最大缺口 |

**决策流**：
```
1. check_remaining_rounds → 发现只剩2轮
2. analyze_generation_gap → 找最大缺口
3. decide_strategy → 选择aggressive
4. optimize_parameters → 提高请求数，降低冗余容忍度
5. sample_evidence → 采样最高分证据
6. generate_questions_batch → 激进生成
```

---

### 场景4: 生成质量持续下降

| 状态 | 决策 | 工具调用 | 参数 |
|------|------|----------|------|
| 连续3轮有效率 < 0.4 | 质量优先 | `reflect_on_execution` | 识别问题根源 |
| 历史显示证据重复 | 扩展检索 | `decide_retrieval_action` | 获取新证据 |
| Prompt可能不够好 | 调整Prompt | `adjust_generation_prompt` | 增加难度说明 |

**决策流**：
```
1. evaluate_quality → 发现质量下降
2. reflect_on_execution → 分析原因（证据重复）
3. decide_retrieval_action → 决定扩展
4. expand_retrieval → 获取新证据
5. rebuild_evidence_pool → 更新证据池
6. decide_evidence_strategy → 优先新证据
7. sample_evidence → 采样新证据
8. generate_questions_batch → 生成
```

---

## 工具依赖关系图

```
┌─────────────────────────────────────────────────────────┐
│                   高层决策工具 (L2)                     │
│  decompose, analyze, decide_strategy, evaluate, reflect │
└────────────────────┬────────────────────────────────────┘
                     │ 决策参数
┌────────────────────▼────────────────────────────────────┐
│                参数优化工具 (L3)                        │
│             optimize_parameters                          │
└────────────────────┬────────────────────────────────────┘
                     │ 优化参数
┌────────────────────▼────────────────────────────────────┐
│                 中层组合工具 (L1)                        │
│  build_pool, sample_evidence, merge_chunks, update_stats │
└────────────────────┬────────────────────────────────────┘
                     │ 组合操作
┌────────────────────▼────────────────────────────────────┐
│                 低层原子工具 (L0)                        │
│  search, fetch, chunk, calculate, filter, parse         │
└─────────────────────────────────────────────────────────┘
```

---

## 工具调用示例

### 示例1: 完整的一轮生成

```python
async def execute_one_round(topic: str, agent: TrueQuestionGeneratorAgent):
    """执行一轮完整生成的工具调用序列。"""

    # === L2: 分析缺口 ===
    gap_analysis = await ToolRegistry.call_tool(
        name="analyze_generation_gap",
        parameters={
            "topic": topic,
            "current_state": agent.topic_states[topic].model_dump(),
            "evidence_stats": agent.evidence_pools[topic].stats.model_dump(),
            "history": agent.memory[topic].actions[-3:]
        },
        model_client=agent.model_client  # L2工具需要LLM
    )
    # 输出: {"primary_gap": "qa:hard", "gap_reason": "...", ...}

    # === L2: 选择策略 ===
    strategy = await ToolRegistry.call_tool(
        name="decide_strategy",
        parameters={
            "current_task": {"task_type": "generation"},
            "state": agent.topic_states[topic].model_dump(),
            "evidence_stats": agent.evidence_pools[topic].stats.model_dump(),
            "history": agent.memory[topic].actions,
            "constraints": {"remaining_rounds": 5}
        },
        model_client=agent.model_client  # L2工具需要LLM
    )
    # 输出: {"selected_strategy": "gap_driven", "strategy_parameters": {...}, ...}

    # === L3: 优化参数 ===
    params = await ToolRegistry.call_tool(
        name="optimize_parameters",
        parameters={
            "strategy": strategy["result"],
            "history_performance": agent.memory[topic].performance_metrics,
            "constraints": {"remaining_rounds": 5}
        },
        model_client=agent.model_client  # L3工具需要LLM
    )
    # 输出: {"optimized_parameters": {"requested_questions": 7, ...}, ...}

    # === L1: 采样证据 ===
    sample_result = await ToolRegistry.call_tool(
        name="sample_evidence",
        parameters={
            "topic": topic,
            "target_mode": gap_analysis["result"]["primary_gap"].split(":")[0],
            "target_difficulty": gap_analysis["result"]["primary_gap"].split(":")[1],
            "strategy": strategy["result"]["selected_strategy"],
            "num_evidence": params["result"]["optimized_parameters"]["num_evidence"],
            "prefer_multi_chunk": params["result"]["optimized_parameters"]["multi_chunk_ratio"] > 0.3,
            "agent_context": {
                "evidence_pools": agent.evidence_pools
            }
        }
        # L1工具不需要model_client
    )
    # 输出: {"batch": GenerationBatch(...), "selected_count": 6}

    # === L1: 生成题目 ===
    generation_result = await ToolRegistry.call_tool(
        name="generate_questions_batch",
        parameters={
            "topic": topic,
            "batch": sample_result["result"]["batch"],
            "requested_questions": params["result"]["optimized_parameters"]["requested_questions"],
            "temperature": params["result"]["optimized_parameters"]["temperature"],
            "agent_context": {
                "model_clients": agent.model_clients,
                "all_questions": agent.all_questions
            }
        }
        # L1工具内部会调用LLM（生成题目），但不需要额外的model_client
    )
    # 输出: {"raw_questions": [...], "candidate_count": 10}

    # === L0: 过滤题目 ===
    filter_result = await ToolRegistry.call_tool(
        name="filter_questions",
        parameters={
            "questions": generation_result["result"]["raw_questions"]
        }
        # L0工具不需要任何额外参数
    )
    # 输出: {"passed": [...], "failed": [...]}

    # === L2: 评估质量 ===
    quality_eval = await ToolRegistry.call_tool(
        name="evaluate_quality",
        parameters={
            "generation_result": generation_result["result"],
            "filter_result": filter_result["result"],
            "state": agent.topic_states[topic].model_dump()
        },
        model_client=agent.model_client  # L2工具需要LLM
    )
    # 输出: {"effectiveness": "good", "scores": {...}, "analysis": "...", ...}

    # === L2: 反思执行 ===
    reflection = await ToolRegistry.call_tool(
        name="reflect_on_execution",
        parameters={
            "strategy": strategy["result"],
            "generation_result": generation_result["result"],
            "quality_eval": quality_eval["result"],
            "state": agent.topic_states[topic].model_dump()
        },
        model_client=agent.model_client  # L2工具需要LLM
    )
    # 输出: {"effectiveness": "good", "analysis": "...", "suggestions": [...], ...}

    # === 更新状态（内部逻辑，不是工具） ===
    agent._update_state(topic, filter_result["result"]["passed"])

    # === 更新记忆（内部逻辑，不是工具） ===
    agent._update_memory(topic, {
        "gap_analysis": gap_analysis["result"],
        "strategy": strategy["result"],
        "params": params["result"],
        "generation": generation_result["result"],
        "quality": quality_eval["result"],
        "reflection": reflection["result"]
    })

    return {
        "gap_analysis": gap_analysis["result"],
        "strategy": strategy["result"],
        "params": params["result"],
        "generation": generation_result["result"],
        "filter": filter_result["result"],
        "quality": quality_eval["result"],
        "reflection": reflection["result"]
    }
```

---

## 工具调用成本估算

| 工具类型 | 每轮调用次数 | 是否LLM | 单次成本(相对) | 每轮成本(相对) |
|---------|-------------|---------|---------------|---------------|
| L0工具 | 2-3 | 否 | 0 | 0 |
| L1工具 | 2-3 | 否 | 0 | 0 |
| L2工具 | 3-4 | 是 | 0.1 | 0.3-0.4 |
| L3工具 | 1 | 是 | 0.1 | 0.1 |
| 生成(内部) | 1 | 是 | 1.0 | 1.0 |
| **合计** | | | | **1.4-1.5x** |

**说明**：
- 生成题目的LLM调用是必须的，原来也有
- 新增的成本主要是L2和L3工具
- 通过缓存和降级可以减少实际调用
- 预期成本增加40-50%，但收益显著提升

---

## 工具注册表实现

```python
class ToolRegistry:
    """工具注册表。"""

    _tools: dict[str, dict] = {}
    _by_category: dict[str, list[str]] = {}
    _by_layer: dict[str, list[str]] = {}

    @classmethod
    def register(cls, name: str, category: str, layer: str, description: str, parameters: dict):
        """注册工具。"""
        tool_def = {
            "name": name,
            "category": category,
            "layer": layer,
            "description": description,
            "parameters": parameters,
            "func": None,  # 将通过装饰器设置
        }
        cls._tools[name] = tool_def

        # 分类索引
        if category not in cls._by_category:
            cls._by_category[category] = []
        cls._by_category[category].append(name)

        if layer not in cls._by_layer:
            cls._by_layer[layer] = []
        cls._by_layer[layer].append(name)

    @classmethod
    def get_tool(cls, name: str) -> dict | None:
        """获取工具定义。"""
        return cls._tools.get(name)

    @classmethod
    def list_tools_by_category(cls, category: str) -> list[dict]:
        """按类别列出工具。"""
        names = cls._by_category.get(category, [])
        return [cls._tools[name] for name in names]

    @classmethod
    def list_tools_by_layer(cls, layer: str) -> list[dict]:
        """按层级列出工具。"""
        names = cls._by_layer.get(layer, [])
        return [cls._tools[name] for name in names]

    @classmethod
    async def call_tool(cls, name: str, parameters: dict, model_client=None, agent_context=None):
        """调用工具。"""
        tool_def = cls.get_tool(name)
        if not tool_def:
            raise ValueError(f"Tool not found: {name}")

        func = tool_def["func"]

        # 根据层级决定是否传递model_client
        if tool_def["layer"] in ["L2", "L3"]:
            return await func(**parameters, model_client=model_client, agent_context=agent_context)
        else:
            return await func(**parameters, agent_context=agent_context)
```

---

## 工具测试策略

### L0工具测试
- **单元测试**: 验证输入输出关系
- **基准测试**: 验证性能
- **边界测试**: 验证极端输入

### L1工具测试
- **单元测试**: 验证参数选择逻辑
- **集成测试**: 验证与L0工具的配合
- **基准测试**: 对比不同策略的效果

### L2工具测试
- **Prompt测试**: 验证LLM输出的正确性
- **场景测试**: 测试各种状态下的决策
- **A/B测试**: 对比LLM决策与规则决策
- **成本测试**: 验证成本效益比

### L3工具测试
- **优化效果测试**: 验证参数优化后的改进
- **稳定性测试**: 验证多次运行的一致性
- **边界测试**: 验证极端约束下的优化