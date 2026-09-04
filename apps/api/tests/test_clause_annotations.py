from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256

import pytest

from regimpact.clause_annotations import (
    GUIDELINE_VERSION,
    AdjudicatedDataset,
    Adjudication,
    Annotation,
    ClauseCandidate,
    ExtractedSection,
    SourceRecord,
    adjudicate_annotations,
    audit_dataset,
    build_candidates,
)
from regimpact.clause_classifier import ClauseLabel, LabelledClause

HASH = "a" * 64
STAMP = "2026-09-03T12:00:00Z"


def source(**updates: object) -> SourceRecord:
    values = {
        "source_id": "aer-directive-060",
        "document_id": "aer-060-v1",
        "regulator": "AER",
        "jurisdiction": "CA-AB",
        "title": "Directive 060",
        "version": "v1",
        "source_url": "https://www.aer.ca/example",
        "rights_status": "approved",
        "rights_basis": "Official regulator publication approved for this research dataset.",
        "retrieved_at": STAMP,
        "content_sha256": HASH,
    }
    values.update(updates)
    return SourceRecord(**values)  # type: ignore[arg-type]


def candidate(clause_id: str = "c1", *, document_id: str = "doc-1", text: str = "Firm must report incidents.") -> ClauseCandidate:
    return ClauseCandidate(
        clause_id=clause_id,
        source_id=f"source-{document_id}",
        document_id=document_id,
        regulator="AER",
        jurisdiction="CA-AB",
        title="Directive",
        version="v1",
        source_url="https://www.aer.ca/example",
        rights_status="approved",
        rights_basis="Official publication",
        retrieved_at=STAMP,
        content_sha256=HASH,
        section_id="4.2",
        heading="Reporting",
        page=12,
        position=1,
        text=text,
        text_sha256=sha256(text.encode()).hexdigest(),
    )


def annotation(clause_id: str, annotator: str, label: ClauseLabel) -> Annotation:
    return Annotation(clause_id, annotator, label, GUIDELINE_VERSION, STAMP)


def test_candidate_ids_are_stable_and_preserve_source_lineage() -> None:
    section = ExtractedSection("aer-060-v1", "4.2", "Reporting", 12, "Firm must report incidents.")
    first = build_candidates({"aer-060-v1": source()}, (section,))
    second = build_candidates({"aer-060-v1": source()}, (section,))
    assert first == second
    assert first[0].content_sha256 == HASH
    assert first[0].page == 12


def test_candidate_build_refuses_source_without_rights_approval() -> None:
    pending = source(rights_status="review_required", rights_basis="", retrieved_at=None, content_sha256="")
    section = ExtractedSection("aer-060-v1", "1", "Purpose", 1, "This directive applies.")
    with pytest.raises(ValueError, match="rights not approved"):
        build_candidates({"aer-060-v1": pending}, (section,))


def test_dual_agreement_produces_training_row_and_lineage() -> None:
    item = candidate()
    result = adjudicate_annotations(
        (item,),
        (
            annotation("c1", "annotator-a", ClauseLabel.REPORTING_REQUIREMENT),
            annotation("c1", "annotator-b", ClauseLabel.REPORTING_REQUIREMENT),
        ),
    )
    assert result.rows[0].label is ClauseLabel.REPORTING_REQUIREMENT
    assert result.lineage[0]["resolution"] == "agreement"
    assert result.agreement_rate == 1.0


def test_disagreement_requires_independent_adjudicator() -> None:
    item = candidate()
    votes = (
        annotation("c1", "annotator-a", ClauseLabel.OBLIGATION),
        annotation("c1", "annotator-b", ClauseLabel.REPORTING_REQUIREMENT),
    )
    unresolved = adjudicate_annotations((item,), votes)
    assert unresolved.unresolved_clause_ids == ("c1",)
    resolved = adjudicate_annotations(
        (item,),
        votes,
        (Adjudication("c1", "reviewer-c", ClauseLabel.REPORTING_REQUIREMENT, STAMP, "Reporting is the specific label."),),
    )
    assert resolved.rows[0].label is ClauseLabel.REPORTING_REQUIREMENT
    assert resolved.adjudicated_count == 1


def test_adjudication_for_agreed_clause_is_rejected() -> None:
    votes = (
        annotation("c1", "a", ClauseLabel.OBLIGATION),
        annotation("c1", "b", ClauseLabel.OBLIGATION),
    )
    decision = Adjudication("c1", "c", ClauseLabel.OBLIGATION, STAMP, "Unnecessary")
    with pytest.raises(ValueError, match="agreed clause"):
        adjudicate_annotations((candidate(),), votes, (decision,))


def test_mismatched_guideline_versions_are_rejected() -> None:
    votes = (
        annotation("c1", "a", ClauseLabel.OBLIGATION),
        replace(annotation("c1", "b", ClauseLabel.OBLIGATION), guideline_version="obsolete-v0"),
    )
    with pytest.raises(ValueError, match="guideline version"):
        adjudicate_annotations((candidate(),), votes)


def qualifying_dataset() -> AdjudicatedDataset:
    labels = tuple(ClauseLabel)
    rows = []
    lineage = []
    for index in range(525):
        document_id = f"doc-{index % 35}"
        label = labels[index % len(labels)]
        text = f"Unique regulatory clause {index} establishes requirement token {index * 17}."
        item = candidate(f"c-{index}", document_id=document_id, text=text)
        item = replace(item, regulator=f"R{index % 3}")
        rows.append(LabelledClause(item.clause_id, item.document_id, item.regulator, item.text, label))
        lineage.append(
            {**asdict(item), "label": label.value, "guideline_version": GUIDELINE_VERSION}
        )
    return AdjudicatedDataset(tuple(rows), tuple(lineage), (), 0.91, 47)


def test_qualifying_dataset_passes_construction_gates() -> None:
    report = audit_dataset(qualifying_dataset())
    assert report["status"] == "ready"
    assert report["examples"] == 525


def test_cross_document_exact_duplicate_blocks_dataset() -> None:
    dataset = qualifying_dataset()
    duplicate = replace(dataset.rows[1], text=dataset.rows[0].text)
    report = audit_dataset(replace(dataset, rows=(dataset.rows[0], duplicate, *dataset.rows[2:])))
    assert "cross_document_exact_duplicates" in report["failures"]


def test_duplicate_lineage_ids_block_dataset() -> None:
    dataset = qualifying_dataset()
    lineage = (dataset.lineage[0], dataset.lineage[0], *dataset.lineage[2:])
    report = audit_dataset(replace(dataset, lineage=lineage))
    assert "invalid_lineage" in report["failures"]


@pytest.mark.parametrize("field", ["text", "document_id", "regulator", "label", "text_sha256"])
def test_lineage_must_match_training_row(field: str) -> None:
    dataset = qualifying_dataset()
    first = dict(dataset.lineage[0])
    first[field] = "tampered"
    report = audit_dataset(replace(dataset, lineage=(first, *dataset.lineage[1:])))
    assert "invalid_lineage" in report["failures"]
