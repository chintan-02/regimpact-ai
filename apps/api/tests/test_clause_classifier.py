import json
from dataclasses import asdict
from pathlib import Path

import pytest

from regimpact.classifier_evaluation import (
    ScoredPrediction,
    evaluate,
    select_abstention_threshold,
)
from regimpact.classifier_runtime import TransformerClauseClassifier, UnpromotedModelError
from regimpact.clause_classifier import (
    ClauseLabel,
    ModelManifest,
)
from regimpact.clause_dataset import dataset_summary, load_jsonl, split_by_document
from regimpact.config import Settings

FIXTURE = Path(__file__).parent / "fixtures" / "clause_classifier_eval.jsonl"


def test_annotation_contract_and_dataset_fingerprint_are_stable():
    bundle = load_jsonl(FIXTURE, dataset_id="clause-types-eval-v1")
    summary = dataset_summary(bundle.rows)
    assert summary == {
        "examples": 14,
        "documents": 5,
        "regulators": 5,
        "labels": {
            "definition": 2,
            "non_obligation": 2,
            "obligation": 2,
            "permission": 2,
            "prohibition": 2,
            "record_retention_requirement": 2,
            "reporting_requirement": 2,
        },
    }
    assert len(bundle.sha256) == 64
    assert bundle.sha256 == load_jsonl(FIXTURE, dataset_id="ignored").sha256


def test_document_split_prevents_clause_leakage():
    bundle = load_jsonl(FIXTURE, dataset_id="clause-types-eval-v1")
    split = split_by_document(
        bundle.rows,
        seed="split-with-non-empty-partitions",
        train_percent=50,
        validation_percent=25,
    )
    train_documents = {row.document_id for row in split.train}
    validation_documents = {row.document_id for row in split.validation}
    test_documents = {row.document_id for row in split.test}
    assert train_documents.isdisjoint(validation_documents)
    assert train_documents.isdisjoint(test_documents)
    assert validation_documents.isdisjoint(test_documents)
    assert len(split.train) + len(split.validation) + len(split.test) == len(bundle.rows)


def test_duplicate_annotation_is_rejected(tmp_path):
    first = FIXTURE.read_text(encoding="utf-8").splitlines()[0]
    path = tmp_path / "duplicate.jsonl"
    path.write_text(first + "\n" + first + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate clause_id"):
        load_jsonl(path, dataset_id="invalid")


def test_evaluation_reports_all_classes_and_selective_accuracy():
    predictions = tuple(
        ScoredPrediction(label, label, confidence)
        for label, confidence in zip(ClauseLabel, (0.99, 0.95, 0.91, 0.88, 0.86, 0.82, 0.79), strict=True)
    ) + (
        ScoredPrediction(ClauseLabel.OBLIGATION, ClauseLabel.NON_OBLIGATION, 0.55),
    )
    report = evaluate(predictions, confidence_threshold=0.79)
    assert report.accuracy == pytest.approx(0.875)
    assert report.coverage == pytest.approx(0.875)
    assert report.covered_accuracy == 1.0
    assert set(report.per_class) == set(ClauseLabel)
    threshold = select_abstention_threshold(
        predictions, minimum_covered_accuracy=1.0, minimum_coverage=0.75
    )
    assert threshold == 0.79


def _manifest(**overrides) -> ModelManifest:
    values = {
        "model_id": "legal-bert@clauses-v1:abc123",
        "base_model": "nlpaueb/legal-bert-base-uncased",
        "dataset_id": "clauses-v1",
        "dataset_sha256": "a" * 64,
        "labels": tuple(ClauseLabel),
        "confidence_threshold": 0.80,
        "temperature": 1.0,
        "example_count": 1_000,
        "document_count": 60,
        "regulator_count": 5,
        "macro_f1": 0.84,
        "per_class_f1": {label: 0.80 for label in ClauseLabel},
        "covered_accuracy": 0.91,
        "expected_calibration_error": 0.06,
        "coverage": 0.72,
    }
    values.update(overrides)
    return ModelManifest(**values)


def test_promotion_gate_rejects_small_or_weak_models():
    manifest = _manifest(example_count=14, document_count=5, macro_f1=0.62)
    assert set(manifest.promotion_failures()) == {
        "insufficient_examples",
        "insufficient_documents",
        "macro_f1_below_gate",
    }
    assert not manifest.promoted
    assert _manifest().promoted


def test_promotion_gate_requires_the_complete_taxonomy():
    labels = tuple(label for label in ClauseLabel if label is not ClauseLabel.PERMISSION)
    manifest = _manifest(
        labels=labels,
        per_class_f1={label: 0.80 for label in labels},
    )
    assert set(manifest.promotion_failures()) == {
        "incomplete_label_taxonomy",
        "per_class_f1_below_gate",
    }


def test_manifest_rejects_metrics_outside_probability_bounds():
    with pytest.raises(ValueError, match="macro_f1 must be between zero and one"):
        _manifest(macro_f1=1.01)


def test_runtime_refuses_unpromoted_artifact_before_model_loading(tmp_path):
    manifest = _manifest(example_count=14)
    payload = asdict(manifest)
    payload["labels"] = [label.value for label in manifest.labels]
    payload["per_class_f1"] = {
        label.value: score for label, score in manifest.per_class_f1.items()
    }
    (tmp_path / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(UnpromotedModelError, match="insufficient_examples"):
        TransformerClauseClassifier(tmp_path, pipeline_factory=lambda *args, **kwargs: None)


def test_promoted_runtime_preserves_model_and_dataset_lineage(tmp_path):
    manifest = _manifest()
    payload = {
        "model_id": manifest.model_id,
        "base_model": manifest.base_model,
        "dataset_id": manifest.dataset_id,
        "dataset_sha256": manifest.dataset_sha256,
        "labels": [label.value for label in manifest.labels],
        "confidence_threshold": manifest.confidence_threshold,
        "temperature": manifest.temperature,
        "example_count": manifest.example_count,
        "document_count": manifest.document_count,
        "regulator_count": manifest.regulator_count,
        "macro_f1": manifest.macro_f1,
        "per_class_f1": {
            label.value: score for label, score in manifest.per_class_f1.items()
        },
        "covered_accuracy": manifest.covered_accuracy,
        "expected_calibration_error": manifest.expected_calibration_error,
        "coverage": manifest.coverage,
    }
    (tmp_path / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    def factory(*args, **kwargs):
        return lambda text, truncation: [[
            {"label": "obligation", "score": 0.82},
            {"label": "non_obligation", "score": 0.18},
        ]]

    prediction = TransformerClauseClassifier(tmp_path, pipeline_factory=factory).predict(
        "The operator must maintain a register."
    )
    assert prediction.label is ClauseLabel.OBLIGATION
    assert not prediction.abstained
    assert prediction.model_id == manifest.model_id
    assert prediction.dataset_id == manifest.dataset_id


def test_transformer_mode_requires_an_explicit_artifact_path():
    with pytest.raises(ValueError, match="CLAUSE_CLASSIFIER_ARTIFACT_DIR"):
        Settings(clause_classifier_mode="transformer", clause_classifier_artifact_dir="")


def test_classifier_is_fail_closed_by_default():
    settings = Settings()
    assert settings.clause_classifier_mode == "disabled"
    assert settings.clause_classifier_artifact_dir == ""
