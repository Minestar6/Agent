# Controlled Agent 实施方案（修订版）

## 一、核心修订

基于专业反馈，对原方案进行以下修正：

### 修订1: Decision瘦身

**问题**：原方案把reasoning字段塞进Decision，会导致state膨胀、prompt token爆炸

**修正后**：

```python
@dataclass
class ControlDecision:
    """控制决策：只包含执行所需的信息。"""
    next_action: str
    action_parameters: dict[str, Any]


@dataclass
class DecisionReasoning:
    """决策推理：只写日志，不进入长期memory。"""
    summary: str           # 一句话总结
    primary_gap: str       # 主缺口
    selected_strategy: str # 选择的策略
    confidence: float      # 置信度


@dataclass
class AgentDecision:
    """完整决策 = 控制 + 推理。"""
    control: ControlDecision
    reasoning: DecisionReasoning

    # 便捷方法
    @property
    def next_action(self) -> str:
        return self.control.next_action

    @property
    def action_parameters(self) -> dict[str, Any]:
        return self.control.action_parameters
```

**状态管理**：

```python
# state/history 只保存 ControlDecision
state["history"].append(decision.control)

# reasoning 只写日志，不进入长期memory
logger.info(f"Decision reasoning: {decision.reasoning.summary}")
```

---

### 修订2: Observation摘要化

**问题**：原方案直接喂完整数据，会导致prompt不可控

**修正后**：

```python
@dataclass
class Observation:
    """Agent观察到的状态（摘要化）。"""

    topic: str

    # 摘要化的覆盖率（不是完整数据）
    coverage_summary: str          # "已完成75%，主要缺口qa:hard"
    primary_gap: str               # "qa:hard"
    gap_remaining: int             # 5

    # 摘要化的历史（不是完整history）
    compressed_history: list[str]  # ["连续3轮qa:hard生成不足", "多证据成功率高"]

    # 关键指标（摘要，不是完整统计）
    round: int
    max_rounds: int
    evidence_sufficiency: str      # "sufficient | partial | insufficient"
    single_evidence_efficiency: float
    multi_evidence_efficiency: float

    def to_prompt_text(self) -> str:
        """转换为Prompt文本（控制长度）。"""
        return f"""主题: {self.topic}
轮数: {self.round}/{self.max_rounds}
覆盖率: {self.coverage_summary}
主缺口: {self.primary_gap} (剩余{self.gap_remaining}题)
证据状态: {self.evidence_sufficiency}
单证据效率: {self.single_evidence_efficiency:.2f}
多证据效率: {self.multi_evidence_efficiency:.2f}
历史摘要: {'; '.join(self.compressed_history[-3:])}
"""
```

**ObservationBuilder负责压缩**：

```python
class ObservationBuilder:
    """构建Agent观察（负责摘要化）。"""

    def build(self, state: dict, topic: str) -> Observation:
        """构建观察对象（摘要化）。"""
        topic_state = state["topic_states"].get(topic)
        evidence_pool = state.get("evidence_pools", {}).get(topic)
        history = state.get("history", [])

        # 计算覆盖率摘要
        coverage_summary = self._summarize_coverage(topic_state)

        # 识别主缺口
        primary_gap, gap_remaining = self._identify_primary_gap(topic_state)

        # 压缩历史（不是直接history[-3:]）
        compressed_history = self._compress_history(history)

        # 摘要化证据状态
        evidence_sufficiency = self._assess_evidence_sufficiency(evidence_pool)
        single_eff, multi_eff = self._get_efficiency_scores(evidence_pool)

        return Observation(
            topic=topic,
            coverage_summary=coverage_summary,
            primary_gap=primary_gap,
            gap_remaining=gap_remaining,
            compressed_history=compressed_history,
            round=topic_state.current_round,
            max_rounds=state.get("max_rounds_per_topic", 10),
            evidence_sufficiency=evidence_sufficiency,
            single_evidence_efficiency=single_eff,
            multi_evidence_efficiency=multi_eff,
        )

    def _compress_history(self, history: list) -> list[str]:
        """压缩历史为摘要。"""
        if not history:
            return []

        compressed = []

        # 分析历史模式
        recent_decisions = history[-5:] if len(history) >= 5 else history

        # 检测连续失败
        failure_streak = self._detect_failure_streak(recent_decisions)
        if failure_streak > 0:
            compressed.append(f"连续{failure_streak}轮生成不足")

        # 检测高效策略
        high_efficiency_strategies = self._detect_high_efficiency(recent_decisions)
        if high_efficiency_strategies:
            compressed.append(f"{high_efficiency_strategies}策略成功率较高")

        return compressed
```

---

### 修订3: LLM只输出Intent

