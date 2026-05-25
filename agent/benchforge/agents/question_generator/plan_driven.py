"""Plan-Driven Question Generation Agent（主入口）。

Plan-Driven Agent 特征：
- 不自主设定目标，而是执行给定生成计划
- 通过反复识别缺口、检索证据、生成题目、验证结果和更新状态
- 直到计划完成

架构：
├── Planner                # 解析计划、维护 TopicState / remaining_counts
├── ObservationBuilder     # 构造当前观察摘要
├── Scheduler              # 规则驱动决策：选 gap 和 action
├── DecisionValidator      # 验证 action 是否合法
├── ActionExecutor         # 薄封装：执行 action
├── EvidenceManager        # 检索、分块、证据池、采样
├── Generator              # prompt 拼接、LLM 调用
├── Validator              # 解析、过滤、去重、状态更新
├── LoopGuard              # 防止无进展循环
└── TraceWriter            # 实时写 decision_trace.jsonl
"""

from pathlib import Path
from typing import Any
from dataclasses import dataclass, field

from loguru import logger

from benchforge.schemas import (
    GenerationPlan,
    GenerationReport,
    TopicStatus,
    ControlDecision,
)
from benchforge.agents.question_generator.modules import (
    Planner,
    ObservationBuilder,
    Scheduler,
    DecisionValidator,
    ActionExecutor,
    EvidenceManager,
    Generator,
    Validator,
    LoopGuard,
)
from benchforge.agents.question_generator.modules.trace_writer import TraceWriter
from benchforge.utils.artifact_store import ArtifactStore


@dataclass
class AgentRuntimeState:
    """Agent 运行时状态。"""
    step_id: int = 0
    round_num: int = 0
    accepted_count: int = 0


