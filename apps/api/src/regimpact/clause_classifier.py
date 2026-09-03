"""Contracts and safety policy for regulatory-clause classification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any, Protocol


class ClauseLabel(StrEnum):
    OBLIGATION = "obligation"
    PERMISSION = "permission"
    PROHIBITION = "prohibition"
    DEFINITION = "definition"
    REPORTING_REQUIREMENT = "reporting_requirement"
    RECORD_RETENTION_REQUIREMENT = "record_retention_requirement"
    NON_OBLIGATION = "non_obligation"


@dataclass(frozen=True, slots=True)
class LabelledClause:
    clause_id: str
    document_id: str
    regulator: str
    text: str
    label: ClauseLabel

    def __post_init__(self) -> None:
        if not all((self.clause_id.strip(), self.document_id.strip(), self.text.strip())):
            raise ValueError("clause_id, document_id, and text are required")


@dataclass(frozen=True, slots=True)
class ClausePrediction:
    label: ClauseLabel
    confidence: float
    abstained: bool
    model_id: str
    dataset_id: str
    probabilities: dict[ClauseLabel, float]

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        if self.probabilities:
            total = sum(self.probabilities.values())
            if abs(total - 1.0) > 1e-5:
                raise ValueError("class probabilities must sum to one")


class ClauseClassifier(Protocol):
    model_id: str
    dataset_id: str
    dataset_sha256: str

    def predict(self, text: str) -> ClausePrediction: ...


def training_recipe_fingerprint(recipe: dict[str, Any]) -> str:
    """Identify the complete deterministic training recipe used for lineage."""
    encoded = json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    """Minimum evidence required before a trained model may serve predictions."""

    minimum_examples: int = 500
    minimum_documents: int = 25
    minimum_regulators: int = 3
    minimum_macro_f1: float = 0.75
    minimum_per_class_f1: float = 0.55
    minimum_covered_accuracy: float = 0.85
    maximum_expected_calibration_error: float = 0.10
    minimum_coverage: float = 0.60


@dataclass(frozen=True, slots=True)
class ModelManifest:
    model_id: str
    base_model: str
    dataset_id: str
    dataset_sha256: str
    labels: tuple[ClauseLabel, ...]
    confidence_threshold: float
    temperature: float
    example_count: int
    document_count: int
    regulator_count: int
    macro_f1: float
    per_class_f1: dict[ClauseLabel, float]
    covered_accuracy: float
    expected_calibration_error: float
    coverage: float

    def __post_init__(self) -> None:
        if self.temperature <= 0:
            raise ValueError("temperature must be positive")
        bounded_metrics = {
            "confidence_threshold": self.confidence_threshold,
            "macro_f1": self.macro_f1,
            "covered_accuracy": self.covered_accuracy,
            "expected_calibration_error": self.expected_calibration_error,
            "coverage": self.coverage,
            **{
                f"per_class_f1.{label.value}": value
                for label, value in self.per_class_f1.items()
            },
        }
        for name, value in bounded_metrics.items():
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")

    def promotion_failures(self, policy: PromotionPolicy | None = None) -> tuple[str, ...]:
        policy = policy or PromotionPolicy()
        required_labels = set(ClauseLabel)
        checks = (
            (set(self.labels) == required_labels, "incomplete_label_taxonomy"),
            (self.example_count >= policy.minimum_examples, "insufficient_examples"),
            (self.document_count >= policy.minimum_documents, "insufficient_documents"),
            (self.regulator_count >= policy.minimum_regulators, "insufficient_regulators"),
            (self.macro_f1 >= policy.minimum_macro_f1, "macro_f1_below_gate"),
            (
                set(self.per_class_f1) == required_labels
                and all(
                    value >= policy.minimum_per_class_f1
                    for value in self.per_class_f1.values()
                ),
                "per_class_f1_below_gate",
            ),
            (
                self.covered_accuracy >= policy.minimum_covered_accuracy,
                "covered_accuracy_below_gate",
            ),
            (
                self.expected_calibration_error <= policy.maximum_expected_calibration_error,
                "calibration_error_above_gate",
            ),
            (self.coverage >= policy.minimum_coverage, "coverage_below_gate"),
        )
        return tuple(reason for passed, reason in checks if not passed)

    @property
    def promoted(self) -> bool:
        return not self.promotion_failures()


def dataset_fingerprint(rows: tuple[LabelledClause, ...]) -> str:
    """Return a stable fingerprint over ordered, normalized annotations."""
    payload = "\n".join(
        "|".join(
            (
                row.clause_id.strip(),
                row.document_id.strip(),
                row.regulator.strip(),
                " ".join(row.text.split()),
                row.label.value,
            )
        )
        for row in sorted(rows, key=lambda item: item.clause_id)
    )
    return sha256(payload.encode("utf-8")).hexdigest()
