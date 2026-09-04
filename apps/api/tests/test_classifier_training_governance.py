from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from regimpact.classifier_training_governance import (
    TrainingGovernanceError,
    load_ready_dataset_audit,
    promote_artifact,
    verify_promotion_receipt,
)
from regimpact.clause_classifier import ClauseLabel, ModelManifest


def manifest() -> ModelManifest:
    return ModelManifest(
        model_id="legal-bert@clauses-v1:abc123",
        base_model="nlpaueb/legal-bert-base-uncased",
        dataset_id="clauses-v1",
        dataset_sha256="a" * 64,
        labels=tuple(ClauseLabel),
        confidence_threshold=0.8,
        temperature=1.0,
        example_count=700,
        document_count=40,
        regulator_count=4,
        macro_f1=0.84,
        per_class_f1={label: 0.8 for label in ClauseLabel},
        covered_accuracy=0.91,
        expected_calibration_error=0.06,
        coverage=0.72,
    )


def write_manifest(path, value: ModelManifest) -> None:
    payload = asdict(value)
    payload["labels"] = [label.value for label in value.labels]
    payload["per_class_f1"] = {
        label.value: score for label, score in value.per_class_f1.items()
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_audit(path, value: ModelManifest, **updates) -> None:
    payload = {
        "status": "ready",
        "failures": [],
        "dataset_id": value.dataset_id,
        "dataset_sha256": value.dataset_sha256,
        "unresolved_count": 0,
        "examples": value.example_count,
    }
    payload.update(updates)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_training_refuses_non_ready_or_mismatched_audit(tmp_path) -> None:
    path = tmp_path / "audit.json"
    write_audit(path, manifest(), status="blocked", failures=["insufficient_examples"])
    with pytest.raises(TrainingGovernanceError, match="not ready"):
        load_ready_dataset_audit(path, dataset_id="clauses-v1", dataset_sha256="a" * 64)
    write_audit(path, manifest(), dataset_sha256="b" * 64)
    with pytest.raises(TrainingGovernanceError, match="SHA-256"):
        load_ready_dataset_audit(path, dataset_id="clauses-v1", dataset_sha256="a" * 64)


def test_promotion_receipt_detects_artifact_tampering(tmp_path) -> None:
    value = manifest()
    write_manifest(tmp_path / "manifest.json", value)
    (tmp_path / "model.safetensors").write_bytes(b"weights")
    audit_path = tmp_path / "audit.json"
    write_audit(audit_path, value)
    receipt = promote_artifact(
        tmp_path,
        dataset_audit_path=audit_path,
        approver="model-risk-reviewer",
        approved_at="2026-09-04T00:00:00+00:00",
        training_commit="b" * 40,
    )
    assert receipt["promoted"] is True
    verify_promotion_receipt(tmp_path)
    (tmp_path / "model.safetensors").write_bytes(b"tampered")
    with pytest.raises(TrainingGovernanceError, match="changed after promotion"):
        verify_promotion_receipt(tmp_path)


def test_promotion_refuses_unqualified_model(tmp_path) -> None:
    value = manifest()
    write_manifest(tmp_path / "manifest.json", value)
    audit_path = tmp_path / "audit.json"
    write_audit(audit_path, value)
    payload = json.loads((tmp_path / "manifest.json").read_text())
    payload["macro_f1"] = 0.2
    (tmp_path / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TrainingGovernanceError, match="macro_f1_below_gate"):
        promote_artifact(
            tmp_path,
            dataset_audit_path=audit_path,
            approver="reviewer",
            approved_at="2026-09-04T00:00:00+00:00",
            training_commit="c" * 40,
        )
