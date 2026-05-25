# 中量级 Controlled Agent 实施方案

## 一、最终架构

```
QuestionGeneratorAgent（中量级 Controlled Agent）
  ├── ObservationBuilder           # 构建观察
  ├── NextDecisionPolicy            # 决策引擎
  │     ├── RuleBasedDecisionPolicy    # 规则策略（baseline + fallback）
  │     └── LLMDecisionPolicy           # LLM策略（深度决策，单个Prompt）
  ├── ToolRouter                   # 工具路由
  ├── RetrievalTool                # 纯执行
  ├── EvidenceTool                 # 纯执行
  ├── SamplingTool                 # 纯执行（策略参数由Agent决定）
  ├── GenerationTool               # 纯执行
  ├── FormatFilterTool             # 纯执行
  ├── CoverageManager              # 覆盖率管理
  ├── ArtifactManager              # 工件管理
  └── LightweightReflection        # 可选，轻量反思
```

---

## 二、核心改动

### 改动1: AgentAction → AgentDecision

**之前**：
```python
@dataclass
class AgentAction:
    action: Literal["retrieve", "expand", "sample", "generate", "finish"]
    topic: str
    target_mode: str | None = None
    target_difficulty: str | None = None
    batch_size: int | None = None
    queries: list[str] = field(default_factory=list)
    reason: str = ""
```

**之后**：
```python
@dataclass
class AgentDecision:
    """Agent的深度决策。"""

    # 动作信息
    next_action: str
    action_parameters: dict[str, Any]

    # 推理信息（新增）
    state_assessment: str      # 状态评估
    primary_gap: str           # 主缺口
    gap_reason: str            # 缺口原因
    selected_strategy: str     # 选择的策略
    strategy_rationale: str    # 策略理由

    # 元信息（新增）
    confidence: float          # 置信度 0-1
```

---

### 改动2: Prompt深度化

**之前**：
```python
"""
你是策略控制器，选择下一步 action。
只能从以下动作中选择：retrieve/expand/sample/generate/finish
"""
```

**之后**：
```python
"""
你是问题生成决策引擎。

当前状态：
主题: {topic}
覆盖率: {coverage}
剩余缺口: {gaps}
当前轮数: {round}
证据统计: {evidence_stats}
历史行动: {history}

你的任务：
1. 分析当前状态
2. 识别最紧急的缺口
3. 选择最优策略
4. 优化执行参数

输出格式：
{
  "state_assessment": "状态评估",
  "primary_gap": "qa:hard",
  "gap_reason": "缺口原因",
  "selected_strategy": "gap_driven",
  "strategy_rationale": "策略理由",
  "next_action": "sample_evidence",
  "action_parameters": {
    "strategy": "gap_driven",
    "target_gap": "qa:hard",
    "num_evidence": 5
  },
  "confidence": 0.85
}
"""
```

---

### 改动3: 执行流程

```python
async def _process_topic(self, topic: str):
    """处理单个主题。"""

    while not self._should_stop(topic):

        # 1. 构建观察
        observation = self.observation_builder.build(
            self.state,
            topic
        )

        # 2. 决策（Policy）
        try:
            decision = await self.next_decision_policy.decide(observation)
        except Exception as e:
            logger.warning(f"LLM policy failed: {e}, falling back to rule-based")
            decision = await self.rule_based_policy.decide(observation)

        # 3. 执行（ToolRouter）
        tool_result = await self.tool_router.execute(
            decision.next_action,
            decision.action_parameters,
            self.state
        )

        # 4. 轻量反思（可选）
        if self.enable_lightweight_reflection:
            reflection = await self._lightweight_reflection(topic, decision, tool_result)
            # 根据反思调整策略（如果需要）
            if reflection.get("strategy_adjustment_needed"):
                await self._adjust_strategy(topic, reflection)

        # 5. 更新状态
        await self.state_manager.update(
            self.state,
            decision,
            tool_result
        )
```

---

## 三、实施步骤

### Phase 1: 架构引入（保持逻辑）

#### Step 1: 定义Schema

创建 `benchforge/schemas/agent_decision.py`：

