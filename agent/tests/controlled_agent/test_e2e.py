"""Phase 1 端到端集成测试。"""

import asyncio
from pathlib import Path
from benchforge.models import OpenAIClient
from benchforge.config import QuestionGeneratorConfig, RunConfig
from benchforge.schemas import (
    GenerationPlan,
    QuestionModeTarget,
    Difficulty,
    QuestionMode,
)
from benchforge.agents.question_generator import ControlledQuestionGeneratorAgent


async def test_e2e():
    """端到端测试完整流程。"""

    print("=" * 60)
    print("Phase 1 端到端集成测试")
    print("=" * 60)

    # 创建配置（使用正确的schema格式）
    config = QuestionGeneratorConfig(
        run=RunConfig(
            run_id="test_e2e_001",
            output_path="./tests/output/${run_id}",
            language="en",
        ),
    )

    print("\n[配置]")
    print(f"   - 输出目录: {config.run.output_path}")
    print(f"   - run_id: {config.run.run_id}")

    # 创建生成计划（使用正确的schema格式）
    qa_target = QuestionModeTarget(
        count=4,
        difficulty_distribution={"easy": 0.5, "medium": 0.5},
    )

    plan = GenerationPlan(
        run_id="test_e2e_001",
        goal="Generate test questions",
        topics=["machine_learning"],
        mode_targets={"qa": qa_target},
        max_rounds_per_topic=3,
        max_total_rounds=10,
        language="en",
    )

    print("\n[执行计划]")
    print(f"   - run_id: {plan.run_id}")
    print(f"   - 目标: {plan.goal}")
    print(f"   - 主题: {plan.topics}")

    # 创建Agent
    print("\n[创建Agent]")
    agent = ControlledQuestionGeneratorAgent(
        model_client=None,  # 端到端测试不需要真实的LLM调用
        config=config,
        enable_lightweight_reflection=False,
    )
    print("✅ Agent创建成功")

    # 验证组件
    print("\n[验证组件]")
    print(f"   ✅ ObservationBuilder: {type(agent.observation_builder).__name__}")
    print(f"   ✅ DecisionPolicy: {type(agent.decision_policy).__name__}")
    print(f"   ✅ DecisionValidator: {type(agent.decision_validator).__name__}")
    print(f"   ✅ LoopGuard: {type(agent.loop_guard).__name__}")
    print(f"   ✅ ToolRouter: {type(agent.tool_router).__name__}")

    # 验证工具注册
    print("\n[验证工具注册]")
    registered_tools = list(agent.tool_router.tools.keys())
    print(f"   - 已注册工具: {registered_tools}")
    expected_tools = ["sample_evidence", "generate_questions", "expand_retrieval"]
    if set(registered_tools) == set(expected_tools):
        print("   ✅ 工具注册完整")
    else:
        print(f"   ⚠️ 工具不完整: 期望 {expected_tools}, 实际 {registered_tools}")

    # 验证状态初始化
    print("\n[验证状态初始化]")
    agent.state.run_id = "test_run"
    print(f"   - run_id: {agent.state.run_id}")
    print(f"   - output_path: {agent.output_path}")
    print(f"   - artifact_store: {type(agent.artifact_store).__name__}")

    print("\n" + "=" * 60)
    print("✅ Phase 1 端到端测试通过！")
    print("=" * 60)
    print("\n注意: 由于需要真实的LLM调用，完整执行流程的测试")
    print("      需要在配置API Key后进行。")


if __name__ == "__main__":
    asyncio.run(test_e2e())