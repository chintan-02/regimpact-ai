import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from regimpact.corpus_acquisition import (
    CorpusAcquisitionError,
    CorpusDocument,
    acquire_corpus,
    load_corpus_manifest,
    verify_acquisition_lock,
)

COMMIT = "a" * 40


def document(index: int, *, regulator: str | None = None) -> dict[str, str]:
    source_id = f"source-{index:02d}"
    return {
        "source_id": source_id,
        "document_id": f"document-{index:02d}",
        "title": f"Document {index}",
        "regulator": regulator or f"Regulator {index % 3}",
        "document_type": "act",
        "official_url": "https://laws-lois.justice.gc.ca/eng/acts/test/",
        "portfolio_basis_url": "https://example.gc.ca/legislation",
        "artifact_url": (
            "https://raw.githubusercontent.com/justicecanada/laws-lois-xml/"
            f"{COMMIT}/eng/acts/Test-{index}.xml"
        ),
        "repository_commit": COMMIT,
        "rights_status": "review_required",
        "rights_basis_url": "https://open.canada.ca/en/open-government-licence-canada",
    }


def write_manifest(path: Path, documents: list[dict[str, str]]) -> None:
    path.write_text(
        json.dumps({"schema_version": "regimpact-corpus-manifest-v1", "documents": documents})
    )


def test_manifest_requires_25_unique_documents_and_three_regulators(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    write_manifest(path, [document(index) for index in range(25)])
    loaded = load_corpus_manifest(path)
    assert len(loaded) == 25
    write_manifest(path, [document(index, regulator="One") for index in range(25)])
    with pytest.raises(CorpusAcquisitionError, match="three regulators"):
        load_corpus_manifest(path)


def test_artifact_url_is_pinned_and_allow_listed() -> None:
    payload = document(1)
    payload["artifact_url"] = "https://example.com/document.xml"
    with pytest.raises(ValueError, match="raw.githubusercontent.com"):
        CorpusDocument(**payload)


def test_acquisition_hashes_exact_xml_bytes(tmp_path: Path) -> None:
    item = CorpusDocument(**document(1))
    content = b'\xef\xbb\xbf<?xml version="1.0"?><Statute />\n'
    receipt = acquire_corpus(
        (item,),
        output_dir=tmp_path,
        fetch=lambda _: content,
        acquired_at=datetime(2026, 9, 4, tzinfo=UTC),
    )
    assert (tmp_path / "source-01.xml").read_bytes() == content
    assert receipt["status"] == "acquired_pending_rights_review"
    assert receipt["training_authorized"] is False
    assert receipt["artifacts"][0]["artifact_sha256"] == sha256(content).hexdigest()


def test_acquisition_refuses_overwrite_and_non_xml(tmp_path: Path) -> None:
    item = CorpusDocument(**document(1))
    with pytest.raises(CorpusAcquisitionError, match="not XML"):
        acquire_corpus((item,), output_dir=tmp_path, fetch=lambda _: b"not xml")
    (tmp_path / "source-01.xml").write_text("existing")
    with pytest.raises(CorpusAcquisitionError, match="overwrite"):
        acquire_corpus((item,), output_dir=tmp_path, fetch=lambda _: b"<?xml?>")


def test_lock_must_exactly_cover_manifest(tmp_path: Path) -> None:
    documents = tuple(CorpusDocument(**document(index)) for index in range(25))
    lock = {
        "schema_version": "regimpact-corpus-acquisition-v1",
        "status": "acquired_pending_rights_review",
        "repository_commit": COMMIT,
        "training_authorized": False,
        "artifacts": [
            {
                "source_id": item.source_id,
                "document_id": item.document_id,
                "artifact_sha256": "b" * 64,
                "artifact_size_bytes": 100,
            }
            for item in documents
        ],
    }
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    assert verify_acquisition_lock(documents, path)["training_authorized"] is False
    lock["artifacts"].pop()
    path.write_text(json.dumps(lock))
    with pytest.raises(CorpusAcquisitionError, match="exactly cover"):
        verify_acquisition_lock(documents, path)
