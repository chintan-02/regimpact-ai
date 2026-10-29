"""Batch a governed sample into secure, independently reviewed annotation workspaces."""

from __future__ import annotations

import json
import re
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

from .annotation_sampling import (
    AnnotationSamplingError,
    annotation_progress_report,
    build_blinded_package,
    export_completed_annotations,
    sample_payload,
    sample_pilot,
    sampling_report,
    validate_annotation_package,
)
from .annotation_workspace import build_annotation_workspace
from .clause_annotations import Annotation, ClauseCandidate

CAMPAIGN_SCHEMA_VERSION = "regimpact-annotation-campaign-v1"
MINIMUM_PRODUCTION_SAMPLE = 500


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _write_json(path: Path, value: object, *, private: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if private:
        path.chmod(0o600)


def _safe_campaign_id(value: str) -> str:
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,59}", value) is None:
        raise AnnotationSamplingError("campaign ID must be a safe stable identifier")
    return value


def prepare_campaign(
    candidates: tuple[ClauseCandidate, ...],
    *,
    candidate_queue_sha256: str,
    output_dir: Path,
    campaign_id: str = "v0.6c6-production-v1",
    target: int = 700,
    batch_size: int = 100,
    seed: str = "v0.6c6-production-v1",
) -> dict[str, Any]:
    """Create deterministic, non-overlapping batches and offline A/B workspaces."""
    campaign_id = _safe_campaign_id(campaign_id)
    if target < MINIMUM_PRODUCTION_SAMPLE:
        raise AnnotationSamplingError("production campaign target must be at least 500")
    if batch_size <= 0 or batch_size > 200:
        raise AnnotationSamplingError("batch size must be between 1 and 200")
    if re.fullmatch(r"[0-9a-f]{64}", candidate_queue_sha256) is None:
        raise AnnotationSamplingError("candidate queue SHA-256 is invalid")

    sample = sample_pilot(candidates, target=target, seed=seed)
    global_records = sample_payload(sample)
    global_sample_sha256 = sha256(_canonical(global_records).encode()).hexdigest()
    batches: list[dict[str, Any]] = []
    for offset in range(0, len(sample), batch_size):
        number = offset // batch_size + 1
        batch_id = f"batch-{number:03d}"
        batch = sample[offset : offset + batch_size]
        batch_dir = output_dir / batch_id
        sample_path = batch_dir / "sample.json"
        package_a_path = batch_dir / "package-a.json"
        package_b_path = batch_dir / "package-b.json"
        workspace_a_path = batch_dir / "workspace-a.html"
        workspace_b_path = batch_dir / "workspace-b.html"
        report_path = batch_dir / "sampling-report.json"
        records = sample_payload(batch)
        batch_sample_sha256 = sha256(
            "\n".join(_canonical(item) for item in records).encode()
        ).hexdigest()
        package_prefix = f"{campaign_id}-{batch_id}"

        _write_json(
            sample_path,
            {"schema_version": "regimpact-sampled-clauses-v1", "records": records},
        )
        _write_json(
            package_a_path,
            build_blinded_package(
                batch,
                slot="A",
                seed=seed,
                candidate_queue_sha256=candidate_queue_sha256,
                package_id_prefix=package_prefix,
            ),
        )
        _write_json(
            package_b_path,
            build_blinded_package(
                batch,
                slot="B",
                seed=seed,
                candidate_queue_sha256=candidate_queue_sha256,
                package_id_prefix=package_prefix,
            ),
        )
        workspace_a_path.write_text(
            build_annotation_workspace(sample_path, package_a_path), encoding="utf-8"
        )
        workspace_b_path.write_text(
            build_annotation_workspace(sample_path, package_b_path), encoding="utf-8"
        )
        workspace_a_path.chmod(0o600)
        workspace_b_path.chmod(0o600)
        report = sampling_report(candidates, batch, seed=f"{seed}:{batch_id}")
        _write_json(report_path, report, private=False)
        batches.append(
            {
                "batch_id": batch_id,
                "count": len(batch),
                "sample_sha256": batch_sample_sha256,
                "sample": f"{batch_id}/sample.json",
                "package_a": f"{batch_id}/package-a.json",
                "package_b": f"{batch_id}/package-b.json",
                "workspace_a": f"{batch_id}/workspace-a.html",
                "workspace_b": f"{batch_id}/workspace-b.html",
                "completed_a": f"{batch_id}/completed-a.json",
                "completed_b": f"{batch_id}/completed-b.json",
            }
        )

    manifest = {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "status": "awaiting_independent_annotation",
        "campaign_id": campaign_id,
        "seed": seed,
        "target": target,
        "batch_size": batch_size,
        "candidate_queue_sha256": candidate_queue_sha256,
        "sample_sha256": global_sample_sha256,
        "documents": len({item.candidate.document_id for item in sample}),
        "regulators": len({item.candidate.regulator for item in sample}),
        "sampling_strata": dict(
            sorted(Counter(item.sampling_stratum for item in sample).items())
        ),
        "batches": batches,
        "two_independent_humans_required_per_clause": True,
        "third_party_adjudication_required_for_disagreements": True,
        "model_training_authorized": False,
    }
    _write_json(output_dir / "campaign-manifest.json", manifest, private=False)
    return manifest


