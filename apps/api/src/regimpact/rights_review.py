"""Human rights-review contracts for admitting acquired regulatory sources."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .corpus_acquisition import CorpusDocument

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECISIONS = {"pending", "approved", "rejected"}
_REQUIRED_CHECKS = (
    "authoritative_source_confirmed",
    "licence_scope_reviewed",
    "attribution_plan_confirmed",
    "accuracy_disclaimer_confirmed",
    "no_official_status_claim_confirmed",
    "portfolio_assignment_confirmed",
)
_REVIEW_BASIS = (
    "https://open.canada.ca/en/open-government-licence-canada",
    "https://laws-lois.justice.gc.ca/eng/regulations/si-97-5/",
    "https://laws-lois.justice.gc.ca/eng/faq/",
    (
        "https://github.com/justicecanada/laws-lois-xml/blob/"
        "a782c13dbf0c710f33d8b2adc3e42377c94d0626/LICENSE.md"
    ),
)


class RightsReviewError(RuntimeError):
    """Raised when review evidence is incomplete or inconsistent."""


def _aware(value: str) -> bool:
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class RightsReviewRecord:
    source_id: str
    document_id: str
    title: str
    regulator: str
    artifact_path: str
    artifact_sha256: str
    artifact_size_bytes: int
    official_url: str
    portfolio_basis_url: str
    artifact_url: str
    rights_basis_urls: tuple[str, ...]
    decision: str
    reviewer_name: str
    reviewed_at: str
    rationale: str
    checks: dict[str, bool]

    def __post_init__(self) -> None:
        if self.decision not in _DECISIONS:
            raise ValueError(f"unknown review decision: {self.decision}")
        if not _SHA256.fullmatch(self.artifact_sha256):
            raise ValueError("artifact_sha256 must be a lowercase SHA-256")
        if self.artifact_size_bytes <= 0:
            raise ValueError("artifact_size_bytes must be positive")
        if set(self.checks) != set(_REQUIRED_CHECKS):
            raise ValueError("review record must contain the exact required checks")
        if tuple(self.rights_basis_urls) != _REVIEW_BASIS:
            raise ValueError("review record must use the governed rights basis")
        if self.decision != "pending":
            if not self.reviewer_name.strip() or not _aware(self.reviewed_at):
                raise ValueError("completed review requires a named reviewer and aware timestamp")
            if len(self.rationale.strip()) < 20:
                raise ValueError("completed review requires a substantive rationale")
            if not all(self.checks.values()):
                raise ValueError("completed review requires every review check")


def _locked_artifacts(lock: dict[str, object]) -> dict[str, dict[str, object]]:
    artifacts = lock.get("artifacts")
    if not isinstance(artifacts, list):
        raise RightsReviewError("acquisition lock artifacts must be an array")
    return {str(item["source_id"]): item for item in artifacts}


def prepare_rights_review(
    documents: tuple[CorpusDocument, ...], lock: dict[str, object]
) -> tuple[RightsReviewRecord, ...]:
    locked = _locked_artifacts(lock)
    acquired_at = str(lock.get("acquired_at", ""))
    if not _aware(acquired_at):
        raise RightsReviewError("acquisition lock requires a timezone-aware acquired_at")
    records = []
    for document in documents:
        artifact = locked[document.source_id]
        artifact_size = artifact["artifact_size_bytes"]
        if not isinstance(artifact_size, int):
            raise RightsReviewError(f"invalid artifact size: {document.source_id}")
        records.append(
            RightsReviewRecord(
                source_id=document.source_id,
                document_id=document.document_id,
                title=document.title,
                regulator=document.regulator,
                artifact_path=f"{document.source_id}.xml",
                artifact_sha256=str(artifact["artifact_sha256"]),
                artifact_size_bytes=artifact_size,
                official_url=document.official_url,
                portfolio_basis_url=document.portfolio_basis_url,
                artifact_url=document.artifact_url,
                rights_basis_urls=_REVIEW_BASIS,
                decision="pending",
                reviewer_name="",
                reviewed_at="",
                rationale="",
                checks={name: False for name in _REQUIRED_CHECKS},
            )
        )
    return tuple(records)


def load_rights_review(path: Path) -> tuple[RightsReviewRecord, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "regimpact-rights-review-v1":
        raise RightsReviewError("unsupported rights-review schema")
    values = payload.get("records")
    if not isinstance(values, list):
        raise RightsReviewError("rights-review records must be an array")
    return tuple(
        RightsReviewRecord(
            **{
                **item,
                "rights_basis_urls": tuple(item["rights_basis_urls"]),
            }
        )
        for item in values
    )


def verify_review_coverage(
    documents: tuple[CorpusDocument, ...],
    lock: dict[str, object],
    records: tuple[RightsReviewRecord, ...],
) -> None:
    if len(records) != len({item.source_id for item in records}):
        raise RightsReviewError("duplicate source in rights review")
    by_source = {item.source_id: item for item in records}
    if set(by_source) != {item.source_id for item in documents}:
        raise RightsReviewError("rights review does not exactly cover the corpus manifest")
    locked = _locked_artifacts(lock)
    for document in documents:
        record = by_source[document.source_id]
        artifact = locked[document.source_id]
        expected = (
            document.document_id,
            document.title,
            document.regulator,
            document.official_url,
            document.portfolio_basis_url,
            document.artifact_url,
            artifact["artifact_sha256"],
            artifact["artifact_size_bytes"],
        )
        actual = (
            record.document_id,
            record.title,
            record.regulator,
            record.official_url,
            record.portfolio_basis_url,
            record.artifact_url,
            record.artifact_sha256,
            record.artifact_size_bytes,
        )
        if actual != expected:
            raise RightsReviewError(f"review evidence mismatch: {document.source_id}")


def finalize_rights_review(
    documents: tuple[CorpusDocument, ...],
    lock: dict[str, object],
    records: tuple[RightsReviewRecord, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    verify_review_coverage(documents, lock, records)
    incomplete = [item.source_id for item in records if item.decision != "approved"]
    if incomplete:
        raise RightsReviewError(
            f"all 25 sources require explicit approval; unresolved: {', '.join(incomplete)}"
        )
    by_source = {item.source_id: item for item in records}
    acquired_at = str(lock["acquired_at"])
    registry: list[dict[str, Any]] = []
    approvals: list[dict[str, str]] = []
    for document in documents:
        review = by_source[document.source_id]
        rights_basis = "; ".join(review.rights_basis_urls)
        registry.append(
            {
                "source_id": document.source_id,
                "document_id": document.document_id,
                "regulator": document.regulator,
                "jurisdiction": "Canada (federal)",
                "title": document.title,
                "version": document.repository_commit,
                "source_url": document.official_url,
                "rights_status": "approved",
                "rights_basis": rights_basis,
                "retrieved_at": acquired_at,
                "content_sha256": review.artifact_sha256,
            }
        )
        approvals.append(
            {
                "source_id": review.source_id,
                "document_id": review.document_id,
                "artifact_path": review.artifact_path,
                "artifact_sha256": review.artifact_sha256,
                "rights_basis_url": review.rights_basis_urls[0],
                "rights_reviewer": review.reviewer_name,
                "rights_reviewed_at": review.reviewed_at,
            }
        )
    review_payload = "\n".join(
        json.dumps(asdict(item), sort_keys=True, separators=(",", ":")) for item in records
    )
    receipt = {
        "schema_version": "regimpact-rights-review-receipt-v1",
        "status": "approved_for_annotation",
        "documents": len(documents),
        "regulators": len({item.regulator for item in documents}),
        "reviewers": sorted({item.reviewer_name for item in records}),
        "rights_review_sha256": sha256(review_payload.encode()).hexdigest(),
        "acquisition_lock_sha256": sha256(
            json.dumps(lock, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "annotation_authorized": True,
        "model_training_authorized": False,
    }
    return registry, approvals, receipt


def review_packet_payload(records: tuple[RightsReviewRecord, ...]) -> dict[str, object]:
    return {
        "schema_version": "regimpact-rights-review-v1",
        "instructions": (
            "A named human must review each source and replace pending fields. "
            "This file is evidence collection, not legal advice."
        ),
        "records": [asdict(item) for item in records],
    }
