"""Run the qa_agent pipeline end-to-end using qa_agent.yaml."""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from benchforge.config import QuestionGeneratorConfig
from benchforge.models import OpenAIClient
from benchforge.agents.question_generator.modules.evidence_manager import EvidenceManager
from benchforge.agents.question_generator.modules.generator import Generator
from benchforge.agents.qa_agent import run_generation_agent
from benchforge.agents.qa_agent.config_loader import load_qa_agent_config


async def main():
    blueprint, agent_config, model_cfg = load_qa_agent_config(
        project_root / "benchforge/config/qa_agent.yaml"
    )

    # 日志落盘
    log_path = Path("runs") / blueprint.task_id / blueprint.run_id / "run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(str(log_path), level="DEBUG", encoding="utf-8")

    sys_config = QuestionGeneratorConfig.from_yaml(
        project_root / "benchforge/config/question_generator_config.yaml",
        task_id=blueprint.task_id,
        run_id=blueprint.run_id,
    )

    client = OpenAIClient(
        api_key=model_cfg["api_key"],
        model_name=model_cfg["model_name"],
        base_url=model_cfg["base_url"],
    )

    report = await run_generation_agent(
        blueprint=blueprint,
        config=agent_config,
        evidence_manager=EvidenceManager(sys_config, client),
        generator=Generator(),
    )

    print(f"\n=== Generation Report ===")
    print(f"task_id : {report['task_id']}")
    print(f"run_id  : {report['run_id']}")
    for mode, s in report["modes"].items():
        print(f"  {mode}: {s['candidate_count']}/{s['target_candidate_count']} candidates  stopped={s['stopped_reason']}")
    print(f"total   : {report['total_candidates']} candidates")
    print(f"combos  : {report['global_used_chunk_combinations']} chunk combinations used")
    print(f"output  : runs/{report['task_id']}/{report['run_id']}/")
    print(f"log     : {log_path}")


if __name__ == "__main__":
    asyncio.run(main())
