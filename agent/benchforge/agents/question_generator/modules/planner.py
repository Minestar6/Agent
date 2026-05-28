"""Planner 模块：解析计划、维护 TopicState / remaining_counts。"""

from typing import Any

from benchforge.schemas import (
    GenerationPlan,
    TopicState,
    TopicStatus,
    QuestionModeTarget,
)


class Planner:
    """计划解析器和状态维护器。

    职责：
    - 解析 GenerationPlan
    - 维护 TopicState
    - 跟踪 remaining_counts
    - 判断计划是否完成
    """

    def __init__(self):
        """初始化 Planner。"""
        self.topic_states: dict[str, TopicState] = {}
        self.plan: GenerationPlan | None = None

    def initialize(self, plan: GenerationPlan) -> dict[str, TopicState]:
        """初始化计划，创建主题状态。

        Args:
            plan: 生成计划

        Returns:
            主题状态字典
        """
        self.plan = plan
        self.topic_states = self._compile_generation_plan(plan)
        return self.topic_states

    def _compile_generation_plan(self, plan: GenerationPlan) -> dict[str, TopicState]:
        """编译生成计划，初始化主题状态。

        步骤：
        1. 展开 mode × difficulty 目标数
        2. 按主题均分
        3. 初始化 TopicState

        Args:
            plan: 生成计划

        Returns:
            主题状态字典
        """
        topic_states: dict[str, TopicState] = {}

        # 1. 展开 mode × difficulty 目标数
        global_targets = self._expand_mode_targets(plan.mode_targets)

        # 2. 按主题均分
        topic_targets = self._distribute_across_topics(global_targets, plan.topics)

        # 3. 初始化 TopicState
        for topic in plan.topics:
            topic_states[topic] = TopicState(
                topic=topic,
                status=TopicStatus.PENDING,
                current_round=0,
                target_counts=topic_targets.get(topic, {}),
                completed_counts={},
                remaining_counts=topic_targets.get(topic, {}),
            )

        return topic_states

    def _expand_mode_targets(
        self,
        mode_targets: dict[str, QuestionModeTarget],
    ) -> dict[str, int]:
        """展开模式目标为具体难度数量。

        使用最大余数法分配余数。

        Args:
            mode_targets: 模式目标

        Returns:
            展开后的目标 {mode:difficulty: count}
        """
        expanded = {}

        for mode, target in mode_targets.items():
            count = target.count
            distribution = target.difficulty_distribution

            # 计算浮点目标
            float_targets = {
                f"{mode}:{diff}": count * ratio
                for diff, ratio in distribution.items()
            }

            # 向下取整
            floor_targets = {
                key: int(value)
                for key, value in float_targets.items()
            }

            # 计算余数
            remainder_keys = [
                (key, float_targets[key] - floor_targets[key])
                for key in floor_targets.keys()
            ]
            remainder_keys.sort(key=lambda x: x[1], reverse=True)

            # 计算已分配总数
            allocated = sum(floor_targets.values())
            remainder = count - allocated

            # 分配余数
            for i in range(remainder):
                if i < len(remainder_keys):
                    key = remainder_keys[i][0]
                    floor_targets[key] += 1

            expanded.update(floor_targets)

        return expanded

    def _distribute_across_topics(
        self,
        global_targets: dict[str, int],
        topics: list[str],
    ) -> dict[str, dict[str, int]]:
        """将全局目标均分到各主题。

        Args:
            global_targets: 全局目标
            topics: 主题列表

        Returns:
            各主题目标 {topic: {mode:difficulty: count}}
        """
        topic_targets = {}

        if not topics:
            return topic_targets

        num_topics = len(topics)

        for key, total in global_targets.items():
            base = total // num_topics
            remainder = total % num_topics

            for i, topic in enumerate(topics):
                if topic not in topic_targets:
                    topic_targets[topic] = {}

                count = base
                if i < remainder:
                    count += 1

                topic_targets[topic][key] = count

        return topic_targets

    def update_state(
        self,
        topic: str,
        completed_counts: dict[str, int],
    ) -> TopicState:
        """更新主题状态。

        Args:
            topic: 主题名称
            completed_counts: 本轮完成的计数字典

        Returns:
            更新后的主题状态
        """
        state = self.topic_states.get(topic)
        if not state:
            raise ValueError(f"Topic state not found: {topic}")

        # 更新已完成计数
        for key, count in completed_counts.items():
            if key not in state.completed_counts:
                state.completed_counts[key] = 0
            state.completed_counts[key] += count

        # 更新剩余计数
        for key in state.target_counts.keys():
            completed = state.completed_counts.get(key, 0)
            target = state.target_counts.get(key, 0)
            state.remaining_counts[key] = max(0, target - completed)

        return state

    def is_topic_done(self, topic: str) -> bool:
        """检查主题是否完成。

        Args:
            topic: 主题名称

        Returns:
            是否完成（含 DEFERRED 状态）
        """
        state = self.topic_states.get(topic)
        if not state:
            return False

        # DEFERRED 和 COMPLETED 状态均视为"不再处理"
        if state.status in (TopicStatus.DEFERRED, TopicStatus.COMPLETED):
            return True

        for key, target in state.target_counts.items():
            completed = state.completed_counts.get(key, 0)
            if completed < target:
                return False
        return True

    def is_done(self) -> bool:
        """检查所有主题是否完成。

        Returns:
            是否完成
        """
        return all(self.is_topic_done(topic) for topic in self.topic_states.keys())

    def get_total_gap(self) -> int:
        """获取全局剩余缺口总数。

        Returns:
            剩余缺口总数
        """
        total = 0
        for state in self.topic_states.values():
            total += sum(state.remaining_counts.values())
        return total

    def get_progress(self) -> float:
        """获取整体完成进度。

        Returns:
            进度 0.0-1.0
        """
        total_target = sum(
            sum(state.target_counts.values()) for state in self.topic_states.values()
        )
        if total_target == 0:
            return 1.0

        total_completed = sum(
            sum(state.completed_counts.values()) for state in self.topic_states.values()
        )
        return total_completed / total_target

    def get_global_gap(self) -> tuple[str | None, list[str]]:
        """获取全局最大的模式难度缺口。

        Returns:
            (缺口键, 主题列表) 或 (None, [])
        """
        gap_totals: dict[str, int] = {}
        gap_topics: dict[str, list[str]] = {}

        for topic, state in self.topic_states.items():
            if state.status == TopicStatus.DEFERRED:
                continue

            for key, remaining in state.remaining_counts.items():
                if remaining <= 0:
                    continue
                gap_totals[key] = gap_totals.get(key, 0) + remaining
                gap_topics.setdefault(key, []).append(topic)

        if not gap_totals:
            return None, []

        # 按缺口数量降序，然后按模式难度排序（hard > medium > easy）
        def sort_key(item: tuple[str, int]) -> tuple[int, str]:
            key, count = item
            difficulty_order = {"hard": 0, "medium": 1, "easy": 2}
            diff = key.split(":")[-1] if ":" in key else "medium"
            return (-count, difficulty_order.get(diff, 1), key)

        best_key = sorted(gap_totals.items(), key=sort_key)[0][0]
        return best_key, gap_topics.get(best_key, [])