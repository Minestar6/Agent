# Controlled Agent 实施方案（最终版）

## 一、新增3个关键组件

### 1. DecisionValidator

**目的**：统一验证层，防止无效决策

```python
@dataclass
class ValidationIssue:
    """验证问题。"""
    severity: str  # "error" | "warning"
    field: str
    message: str


class DecisionValidator:
    """决策验证器。"""

    MAX_REQUESTED_QUESTIONS = 20  # 最大请求数
    MAX_NO_PROGRESS_ROUNDS = 3    # 最大无进展轮数

    def validate(
        self,
        decision: ControlDecision,
        observation: Observation,
        tool_registry: dict[str, BaseTool]
    ) -> list[ValidationIssue]:
        """验证决策。"""
        issues = []

        # 1. 检查action是否存在
        if decision.next_action not in tool_registry:
            issues.append(ValidationIssue(
                severity="error",
                field="next_action",
                message=f"Unknown action: {decision.next_action}"
            ))

        # 2. 检查参数是否符合schema
        if decision.next_action in tool_registry:
            tool = tool_registry[decision.next_action]
            if not tool.validate_input(decision.action_parameters):
                issues.append(ValidationIssue(
                    severity="error",
                    field="action_parameters",
                    message="Input validation failed"
                ))

        # 3. 检查target_gap是否真的存在
        target_gap = decision.action_parameters.get("target_gap")
        if target_gap and target_gap not in observation.gaps:
            issues.append(ValidationIssue(
                severity="warning",
                field="target_gap",
                message=f"Target gap {target_gap} not found in current gaps"
            ))

        # 4. 检查requested_questions是否超限
        requested = decision.action_parameters.get("requested_questions", 0)
        if requested > self.MAX_REQUESTED_QUESTIONS:
            issues.append(ValidationIssue(
                severity="warning",
                field="requested_questions",
                message=f"Requested {requested} questions exceeds max {self.MAX_REQUESTED_QUESTIONS}"
            ))

        # 5. 检查是否会导致无效循环（简单检测）
        if decision.next_action == "generate_questions":
            requested = decision.action_parameters.get("requested_questions", 0)
            target_gap = decision.action_parameters.get("target_gap", "")
            if target_gap in observation.gaps:
                remaining = observation.gaps[target_gap]
                if requested <= 0:
                    issues.append(ValidationIssue(
                        severity="warning",
                        field="requested_questions",
                        message="Zero requested questions may cause ineffective loop"
                    ))

        return issues

    def is_valid(self, issues: list[ValidationIssue]) -> bool:
        """是否有严重错误。"""
        return all(issue.severity != "error" for issue in issues)
```

**使用方式**：

```python
# 在决策后立即验证
decision = await self.decision_policy.decide(observation)

# 验证
issues = self.decision_validator.validate(
    decision.control,
    observation,
    self.tool_router.tools
)

if not self.decision_validator.is_valid(issues):
    # 记录问题
    for issue in issues:
        logger.warning(f"Decision validation issue: {issue.message}")

    # 有严重错误，fallback到规则策略
    if any(issue.severity == "error" for issue in issues):
        logger.warning("Decision validation failed, falling back to rule-based")
        decision = await self.rule_based_policy.decide(observation)
```

---

### 2. LoopGuard

**目的**：防止无效循环，检测无进展情况

