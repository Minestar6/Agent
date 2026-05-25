# BenchForge `QuestionGeneratorAgent` 重构实施方案（仅题目生成智能体）

## 文档目标

本方案仅针对：

```text
agent/benchforge/agents/question_generator.py
```

进行 Agentic 化重构。

注意：

```text
QuestionGeneratorAgent
≠ 最终验证智能体
```

因此：

- 不包含深度 Verification
- 不包含 Rewrite
- 不包含最终质量裁决

这些由后续：

```text
QuestionVerificationAgent
```

负责。

---

# 1. 当前架构分析

当前 `QuestionGeneratorAgent` 已具备：

## 已有能力

### 1. 状态驱动

已有：

```python
TopicState
```

包含：

- coverage
- difficulty distribution
- mode distribution
- generation progress

这是 Agent 化的重要基础。

---

### 2. 多轮循环

已有：

```python
while not topic_complete:
```

不是单次 pipeline。

---

### 3. Evidence Pool

已有：

```python
EvidencePool
MultiChunkBuilder
```

支持：

- single chunk
- multi chunk
- retrieval expansion

---

### 4. Gap-driven generation

已有：

```python
identify_main_gap()
```

说明系统已经：

```text
coverage-aware
```

---

### 5. Global backfill

已有：

```python
_global_backfill()
```

说明存在：

```text
global optimization
```

---

# 当前本质

当前架构：

```text
State-machine workflow
```

而不是：

```text
Tool-driven controlled agent
```

原因：

```text
下一步行为由 Python 规则决定
```

例如：

```python
build_next_step_plan()
```

内部：

```python
if hard_gap:
    expand_retrieval()

elif insufficient_multi_chunk:
    increase_multi_chunk_ratio()
```

这是：

```text
Rule-based policy
```

不是：

```text
Agentic policy
```

---

# 2. 重构目标

将：

```text
QuestionGeneratorAgent
= Stateful Workflow
```

升级为：

```text
QuestionGeneratorAgent
= Controlled Agentic Generation Component
```

具备：

| 能力 | 是否需要 |
|---|---|
| 状态驱动 | ✅ |
| 动态动作决策 | ✅ |
| Tool abstraction | ✅ |
| Coverage-aware generation | ✅ |
| Retrieval adaptation | ✅ |
| Multi-round execution | ✅ |
| Artifact traceability | ✅ |
| Lightweight filtering | ✅ |
| Verification | ❌ |
| Rewrite | ❌ |
| Final quality judgement | ❌ |

---

# 3. 新架构设计

## 3.1 总体架构

```text
BenchForge Planning Agent
        ↓
GenerationPlan
        ↓
QuestionGeneratorAgent
        ├── NextActionPolicy
        ├── ToolRouter
        ├── RetrievalTool
        ├── EvidenceTool
        ├── SamplingTool
        ├── GenerationTool
        ├── FormatFilterTool
        ├── CoverageManager
        ├── StateManager
        └── ArtifactManager
        ↓
CandidateQuestionSet
        ↓
QuestionVerificationAgent
```

---

## 3.2 核心思想

核心变化：

```text
把“下一步做什么”
从 Python if-else
转变为：
Policy 决策
```

即：

当前：

```python
build_next_step_plan()
```

未来：

```python
next_action_policy.decide()
```

---

# 4. 重构原则

## 原则 1

QuestionGeneratorAgent：

```text
只负责候选题生成
```

不负责：

- 最终验证
- 深度质量判断
- Rewrite

---

## 原则 2

采用：

```text
Controlled Agent
```

不是：

```text
AutoGPT-style open agent
```

所有行为必须：

```text
通过 Tool 白名单执行
```

---

## 原则 3

State 是系统核心。

从：

```text
Function Chain
```

变成：

```text
State-driven execution
```

---

# 5. 新目录结构

```text
agent/benchforge/

  agents/
    question_generator.py

  policies/
    next_action_policy.py
    rule_based_policy.py
    llm_policy.py

  tools/
    retrieval_tool.py
    evidence_tool.py
    sampling_tool.py
    generation_tool.py
    format_filter_tool.py
    coverage_tool.py
    artifact_tool.py

  router/
    tool_router.py

  state/
    agent_state.py
    state_manager.py
    observation_builder.py

  schemas/
    agent_action.py
    tool_result.py
    observation.py
```

