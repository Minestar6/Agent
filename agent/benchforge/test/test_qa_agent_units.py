"""Unit tests for qa_agent modules."""

import sys
from pathlib import Path
from dataclasses import field

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from benchforge.agents.qa_agent.schema import (
    Blueprint, ModeCfg, AgentConfig,
    CandidatePoolConfig, InitialBreadthConfig, PlannerConfig,
    ChunkMixConfig, ChunkMixDifficulty, ModeAdjustment,
    GenerationYield, ChunkLimitsForMode, ChunkKLimit, RuntimeConfig,
)
from benchforge.agents.qa_agent.state import GlobalState, ModeState
from benchforge.agents.qa_agent.planner import (
    resolve_chunk_mix, compute_dynamic_chunk_k,
    choose_difficulty_for_mode, build_mode_round_plan,
    mode_candidate_target, mode_initial_breadth_not_done,
)
from benchforge.agents.qa_agent.executor import (
    normalize_difficulty, parse_questions, mode_should_stop,
)
from benchforge.agents.qa_agent.sampling import raw_chunk_ids, record_global_chunk_usage


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _blueprint(topics=None, qa_count=10, mcq_count=8):
    return Blueprint(
        task_id="test", run_id="r1", language="en",
        topics=topics or ["Topic A", "Topic B", "Topic C"],
        modes={
            "qa": ModeCfg(count=qa_count, max_rounds=5,
                          difficulty_distribution={"easy": 0.3, "medium": 0.4, "hard": 0.3}),
            "multiple_choice": ModeCfg(count=mcq_count, max_rounds=5,
                                       difficulty_distribution={"easy": 0.3, "medium": 0.4, "hard": 0.3}),
        },
    )


def _config():
    return AgentConfig(
        candidate_pool=CandidatePoolConfig(target_multiplier=2.0),
        initial_breadth=InitialBreadthConfig(enabled=True, max_topics_per_round=10, difficulty="medium"),
        planner=PlannerConfig(topics_per_round=2),
        chunk_mix=ChunkMixConfig(
            by_difficulty={
                "easy":   ChunkMixDifficulty(single_ratio=0.8, multi_ratio=0.2),
                "medium": ChunkMixDifficulty(single_ratio=0.5, multi_ratio=0.5),
                "hard":   ChunkMixDifficulty(single_ratio=0.2, multi_ratio=0.8),
            },
            mode_adjustment={
                "qa":              ModeAdjustment(single_delta=0.1),
                "multiple_choice": ModeAdjustment(single_delta=-0.1),
            },
        ),
        generation_yield={
            "qa":              GenerationYield(single_chunk_avg_questions=2.0, multi_chunk_avg_questions=3.0),
            "multiple_choice": GenerationYield(single_chunk_avg_questions=1.5, multi_chunk_avg_questions=2.0),
        },
        chunk_limits={
            "qa": ChunkLimitsForMode(single_k=ChunkKLimit(min=1, max=4), multi_k=ChunkKLimit(min=0, max=3)),
            "multiple_choice": ChunkLimitsForMode(single_k=ChunkKLimit(min=0, max=3), multi_k=ChunkKLimit(min=1, max=4)),
        },
        runtime=RuntimeConfig(
            max_consecutive_empty_rounds_per_mode=3,
            max_failures_per_mode=5,
            max_used_chunk_combinations=100,
        ),
    )


# ── normalize_difficulty ───────────────────────────────────────────────────────

def test_normalize_difficulty():
    assert normalize_difficulty("easy") == "easy"
    assert normalize_difficulty("HARD") == "hard"
    assert normalize_difficulty("simple") == "easy"
    assert normalize_difficulty("advanced") == "hard"
    assert normalize_difficulty("medium") == "medium"
    assert normalize_difficulty(None) == "medium"
    assert normalize_difficulty("unknown") == "medium"
    print("PASS test_normalize_difficulty")


# ── parse_questions ────────────────────────────────────────────────────────────

def test_parse_questions_list():
    items = [{"question": "Q1", "answer": "A1"}]
    assert parse_questions(items) == items
    print("PASS test_parse_questions_list")


def test_parse_questions_empty():
    assert parse_questions([]) == []
    assert parse_questions("") == []
    print("PASS test_parse_questions_empty")


# ── resolve_chunk_mix ──────────────────────────────────────────────────────────

