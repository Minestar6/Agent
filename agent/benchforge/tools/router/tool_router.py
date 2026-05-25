"""工具路由器。"""

from typing import Any
from loguru import logger

from benchforge.tools.base_tool import BaseTool, ToolResult
from benchforge.tools.sampling_tool import SamplingTool
from benchforge.tools.generation_tool import GenerationTool
from benchforge.tools.retrieval_tool import RetrievalTool


class ToolRouter:
    """工具路由器（代码实现，确定性）。

    职责：
    - 注册工具
    - 验证输入
    - 执行工具（带重试）
    """

    def __init__(self):
        """初始化工具路由器。"""
        self.tools: dict[str, BaseTool] = {}
        self._register_tools()

    def _register_tools(self):
        """注册工具（Phase 1版本，只注册3个工具）。"""
        self.tools = {
            "sample_evidence": SamplingTool(),
            "generate_questions": GenerationTool(),
            "expand_retrieval": RetrievalTool(),
        }

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        state: dict[str, Any]
    ) -> ToolResult:
        """执行工具。

        Args:
            action: 动作名称
            parameters: 输入参数
            state: 当前状态

        Returns:
            执行结果
        """
        tool = self.tools.get(action)

        if not tool:
            return ToolResult(
                success=False,
                output={},
                error=f"Unknown action: {action}"
            )

        # 验证输入
        if not tool.validate_input(parameters):
            return ToolResult(
                success=False,
                output={},
                error="Input validation failed"
            )

        # 执行（带重试）
        if tool.spec.retryable:
            result = await self._execute_with_retry(tool, parameters, state)
        else:
            result = await tool.execute(parameters, state)

        return result

    async def _execute_with_retry(
        self,
        tool: BaseTool,
        parameters: dict[str, Any],
        state: dict[str, Any]
    ) -> ToolResult:
        """带重试的执行。

        Args:
            tool: 工具
            parameters: 参数
            state: 状态

        Returns:
            执行结果
        """
        for attempt in range(tool.spec.max_retries):
            try:
                result = await tool.execute(parameters, state)
                if result.success:
                    return result
            except Exception as e:
                logger.warning(f"Tool {tool.spec.name} attempt {attempt + 1} failed: {e}")

        return ToolResult(
            success=False,
            output={},
            error="Max retries exceeded"
        )

    def list_tools(self) -> list[dict[str, Any]]:
        """列出所有工具规格。"""
        return [tool.spec for tool in self.tools.values()]