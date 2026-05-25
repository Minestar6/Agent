"""TraceWriter 模块：实时写 decision_trace.jsonl。"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class TraceWriter:
    """决策追踪写入器。

    职责：
    - 实时写入 decision_trace.jsonl
    - 支持内存累积（可选）
    """

    def __init__(self, output_path: Path):
        """初始化追踪写入器。

        Args:
            output_path: 输出目录路径
        """
        self.output_path = output_path
        self.trace_file = output_path / "decision_trace.jsonl"
        self._step_id = 0

    def write(
        self,
        decision: Any,
        result: Any,
        progress_before: float,
        progress_after: float,
        round_num: int,
        topic: str,
    ) -> None:
        """写入追踪记录。

        Args:
            decision: 控制决策
            result: 执行结果
            progress_before: 执行前进度
            progress_after: 执行后进度
            round_num: 轮次
            topic: 主题
        """
        from benchforge.schemas import DecisionTrace

        self._step_id += 1

        trace = DecisionTrace(
            timestamp=datetime.utcnow().isoformat(),
            step_id=self._step_id,
            round_num=round_num,
            topic=topic,
            gap_key=decision.params.get("gap_key", None),
            action=decision.action,
            note=decision.note,
            priority=decision.priority,
            progress_before=progress_before,
            progress_after=progress_after,
            num_candidates=result.output.get("num_candidates", 0),
            num_accepted=result.output.get("num_accepted", 0),
            num_rejected=result.output.get("num_rejected", 0),
        )

        # 追加到文件
        with open(self.trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(trace.to_dict(), ensure_ascii=False) + "\n")

    def reset(self) -> None:
        """重置步骤计数器。"""
        self._step_id = 0