---

# 6. 核心模块设计

## 6.1 QuestionGeneratorAgent

### 职责

负责：

- 生命周期管理
- topic 执行
- 调度 policy
- 调度 tools
- 管理 state
- 输出 candidate questions

### 接口

```python
class QuestionGeneratorAgent:

    async def execute(
        self,
        generation_plan: GenerationPlan
    ) -> CandidateQuestionSet:
        ...
```

### 主循环

```python
async def _process_topic(self, topic: str):

    while not self._should_stop(topic):

        observation = self.observation_builder.build(
            self.state,
            topic
        )

        action = await self.next_action_policy.decide(
            observation
        )

        tool_result = await self.tool_router.execute(
            action,
            self.state
        )

        await self.state_manager.update(
            self.state,
            action,
            tool_result
        )
```

---

## 6.2 NextActionPolicy

### 职责

决定：

```text
下一步执行什么 action
```

替代：

```python
build_next_step_plan()
```

### 输入

```python
Observation
```

包含：

```python
{
    "coverage_gap": ...,
    "difficulty_distribution": ...,
    "mode_distribution": ...,
    "evidence_stats": ...,
    "recent_actions": ...,
    "generation_round": ...
}
```

### 输出

```python
AgentAction
```

---

## 6.3 两种 Policy

### 1. RuleBasedNextActionPolicy

兼容当前逻辑。

用于：

- baseline
- debug
- deterministic generation

### 2. LLMNextActionPolicy

Agent 化版本。

#### Prompt 示例

```text
你是题目生成策略控制器。

你的任务不是生成题目，
而是决定下一步应该执行什么动作。

当前 topic:
{topic}

当前 coverage:
{coverage}

当前 gap:
{gap}

当前 evidence:
{evidence_stats}

请选择下一步 action。
只能从以下动作中选择：
- retrieve_documents
- expand_retrieval
- sample_evidence
- generate_questions
- increase_multi_chunk_ratio
- harden_generation
- finish_topic
```

#### 输出 JSON

```json
{
  "action": "expand_retrieval",
  "reason": "hard QA coverage insufficient",
  "queries": [
    "distributed consensus failure",
    "raft leader election edge cases"
  ]
}
```

---

# 7. Action Schema

```python
@dataclass
class AgentAction:

    action: Literal[
        "retrieve_documents",
        "expand_retrieval",
        "sample_evidence",
        "generate_questions",
        "increase_multi_chunk_ratio",
        "harden_generation",
        "finish_topic",
    ]

    topic: str

    target_mode: str | None = None

    target_difficulty: str | None = None

    batch_size: int | None = None

    queries: list[str] = field(default_factory=list)

    reason: str = ""
```

---

# 8. ToolRouter

## 职责

将：

```python
AgentAction
```

映射到：

```python
Tool.execute()
```

### 接口

```python
class ToolRouter:

    async def execute(
        self,
        action: AgentAction,
        state: QuestionAgentState
    ) -> ToolResult:
        ...
```

### 注册机制

```python
tools = {
    "retrieve_documents": RetrievalTool(...),
    "expand_retrieval": RetrievalTool(...),
    "sample_evidence": SamplingTool(...),
    "generate_questions": GenerationTool(...),
}
```

---

# 9. Tool 设计

## 9.1 RetrievalTool

### 封装当前逻辑

```text
search_wikipedia
fetch_wikipedia_page
_expand_retrieval
```

### 输入

```python
{
    "topic": "...",
    "queries": [...]
}
```

### 输出

```python
RetrievedDocuments
```

---

## 9.2 EvidenceTool

### 封装

```text
chunk_document
summary_generation
MultiChunkBuilder
build_evidence_pool
```

### 输出

```python
EvidencePool
```

---

## 9.3 SamplingTool

### 封装

```text
BroadExplorationSampling
GapDrivenSampling
```

### 职责

根据：

- gap
- difficulty
- mode
- evidence diversity

采样 generation batch。

---

## 9.4 GenerationTool

### 职责

真正调用：

```text
LLM generation
```

### 输入

```python
GenerationBatch
```

### 输出

```python
CandidateQuestions
```

---

## 9.5 FormatFilterTool

### 注意

这里只做：

```text
轻量过滤
```

不做：

```text
验证
```

### 检查项