class PlanDrivenQuestionGenerationAgent:
    """计划驱动题目生成智能体。

    核心特征：
    - 规则驱动决策（硬编码规则链）
    - Plan-Driven 状态机
    - 完整的安全机制（LoopGuard, DecisionValidator）
    - 实时决策追踪
    """

    def __init__(
        self,
        config: Any,
        model_client: Any,
    ):
        """初始化 Agent。

        Args:
            config: 配置对象
            model_client: 模型客户端
        """
        self.config = config
        self.model_client = model_client

        # 输出路径
        self.output_path = config.get_resolved_output_path()
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.artifact_store = ArtifactStore(str(self.output_path))

        # 初始化模块
        self.planner = Planner()
        self.observation_builder = ObservationBuilder()
        self.scheduler = Scheduler()
        self.decision_validator = DecisionValidator()
        self.evidence_manager = EvidenceManager(config)
        self.generator = Generator()
        self.validator = Validator()
        self.action_executor = ActionExecutor(
            evidence_manager=self.evidence_manager,
            generator=self.generator,
            validator=self.validator,
        )
        self.loop_guard = LoopGuard(stuck_threshold=3)
        self.trace_writer = TraceWriter(self.output_path)

        # 运行时状态
        self.runtime_state = AgentRuntimeState()
        self.all_questions: list[dict[str, Any]] = []
        self.evidence_pools: dict[str, Any] = {}
        self.plan: GenerationPlan | None = None

    async def execute(self, plan: GenerationPlan) -> GenerationReport:
        """执行生成任务。

        主循环：
        while not planner.is_done():
            observation = observation_builder.build(...)
            decision = scheduler.decide(observation)

            decision_validator.validate(decision, observation)
            guard_report = loop_guard.check(observation)

            if guard_report.is_stuck:
                decision = scheduler.fallback_decision(observation, guard_report)

            result = await action_executor.execute(decision, context)

            validator.apply_result(result, planner, state)
            trace_writer.write(decision, result)

        Args:
            plan: 生成计划

        Returns:
            生成报告
        """
        logger.info(f"Starting Plan-Driven Agent for run: {plan.run_id}")
        logger.info(f"Topics: {plan.topics}")
        logger.info(f"Goal: {plan.goal}")

        self.plan = plan
        self.runtime_state = AgentRuntimeState()
        self.all_questions = []
        self.trace_writer.reset()

        # 初始化计划
        self.planner.initialize(plan)

        # 阶段 1: 主题串行执行
        for topic in plan.topics:
            await self._process_topic(topic, plan)

        # 阶段 2: 全局补题（可选）
        if not self.planner.is_done() and self.runtime_state.round_num < plan.max_total_rounds:
            await self._global_backfill(plan)

        # 生成报告
        report = self._build_report(plan)

        # 保存结果
        self._save_results(report)

        return report

    async def _process_topic(
        self,
        topic: str,
        plan: GenerationPlan,
    ) -> None:
        """处理单个主题。

        Args:
            topic: 主题名称
            plan: 生成计划
        """
        logger.info(f"Processing topic: {topic}")

        state = self.planner.topic_states[topic]
        state.status = TopicStatus.ACTIVE

        # 准备证据
        chunks, evidence_pool = await self.evidence_manager.prepare_evidence(topic, plan)
        self.evidence_pools[topic] = evidence_pool

        # 重置 LoopGuard
        self.loop_guard.reset()

        # 主循环
        while not self.planner.is_topic_done(topic):
            if self.runtime_state.round_num >= plan.max_total_rounds:
                logger.info(f"Reached max total rounds: {plan.max_total_rounds}")
                break

            await self._run_one_round(topic, plan)

        # 检查退出条件
        if self.planner.is_topic_done(topic):
            state.status = TopicStatus.COMPLETED
            logger.info(f"Topic {topic} completed")
        else:
            state.status = TopicStatus.DEFERRED
            logger.info(f"Topic {topic} deferred")

    async def _run_one_round(
        self,
        topic: str,
        plan: GenerationPlan,
    ) -> None:
        """运行一轮生成。

        主循环步骤：
        1. 构建观察
        2. 规则决策
        3. 验证合法性
        4. 检查卡死
        5. 执行动作
        6. 应用结果
        7. 写入追踪

        Args:
            topic: 主题名称
            plan: 生成计划
        """
        state = self.planner.topic_states[topic]
        evidence_pool = self.evidence_pools.get(topic)

        if not evidence_pool:
            logger.warning(f"No evidence pool for topic: {topic}")
            return

        self.runtime_state.round_num += 1

        # 1. 构建观察
        observation = self.observation_builder.build(
            plan=plan,
            topic=topic,
            topic_state=state,
            evidence_pool=evidence_pool,
            evidence_stats=evidence_pool.stats,
            progress=self.planner.get_progress(),
        )

        progress_before = observation.progress

        # 2. 规则决策
        decision = self.scheduler.decide(observation)

        # 3. 验证合法性
        issues = self.decision_validator.validate(decision, observation)

        if not self.decision_validator.is_valid(issues):
            for issue in issues:
                logger.warning(f"Decision validation issue: {issue}")

            # 有严重错误，使用默认决策继续
            logger.warning("Decision validation failed, using fallback")

        # 4. 检查卡死
        gap_total = self.planner.get_total_gap()
        guard_report = self.loop_guard.check(observation)

        if guard_report.is_stuck:
            logger.warning(
                f"Loop stuck for {guard_report.stuck_rounds} rounds, "
                f"reason: {guard_report.reason}"
            )
            decision = self.scheduler.fallback_decision(observation, guard_report)

        # 记录推理（只写日志）
        logger.info(f"Decision: action={decision.action}, note={decision.note}")

        # 5. 执行动作
        context = {
            "topic": topic,
            "planner": self.planner,
            "evidence_pool": evidence_pool,
            "model_client": self.model_client,
            "language": plan.language,
            "run_id": plan.run_id,
        }

        result = await self.action_executor.execute(decision, context)

        if not result.success:
            logger.error(f"Action execution failed: {result.error}")
            return

        # 6. 应用结果
        self.validator.apply_result(result, self.planner, self.runtime_state)

        # 更新 LoopGuard
        gap_total_after = self.planner.get_total_gap()
        accepted_count = result.output.get("num_accepted", 0)

        self.loop_guard.record_round(gap_total_after, accepted_count)

        # 收集题目
        questions = result.output.get("questions", [])
        self.all_questions.extend(questions)

        # 7. 写入追踪
        progress_after = self.planner.get_progress()

        self.trace_writer.write(
            decision=decision,
            result=result,
            progress_before=progress_before,
            progress_after=progress_after,
            round_num=self.runtime_state.round_num,
            topic=topic,
        )

        logger.info(
            f"Round {self.runtime_state.round_num}: "
            f"action={decision.action}, "
            f"gap_total={gap_total_after}, "
            f"accepted={accepted_count}, "
            f"progress={progress_after:.2%}"
        )

    async def _global_backfill(self, plan: GenerationPlan) -> None:
        """全局补题阶段。

        Args:
            plan: 生成计划
        """
        logger.info("Starting global backfill phase")

        while (
            not self.planner.is_done()
            and self.runtime_state.round_num < plan.max_total_rounds
        ):
            gap_key, gap_topics = self.planner.get_global_gap()

            if not gap_key or not gap_topics:
                break

            # 选择第一个缺口主题
            target_topic = gap_topics[0]
            logger.info(f"Global backfill targeting {gap_key} on {target_topic}")

            # 尝试继续生成
            await self._run_one_round(target_topic, plan)

    def _build_report(self, plan: GenerationPlan) -> GenerationReport:
        """构建生成报告。

        Args:
            plan: 生成计划

        Returns:
            生成报告
        """
        final_counts: dict[str, int] = {}
        remaining_gaps: dict[str, int] = {}

        for state in self.planner.topic_states.values():
            for key, completed in state.completed_counts.items():
                final_counts[key] = final_counts.get(key, 0) + completed

            for key, remaining in state.remaining_counts.items():
                remaining_gaps[key] = remaining_gaps.get(key, 0) + remaining

        status = "completed" if self.planner.is_done() else "partial"

        # 构建全局统计（包含证据统计）
        global_stats = {
            "total_rounds": self.runtime_state.round_num,
            "total_questions": len(self.all_questions),
        }

        # 添加证据统计
        for topic, pool in self.evidence_pools.items():
            global_stats[f"{topic}_evidence"] = {
                "single_chunks": len(pool.single_chunks),
                "multi_chunks": len(pool.multi_chunks),
            }

        return GenerationReport(
            run_id=plan.run_id,
            goal=plan.goal,
            topics=plan.topics,
            mode_targets=plan.mode_targets,
            topic_states=self.planner.topic_states,
            global_stats=global_stats,
            final_counts=final_counts,
            remaining_gaps=remaining_gaps,
            status=status,
        )

    def _save_results(self, report: GenerationReport) -> None:
        """保存结果。

        Args:
            report: 生成报告
        """
        if self.all_questions:
            self.artifact_store.append_jsonl("accepted_questions.jsonl", self.all_questions)

        # 保存主题状态
        topic_states_data = {
            k: v.model_dump() for k, v in self.planner.topic_states.items()
        }
        self.artifact_store.save_json("topic_states.json", topic_states_data)

        # 保存生成报告
        self.artifact_store.save_json("generation_report.json", report.model_dump())

        logger.info(f"Results saved to {self.output_path}")