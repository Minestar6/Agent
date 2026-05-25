# 问题生成智能体：完整设计文档

## 一、核心概念

### Agent vs 工具的本质区别

| 维度 | Agent（智能体） | 工具 |
|------|----------------|------|
| **本质** | 有推理能力的自主系统 | 原子操作单元 |
| **能力** | 理解、分析、决策、学习 | 执行特定任务 |
| **输出** | 决策、策略、评估 | 数据、结果 |
| **自主性** | 根据状态自主决定下一步 | 按指令执行 |
| **示例** | "我需要先扩展检索" | 搜索"quantum physics" |

**一句话总结**：
- Agent = 大脑（推理） + 手（工具使用）
- 工具 = 只能按指令执行的函数

---

## 二、系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent核心（推理层）                     │
│                                                              │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐ │
│  │ 状态理解 │ →  │ 缺口分析 │ →  │ 策略选择 │ →  │ 参数优化 │ │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘ │
│                                                              │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐                │
│  │ 工具执行 │ →  │ 质量评估 │ →  │ 反思改进 │ → 循环        │
│  └─────────┘    └─────────┘    └─────────┘                │
│                                                              │
│  这些是Agent的能力，不是工具！用LLM实现推理                  │
└────────────────────┬────────────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
┌────────▼─────────┐   ┌────────▼─────────┐
│    工具层（执行）  │   │   内部计算层      │
│                   │   │                   │
│ • search_wiki     │   │ • 证据池管理      │
│ • fetch_page      │   │ • 采样策略选择    │
│ • generate_q      │   │ • 状态更新        │
│ • filter_q        │   │ • 统计计算        │
│ • chunk_document  │   │                   │
└───────────────────┘   └───────────────────┘
```

---

### 2.2 Agent的核心能力（推理层）

这些是Agent的"大脑"能力，用LLM实现：

| 能力 | 方法名 | 输入 | 输出 | LLM调用 |
|------|--------|------|------|---------|
| 状态理解 | `_understand_state` | TopicState | 状态摘要 | 是 |
| 缺口分析 | `_analyze_gaps` | 状态摘要 | 主缺口分析 | 是 |
| 策略选择 | `_select_strategy` | 缺口分析 | 策略决策 | 是 |
| 参数优化 | `_optimize_parameters` | 策略 | 优化参数 | 是 |
| 质量评估 | `_evaluate_quality` | 生成结果 | 质量评分 | 是 |
| 反思改进 | `_reflect_and_improve` | 执行历史 | 改进建议 | 是 |

**关键特征**：
- 都用LLM实现推理
- 输出是"决策"而非"数据"
- 不包装为工具，是Agent的内在能力

---

### 2.3 工具层（执行层）

这些是Agent的"手"，可以调用的原子操作：

| 工具 | 方法名 | 功能 | 类型 |
|------|--------|------|------|
| 搜索 | `_search_wikipedia` | 搜索Wikipedia | 信息获取 |
| 获取 | `_fetch_page` | 获取页面内容 | 信息获取 |
| 分块 | `_chunk_document` | 文档分块 | 数据处理 |
| 生成 | `_generate_questions_llm` | 调用LLM生成题目 | LLM调用 |
| 过滤 | `_filter_questions` | 过滤题目 | 数据处理 |
| 解析 | `_parse_llm_response` | 解析LLM响应 | 数据处理 |

**关键特征**：
- 纯函数，输入输出明确
- 不包含决策逻辑
- 可以被Agent调用来"执行动作"

---

### 2.4 内部计算层

这些是Agent的"逻辑"，无需LLM的确定性计算：

| 计算 | 方法名 | 功能 |
|------|--------|------|
| 采样证据 | `_sample_evidence` | 根据策略采样证据 |
| 构建证据池 | `_build_evidence_pool` | 构建单/多证据单元 |
| 更新状态 | `_update_state` | 更新TopicState |
| 解析题目 | `_parse_questions` | 解析LLM生成的题目 |
| 存储启发式 | `_store_learned_heuristics` | 存储学习到的规则 |

**关键特征**：
- 确定性逻辑，无需LLM
- 优化后的规则（可来自反思）

---

## 三、执行流程

### 3.1 完整的思考-执行循环

```python
class QuestionGeneratorAgent:
    async def run(self, topic: str, max_rounds: int = 10) -> dict:
        """Agent的主执行循环。"""

        for round_num in range(max_rounds):
            # ========== 阶段1：思考（推理层）==========
            decision = await self.think(topic)

            if decision.next_action == "complete":
                break

            # ========== 阶段2：执行（工具层）==========
            result = await self._execute_decision(decision)

            # ========== 阶段3：评估（推理层）==========
            evaluation = await self._evaluate_quality(topic, result)

            # ========== 阶段4：反思（推理层）==========
            reflection = await self._reflect_and_improve(
                topic, decision, result, evaluation
            )

            # ========== 阶段5：学习（内部层）==========
            self._apply_learnings(topic, reflection)

            # ========== 阶段6：更新（内部层）==========
            self._update_state(topic, result)