```python
@dataclass
class LoopGuardConfig:
    """循环守护配置。"""
    max_no_progress_rounds: int = 3
    min_gap_reduction_threshold: int = 1
    min_coverage_progress_threshold: float = 0.05


@dataclass
class LoopGuardReport:
    """循环守护报告。"""
    is_stuck: bool
    stuck_rounds: int
    last_progress_round: int
    suggested_actions: list[str]


class LoopGuard:
    """循环守护器。"""

    def __init__(self, config: LoopGuardConfig | None = None):
        """初始化。"""
        self.config = config or LoopGuardConfig()
        self.gap_history: list[int] = []  # 缺口历史
        self.coverage_history: list[float] = []  # 覆盖率历史

    def record_round(self, gap_total: int, coverage_progress: float):
        """记录一轮的结果。"""
        self.gap_history.append(gap_total)
        self.coverage_history.append(coverage_progress)

    def check_stuck(self) -> LoopGuardReport:
        """检查是否陷入无效循环。"""

        if len(self.gap_history) < self.config.max_no_progress_rounds:
            return LoopGuardReport(
                is_stuck=False,
                stuck_rounds=0,
                last_progress_round=len(self.gap_history),
                suggested_actions=[]
            )

        # 检查最近几轮是否有进展
        recent_rounds = self.config.max_no_progress_rounds
        recent_gaps = self.gap_history[-recent_rounds:]
        recent_coverages = self.coverage_history[-recent_rounds:]

        # 检查缺口减少
        gap_reduction = recent_gaps[0] - recent_gaps[-1]

        # 检查覆盖率增加
        coverage_progress = recent_coverages[-1] - recent_coverages[0]

        # 判断是否卡住
        is_stuck = (
            gap_reduction < self.config.min_gap_reduction_threshold and
            coverage_progress < self.config.min_coverage_progress_threshold
        )

        if is_stuck:
            # 查找最后有进展的轮数
            last_progress_round = 0
            for i in range(len(self.gap_history) - 1, 0, -1):
                if i > 0:
                    prev_gap = self.gap_history[i - 1]
                    curr_gap = self.gap_history[i]
                    if prev_gap - curr_gap >= self.config.min_gap_reduction_threshold:
                        last_progress_round = i
                        break

            # 生成建议行动
            suggested_actions = self._generate_stuck_actions()

            return LoopGuardReport(
                is_stuck=True,
                stuck_rounds=recent_rounds,
                last_progress_round=last_progress_round,
                suggested_actions=suggested_actions
            )

        return LoopGuardReport(
            is_stuck=False,
            stuck_rounds=0,
            last_progress_round=len(self.gap_history),
            suggested_actions=[]
        )

    def _generate_stuck_actions(self) -> list[str]:
        """生成卡住时的建议行动。"""
        return [
            "expand_evidence",     # 扩展证据池
            "adjust_strategy",     # 调整策略
            "finish_topic",        # 强制完成
        ]

    def reset(self):
        """重置历史。"""
        self.gap_history = []
        self.coverage_history = []
```

**使用方式**：

```python
# 在循环中检查
while not self._should_stop(topic):

    # ... 执行逻辑 ...

    # 更新LoopGuard
    state = self.state["topic_states"][topic]
    gap_total = sum(state.remaining_counts.values())
    coverage_progress = sum(
        state.completed_counts.get(k, 0) / state.target_counts.get(k, 1)
        for k in state.target_counts
    ) / len(state.target_counts) if state.target_counts else 0

    self.loop_guard.record_round(gap_total, coverage_progress)

    # 检查是否卡住
    guard_report = self.loop_guard.check_stuck()

    if guard_report.is_stuck:
        logger.warning(
            f"Loop stuck for {guard_report.stuck_rounds} rounds, "
            f"last progress at round {guard_report.last_progress_round}"
        )

        # 强制触发建议行动
        forced_action = guard_report.suggested_actions[0]
        logger.warning(f"Forcing action: {forced_action}")

        decision = ControlDecision(
            next_action=forced_action,
            action_parameters={"topic": topic}
        )
```

---

### 3. Phase 1 Tool选择

**原则**：Phase 1只抽3个Tool，其他保留原逻辑

**抽离的工具**：
```python
# 1. SamplingTool
class SamplingTool(BaseTool):
    """采样工具。"""
    @property
    def spec(self) -> ToolSpec: ...

    async def execute(self, parameters, state) -> ToolResult: ...

# 2. GenerationTool
class GenerationTool(BaseTool):
    """生成工具。"""
    @property
    def spec(self) -> ToolSpec: ...

    async def execute(self, parameters, state) -> ToolResult: ...

# 3. RetrievalTool
class RetrievalTool(BaseTool):
    """检索工具。"""
    @property
    def spec(self) -> ToolSpec: ...

    async def execute(self, parameters, state) -> ToolResult: ...
```

**保留原逻辑的组件**：
```python
# CoverageManager - 保留原逻辑
# 不抽离为Tool，继续使用原有的 _update_state, _calculate_coverage 等

# ArtifactManager - 保留原逻辑
# 不抽离为Tool，继续使用原有的 artifact_store, _save_results 等
```

**ToolRouter只注册3个工具**：

```python
class ToolRouter:
    """工具路由器（Phase 1版本，只注册3个工具）。"""

    def __init__(self):
        self.tools = {
            "sample_evidence": SamplingTool(),
            "generate_questions": GenerationTool(),
            "expand_retrieval": RetrievalTool(),
        }
        self._register_tools()

    # 其他方法：execute, execute_with_retry, list_tools, ...
```

