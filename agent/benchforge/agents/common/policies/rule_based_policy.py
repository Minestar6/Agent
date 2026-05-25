"""基于规则的决策策略（复制原有逻辑）。"""

from typing import Any

from benchforge.schemas import Observation, AgentDecision, ControlDecision, DecisionReasoning
from benchforge.utils.planning import (
    identify_main_gap,
    build_allowed_actions,
    check_topic_completion,
    calculate_batch_request_counts,
)


class RuleBasedDecisionPolicy:
    """基于规则的决策策略。

    复制原有的build_next_step_plan逻辑，作为baseline和fallback。

    输出：AgentDecision（包含ControlDecision + DecisionReasoning）
    """

    def decide(self, observation: Observation) -> AgentDecision:
        """基于规则做决策。

        Args:
            observation: 摘要化的观察

        Returns:
            Agent决策
        """
        # 1. 检查是否应该完成
        if observation.gap_remaining == 0 or observation.round >= observation.max_rounds:
            return self._finish_decision(observation)

        # 2. 确定目标
        target_gap = observation.primary_gap

        # 3. 构建ControlDecision
        control = self._build_control_decision(observation, target_gap)

        # 4. 构建DecisionReasoning
        reasoning = self._build_reasoning(observation, target_gap)

        return AgentDecision(
            control=control,
            reasoning=reasoning,
        )

    def _finish_decision(self, observation: Observation) -> AgentDecision:
        """完成决策。"""
        control = ControlDecision(
            next_action="finish_topic",
            action_parameters={"topic": observation.topic},
        )

        reasoning = DecisionReasoning(
            summary=f"主题{observation.topic}已完成或达到最大轮数",
            primary_gap="",
            selected_strategy="finish",
            confidence=1.0,
        )

        return AgentDecision(
            control=control,
            reasoning=reasoning,
        )

    def _build_control_decision(
        self,
        observation: Observation,
        target_gap: str
    ) -> ControlDecision:
        """构建控制决策（决定具体的action和parameters）。"""

        # 根据缺口决定action
        if observation.gap_remaining > 0:
            # 继续生成
            min_questions, target_questions = calculate_batch_request_counts(
                observation.gap_remaining
            )

            target_mode, target_difficulty = target_gap.split(":")

            control = ControlDecision(
                next_action="generate_questions",
                action_parameters={
                    "topic": observation.topic,
                    "target_mode": target_mode,
                    "target_difficulty": target_difficulty,
                    "requested_questions": target_questions,
                    "strategy": "gap_driven" if observation.round > 0 else "broad_exploration",
                    "num_evidence": min(5, observation.gap_remaining + 2),
                    "prefer_multi_chunk": self._should_prefer_multi_chunk(observation, target_difficulty),
                },
            )
        else:
            # 应该不会到这里，但保险起见
            control = ControlDecision(
                next_action="finish_topic",
                action_parameters={"topic": observation.topic},
            )

        return control

    def _build_reasoning(
        self,
        observation: Observation,
        target_gap: str
    ) -> DecisionReasoning:
        """构建决策推理（用于日志）。"""

        if observation.gap_remaining == 0:
            return DecisionReasoning(
                summary="所有目标已完成",
                primary_gap="",
                selected_strategy="finish",
                confidence=1.0,
            )

        # 构建推理文本
        strategy = "gap_driven" if observation.round > 0 else "broad_exploration"

        return DecisionReasoning(
            summary=f"缺口{target_gap}剩余{observation.gap_remaining}题，使用{strategy}策略",
            primary_gap=target_gap,
            selected_strategy=strategy,
            confidence=0.9,  # 规则策略置信度高
        )

    def _should_prefer_multi_chunk(self, observation: Observation, difficulty: str) -> bool:
        """是否应该偏好多证据。

        Args:
            observation: 观察
            difficulty: 目标难度

        Returns:
            是否偏好多证据
        """
        # hard题目且多证据效率高时，偏好多证据
        if difficulty == "hard":
            return observation.multi_evidence_efficiency > observation.single_evidence_efficiency

        return False