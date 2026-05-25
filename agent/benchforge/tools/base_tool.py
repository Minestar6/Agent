"""工具基类和规格定义。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    """工具规格。

    定义工具的输入输出schema、重试策略等。
    """
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)   # JSON Schema
    output_schema: dict[str, Any] = field(default_factory=dict)  # JSON Schema
    retryable: bool = False
    max_retries: int = 3
    timeout: int = 60


@dataclass
class ToolResult:
    """工具执行结果。"""
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    retries: int = 0


class BaseTool(ABC):
    """工具基类。

    所有工具都必须继承此类，并实现spec和execute方法。
    """

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        """返回工具规格。"""
        pass

    @abstractmethod
    async def execute(self, parameters: dict[str, Any], state: dict[str, Any]) -> ToolResult:
        """执行工具。

        Args:
            parameters: 输入参数
            state: 当前状态

        Returns:
            执行结果
        """
        pass

    def validate_input(self, parameters: dict[str, Any]) -> bool:
        """验证输入参数。

        Args:
            parameters: 输入参数

        Returns:
            是否有效
        """
        # 简化实现：检查必需字段
        required = self.spec.input_schema.get("required", [])
        properties = self.spec.input_schema.get("properties", {})

        for field in required:
            if field not in parameters:
                return False

            # 检查类型（简化实现）
            if field in properties:
                expected_type = properties[field].get("type")
                actual_value = parameters[field]

                if expected_type == "string" and not isinstance(actual_value, str):
                    return False
                elif expected_type == "integer" and not isinstance(actual_value, int):
                    return False
                elif expected_type == "boolean" and not isinstance(actual_value, bool):
                    return False
                elif expected_type == "array" and not isinstance(actual_value, list):
                    return False

        return True