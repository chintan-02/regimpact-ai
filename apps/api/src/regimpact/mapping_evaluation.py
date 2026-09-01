"""Deterministic mapping-ranking evaluation kept separate from extraction evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class MappingEvaluationRow(TypedDict):
    expected_control_keys: list[str]
    candidate_control_keys: list[str]
    ambiguous: bool
    requires_review: bool


@dataclass(frozen=True)
class MappingMetrics:
    candidate_recall_at_k: float
    precision_at_k: float
    mean_reciprocal_rank: float
    coverage_rate: float
    ambiguity_rate: float
    unmapped_accuracy: float
    review_workload: float


def evaluate(rows: list[MappingEvaluationRow], top_k: int = 3) -> MappingMetrics:
    if not rows or top_k < 1:
        raise ValueError("evaluation requires rows and a positive top_k")
    mapped = [row for row in rows if row["expected_control_keys"]]
    recalls: list[float] = []
    precisions: list[float] = []
    reciprocal_ranks: list[float] = []
    covered = ambiguous = review = unmapped_correct = 0
    for row in rows:
        expected = set(row["expected_control_keys"])
        candidates = row["candidate_control_keys"][:top_k]
        if candidates:
            covered += 1
        if row["ambiguous"]:
            ambiguous += 1
        if row["requires_review"]:
            review += 1
        if not expected:
            unmapped_correct += int(not candidates)
            continue
        hits = expected.intersection(candidates)
        recalls.append(len(hits) / len(expected))
        precisions.append(len(hits) / top_k)
        reciprocal_ranks.append(
            next((1 / rank for rank, key in enumerate(candidates, 1) if key in expected), 0.0)
        )
    unmapped = len(rows) - len(mapped)
    return MappingMetrics(
        candidate_recall_at_k=sum(recalls) / len(recalls) if recalls else 0,
        precision_at_k=sum(precisions) / len(precisions) if precisions else 0,
        mean_reciprocal_rank=sum(reciprocal_ranks) / len(reciprocal_ranks)
        if reciprocal_ranks
        else 0,
        coverage_rate=covered / len(rows),
        ambiguity_rate=ambiguous / len(rows),
        unmapped_accuracy=unmapped_correct / unmapped if unmapped else 1,
        review_workload=review / len(rows),
    )