**问题**：原方案LLM直接控制action，风险太高

**修正后**：

```python
@dataclass
class AgentIntent:
    """Agent意图：LLM只输出高层意图，不直接控制action。"""
    intent: str                    # "increase_hard_questions"
    reason: str                    # "qa:hard缺口持续存在"
    target_gap: str                # "qa:hard"
    suggested_strategy: str        # "gap_driven"
    confidence: float


class IntentCompiler:
    """意图编译器：将Intent转换为ControlDecision。"""

    INTENT_ACTION_MAP = {
        "increase_hard_questions": "generate_questions",
        "increase_coverage": "generate_questions",
        "expand_evidence": "expand_retrieval",
        "adjust_strategy": "adjust_sampling_strategy",
        "complete_topic": "finish_topic",
    }

    def compile(self, intent: AgentIntent, observation: Observation) -> ControlDecision:
        """将意图编译为控制决策。"""

        action = self.INTENT_ACTION_MAP.get(intent.intent, "generate_questions")

        # Rule Layer负责参数编排
        parameters = self._build_parameters(intent, observation)

        return ControlDecision(
            next_action=action,
            action_parameters=parameters,
        )

    def _build_parameters(self, intent: AgentIntent, observation: Observation) -> dict:
        """根据意图构建参数（Rule Layer控制）。"""

        if intent.intent == "increase_hard_questions":
            return {
                "strategy": intent.suggested_strategy,
                "target_gap": intent.target_gap,
                "num_evidence": self._calculate_evidence_count(observation),
                "prefer_multi_chunk": self._should_prefer_multi_chunk(observation),
                "requested_questions": observation.gap_remaining + 2,
            }

        elif intent.intent == "expand_evidence":
            return {
                "queries": self._generate_expansion_queries(intent.target_gap),
            }

        else:
            return {}

    def _calculate_evidence_count(self, observation: Observation) -> int:
        """计算需要的证据数量（Rule控制，不是LLM决定）。"""
        if observation.gap_remaining <= 3:
            return 4
        elif observation.gap_remaining <= 6:
            return 5
        else:
            return 6

    def _should_prefer_multi_chunk(self, observation: Observation) -> bool:
        """是否应该偏好多证据（Rule控制）。"""
        # 基于历史效率决定
        return observation.multi_evidence_efficiency > observation.single_evidence_efficiency
```

**LLM Policy只输出Intent**：

```python
class LLMDecisionPolicy:
    """基于LLM的决策策略（只输出Intent）。"""

    async def decide(self, observation: Observation) -> AgentDecision:
        """基于LLM输出意图，由IntentCompiler编译。"""

        # 1. LLM输出Intent
        intent = await self._get_intent_from_llm(observation)

        # 2. IntentCompiler编译为ControlDecision
        compiler = IntentCompiler()
        control_decision = compiler.compile(intent, observation)

        # 3. 构建DecisionReasoning（不进入长期memory）
        reasoning = DecisionReasoning(
            summary=f"意图：{intent.intent}，目标缺口：{intent.target_gap}",
            primary_gap=intent.target_gap,
            selected_strategy=intent.suggested_strategy,
            confidence=intent.confidence,
        )

        return AgentDecision(
            control=control_decision,
            reasoning=reasoning,
        )

    async def _get_intent_from_llm(self, observation: Observation) -> AgentIntent:
        """从LLM获取意图。"""

        prompt = f"""你是问题生成策略决策引擎。

当前状态：
{observation.to_prompt_text()}

你的任务是选择下一步的策略意图。

可选意图：
- increase_hard_questions: 增加hard难度题目
- increase_coverage: 提高覆盖率
- expand_evidence: 扩展证据池
- adjust_strategy: 调整生成策略
- complete_topic: 完成当前主题

请输出JSON：
{{
  "intent": "increase_hard_questions",
  "reason": "qa:hard缺口持续存在",
  "target_gap": "qa:hard",
  "suggested_strategy": "gap_driven",
  "confidence": 0.85
}}
"""

        response = await self.model_client.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        intent_data = self._parse_response(response["text"])
        return AgentIntent(**intent_data)
```

---

### 修订4: Reflection后移

**问题**：原方案reflection在update_state之前，看不到最新状态

**修正后**：

```python
async def _process_topic(self, topic: str, plan: GenerationPlan):
    """处理单个主题（修订后的执行流程）。"""

    while not self._should_stop(topic):

        # 1. 构建观察（摘要化）
        observation = self.observation_builder.build(self.state, topic)

        # 2. 决策（Intent → ControlDecision）
        decision = await self.decision_policy.decide(observation)

        # 3. 执行
        tool_result = await self.tool_router.execute(
            decision.control.next_action,
            decision.control.action_parameters,
            self.state
        )

        # 4. 更新状态（先更新）
        await self.state_manager.update(self.state, decision, tool_result)

        # 5. 轻量反思（后置，可以看到最新状态）
        if self.enable_lightweight_reflection:
            reflection = await self._lightweight_reflection(
                topic,
                decision,
                tool_result,
                self.state  # 传入更新后的state
            )
```

