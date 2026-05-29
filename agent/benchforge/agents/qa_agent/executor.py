"""Execution logic: round execution, state update, stop conditions."""

from typing import Any

from loguru import logger

from .state import GlobalState, ModeState, ModeRoundPlan
from .planner import mode_candidate_target, mode_initial_breadth_not_done
from .sampling import sample_chunks, raw_chunk_ids, record_global_chunk_usage


def normalize_difficulty(value: Any) -> str:
    if not value:
        return "medium"
    v = str(value).lower().strip()
    if v in ("easy", "simple", "low"):
        return "easy"
    if v in ("hard", "difficult", "advanced", "high"):
        return "hard"
    # numeric: 1-3 easy, 4-7 medium, 8-10 hard
    try:
        n = float(v)
        if n <= 3:
            return "easy"
        if n <= 7:
            return "medium"
        return "hard"
    except ValueError:
        return "medium"


def parse_questions(raw_output: Any) -> list[dict]:
    if isinstance(raw_output, list):
        return raw_output
    from benchforge.utils.filter import parse_llm_response
    try:
        return parse_llm_response(raw_output) or []
    except Exception:
        return []


def update_mode_state(
    mode_state: ModeState,
    topic: str,
    round_plan: ModeRoundPlan,
    parsed_questions: list[dict],
) -> None:
    for q in parsed_questions:
        mode_state.candidate_questions.append(q)
        # Track requested difficulty so planner gap is based on what was asked, not LLM self-rating
        mode_state.difficulty_counts[round_plan.difficulty] = (
            mode_state.difficulty_counts.get(round_plan.difficulty, 0) + 1
        )
        mode_state.topic_counts[topic] = mode_state.topic_counts.get(topic, 0) + 1


def update_mode_trace(
    mode_state: ModeState,
    round_plan: ModeRoundPlan,
    round_results: list[dict],
) -> None:
    mode_state.trace.append({
        "mode": round_plan.mode,
        "round_in_mode": round_plan.round_in_mode,
        "strategy": round_plan.strategy,
        "difficulty": round_plan.difficulty,
        "topics": list(round_plan.topics),
        "single_k": round_plan.single_k,
        "multi_k": round_plan.multi_k,
        "target_candidates_per_topic": round_plan.target_candidates_per_topic,
        "results": round_results,
    })


def mode_should_stop(
    mode_cfg: Any,
    mode_state: ModeState,
    global_state: GlobalState,
    blueprint: Any,
    config: Any,
) -> tuple[bool, str | None]:
    """Pure predicate — no side effects. Caller sets mode_state.stopped_reason."""
    initial_done = not mode_initial_breadth_not_done(mode_state, blueprint)
    target = mode_candidate_target(mode_cfg, config)

    if initial_done and len(mode_state.candidate_questions) >= target:
        return True, "candidate_pool_sufficient"

    if mode_state.round_in_mode > mode_cfg.max_rounds:
        return True, "max_rounds_reached"

    if mode_state.consecutive_empty_rounds >= config.runtime.max_consecutive_empty_rounds_per_mode:
        return True, "consecutive_empty_rounds_reached"

    if mode_state.failures_count >= config.runtime.max_failures_per_mode:
        return True, "mode_failure_limit_reached"

    return False, None


async def execute_mode_round_plan(
    round_plan: ModeRoundPlan,
    blueprint: Any,
    config: Any,
    global_state: GlobalState,
    mode_state: ModeState,
    evidence_manager: Any,
    generator: Any,
) -> list[dict]:
    round_results = []

    for topic in round_plan.topics:
        result: dict
        try:
            chunks, duplicate_combination = sample_chunks(
                evidence_manager=evidence_manager,
                topic=topic,
                mode=round_plan.mode,
                difficulty=round_plan.difficulty,
                single_k=round_plan.single_k,
                multi_k=round_plan.multi_k,
                global_used_combinations=global_state.used_chunk_combinations,
                global_chunk_usage_counts=global_state.chunk_usage_counts,
                round_num=mode_state.round_in_mode,
            )

            evidence_pool = evidence_manager.evidence_pools.get(topic)
            batch = _make_batch(topic, round_plan, chunks, evidence_pool)
            document_summary = evidence_manager.get_document_summary(batch, evidence_pool) if evidence_pool else ""

            raw_items, _ = await generator.generate(
                batch=batch,
                model_client=evidence_manager.model_client,
                evidence_pool=evidence_pool,
                document_summary=document_summary,
                language=blueprint.language,
            )

            parsed_questions = parse_questions(raw_items)

            # Inject chunk provenance into every question for downstream citation verification.
            # Mirrors YourBench prepared_lighteval: chunk_ids + chunks (texts) on each row.
            chunk_id_list = raw_chunk_ids(chunks)
            chunk_text_map = {
                u.chunk_id: getattr(u, "text", "")
                for u in chunks if hasattr(u, "chunk_id")
            }
            for q in parsed_questions:
                q["chunk_ids"] = chunk_id_list
                q["chunks"] = [chunk_text_map.get(cid, "") for cid in chunk_id_list]
                q["topic"] = topic

            update_mode_state(
                mode_state=mode_state,
                topic=topic,
                round_plan=round_plan,
                parsed_questions=parsed_questions,
            )

            # Record chunk usage regardless of whether parsed_questions is empty.
            record_global_chunk_usage(
                global_state=global_state,
                chunks=chunks,
                max_size=config.runtime.max_used_chunk_combinations,
            )

            result = {
                "topic": topic,
                "success": True,
                "generated_count": len(parsed_questions),
                "chunks": raw_chunk_ids(chunks),
                "duplicate_combination": duplicate_combination,
                "error": None,
            }

        except Exception as exc:
            mode_state.failures_count += 1
            global_state.global_failures += 1
            mode_state.failures.append({
                "mode": round_plan.mode,
                "round_in_mode": round_plan.round_in_mode,
                "topic": topic,
                "difficulty": round_plan.difficulty,
                "error": str(exc),
                "error_type": exc.__class__.__name__,
            })
            logger.warning(f"Topic {topic} failed in round {round_plan.round_in_mode}: {exc}")
            result = {
                "topic": topic,
                "success": False,
                "generated_count": 0,
                "chunks": [],
                "duplicate_combination": False,
                "error": str(exc),
                "error_type": exc.__class__.__name__,
            }

        finally:
            if round_plan.strategy == "initial_breadth":
                mode_state.initial_coverage.add(topic)

        round_results.append(result)

    return round_results


def _make_batch(topic: str, round_plan: ModeRoundPlan, chunks: list, evidence_pool: Any) -> Any:
    """Build a GenerationBatch from sampled chunks."""
    from benchforge.schemas import GenerationBatch

    single_ids = [u.chunk_id for u in chunks if hasattr(u, "chunk_id") and not hasattr(u, "unit_id")]
    multi_ids = [u.unit_id for u in chunks if hasattr(u, "unit_id")]

    return GenerationBatch(
        topic=topic,
        target_mode=round_plan.mode,
        target_difficulty=round_plan.difficulty,
        remaining_count=round_plan.target_candidates_per_topic,
        single_chunk_ids=single_ids,
        multi_chunk_ids=multi_ids,
        prompt_template_id=(
            "mcq_generation_v1" if round_plan.mode == "multiple_choice" else "qa_generation_v1"
        ),
        requested_min_questions=round_plan.target_candidates_per_topic,
        requested_target_questions=round_plan.target_candidates_per_topic,
    )