```python
from dataclasses import dataclass, field
from typing import Any, Literal
import json


@dataclass
class AgentDecision:
    """Agent的深度决策。"""

    # 动作信息
    next_action: str
    action_parameters: dict[str, Any] = field(default_factory=dict)

    # 推理信息
    state_assessment: str = ""
    primary_gap: str = ""
    gap_reason: str = ""
    selected_strategy: str = ""
    strategy_rationale: str = ""

    # 元信息
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "next_action": self.next_action,
            "action_parameters": self.action_parameters,
            "state_assessment": self.state_assessment,
            "primary_gap": self.primary_gap,
            "gap_reason": self.gap_reason,
            "selected_strategy": self.selected_strategy,
            "strategy_rationale": self.strategy_rationale,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentDecision":
        """从字典创建。"""
        return cls(
            next_action=data["next_action"],
            action_parameters=data.get("action_parameters", {}),
            state_assessment=data.get("state_assessment", ""),
            primary_gap=data.get("primary_gap", ""),
            gap_reason=data.get("gap_reason", ""),
            selected_strategy=data.get("selected_strategy", ""),
            strategy_rationale=data.get("strategy_rationale", ""),
            confidence=data.get("confidence", 0.0),
        )
```

创建 `benchforge/schemas/observation.py`：

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Observation:
    """Agent观察到的状态。"""

    topic: str
    coverage: dict[str, Any]
    gaps: dict[str, int]
    round: int
    max_rounds: int
    evidence_stats: dict[str, Any]
    history: list[dict[str, Any]] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于Prompt）。"""
        return {
            "topic": self.topic,
            "coverage": self.coverage,
            "gaps": self.gaps,
            "round": self.round,
            "max_rounds": self.max_rounds,
            "evidence_stats": self.evidence_stats,
            "history": self.history[-3:],  # 最近3次
            "constraints": self.constraints,
        }
```

---

#### Step 2: 实现ObservationBuilder

创建 `benchforge/agents/observation_builder.py`：

```python
from benchforge.schemas import Observation, TopicState, EvidencePool
from benchforge.utils.planning import identify_main_gap


class ObservationBuilder:
    """构建Agent观察。"""

    def build(
        self,
        state: dict,
        topic: str
    ) -> Observation:
        """构建观察对象。"""
        topic_state = state["topic_states"].get(topic)
        evidence_pool = state.get("evidence_pools", {}).get(topic)

        if not topic_state:
            raise ValueError(f"Topic state not found: {topic}")

        # 计算覆盖率
        coverage = self._calculate_coverage(topic_state)

        # 识别缺口
        gaps = topic_state.remaining_counts

        # 证据统计
        evidence_stats = self._get_evidence_stats(evidence_pool)

        # 历史行动
        history = state.get("history", [])

        # 约束
        constraints = {
            "max_rounds_per_topic": state.get("max_rounds_per_topic", 10),
            "max_total_rounds": state.get("max_total_rounds", 50),
        }

        return Observation(
            topic=topic,
            coverage=coverage,
            gaps=gaps,
            round=topic_state.current_round,
            max_rounds=constraints["max_rounds_per_topic"],
            evidence_stats=evidence_stats,
            history=history,
            constraints=constraints,
        )

    def _calculate_coverage(self, state: TopicState) -> dict[str, Any]:
        """计算覆盖率。"""
        target = state.target_counts
        completed = state.completed_counts

        coverage = {}
        for key, target_count in target.items():
            completed_count = completed.get(key, 0)
            coverage[key] = {
                "target": target_count,
                "completed": completed_count,
                "remaining": max(0, target_count - completed_count),
                "progress": completed_count / target_count if target_count > 0 else 1.0,
            }

        return coverage

    def _get_evidence_stats(self, pool: EvidencePool | None) -> dict[str, Any]:
        """获取证据统计。"""
        if not pool:
            return {
                "single_chunks_count": 0,
                "multi_chunks_count": 0,
                "single_avg_valid": 0.0,
                "multi_avg_valid": 0.0,
            }

        return {
            "single_chunks_count": len(pool.single_chunks),
            "multi_chunks_count": len(pool.multi_chunks),
            "single_avg_valid": pool.stats.single_chunk_stats.avg_valid_count,
            "multi_avg_valid": pool.stats.multi_chunk_stats.avg_valid_count,
        }
```

---

#### Step 3: 实现RuleBasedDecisionPolicy（复制原有逻辑）

创建 `benchforge/policies/rule_based_policy.py`：

```python
from benchforge.schemas import Observation, AgentDecision
from benchforge.utils.planning import identify_main_gap, build_allowed_actions, build_next_step_plan


class RuleBasedDecisionPolicy:
    """基于规则的决策策略（复制原有逻辑）。"""

    def decide(self, observation: Observation) -> AgentDecision:
        """基于规则做决策。"""

        # 1. 识别主缺口（复制原有逻辑）
        state = {
            "remaining_counts": observation.gaps,
            "current_round": observation.round,
            "max_rounds_per_topic": observation.max_rounds,
        }

        main_gap = identify_main_gap(state)

        if not main_gap:
            return self._finish_decision(observation)

        gap_key, remaining = main_gap

        # 2. 构建下一步计划（复制原有逻辑）
        allowed_actions = build_allowed_actions(state, observation.max_rounds)

        next_plan = build_next_step_plan(
            observation.topic,
            gap_key,
            [a.value for a in allowed_actions],
            prefer_multi=False,  # 简化版
        )

        # 3. 转换为AgentDecision
        return self._convert_to_decision(
            observation,
            next_plan,
            gap_key
        )

    def _finish_decision(self, observation: Observation) -> AgentDecision:
        """完成决策。"""
        return AgentDecision(
            next_action="finish_topic",
            action_parameters={"topic": observation.topic},
            state_assessment=f"所有目标已完成或达到最大轮数",
            primary_gap="",
            gap_reason="",
            selected_strategy="finish",
            strategy_rationale="任务完成",
            confidence=1.0,
        )

    def _convert_to_decision(
        self,
        observation: Observation,
        next_plan: dict,
        gap_key: str
    ) -> AgentDecision:
        """转换为AgentDecision。"""

        state_assessment = self._assess_state(observation, gap_key)
        gap_reason = self._explain_gap(observation, gap_key)
        selected_strategy = next_plan.get("action", "continue_generation")
        strategy_rationale = next_plan.get("reason", "继续生成")

        # 构建action_parameters
        action_parameters = {
            "topic": observation.topic,
        }

        if selected_strategy == "continue_generation":
            action_parameters.update({
                "target_mode": gap_key.split(":")[0],
                "target_difficulty": gap_key.split(":")[1],
                "requested_questions": observation.gaps.get(gap_key, 0) + 2,
                "strategy": "gap_driven" if observation.round > 0 else "broad_exploration",
            })
        elif selected_strategy == "expand_retrieval":
            action_parameters.update({
                "queries": next_plan.get("retrieval_expansion_queries", [observation.topic]),
            })

        return AgentDecision(
            next_action=self._map_action(selected_strategy),
            action_parameters=action_parameters,
            state_assessment=state_assessment,
            primary_gap=gap_key,
            gap_reason=gap_reason,
            selected_strategy=selected_strategy,
            strategy_rationale=strategy_rationale,
            confidence=0.9,  # 规则策略置信度高
        )

    def _assess_state(self, observation: Observation, gap_key: str) -> str:
        """评估状态。"""
        coverage = observation.coverage.get(gap_key, {})
        progress = coverage.get("progress", 0)

        if progress < 0.3:
            return f"早期阶段，{gap_key} 进度较慢"
        elif progress < 0.7:
            return f"中期阶段，{gap_key} 持续生成中"
        else:
            return f"后期阶段，{gap_key} 接近完成"

    def _explain_gap(self, observation: Observation, gap_key: str) -> str:
        """解释缺口。"""
        remaining = observation.gaps.get(gap_key, 0)
        return f"目标数量为{observation.coverage.get(gap_key, {}).get('target', 0)}，还剩{remaining}题"

    def _map_action(self, action: str) -> str:
        """映射action名称。"""
        action_map = {
            "continue_generation": "generate_questions",
            "expand_retrieval": "expand_retrieval",
            "increase_multi_chunk_ratio": "adjust_sampling_strategy",
            "enable_hardening": "adjust_generation_prompt",
            "defer_topic": "finish_topic",
        }
        return action_map.get(action, action)
```

---

#### Step 4: 实现ToolRouter

创建 `benchforge/router/tool_router.py`：

```python
from typing import Any
from benchforge.schemas import AgentDecision
from benchforge.tools import (
    RetrievalTool,
    EvidenceTool,
    SamplingTool,
    GenerationTool,
    FormatFilterTool,
    CoverageTool,
    ArtifactTool,
)


class ToolRouter:
    """工具路由器。"""

    def __init__(self):
        """初始化工具路由器。"""
        self.tools = {
            "retrieve_documents": RetrievalTool(),
            "expand_retrieval": RetrievalTool(),
            "build_evidence_pool": EvidenceTool(),
            "sample_evidence": SamplingTool(),
            "generate_questions": GenerationTool(),
            "filter_questions": FormatFilterTool(),
            "update_coverage": CoverageTool(),
            "save_artifact": ArtifactTool(),
        }

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        state: dict
    ) -> dict[str, Any]:
        """执行工具。"""

        tool = self.tools.get(action)

        if not tool:
            raise ValueError(f"Unknown action: {action}")

        # 调用工具
        result = await tool.execute(parameters, state)

        return result
```

---

#### Step 5: 抽离工具

创建 `benchforge/tools/retrieval_tool.py`：

```python
from typing import Any
from benchforge.utils import search_wikipedia, fetch_wikipedia_page


class RetrievalTool:
    """检索工具。"""

    async def execute(self, parameters: dict[str, Any], state: dict) -> dict[str, Any]:
        """执行检索。"""
        topic = parameters["topic"]
        max_pages = parameters.get("max_pages", 5)

        # 搜索文档
        results = search_wikipedia(
            query=topic,
            language=state.get("language", "en"),
            max_pages=max_pages
        )

        return {
            "results": results,
            "count": len(results),
        }
```

创建 `benchforge/tools/sampling_tool.py`：

```python
from typing import Any
from benchforge.schemas import EvidencePool, GenerationBatch
from benchforge.utils.sampling import (
    BroadExplorationSampling,
    GapDrivenSampling,
)


class SamplingTool:
    """采样工具。"""

    async def execute(self, parameters: dict[str, Any], state: dict) -> dict[str, Any]:
        """执行采样。"""
        topic = parameters["topic"]
        strategy = parameters["strategy"]
        target_gap = parameters["target_gap"]
        num_evidence = parameters["num_evidence"]

        pool = state.get("evidence_pools", {}).get(topic)
        if not pool:
            raise ValueError(f"Evidence pool not found: {topic}")

        # 选择采样策略
        if strategy == "broad_exploration":
            sampler = BroadExplorationSampling()
        elif strategy == "gap_driven":
            sampler = GapDrivenSampling()
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        # 采样
        target_mode, target_difficulty = target_gap.split(":")
        batch = sampler.sample(
            pool=pool,
            target_mode=target_mode,
            target_difficulty=target_difficulty,
            num_evidence=num_evidence,
            prefer_multi_chunk=parameters.get("prefer_multi_chunk", False)
        )

        return {
            "batch": batch,
            "single_chunk_count": len(batch.single_chunk_ids),
            "multi_chunk_count": len(batch.multi_chunk_ids),
        }
```

---

#### Step 6: 重构QuestionGeneratorAgent

修改 `benchforge/agents/question_generator.py`：

```python
from benchforge.schemas import GenerationPlan
from benchforge.agents.observation_builder import ObservationBuilder
from benchforge.policies.rule_based_policy import RuleBasedDecisionPolicy
from benchforge.router.tool_router import ToolRouter


class QuestionGeneratorAgent:
    """问题生成智能体（中量级 Controlled Agent）。"""

    def __init__(
        self,
        model_client,
        config=None,
        enable_lightweight_reflection: bool = False,
    ):
        """初始化Agent。"""
        self.model_client = model_client
        self.config = config

        # 初始化组件
        self.observation_builder = ObservationBuilder()
        self.decision_policy = RuleBasedDecisionPolicy()  # 初始用规则策略
        self.tool_router = ToolRouter()

        # 轻量反思开关
        self.enable_lightweight_reflection = enable_lightweight_reflection

        # 初始化状态（复用原有逻辑）
        self.topic_states: dict[str, TopicState] = {}
        self.evidence_pools: dict[str, EvidencePool] = {}
        self.all_questions: list[dict[str, Any]] = []

    async def execute(self, plan: GenerationPlan) -> dict:
        """执行生成任务。"""
        # 初始化状态（复用原有逻辑）
        self.topic_states = self._compile_generation_plan(plan)

        # 为每个主题处理
        for topic in plan.topics:
            await self._process_topic(topic, plan)

        # 生成报告
        return self._build_report(plan)

    async def _process_topic(self, topic: str, plan: GenerationPlan):
        """处理单个主题（重构后的循环）。"""

        # 准备初始证据（复用原有逻辑）
        await self._prepare_evidence(topic, plan)

        # 主循环
        while not self._should_stop(topic):

            # 1. 构建观察
            observation = self.observation_builder.build(
                {
                    "topic_states": self.topic_states,
                    "evidence_pools": self.evidence_pools,
                    "history": [],  # TODO: 实现历史记录
                    "max_rounds_per_topic": plan.max_rounds_per_topic,
                    "language": plan.language,
                },
                topic
            )

            # 2. 决策
            try:
                decision = await self.decision_policy.decide(observation)
            except Exception as e:
                logger.warning(f"Policy failed: {e}")
                continue

            # 3. 执行
            if decision.next_action == "finish_topic":
                break

            tool_result = await self.tool_router.execute(
                decision.next_action,
                decision.action_parameters,
                {
                    "topic_states": self.topic_states,
                    "evidence_pools": self.evidence_pools,
                    "all_questions": self.all_questions,
                    "language": plan.language,
                    "model_client": self.model_client,
                }
            )

            # 4. 轻量反思（可选）
            if self.enable_lightweight_reflection:
                await self._lightweight_reflection(topic, decision, tool_result)

            # 5. 更新状态
            await self._update_state(topic, decision, tool_result)

    # 以下方法复用原有逻辑
    def _should_stop(self, topic: str) -> bool:
        """检查是否应该停止。"""
        state = self.topic_states.get(topic)
        if not state:
            return False

        # 检查是否完成
        from benchforge.utils.planning import check_topic_completion
        return check_topic_completion(state)

    async def _prepare_evidence(self, topic: str, plan: GenerationPlan):
        """准备证据（复用原有逻辑）。"""
        # 复制原有的 _prepare_evidence 实现
        pass

    async def _update_state(self, topic: str, decision: AgentDecision, result: dict):
        """更新状态（复用原有逻辑）。"""
        # 复制原有的状态更新逻辑
        pass

    async def _lightweight_reflection(self, topic: str, decision: AgentDecision, result: dict):
        """轻量反思（生成过程优化，不是题目质量验证）。"""
        # 简化的轻量反思
        logger.info(f"Reflection: action={decision.next_action}, result={result.get('count', 'N/A')}")

    def _compile_generation_plan(self, plan: GenerationPlan) -> dict:
        """编译生成计划（复用原有逻辑）。"""
        from benchforge.utils.planning import compile_generation_plan
        return compile_generation_plan(plan)

    def _build_report(self, plan: GenerationPlan) -> dict:
        """构建报告（复用原有逻辑）。"""
        # 复制原有的报告生成逻辑
        return {}
```

---

### Phase 2: LLM决策策略

#### Step 7: 实现LLMDecisionPolicy

创建 `benchforge/policies/llm_policy.py`：

```python
import json
import re
from typing import Any

from benchforge.schemas import Observation, AgentDecision
from benchforge.models.base import BaseModelClient


class LLMDecisionPolicy:
    """基于LLM的决策策略。"""

    SYSTEM_PROMPT = """你是问题生成决策引擎。