**Reflection基于新状态**：

```python
async def _lightweight_reflection(
    self,
    topic: str,
    decision: AgentDecision,
    result: dict,
    new_state: dict  # 传入更新后的state
) -> dict:
    """轻量反思：基于最新状态评估。"""

    # 可以看到最新的覆盖率变化
    topic_state = new_state["topic_states"].get(topic)

    # 可以看到缺口是否真正减少
    gap_before = result.get("gap_before", 0)
    gap_after = topic_state.remaining_counts.get(decision.reasoning.primary_gap, 0)
    gap_reduction = gap_before - gap_after

    # 可以看到证据是否真正生效
    evidence_usage = result.get("evidence_usage", {})

    reflection = {
        "gap_reduction": gap_reduction,
        "evidence_effectiveness": evidence_usage.get("success_rate", 0),
        "suggestions": [],
    }

    # 根据实际效果给出建议
    if gap_reduction < 1:
        reflection["suggestions"].append("策略效果不明显，考虑调整")

    return reflection
```

---

### 修订5: ToolSpec与Contract

**问题**：原方案ToolRouter太RPC，缺少contract

**修正后**：

```python
@dataclass
class ToolSpec:
    """工具规格。"""
    name: str
    description: str
    input_schema: dict[str, Any]      # JSON Schema
    output_schema: dict[str, Any]     # JSON Schema
    retryable: bool = False
    max_retries: int = 3
    timeout: int = 60


@dataclass
class ToolResult:
    """工具执行结果。"""
    success: bool
    output: dict[str, Any]
    error: str | None = None
    retries: int = 0


class BaseTool(ABC):
    """工具基类。"""

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        """返回工具规格。"""
        pass

    @abstractmethod
    async def execute(self, parameters: dict[str, Any], state: dict) -> ToolResult:
        """执行工具。"""
        pass

    def validate_input(self, parameters: dict[str, Any]) -> bool:
        """验证输入参数。"""
        # 使用input_schema验证
        return True


class SamplingTool(BaseTool):
    """采样工具。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="sample_evidence",
            description="从证据池中采样证据单元",
            input_schema={
                "type": "object",
                "properties": {
                    "strategy": {"type": "string", "enum": ["gap_driven", "broad_exploration"]},
                    "target_gap": {"type": "string", "pattern": "^(qa|multiple_choice):(easy|medium|hard)$"},
                    "num_evidence": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["strategy", "target_gap", "num_evidence"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "batch": {"type": "object"},
                    "single_chunk_count": {"type": "integer"},
                    "multi_chunk_count": {"type": "integer"},
                },
            },
            retryable=False,
        )

    async def execute(self, parameters: dict[str, Any], state: dict) -> ToolResult:
        """执行采样。"""

        # 验证输入
        if not self.validate_input(parameters):
            return ToolResult(success=False, output={}, error="Invalid input")

        # 执行逻辑
        # ...

        return ToolResult(success=True, output=result)
```

**ToolRouter增强**：

```python
class ToolRouter:
    """工具路由器（增强版）。"""

    def __init__(self):
        self.tools: dict[str, BaseTool] = {}
        self._register_tools()

    def _register_tools(self):
        """注册工具。"""
        self.tools = {
            "sample_evidence": SamplingTool(),
            "generate_questions": GenerationTool(),
            "expand_retrieval": RetrievalTool(),
        }

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        state: dict
    ) -> ToolResult:
        """执行工具（带验证和重试）。"""

        tool = self.tools.get(action)
        if not tool:
            return ToolResult(success=False, output={}, error=f"Unknown action: {action}")

        # 验证输入
        if not tool.validate_input(parameters):
            return ToolResult(success=False, output={}, error="Input validation failed")

        # 执行（带重试）
        result = await self._execute_with_retry(tool, parameters, state)

        return result

    async def _execute_with_retry(
        self,
        tool: BaseTool,
        parameters: dict[str, Any],
        state: dict
    ) -> ToolResult:
        """带重试的执行。"""

        if not tool.spec.retryable:
            return await tool.execute(parameters, state)

        for attempt in range(tool.spec.max_retries):
            try:
                result = await tool.execute(parameters, state)
                if result.success:
                    return result
            except Exception as e:
                logger.warning(f"Tool {tool.spec.name} attempt {attempt + 1} failed: {e}")

        return ToolResult(success=False, output={}, error="Max retries exceeded")

    def list_tools(self) -> list[ToolSpec]:
        """列出所有工具规格。"""
        return [tool.spec for tool in self.tools.values()]
```

