"""Load qa_agent.yaml into Blueprint and AgentConfig dataclasses."""

import os
import re
from pathlib import Path
from typing import Any

import yaml

from benchforge.agents.qa_agent.schema import (
    Blueprint, ModeCfg, AgentConfig,
    CandidatePoolConfig, InitialBreadthConfig, PlannerConfig,
    ChunkMixConfig, ChunkMixDifficulty, ModeAdjustment,
    GenerationYield, ChunkLimitsForMode, ChunkKLimit, RuntimeConfig,
)


def _load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _expand(text: str) -> str:
    def _replace(m):
        expr = m.group(1)
        if ":" in expr:
            var, default = expr.split(":", 1)
            return os.getenv(var, default)
        return os.getenv(expr, "")
    return re.sub(r'\$\{([^}]+)\}', _replace, text)


def _expand_recursive(data: Any) -> Any:
    if isinstance(data, str):
        return _expand(data)
    if isinstance(data, dict):
        return {k: _expand_recursive(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_expand_recursive(i) for i in data]
    return data


def load_qa_agent_config(path: str | Path) -> tuple[Blueprint, AgentConfig, dict]:
    """Returns (blueprint, agent_config, model_cfg).

    model_cfg keys: api_key, base_url, model_name, temperature, max_tokens, max_retries.
    """
    path = Path(path)
    _load_dotenv(path.parent.parent.parent / ".env")  # project root .env

    with open(path, encoding="utf-8") as f:
        raw = _expand_recursive(yaml.safe_load(f))

    run = raw["run"]
    bp_raw = raw["blueprint"]

    blueprint = Blueprint(
        task_id=run["task_id"],
        run_id=run["run_id"],
        language=run["language"],
        topics=bp_raw["topics"],
        modes={
            mode: ModeCfg(
                count=cfg["count"],
                max_rounds=cfg["max_rounds"],
                difficulty_distribution=cfg["difficulty_distribution"],
            )
            for mode, cfg in bp_raw["modes"].items()
        },
    )

    cm = raw["chunk_mix"]
    agent_config = AgentConfig(
        candidate_pool=CandidatePoolConfig(**raw["candidate_pool"]),
        initial_breadth=InitialBreadthConfig(**raw["initial_breadth"]),
        planner=PlannerConfig(**raw["planner"]),
        chunk_mix=ChunkMixConfig(
            by_difficulty={
                d: ChunkMixDifficulty(**v)
                for d, v in cm["by_difficulty"].items()
            },
            mode_adjustment={
                m: ModeAdjustment(**v)
                for m, v in cm.get("mode_adjustment", {}).items()
            },
        ),
        generation_yield={
            m: GenerationYield(**v)
            for m, v in raw["generation_yield"].items()
        },
        chunk_limits={
            m: ChunkLimitsForMode(
                single_k=ChunkKLimit(**v["single_k"]),
                multi_k=ChunkKLimit(**v["multi_k"]),
            )
            for m, v in raw["chunk_limits"].items()
        },
        runtime=RuntimeConfig(**raw["runtime"]),
    )

    model_cfg = {k: str(v) for k, v in raw.get("model", {}).items()}

    return blueprint, agent_config, model_cfg
