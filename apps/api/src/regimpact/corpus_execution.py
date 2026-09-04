"""Evidence contracts for executing the classifier pipeline on a real corpus."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .clause_annotations import ClauseCandidate, SourceRecord, build_candidates, load_sections

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CorpusExecutionError(RuntimeError):
    """Raised when source or execution evidence fails closed."""


def _aware(value: str) -> bool:
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class SourceApproval:
    source_id: str
    document_id: str
    artifact_path: str
    artifact_sha256: str
    rights_basis_url: str
    rights_reviewer: str
    rights_reviewed_at: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.source_id,
                self.document_id,
                self.artifact_path,
                self.rights_reviewer,
            )
        ):
            raise ValueError("source approval identity fields are required")
        if not _SHA256.fullmatch(self.artifact_sha256):
            raise ValueError("artifact_sha256 must be a lowercase SHA-256")
        if not self.rights_basis_url.startswith("https://"):
            raise ValueError("rights_basis_url must use HTTPS")
        if not _aware(self.rights_reviewed_at):
            raise ValueError("rights_reviewed_at must be timezone-aware")


def load_source_approvals(path: Path) -> tuple[SourceApproval, ...]:
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise CorpusExecutionError("source approvals must be a JSON array")
    approvals = tuple(SourceApproval(**item) for item in values)
    if len({item.source_id for item in approvals}) != len(approvals):
        raise CorpusExecutionError("duplicate source approval")
    return approvals


def verify_source_artifacts(
    sources: dict[str, SourceRecord],
    approvals: tuple[SourceApproval, ...],
    *,
    artifact_root: Path,
) -> dict[str, str]:
    """Bind approved registry records to immutable local bytes and human rights review."""
    approved_sources = {
        item.source_id: item for item in sources.values() if item.rights_status == "approved"
    }
    approval_by_source = {item.source_id: item for item in approvals}
    if set(approved_sources) != set(approval_by_source):
        raise CorpusExecutionError("source approvals do not exactly match approved registry sources")
    hashes: dict[str, str] = {}
    root = artifact_root.resolve()
    for source_id, source in approved_sources.items():
        approval = approval_by_source[source_id]
        if approval.document_id != source.document_id:
            raise CorpusExecutionError(f"document mismatch for source: {source_id}")
        artifact = (root / approval.artifact_path).resolve()
        if not artifact.is_relative_to(root) or not artifact.is_file():
            raise CorpusExecutionError(f"source artifact missing or outside root: {source_id}")
        digest = sha256(artifact.read_bytes()).hexdigest()
        if digest != approval.artifact_sha256 or digest != source.content_sha256:
            raise CorpusExecutionError(f"source artifact hash mismatch: {source_id}")
        hashes[source_id] = digest
    return hashes


def execute_corpus(
    sources: dict[str, SourceRecord],
    approvals: tuple[SourceApproval, ...],
    *,
    artifact_root: Path,
    sections_path: Path,
) -> tuple[tuple[ClauseCandidate, ...], dict[str, Any]]:
    hashes = verify_source_artifacts(sources, approvals, artifact_root=artifact_root)
    sections = load_sections(sections_path)
    approved_documents = {
        item.document_id for item in sources.values() if item.rights_status == "approved"
    }
    section_documents = {item.document_id for item in sections}
    if approved_documents != section_documents:
        raise CorpusExecutionError(
            "extracted sections do not exactly cover approved document/version groups"
        )
    candidates = build_candidates(sources, sections)
    if not candidates:
        raise CorpusExecutionError("real-corpus execution produced no clause candidates")
    candidate_payload = "\n".join(
        json.dumps(asdict(item), sort_keys=True, separators=(",", ":"))
        for item in candidates
    )
    registry_payload = "\n".join(
        json.dumps(asdict(item), sort_keys=True, separators=(",", ":"))
        for item in sorted(sources.values(), key=lambda value: value.source_id)
    )
    approved_source_records = tuple(
        item for item in sources.values() if item.rights_status == "approved"
    )
    receipt = {
        "schema_version": "regimpact-real-corpus-execution-v1",
        "status": "candidate_queue_ready",
        "documents": len(approved_documents),
        "regulators": len({item.regulator for item in approved_source_records}),
        "sections": len(sections),
        "candidates": len(candidates),
        "source_artifact_sha256": dict(sorted(hashes.items())),
        "source_registry_sha256": sha256(registry_payload.encode()).hexdigest(),
        "sections_sha256": sha256(sections_path.read_bytes()).hexdigest(),
        "candidate_queue_sha256": sha256(candidate_payload.encode()).hexdigest(),
        "human_annotation_required": True,
        "model_training_authorized": False,
    }
    return candidates, receipt