---

## 二、修订后的完整架构

```
QuestionGeneratorAgent（中量级 Controlled Agent）
  ├── ObservationBuilder           # 摘要化观察
  ├── DecisionPolicy
  │     ├── RuleBasedDecisionPolicy     # 核心策略（baseline + fallback）
  │     └── LLMDecisionPolicy            # 只输出Intent
  ├── DecisionValidator           # 统一验证层（新增）
  ├── IntentCompiler              # Intent → ControlDecision
  ├── ToolRouter                  # 只注册3个工具
  │     ├── SamplingTool (BaseTool + ToolSpec)
  │     ├── GenerationTool
  │     └── RetrievalTool
  ├── LoopGuard                   # 循环守护器（新增）
  ├── CoverageManager             # 保留原逻辑
  └── ArtifactManager              # 保留原逻辑
```

---

## 三、修订后的执行流程

```python
async def _process_topic(self, topic: str, plan: GenerationPlan):
    """修订后的执行流程。"""

    # 重置LoopGuard
    self.loop_guard.reset()

    while not self._should_stop(topic):

        # 1. 构建观察（摘要化）
        observation = self.observation_builder.build(self.state, topic)

        # 2. 决策
        try:
            decision = await self.decision_policy.decide(observation)
        except Exception as e:
            logger.warning(f"Policy failed: {e}, falling back to rule-based")
            decision = await self.rule_based_policy.decide(observation)

        # 3. 验证决策（新增）
        validation_issues = self.decision_validator.validate(
            decision.control,
            observation,
            self.tool_router.tools
        )

        if not self.decision_validator.is_valid(validation_issues):
            # 记录问题
            for issue in validation_issues:
                logger.warning(f"Decision validation issue: {issue.message}")

            # 有严重错误，fallback
            if any(issue.severity == "error" for issue in validation_issues):
                logger.warning("Decision validation failed, falling back")
                decision = await self.rule_based_policy.decide(observation)

        # 4. 检查LoopGuard（新增）
        guard_report = self.loop_guard.check_stuck()
        if guard_report.is_stuck:
            logger.warning(f"Loop stuck, forcing action: {guard_report.suggested_actions[0]}")
            decision = ControlDecision(
                next_action=guard_report.suggested_actions[0],
                action_parameters={"topic": topic}
            )

        # 5. 执行（带Spec/Contract/Retry）
        tool_result = await self.tool_router.execute(
            decision.control.next_action,
            decision.control.action_parameters,
            self.state
        )

        # 6. 更新状态
        self.state["history"].append(decision.control)
        await self.state_manager.update(self.state, decision, tool_result)

        # 7. 更新LoopGuard（新增）
        state = self.state["topic_states"][topic]
        gap_total = sum(state.remaining_counts.values())
        coverage_progress = self._calculate_coverage_progress(state)
        self.loop_guard.record_round(gap_total, coverage_progress)

        # 8. 轻量反思（后置，可选）
        if self.enable_lightweight_reflection:
            reflection = await self._lightweight_reflection(topic, decision, tool_result, self.state)
```

---

## 四、分阶段计划（最终版）

### Phase 1: 架构引入（稳定优先）

**目标**：引入核心架构，保持行为不变

**新增组件**：
- [ ] `schemas/agent_decision.py`：ControlDecision + DecisionReasoning分离
- [ ] `schemas/observation.py`：摘要化的观察
- [ ] `agents/observation_builder.py`：构建摘要化观察
- [ ] `policies/rule_based_policy.py`：规则策略（复制原有逻辑）
- [ ] `decision_validator.py`：决策验证器（新增）
- [ ] `loop_guard.py`：循环守护器（新增）
- [ ] `router/tool_router.py`：工具路由器
- [ ] `tools/sampling_tool.py`：采样工具（BaseTool + ToolSpec）
- [ ] `tools/generation_tool.py`：生成工具
- [ ] `tools/retrieval_tool.py`：检索工具

**修改组件**：
- [ ] `agents/question_generator.py`：重构为新的执行流程

**保持不变**：
- CoverageManager - 保留原逻辑
- ArtifactManager - 保留原逻辑
- 不引入LLM Policy
- 不引入Intent

**验收标准**：
- 规则策略行为与原有Pipeline一致
- DecisionValidator能检测无效决策
- LoopGuard能检测无效循环
- 工具能正常执行

