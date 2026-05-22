# BenchForge

基准测试问题自动生成框架，支持多种模型后端。

## 功能

- 自动从 Wikipedia 检索相关文档
- 智能文档分块处理
- 使用 LLM 自动生成高质量评估问题
- 自动生成答案和引用
- 支持多种问题类型和难度级别
- **支持多种模型后端**：OpenAI API、Ollama、vLLM、Transformers
- 结构化输出 (JSONL 格式)

## 项目结构

```
benchforge/
├── agents/          # 代理模块
│   └── question_generator.py
├── artifacts/       # 存储模块
│   └── store.py
├── config/          # 配置管理
│   ├── config.py
│   └── question_generator_config.yaml
├── models/          # 模型客户端
│   ├── base.py              # 抽象基类
│   ├── openai_client.py     # OpenAI 兼容 API
│   ├── local_client.py      # 本地模型
│   └── fake.py              # 测试用假客户端
├── utils/           # 工具函数
│   ├── chunking.py          # 文本分块
│   ├── parsing.py           # JSON 解析
│   └── retrieval.py         # Wikipedia 检索
├── prompts/         # 提示模板
│   └── question_generation.md
└── schemas/         # 数据模式
    └── __init__.py
```

## 安装

```bash
pip install -r requirements.txt
```

### 可选依赖

```bash
# 本地模型支持
pip install transformers torch

# Ollama 支持（无需额外安装，只需运行 Ollama 服务）
# vLLM 支持（无需额外安装，只需运行 vLLM 服务）
```

## 模型后端支持

### 1. OpenAI 兼容 API（默认）

```python
from benchforge.models import OpenAIClient
from benchforge.agents import QuestionGeneratorAgent

client = OpenAIClient(
    api_key="your-api-key",
    base_url="https://api.openai.com/v1",
)
agent = QuestionGeneratorAgent(config=config, model_client=client)
```

### 2. Ollama 本地模型

```python
from benchforge.models import OllamaClient

client = OllamaClient(base_url="http://localhost:11434")
agent.config.generation.model.model_name = "llama2"
```

### 3. vLLM 本地模型

```python
from benchforge.models import VLLMClient

client = VLLMClient(base_url="http://localhost:8000/v1")
```

### 4. Transformers 直接加载

```python
from benchforge.models import TransformersClient

client = TransformersClient(
    model_name_or_path="gpt2",
    device="auto",
)
```

### 5. 假模型（测试用）

```python
from benchforge.models import FakeModelClient

fake_client = FakeModelClient()
agent = QuestionGeneratorAgent(config=config, model_client=fake_client)
```

## 快速开始

```python
import asyncio
from benchforge.agents import QuestionGeneratorAgent
from benchforge.models import OpenAIClient
from benchforge.schemas import GenerationPlan, QuestionModeTarget

async def generate_questions():
    plan = GenerationPlan(
        run_id="my_run",
        goal="生成 AI 领域评估问题",
        topics=["Artificial Intelligence"],
        mode_targets={
            "qa": QuestionModeTarget(
                count=10,
                difficulty_distribution={"easy": 0.3, "medium": 0.5, "hard": 0.2},
            )
        },
        max_rounds_per_topic=3,
        max_total_rounds=10,
    )

    client = OpenAIClient(api_key="your-api-key")
    agent = QuestionGeneratorAgent(model_client=client)

    report = await agent.execute(plan)
    print(f"状态: {report.status}")
    print(f"最终计数: {report.final_counts}")
    print(f"剩余缺口: {report.remaining_gaps}")

asyncio.run(generate_questions())
```

## 命令行运行

```bash
# 使用假模型（测试）
python example_run.py fake

# 使用 OpenAI
python example_run.py openai

# 使用 Ollama
python example_run.py ollama

# 使用 vLLM
python example_run.py vllm

# 使用 Transformers
python example_run.py transformers
```

## 配置文件

```yaml
# benchforge/config/question_generator_config.yaml

generation:
  model:
    provider: "openai"  # openai, ollama, vllm, transformers
    model_name: "gpt-4o-mini"
    base_url: "${OPENAI_BASE_URL:https://api.openai.com/v1}"
    api_key: "${OPENAI_API_KEY}"
    temperature: 0.7
    max_tokens: 2000

chunking:
  chunk_size: 1200
  overlap: 150

retrieval:
  max_pages: 5
  content_max_length: 10000
```

## 开发

```bash
# 运行测试
pytest

# 代码检查
ruff check .
ruff format .
```

## 许可证

MIT License