def load_campaign_manifest(campaign_dir: Path) -> dict[str, Any]:
    manifest_path = campaign_dir / "campaign-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != CAMPAIGN_SCHEMA_VERSION
        or manifest.get("model_training_authorized") is not False
        or not isinstance(manifest.get("batches"), list)
        or not manifest["batches"]
        or not isinstance(manifest.get("campaign_id"), str)
        or _safe_campaign_id(manifest["campaign_id"]) != manifest["campaign_id"]
        or not isinstance(manifest.get("target"), int)
        or manifest["target"] < MINIMUM_PRODUCTION_SAMPLE
        or re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("candidate_queue_sha256"))) is None
    ):
        raise AnnotationSamplingError("invalid annotation campaign manifest")
    batches = manifest["batches"]
    expected_ids = [f"batch-{index:03d}" for index in range(1, len(batches) + 1)]
    actual_ids = [batch.get("batch_id") for batch in batches if isinstance(batch, dict)]
    if actual_ids != expected_ids:
        raise AnnotationSamplingError("annotation campaign batches are invalid")
    expected_keys = (
        "sample",
        "package_a",
        "package_b",
        "workspace_a",
        "workspace_b",
        "completed_a",
        "completed_b",
    )
    expected_names = (
        "sample.json",
        "package-a.json",
        "package-b.json",
        "workspace-a.html",
        "workspace-b.html",
        "completed-a.json",
        "completed-b.json",
    )
    total = 0
    for batch, batch_id in zip(batches, expected_ids, strict=True):
        if not isinstance(batch.get("count"), int) or batch["count"] <= 0:
            raise AnnotationSamplingError("annotation campaign batch count is invalid")
        if re.fullmatch(r"[0-9a-f]{64}", str(batch.get("sample_sha256"))) is None:
            raise AnnotationSamplingError("annotation campaign sample hash is invalid")
        expected_paths = [f"{batch_id}/{name}" for name in expected_names]
        if [batch.get(key) for key in expected_keys] != expected_paths:
            raise AnnotationSamplingError("annotation campaign batch paths are invalid")
        total += int(batch["count"])
    if total != manifest["target"]:
        raise AnnotationSamplingError("annotation campaign target does not match batch coverage")
    return manifest


def _validate_batch_sample(campaign_dir: Path, batch: dict[str, Any]) -> Path:
    sample_path = campaign_dir / str(batch["sample"])
    sample_document = json.loads(sample_path.read_text(encoding="utf-8"))
    if not isinstance(sample_document, dict):
        raise AnnotationSamplingError(f"invalid campaign sample: {batch['batch_id']}")
    records = sample_document.get("records")
    if (
        sample_document.get("schema_version") != "regimpact-sampled-clauses-v1"
        or not isinstance(records, list)
        or len(records) != batch["count"]
        or any(not isinstance(item, dict) for item in records)
    ):
        raise AnnotationSamplingError(f"invalid campaign sample: {batch['batch_id']}")
    fingerprint = sha256("\n".join(_canonical(item) for item in records).encode()).hexdigest()
    if fingerprint != batch["sample_sha256"]:
        raise AnnotationSamplingError(f"campaign sample fingerprint mismatch: {batch['batch_id']}")
    return sample_path