---

### Phase 2: Intent层（增强控制）

**目标**：LLM只输出Intent，Rule Layer编排

**新增组件**：
- [ ] `schemas/agent_intent.py`：AgentIntent Schema
- [ ] `policies/intent_compiler.py`：Intent编译器
- [ ] `policies/llm_policy.py`：LLM策略（只输出Intent）

**修改组件**：
- [ ] `agents/question_generator.py`：集成LLM策略

**验收标准**：
- LLM能正确输出Intent
- IntentCompiler能正确编译为ControlDecision
- LLM失败时能fallback到规则策略
- 不出现invalid action

---

### Phase 3: 优化与反思

**目标**：轻量反思、策略优化

**新增组件**：
- [ ] `agents/reflection.py`：轻量反思模块

**优化组件**：
- [ ] `policies/rule_based_policy.py`：根据反思调整策略
- [ ] `policies/llm_policy.py`：根据反思优化Prompt

**验收标准**：
- 反思能检测生成过程问题
- 反思能触发策略调整
- LoopGuard能强制解决无效循环

---

## 五、文件结构（Phase 1）

```
benchforge/
├── schemas/
│   ├── agent_decision.py          # 新增：ControlDecision + DecisionReasoning
│   ├── observation.py             # 新增：摘要化的观察
│   └── validation.py              # 新增：验证相关Schema
├── agents/
│   ├── observation_builder.py     # 新增：构建摘要化观察
│   ├── decision_validator.py      # 新增：决策验证器
│   ├── loop_guard.py              # 新增：循环守护器
│   └── question_generator.py      # 修改：重构为Agent架构
├── policies/
│   ├── rule_based_policy.py       # 新增：规则策略
│   └── intent_compiler.py         # Phase 2
├── router/
│   └── tool_router.py             # 新增：工具路由器
└── tools/
    ├── base_tool.py               # 新增：BaseTool基类
    ├── sampling_tool.py           # 新增：采样工具
    ├── generation_tool.py         # 新增：生成工具
    └── retrieval_tool.py          # 新增：检索工具
```

---

## 六、关键原则总结

1. **LLM只输出Intent，不直接控制action**
   - LLM负责"方向"
   - Rule负责"控制"

2. **Decision瘦身**
   - ControlDecision进入状态
   - DecisionReasoning只写日志

3. **Observation摘要化**
   - 不直接喂完整数据
   - 压缩历史为模式摘要

4. **ToolSpec与Contract**
   - 输入输出验证
   - 重试策略

5. **DecisionValidator**
   - 统一验证层
   - 防止无效决策

6. **LoopGuard**
   - 检测无效循环
   - 强制触发行动

7. **Phase 1渐进式**
   - 只抽3个工具
   - 其他保留原逻辑

8. **Reflection后置**
   - 基于更新后的状态评估

---

## 七、实施检查清单

### Phase 1: 架构引入
- [ ] ControlDecision + DecisionReasoning Schema
- [ ] Observation Schema（摘要化）
- [ ] ObservationBuilder
- [ ] RuleBasedDecisionPolicy
- [ ] DecisionValidator
- [ ] LoopGuard
- [ ] BaseTool + ToolSpec
- [ ] SamplingTool
- [ ] GenerationTool
- [ ] RetrievalTool
- [ ] ToolRouter
- [ ] 重构QuestionGeneratorAgent
- [ ] 测试：规则策略行为一致
- [ ] 测试：DecisionValidator验证
- [ ] 测试：LoopGuard检测

### Phase 2: Intent层
- [ ] AgentIntent Schema
- [ ] IntentCompiler
- [ ] LLMDecisionPolicy
- [ ] 集成LLM策略
- [ ] 测试：Intent输出
- [ ] 测试：Intent编译
- [ ] 测试：Fallback机制

### Phase 3: 优化与反思
- [ ] 轻量反思模块
- [ ] 策略调整逻辑
- [ ] Prompt优化
- [ ] 测试：反思效果
- [ ] 测试：策略调整

---

## 八、最终路线图

### Week 1-2: Phase 1
- 引入核心架构
- 保持行为不变
- 验证稳定性

### Week 3: Phase 2
- 引入LLM Intent
- 测试与调优

### Week 4: Phase 3
- 轻量反思
- 策略优化

---

这个方案现在是一个真正能长期演进成稳定Production Controlled Agent的路线。需要我开始实施Phase 1吗？