你的任务是基于当前状态，做出最优的生成决策。

决策时请考虑：
1. 当前覆盖率
2. 剩余缺口的紧急程度
3. 证据池的充足度
4. 历史生成效率
5. 剩余轮数

输出必须为有效的JSON格式。
"""

    def __init__(self, model_client: BaseModelClient):
        """初始化LLM策略。"""
        self.model_client = model_client

    async def decide(self, observation: Observation) -> AgentDecision:
        """基于LLM做决策。"""

        # 构建Prompt
        user_prompt = self._build_prompt(observation)

        # 调用LLM
        response = await self.model_client.complete(
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,  # 需要确定性
            max_tokens=1000,
        )

        # 解析响应
        decision_data = self._parse_response(response["text"])

        return AgentDecision.from_dict(decision_data)

    def _build_prompt(self, observation: Observation) -> str:
        """构建Prompt。"""
        obs_dict = observation.to_dict()

        prompt = f"""## 当前状态

主题: {obs_dict['topic']}
当前轮数: {obs_dict['round']}
最大轮数: {obs_dict['max_rounds']}

## 覆盖率
{json.dumps(obs_dict['coverage'], indent=2, ensure_ascii=False)}

## 剩余缺口
{json.dumps(obs_dict['gaps'], indent=2, ensure_ascii=False)}

