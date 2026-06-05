"""model_eval_agent.yaml → dataclass 配置加载。"""

import os
import re
from pathlib import Path
from typing import Any

import yaml

from .schema import (
    AutoMetricSpec,
    DatasetEvaluationConfig,
    DatasetMetricSpec,
    JudgeConfig,
    JudgeMetricSpec,
    ModelEvalAgentConfig,
    ModelsConfig,
    QuestionModeMetricPlan,
    RunConfig,
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


def load_model_eval_config(path: str | Path) -> ModelEvalAgentConfig:
    path = Path(path)
    _load_dotenv(path.parent.parent.parent / ".env")

    with open(path, encoding="utf-8") as f:
        raw = _expand_recursive(yaml.safe_load(f))

    run_raw = raw.get("run", {})
    run = RunConfig(
        shared_state_path=run_raw.get("shared_state_path", "").strip(),
        task_id=run_raw.get("task_id", "").strip(),
        run_id=run_raw.get("run_id", "").strip(),
        input_paths=run_raw.get("input_paths", []),
        evaluation_session_id=run_raw.get("evaluation_session_id", "").strip(),
    )

    ds_raw = raw.get("dataset_evaluation", {})
    dataset_evaluation = DatasetEvaluationConfig(
        enabled=ds_raw.get("enabled", True),
        metrics=[
            DatasetMetricSpec(name=m["name"], threshold=m.get("threshold"))
            for m in ds_raw.get("metrics", [])
        ],
    )

    models_raw = raw.get("models", {})
    models = ModelsConfig(
        candidate_model_names=models_raw.get("candidate_model_names", []),
        judge_model_name=models_raw.get("judge_model_name"),
        generation_defaults=models_raw.get("generation_defaults", {}),
        judge_defaults=models_raw.get("judge_defaults", {}),
    )

    metrics: dict[str, QuestionModeMetricPlan] = {}
    for mode, plan_raw in raw.get("metrics", {}).items():
        metrics[mode] = QuestionModeMetricPlan(
            automatic_metrics=[
                AutoMetricSpec(name=m["name"], threshold=m.get("threshold"))
                for m in plan_raw.get("automatic_metrics", [])
            ],
            llm_judge_metrics=[
                JudgeMetricSpec(
                    name=m["name"],
                    description=m.get("description", ""),
                    direction=m.get("direction", "higher_is_better"),
                )
                for m in plan_raw.get("llm_judge_metrics", [])
            ],
        )

    judge_raw = raw.get("judge", {})
    judge = JudgeConfig(
        enabled=judge_raw.get("enabled", False),
        prompt_system=judge_raw.get("prompt_system", ""),
        prompt_user=judge_raw.get("prompt_user", ""),
    )

    return ModelEvalAgentConfig(
        run=run,
        dataset_evaluation=dataset_evaluation,
        models=models,
        metrics=metrics,
        judge=judge,
    )
