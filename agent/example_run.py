"""BenchForge 示例运行脚本（支持多种模型后端）。"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from benchforge.config import QuestionGeneratorConfig
from benchforge.agents import QuestionGeneratorAgent
from benchforge.models import (
    OpenAIClient,
    OllamaClient,
    VLLMClient,
    FakeModelClient,
)
from benchforge.schemas import GenerationPlan, QuestionModeTarget


async def demo_openai():
    """使用 OpenAI API。"""
    import os

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("请设置 OPENAI_API_KEY 环境变量")
        return

    plan = GenerationPlan(
        run_id="openai_demo_001",
        goal="demo benchmark generation",
        topics=["Fordism"],
        mode_targets={
            "qa": QuestionModeTarget(
                count=6,
                difficulty_distribution={"easy": 0.33, "medium": 0.34, "hard": 0.33},
            )
        },
        max_rounds_per_topic=3,
        max_total_rounds=6,
    )

    client = OpenAIClient(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )

    agent = QuestionGeneratorAgent(model_client=client)
    report = await agent.execute(plan)

    print(f"\nOpenAI 演示完成!")
    print(f"状态: {report.status}")
    print(f"最终计数: {report.final_counts}")
    print(f"剩余缺口: {report.remaining_gaps}")


async def demo_ollama():
    """使用 Ollama 本地模型。"""
    plan = GenerationPlan(
        run_id="ollama_demo_001",
        goal="demo benchmark generation",
        topics=["Quantum Computing"],
        mode_targets={
            "qa": QuestionModeTarget(
                count=4,
                difficulty_distribution={"easy": 0.25, "medium": 0.5, "hard": 0.25},
            )
        },
        max_rounds_per_topic=2,
        max_total_rounds=4,
    )

    client = OllamaClient(base_url="http://localhost:11434")
    agent = QuestionGeneratorAgent(model_client=client)
    agent.config.generation.model.model_name = "llama2"

    report = await agent.execute(plan)

    print(f"\nOllama 演示完成!")
    print(f"状态: {report.status}")
    print(f"最终计数: {report.final_counts}")
    print(f"剩余缺口: {report.remaining_gaps}")


async def demo_vllm():
    """使用 vLLM 本地模型。"""
    plan = GenerationPlan(
        run_id="vllm_demo_001",
        goal="demo benchmark generation",
        topics=["Artificial Intelligence"],
        mode_targets={
            "qa": QuestionModeTarget(
                count=4,
                difficulty_distribution={"easy": 0.25, "medium": 0.5, "hard": 0.25},
            )
        },
        max_rounds_per_topic=2,
        max_total_rounds=4,
    )

    client = VLLMClient(base_url="http://localhost:8000/v1")
    agent = QuestionGeneratorAgent(model_client=client)
    agent.config.generation.model.model_name = "meta-llama/Meta-Llama-3-8B-Instruct"

    report = await agent.execute(plan)

    print(f"\nvLLM 演示完成!")
    print(f"状态: {report.status}")
    print(f"最终计数: {report.final_counts}")
    print(f"剩余缺口: {report.remaining_gaps}")


async def demo_transformers():
    """使用 Transformers 直接加载模型（需要先下载模型）。"""
    plan = GenerationPlan(
        run_id="transformers_demo_001",
        goal="demo benchmark generation",
        topics=["Machine Learning"],
        mode_targets={
            "qa": QuestionModeTarget(
                count=4,
                difficulty_distribution={"easy": 0.25, "medium": 0.5, "hard": 0.25},
            )
        },
        max_rounds_per_topic=2,
        max_total_rounds=4,
    )

    try:
        from benchforge.models import TransformersClient

        client = TransformersClient(
            model_name_or_path="gpt2",
            device="auto",
        )
        agent = QuestionGeneratorAgent(model_client=client)
        agent.config.generation.model.model_name = "gpt2"

        report = await agent.execute(plan)

        print(f"\nTransformers 演示完成!")
        print(f"状态: {report.status}")
        print(f"最终计数: {report.final_counts}")
        print(f"剩余缺口: {report.remaining_gaps}")

    except ImportError:
        print("请安装 transformers 和 torch: pip install transformers torch")
    except Exception as e:
        print(f"Transformers 演示失败: {e}")


async def demo_fake():
    """使用假模型（用于测试，无需 API Key）。"""
    plan = GenerationPlan(
        run_id="fake_demo_001",
        goal="demo benchmark generation",
        topics=["Quantum Computing"],
        mode_targets={
            "qa": QuestionModeTarget(
                count=4,
                difficulty_distribution={"easy": 0.25, "medium": 0.5, "hard": 0.25},
            )
        },
        max_rounds_per_topic=2,
        max_total_rounds=4,
    )

    fake_client = FakeModelClient()
    agent = QuestionGeneratorAgent(model_client=fake_client)
    report = await agent.execute(plan)

    print(f"\n假模型演示完成!")
    print(f"状态: {report.status}")
    print(f"最终计数: {report.final_counts}")
    print(f"剩余缺口: {report.remaining_gaps}")
    print(f"模型调用次数: {fake_client.call_count}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BenchForge 演示")
    parser.add_argument(
        "mode",
        choices=["openai", "ollama", "vllm", "transformers", "fake"],
        default="fake",
        help="运行模式",
    )

    args = parser.parse_args()

    print(f"使用 {args.mode} 模式运行...")

    if args.mode == "openai":
        asyncio.run(demo_openai())
    elif args.mode == "ollama":
        asyncio.run(demo_ollama())
    elif args.mode == "vllm":
        asyncio.run(demo_vllm())
    elif args.mode == "transformers":
        asyncio.run(demo_transformers())
    else:
        asyncio.run(demo_fake())