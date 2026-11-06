"""Reproducible evidence packaging for single-human silver-label evaluation."""

from __future__ import annotations

import json
import re
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any

from .annotation_sampling import AnnotationSamplingError
from .silver_labeling import evaluate_human_silver_labels

EVIDENCE_SCHEMA_VERSION = "regimpact-human-silver-evidence-package-v1"
REPORT_FILENAME = "human-silver-evaluation-report.json"
DISAGREEMENTS_FILENAME = "human-silver-disagreements.jsonl"
SUMMARY_FILENAME = "experiment-summary.md"
RECEIPT_FILENAME = "evidence-receipt.json"

_GOVERNED_THRESHOLD_ARTIFACTS = (
    "silver-consensus-report.json",
    "silver-adjudication-manifest.json",
    "silver-adjudication-report.json",
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _jsonl_bytes(values: list[dict[str, Any]]) -> bytes:
    return "".join(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n" for value in values
    ).encode()


def _sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _file_evidence(path: Path, *, name: str) -> dict[str, str | int]:
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise AnnotationSamplingError(f"missing evaluation evidence input: {name}") from exc
    return {"name": name, "sha256": _sha256_bytes(value), "size_bytes": len(value)}


def _percentage(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def _summary(report: dict[str, Any]) -> str:
    labelers = report["labelers"]
    agreement = report["agreement"]
    rows = []
    for slot in ("A", "B"):
        metrics = labelers[slot]
        rows.append(
            f"| {slot} | {metrics['labeler_id']} | {metrics['model_id']} | "
            f"{_percentage(metrics['accuracy'])} | {_percentage(metrics['macro_f1'])} | "
            f"{_percentage(metrics['weighted_f1'])} |"
        )

    macro_a = float(labelers["A"]["macro_f1"])
    macro_b = float(labelers["B"]["macro_f1"])
    if macro_a == macro_b:
        comparison = "The two labelers have equal macro-F1 on this holdout."
    else:
        better = "A" if macro_a > macro_b else "B"
        comparison = f"Labeler {better} has the higher macro-F1 on this holdout."

    per_class_rows = []
    for label, metrics_a in labelers["A"]["per_class"].items():
        metrics_b = labelers["B"]["per_class"][label]
        per_class_rows.append(
            f"| {label} | {metrics_a['support']} | {_percentage(metrics_a['precision'])} | "
            f"{_percentage(metrics_a['recall'])} | {_percentage(metrics_a['f1'])} | "
            f"{_percentage(metrics_b['precision'])} | {_percentage(metrics_b['recall'])} | "
            f"{_percentage(metrics_b['f1'])} |"
        )

    return "\n".join(
        [
            "# v0.6C Single-Human Silver-Label Evaluation Summary",
            "",
            "## Scope",
            "",
            f"- Evaluated clauses: {report['evaluation_clauses']}",
            "- Reference: one human annotator on a document-held-out sample",
            "- Adjudicated gold data: no",
            "- Held out from training: yes",
            "- Model training authorized by this package: no",
            "- Production promotion authorized by this package: no",
            "",
            "## Labeler metrics",
            "",
            "| Slot | Labeler | Model | Accuracy | Macro-F1 | Weighted-F1 |",
            "| --- | --- | --- | ---: | ---: | ---: |",
            *rows,
            "",
            "## Per-class metrics",
            "",
            "| Label | Human support | A precision | A recall | A F1 | B precision | B recall | B F1 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            *per_class_rows,
            "",
            "## Agreement and review",
            "",
            f"- Raw A/B agreement: {_percentage(agreement['raw_agreement'])}",
            f"- Consensus coverage: {_percentage(agreement['consensus_coverage'])}",
            (
                f"- Consensus accuracy against the single-human reference: "
                f"{_percentage(agreement['consensus_accuracy'])}"
            ),
            f"- Governed confidence threshold: {agreement['minimum_confidence']:.2f}",
            (
                f"- High-confidence consensus coverage: "
                f"{_percentage(agreement['high_confidence_consensus_coverage'])}"
            ),
            (
                f"- High-confidence consensus accuracy: "
                f"{_percentage(agreement['high_confidence_consensus_accuracy'])}"
            ),
            (
                f"- Disagreement or error records requiring review: "
                f"{report['disagreement_or_error_records']}"
            ),
            "",
            "## Exploratory conclusion",
            "",
            comparison,
            (
                "The result is exploratory because the reference labels were produced by one human "
                "annotator and were not independently adjudicated. Per-class metrics and the "
                "text-free disagreement records must be reviewed before changing prompts, models, "
                "thresholds or training data."
            ),
            "",
            "## Governance decision",
            "",
            (
                "This evidence package does not convert the human labels into ground truth, "
                "authorize model training, or authorize production promotion. A governed "
                "multi-human review and adjudication process remains required for those decisions."
            ),
            "",
        ]
    )


def package_human_silver_evaluation(
    experiment_dir: Path,
    completed_path: Path,
    output_dir: Path,
    *,
    implementation_commit: str,
) -> dict[str, Any]:
    """Validate an evaluation and atomically write a text-free, hash-bound evidence package."""
    if output_dir.exists():
        raise AnnotationSamplingError("evaluation evidence output directory already exists")
    if re.fullmatch(r"[0-9a-f]{40}", implementation_commit) is None:
        raise AnnotationSamplingError("implementation commit must be a full lowercase Git SHA")

    report, disagreements = evaluate_human_silver_labels(experiment_dir, completed_path)
    outputs = {
        REPORT_FILENAME: _json_bytes(report),
        DISAGREEMENTS_FILENAME: _jsonl_bytes(disagreements),
        SUMMARY_FILENAME: _summary(report).encode(),
    }

    input_paths = [
        (experiment_dir / "silver-experiment-manifest.json", "silver-experiment-manifest.json"),
        (experiment_dir / "human-evaluation-sample.json", "human-evaluation-sample.json"),
        (experiment_dir / "labeler-a-responses.jsonl", "labeler-a-responses.jsonl"),
        (experiment_dir / "labeler-b-responses.jsonl", "labeler-b-responses.jsonl"),
        (completed_path, "completed-human-evaluation.json"),
    ]
    input_paths.extend(
        (experiment_dir / name, name)
        for name in _GOVERNED_THRESHOLD_ARTIFACTS
        if (experiment_dir / name).exists()
    )
    inputs = [_file_evidence(path, name=name) for path, name in input_paths]
    receipt = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "implementation_commit": implementation_commit,
        "evaluation_schema_version": report["schema_version"],
        "evaluation_clauses": report["evaluation_clauses"],
        "single_human_reference": True,
        "adjudicated_gold_data": False,
        "held_out_from_training": True,
        "model_training_authorized": False,
        "production_promotion_authorized": False,
        "inputs": inputs,
        "outputs": [
            {
                "name": name,
                "sha256": _sha256_bytes(value),
                "size_bytes": len(value),
            }
            for name, value in outputs.items()
        ],
    }
    outputs[RECEIPT_FILENAME] = _json_bytes(receipt)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output_dir.name}-", dir=output_dir.parent) as temp:
        staging_dir = Path(temp) / output_dir.name
        staging_dir.mkdir()
        for name, value in outputs.items():
            path = staging_dir / name
            path.write_bytes(value)
            path.chmod(0o600)
        staging_dir.replace(output_dir)
    return receipt
