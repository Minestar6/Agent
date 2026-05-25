# 从Pipeline到真正Agent的重构方案

## 核心变化对比

### 1. 决策机制

| 维度 | 原有Pipeline | 重构后Agent |
|------|-------------|------------|
| 决策方式 | 硬编码规则（if-else） | LLM推理生成JSON决策 |
| 优先级 | 固定：hard > medium > easy | 动态评估：基于状态、历史、效率 |
| 适应性 | 无 | 根据历史反思调整策略 |
| 可解释性 | 规则明确但机械 | 有推理过程（reasoning字段） |

**代码对比：**

```python
# 原有（planning.py）
gaps.sort(key=lambda x: (
    0 if "hard" in x[0] else (1 if "medium" in x[0] else 2),
    -x[1],
))

# 重构后（planner.py）
# LLM分析当前状态，输出：
{
  "reasoning": "当前hard缺口剩余5题，但单证据有效率仅0.3，应先扩展检索",
  "action": "expand_retrieval",
  "parameters": {"queries": ["topic", "related_concept"]},
  "priority": 0.85,
  "confidence": 0.72
}
```

---

### 2. 工具使用

| 维度 | 原有Pipeline | 重构后Agent |
|------|-------------|------------|
| 工具选择 | 固定序列 | Agent自主选择 |
| 工具组合 | 预定义 | 动态组合 |
| 参数调整 | 固定值 | 根据状态调整 |

**原有调用链：**
```python
async def _process_topic(...):
    await self._prepare_evidence()      # 固定步骤1
    while ...:
        await self._run_generation_round()  # 固定步骤2
```

**重构后Agent循环：**
```python
async def _run_agent_loop(...):
    while not done:
        plan = await self._plan_step()      # Agent决定下一步
        result = await self._act_step(plan)  # 执行Agent选择的工具
        await self._observe_step(result)     # 更新状态
        reflection = await self._reflect_step()  # 反思改进
```

---

### 3. 学习与适应

| 维度 | 原有Pipeline | 重构后Agent |
|------|-------------|------------|
| 参数调整 | alpha=0.3 固定 | 根据反思动态调整 |
| 策略更新 | 无 | `learned_strategies` 记录有效策略 |
| 失败处理 | 重试或放弃 | 分析原因并调整策略 |

**新增反思机制：**
```python
# 每轮执行后
reflection = {
    "effectiveness": "poor",
    "analysis": "hard题目有效率仅0.2，原因是单证据信息不足",
    "suggestions": [
        "增加多证据组合比例",
        "扩展检索获取更相关文档"
    ],
    "adjustments": {
        "prefer_multi_chunk": True,
        "retrieval_expansion": True
    }
}

# 自动应用到下一轮
memory.learned_strategies.update(reflection["adjustments"])
```

---

### 4. 记忆系统

**原有：** 简单字典
```python
self.topic_states: dict[str, TopicState] = {}
self.evidence_pools: dict[str, EvidencePool] = {}
```

**重构后：** 结构化记忆
```python
@dataclass
class AgentMemory:
    actions: list[dict]         # 行动历史
    reflections: list[dict]      # 反思历史
    performance_metrics: dict    # 性能指标时序
    learned_strategies: dict     # 学习到的策略
```

---

## 重构步骤总结

### 第一阶段：工具标准化（1-2天）
- [x] 创建 `tools.py`，包装现有功能为标准工具接口
- [ ] 实现 `tool_search_documents`
- [ ] 实现 `tool_generate_questions_batch`
- [ ] 实现 `tool_expand_retrieval`
- [ ] 实现 `tool_analyze_generation_gap`

### 第二阶段：LLM规划器（2-3天）
- [x] 创建 `planner.py`
- [ ] 实现 `LLMPlanner.plan()` 的prompt优化
- [ ] 实现 `LLMReflector.reflect()` 的反思逻辑
- [ ] 测试规划器的决策质量

### 第三阶段：Agent核心循环（3-5天）
- [x] 创建 `true_agent.py`
- [ ] 实现 `_plan_step`
- [ ] 实现 `_act_step` 与工具的集成
- [ ] 实现 `_observe_step` 状态更新
- [ ] 实现 `_reflect_step` 与策略应用

### 第四阶段：记忆与学习（2-3天）
- [ ] 实现短期记忆（当前会话）
- [ ] 实现长期记忆（跨会话）
- [ ] 实现策略持久化
- [ ] 实现性能指标追踪

### 第五阶段：优化与测试（持续）
- [ ] A/B测试：Pipeline vs Agent
- [ ] 规划器prompt优化
- [ ] 反思阈值调优
- [ ] 成本优化（减少LLM调用）

---

## 成本考量

### LLM调用增加
- **原有**：每轮1次（生成题目）
- **重构后**：每轮3次（规划 + 生成 + 反思）
- **优化策略**：
  1. 反思可以每N轮执行一次
  2. 规划器使用更小/更快的模型
  3. 缓存相似状态的决策

### 预期收益
- **自适应能力**：根据实际表现调整策略
- **鲁棒性**：处理边缘情况（如检索失败、质量低）
- **可解释性**：每个决策都有推理过程
- **可扩展性**：新增工具无需修改核心逻辑

---

## 文件结构

```
benchforge/agents/
├── __init__.py
├── question_generator.py      # 原有Pipeline（保留对比）
├── true_agent.py              # 新的Agent实现
├── planner.py                 # LLM规划器和反思器
├── tools.py                   # 工具定义和注册
└── memory.py                  # 记忆系统（待实现）
```

---

## 下一步建议

1. **先实现工具层**：确保现有功能无损迁移
2. **测试规划器**：用历史状态测试LLM的决策质量
3. **渐进式迁移**：先在一个主题上测试Agent循环
4. **性能监控**：对比Pipeline和Agent的效率与质量