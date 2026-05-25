# 重构计划评估与修正

## 一、总体评价

这份重构计划**方向正确但深度不足**。

### ✅ 合理的地方

1. **职责边界清晰**
   - 明确 QuestionGeneratorAgent 只负责候选题生成
   - 验证、质量判断、Rewrite 由其他Agent负责
   - 边界划分正确

2. **State-driven 设计**
   - 以状态为核心，不是函数链
   - 符合Agent的本质

3. **Controlled Agent 概念**
   - 不是AutoGPT风格的开放Agent
   - 通过Tool白名单控制行为
   - 避免失控问题

4. **分阶段重构思路正确**
   - Phase 1: 引入架构，保持逻辑
   - Phase 2: 引入LLM
   - Phase 3: 自适应优化

5. **工具抽象思路正确**
   - 将现有功能抽象为工具
   - 通过ToolRouter执行
   - 这是正确的方向

---

### ❌ 存在的问题

#### 问题1: Policy设计过于浅层

**当前设计**：
```python
# LLM只做简单的动作选择
"请选择下一步 action: retrieve/expand/sample/generate/finish"
```

**问题**：
- 这只是"把if-else换成LLM"
- 没有真正的推理能力
- LLM不知道"为什么"选择某个动作

**应该是**：
```python
# LLM进行完整的推理
# 1. 理解状态
# 2. 分析缺口
# 3. 选择策略
# 4. 优化参数
# 5. 输出决策

"""
分析当前状态，识别问题，选择策略：

主题: quantum physics
覆盖率: 75%
缺口: qa:hard(剩5), multiple_choice:easy(剩2)
历史效率: 单证据0.3, 多证据0.8

请进行完整推理：
1. 当前状态评估
2. 识别最紧急的缺口及其原因
3. 评估当前证据是否足够
4. 选择最优策略并说明理由
"""
```

---

#### 问题2: 工具与能力混淆

**当前设计**：
```python
tools = {
    "retrieval_tool": ...,     # 工具
    "evidence_tool": ...,      # 工具 ← 这里有问题
    "sampling_tool": ...,      # 工具 ← 这里有问题
    "generation_tool": ...,    # 工具 ← 这里有问题
}
```

**问题**：
- `evidence_tool` 包含采样策略选择，这应该是Agent的能力
- `sampling_tool` 的策略选择应该是Agent决策，不是工具参数
- `generation_tool` 的参数设置应该是Agent决策，不是工具参数

**应该是**：
```python
# Agent的能力（推理层）
capabilities = {
    "understand_state": ...,      # 理解状态
    "analyze_gaps": ...,          # 分析缺口
    "select_strategy": ...,       # 选择策略
    "optimize_parameters": ...,   # 优化参数
}

# 工具（执行层）
tools = {
    "search_wikipedia": ...,      # 纯执行
    "fetch_page": ...,            # 纯执行
    "generate_questions_llm": ..., # 纯执行
    "filter_questions": ...,      # 纯执行
}

# 内部计算（逻辑层）
calculations = {
    "sample_evidence": ...,       # 根据策略执行
    "build_evidence_pool": ...,   # 根据策略执行
}
```

---

#### 问题3: Prompt设计不完整

**当前设计**：
```python
"""
你是题目生成策略控制器。
你的任务不是生成题目，而是决定下一步应该执行什么动作。

请选择下一步 action。
只能从以下动作中选择：
- retrieve_documents
- expand_retrieval
- sample_evidence
- generate_questions
...
"""
```

**问题**：
- 没有状态分析
- 没有缺口识别
- 没有策略推理
- 只是"选择题"

**应该是**：
```python
"""
你是问题生成智能体。

当前状态：
{状态摘要}

你的任务：
1. 分析当前状态，识别问题
2. 识别最紧急的缺口及其原因
3. 评估当前证据是否足够
4. 选择最优策略并说明理由
5. 优化执行参数

输出格式：
{
  "state_assessment": "状态评估",
  "primary_gap": "主缺口",
  "gap_reason": "原因",
  "evidence_sufficiency": "充足度",
  "selected_strategy": "策略",
  "strategy_rationale": "策略理由",
  "optimized_parameters": {...}
}
"""
```

---

#### 问题4: 缺少反思能力

**当前设计**：
```python
while not should_stop:
    observation = build(state)
    action = policy.decide(observation)  # 只有决策
    result = tool_router.execute(action)
    update(state, result)  # 只更新，没有反思
```