## 证据统计
{json.dumps(obs_dict['evidence_stats'], indent=2, ensure_ascii=False)}

## 最近行动
{json.dumps(obs_dict['history'], indent=2, ensure_ascii=False)}

## 你的任务

1. 分析当前状态（state_assessment）
2. 识别最紧急的缺口（primary_gap）
3. 解释缺口原因（gap_reason）
4. 选择最优策略（selected_strategy）
5. 说明策略理由（strategy_rationale）
6. 决定下一步动作（next_action）
7. 优化执行参数（action_parameters）

## 可选动作

- sample_evidence: 采样证据
- generate_questions: 生成题目
- expand_retrieval: 扩展检索
- adjust_sampling_strategy: 调整采样策略
- adjust_generation_prompt: 调整生成prompt
- finish_topic: 完成主题

## 输出格式

请以JSON格式输出：

{{
  "state_assessment": "当前状态的评估",
  "primary_gap": "qa:hard",
  "gap_reason": "缺口存在的原因",
  "selected_strategy": "gap_driven",
  "strategy_rationale": "为什么选择这个策略",
  "next_action": "sample_evidence",
  "action_parameters": {{
    "strategy": "gap_driven",
    "target_gap": "qa:hard",
    "num_evidence": 5
  }},
  "confidence": 0.85
}}
"""

        return prompt

    def _parse_response(self, text: str) -> dict[str, Any]:
        """解析LLM响应。"""

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取JSON
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 解析失败，返回默认值
        logger.warning("Failed to parse LLM response, using default")
        return {
            "state_assessment": "解析失败",
            "primary_gap": "qa:medium",
            "gap_reason": "解析失败，使用默认",
            "selected_strategy": "continue",
            "strategy_rationale": "解析失败",
            "next_action": "generate_questions",
            "action_parameters": {},
            "confidence": 0.0,
        }
```

---

#### Step 8: 集成LLM策略

修改 `QuestionGeneratorAgent.__init__`：

```python
class QuestionGeneratorAgent:
    def __init__(
        self,
        model_client,
        config=None,
        enable_lightweight_reflection: bool = False,
        use_llm_policy: bool = False,  # 新增
    ):
        """初始化Agent。"""
        self.model_client = model_client
        self.config = config

        # 初始化组件
        self.observation_builder = ObservationBuilder()
        self.rule_based_policy = RuleBasedDecisionPolicy()

        # 根据配置选择策略
        if use_llm_policy:
            from benchforge.policies.llm_policy import LLMDecisionPolicy
            self.decision_policy = LLMDecisionPolicy(model_client)
        else:
            self.decision_policy = self.rule_based_policy

        # 保存规则策略作为fallback
        self.rule_based_policy = RuleBasedDecisionPolicy()

        self.tool_router = ToolRouter()
        self.enable_lightweight_reflection = enable_lightweight_reflection

        # 初始化状态
        self.topic_states: dict[str, TopicState] = {}
        self.evidence_pools: dict[str, EvidencePool] = {}
        self.all_questions: list[dict[str, Any]] = []
```

修改 `_process_topic` 添加fallback：

```python
async def _process_topic(self, topic: str, plan: GenerationPlan):
    while not self._should_stop(topic):
        observation = self.observation_builder.build(...)

        # 决策（带fallback）
        try:
            decision = await self.decision_policy.decide(observation)
        except Exception as e:
            logger.warning(f"LLM policy failed: {e}, falling back to rule-based")
            decision = await self.rule_based_policy.decide(observation)

        # 执行
        # ...
```

---

### Phase 3: 轻量反思（可选）

#### Step 9: 实现轻量反思

修改 `QuestionGeneratorAgent`：

```python
async def _lightweight_reflection(self, topic: str, decision: AgentDecision, result: dict):
    """轻量反思：评估生成过程，不是题目质量。"""

    # 只对生成动作进行反思
    if decision.next_action != "generate_questions":
        return

    # 提取结果信息
    requested = result.get("requested_count", 0)
    valid = result.get("valid_count", 0)
    valid_rate = valid / requested if requested > 0 else 0

    # 简单判断
    issues = []
    if valid < requested * 0.5:  # 完成度低于50%
        issues.append("生成数量严重不足")

    if valid_rate < 0.3:  # 有效率低于30%
        issues.append("格式过滤通过率过低")

    if issues:
        logger.warning(f"Reflection issues: {issues}")
        # TODO: 根据问题调整策略
        # 例如：如果有效率低，下次增加请求数
```

---

## 四、测试策略

### 测试1: 规则策略Baseline

```python
# 测试规则策略是否与原有逻辑一致
agent = QuestionGeneratorAgent(
    model_client=model_client,
    use_llm_policy=False  # 使用规则策略
)

result = await agent.execute(plan)

# 验证结果与原有Pipeline一致
```

### 测试2: LLM策略输出

```python
# 测试LLM策略的决策质量
agent = QuestionGeneratorAgent(
    model_client=model_client,
    use_llm_policy=True  # 使用LLM策略
)

result = await agent.execute(plan)

# 验证决策的合理性
# - state_assessment是否合理
# - primary_gap是否正确
# - selected_strategy是否恰当
# - confidence是否合理
```

### 测试3: Fallback机制

```python
# 测试LLM失败时的fallback
# 模拟LLM失败，验证是否正确fallback到规则策略
```

### 测试4: 轻量反思

```python
# 测试轻量反思是否触发策略调整
# 模拟低有效率情况，验证是否调整策略
```

---

## 五、文件结构

```
benchforge/
├── schemas/
│   ├── agent_decision.py          # 新增
│   └── observation.py             # 新增
├── agents/
│   ├── observation_builder.py     # 新增
│   └── question_generator.py      # 修改
├── policies/
│   ├── rule_based_policy.py       # 新增
│   └── llm_policy.py              # 新增
├── router/
│   └── tool_router.py             # 新增
└── tools/
    ├── retrieval_tool.py          # 新增
    ├── evidence_tool.py           # 新增（可选）
    ├── sampling_tool.py           # 新增
    ├── generation_tool.py         # 新增（可选）
    ├── format_filter_tool.py      # 新增（可选）
    ├── coverage_tool.py           # 新增（可选）
    └── artifact_tool.py           # 新增（可选）
```

---

## 六、实施检查清单

### Phase 1: 架构引入
- [ ] 定义 AgentDecision Schema
- [ ] 定义 Observation Schema
- [ ] 实现 ObservationBuilder
- [ ] 实现 RuleBasedDecisionPolicy
- [ ] 实现 ToolRouter
- [ ] 抽离 RetrievalTool
- [ ] 抽离 SamplingTool
- [ ] 重构 QuestionGeneratorAgent

### Phase 2: LLM决策策略
- [ ] 实现 LLMDecisionPolicy
- [ ] 设计并测试 Prompt
- [ ] 集成 LLM 策略
- [ ] 实现 fallback 机制
- [ ] 测试 LLM 策略输出

### Phase 3: 轻量反思（可选）
- [ ] 实现轻量反思逻辑
- [ ] 实现策略调整机制
- [ ] 测试反思效果

---

## 七、预期效果

| 指标 | 原Pipeline | Phase 1 | Phase 2 |
|------|-----------|---------|---------|
| 决策方式 | 规则 | 规则 | LLM + fallback |
| 可解释性 | 低 | 中 | 高 |
| 自适应性 | 无 | 无 | 有 |
| 成本 | 1x | 1x | 1.2x |
| 稳定性 | 高 | 高 | 中高（有fallback）|