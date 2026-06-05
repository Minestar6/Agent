"""citation_score 数据集级指标。"""

from typing import Any

from .base import DatasetMetric


def resolve_citation_score(question: dict[str, Any]) -> float | None:
    if "citation_score" in question:
        val = question["citation_score"]
        if val is not None:
            return float(val)

    for key in ("citation_validation", "validation_result"):
        obj = question.get(key)
        if isinstance(obj, dict):
            for field in ("score", "citation_score"):
                if field in obj and obj[field] is not None:
                    return float(obj[field])

    return None


class CitationScoreMetric(DatasetMetric):
    name = "citation_score"

    def compute(
        self,
        questions: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        threshold = (context or {}).get("threshold")
        scored: list[tuple[str, float]] = []
        missing_ids: list[str] = []

        for q in questions:
            qid = q.get("question_id", "")
            score = resolve_citation_score(q)
            if score is not None:
                scored.append((qid, score))
            else:
                missing_ids.append(qid)

        if not scored:
            return {
                "type": "dataset_metric",
                "metric_name": self.name,
                "threshold": threshold,
                "question_ids": [],
                "scores": [],
                "passed": [],
                "mean": None,
                "pass_rate": None,
                "num_scored": 0,
                "num_missing": len(missing_ids),
            }

        ids = [s[0] for s in scored]
        scores = [s[1] for s in scored]
        mean = sum(scores) / len(scores)
        passed = [s >= threshold for s in scores] if threshold is not None else [None] * len(scores)
        pass_rate = sum(passed) / len(passed) if threshold is not None else None

        return {
            "type": "dataset_metric",
            "metric_name": self.name,
            "threshold": threshold,
            "question_ids": ids,
            "scores": scores,
            "passed": passed,
            "mean": mean,
            "pass_rate": pass_rate,
            "num_scored": len(scored),
            "num_missing": len(missing_ids),
        }

    def compute_by_group(
        self,
        questions: list[dict[str, Any]],
        group_key: str,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for q in questions:
            group_value = str(q.get(group_key, "unknown"))
            groups.setdefault(group_value, []).append(q)

        results: list[dict[str, Any]] = []
        for group_value, group_questions in groups.items():
            record = self.compute(group_questions, context)
            record["scope"] = group_key
            record["group_value"] = group_value
            record["num_questions"] = len(group_questions)
            results.append(record)
        return results
