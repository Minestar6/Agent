"""QuestionGeneratorAgent 使用示例。"""

import asyncio
from pathlib import Path

from benchforge.schemas import GenerationPlan, QuestionModeTarget
from benchforge.agents.question_generator import QuestionGeneratorAgent
from benchforge.models import ModelLoader, ModelConfig


async def main():
    """主函数。"""
    # 1. 创建生成计划
    plan = GenerationPlan(
        run_id="run_example_001",
        goal="生成历史与产业制度相关评测题",
        topics=["Fordism", "Taylorism"],
        mode_targets={
            "multiple_choice": QuestionModeTarget(
                count=6,
                difficulty_distribution={"easy": 0.25, "medium": 0.5, "hard": 0.25},
            ),
            "qa": QuestionModeTarget(
                count=4,
                difficulty_distribution={"easy": 0.125, "medium": 0.5, "hard": 0.375},
            ),
        },
        max_rounds_per_topic=3,
        max_total_rounds=8,
        language="en",
        retrieval_policy="wikipedia_first",
    )

    # 2. 统一配置多个模型
    model_configs = [
        ModelConfig(
            model_name="gpt-4o",
            provider="openai",
            base_url="https://api.openai.com/v1",
            temperature=0.7,
        ),
        ModelConfig(
            model_name="llama3",
            provider="ollama",
            base_url="http://localhost:11434",
            temperature=0.8,
        ),
        ModelConfig(
            model_name="vllm-model",
            provider="vllm",
            base_url="http://localhost:8000",
            temperature=0.7,
        ),
    ]

    # 3. 统一加载模型
    model_clients = ModelLoader.load_models(
        configs=model_configs,
        step_name="question_generation",
    )

    # 4. 初始化代理
    agent = QuestionGeneratorAgent(model_clients=model_clients)

    # 5. 执行生成
    print("开始生成题目...")
    print(f"使用模型数量: {len(agent.model_clients)}")
    for i, client in enumerate(agent.model_clients):
        model_name = getattr(client, 'model_name', f'model_{i}')
        print(f"  - {model_name}")

    report = await agent.execute(plan)

    # 6. 打印报告
    print("\n=== 生成报告 ===")
    print(f"状态: {report.status}")
    print(f"完成数量: {report.final_counts}")
    print(f"剩余缺口: {report.remaining_gaps}")

    # 7. 查看各主题状态
    print("\n=== 主题状态 ===")
    for topic, state in report.topic_states.items():
        print(f"\n主题 {topic}:")
        print(f"  状态: {state.status.value}")
        print(f"  轮次: {state.current_round}")
        print(f"  目标: {state.target_counts}")
        print(f"  完成: {state.completed_counts}")
        print(f"  剩余: {state.remaining_counts}")
        print(f"  证据池: {len(state.available_single_chunk_ids)} 单 chunk, "
              f"{len(state.available_multi_chunk_ids)} 多 chunk")

    # 8. 输出文件位置
    output_path = Path("runs/run_example_001")
    print(f"\n=== 输出文件 ===")
    print(f"输出目录: {output_path.absolute()}")
    if output_path.exists():
        for file in output_path.iterdir():
            print(f"  - {file.name}")


if __name__ == "__main__":
    asyncio.run(main())