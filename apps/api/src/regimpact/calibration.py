"""Versioned confidence calibration and review-routing policy."""

from __future__ import annotations

from dataclasses import dataclass

POLICY_ID = "obligation-calibration-v1"
DATASET_ID = "curated-regulatory-sentences-v1"
DATASET_SIZE = 24
CALIBRATION_CANDIDATE_COUNT = 18


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    upper_bound: float
    calibrated_confidence: float
    training_count: int


@dataclass(frozen=True, slots=True)
class CalibrationPolicy:
    policy_id: str
    dataset_id: str
    dataset_size: int
    calibration_candidate_count: int
    review_threshold: float
    minimum_precision: float
    bins: tuple[CalibrationBin, ...]

    def calibrate(self, raw_confidence: float) -> float:
        if not 0 <= raw_confidence <= 1:
            raise ValueError("raw confidence must be between zero and one")
        for item in self.bins:
            if raw_confidence <= item.upper_bound:
                return item.calibrated_confidence
        return self.bins[-1].calibrated_confidence

    def requires_review(self, calibrated_confidence: float) -> bool:
        return calibrated_confidence < self.review_threshold


def select_precision_threshold(
    observations: tuple[tuple[float, bool], ...], *, minimum_precision: float
) -> float:
    """Choose the lowest observed threshold meeting a precision constraint."""
    if not observations:
        raise ValueError("at least one calibration observation is required")
    qualifying: list[float] = []
    for threshold in sorted({score for score, _ in observations}):
        selected = [label for score, label in observations if score >= threshold]
        if selected and sum(selected) / len(selected) >= minimum_precision:
            qualifying.append(threshold)
    if not qualifying:
        raise ValueError("no threshold satisfies the minimum precision")
    return min(qualifying)


def calibration_metrics(observations: tuple[tuple[float, bool], ...]) -> tuple[float, float]:
    """Return Brier score and exact-score expected calibration error."""
    if not observations:
        raise ValueError("at least one calibration observation is required")
    brier = sum((score - float(label)) ** 2 for score, label in observations) / len(observations)
    ece = 0.0
    for score in {item[0] for item in observations}:
        labels = [label for candidate_score, label in observations if candidate_score == score]
        ece += len(labels) / len(observations) * abs(sum(labels) / len(labels) - score)
    return round(brier, 4), round(ece, 4)


CURRENT_POLICY = CalibrationPolicy(
    policy_id=POLICY_ID,
    dataset_id=DATASET_ID,
    dataset_size=DATASET_SIZE,
    calibration_candidate_count=CALIBRATION_CANDIDATE_COUNT,
    review_threshold=0.80,
    minimum_precision=0.90,
    bins=(
        CalibrationBin(0.819, 0.727, 9),
        CalibrationBin(0.869, 0.800, 3),
        CalibrationBin(1.0, 0.875, 6),
    ),
)
