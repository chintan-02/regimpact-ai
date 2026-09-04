"""Governed construction, annotation, adjudication, and audit of clause datasets."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .clause_classifier import ClauseLabel, LabelledClause, PromotionPolicy, dataset_fingerprint
from .clause_dataset import split_by_document
from .obligation_extraction import split_sentences

GUIDELINE_VERSION = "regimpact-clause-guidelines-v1"
APPROVED_RIGHTS_STATUS = "approved"
_RIGHTS_STATUSES = {APPROVED_RIGHTS_STATUS, "review_required", "rejected"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _aware_timestamp(value: str) -> bool:
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    document_id: str
    regulator: str
    jurisdiction: str
    title: str
    version: str
    source_url: str
    rights_status: str
    rights_basis: str = ""
    retrieved_at: str | None = None
    content_sha256: str = ""

    def __post_init__(self) -> None:
        required = (
            self.source_id,
            self.document_id,
            self.regulator,
            self.jurisdiction,
            self.title,
            self.version,
        )
        if not all(value.strip() for value in required):
            raise ValueError("source identity fields are required")
        if not self.source_url.startswith("https://"):
            raise ValueError("source_url must use HTTPS")
        if self.rights_status not in _RIGHTS_STATUSES:
            raise ValueError(f"unknown rights_status: {self.rights_status}")
        if self.rights_status == APPROVED_RIGHTS_STATUS:
            if not self.rights_basis.strip():
                raise ValueError("approved sources require a rights_basis")
            if not self.retrieved_at or not _aware_timestamp(self.retrieved_at):
                raise ValueError("approved sources require a timezone-aware retrieved_at")
            if not _SHA256.fullmatch(self.content_sha256):
                raise ValueError("approved sources require a lowercase SHA-256 content hash")


@dataclass(frozen=True, slots=True)
class ExtractedSection:
    document_id: str
    section_id: str
    heading: str
    page: int | None
    text: str


@dataclass(frozen=True, slots=True)
class ClauseCandidate:
    clause_id: str
    source_id: str
    document_id: str
    regulator: str
    jurisdiction: str
    title: str
    version: str
    source_url: str
    rights_status: str
    rights_basis: str
    retrieved_at: str
    content_sha256: str
    section_id: str
    heading: str
    page: int | None
    position: int
    text: str
    text_sha256: str


@dataclass(frozen=True, slots=True)
class Annotation:
    clause_id: str
    annotator_id: str
    label: ClauseLabel
    guideline_version: str
    annotated_at: str
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.clause_id.strip() or not self.annotator_id.strip():
            raise ValueError("clause_id and annotator_id are required")
        if not _aware_timestamp(self.annotated_at):
            raise ValueError("annotated_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Adjudication:
    clause_id: str
    reviewer_id: str
    label: ClauseLabel
    adjudicated_at: str
    rationale: str

    def __post_init__(self) -> None:
        if not all((self.clause_id.strip(), self.reviewer_id.strip(), self.rationale.strip())):
            raise ValueError("adjudication identity and rationale are required")
        if not _aware_timestamp(self.adjudicated_at):
            raise ValueError("adjudicated_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AdjudicatedDataset:
    rows: tuple[LabelledClause, ...]
    lineage: tuple[dict[str, Any], ...]
    unresolved_clause_ids: tuple[str, ...]
    agreement_rate: float
    adjudicated_count: int


def load_json_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        values = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    else:
        value = json.loads(path.read_text())
        values = value if isinstance(value, list) else value.get("sources", [])
    if not all(isinstance(item, dict) for item in values):
        raise ValueError(f"{path} must contain JSON objects")
    return values


def load_source_registry(path: Path) -> dict[str, SourceRecord]:
    sources = tuple(SourceRecord(**item) for item in load_json_records(path))
    result = {item.document_id: item for item in sources}
    if len(result) != len(sources):
        raise ValueError("duplicate document_id in source registry")
    return result


def load_sections(path: Path) -> tuple[ExtractedSection, ...]:
    return tuple(ExtractedSection(**item) for item in load_json_records(path))


def build_candidates(
    sources: dict[str, SourceRecord], sections: Iterable[ExtractedSection]
) -> tuple[ClauseCandidate, ...]:
    candidates: list[ClauseCandidate] = []
    seen_text: set[tuple[str, str]] = set()
    for section in sections:
        source = sources.get(section.document_id)
        if source is None:
            raise ValueError(f"document not registered: {section.document_id}")
        if source.rights_status != APPROVED_RIGHTS_STATUS:
            raise ValueError(f"source rights not approved: {source.source_id}")
        assert source.retrieved_at is not None
        for position, text in enumerate(split_sentences(section.text), start=1):
            normalized = " ".join(text.split())
            text_hash = sha256(normalized.encode()).hexdigest()
            duplicate_key = (source.document_id, text_hash)
            if duplicate_key in seen_text:
                continue
            seen_text.add(duplicate_key)
            identity = ":".join(
                (source.document_id, section.section_id, str(section.page), str(position), text_hash)
            )
            candidates.append(
                ClauseCandidate(
                    clause_id=f"clause-{sha256(identity.encode()).hexdigest()[:24]}",
                    source_id=source.source_id,
                    document_id=source.document_id,
                    regulator=source.regulator,
                    jurisdiction=source.jurisdiction,
                    title=source.title,
                    version=source.version,
                    source_url=source.source_url,
                    rights_status=source.rights_status,
                    rights_basis=source.rights_basis,
                    retrieved_at=source.retrieved_at,
                    content_sha256=source.content_sha256,
                    section_id=section.section_id,
                    heading=section.heading,
                    page=section.page,
                    position=position,
                    text=normalized,
                    text_sha256=text_hash,
                )
            )
    return tuple(candidates)


def load_annotations(path: Path) -> tuple[Annotation, ...]:
    return tuple(
        Annotation(**{**item, "label": ClauseLabel(item["label"])})
        for item in load_json_records(path)
    )


def load_adjudications(path: Path) -> tuple[Adjudication, ...]:
    return tuple(
        Adjudication(**{**item, "label": ClauseLabel(item["label"])})
        for item in load_json_records(path)
    )


def adjudicate_annotations(
    candidates: Iterable[ClauseCandidate],
    annotations: Iterable[Annotation],
    adjudications: Iterable[Adjudication] = (),
) -> AdjudicatedDataset:
    adjudications = tuple(adjudications)
    candidate_by_id = {item.clause_id: item for item in candidates}
    grouped: dict[str, list[Annotation]] = defaultdict(list)
    for annotation in annotations:
        if annotation.clause_id not in candidate_by_id:
            raise ValueError(f"annotation references unknown clause: {annotation.clause_id}")
        grouped[annotation.clause_id].append(annotation)
    decisions = {item.clause_id: item for item in adjudications}
    if len(decisions) != len(adjudications):
        raise ValueError("duplicate adjudication")
    if unknown := set(decisions) - set(candidate_by_id):
        raise ValueError(f"adjudication references unknown clause: {min(unknown)}")

    rows: list[LabelledClause] = []
    lineage: list[dict[str, Any]] = []
    unresolved: list[str] = []
    agreements = 0
    dual_count = 0
    adjudicated_count = 0
    used_decisions: set[str] = set()
    for clause_id, candidate in candidate_by_id.items():
        votes = grouped.get(clause_id, [])
        annotators = {item.annotator_id for item in votes}
        if len(votes) != 2 or len(annotators) != 2:
            unresolved.append(clause_id)
            continue
        guideline_versions = {item.guideline_version for item in votes}
        if guideline_versions != {GUIDELINE_VERSION}:
            raise ValueError(f"unsupported or mismatched guideline version: {clause_id}")
        dual_count += 1
        if votes[0].label == votes[1].label:
            label = votes[0].label
            agreements += 1
            resolution = "agreement"
            if clause_id in decisions:
                raise ValueError(f"adjudication supplied for an agreed clause: {clause_id}")
        else:
            decision = decisions.get(clause_id)
            if decision is None or decision.reviewer_id in annotators:
                unresolved.append(clause_id)
                continue
            label = decision.label
            resolution = "adjudicated"
            adjudicated_count += 1
            used_decisions.add(clause_id)
        rows.append(
            LabelledClause(
                clause_id=clause_id,
                document_id=candidate.document_id,
                regulator=candidate.regulator,
                text=candidate.text,
                label=label,
            )
        )
        lineage.append(
            {
                **asdict(candidate),
                "label": label.value,
                "guideline_version": GUIDELINE_VERSION,
                "annotators": sorted(annotators),
                "resolution": resolution,
                "adjudicator": decisions[clause_id].reviewer_id if resolution == "adjudicated" else None,
            }
        )
    if extra := set(decisions) - used_decisions:
        raise ValueError(f"unused adjudication: {min(extra)}")
    return AdjudicatedDataset(
        rows=tuple(rows),
        lineage=tuple(lineage),
        unresolved_clause_ids=tuple(sorted(unresolved)),
        agreement_rate=agreements / dual_count if dual_count else 0.0,
        adjudicated_count=adjudicated_count,
    )


def _shingles(text: str, size: int = 3) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {tuple(words[index : index + size]) for index in range(max(1, len(words) - size + 1))}


def audit_dataset(dataset: AdjudicatedDataset) -> dict[str, Any]:
    policy = PromotionPolicy()
    counts = Counter(row.label.value for row in dataset.rows)
    documents = {row.document_id for row in dataset.rows}
    regulators = {row.regulator for row in dataset.rows}
    failures: list[str] = []
    if len(dataset.rows) < policy.minimum_examples:
        failures.append("insufficient_examples")
    if len(documents) < policy.minimum_documents:
        failures.append("insufficient_documents")
    if len(regulators) < policy.minimum_regulators:
        failures.append("insufficient_regulators")
    if any(counts[label.value] < 30 for label in ClauseLabel):
        failures.append("insufficient_examples_per_class")
    if dataset.unresolved_clause_ids:
        failures.append("unresolved_annotations")

    lineage_ids = [str(item.get("clause_id", "")) for item in dataset.lineage]
    row_ids = [row.clause_id for row in dataset.rows]
    if len(set(lineage_ids)) != len(lineage_ids) or set(lineage_ids) != set(row_ids):
        failures.append("invalid_lineage")
    else:
        rows_by_id = {row.clause_id: row for row in dataset.rows}
        for item in dataset.lineage:
            row = rows_by_id[str(item["clause_id"])]
            expected_text_hash = sha256(row.text.encode()).hexdigest()
            if (
                item.get("rights_status") != APPROVED_RIGHTS_STATUS
                or not _SHA256.fullmatch(str(item.get("content_sha256", "")))
                or item.get("text_sha256") != expected_text_hash
                or not item.get("source_url")
                or item.get("document_id") != row.document_id
                or item.get("regulator") != row.regulator
                or item.get("text") != row.text
                or item.get("label") != row.label.value
                or item.get("guideline_version") != GUIDELINE_VERSION
            ):
                failures.append("invalid_lineage")
                break

    hashes: dict[str, set[str]] = defaultdict(set)
    for row in dataset.rows:
        hashes[sha256(" ".join(row.text.split()).lower().encode()).hexdigest()].add(row.document_id)
    exact_duplicates = sorted(key for key, docs in hashes.items() if len(docs) > 1)
    if exact_duplicates:
        failures.append("cross_document_exact_duplicates")

    near_duplicates: list[tuple[str, str]] = []
    shingles = [(row, _shingles(row.text)) for row in dataset.rows]
    for index, (left, left_set) in enumerate(shingles):
        for right, right_set in shingles[index + 1 :]:
            if left.document_id == right.document_id or not left_set or not right_set:
                continue
            similarity = len(left_set & right_set) / len(left_set | right_set)
            if similarity >= 0.9:
                near_duplicates.append((left.clause_id, right.clause_id))
    if near_duplicates:
        failures.append("cross_document_near_duplicates")

    try:
        split = split_by_document(dataset.rows)
        split_counts = {
            "train": len(split.train),
            "validation": len(split.validation),
            "test": len(split.test),
        }
    except ValueError:
        failures.append("invalid_document_split")
        split_counts = {}

    return {
        "status": "ready" if not failures else "blocked",
        "failures": sorted(set(failures)),
        "dataset_sha256": dataset_fingerprint(dataset.rows) if dataset.rows else None,
        "examples": len(dataset.rows),
        "documents": len(documents),
        "regulators": len(regulators),
        "labels": dict(sorted(counts.items())),
        "agreement_rate": round(dataset.agreement_rate, 4),
        "adjudicated_count": dataset.adjudicated_count,
        "unresolved_count": len(dataset.unresolved_clause_ids),
        "split_examples": split_counts,
        "exact_duplicate_groups": len(exact_duplicates),
        "near_duplicate_pairs": near_duplicates,
    }


def write_jsonl(path: Path, values: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for value in values:
            payload = asdict(value) if hasattr(value, "__dataclass_fields__") else value
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