def test_resolve_chunk_mix_sums_to_one():
    cfg = _config()
    for diff in ("easy", "medium", "hard"):
        s, m = resolve_chunk_mix("qa", diff, cfg)
        assert abs(s + m - 1.0) < 1e-9, f"sum != 1 for {diff}"
    print("PASS test_resolve_chunk_mix_sums_to_one")


def test_resolve_chunk_mix_mode_adjustment():
    cfg = _config()
    s_qa, _ = resolve_chunk_mix("qa", "medium", cfg)
    s_mcq, _ = resolve_chunk_mix("multiple_choice", "medium", cfg)
    assert s_qa > s_mcq, "qa should have higher single_ratio than mcq"
    print("PASS test_resolve_chunk_mix_mode_adjustment")


def test_resolve_chunk_mix_clamped():
    cfg = _config()
    # easy + qa delta=0.1 => 0.8+0.1=0.9, still <=1
    s, m = resolve_chunk_mix("qa", "easy", cfg)
    assert 0.0 <= s <= 1.0 and 0.0 <= m <= 1.0
    print("PASS test_resolve_chunk_mix_clamped")


# ── mode_candidate_target ──────────────────────────────────────────────────────

def test_mode_candidate_target():
    bp = _blueprint(qa_count=10)
    cfg = _config()
    target = mode_candidate_target(bp.modes["qa"], cfg)
    assert target == 20  # ceil(10 * 2.0)
    print("PASS test_mode_candidate_target")


# ── mode_initial_breadth_not_done ─────────────────────────────────────────────

def test_initial_breadth_not_done():
    bp = _blueprint()
    ms = ModeState(mode="qa")
    assert mode_initial_breadth_not_done(ms, bp) is True
    ms.initial_coverage = set(bp.topics)
    assert mode_initial_breadth_not_done(ms, bp) is False
    print("PASS test_initial_breadth_not_done")


# ── choose_difficulty_for_mode ────────────────────────────────────────────────

def test_choose_difficulty_targets_deficit():
    bp = _blueprint()
    cfg = _config()
    ms = ModeState(mode="qa")
    # No questions yet — should pick the difficulty with highest target ratio
    diff = choose_difficulty_for_mode(bp.modes["qa"], ms)
    assert diff in ("easy", "medium", "hard")
    # Fill up easy and medium, hard should be chosen
    ms.candidate_questions = [{}] * 10
    ms.difficulty_counts = {"easy": 4, "medium": 5, "hard": 0}
    diff = choose_difficulty_for_mode(bp.modes["qa"], ms)
    assert diff == "hard"
    print("PASS test_choose_difficulty_targets_deficit")


# ── compute_dynamic_chunk_k ───────────────────────────────────────────────────

def test_compute_dynamic_chunk_k_respects_limits():
    bp = _blueprint(qa_count=10)
    cfg = _config()
    ms = ModeState(mode="qa")
    single_k, multi_k, _ = compute_dynamic_chunk_k(
        mode="qa", mode_cfg=bp.modes["qa"], difficulty="medium",
        selected_topic_count=2, mode_state=ms, blueprint=bp, config=cfg,
    )
    limits = cfg.chunk_limits["qa"]
    assert limits.single_k.min <= single_k <= limits.single_k.max
    assert limits.multi_k.min <= multi_k <= limits.multi_k.max
    print("PASS test_compute_dynamic_chunk_k_respects_limits")


# ── mode_should_stop ──────────────────────────────────────────────────────────

def test_stop_candidate_pool_sufficient():
    bp = _blueprint(qa_count=5)
    cfg = _config()
    ms = ModeState(mode="qa")
    ms.initial_coverage = set(bp.topics)
    ms.candidate_questions = [{}] * 10  # >= target=10
    stop, reason = mode_should_stop(bp.modes["qa"], ms, GlobalState(), bp, cfg)
    assert stop and reason == "candidate_pool_sufficient"
    print("PASS test_stop_candidate_pool_sufficient")


def test_stop_max_rounds():
    bp = _blueprint()
    cfg = _config()
    ms = ModeState(mode="qa")
    ms.round_in_mode = 6  # > max_rounds=5
    stop, reason = mode_should_stop(bp.modes["qa"], ms, GlobalState(), bp, cfg)
    assert stop and reason == "max_rounds_reached"
    print("PASS test_stop_max_rounds")


