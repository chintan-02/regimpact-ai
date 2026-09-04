import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pytest

from regimpact.clause_annotations import SourceRecord
from regimpact.corpus_execution import SourceApproval
from regimpact.xml_section_extraction import (
    XmlSectionExtractionError,
    extract_approved_corpus_sections,
    extract_xml_sections,
)

XML = b'''<?xml version="1.0" encoding="utf-8"?>
<Statute xmlns:lims="http://justice.gc.ca/lims">
  <Body>
    <Heading level="1"><TitleText>Compliance</TitleText></Heading>
    <Section lims:id="101">
      <MarginalNote>Records</MarginalNote><Label>7</Label>
      <Text>An institution must retain each record.</Text>
      <Subsection><Label>(1)</Label><Text>It shall protect the record.</Text></Subsection>
      <HistoricalNote><HistoricalNoteSubItem>2020, c. 1</HistoricalNoteSubItem></HistoricalNote>
    </Section>
    <Section lims:id="102"><Label>8</Label><Text>A report may be filed electronically.</Text></Section>
  </Body>
  <Schedule><Section><Label>99</Label><Text>Historical schedule text.</Text></Section></Schedule>
</Statute>'''


def test_extracts_only_body_sections_with_lineage(tmp_path: Path) -> None:
    path = tmp_path / "law.xml"
    path.write_bytes(b"\xef\xbb\xbf" + XML)
    sections = extract_xml_sections(path, document_id="doc-1")
    assert [item.section_id for item in sections] == ["section-7", "section-8"]
    assert sections[0].heading == "Records"
    assert sections[0].text == "An institution must retain each record. It shall protect the record."
    assert "2020" not in sections[0].text
    assert sections[1].heading == "Compliance"
    assert all(item.page is None for item in sections)


def test_rejects_xml_without_body_sections(tmp_path: Path) -> None:
    path = tmp_path / "empty.xml"
    path.write_text("<Statute><Body /></Statute>")
    with pytest.raises(XmlSectionExtractionError, match="no non-empty Body sections"):
        extract_xml_sections(path, document_id="doc-1")


def test_approved_extraction_verifies_hashes_and_emits_receipt(tmp_path: Path) -> None:
    artifact = tmp_path / "source-1.xml"
    artifact.write_bytes(XML)
    digest = sha256(XML).hexdigest()
    source = SourceRecord(
        source_id="source-1",
        document_id="doc-1",
        regulator="Regulator",
        jurisdiction="Canada (federal)",
        title="Law",
        version="a" * 40,
        source_url="https://example.gc.ca/law",
        rights_status="approved",
        rights_basis="reviewed terms",
        retrieved_at="2026-09-04T15:34:00+00:00",
        content_sha256=digest,
    )
    approval = SourceApproval(
        source_id="source-1",
        document_id="doc-1",
        artifact_path=artifact.name,
        artifact_sha256=digest,
        rights_basis_url="https://example.gc.ca/terms",
        rights_reviewer="Human Reviewer",
        rights_reviewed_at="2026-09-04T16:00:00+00:00",
    )
    sections, receipt = extract_approved_corpus_sections(
        {source.document_id: source}, (approval,), artifact_root=tmp_path
    )
    assert len(sections) == 2
    assert receipt["documents"] == 1
    assert receipt["model_training_authorized"] is False
    expected = "\n".join(
        json.dumps(asdict(item), sort_keys=True, separators=(",", ":")) for item in sections
    )
    assert receipt["sections_sha256"] == sha256(expected.encode()).hexdigest()


def test_approved_extraction_rejects_tampered_xml(tmp_path: Path) -> None:
    artifact = tmp_path / "source-1.xml"
    artifact.write_bytes(XML)
    source = SourceRecord(
        source_id="source-1", document_id="doc-1", regulator="R", jurisdiction="Canada",
        title="Law", version="v1", source_url="https://example.gc.ca/law",
        rights_status="approved", rights_basis="basis",
        retrieved_at="2026-09-04T15:34:00+00:00", content_sha256="0" * 64,
    )
    approval = SourceApproval(
        source_id="source-1", document_id="doc-1", artifact_path=artifact.name,
        artifact_sha256="0" * 64, rights_basis_url="https://example.gc.ca/terms",
        rights_reviewer="Reviewer", rights_reviewed_at="2026-09-04T16:00:00+00:00",
    )
    with pytest.raises(RuntimeError, match="hash mismatch"):
        extract_approved_corpus_sections({"doc-1": source}, (approval,), artifact_root=tmp_path)