**问题**：
- 没有质量评估
- 没有反思机制
- 无法从错误中学习

**应该是**：
```python
while not should_stop:
    # 1. 思考
    decision = agent.think(state)

    # 2. 执行
    result = agent.execute(decision)

    # 3. 评估
    evaluation = agent.evaluate(result)

    # 4. 反思
    reflection = agent.reflect(decision, result, evaluation)

    # 5. 学习
    agent.apply_learnings(reflection)

    # 6. 更新
    update(state, result)
```

---

#### 问题5: Action Schema过于简单

**当前设计**：
```python
@dataclass
class AgentAction:
    action: Literal["retrieve", "expand", "sample", "generate", ...]
    topic: str
    target_mode: str | None = None
    target_difficulty: str | None = None
    batch_size: int | None = None
    queries: list[str] = field(default_factory=list)
    reason: str = ""
```

**问题**：
- 只有"是什么"，没有"为什么"
- 缺少置信度
- 缺少策略信息

**应该是**：
```python
@dataclass
class AgentDecision:
    """Agent的完整决策，不只是动作。"""
    next_action: str
    action_parameters: dict[str, Any]

    # 推理信息
    state_assessment: str        # 状态评估
    primary_gap: str             # 主缺口
    gap_reason: str              # 缺口原因
    selected_strategy: str       # 选择的策略
    strategy_rationale: str      # 策略理由

    # 元信息
    confidence: float            # 置信度
    alternatives: list[str]      # 备选方案
    reasoning: str               # 完整推理过程
```

---

## 二、修正后的架构

### 核心变化

```
原计划：
Observation → NextActionPolicy（简单动作选择） → ToolRouter

修正后：
Agent Capabilities（完整推理）
  ├── 状态理解
  ├── 缺口分析
  ├── 策略选择
  ├── 参数优化
  ├── 质量评估
  └── 反思改进
     ↓
  ToolRouter（执行）
```

---

### 修正后的执行流程

```python
async def _process_topic(self, topic: str):
    while not self._should_stop(topic):

        # ========== 思考阶段（完整推理）==========
        decision = await self.agent.think(topic)

        # ========== 执行阶段（工具调用）==========
        result = await self.tool_router.execute(decision)

        # ========== 评估阶段（质量评估）==========
        evaluation = await self.agent.evaluate(topic, result)

        # ========== 反思阶段（学习改进）==========
        reflection = await self.agent.reflect(
            topic, decision, result, evaluation
        )

        # ========== 学习阶段（应用改进）==========
        self.agent.apply_learnings(topic, reflection)

        # ========== 更新阶段（状态更新）==========
        self.state_manager.update(self.state, result)
```

---

### 修正后的Prompt

#### 1. 状态理解Prompt

```python
"""
你是问题生成智能体的状态理解模块。

当前状态：
{state_summary}

你的任务：
1. 评估当前生成进度
2. 识别关键问题
3. 分析主要瓶颈
4. 总结整体状况

输出格式：
{
  "status_summary": "一句话总结",
  "key_issues": ["问题1", "问题2"],
  "bottleneck": "主要瓶颈",
  "overall_progress": 0.75
}
"""
```

#### 2. 缺口分析Prompt

```python
"""
你是问题生成智能体的缺口分析模块。

状态摘要：
{state_summary}

你的任务：
1. 识别最紧急的缺口
2. 分析缺口存在的原因
3. 评估当前证据是否足够
4. 给出处理建议

输出格式：
{
  "primary_gap": "qa:hard",
  "gap_reason": "原因",
  "evidence_sufficiency": "sufficient | partial | insufficient",
  "suggested_approach": "建议方法",
  "confidence": 0.85
}
"""
```

#### 3. 策略选择Prompt

```python
"""
你是问题生成智能体的策略选择模块。

缺口分析：
{gap_analysis}

当前轮数：{current_round}
历史效率：{efficiency_stats}

你的任务：
1. 根据缺口分析选择最优策略
2. 说明为什么选择这个策略
3. 给出策略的置信度

输出格式：
{
  "selected_strategy": "gap_driven | broad_exploration | quality_focused",
  "strategy_rationale": "策略理由",
  "confidence": 0.85,
  "alternatives": ["备选方案"]
}
"""
```

---

### 修正后的工具定义

#### 真正的工具（纯执行）

