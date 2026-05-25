"""采样工具。"""

from typing import Any

from benchforge.tools.base_tool import BaseTool, ToolSpec, ToolResult
from benchforge.utils.sampling import (
    BroadExplorationSampling,
    GapDrivenSampling,
)


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
                    "topic": {"type": "string", "description": "主题名称"},
                    "strategy": {
                        "type": "string",
                        "enum": ["gap_driven", "broad_exploration"],
                        "description": "采样策略"
                    },
                    "target_gap": {
                        "type": "string",
                        "pattern": "^(qa|multiple_choice):(easy|medium|hard)$",
                        "description": "目标缺口"
                    },
                    "num_evidence": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "证据数量"
                    },
                    "prefer_multi_chunk": {
                        "type": "boolean",
                        "default": False,
                        "description": "是否偏好多证据"
                    },
                },
                "required": ["topic", "strategy", "target_gap", "num_evidence"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "batch": {"type": "object"},
                    "single_chunk_count": {"type": "integer"},
                    "multi_chunk_count": {"type": "integer"},
                },
            },
            retryable=False,  # 采样不需要重试
            max_retries=1,
            timeout=30,
        )

    async def execute(self, parameters: dict[str, Any], state: dict[str, Any]) -> ToolResult:
        """执行采样。

        Args:
            parameters: 输入参数
            state: 当前状态

        Returns:
            执行结果
        """
        topic = parameters["topic"]
        strategy = parameters["strategy"]
        target_gap = parameters["target_gap"]
        num_evidence = parameters["num_evidence"]
        prefer_multi_chunk = parameters.get("prefer_multi_chunk", False)

        # 获取证据池
        pool = state.get("evidence_pools", {}).get(topic)
        if not pool:
            return ToolResult(
                success=False,
                output={},
                error=f"Evidence pool not found for topic: {topic}"
            )

        # 选择采样策略
        if strategy == "broad_exploration":
            sampler = BroadExplorationSampling()
        elif strategy == "gap_driven":
            sampler = GapDrivenSampling()
        else:
            return ToolResult(
                success=False,
                output={},
                error=f"Unknown strategy: {strategy}"
            )

        # 解析目标缺口
        target_mode, target_difficulty = target_gap.split(":")

        # 执行采样
        try:
            batch = sampler.sample(
                pool=pool,
                target_mode=target_mode,
                target_difficulty=target_difficulty,
                num_evidence=num_evidence,
                prefer_multi_chunk=prefer_multi_chunk
            )

            # 更新证据使用计数（简化版）
            for chunk_id in batch.single_chunk_ids:
                for chunk in pool.single_chunks:
                    if chunk.chunk_id == chunk_id:
                        chunk.usage_count += 1

            for unit_id in batch.multi_chunk_ids:
                for unit in pool.multi_chunks:
                    if unit.unit_id == unit_id:
                        unit.usage_count += 1

            return ToolResult(
                success=True,
                output={
                    "batch": batch,
                    "single_chunk_count": len(batch.single_chunk_ids),
                    "multi_chunk_count": len(batch.multi_chunk_ids),
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output={},
                error=f"Sampling failed: {e}"
            )