def campaign_progress_report(campaign_dir: Path) -> dict[str, Any]:
    """Validate all returned packages and aggregate campaign progress."""
    manifest = load_campaign_manifest(campaign_dir)
    reports: list[dict[str, Any]] = []
    completed_a = completed_b = dual_annotated = agreements = disagreements = 0
    for batch in manifest["batches"]:
        sample = _validate_batch_sample(campaign_dir, batch)
        package_a = campaign_dir / str(batch["completed_a"])
        package_b = campaign_dir / str(batch["completed_b"])
        returned = {"A": package_a.exists(), "B": package_b.exists()}
        validated: dict[str, dict[str, Any]] = {}
        completed = {"A": 0, "B": 0}
        expected_prefix = f"{manifest['campaign_id']}-{batch['batch_id']}"
        for slot, path in (("A", package_a), ("B", package_b)):
            if not returned[slot]:
                continue
            package = validate_annotation_package(sample, path, expected_slot=slot)
            if (
                package.get("package_id") != f"{expected_prefix}-{slot.lower()}"
                or package.get("candidate_queue_sha256")
                != manifest["candidate_queue_sha256"]
            ):
                raise AnnotationSamplingError(
                    f"campaign package identity mismatch: {batch['batch_id']}"
                )
            validated[slot] = package
            completed[slot] = sum(
                task.get("label") is not None for task in package["tasks"]
            )
        completed_a += completed["A"]
        completed_b += completed["B"]

        if not all(returned.values()):
            reports.append(
                {
                    "batch_id": batch["batch_id"],
                    "status": "awaiting_returned_packages",
                    "count": batch["count"],
                    "completed": completed,
                }
            )
            continue
        report = annotation_progress_report(sample, package_a, package_b)
        reports.append({"batch_id": batch["batch_id"], **report})
        dual_annotated += int(report["dual_annotated"])
        agreements += int(report["agreements"])
        disagreements += int(report["disagreements"])

    target = int(manifest["target"])
    ready = dual_annotated == target and all(
        report.get("status") == "ready_for_adjudication" for report in reports
    )
    return {
        "schema_version": "regimpact-annotation-campaign-progress-v1",
        "campaign_id": manifest["campaign_id"],
        "status": "ready_for_adjudication" if ready else "annotation_in_progress",
        "target": target,
        "completed": {"A": completed_a, "B": completed_b},
        "dual_annotated": dual_annotated,
        "agreements": agreements,
        "disagreements": disagreements,
        "agreement_rate": round(agreements / dual_annotated, 4) if dual_annotated else None,
        "batches": reports,
        "model_training_authorized": False,
    }


def export_campaign_annotations(
    campaign_dir: Path,
) -> tuple[tuple[Annotation, ...], dict[str, Any]]:
    """Export only a fully completed campaign into the existing adjudication schema."""
    progress = campaign_progress_report(campaign_dir)
    if progress["status"] != "ready_for_adjudication":
        raise AnnotationSamplingError("every campaign batch must be complete before export")
    manifest = load_campaign_manifest(campaign_dir)
    annotations: list[Annotation] = []
    clause_ids: set[str] = set()
    for batch in manifest["batches"]:
        values, _ = export_completed_annotations(
            campaign_dir / str(batch["sample"]),
            campaign_dir / str(batch["completed_a"]),
            campaign_dir / str(batch["completed_b"]),
        )
        batch_ids = {item.clause_id for item in values}
        if clause_ids & batch_ids:
            raise AnnotationSamplingError("campaign batches contain duplicate clauses")
        clause_ids.update(batch_ids)
        annotations.extend(values)
    if len(annotations) != int(manifest["target"]) * 2:
        raise AnnotationSamplingError("campaign export does not contain two votes per clause")
    return tuple(annotations), progress
