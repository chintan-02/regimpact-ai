import json
from hashlib import sha256
from pathlib import Path

import pytest

from regimpact.annotation_campaign import (
    campaign_progress_report,
    export_campaign_annotations,
    prepare_campaign,
)
from regimpact.annotation_sampling import AnnotationSamplingError
from regimpact.clause_annotations import ClauseCandidate

TEXTS = (
    "A bank must retain each record for seven years.",
    "The institution shall report the transaction.",
    "No person shall disclose the information.",
    "The Minister may issue a licence.",
    "Account means an account maintained in Canada.",
    "Every company shall establish controls.",
    "This section applies to federal institutions.",
)


def _candidate(index: int) -> ClauseCandidate:
    document = index % 25
    text = f"{TEXTS[index % len(TEXTS)]} Example {index}."
    return ClauseCandidate(
        clause_id=f"clause-{index:04d}",
        source_id=f"source-{document:02d}",
        document_id=f"document-{document:02d}",
        regulator=f"Regulator {document % 5}",
        jurisdiction="Canada (federal)",
        title=f"Document {document}",
        version="a" * 40,
        source_url="https://laws.example/document",
        rights_status="approved",
        rights_basis="reviewed",
        retrieved_at="2026-09-04T16:00:00+00:00",
        content_sha256=f"{document:064x}",
        section_id=f"section-{index}",
        heading="Heading",
        page=None,
        position=index,
        text=text,
        text_sha256=sha256(text.encode()).hexdigest(),
    )


def _complete(path: Path, annotator: str) -> None:
    package = json.loads(path.read_text())
    package["annotator_id"] = annotator
    for task in package["tasks"]:
        task["label"] = "obligation"
        task["annotated_at"] = "2026-10-28T12:00:00-06:00"
    path.write_text(json.dumps(package))


def test_campaign_batches_are_unique_private_and_reportable(tmp_path: Path) -> None:
    candidates = tuple(_candidate(index) for index in range(550))
    manifest = prepare_campaign(
        candidates,
        candidate_queue_sha256="f" * 64,
        output_dir=tmp_path,
        target=500,
        batch_size=100,
        seed="fixed",
    )
    assert manifest["target"] == 500
    assert len(manifest["batches"]) == 5
    assert sum(batch["count"] for batch in manifest["batches"]) == 500
    assert len({batch["sample_sha256"] for batch in manifest["batches"]}) == 5
    assert len({batch["batch_id"] for batch in manifest["batches"]}) == 5
    assert (tmp_path / "batch-001/workspace-a.html").stat().st_mode & 0o077 == 0

    initial = campaign_progress_report(tmp_path)
    assert initial["status"] == "annotation_in_progress"
    assert initial["dual_annotated"] == 0

    for batch in manifest["batches"]:
        batch_dir = tmp_path / str(batch["batch_id"])
        completed_a = batch_dir / "completed-a.json"
        completed_b = batch_dir / "completed-b.json"
        completed_a.write_text((batch_dir / "package-a.json").read_text())
        completed_b.write_text((batch_dir / "package-b.json").read_text())
        _complete(completed_a, "human-a")
        _complete(completed_b, "human-b")

    report = campaign_progress_report(tmp_path)
    assert report["status"] == "ready_for_adjudication"
    assert report["dual_annotated"] == 500
    annotations, export_report = export_campaign_annotations(tmp_path)
    assert len(annotations) == 1000
    assert export_report["agreements"] == 500


def test_campaign_rejects_targets_below_production_gate(tmp_path: Path) -> None:
    with pytest.raises(AnnotationSamplingError, match="at least 500"):
        prepare_campaign(
            tuple(_candidate(index) for index in range(100)),
            candidate_queue_sha256="f" * 64,
            output_dir=tmp_path,
            target=70,
        )


def test_campaign_rejects_manifest_path_and_sample_tampering(tmp_path: Path) -> None:
    candidates = tuple(_candidate(index) for index in range(500))
    prepare_campaign(
        candidates,
        candidate_queue_sha256="f" * 64,
        output_dir=tmp_path,
        target=500,
        batch_size=100,
        seed="fixed",
    )
    manifest_path = tmp_path / "campaign-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["batches"][0]["sample"] = "../outside.json"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(AnnotationSamplingError, match="paths are invalid"):
        campaign_progress_report(tmp_path)

    prepare_campaign(
        candidates,
        candidate_queue_sha256="f" * 64,
        output_dir=tmp_path,
        target=500,
        batch_size=100,
        seed="fixed",
    )
    sample_path = tmp_path / "batch-001/sample.json"
    sample = json.loads(sample_path.read_text())
    sample["records"][0]["text"] = "tampered"
    sample_path.write_text(json.dumps(sample))
    with pytest.raises(AnnotationSamplingError, match="fingerprint mismatch"):
        campaign_progress_report(tmp_path)