```

---

### 3.2 思考过程详解

```python
async def think(self, topic: str) -> AgentDecision:
    """Agent的核心思考过程。"""

    # 步骤1：理解当前状态
    state_summary = await self._understand_state(topic)
    # LLM分析：当前进度如何？有什么问题？

    # 步骤2：分析缺口
    gap_analysis = await self._analyze_gaps(topic, state_summary)
    # LLM分析：哪个缺口最紧急？为什么？

    # 步骤3：选择策略
    strategy = await self._select_strategy(topic, gap_analysis)
    # LLM决策：应该用什么策略？

    # 步骤4：优化参数
    parameters = await self._optimize_parameters(topic, strategy)
    # LLM优化：具体参数怎么设置？

    return AgentDecision(
        next_action=strategy["action"],
        action_parameters=parameters,
        reasoning=strategy["reasoning"],
        confidence=strategy["confidence"]
    )
```

**示例输出**：
```json
{
  "next_action": "generate_questions",
  "action_parameters": {
    "target_mode": "qa",
    "target_difficulty": "hard",
    "requested_questions": 7,
    "num_evidence": 5,
    "prefer_multi_chunk": true,
    "temperature": 0.7
  },
  "reasoning": "当前主缺口为qa:hard（剩5题），历史显示多证据有效率高（0.8），故选择gap_driven策略 + 多证据",
  "confidence": 0.85
}
```

---

### 3.3 执行过程详解

```python
async def _execute_decision(self, decision: AgentDecision) -> dict:
    """执行Agent的决策（调用工具）。"""

    action = decision.next_action
    params = decision.action_parameters

    if action == "generate_questions":
        return await self._execute_generation(params)
    elif action == "expand_retrieval":
        return await self._execute_retrieval(params)
    else:
        raise ValueError(f"Unknown action: {action}")
```

```python
async def _execute_generation(self, params: dict) -> dict:
    """执行生成（组合多个工具）。"""

    # 1. 采样证据（内部计算）
    sampled_evidence = self._sample_evidence(
        topic=params.get("topic"),
        num_evidence=params.get("num_evidence", 5),
        prefer_multi_chunk=params.get("prefer_multi_chunk", False)
    )

    # 2. 生成题目（工具调用）
    generation_result = await self.tools["generate_questions_llm"](
        evidence_text=sampled_evidence["text"],
        target_mode=params["target_mode"],
        target_difficulty=params["target_difficulty"],
        requested_count=params["requested_questions"],
        temperature=params.get("temperature", 0.7)
    )

    # 3. 解析响应（内部计算）
    raw_questions = self._parse_questions(generation_result["raw_text"])

    # 4. 过滤题目（工具调用）
    filter_result = await self.tools["filter_questions"](raw_questions)

    return {
        "requested_count": params["requested_questions"],
        "raw_count": len(raw_questions),
        "valid_count": len(filter_result["passed"]),
        "valid_rate": filter_result["pass_rate"],
        "questions": filter_result["passed"]
    }