---

## 二、修订后的架构

```
QuestionGeneratorAgent
  ├── ObservationBuilder          # 摘要化观察
  ├── DecisionPolicy
  │     ├── RuleBasedDecisionPolicy     # 核心策略
  │     └── LLMDecisionPolicy            # 只输出Intent
  ├── IntentCompiler              # Intent → ControlDecision
  ├── ToolRouter                  # 带Spec/Contract/Retry
  │     ├── SamplingTool (BaseTool + ToolSpec)
  │     ├── GenerationTool
  │     └── RetrievalTool
  ├── CoverageManager
  ├── ArtifactManager
  └── LightweightReflection       # 后置，基于新状态
```

---

## 三、修订后的执行流程

```python
async def _process_topic(self, topic: str, plan: GenerationPlan):
    """修订后的执行流程。"""

    while not self._should_stop(topic):

        # 1. 构建观察（摘要化）
        observation = self.observation_builder.build(self.state, topic)

        # 2. 决策
        #    RuleBased: Observation → ControlDecision
        #    LLM: Observation → Intent → IntentCompiler → ControlDecision
        decision = await self.decision_policy.decide(observation)

        # 3. 执行（带Spec/Contract/Retry）
        tool_result = await self.tool_router.execute(
            decision.control.next_action,
            decision.control.action_parameters,
            self.state
        )

        # 4. 更新状态（先更新）
        #    只保存ControlDecision，不保存Reasoning
        self.state["history"].append(decision.control)
        await self.state_manager.update(self.state, decision, tool_result)

        # 5. 轻量反思（后置，基于新状态）
        if self.enable_lightweight_reflection:
            reflection = await self._lightweight_reflection(
                topic, decision, tool_result, self.state
            )
```

---

## 四、修订后的分阶段计划

### Phase 1: 架构引入（保持稳定）

**核心**：保留RuleBasedDecisionPolicy作为核心

**目标**：
- 引入ObservationBuilder（摘要化）
- 引入ToolRouter（带Spec/Contract）
- 引入ControlDecision（瘦身）
- 保持原有逻辑不变

**不做**：
- 不引入LLM Policy
- 不引入Intent

---

### Phase 2: Intent层（增强控制）

**核心**：LLM只输出Intent，Rule Layer做编排

**目标**：
- 引入AgentIntent
- 引入IntentCompiler
- LLM Policy只输出Intent
- IntentCompiler编译为ControlDecision

**优势**：
- LLM负责"方向"
- Rule负责"控制"
- 稳定可控

---

### Phase 3: Reflection优化

**核心**：基于新状态的轻量反思

**目标**：
- Reflection后移
- 基于最新覆盖率评估
- 基于实际效果调整

---

## 五、关键差异对比

| 维度 | 原方案 | 修订后 |
|------|--------|--------|
| Decision | 包含reasoning | ControlDecision + DecisionReasoning分离 |
| Observation | 完整数据 | 摘要化 |
| LLM角色 | 直接输出action | 只输出Intent |
| Reflection位置 | update前 | update后 |
| ToolRouter | RPC风格 | 带Spec/Contract/Retry |
| 状态管理 | reasoning进入history | 只有control进入history |

---

## 六、核心原则

1. **LLM只输出Intent，不直接控制action**
   - LLM负责"方向"
   - Rule负责"控制"

2. **Decision瘦身**
   - ControlDecision进入状态
   - Reasoning只写日志

3. **Observation摘要化**
   - 不直接喂完整数据
   - 压缩历史为模式摘要

4. **ToolSpec与Contract**
   - 每个工具有明确规格
   - 输入输出有验证
   - 支持重试策略

5. **Reflection后置**
   - 基于更新后的状态评估
   - 可以看到实际效果

---

## 七、实施检查清单

### Phase 1
- [ ] ControlDecision + DecisionReasoning分离
- [ ] ObservationBuilder摘要化
- [ ] ToolSpec + BaseTool
- [ ] ToolRouter增强（验证、重试）
- [ ] RuleBasedDecisionPolicy
- [ ] 测试架构稳定性

### Phase 2
- [ ] AgentIntent Schema
- [ ] IntentCompiler
- [ ] LLMDecisionPolicy（只输出Intent）
- [ ] 测试Intent编译正确性
- [ ] 测试fallback机制

### Phase 3
- [ ] Reflection后置
- [ ] 基于新状态的评估逻辑
- [ ] 测试反思效果