def test_stop_consecutive_empty():
    bp = _blueprint()
    cfg = _config()
    ms = ModeState(mode="qa")
    ms.consecutive_empty_rounds = 3  # >= max=3
    stop, reason = mode_should_stop(bp.modes["qa"], ms, GlobalState(), bp, cfg)
    assert stop and reason == "consecutive_empty_rounds_reached"
    print("PASS test_stop_consecutive_empty")


def test_no_stop_initial_breadth_incomplete():
    bp = _blueprint(qa_count=1)
    cfg = _config()
    ms = ModeState(mode="qa")
    # candidate_questions >= target but initial breadth not done
    ms.candidate_questions = [{}] * 10
    stop, _ = mode_should_stop(bp.modes["qa"], ms, GlobalState(), bp, cfg)
    assert not stop
    print("PASS test_no_stop_initial_breadth_incomplete")


# ── raw_chunk_ids ─────────────────────────────────────────────────────────────

def test_raw_chunk_ids_single():
    from types import SimpleNamespace
    units = [SimpleNamespace(chunk_id="doc_a::chunk_0"), SimpleNamespace(chunk_id="doc_a::chunk_1")]
    ids = raw_chunk_ids(units)
    assert ids == ["doc_a::chunk_0", "doc_a::chunk_1"]
    print("PASS test_raw_chunk_ids_single")


def test_raw_chunk_ids_multi():
    from types import SimpleNamespace
    unit = SimpleNamespace(raw_chunk_ids=["doc_a::chunk_0", "doc_b::chunk_0"])
    ids = raw_chunk_ids([unit])
    assert "doc_a::chunk_0" in ids and "doc_b::chunk_0" in ids
    print("PASS test_raw_chunk_ids_multi")


# ── record_global_chunk_usage ─────────────────────────────────────────────────

def test_record_global_chunk_usage_eviction():
    from types import SimpleNamespace
    gs = GlobalState()
    for i in range(5):
        units = [SimpleNamespace(chunk_id=f"doc::chunk_{i}")]
        record_global_chunk_usage(gs, units, max_size=3)
    assert len(gs.used_chunk_combinations) <= 3
    print("PASS test_record_global_chunk_usage_eviction")


# ── build_mode_round_plan ─────────────────────────────────────────────────────

def test_build_initial_breadth_plan():
    bp = _blueprint()
    cfg = _config()
    ms = ModeState(mode="qa")
    plan = build_mode_round_plan("qa", bp.modes["qa"], bp, cfg, ms)
    assert plan.strategy == "initial_breadth"
    assert len(plan.topics) > 0
    assert all(t in bp.topics for t in plan.topics)
    print("PASS test_build_initial_breadth_plan")


def test_build_adaptive_plan_after_breadth():
    bp = _blueprint()
    cfg = _config()
    ms = ModeState(mode="qa")
    ms.initial_coverage = set(bp.topics)
    plan = build_mode_round_plan("qa", bp.modes["qa"], bp, cfg, ms)
    assert plan.strategy == "adaptive"
    assert len(plan.topics) <= cfg.planner.topics_per_round
    print("PASS test_build_adaptive_plan_after_breadth")


# ── config_loader ─────────────────────────────────────────────────────────────

def test_load_qa_agent_config():
    from benchforge.agents.qa_agent.config_loader import load_qa_agent_config
    blueprint, agent_config, model_cfg = load_qa_agent_config(
        project_root / "benchforge/config/qa_agent.yaml"
    )
    assert blueprint.task_id
    assert blueprint.topics
    assert "qa" in blueprint.modes
    assert agent_config.candidate_pool.target_multiplier > 0
    assert "api_key" in model_cfg
    print("PASS test_load_qa_agent_config")


# ── runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_normalize_difficulty,
        test_parse_questions_list,
        test_parse_questions_empty,
        test_resolve_chunk_mix_sums_to_one,
        test_resolve_chunk_mix_mode_adjustment,
        test_resolve_chunk_mix_clamped,
        test_mode_candidate_target,
        test_initial_breadth_not_done,
        test_choose_difficulty_targets_deficit,
        test_compute_dynamic_chunk_k_respects_limits,
        test_stop_candidate_pool_sufficient,
        test_stop_max_rounds,
        test_stop_consecutive_empty,
        test_no_stop_initial_breadth_incomplete,
        test_raw_chunk_ids_single,
        test_raw_chunk_ids_multi,
        test_record_global_chunk_usage_eviction,
        test_build_initial_breadth_plan,
        test_build_adaptive_plan_after_breadth,
        test_load_qa_agent_config,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
