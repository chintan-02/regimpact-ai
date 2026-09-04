import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from regimpact.corpus_acquisition import CorpusDocument
from regimpact.rights_review import (
    RightsReviewError,
    finalize_rights_review,
    load_rights_review,
    prepare_rights_review,
    review_packet_payload,
    verify_review_coverage,
)

COMMIT = "a" * 40
CHECKS = {
    "authoritative_source_confirmed": True,
    "licence_scope_reviewed": True,
    "attribution_plan_confirmed": True,
    "accuracy_disclaimer_confirmed": True,
    "no_official_status_claim_confirmed": True,
    "portfolio_assignment_confirmed": True,
}


def document(index: int) -> CorpusDocument:
    return CorpusDocument(
        source_id=f"source-{index:02d}",
        document_id=f"document-{index:02d}",
        title=f"Document {index}",
        regulator=f"Regulator {index % 3}",
        document_type="act",
        official_url="https://laws-lois.justice.gc.ca/eng/acts/test/",
        portfolio_basis_url="https://example.gc.ca/legislation",
        artifact_url=(
            "https://raw.githubusercontent.com/justicecanada/laws-lois-xml/"
            f"{COMMIT}/eng/acts/Test-{index}.xml"
        ),
        repository_commit=COMMIT,
        rights_status="review_required",
        rights_basis_url="https://open.canada.ca/en/open-government-licence-canada",
    )


def corpus() -> tuple[tuple[CorpusDocument, ...], dict[str, object]]:
    documents = tuple(document(index) for index in range(25))
    lock = {
        "acquired_at": "2026-09-04T15:34:00+00:00",
        "artifacts": [
            {
                "source_id": item.source_id,
                "document_id": item.document_id,
                "artifact_sha256": f"{index:064x}",
                "artifact_size_bytes": index + 1,
            }
            for index, item in enumerate(documents)
        ],
    }
    return documents, lock


def test_prepare_creates_only_pending_human_records() -> None:
    documents, lock = corpus()
    records = prepare_rights_review(documents, lock)
    assert len(records) == 25
    assert {item.decision for item in records} == {"pending"}
    assert all(not any(item.checks.values()) for item in records)


def test_review_packet_round_trip(tmp_path: Path) -> None:
    documents, lock = corpus()
    records = prepare_rights_review(documents, lock)
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review_packet_payload(records)))
    loaded = load_rights_review(path)
    verify_review_coverage(documents, lock, loaded)
    assert loaded == records


def test_finalize_rejects_pending_decisions() -> None:
    documents, lock = corpus()
    records = prepare_rights_review(documents, lock)
    with pytest.raises(RightsReviewError, match="explicit approval"):
        finalize_rights_review(documents, lock, records)


def test_completed_review_requires_human_evidence() -> None:
    documents, lock = corpus()
    pending = prepare_rights_review(documents, lock)[0]
    with pytest.raises(ValueError, match="named reviewer"):
        replace(pending, decision="approved")
    with pytest.raises(ValueError, match="substantive rationale"):
        replace(
            pending,
            decision="approved",
            reviewer_name="Human Reviewer",
            reviewed_at="2026-09-04T09:00:00-06:00",
            checks=CHECKS,
        )


def test_finalize_emits_execution_contracts_but_not_training_authority() -> None:
    documents, lock = corpus()
    records = tuple(
        replace(
            item,
            decision="approved",
            reviewer_name="Human Reviewer",
            reviewed_at=datetime(2026, 9, 4, tzinfo=UTC).isoformat(),
            rationale="Reviewed official source and governed reuse terms for this artifact.",
            checks=CHECKS,
        )
        for item in prepare_rights_review(documents, lock)
    )
    registry, approvals, receipt = finalize_rights_review(documents, lock, records)
    assert len(registry) == len(approvals) == 25
    assert {item["rights_status"] for item in registry} == {"approved"}
    assert receipt["status"] == "approved_for_annotation"
    assert receipt["annotation_authorized"] is True
    assert receipt["model_training_authorized"] is False


def test_review_coverage_rejects_changed_evidence() -> None:
    documents, lock = corpus()
    records = prepare_rights_review(documents, lock)
    changed = (replace(records[0], title="Changed"), *records[1:])
    with pytest.raises(RightsReviewError, match="evidence mismatch"):
        verify_review_coverage(documents, lock, changed)
