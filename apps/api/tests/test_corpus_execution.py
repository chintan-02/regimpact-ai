from __future__ import annotations

import json
from hashlib import sha256

import pytest

from regimpact.clause_annotations import SourceRecord
from regimpact.corpus_execution import (
    CorpusExecutionError,
    SourceApproval,
    execute_corpus,
    verify_source_artifacts,
)

STAMP = "2026-09-04T12:00:00+00:00"


def evidence(tmp_path):
    artifact = tmp_path / "source.pdf"
    artifact.write_bytes(b"immutable official source bytes")
    digest = sha256(artifact.read_bytes()).hexdigest()
    source = SourceRecord(
        source_id="source-1",
        document_id="doc-v1",
        regulator="Regulator",
        jurisdiction="CA",
        title="Official document",
        version="v1",
        source_url="https://regulator.example/document",
        rights_status="approved",
        rights_basis="Approved under the recorded official reuse terms.",
        retrieved_at=STAMP,
        content_sha256=digest,
    )
    approval = SourceApproval(
        source_id="source-1",
        document_id="doc-v1",
        artifact_path="source.pdf",
        artifact_sha256=digest,
        rights_basis_url="https://regulator.example/terms",
        rights_reviewer="rights-reviewer",
        rights_reviewed_at=STAMP,
    )
    return source, approval, artifact


def test_real_corpus_execution_binds_bytes_sections_and_candidates(tmp_path) -> None:
    source, approval, _ = evidence(tmp_path)
    sections = tmp_path / "sections.jsonl"
    sections.write_text(
        json.dumps(
            {
                "document_id": "doc-v1",
                "section_id": "4.2",
                "heading": "Reporting",
                "page": 12,
                "text": "A firm must report the incident. Records must be retained for seven years.",
            }
        )
        + "\n"
    )
    candidates, receipt = execute_corpus(
        {source.document_id: source},
        (approval,),
        artifact_root=tmp_path,
        sections_path=sections,
    )
    assert len(candidates) == 2
    assert receipt["status"] == "candidate_queue_ready"
    assert receipt["model_training_authorized"] is False


def test_source_artifact_tampering_fails_closed(tmp_path) -> None:
    source, approval, artifact = evidence(tmp_path)
    artifact.write_bytes(b"tampered")
    with pytest.raises(CorpusExecutionError, match="hash mismatch"):
        verify_source_artifacts(
            {source.document_id: source}, (approval,), artifact_root=tmp_path
        )


def test_sections_must_cover_exact_approved_document_set(tmp_path) -> None:
    source, approval, _ = evidence(tmp_path)
    sections = tmp_path / "sections.jsonl"
    sections.write_text(
        json.dumps(
            {
                "document_id": "other-document",
                "section_id": "1",
                "heading": "Scope",
                "page": 1,
                "text": "This is a clause.",
            }
        )
        + "\n"
    )
    with pytest.raises(CorpusExecutionError, match="exactly cover"):
        execute_corpus(
            {source.document_id: source},
            (approval,),
            artifact_root=tmp_path,
            sections_path=sections,
        )
