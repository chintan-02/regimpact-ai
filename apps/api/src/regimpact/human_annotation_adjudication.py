"""Independent-human comparison and governed adjudication for silver holdouts."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .annotation_sampling import (
    SAMPLING_POLICY_VERSION,
    AnnotationSamplingError,
    validate_annotation_package,
)
from .clause_annotations import GUIDELINE_VERSION
from .clause_classifier import ClauseLabel
from .silver_labeling import SILVER_SCHEMA_VERSION

COMPARISON_SCHEMA_VERSION = "regimpact-human-annotation-comparison-v1"
ADJUDICATION_PACKAGE_SCHEMA_VERSION = "regimpact-human-adjudication-package-v1"
ADJUDICATION_REPORT_SCHEMA_VERSION = "regimpact-human-adjudication-report-v1"
HUMAN_EVALUATION_PACKAGE_PREFIX = "v0.6c7-human-evaluation"
LABELS = tuple(label.value for label in ClauseLabel)
ADJUDICATION_REASON_CODES = (
    "annotation_error",
    "guideline_interpretation",
    "scope_resolution",
    "taxonomy_boundary",
    "other_governed_reason",
)
_AWARE_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})$"
)
_ANNOTATION_PACKAGE_FIELDS = {
    "schema_version",
    "package_id",
    "annotator_slot",
    "annotator_id",
    "candidate_queue_sha256",
    "sample_sha256",
    "sampling_policy_version",
    "guideline_version",
    "allowed_labels",
    "labels_visible_from_other_annotator",
    "model_training_authorized",
    "tasks",
}
_ANNOTATION_TASK_FIELDS = {
    "clause_id",
    "document_id",
    "regulator",
    "source_url",
    "section_id",
    "heading",
    "page",
    "text",
    "text_sha256",
    "guideline_version",
    "label",
    "annotated_at",
    "notes",
}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sample_hash(records: list[dict[str, Any]]) -> str:
    stream = "\n".join(_canonical(item) for item in records)
    return sha256(stream.encode()).hexdigest()


def _file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _aware_timestamp(value: object) -> bool:
    if not isinstance(value, str) or _AWARE_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def _load_context(experiment_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_path = experiment_dir / "silver-experiment-manifest.json"
    sample_path = experiment_dir / "human-evaluation-sample.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AnnotationSamplingError("invalid multi-human evaluation input") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != SILVER_SCHEMA_VERSION
        or manifest.get("evaluation_clauses") != 70
        or not isinstance(manifest.get("seed"), str)
        or not str(manifest["seed"]).strip()
        or manifest.get("model_training_authorized") is not False
        or manifest.get("production_promotion_authorized") is not False
    ):
        raise AnnotationSamplingError("invalid multi-human evaluation governance metadata")
    records = sample.get("records") if isinstance(sample, dict) else None
    if (
        not isinstance(sample, dict)
        or sample.get("schema_version") != "regimpact-sampled-clauses-v1"
        or not isinstance(records, list)
        or len(records) != 70
        or any(not isinstance(item, dict) for item in records)
    ):
        raise AnnotationSamplingError("multi-human evaluation must contain exactly 70 clauses")
    clause_ids = [str(item.get("clause_id")) for item in records]
    if len(set(clause_ids)) != len(clause_ids):
        raise AnnotationSamplingError("multi-human evaluation sample contains duplicate clause IDs")
    identity_hash = sha256(_canonical(sorted(clause_ids)).encode()).hexdigest()
    if manifest.get("evaluation_clause_ids_sha256") != identity_hash:
        raise AnnotationSamplingError("multi-human evaluation clause identity mismatch")
    holdouts = manifest.get("holdout_documents")
    if not isinstance(holdouts, list) or any(
        item.get("document_id") not in holdouts for item in records
    ):
        raise AnnotationSamplingError("multi-human evaluation is not document-held-out")
    for item in records:
        clause_id = str(item.get("clause_id"))
        text = item.get("text")
        if not isinstance(text, str) or item.get("text_sha256") != sha256(text.encode()).hexdigest():
            raise AnnotationSamplingError(f"multi-human evaluation text hash mismatch: {clause_id}")
    return manifest, records


def _expected_order(records: list[dict[str, Any]], *, seed: str, slot: str) -> list[str]:
    return [
        str(item["clause_id"])
        for item in sorted(
            records,
            key=lambda item: sha256(
                f"{seed}:{slot}:{item['clause_id']}".encode()
            ).hexdigest(),
        )
    ]


def _validated_human_packages(
    experiment_dir: Path,
    completed_a_path: Path,
    completed_b_path: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, dict[str, Any]]],
]:
    manifest, records = _load_context(experiment_dir)
    sample_path = experiment_dir / "human-evaluation-sample.json"
    packages: dict[str, dict[str, Any]] = {}
    tasks_by_slot: dict[str, dict[str, dict[str, Any]]] = {}
    for slot, path in (("A", completed_a_path), ("B", completed_b_path)):
        try:
            package = validate_annotation_package(sample_path, path, expected_slot=slot)
        except (json.JSONDecodeError, OSError) as exc:
            raise AnnotationSamplingError(f"invalid completed human slot {slot} package") from exc
        if set(package) != _ANNOTATION_PACKAGE_FIELDS or any(
            set(item) != _ANNOTATION_TASK_FIELDS for item in package["tasks"]
        ):
            raise AnnotationSamplingError(
                f"human slot {slot} package contains non-annotation fields"
            )
        if package.get("package_id") != f"{HUMAN_EVALUATION_PACKAGE_PREFIX}-{slot.lower()}":
            raise AnnotationSamplingError(f"human slot {slot} package identity mismatch")
        tasks = package["tasks"]
        expected_order = _expected_order(records, seed=str(manifest["seed"]), slot=slot)
        if [str(item.get("clause_id")) for item in tasks] != expected_order:
            raise AnnotationSamplingError(f"human slot {slot} task ordering mismatch")
        if any(item.get("label") is None for item in tasks):
            raise AnnotationSamplingError(f"human slot {slot} labels are incomplete")
        annotator_id = package.get("annotator_id")
        if not isinstance(annotator_id, str) or not annotator_id.strip():
            raise AnnotationSamplingError(f"human slot {slot} annotator identity is required")
        packages[slot] = package
        tasks_by_slot[slot] = {str(item["clause_id"]): item for item in tasks}

    if packages["A"]["annotator_id"] == packages["B"]["annotator_id"]:
        raise AnnotationSamplingError("human slots A and B require distinct annotator identities")
    for field in (
        "candidate_queue_sha256",
        "sample_sha256",
        "sampling_policy_version",
        "guideline_version",
        "allowed_labels",
    ):
        if packages["A"].get(field) != packages["B"].get(field):
            raise AnnotationSamplingError(f"human annotation package {field} mismatch")
    if packages["A"]["sample_sha256"] != _sample_hash(records):
        raise AnnotationSamplingError("human annotation sample hash mismatch")
    if packages["A"]["sampling_policy_version"] != SAMPLING_POLICY_VERSION:
        raise AnnotationSamplingError("human annotation sampling policy mismatch")
    if packages["A"]["guideline_version"] != GUIDELINE_VERSION:
        raise AnnotationSamplingError("human annotation guideline mismatch")
    if packages["A"]["allowed_labels"] != list(LABELS):
        raise AnnotationSamplingError("human annotation allowed labels mismatch")
    return manifest, records, packages, tasks_by_slot


def compare_human_annotations(
    experiment_dir: Path,
    completed_a_path: Path,
    completed_b_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compare two complete independent humans and create a text-free review package."""
    _manifest, records, packages, tasks_by_slot = _validated_human_packages(
        experiment_dir, completed_a_path, completed_b_path
    )
    matrix = [[0 for _ in LABELS] for _ in LABELS]
    label_index = {label: index for index, label in enumerate(LABELS)}
    disagreements: list[dict[str, Any]] = []
    agreements = 0
    for record in records:
        clause_id = str(record["clause_id"])
        label_a = str(tasks_by_slot["A"][clause_id]["label"])
        label_b = str(tasks_by_slot["B"][clause_id]["label"])
        matrix[label_index[label_a]][label_index[label_b]] += 1
        if label_a == label_b:
            agreements += 1
        else:
            disagreements.append(
                {
                    "clause_id": clause_id,
                    "text_sha256": record["text_sha256"],
                    "label_a": label_a,
                    "label_b": label_b,
                    "disagreement_reason_code": "human_label_disagreement",
                    "adjudicated_label": None,
                    "adjudication_reason_code": None,
                }
            )

    total = len(records)
    counts_a = Counter(
        str(tasks_by_slot["A"][str(item["clause_id"])]["label"]) for item in records
    )
    counts_b = Counter(
        str(tasks_by_slot["B"][str(item["clause_id"])]["label"]) for item in records
    )
    raw_agreement = agreements / total
    expected_agreement = sum(counts_a[label] * counts_b[label] for label in LABELS) / total**2
    if expected_agreement == 1.0:
        kappa = 1.0 if raw_agreement == 1.0 else 0.0
    else:
        kappa = (raw_agreement - expected_agreement) / (1.0 - expected_agreement)
    per_class = {}
    for index, label in enumerate(LABELS):
        matches = matrix[index][index]
        uses = counts_a[label] + counts_b[label]
        union = counts_a[label] + counts_b[label] - matches
        binary_matches = matches + total - union
        per_class[label] = {
            "positive_agreement": 2 * matches / uses if uses else None,
            "binary_agreement": binary_matches / total,
            "matches": matches,
            "annotator_a_count": counts_a[label],
            "annotator_b_count": counts_b[label],
        }

    clause_ids = [str(item["clause_id"]) for item in records]
    clause_ids_sha256 = sha256(_canonical(sorted(clause_ids)).encode()).hexdigest()
    package_evidence = {
        slot: {
            "package_id": packages[slot]["package_id"],
            "completed_sha256": _file_hash(path),
            "annotator_id": packages[slot]["annotator_id"],
        }
        for slot, path in (("A", completed_a_path), ("B", completed_b_path))
    }
    report = {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "evaluation_clauses": total,
        "sample_sha256": packages["A"]["sample_sha256"],
        "evaluation_clause_ids_sha256": clause_ids_sha256,
        "annotation_packages": package_evidence,
        "raw_agreement": raw_agreement,
        "cohens_kappa": kappa,
        "per_class_agreement": per_class,
        "confusion_matrix": {
            "labels": list(LABELS),
            "rows": "human_a_label",
            "columns": "human_b_label",
            "matrix": matrix,
        },
        "agreement_count": agreements,
        "disagreement_count": len(disagreements),
        "all_disagreements_require_adjudication": True,
        "independent_annotation_complete": True,
        "model_predictions_included": False,
        "model_predictions_exposed_before_independent_annotation_complete": False,
        "model_training_authorized": False,
        "production_promotion_authorized": False,
    }
    adjudication_package = {
        "schema_version": ADJUDICATION_PACKAGE_SCHEMA_VERSION,
        "package_id": "v0.6c-human-adjudication-v1",
        "sample_sha256": packages["A"]["sample_sha256"],
        "evaluation_clause_ids_sha256": clause_ids_sha256,
        "annotation_packages": package_evidence,
        "allowed_labels": list(LABELS),
        "allowed_adjudication_reason_codes": list(ADJUDICATION_REASON_CODES),
        "disagreement_count": len(disagreements),
        "independent_annotation_complete": True,
        "all_disagreements_require_adjudication": True,
        "model_predictions_included": False,
        "model_predictions_exposed_before_independent_annotation_complete": False,
        "adjudicator_id": None,
        "adjudicated_at": None,
        "model_training_authorized": False,
        "production_promotion_authorized": False,
        "records": disagreements,
    }
    return report, adjudication_package


