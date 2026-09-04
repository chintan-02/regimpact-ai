"""Fail-closed runtime adapter for promoted transformer clause classifiers."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from .clause_classifier import (
    ClauseLabel,
    ClausePrediction,
    ModelManifest,
    PromotionPolicy,
)


class UnpromotedModelError(RuntimeError):
    pass


def load_manifest(path: Path) -> ModelManifest:
    value = json.loads(path.read_text(encoding="utf-8"))
    return ModelManifest(
        model_id=value["model_id"],
        base_model=value["base_model"],
        dataset_id=value["dataset_id"],
        dataset_sha256=value["dataset_sha256"],
        labels=tuple(ClauseLabel(item) for item in value["labels"]),
        confidence_threshold=float(value["confidence_threshold"]),
        temperature=float(value["temperature"]),
        example_count=int(value["example_count"]),
        document_count=int(value["document_count"]),
        regulator_count=int(value["regulator_count"]),
        macro_f1=float(value["macro_f1"]),
        per_class_f1={
            ClauseLabel(label): float(score)
            for label, score in value["per_class_f1"].items()
        },
        covered_accuracy=float(value["covered_accuracy"]),
        expected_calibration_error=float(value["expected_calibration_error"]),
        coverage=float(value["coverage"]),
    )


class TransformerClauseClassifier:
    """Load only an artifact whose manifest passes the model-promotion policy."""

    def __init__(
        self,
        artifact_dir: Path,
        *,
        policy: PromotionPolicy | None = None,
        pipeline_factory: Any | None = None,
    ) -> None:
        self.manifest = load_manifest(artifact_dir / "manifest.json")
        failures = self.manifest.promotion_failures(policy)
        if failures:
            raise UnpromotedModelError("model failed promotion gates: " + ", ".join(failures))
        from .classifier_training_governance import verify_promotion_receipt

        try:
            verify_promotion_receipt(artifact_dir)
        except RuntimeError as exc:
            raise UnpromotedModelError(str(exc)) from exc
        if pipeline_factory is None:
            try:
                from transformers import pipeline  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError("install the 'ml' extra to serve a transformer model") from exc
            pipeline_factory = pipeline
        self._pipeline = pipeline_factory(
            "text-classification",
            model=str(artifact_dir),
            tokenizer=str(artifact_dir),
            top_k=None,
        )
        self.model_id = self.manifest.model_id
        self.dataset_id = self.manifest.dataset_id
        self.dataset_sha256 = self.manifest.dataset_sha256

    def predict(self, text: str) -> ClausePrediction:
        if not text.strip():
            raise ValueError("clause text must not be empty")
        raw = self._pipeline(text, truncation=True)
        scores = raw[0] if raw and isinstance(raw[0], list) else raw
        uncalibrated = {
            ClauseLabel(item["label"]): float(item["score"])
            for item in scores
        }
        scaled = {
            label: math.exp(math.log(max(score, 1e-12)) / self.manifest.temperature)
            for label, score in uncalibrated.items()
        }
        total = sum(scaled.values())
        probabilities = {label: score / total for label, score in scaled.items()}
        label, confidence = max(probabilities.items(), key=lambda item: item[1])
        return ClausePrediction(
            label=label,
            confidence=confidence,
            abstained=confidence < self.manifest.confidence_threshold,
            model_id=self.model_id,
            dataset_id=self.dataset_id,
            probabilities=probabilities,
        )


@lru_cache(maxsize=4)
def load_promoted_classifier(artifact_dir: str) -> TransformerClauseClassifier:
    """Cache immutable model artifacts so requests do not reload transformer weights."""
    return TransformerClauseClassifier(Path(artifact_dir))
