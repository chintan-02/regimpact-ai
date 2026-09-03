"""Dependency-free evaluation, calibration, and selective-classification metrics."""

from __future__ import annotations

from dataclasses import dataclass

from .clause_classifier import ClauseLabel


@dataclass(frozen=True, slots=True)
class ScoredPrediction:
    expected: ClauseLabel
    predicted: ClauseLabel
    confidence: float


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    macro_f1: float
    per_class: dict[ClauseLabel, dict[str, float]]
    accuracy: float
    expected_calibration_error: float
    confidence_threshold: float
    coverage: float
    covered_accuracy: float


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def expected_calibration_error(
    predictions: tuple[ScoredPrediction, ...], *, bins: int = 10
) -> float:
    if not predictions:
        raise ValueError("predictions must not be empty")
    total = len(predictions)
    error = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        members = tuple(
            item
            for item in predictions
            if lower <= item.confidence <= upper and (index == bins - 1 or item.confidence < upper)
        )
        if not members:
            continue
        accuracy = sum(item.expected == item.predicted for item in members) / len(members)
        confidence = sum(item.confidence for item in members) / len(members)
        error += len(members) / total * abs(accuracy - confidence)
    return error


def evaluate(
    predictions: tuple[ScoredPrediction, ...],
    *,
    confidence_threshold: float,
) -> EvaluationReport:
    if not predictions:
        raise ValueError("predictions must not be empty")
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence_threshold must be between zero and one")
    labels = tuple(ClauseLabel)
    per_class: dict[ClauseLabel, dict[str, float]] = {}
    f1_values: list[float] = []
    for label in labels:
        tp = sum(item.expected == label and item.predicted == label for item in predictions)
        fp = sum(item.expected != label and item.predicted == label for item in predictions)
        fn = sum(item.expected == label and item.predicted != label for item in predictions)
        precision = _safe_divide(tp, tp + fp)
        recall = _safe_divide(tp, tp + fn)
        f1 = _safe_divide(2 * precision * recall, precision + recall)
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": float(tp + fn)}
        f1_values.append(f1)
    correct = sum(item.expected == item.predicted for item in predictions)
    covered = tuple(item for item in predictions if item.confidence >= confidence_threshold)
    covered_correct = sum(item.expected == item.predicted for item in covered)
    return EvaluationReport(
        macro_f1=sum(f1_values) / len(f1_values),
        per_class=per_class,
        accuracy=correct / len(predictions),
        expected_calibration_error=expected_calibration_error(predictions),
        confidence_threshold=confidence_threshold,
        coverage=len(covered) / len(predictions),
        covered_accuracy=_safe_divide(covered_correct, len(covered)),
    )


def select_abstention_threshold(
    predictions: tuple[ScoredPrediction, ...],
    *,
    minimum_covered_accuracy: float,
    minimum_coverage: float,
) -> float:
    """Choose the lowest observed threshold satisfying accuracy and coverage constraints."""
    candidates = sorted({item.confidence for item in predictions})
    for threshold in candidates:
        report = evaluate(predictions, confidence_threshold=threshold)
        if report.covered_accuracy >= minimum_covered_accuracy and report.coverage >= minimum_coverage:
            return threshold
    raise ValueError("no confidence threshold satisfies the selective-classification policy")
