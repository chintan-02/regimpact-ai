"""Deterministic sampling and blinded packages for independent clause annotation."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .clause_annotations import GUIDELINE_VERSION, Annotation, ClauseCandidate, load_json_records
from .clause_classifier import ClauseLabel

SAMPLING_POLICY_VERSION = "regimpact-clause-pilot-v1"
_STRATA = tuple(label.value for label in ClauseLabel)
_AWARE_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})$"
)
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "record_retention_requirement",
        re.compile(
            r"\b(retain|retention|keep|preserve|maintain).{0,50}\b(record|document|information|year|month)",
            re.IGNORECASE,
        ),
    ),
    (
        "prohibition",
        re.compile(
            r"\b(shall not|must not|may not|no person shall|prohibited|forbidden)\b", re.IGNORECASE
        ),
    ),
    (
        "reporting_requirement",
        re.compile(
            r"\b(report|notify|notification|file|submit|disclose|return|statement)\b", re.IGNORECASE
        ),
    ),
    (
        "permission",
        re.compile(r"\b(may|is authorized to|is entitled to|permission)\b", re.IGNORECASE),
    ),
    ("definition", re.compile(r"\b(means|includes|refers to|is defined as)\b", re.IGNORECASE)),
    ("obligation", re.compile(r"\b(must|shall|required to|is to)\b", re.IGNORECASE)),
)


class AnnotationSamplingError(RuntimeError):
    """Raised when a candidate queue or annotation package violates its contract."""


@dataclass(frozen=True, slots=True)
class SampledClause:
    candidate: ClauseCandidate
    sampling_stratum: str
    sampling_policy_version: str = SAMPLING_POLICY_VERSION


def _canonical(values: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in values)


def _stable_rank(seed: str, *values: str) -> str:
    return sha256(":".join((seed, *values)).encode()).hexdigest()


def sampling_stratum(text: str) -> str:
    """Return a transparent enrichment stratum, never a ground-truth label."""
    for name, pattern in _PATTERNS:
        if pattern.search(text):
            return name
    return "non_obligation"


def load_candidate_queue(path: Path) -> tuple[ClauseCandidate, ...]:
    candidates = tuple(ClauseCandidate(**item) for item in load_json_records(path))
    ids = [item.clause_id for item in candidates]
    if len(ids) != len(set(ids)):
        raise AnnotationSamplingError("candidate queue contains duplicate clause IDs")
    return candidates


def verify_candidate_queue(
    candidates: tuple[ClauseCandidate, ...], receipt_path: Path
) -> dict[str, Any]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema_version") != "regimpact-real-corpus-execution-v1":
        raise AnnotationSamplingError("unsupported candidate queue receipt")
    if receipt.get("status") != "candidate_queue_ready":
        raise AnnotationSamplingError("candidate queue is not ready")
    if receipt.get("model_training_authorized") is not False:
        raise AnnotationSamplingError("candidate receipt must not authorize model training")
    payload = _canonical([asdict(item) for item in candidates])
    if receipt.get("candidate_queue_sha256") != sha256(payload.encode()).hexdigest():
        raise AnnotationSamplingError("candidate queue fingerprint mismatch")
    if receipt.get("candidates") != len(candidates):
        raise AnnotationSamplingError("candidate queue count mismatch")
    return receipt


def sample_pilot(
    candidates: tuple[ClauseCandidate, ...], *, target: int = 350, seed: str = "v0.6c4-pilot-v1"
) -> tuple[SampledClause, ...]:
    if target <= 0 or target > len(candidates):
        raise AnnotationSamplingError("target must be positive and not exceed candidate count")
    by_document: dict[str, list[SampledClause]] = defaultdict(list)
    for candidate in candidates:
        by_document[candidate.document_id].append(
            SampledClause(candidate=candidate, sampling_stratum=sampling_stratum(candidate.text))
        )
    if target < len(by_document):
        raise AnnotationSamplingError("target cannot cover every document")

    selected: list[SampledClause] = []
    selected_ids: set[str] = set()
    quota = target // len(by_document)
    for document_id in sorted(by_document):
        offset = int(_stable_rank(seed, "document-strata", document_id)[:8], 16) % len(_STRATA)
        document_strata = _STRATA[offset:] + _STRATA[:offset]
        values = sorted(
            by_document[document_id],
            key=lambda item: (
                document_strata.index(item.sampling_stratum),
                _stable_rank(seed, document_id, item.sampling_stratum, item.candidate.clause_id),
            ),
        )
        # Round-robin across strata avoids letting high-volume modal clauses dominate a document.
        buckets: dict[str, list[SampledClause]] = defaultdict(list)
        for value in values:
            buckets[value.sampling_stratum].append(value)
        document_sample: list[SampledClause] = []
        while len(document_sample) < min(quota, len(values)):
            progressed = False
            for stratum in document_strata:
                if buckets[stratum] and len(document_sample) < quota:
                    document_sample.append(buckets[stratum].pop(0))
                    progressed = True
            if not progressed:
                break
        selected.extend(document_sample)
        selected_ids.update(item.candidate.clause_id for item in document_sample)

    remaining = [
        SampledClause(candidate=item, sampling_stratum=sampling_stratum(item.text))
        for item in candidates
        if item.clause_id not in selected_ids
    ]
    remaining_buckets: dict[str, list[SampledClause]] = defaultdict(list)
    for item in remaining:
        remaining_buckets[item.sampling_stratum].append(item)
    for stratum, bucket in remaining_buckets.items():
        bucket.sort(
            key=lambda item: _stable_rank(
                seed, item.sampling_stratum, item.candidate.document_id, item.candidate.clause_id
            )
        )
    stratum_counts = Counter(item.sampling_stratum for item in selected)
    while len(selected) < target:
        available = [stratum for stratum in _STRATA if remaining_buckets[stratum]]
        if not available:
            raise AnnotationSamplingError("candidate queue exhausted before target was reached")
        next_stratum = min(available, key=lambda value: (stratum_counts[value], value))
        selected.append(remaining_buckets[next_stratum].pop(0))
        stratum_counts[next_stratum] += 1
    selected.sort(key=lambda item: _stable_rank(seed, "master", item.candidate.clause_id))
    return tuple(selected)


def sample_payload(sample: tuple[SampledClause, ...]) -> list[dict[str, Any]]:
    return [
        {
            **asdict(item.candidate),
            "sampling_stratum": item.sampling_stratum,
            "sampling_policy_version": item.sampling_policy_version,
        }
        for item in sample
    ]


def build_blinded_package(
    sample: tuple[SampledClause, ...], *, slot: str, seed: str, candidate_queue_sha256: str
) -> dict[str, Any]:
    if slot not in {"A", "B"}:
        raise AnnotationSamplingError("annotator slot must be A or B")
    values = sorted(sample, key=lambda item: _stable_rank(seed, slot, item.candidate.clause_id))
    tasks = [
        {
            "clause_id": item.candidate.clause_id,
            "document_id": item.candidate.document_id,
            "regulator": item.candidate.regulator,
            "source_url": item.candidate.source_url,
            "section_id": item.candidate.section_id,
            "heading": item.candidate.heading,
            "page": item.candidate.page,
            "text": item.candidate.text,
            "text_sha256": item.candidate.text_sha256,
            "guideline_version": GUIDELINE_VERSION,
            "label": None,
            "annotated_at": None,
            "notes": "",
        }
        for item in values
    ]
    sample_hash = sha256(_canonical(sample_payload(sample)).encode()).hexdigest()
    return {
        "schema_version": "regimpact-blinded-annotation-package-v1",
        "package_id": f"v0.6c4-pilot-{slot.lower()}",
        "annotator_slot": slot,
        "annotator_id": None,
        "candidate_queue_sha256": candidate_queue_sha256,
        "sample_sha256": sample_hash,
        "sampling_policy_version": SAMPLING_POLICY_VERSION,
        "guideline_version": GUIDELINE_VERSION,
        "allowed_labels": list(_STRATA),
        "labels_visible_from_other_annotator": False,
        "model_training_authorized": False,
        "tasks": tasks,
    }


def sampling_report(
    candidates: tuple[ClauseCandidate, ...], sample: tuple[SampledClause, ...], *, seed: str
) -> dict[str, Any]:
    sample_values = sample_payload(sample)
    return {
        "schema_version": "regimpact-annotation-sampling-report-v1",
        "status": "pilot_packages_ready",
        "seed": seed,
        "sampling_policy_version": SAMPLING_POLICY_VERSION,
        "candidate_count": len(candidates),
        "sample_count": len(sample),
        "documents": len({item.candidate.document_id for item in sample}),
        "regulators": len({item.candidate.regulator for item in sample}),
        "sampling_strata": dict(sorted(Counter(item.sampling_stratum for item in sample).items())),
        "documents_sampled": dict(
            sorted(Counter(item.candidate.document_id for item in sample).items())
        ),
        "sample_sha256": sha256(_canonical(sample_values).encode()).hexdigest(),
        "heuristics_are_labels": False,
        "two_independent_humans_required": True,
        "third_party_adjudication_required_for_disagreements": True,
        "model_training_authorized": False,
    }


def _aware_timestamp(value: object) -> bool:
    if not isinstance(value, str) or _AWARE_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def validate_annotation_package(
    sample_path: Path, package_path: Path, *, expected_slot: str | None = None
) -> dict[str, Any]:
    """Verify one package against its immutable sample while allowing annotation fields."""
    sample_document = json.loads(sample_path.read_text(encoding="utf-8"))
    if (
        not isinstance(sample_document, dict)
        or sample_document.get("schema_version") != "regimpact-sampled-clauses-v1"
    ):
        raise AnnotationSamplingError("unsupported sampled-clause schema")
    records = sample_document.get("records")
    if (
        not isinstance(records, list)
        or not records
        or any(not isinstance(item, dict) for item in records)
    ):
        raise AnnotationSamplingError("sample must contain records")
    by_id = {str(item.get("clause_id")): item for item in records}
    if len(by_id) != len(records):
        raise AnnotationSamplingError("sample contains duplicate clause IDs")

    package = json.loads(package_path.read_text(encoding="utf-8"))
    if not isinstance(package, dict):
        raise AnnotationSamplingError("annotation package must be an object")
    slot = package.get("annotator_slot")
    sample_hash = sha256(_canonical(records).encode()).hexdigest()
    if (
        package.get("schema_version") != "regimpact-blinded-annotation-package-v1"
        or slot not in {"A", "B"}
        or (expected_slot is not None and slot != expected_slot)
        or package.get("package_id") != f"v0.6c4-pilot-{str(slot).lower()}"
        or package.get("sample_sha256") != sample_hash
        or package.get("sampling_policy_version") != SAMPLING_POLICY_VERSION
        or package.get("guideline_version") != GUIDELINE_VERSION
        or package.get("allowed_labels") != list(_STRATA)
        or re.fullmatch(r"[0-9a-f]{64}", str(package.get("candidate_queue_sha256"))) is None
        or package.get("labels_visible_from_other_annotator") is not False
        or package.get("model_training_authorized") is not False
    ):
        raise AnnotationSamplingError("annotation package metadata mismatch")
    tasks = package.get("tasks")
    if (
        not isinstance(tasks, list)
        or len(tasks) != len(records)
        or any(not isinstance(item, dict) for item in tasks)
    ):
        raise AnnotationSamplingError("annotation package task coverage mismatch")
    task_by_id = {str(item.get("clause_id")): item for item in tasks}
    if set(task_by_id) != set(by_id) or len(task_by_id) != len(tasks):
        raise AnnotationSamplingError("annotation package clause coverage mismatch")
    immutable_fields = (
        "clause_id",
        "document_id",
        "regulator",
        "source_url",
        "section_id",
        "heading",
        "page",
        "text",
        "text_sha256",
    )
    completed = 0
    for clause_id, task in task_by_id.items():
        source = by_id[clause_id]
        if any(task.get(field) != source.get(field) for field in immutable_fields):
            raise AnnotationSamplingError(f"annotation package task was modified: {clause_id}")
        if task.get("guideline_version") != GUIDELINE_VERSION:
            raise AnnotationSamplingError("annotation package guideline mismatch")
        label = task.get("label")
        annotated_at = task.get("annotated_at")
        if not isinstance(task.get("notes"), str):
            raise AnnotationSamplingError(f"annotation package notes must be text: {clause_id}")
        if label is None and annotated_at is None:
            continue
        if label not in _STRATA or not _aware_timestamp(annotated_at):
            raise AnnotationSamplingError(f"annotation package has incomplete task: {clause_id}")
        completed += 1
    annotator_id = package.get("annotator_id")
    if annotator_id is not None and (
        not isinstance(annotator_id, str) or not annotator_id.strip()
    ):
        raise AnnotationSamplingError("annotator ID must be non-empty text")
    if completed and annotator_id is None:
        raise AnnotationSamplingError("completed annotations require an annotator ID")
    return package


def annotation_progress_report(
    sample_path: Path, package_a_path: Path, package_b_path: Path
) -> dict[str, Any]:
    """Validate immutable tasks and report independent annotation progress/agreement."""
    sample_document = json.loads(sample_path.read_text(encoding="utf-8"))
    if (
        not isinstance(sample_document, dict)
        or sample_document.get("schema_version") != "regimpact-sampled-clauses-v1"
    ):
        raise AnnotationSamplingError("unsupported sampled-clause schema")
    records = sample_document.get("records")
    if (
        not isinstance(records, list)
        or not records
        or any(not isinstance(item, dict) for item in records)
    ):
        raise AnnotationSamplingError("sample must contain records")
    by_id = {str(item.get("clause_id")): item for item in records}
    if len(by_id) != len(records):
        raise AnnotationSamplingError("sample contains duplicate clause IDs")
    expected_sample_hash = sha256(_canonical(records).encode()).hexdigest()

    packages: dict[str, dict[str, Any]] = {}
    completed: dict[str, dict[str, str]] = {}
    label_counts: dict[str, Counter[str]] = {}
    immutable_fields = (
        "clause_id",
        "document_id",
        "regulator",
        "source_url",
        "section_id",
        "heading",
        "page",
        "text",
        "text_sha256",
    )
    for expected_slot, path in (("A", package_a_path), ("B", package_b_path)):
        package = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(package, dict)
            or package.get("schema_version") != "regimpact-blinded-annotation-package-v1"
            or package.get("annotator_slot") != expected_slot
            or package.get("package_id") != f"v0.6c4-pilot-{expected_slot.lower()}"
            or package.get("sample_sha256") != expected_sample_hash
            or package.get("sampling_policy_version") != SAMPLING_POLICY_VERSION
            or package.get("guideline_version") != GUIDELINE_VERSION
            or package.get("allowed_labels") != list(_STRATA)
            or re.fullmatch(r"[0-9a-f]{64}", str(package.get("candidate_queue_sha256"))) is None
            or package.get("labels_visible_from_other_annotator") is not False
            or package.get("model_training_authorized") is not False
        ):
            raise AnnotationSamplingError(f"package {expected_slot} metadata mismatch")
        tasks = package.get("tasks")
        if (
            not isinstance(tasks, list)
            or len(tasks) != len(records)
            or any(not isinstance(item, dict) for item in tasks)
        ):
            raise AnnotationSamplingError(f"package {expected_slot} task coverage mismatch")
        task_by_id = {str(item.get("clause_id")): item for item in tasks}
        if set(task_by_id) != set(by_id) or len(task_by_id) != len(tasks):
            raise AnnotationSamplingError(f"package {expected_slot} clause coverage mismatch")
        annotations: dict[str, str] = {}
        counts: Counter[str] = Counter()
        for clause_id, task in task_by_id.items():
            source = by_id[clause_id]
            if any(task.get(field) != source.get(field) for field in immutable_fields):
                raise AnnotationSamplingError(
                    f"package {expected_slot} task was modified: {clause_id}"
                )
            if task.get("guideline_version") != GUIDELINE_VERSION:
                raise AnnotationSamplingError(f"package {expected_slot} guideline mismatch")
            label = task.get("label")
            annotated_at = task.get("annotated_at")
            if not isinstance(task.get("notes"), str):
                raise AnnotationSamplingError(
                    f"package {expected_slot} notes must be text: {clause_id}"
                )
            if label is None and annotated_at is None:
                continue
            if label not in _STRATA or not _aware_timestamp(annotated_at):
                raise AnnotationSamplingError(
                    f"package {expected_slot} has an incomplete annotation: {clause_id}"
                )
            annotations[clause_id] = str(label)
            counts[str(label)] += 1
        annotator_id = package.get("annotator_id")
        if annotations and (not isinstance(annotator_id, str) or not annotator_id.strip()):
            raise AnnotationSamplingError(f"package {expected_slot} requires an annotator ID")
        packages[expected_slot] = package
        completed[expected_slot] = annotations
        label_counts[expected_slot] = counts

    identities = [packages[slot].get("annotator_id") for slot in ("A", "B")]
    if packages["A"].get("candidate_queue_sha256") != packages["B"].get(
        "candidate_queue_sha256"
    ):
        raise AnnotationSamplingError("annotation packages reference different candidate queues")
    if (
        all(isinstance(value, str) and value.strip() for value in identities)
        and identities[0] == identities[1]
    ):
        raise AnnotationSamplingError("annotator A and B must be different humans")
    overlap = set(completed["A"]) & set(completed["B"])
    agreements = sum(completed["A"][key] == completed["B"][key] for key in overlap)
    disagreements = sorted(key for key in overlap if completed["A"][key] != completed["B"][key])
    return {
        "schema_version": "regimpact-annotation-progress-v1",
        "status": "ready_for_adjudication"
        if len(overlap) == len(records)
        else "annotation_in_progress",
        "sample_sha256": expected_sample_hash,
        "sample_count": len(records),
        "completed": {slot: len(values) for slot, values in completed.items()},
        "label_counts": {
            slot: dict(sorted(values.items())) for slot, values in label_counts.items()
        },
        "dual_annotated": len(overlap),
        "agreements": agreements,
        "disagreements": len(disagreements),
        "disagreement_clause_ids": disagreements,
        "agreement_rate": round(agreements / len(overlap), 4) if overlap else None,
        "third_party_adjudication_required": bool(disagreements),
        "model_training_authorized": False,
    }


def export_completed_annotations(
    sample_path: Path, package_a_path: Path, package_b_path: Path
) -> tuple[tuple[Annotation, ...], dict[str, Any]]:
    """Export two complete, validated packages in the adjudicator's JSONL schema."""
    report = annotation_progress_report(sample_path, package_a_path, package_b_path)
    if report["status"] != "ready_for_adjudication":
        raise AnnotationSamplingError("both annotation packages must be complete before export")
    annotations: list[Annotation] = []
    for path in (package_a_path, package_b_path):
        package = json.loads(path.read_text(encoding="utf-8"))
        annotator_id = str(package["annotator_id"])
        for task in package["tasks"]:
            annotations.append(
                Annotation(
                    clause_id=str(task["clause_id"]),
                    annotator_id=annotator_id,
                    label=ClauseLabel(str(task["label"])),
                    guideline_version=str(task["guideline_version"]),
                    annotated_at=str(task["annotated_at"]),
                    notes=str(task.get("notes", "")),
                )
            )
    if len(annotations) != int(report["sample_count"]) * 2:
        raise AnnotationSamplingError("export does not contain two annotations per sampled clause")
    return tuple(annotations), report