def compile_human_adjudication(
    experiment_dir: Path,
    completed_a_path: Path,
    completed_b_path: Path,
    adjudication_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate complete adjudication coverage and compile text-free final human labels."""
    comparison, expected = compare_human_annotations(
        experiment_dir, completed_a_path, completed_b_path
    )
    _, records, packages, tasks_by_slot = _validated_human_packages(
        experiment_dir, completed_a_path, completed_b_path
    )
    try:
        package = json.loads(adjudication_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AnnotationSamplingError("invalid human adjudication package") from exc
    if not isinstance(package, dict) or set(package) != set(expected):
        raise AnnotationSamplingError("human adjudication package metadata mismatch")
    for field in expected:
        if field in {"adjudicator_id", "adjudicated_at", "records"}:
            continue
        if package.get(field) != expected[field]:
            raise AnnotationSamplingError(f"human adjudication package {field} mismatch")
    adjudicator_id = package.get("adjudicator_id")
    if not isinstance(adjudicator_id, str) or not adjudicator_id.strip():
        raise AnnotationSamplingError("human adjudication requires an adjudicator identity")
    if adjudicator_id in {packages["A"]["annotator_id"], packages["B"]["annotator_id"]}:
        raise AnnotationSamplingError("adjudicator must be independent of human slots A and B")
    if not _aware_timestamp(package.get("adjudicated_at")):
        raise AnnotationSamplingError("human adjudication requires a timezone-aware timestamp")
    adjudication_records = package.get("records")
    expected_records = expected["records"]
    if (
        not isinstance(adjudication_records, list)
        or len(adjudication_records) != len(expected_records)
        or any(not isinstance(item, dict) for item in adjudication_records)
    ):
        raise AnnotationSamplingError("human adjudication disagreement coverage mismatch")
    resolved_by_id: dict[str, dict[str, Any]] = {}
    allowed_record_fields = {
        "clause_id",
        "text_sha256",
        "label_a",
        "label_b",
        "disagreement_reason_code",
        "adjudicated_label",
        "adjudication_reason_code",
    }
    for expected_record, actual in zip(expected_records, adjudication_records, strict=True):
        if set(actual) != allowed_record_fields:
            raise AnnotationSamplingError("human adjudication records must remain text-free")
        for field in (
            "clause_id",
            "text_sha256",
            "label_a",
            "label_b",
            "disagreement_reason_code",
        ):
            if actual.get(field) != expected_record[field]:
                raise AnnotationSamplingError(
                    f"human adjudication record identity mismatch: {expected_record['clause_id']}"
                )
        label = actual.get("adjudicated_label")
        reason = actual.get("adjudication_reason_code")
        if label not in LABELS or reason not in ADJUDICATION_REASON_CODES:
            raise AnnotationSamplingError(
                f"unresolved human disagreement: {expected_record['clause_id']}"
            )
        resolved_by_id[str(actual["clause_id"])] = actual
    if len(resolved_by_id) != len(expected_records):
        raise AnnotationSamplingError("human adjudication contains duplicate clause IDs")

    final_records: list[dict[str, Any]] = []
    for record in records:
        clause_id = str(record["clause_id"])
        label_a = str(tasks_by_slot["A"][clause_id]["label"])
        label_b = str(tasks_by_slot["B"][clause_id]["label"])
        decision = resolved_by_id.get(clause_id)
        if label_a == label_b:
            final_label = label_a
            reason_code = "human_human_agreement"
        elif decision is not None:
            final_label = str(decision["adjudicated_label"])
            reason_code = str(decision["adjudication_reason_code"])
        else:
            raise AnnotationSamplingError(f"unresolved human disagreement: {clause_id}")
        final_records.append(
            {
                "clause_id": clause_id,
                "text_sha256": record["text_sha256"],
                "label_a": label_a,
                "label_b": label_b,
                "final_label": final_label,
                "resolution_reason_code": reason_code,
            }
        )

    report = {
        "schema_version": ADJUDICATION_REPORT_SCHEMA_VERSION,
        "status": "adjudication_complete",
        "evaluation_clauses": len(final_records),
        "sample_sha256": comparison["sample_sha256"],
        "evaluation_clause_ids_sha256": comparison["evaluation_clause_ids_sha256"],
        "annotation_packages": comparison["annotation_packages"],
        "adjudication_package_sha256": _file_hash(adjudication_path),
        "adjudicator_id": adjudicator_id,
        "adjudicated_at": package["adjudicated_at"],
        "agreement_count": comparison["agreement_count"],
        "adjudicated_disagreement_count": comparison["disagreement_count"],
        "unresolved_disagreement_count": 0,
        "final_label_distribution": dict(
            sorted(Counter(item["final_label"] for item in final_records).items())
        ),
        "adjudicated_gold_data": True,
        "model_predictions_included": False,
        "model_training_authorized": False,
        "production_promotion_authorized": False,
    }
    return report, final_records
