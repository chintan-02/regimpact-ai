"""Fail-closed dataset admission and artifact-promotion evidence."""

from __future__ import annotations

import json
import re
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .classifier_runtime import load_manifest

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class TrainingGovernanceError(RuntimeError):
    pass


def load_ready_dataset_audit(
    path: Path, *, dataset_id: str, dataset_sha256: str
) -> dict[str, Any]:
    """Admit only a matching, successful v0.6A dataset audit."""
    value = json.loads(path.read_text(encoding="utf-8"))
    failures = value.get("failures")
    if value.get("status") != "ready" or failures != []:
        raise TrainingGovernanceError("dataset audit is not ready")
    if value.get("dataset_id") != dataset_id:
        raise TrainingGovernanceError("dataset audit ID does not match the training dataset")
    if value.get("dataset_sha256") != dataset_sha256:
        raise TrainingGovernanceError("dataset audit SHA-256 does not match the training dataset")
    if value.get("unresolved_count") != 0:
        raise TrainingGovernanceError("dataset audit contains unresolved annotations")
    return value


def artifact_fingerprint(artifact_dir: Path) -> str:
    """Hash artifact paths and bytes, excluding the mutable promotion receipt."""
    digest = sha256()
    files = sorted(
        path for path in artifact_dir.rglob("*") if path.is_file() and path.name != "promotion.json"
    )
    if not files:
        raise TrainingGovernanceError("model artifact contains no files")
    for path in files:
        digest.update(path.relative_to(artifact_dir).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def promote_artifact(
    artifact_dir: Path,
    *,
    dataset_audit_path: Path,
    approver: str,
    approved_at: str,
    training_commit: str,
) -> dict[str, Any]:
    """Create an immutable evidence receipt only for a qualifying artifact."""
    if not approver.strip():
        raise TrainingGovernanceError("promotion requires an approver")
    try:
        timestamp = datetime.fromisoformat(approved_at)
    except ValueError as exc:
        raise TrainingGovernanceError("approved_at must be an ISO-8601 timestamp") from exc
    if timestamp.tzinfo is None:
        raise TrainingGovernanceError("approved_at must be timezone-aware")
    if not _GIT_SHA.fullmatch(training_commit):
        raise TrainingGovernanceError("training_commit must be a full lowercase commit SHA")

    manifest_path = artifact_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    failures = manifest.promotion_failures()
    if failures:
        raise TrainingGovernanceError("model failed promotion gates: " + ", ".join(failures))
    audit = load_ready_dataset_audit(
        dataset_audit_path,
        dataset_id=manifest.dataset_id,
        dataset_sha256=manifest.dataset_sha256,
    )
    receipt = {
        "schema_version": "regimpact-model-promotion-v1",
        "model_id": manifest.model_id,
        "dataset_id": manifest.dataset_id,
        "dataset_sha256": manifest.dataset_sha256,
        "dataset_audit_sha256": sha256(dataset_audit_path.read_bytes()).hexdigest(),
        "manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        "artifact_sha256": artifact_fingerprint(artifact_dir),
        "training_commit": training_commit,
        "approver": approver,
        "approved_at": approved_at,
        "dataset_examples": audit["examples"],
        "promotion_failures": [],
        "promoted": True,
    }
    destination = artifact_dir / "promotion.json"
    temporary = artifact_dir / ".promotion.json.tmp"
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return receipt


def verify_promotion_receipt(artifact_dir: Path) -> dict[str, Any]:
    receipt_path = artifact_dir / "promotion.json"
    if not receipt_path.exists():
        raise TrainingGovernanceError("model artifact has no promotion receipt")
    value = json.loads(receipt_path.read_text(encoding="utf-8"))
    manifest_path = artifact_dir / "manifest.json"
    if value.get("promoted") is not True or value.get("promotion_failures") != []:
        raise TrainingGovernanceError("model promotion receipt is not approved")
    if value.get("manifest_sha256") != sha256(manifest_path.read_bytes()).hexdigest():
        raise TrainingGovernanceError("model manifest changed after promotion")
    if value.get("artifact_sha256") != artifact_fingerprint(artifact_dir):
        raise TrainingGovernanceError("model artifact changed after promotion")
    manifest = load_manifest(manifest_path)
    if value.get("model_id") != manifest.model_id:
        raise TrainingGovernanceError("promotion receipt model ID does not match manifest")
    return value
