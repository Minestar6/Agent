"""循环守护器：检测无效循环（代码实现）。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LoopGuardConfig:
    """循环守护配置。"""
    max_no_progress_rounds: int = 3    # 最大无进展轮数
    min_gap_reduction_threshold: int = 1  # 最小缺口减少阈值
    min_coverage_progress_threshold: float = 0.05  # 最小覆盖率进度阈值


@dataclass
class LoopGuardReport:
    """循环守护报告。"""
    is_stuck: bool
    stuck_rounds: int
    last_progress_round: int
    suggested_actions: list[str] = field(default_factory=list)


class LoopGuard:
    """循环守护器（纯代码实现，确定性）。

    防止"看起来在动，其实没进展"。

    检测：
    - 连续N轮 gap_reduction == 0
    - 连续N轮 coverage_progress < 阈值

    触发：
    - expand_evidence
    - adjust_strategy
    - finish_topic
    """

    def __init__(self, config: LoopGuardConfig | None = None):
        """初始化。"""
        self.config = config or LoopGuardConfig()
        self.gap_history: list[int] = []  # 缺口总数历史
        self.coverage_history: list[float] = []  # 覆盖率进度历史

    def record_round(self, gap_total: int, coverage_progress: float):
        """记录一轮的结果。

        Args:
            gap_total: 当前缺口总数
            coverage_progress: 当前覆盖率进度（0-1）
        """
        self.gap_history.append(gap_total)
        self.coverage_history.append(coverage_progress)

    def check_stuck(self) -> LoopGuardReport:
        """检查是否陷入无效循环。

        Returns:
            循环守护报告
        """
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
        """生成卡住时的建议行动。

        Returns:
            建议行动列表
        """
        return [
            "expand_retrieval",     # 扩展证据池
            "adjust_strategy",     # 调整策略
            "finish_topic",        # 强制完成
        ]

    def reset(self):
        """重置历史。"""
        self.gap_history = []
        self.coverage_history = []