```python
class RetrievalTool:
    """检索工具。"""

    async def execute(self, query: str, max_pages: int) -> list[dict]:
        """纯执行，无决策。"""
        from benchforge.utils import search_wikipedia
        return search_wikipedia(query, "en", max_pages)


class GenerationTool:
    """生成工具。"""

    async def execute(
        self,
        evidence_text: str,
        target_mode: str,
        target_difficulty: str,
        requested_count: int,
        temperature: float
    ) -> dict:
        """纯执行，无决策。"""
        response = await self.model_client.complete(...)
        return {"raw_text": response["text"]}
```

#### 不是工具（包含决策逻辑）

```python
# ❌ 错误：这不应该叫"工具"
class SamplingTool:
    async def execute(self, pool, strategy, ...):
        if strategy == "broad_exploration":
            sampler = BroadExplorationSampling()
        else:
            sampler = GapDrivenSampling()
        return sampler.sample(...)

# ✅ 正确：这是Agent的内部计算
class QuestionGeneratorAgent:
    def _sample_evidence(self, topic: str, strategy: str):
        """内部计算，根据Agent选择的策略执行。"""
        pool = self.evidence_pools[topic]

        if strategy == "broad_exploration":
            sampler = BroadExplorationSampling()
        else:
            sampler = GapDrivenSampling()

        return sampler.sample(pool, ...)
```

---

## 三、修正后的分阶段计划

### Phase 1: 架构引入（保持逻辑）

**目标**：引入Agent架构，保持原有逻辑

**步骤**：
1. 定义 `AgentDecision` Schema（包含推理信息）
2. 实现 `ToolRouter`
3. 实现 `RuleBasedAgent`（复制原有逻辑）
4. 重构 `_process_topic` 为循环结构

**保持不变**：
- 检索、生成、过滤逻辑
- Prompt模板
- 状态管理

---

### Phase 2: LLM推理能力

**目标**：用LLM实现完整推理

**步骤**：
1. 实现 `LLMAgent` 类
2. 实现状态理解能力（`_understand_state`）
3. 实现缺口分析能力（`_analyze_gaps`）
4. 实现策略选择能力（`_select_strategy`）
5. 实现参数优化能力（`_optimize_parameters`）
6. 测试LLM决策质量

**关键**：
- 不是简单"选择题"
- 完整的推理过程
- 可解释的决策理由

---

### Phase 3: 反思与学习

**目标**：实现反思机制

**步骤**：
1. 实现质量评估能力（`_evaluate_quality`）
2. 实现反思改进能力（`_reflect_and_improve`）
3. 实现启发式规则存储
4. 实现规则应用逻辑
5. 测试学习效果

**关键**：
- 从错误中学习
- 改进决策策略
- 提升长期表现

---

## 四、关键对比

| 维度 | 原计划 | 修正后 |
|------|--------|--------|
| LLM角色 | 动作选择器 | 完整推理引擎 |
| Prompt设计 | 选择题 | 分析+决策 |
| 工具定义 | 包含决策逻辑 | 纯执行 |
| 反思能力 | 无 | 有 |
| 决策输出 | 动作 | 完整决策 |
| 可解释性 | 低 | 高 |

---

## 五、建议的实施顺序

### 严格遵循的步骤

1. **先设计Prompt**，再写代码
   - 状态理解Prompt
   - 缺口分析Prompt
   - 策略选择Prompt
   - 参数优化Prompt

2. **先测试LLM输出**，再集成
   - 测试Prompt效果
   - 测试JSON解析
   - 测试决策合理性

3. **先实现RuleBased**，再实现LLMBased
   - 确保架构正确
   - 对比效果
   - 渐进替换

---

## 六、总结

### 原计划的优点
- 职责边界清晰
- State-driven设计
- Controlled Agent概念
- 分阶段重构思路

### 原计划的问题
- Policy设计过于浅层
- 工具与能力混淆
- Prompt设计不完整
- 缺少反思能力
- Action Schema过于简单

### 核心修正
1. LLM从"动作选择器"变为"完整推理引擎"
2. Prompt从"选择题"变为"分析+决策"
3. 工具从"包含决策"变为"纯执行"
4. 执行流程从"观察-决策-执行"变为"思考-执行-评估-反思"

### 参考文档
- [true-agent-complete-design.md](docs/true-agent-complete-design.md) - 完整的Agent设计
- [true_agent_v2.py](benchforge/agents/true_agent_v2.py) - 修正后的Agent实现代码