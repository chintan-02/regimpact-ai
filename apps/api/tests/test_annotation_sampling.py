import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pytest

from regimpact.annotation_sampling import (
    AnnotationSamplingError,
    annotation_progress_report,
    build_blinded_package,
    sample_payload,
    sample_pilot,
    sampling_report,
    sampling_stratum,
    verify_candidate_queue,
)
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


def candidate(index: int, document: int) -> ClauseCandidate:
    text = TEXTS[index % len(TEXTS)] + f" Example {index}."
    return ClauseCandidate(
        clause_id=f"clause-{document:02d}-{index:03d}",
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


def corpus() -> tuple[ClauseCandidate, ...]:
    return tuple(candidate(index, document) for document in range(25) for index in range(20))


def test_strata_are_enrichment_hints_not_hidden_labels() -> None:
    assert sampling_stratum(TEXTS[0]) == "record_retention_requirement"
    assert sampling_stratum(TEXTS[1]) == "reporting_requirement"
    assert sampling_stratum(TEXTS[2]) == "prohibition"
    assert sampling_stratum(TEXTS[3]) == "permission"
    assert sampling_stratum(TEXTS[4]) == "definition"
    assert sampling_stratum(TEXTS[5]) == "obligation"
    assert sampling_stratum(TEXTS[6]) == "non_obligation"


def test_pilot_is_deterministic_balanced_and_covers_every_document() -> None:
    candidates = corpus()
    first = sample_pilot(candidates, target=350, seed="fixed")
    second = sample_pilot(tuple(reversed(candidates)), target=350, seed="fixed")
    assert [item.candidate.clause_id for item in first] == [
        item.candidate.clause_id for item in second
    ]
    report = sampling_report(candidates, first, seed="fixed")
    assert report["sample_count"] == 350
    assert report["documents"] == 25
    assert report["regulators"] == 5
    assert set(report["sampling_strata"]) == {
        "definition",
        "non_obligation",
        "obligation",
        "permission",
        "prohibition",
        "record_retention_requirement",
        "reporting_requirement",
    }
    assert report["heuristics_are_labels"] is False


def test_blinded_packages_share_tasks_but_not_order_or_labels() -> None:
    sample = sample_pilot(corpus(), target=100, seed="fixed")
    package_a = build_blinded_package(
        sample, slot="A", seed="fixed", candidate_queue_sha256="f" * 64
    )
    package_b = build_blinded_package(
        sample, slot="B", seed="fixed", candidate_queue_sha256="f" * 64
    )
    assert {item["clause_id"] for item in package_a["tasks"]} == {
        item["clause_id"] for item in package_b["tasks"]
    }
    assert [item["clause_id"] for item in package_a["tasks"]] != [
        item["clause_id"] for item in package_b["tasks"]
    ]
    assert all(item["label"] is None for item in package_a["tasks"] + package_b["tasks"])
    assert package_a["annotator_id"] is None
    assert package_b["labels_visible_from_other_annotator"] is False


def test_receipt_binds_exact_candidate_queue(tmp_path: Path) -> None:
    candidates = corpus()
    payload = "\n".join(
        json.dumps(asdict(item), sort_keys=True, separators=(",", ":")) for item in candidates
    )
    receipt = {
        "schema_version": "regimpact-real-corpus-execution-v1",
        "status": "candidate_queue_ready",
        "candidates": len(candidates),
        "candidate_queue_sha256": sha256(payload.encode()).hexdigest(),
        "model_training_authorized": False,
    }
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    assert verify_candidate_queue(candidates, path) == receipt
    with pytest.raises(AnnotationSamplingError, match="fingerprint mismatch"):
        verify_candidate_queue(candidates[:-1] + (candidate(999, 0),), path)


def test_target_must_cover_every_document() -> None:
    with pytest.raises(AnnotationSamplingError, match="cover every document"):
        sample_pilot(corpus(), target=24)


def test_progress_report_requires_independent_annotators_and_immutable_tasks(
    tmp_path: Path,
) -> None:
    sample = sample_pilot(corpus(), target=25, seed="fixed")
    records = sample_payload(sample)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(
        json.dumps({"schema_version": "regimpact-sampled-clauses-v1", "records": records})
    )
    package_a = build_blinded_package(
        sample, slot="A", seed="fixed", candidate_queue_sha256="f" * 64
    )
    package_b = build_blinded_package(
        sample, slot="B", seed="fixed", candidate_queue_sha256="f" * 64
    )
    package_a["annotator_id"] = "human-a"
    package_b["annotator_id"] = "human-b"
    shared_clause_id = package_a["tasks"][0]["clause_id"]
    for package in (package_a, package_b):
        task = next(item for item in package["tasks"] if item["clause_id"] == shared_clause_id)
        task["label"] = "obligation"
        task["annotated_at"] = "2026-09-04T17:00:00+00:00"
    paths = []
    for name, package in (("a", package_a), ("b", package_b)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(package))
        paths.append(path)
    report = annotation_progress_report(sample_path, paths[0], paths[1])
    assert report["dual_annotated"] == 1
    assert report["agreement_rate"] == 1.0
    assert report["status"] == "annotation_in_progress"

    package_b["tasks"][0]["text"] = "tampered"
    paths[1].write_text(json.dumps(package_b))
    with pytest.raises(AnnotationSamplingError, match="task was modified"):
        annotation_progress_report(sample_path, paths[0], paths[1])