```

---

## 四、能力设计详解

### 4.1 状态理解能力

```python
async def _understand_state(self, topic: str) -> dict:
    """理解当前状态。

    这是Agent的认知能力，不是工具！
    """
    state = self.topic_states[topic]
    pool = self.evidence_pools.get(topic)

    prompt = f"""分析当前生成状态：

主题: {topic}
当前轮数: {state.current_round}

剩余缺口:
{json.dumps(state.remaining_counts, indent=2, ensure_ascii=False)}

已完成统计:
{json.dumps(state.completed_counts, indent=2, ensure_ascii=False)}

证据池统计:
- 单证据数量: {len(pool.single_chunks) if pool else 0}
- 多证据数量: {len(pool.multi_chunks) if pool else 0}
- 单证据平均有效率: {pool.stats.single_chunk_stats.avg_valid_count if pool else 0:.2f}
- 多证据平均有效率: {pool.stats.multi_chunk_stats.avg_valid_count if pool else 0:.2f}

请以JSON格式输出状态分析：
{{
  "status_summary": "一句话总结当前状态",
  "key_issues": ["关键问题1", "关键问题2"],
  "overall_progress": 0.75,
  "bottleneck": "qa:hard"  // 当前主要瓶颈
}}
"""

    response = await self.model_client.complete(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    return self._parse_json_response(response["text"])
```

**示例输出**：
```json
{
  "status_summary": "当前已完成75%的目标，但hard题目进度缓慢",
  "key_issues": [
    "qa:hard缺5题（目标10）",
    "单证据hard有效率仅0.3",
    "多证据利用率不足"
  ],
  "overall_progress": 0.75,
  "bottleneck": "qa:hard"
}
```

---

### 4.2 缺口分析能力

```python
async def _analyze_gaps(self, topic: str, state_summary: dict) -> dict:
    """分析当前缺口。"""

    state = self.topic_states[topic]

    prompt = f"""基于状态分析缺口：

状态摘要: {state_summary['status_summary']}
关键问题: {state_summary['key_issues']}
主要瓶颈: {state_summary['bottleneck']}

剩余缺口详情:
{json.dumps(state.remaining_counts, indent=2, ensure_ascii=False)}

请以JSON格式输出缺口分析：
{{
  "primary_gap": "qa:hard",
  "gap_reason": "为什么这个缺口存在？",
  "evidence_sufficiency": "sufficient | partial | insufficient",
  "suggested_approach": "generate_direct | expand_retrieval | adjust_parameters",
  "confidence": 0.85
}}
"""

    response = await self.model_client.complete(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    return self._parse_json_response(response["text"])
```

**示例输出**：
```json
{
  "primary_gap": "qa:hard",
  "gap_reason": "单证据的hard_score低(0.3)，且多证据使用率仅20%，导致hard题目难以生成",
  "evidence_sufficiency": "partial",
  "suggested_approach": "adjust_parameters",
  "confidence": 0.85
}
```

---

### 4.3 策略选择能力

```python
async def _select_strategy(self, topic: str, gap_analysis: dict) -> dict:
    """选择执行策略。"""

    state = self.topic_states[topic]
    pool = self.evidence_pools.get(topic)

    prompt = f"""根据缺口分析选择策略：

主缺口: {gap_analysis['primary_gap']}
缺口原因: {gap_analysis['gap_reason']}
证据充足度: {gap_analysis['evidence_sufficiency']}
建议方法: {gap_analysis['suggested_approach']}

当前轮数: {state.current_round}
单证据有效率: {pool.stats.single_chunk_stats.avg_valid_count if pool else 0:.2f}
多证据有效率: {pool.stats.multi_chunk_stats.avg_valid_count if pool else 0:.2f}

请以JSON格式输出策略选择：
{{
  "action": "generate_questions | expand_retrieval | adjust_strategy",
  "strategy": "broad_exploration | gap_driven | quality_focused",
  "reasoning": "详细说明为什么选择这个策略",
  "confidence": 0.85
}}
"""

    response = await self.model_client.complete(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    return self._parse_json_response(response["text"])
```

**示例输出**：
```json
{
  "action": "generate_questions",
  "strategy": "gap_driven",
  "reasoning": "主缺口为qa:hard，证据池质量良好，应继续生成但调整参数（增加多证据比例）",
  "confidence": 0.85
}
```

---

### 4.4 参数优化能力

```python
async def _optimize_parameters(self, topic: str, strategy: dict) -> dict:
    """优化执行参数。"""

    state = self.topic_states[topic]

    prompt = f"""优化以下策略的参数：

策略: {strategy['action']}
方法: {strategy['strategy']}

当前剩余:
{json.dumps(state.remaining_counts, indent=2, ensure_ascii=False)}

历史有效率（最近3轮）:
{self.memory[topic][-3:] if topic in self.memory else []}

请以JSON格式输出优化参数：
{{
  "target_mode": "qa | multiple_choice",
  "target_difficulty": "easy | medium | hard",
  "requested_questions": 7,
  "num_evidence": 5,
  "prefer_multi_chunk": true,
  "temperature": 0.7,
  "rationale": "每个参数的优化理由"
}}
"""

    response = await self.model_client.complete(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2  # 参数优化需要确定性
    )

    return self._parse_json_response(response["text"])
```

**示例输出**：
```json
{
  "target_mode": "qa",
  "target_difficulty": "hard",
  "requested_questions": 7,
  "num_evidence": 5,
  "prefer_multi_chunk": true,
  "temperature": 0.7,
  "rationale": {
    "requested_questions": "剩余5题，历史有效率0.7，请求7题确保完成",
    "num_evidence": "hard题目需要更多证据支持",
    "prefer_multi_chunk": "历史显示多证据hard题目有效率高(0.8)",
    "temperature": "hard题目需要一定创造性"
  }
}
```

---

### 4.5 质量评估能力

```python
async def _evaluate_quality(self, topic: str, generation_result: dict) -> dict:
    """评估生成质量。"""

    prompt = f"""评估以下生成的质量：

生成结果:
- 请求数: {generation_result.get('requested_count', 'N/A')}
- 原始候选: {generation_result.get('raw_count', 'N/A')}
- 有效题目: {generation_result.get('valid_count', 'N/A')}
- 有效率: {generation_result.get('valid_rate', 'N/A')}

请以JSON格式输出质量评估：
{{
  "effectiveness": "excellent | good | acceptable | poor",
  "scores": {{
    "efficiency": 0.8,
    "quality": 0.75,
    "goal_alignment": 0.9
  }},
  "analysis": "详细分析",
  "suggestions": ["改进建议1", "改进建议2"]
}}
"""

    response = await self.model_client.complete(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    return self._parse_json_response(response["text"])
```

**示例输出**：
```json
{
  "effectiveness": "acceptable",
  "scores": {
    "efficiency": 0.7,
    "quality": 0.6,
    "goal_alignment": 0.8
  },
  "analysis": "请求7题，有效5题，有效率0.71。质量一般，有2题因引用不足被过滤。",
  "suggestions": [
    "在prompt中强调引用的重要性",
    "增加对证据质量的筛选"
  ]
}
```

---

### 4.6 反思改进能力

```python
async def _reflect_and_improve(
    self,
    topic: str,
    strategy: dict,
    result: dict,
    evaluation: dict
) -> dict:
    """反思执行并改进。"""

    prompt = f"""反思以下执行：

策略: {strategy.get('action')}
参数: {strategy.get('action_parameters', {})}
推理: {strategy.get('reasoning', '')}

执行结果:
{json.dumps(result, indent=2, ensure_ascii=False)}

质量评估:
{json.dumps(evaluation, indent=2, ensure_ascii=False)}

请以JSON格式输出反思：
{{
  "what_worked": "什么做对了",
  "what_failed": "什么失败了",
  "root_cause": "失败的根本原因",
  "improvements": ["改进建议1", "改进建议2"],
  "learned_heuristics": {{
    "hard_gap_handling": "新学习的启发式规则",
    "efficiency_optimization": "效率优化的经验"
  }}
}}
"""

    response = await self.model_client.complete(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4
    )

    reflection = self._parse_json_response(response["text"])

    # 将学到的启发式规则存储到Agent的记忆中
    if "learned_heuristics" in reflection:
        self._store_learned_heuristics(topic, reflection["learned_heuristics"])

    return reflection
```

**示例输出**：
```json
{
  "what_worked": "多证据选择策略有效，hard题目有效率提升到0.6",
  "what_failed": "仍有2题因引用不足被过滤",
  "root_cause": "prompt中对引用的要求不够明确",
  "improvements": [
    "在prompt中增加引用格式的示例",
    "提高引用数量的最低要求"
  ],
  "learned_heuristics": {
    "hard_gap_handling": "hard题目应优先使用多证据，且请求数增加20%",
    "efficiency_optimization": "当有效率<0.5时，应先优化prompt再继续生成"
  }
}
```

---

## 五、工具设计详解

### 5.1 工具的定义标准

**工具 = 纯函数，输入输出明确，不包含决策逻辑**

```python
class Tools:
    """Agent可调用的工具集合。"""

    @staticmethod
    async def search_wikipedia(query: str, max_pages: int = 5) -> list[dict]:
        """搜索Wikipedia。

        Args:
            query: 搜索查询词
            max_pages: 最大页面数

        Returns:
            搜索结果列表
        """
        # 纯搜索逻辑，无决策
        from benchforge.utils import search_wikipedia
        return search_wikipedia(query, "en", max_pages)

    @staticmethod
    async def filter_questions(questions: list[dict]) -> dict:
        """过滤题目。

        Args:
            questions: 原始题目列表

        Returns:
            {"passed": [...], "failed": [...], "pass_rate": 0.8}
        """
        # 纯过滤逻辑，无决策
        from benchforge.utils.filter import LightweightFilter
        filter = LightweightFilter()
        passed, failed = filter.filter_questions(questions)
        return {
            "passed": passed,
            "failed": failed,
            "pass_rate": len(passed) / len(questions) if questions else 0
        }
```

---

### 5.2 工具清单

| 工具 | 功能 | 输入 | 输出 | 代码位置 |
|------|------|------|------|----------|
| `search_wikipedia` | 搜索Wikipedia | query, max_pages | 搜索结果 | `utils/retrieval.py` |
| `fetch_page` | 获取页面内容 | page_url, run_id | SourceDocument | `utils/retrieval.py` |
| `chunk_document` | 文档分块 | document, chunk_size | SourceChunk列表 | `utils/chunking.py` |
| `generate_questions_llm` | 调用LLM生成 | evidence_text, params | 原始文本 | `agents/true_agent_v2.py` |
| `filter_questions` | 过滤题目 | 原始题目列表 | (通过, 失败) | `utils/filter.py` |
| `parse_llm_response` | 解析LLM响应 | response_text | 结构化数据 | `utils/filter.py` |

---

### 5.3 工具调用示例

```python
# Agent调用工具
async def _execute_generation(self, params: dict) -> dict:
    """执行生成。"""

    # 1. 采样证据（内部计算，不是工具）
    sampled_evidence = self._sample_evidence(...)

    # 2. 调用工具：生成题目
    generation_result = await self.tools["generate_questions_llm"](
        evidence_text=sampled_evidence["text"],
        target_mode=params["target_mode"],
        target_difficulty=params["target_difficulty"],
        requested_count=params["requested_questions"],
        temperature=params.get("temperature", 0.7)
    )

    # 3. 解析响应（内部计算，不是工具）
    raw_questions = self._parse_questions(generation_result["raw_text"])

    # 4. 调用工具：过滤题目
    filter_result = await self.tools["filter_questions"](raw_questions)

    return {
        "requested_count": params["requested_questions"],
        "raw_count": len(raw_questions),
        "valid_count": len(filter_result["passed"]),
        "valid_rate": filter_result["pass_rate"],
        "questions": filter_result["passed"]
    }
```

---

## 六、内部计算设计详解

### 6.1 内部计算的定义标准

**内部计算 = 确定性逻辑，无需LLM，可被反思优化**

```python
class QuestionGeneratorAgent:
    """Agent的内部计算能力。"""

    def _sample_evidence(
        self,
        topic: str,
        num_evidence: int,
        prefer_multi_chunk: bool = False
    ) -> dict:
        """采样证据。

        这是内部计算，不是工具！
        可根据学到的启发式规则进行优化。
        """
        pool = self.evidence_pools[topic]

        # 获取学到的启发式规则
        heuristics = self._get_learned_heuristics(topic)

        # 根据启发式规则调整采样策略
        if heuristics.get("hard_gap_handling") == "prefer_multi":
            prefer_multi_chunk = True
            num_evidence = max(num_evidence, 6)

        # 采样逻辑（确定性）
        single_samples = self._sample_single_chunks(pool, num_evidence, prefer_multi_chunk)
        multi_samples = self._sample_multi_chunks(pool, num_evidence, prefer_multi_chunk)

        return {
            "single_chunk_ids": [c.chunk_id for c in single_samples],
            "multi_chunk_ids": [m.unit_id for m in multi_samples],
            "text": self._format_evidence_text(single_samples, multi_samples)
        }

    def _parse_questions(self, raw_text: str) -> list[dict]:
        """解析LLM生成的题目。

        这是内部计算，不是工具！
        """
        from benchforge.utils.filter import parse_llm_response
        return parse_llm_response(raw_text)

    def _update_state(self, topic: str, result: dict):
        """更新状态。

        这是内部计算，不是工具！
        """
        state = self.topic_states[topic]
        state.current_round += 1

        # 更新完成计数
        for q in result.get("questions", []):
            mode = q.get("question_mode", "qa")
            diff = q.get("estimated_difficulty", "medium")
            key = f"{mode}:{diff}"
            state.completed_counts[key] = state.completed_counts.get(key, 0) + 1
```

---

### 6.2 内部计算清单

| 计算 | 功能 | 优化来源 |
|------|------|----------|
| `_sample_evidence` | 采样证据 | 反思学习的启发式规则 |
| `_build_evidence_pool` | 构建证据池 | 信号计算器 |
| `_update_state` | 更新状态 | 确定性逻辑 |
| `_parse_questions` | 解析题目 | 确定性逻辑 |
| `_format_evidence_text` | 格式化证据 | 确定性逻辑 |
| `_store_learned_heuristics` | 存储启发式 | 反思输出 |

---

### 6.3 启发式规则应用示例

```python
def _get_learned_heuristics(self, topic: str) -> dict:
    """获取学到的启发式规则。"""
    heuristics = {}

    if topic in self.memory:
        for entry in self.memory[topic]:
            if entry.get("type") == "learned_heuristics":
                heuristics.update(entry.get("content", {}))

    return heuristics

def _sample_evidence(self, topic: str, num_evidence: int, prefer_multi_chunk: bool):
    """应用启发式规则采样证据。"""
    heuristics = self._get_learned_heuristics(topic)

    # 应用学到的规则
    if heuristics.get("hard_gap_handling") == "prefer_multi":
        prefer_multi_chunk = True
        num_evidence = max(num_evidence, 6)

    if heuristics.get("efficiency_optimization") == "focus_high_score":
        # 优先选择高分的证据
        self._filter_low_score_evidence()

    # 执行采样
    # ...
```

---

## 七、文件结构

```
benchforge/agents/
├── __init__.py
├── question_generator.py      # 原有Pipeline（保留对比）
├── true_agent_v2.py           # 新的Agent实现（正确版本）
├── capabilities.py            # Agent能力模块（可选分离）
├── tools.py                   # 工具定义（可选分离）
└── memory.py                  # 记忆系统（可选分离）
```

---

## 八、代码实现

完整的代码实现参考：[true_agent_v2.py](benchforge/agents/true_agent_v2.py)

核心类：

```python
class QuestionGeneratorAgent:
    """问题生成智能体。"""

    def __init__(self, model_client: BaseModelClient):
        self.model_client = model_client

        # Agent的内部状态
        self.topic_states: dict[str, TopicState] = {}
        self.evidence_pools: dict[str, EvidencePool] = {}
        self.memory: dict[str, list[dict]] = {}

        # Agent的能力模块（不是工具！）
        self.capabilities = {
            "understand_state": self._understand_state,
            "analyze_gaps": self._analyze_gaps,
            "select_strategy": self._select_strategy,
            "optimize_parameters": self._optimize_parameters,
            "evaluate_quality": self._evaluate_quality,
            "reflect_and_improve": self._reflect_and_improve,
        }

        # 工具注册（执行能力）
        self.tools = {
            "search_wikipedia": self._search_wikipedia,
            "fetch_page": self._fetch_page,
            "chunk_document": self._chunk_document,
            "generate_questions_llm": self._generate_questions_llm,
            "filter_questions": self._filter_questions,
        }

    # Agent的核心方法
    async def think(self, topic: str) -> AgentDecision:
        """Agent的核心思考过程。"""

    async def run(self, topic: str, max_rounds: int = 10) -> dict:
        """Agent的主执行循环。"""

    # Agent的能力方法（推理层）
    async def _understand_state(self, topic: str) -> dict:
        """理解状态。"""

    async def _analyze_gaps(self, topic: str, state_summary: dict) -> dict:
        """分析缺口。"""

    # ... 其他能力方法

    # Agent的工具方法（执行层）
    async def _search_wikipedia(self, query: str, max_pages: int = 5) -> list[dict]:
        """工具：搜索。"""

    # ... 其他工具方法
```

---

## 九、关键区别总结

### 9.1 Agent能力 vs 工具

| 维度 | Agent能力 | 工具 |
|------|-----------|------|
| 本质 | 推理过程 | 原子操作 |
| 实现方式 | LLM推理 | 确定性代码 |
| 输出 | 决策、策略 | 数据、结果 |
| 示例 | "应该先扩展检索" | 搜索"quantum physics" |
| 位置 | `true_agent_v2.py` | `utils/` |

### 9.2 内部计算 vs 工具

| 维度 | 内部计算 | 工具 |
|------|----------|------|
| 本质 | 确定性逻辑 | 原子操作 |
| 可优化性 | 可被反思优化 | 逻辑固定 |
| 示例 | 采样证据、更新状态 | 搜索、过滤 |
| 位置 | Agent内部 | 独立函数 |

---

## 十、实施建议

### Phase 1: 核心实现
- [ ] 实现 `QuestionGeneratorAgent` 核心类
- [ ] 实现6个能力方法（_understand_state等）
- [ ] 实现6个工具方法（_search_wikipedia等）
- [ ] 实现3个内部计算方法（_sample_evidence等）

### Phase 2: Prompt优化
- [ ] 设计所有能力的Prompt模板
- [ ] 测试Prompt效果
- [ ] 调优Prompt

### Phase 3: 记忆与学习
- [ ] 实现记忆系统
- [ ] 实现启发式规则存储
- [ ] 实现规则应用逻辑

### Phase 4: 测试与优化
- [ ] 对比Pipeline vs Agent
- [ ] 性能优化（缓存、降级）
- [ ] 成本优化

---

## 十一、预期收益

| 指标 | Pipeline | Agent | 提升 |
|------|----------|-------|------|
| 目标达成率 | 85% | 95% | +10% |
| 硬题成功率 | 60% | 80% | +20% |
| 平均轮数 | 8 | 6 | -25% |
| 成本 | 1x | 1.5x | +50% |
| 可解释性 | 低 | 高 | 质的飞跃 |
| 自适应性 | 无 | 强 | 质的飞跃 |