"""配置加载和管理模块。"""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def expand_env_vars(text: str) -> str:
    """展开环境变量。

    支持 ${VAR:default} 语法：
    ${OPENAI_API_KEY} - 使用环境变量，不存在则空字符串
    ${OPENAI_BASE_URL:https://api.openai.com/v1} - 使用环境变量，不存在则使用默认值

    Args:
        text: 包含环境变量引用的文本

    Returns:
        展开后的文本
    """
    def replace_match(match):
        var_expr = match.group(1)
        if ":" in var_expr:
            var_name, default = var_expr.split(":", 1)
            return os.getenv(var_name, default)
        else:
            return os.getenv(var_expr, "")

    pattern = r'\$\{([^}]+)\}'
    return re.sub(pattern, replace_match, text)


def expand_env_recursive(data: Any) -> Any:
    """递归展开数据结构中的环境变量。"""
    if isinstance(data, str):
        return expand_env_vars(data)
    elif isinstance(data, dict):
        return {k: expand_env_recursive(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [expand_env_recursive(item) for item in data]
    else:
        return data


class ModelConfig(BaseModel):
    """模型配置。"""
    provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    temperature: float = 0.7
    max_tokens: int = 2000
    max_retries: int = 3


class RetrievalConfig(BaseModel):
    """检索配置。"""
    max_pages: int = 5
    max_results_per_query: int = 10
    summary_length: int = 500
    content_max_length: int = 10000
    request_timeout: int = 10
    rate_limit_delay: float = 0.5


class ChunkingConfig(BaseModel):
    """分块配置。"""
    chunk_size: int = 1200
    overlap: int = 150
    encoding: str = "cl100k_base"


class GenerationConfig(BaseModel):
    """生成配置。"""
    model: ModelConfig = Field(default_factory=ModelConfig)
    questions_per_chunk: int = 2
    question_mode: str = "open-ended"
    prompt_template_id: str = "question_generation_v1"
    allowed_question_types: list[str] = Field(default_factory=list)
    difficulty_distribution: dict[str, float] = Field(default_factory=dict)


class ValidationConfig(BaseModel):
    """验证配置。"""
    require_citations: bool = True
    min_citation_length: int = 20
    require_capability: bool = True
    deduplicate: bool = True


class PromptConfig(BaseModel):
    """提示配置。"""
    template_path: str = "./prompts/question_generation.md"
    system_prompt: str = "你是一个专业的问答题目生成专家。"


class OutputConfig(BaseModel):
    """输出配置。"""
    save_raw_responses: bool = True
    save_source_documents: bool = True
    output_format: str = "jsonl"


class LoggingConfig(BaseModel):
    """日志配置。"""
    level: str = "INFO"
    log_file: str = "./logs/${run_id}.log"


class RunConfig(BaseModel):
    """运行配置。"""
    run_id: str = "run_001"
    output_path: str = "./runs/${run_id}"
    language: str = "en"
    domain: str | None = None


class QuestionGeneratorConfig(BaseModel):
    """问题生成智能体统一配置。"""

    # 运行时配置
    run: RunConfig = Field(default_factory=RunConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    prompt: PromptConfig = Field(default_factory=PromptConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def from_yaml(cls, config_path: str | Path, run_id: str | None = None) -> "QuestionGeneratorConfig":
        """从 YAML 文件加载配置。"""
        config_path = Path(config_path)

        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        # 展开环境变量
        raw_data = expand_env_recursive(raw_data)

        # 如果提供了 run_id，覆盖配置中的 run_id
        if run_id is not None:
            if "run" in raw_data:
                raw_data["run"]["run_id"] = run_id
            else:
                raw_data["run"] = {"run_id": run_id}

        return cls.model_validate(raw_data)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return self.model_dump()

    def save_yaml(self, output_path: str | Path) -> None:
        """保存为 YAML 文件。"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = self.to_dict()
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def get_resolved_output_path(self) -> Path:
        """获取解析后的输出路径（替换 ${run_id}）。"""
        return Path(self.run.output_path.replace("${run_id}", self.run.run_id))

    def get_resolved_log_path(self) -> Path:
        """获取解析后的日志路径（替换 ${run_id}）。"""
        return Path(self.logging.log_file.replace("${run_id}", self.run.run_id))