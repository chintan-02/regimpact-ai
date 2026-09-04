import json
from hashlib import sha256
from pathlib import Path

import pytest

from regimpact.annotation_sampling import (
    AnnotationSamplingError,
    build_blinded_package,
    sample_payload,
    sample_pilot,
    validate_annotation_package,
)
from regimpact.annotation_workspace import build_annotation_workspace
from regimpact.clause_annotations import ClauseCandidate


def _candidate(index: int) -> ClauseCandidate:
    text = f"Every institution must retain record {index} for seven years."
    return ClauseCandidate(
        clause_id=f"clause-{index}",
        source_id=f"source-{index}",
        document_id=f"document-{index}",
        regulator=f"Regulator {index % 3}",
        jurisdiction="Canada (federal)",
        title=f"Document {index}",
        version="a" * 40,
        source_url="https://laws.example/document",
        rights_status="approved",
        rights_basis="reviewed",
        retrieved_at="2026-09-04T16:00:00+00:00",
        content_sha256=f"{index:064x}",
        section_id=f"section-{index}",
        heading="Records",
        page=None,
        position=index,
        text=text,
        text_sha256=sha256(text.encode()).hexdigest(),
    )


def _files(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    sample = sample_pilot(tuple(_candidate(index) for index in range(25)), target=25, seed="x")
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(
        json.dumps({"schema_version": "regimpact-sampled-clauses-v1", "records": sample_payload(sample)})
    )
    package = build_blinded_package(
        sample, slot="A", seed="x", candidate_queue_sha256="f" * 64
    )
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package))
    return sample_path, package_path, package


def test_workspace_is_self_contained_blinded_and_offline(tmp_path: Path) -> None:
    sample_path, package_path, package = _files(tmp_path)
    document = build_annotation_workspace(sample_path, package_path)
    assert "RegImpact annotation package A" in document
    assert "connect-src 'none'" in document
    assert "labels_visible_from_other_annotator" in document
    assert str(package["sample_sha256"]) in document
    assert '<script src="' not in document
    assert "fetch(" not in document
    assert "XMLHttpRequest" not in document


def test_workspace_escapes_embedded_script_terminators(tmp_path: Path) -> None:
    sample_path, package_path, package = _files(tmp_path)
    attack = "</script><script>globalThis.compromised=true</script>"
    sample = json.loads(sample_path.read_text())
    sample["records"][0]["text"] = attack
    sample["records"][0]["text_sha256"] = sha256(attack.encode()).hexdigest()
    sample_path.write_text(json.dumps(sample))
    task = next(
        item
        for item in package["tasks"]
        if item["clause_id"] == sample["records"][0]["clause_id"]
    )
    task["text"] = attack
    task["text_sha256"] = sha256(attack.encode()).hexdigest()
    records = sample["records"]
    canonical = "\n".join(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in records)
    package["sample_sha256"] = sha256(canonical.encode()).hexdigest()
    package_path.write_text(json.dumps(package))
    document = build_annotation_workspace(sample_path, package_path)
    assert attack not in document
    assert "\\u003c/script\\u003e" in document


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("model_training_authorized", True),
        ("labels_visible_from_other_annotator", True),
        ("sampling_policy_version", "obsolete"),
        ("allowed_labels", ["obligation"]),
    ),
)
def test_package_validator_rejects_governance_metadata_changes(
    tmp_path: Path, field: str, value: object
) -> None:
    sample_path, package_path, package = _files(tmp_path)
    package[field] = value
    package_path.write_text(json.dumps(package))
    with pytest.raises(AnnotationSamplingError, match="metadata mismatch"):
        validate_annotation_package(sample_path, package_path, expected_slot="A")


def test_package_validator_accepts_partial_progress_and_rejects_bad_timestamp(
    tmp_path: Path,
) -> None:
    sample_path, package_path, package = _files(tmp_path)
    package["annotator_id"] = "human-a"
    package["tasks"][0]["label"] = "obligation"
    package["tasks"][0]["annotated_at"] = "2026-09-04T17:00:00+00:00"
    package_path.write_text(json.dumps(package))
    validate_annotation_package(sample_path, package_path, expected_slot="A")

    package["tasks"][0]["annotated_at"] = "2026-09-04 17:00:00"
    package_path.write_text(json.dumps(package))
    with pytest.raises(AnnotationSamplingError, match="incomplete task"):
        validate_annotation_package(sample_path, package_path, expected_slot="A")


def test_package_validator_rejects_modified_clause(tmp_path: Path) -> None:
    sample_path, package_path, package = _files(tmp_path)
    package["tasks"][0]["text"] = "modified"
    package_path.write_text(json.dumps(package))
    with pytest.raises(AnnotationSamplingError, match="task was modified"):
        validate_annotation_package(sample_path, package_path, expected_slot="A")