1. JSON 可解析
2. 字段完整
3. 引用 chunk_id 存在
4. 长度合法
5. 基础重复检测
6. mode/difficulty 标签合法

### 输出

```python
FilteredCandidateQuestions
```

---

## 9.6 CoverageTool

### 职责

维护：

```text
topic coverage
difficulty coverage
mode coverage
```

### 输出

```python
CoverageStats
```

---

## 9.7 ArtifactTool

### 职责

保存：

- candidate questions
- traces
- evidence usage
- generation logs
- coverage report

---

# 10. State 设计

## 10.1 QuestionAgentState

```python
@dataclass
class QuestionAgentState:

    run_id: str

    generation_plan: GenerationPlan

    active_topic: str | None

    topic_states: dict[str, TopicState]

    evidence_pools: dict[str, EvidencePool]

    candidate_questions: list[Question]

    format_rejected_questions: list[RejectedQuestion]

    coverage_stats: dict

    generation_round: int

    recent_actions: list[AgentAction]
```

---

## 10.2 Observation

Planner 不直接读完整 state。

只读：

```python
Observation
```

### Observation 内容

```python
{
    "topic": ...,
    "coverage_gap": ...,
    "difficulty_distribution": ...,
    "mode_distribution": ...,
    "evidence_stats": ...,
    "generation_round": ...,
    "recent_failures": ...
}
```

---

# 11. 执行流程

## 11.1 Topic 生命周期

```text
prepare evidence
→ initialize topic state
→ loop:
      observe
      decide next action
      execute tool
      lightweight filter
      update coverage/state
→ topic complete
```

---

## 11.2 Candidate Question 生命周期

```text
sample evidence
→ generate candidate question
→ lightweight format filter
→ update coverage
→ save artifact
→ output to verification agent
```

---

# 12. 终止条件

## Topic 终止

满足：

```text
coverage 达标
AND
difficulty distribution 达标
AND
mode distribution 达标
OR
达到 max rounds
```

## 全局终止

所有 topic 完成。

---

# 13. 与当前代码映射

| 当前实现 | 新架构 |
|---|---|
| build_next_step_plan | NextActionPolicy |
| _execute_next_step_plan | ToolRouter |
| identify_main_gap | ObservationBuilder |
| _prepare_evidence | RetrievalTool + EvidenceTool |
| _generate_questions | GenerationTool |
| LightweightFilter | FormatFilterTool |
| update_topic_state | StateManager |
| _global_backfill | CoverageTool |

---

# 14. 分阶段重构计划

## Phase 1（推荐先做）

### 目标

引入：

- AgentAction
- ToolRouter
- StateManager

### 保持不变

- retrieval
- prompts
- generation
- filtering

### 修改点

替换：

```python
build_next_step_plan()
```

为：

```python
next_action_policy.decide()
```

---

## Phase 2

### 引入

LLMNextActionPolicy

### 替换

规则式：

```python
if hard_gap:
```

为：

```python
LLM policy decision
```

---

## Phase 3

### 引入

Coverage-aware adaptive generation。

包括：

- retrieval expansion
- multi-chunk adjustment
- hardening strategy

全部通过：

```text
policy + tool router
```

控制。

---

# 15. Claude Code 执行建议

## 第一阶段不要：

- 改 prompts
- 改 retrieval
- 改 generation
- 改 filtering

## 第一阶段只做：

```text
控制流重构
```

即：

```text
Workflow
→ Tool-driven architecture
```

## Claude Code 实施顺序（严格）

### Step 1

新增：

```text
schemas/agent_action.py
```

### Step 2

新增：

```text
router/tool_router.py
```

### Step 3

新增：

```text
policies/next_action_policy.py
```

### Step 4

实现：

```text
RuleBasedNextActionPolicy
```

逻辑复制：

```python
build_next_step_plan()
```

### Step 5

抽离 tools：

```text
retrieval_tool.py
evidence_tool.py
generation_tool.py
sampling_tool.py
```

### Step 6

重构：

```python
_process_topic()
```

变为：

```text
observe
→ decide
→ execute tool
→ update state
```

---

# 16. 最终目标

最终：

```text
QuestionGeneratorAgent
```

将从：

```text
Stateful Workflow
```

升级为：

```text
Controlled Tool-driven Agentic Component
```

但仍保持：

```text
高可控性
高稳定性
高可验证性
```

避免：

```text
开放 Agent 失控问题
```
