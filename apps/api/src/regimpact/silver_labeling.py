"""Governed weak-supervision contracts for experimental clause classification."""

from __future__ import annotations

import json
import time
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

from .annotation_campaign import load_campaign_manifest
from .annotation_sampling import (
    AnnotationSamplingError,
    SampledClause,
    build_blinded_package,
    validate_annotation_package,
)
from .annotation_workspace import build_annotation_workspace
from .clause_annotations import ClauseCandidate
from .clause_classifier import ClauseLabel

SILVER_SCHEMA_VERSION = "regimpact-silver-experiment-v1"
REQUEST_SCHEMA_VERSION = "regimpact-silver-label-request-v1"
RESPONSE_SCHEMA_VERSION = "regimpact-silver-label-response-v1"
PROMPT_VERSIONS = {
    "A": "regimpact-silver-prompt-a-v2",
    "B": "regimpact-silver-prompt-b-v2",
    "C": "regimpact-silver-prompt-c-v1",
}
ADJUDICATION_SCHEMA_VERSION = "regimpact-silver-adjudication-v1"
LABELS = tuple(label.value for label in ClauseLabel)
SILVER_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "regimpact_clause_label",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "enum": list(LABELS)},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "rationale": {"type": "string", "minLength": 1},
            },
            "required": ["label", "confidence", "rationale"],
            "additionalProperties": False,
        },
    },
}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{_canonical(value)}\n" for value in values), encoding="utf-8")
    path.chmod(0o600)


def _records(campaign_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = load_campaign_manifest(campaign_dir)
    values: list[dict[str, Any]] = []
    for batch in manifest["batches"]:
        document = json.loads((campaign_dir / str(batch["sample"])).read_text(encoding="utf-8"))
        records = document.get("records") if isinstance(document, dict) else None
        if not isinstance(records, list) or len(records) != batch["count"]:
            raise AnnotationSamplingError(f"invalid silver source batch: {batch['batch_id']}")
        fingerprint = sha256(
            "\n".join(_canonical(item) for item in records).encode()
        ).hexdigest()
        if fingerprint != batch["sample_sha256"]:
            raise AnnotationSamplingError(f"silver source fingerprint mismatch: {batch['batch_id']}")
        values.extend(records)
    ids = [str(item.get("clause_id")) for item in values]
    if len(ids) != len(set(ids)) or len(values) != manifest["target"]:
        raise AnnotationSamplingError("silver source coverage mismatch")
    return manifest, values


def _prompt(slot: str) -> str:
    if slot == "A":
        order = (
            "reporting_requirement, record_retention_requirement, prohibition, permission, "
            "definition, obligation, non_obligation"
        )
    elif slot == "B":
        order = (
            "definition, prohibition, permission, record_retention_requirement, "
            "reporting_requirement, obligation, non_obligation"
        )
    elif slot == "C":
        order = (
            "prohibition, definition, reporting_requirement, permission, "
            "record_retention_requirement, non_obligation, obligation"
        )
    else:
        raise AnnotationSamplingError(f"unknown silver labeler slot: {slot}")
    return (
        "Classify the direct legal function of one Canadian regulatory clause. "
        "Use exactly one label and do not infer a duty that the text does not expressly create. "
        f"Consider labels independently in this order: {order}. "
        "Use reporting_requirement only when an identified actor must submit, disclose, notify, "
        "file, or report information. Use record_retention_requirement only for an express duty "
        "to keep, maintain, or retain records. Use prohibition for directly forbidden conduct, "
        "permission for directly authorized or optional conduct, definition for a term's stated "
        "meaning or scope, and obligation for another express mandatory action. Use "
        "non_obligation for procedural or evidentiary rules, enforcement mechanics, penalties, "
        "defenses, exemptions, exceptions to liability, transitional rules, and descriptive text "
        "that creates none of those direct duties or permissions. A reference to evidence, "
        "information, a record, or reporting does not itself create a reporting or retention duty. "
        "Classify the clause actually provided, not a requirement mentioned inside it. "
        "Return strict JSON with label, confidence from 0 to 1, and a short rationale. "
        "Reporting and retention labels take precedence over generic obligation when applicable."
    )


def _request(record: dict[str, Any], *, slot: str, labeler_id: str, model_id: str) -> dict[str, Any]:
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "request_id": f"{slot.lower()}-{record['clause_id']}",
        "clause_id": record["clause_id"],
        "document_id": record["document_id"],
        "regulator": record["regulator"],
        "text_sha256": record["text_sha256"],
        "text": record["text"],
        "labeler_slot": slot,
        "labeler_id": labeler_id,
        "model_id": model_id,
        "prompt_version": PROMPT_VERSIONS[slot],
        "system_prompt": _prompt(slot),
        "allowed_labels": list(LABELS),
        "production_ground_truth": False,
    }


def prepare_silver_experiment(
    campaign_dir: Path,
    output_dir: Path,
    *,
    labeler_a_id: str,
    model_a: str,
    labeler_b_id: str,
    model_b: str,
    evaluation_size: int = 70,
    seed: str = "v0.6c7-silver-v1",
) -> dict[str, Any]:
    """Create two AI request streams and a document-isolated human evaluation workspace."""
    if not all(value.strip() for value in (labeler_a_id, model_a, labeler_b_id, model_b)):
        raise AnnotationSamplingError("labeler and model identities are required")
    if labeler_a_id == labeler_b_id or model_a == model_b:
        raise AnnotationSamplingError("silver labelers require distinct labeler and model IDs")
    campaign, records = _records(campaign_dir)
    documents = sorted(
        {str(item["document_id"]) for item in records},
        key=lambda value: sha256(f"{seed}:document:{value}".encode()).hexdigest(),
    )
    holdout_documents: set[str] = set()
    holdout_pool: list[dict[str, Any]] = []
    for document_id in documents:
        holdout_documents.add(document_id)
        holdout_pool.extend(item for item in records if item["document_id"] == document_id)
        if len(holdout_pool) >= evaluation_size:
            break
    if evaluation_size <= 0 or len(holdout_pool) < evaluation_size:
        raise AnnotationSamplingError("evaluation size cannot be satisfied")
    holdout_pool.sort(key=lambda item: sha256(f"{seed}:eval:{item['clause_id']}".encode()).hexdigest())
    evaluation = holdout_pool[:evaluation_size]
    training = [item for item in records if item["document_id"] not in holdout_documents]
    if len(training) < 500:
        raise AnnotationSamplingError("document isolation leaves fewer than 500 training clauses")

    requests_a = [
        _request(item, slot="A", labeler_id=labeler_a_id, model_id=model_a) for item in records
    ]
    requests_b = [
        _request(item, slot="B", labeler_id=labeler_b_id, model_id=model_b)
        for item in reversed(records)
    ]
    _write_jsonl(output_dir / "labeler-a-requests.jsonl", requests_a)
    _write_jsonl(output_dir / "labeler-b-requests.jsonl", requests_b)

    sampled = tuple(
        SampledClause(
            candidate=ClauseCandidate(
                **{
                    key: value
                    for key, value in item.items()
                    if key not in {"sampling_stratum", "sampling_policy_version"}
                }
            ),
            sampling_stratum=str(item["sampling_stratum"]),
        )
        for item in evaluation
    )
    eval_sample = {"schema_version": "regimpact-sampled-clauses-v1", "records": evaluation}
    eval_package = build_blinded_package(
        sampled,
        slot="A",
        seed=seed,
        candidate_queue_sha256=str(campaign["candidate_queue_sha256"]),
        package_id_prefix="v0.6c7-human-evaluation",
    )
    _write_json(output_dir / "human-evaluation-sample.json", eval_sample)
    _write_json(output_dir / "human-evaluation-package.json", eval_package)
    (output_dir / "human-evaluation-workspace.html").write_text(
        build_annotation_workspace(
            output_dir / "human-evaluation-sample.json",
            output_dir / "human-evaluation-package.json",
        ),
        encoding="utf-8",
    )
    (output_dir / "human-evaluation-workspace.html").chmod(0o600)

    manifest = {
        "schema_version": SILVER_SCHEMA_VERSION,
        "status": "awaiting_ai_labelers_and_human_evaluation",
        "source_campaign_id": campaign["campaign_id"],
        "source_sample_sha256": campaign["sample_sha256"],
        "seed": seed,
        "clauses": len(records),
        "training_clauses": len(training),
        "evaluation_clauses": len(evaluation),
        "holdout_documents": sorted(holdout_documents),
        "training_clause_ids_sha256": sha256(
            _canonical(sorted(item["clause_id"] for item in training)).encode()
        ).hexdigest(),
        "evaluation_clause_ids_sha256": sha256(
            _canonical(sorted(item["clause_id"] for item in evaluation)).encode()
        ).hexdigest(),
        "labelers": {
            "A": {"labeler_id": labeler_a_id, "model_id": model_a, "prompt_version": PROMPT_VERSIONS["A"]},
            "B": {"labeler_id": labeler_b_id, "model_id": model_b, "prompt_version": PROMPT_VERSIONS["B"]},
        },
        "silver_labels_are_human_ground_truth": False,
        "production_promotion_authorized": False,
        "model_training_authorized": False,
    }
    _write_json(output_dir / "silver-experiment-manifest.json", manifest)
    return manifest


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except (json.JSONDecodeError, OSError) as exc:
        raise AnnotationSamplingError(f"invalid JSONL: {path.name}") from exc
    if not all(isinstance(item, dict) for item in values):
        raise AnnotationSamplingError(f"invalid JSONL objects: {path.name}")
    return values


def _parse_model_answer(content: object) -> tuple[str, float, str]:
    if not isinstance(content, str):
        raise AnnotationSamplingError("AI labeler returned non-text content")
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AnnotationSamplingError("AI labeler did not return strict JSON") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"label", "confidence", "rationale"}
        or value.get("label") not in LABELS
        or not isinstance(value.get("confidence"), (int, float))
        or not 0 <= float(value["confidence"]) <= 1
        or not isinstance(value.get("rationale"), str)
        or not value["rationale"].strip()
    ):
        raise AnnotationSamplingError("AI labeler response fields are invalid")
    return str(value["label"]), float(value["confidence"]), value["rationale"].strip()


def run_openai_compatible_labeler(
    requests_path: Path,
    responses_path: Path,
    *,
    base_url: str,
    model_id: str,
    labeler_id: str,
    api_key: str | None = None,
    timeout_seconds: float = 90,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Run or resume one immutable request stream against an OpenAI-compatible endpoint."""
    if timeout_seconds <= 0 or max_retries <= 0:
        raise AnnotationSamplingError("timeout and max retries must be positive")
    requests = _load_jsonl(requests_path)
    request_by_id = {str(item.get("clause_id")): item for item in requests}
    if len(request_by_id) != len(requests):
        raise AnnotationSamplingError("AI requests contain duplicate clause IDs")
    for clause_id, request in request_by_id.items():
        if request.get("model_id") != model_id or request.get("labeler_id") != labeler_id:
            raise AnnotationSamplingError(f"AI runner identity mismatch: {clause_id}")
    existing = _load_jsonl(responses_path) if responses_path.exists() else []
    completed = {str(item.get("clause_id")): item for item in existing}
    if len(completed) != len(existing):
        raise AnnotationSamplingError("existing AI responses contain duplicate clause IDs")
    if not set(completed) <= set(request_by_id):
        raise AnnotationSamplingError("existing AI responses do not match the request stream")
    for clause_id, cached_response in completed.items():
        request = request_by_id[clause_id]
        if (
            cached_response.get("schema_version") != RESPONSE_SCHEMA_VERSION
            or cached_response.get("clause_id") != clause_id
            or cached_response.get("text_sha256") != request.get("text_sha256")
            or cached_response.get("labeler_id") != labeler_id
            or cached_response.get("model_id") != model_id
            or cached_response.get("prompt_version") != request.get("prompt_version")
        ):
            raise AnnotationSamplingError(f"cached AI response identity mismatch: {clause_id}")
        _parse_model_answer(
            _canonical(
                {
                    "label": cached_response.get("label"),
                    "confidence": cached_response.get("confidence"),
                    "rationale": cached_response.get("rationale"),
                }
            )
        )
    if not base_url.startswith(("http://", "https://")):
        raise AnnotationSamplingError("AI endpoint must use HTTP or HTTPS")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    responses_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
        for request in requests:
            clause_id = str(request.get("clause_id"))
            if clause_id in completed:
                continue
            payload = {
                "model": model_id,
                "temperature": 0,
                "response_format": SILVER_RESPONSE_FORMAT,
                "messages": [
                    {"role": "system", "content": request["system_prompt"]},
                    {
                        "role": "user",
                        "content": (
                            f"Clause ID: {clause_id}\n"
                            f"Regulatory text:\n{request['text']}\n\n"
                            "Return only JSON."
                        ),
                    },
                ],
            }
            last_error: Exception | None = None
            for attempt in range(max_retries):
                try:
                    response = client.post(f"{base_url.rstrip('/')}/chat/completions", json=payload)
                    response.raise_for_status()
                    body = response.json()
                    content = body["choices"][0]["message"]["content"]
                    label, confidence, rationale = _parse_model_answer(content)
                    result = {
                        "schema_version": RESPONSE_SCHEMA_VERSION,
                        "clause_id": clause_id,
                        "text_sha256": request["text_sha256"],
                        "labeler_id": labeler_id,
                        "model_id": model_id,
                        "prompt_version": request["prompt_version"],
                        "label": label,
                        "confidence": confidence,
                        "rationale": rationale,
                    }
                    with responses_path.open("a", encoding="utf-8") as stream:
                        stream.write(f"{_canonical(result)}\n")
                    completed[clause_id] = result
                    last_error = None
                    break
                except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, AnnotationSamplingError) as exc:
                    last_error = exc
                    if attempt + 1 < max_retries:
                        time.sleep(2**attempt)
            if last_error is not None:
                raise AnnotationSamplingError(f"AI labeler failed for {clause_id}") from last_error
    responses_path.chmod(0o600)
    return {
        "schema_version": "regimpact-silver-labeler-run-v2",
        "labeler_id": labeler_id,
        "model_id": model_id,
        "completed": len(completed),
        "target": len(requests),
        "status": "complete" if len(completed) == len(requests) else "in_progress",
        "production_promotion_authorized": False,
    }


def compile_silver_consensus(
    experiment_dir: Path, *, minimum_confidence: float = 0.80
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Validate both AI outputs and separate accepted silver labels from review cases."""
    manifest = json.loads((experiment_dir / "silver-experiment-manifest.json").read_text())
    if manifest.get("schema_version") != SILVER_SCHEMA_VERSION:
        raise AnnotationSamplingError("invalid silver experiment manifest")
    if not 0 <= minimum_confidence <= 1:
        raise AnnotationSamplingError("minimum confidence must be between zero and one")
    outputs: dict[str, dict[str, dict[str, Any]]] = {}
    for slot in ("A", "B"):
        requests = _load_jsonl(experiment_dir / f"labeler-{slot.lower()}-requests.jsonl")
        responses = _load_jsonl(experiment_dir / f"labeler-{slot.lower()}-responses.jsonl")
        request_by_id = {item["clause_id"]: item for item in requests}
        response_by_id = {str(item.get("clause_id")): item for item in responses}
        if len(response_by_id) != len(responses) or set(response_by_id) != set(request_by_id):
            raise AnnotationSamplingError(f"labeler {slot} response coverage mismatch")
        expected = manifest["labelers"][slot]
        for clause_id, response in response_by_id.items():
            request = request_by_id[clause_id]
            if (
                response.get("schema_version") != RESPONSE_SCHEMA_VERSION
                or response.get("labeler_id") != expected["labeler_id"]
                or response.get("model_id") != expected["model_id"]
                or response.get("prompt_version") != expected["prompt_version"]
                or response.get("label") not in LABELS
                or not isinstance(response.get("confidence"), (int, float))
                or not 0 <= float(response["confidence"]) <= 1
                or not isinstance(response.get("rationale"), str)
                or not response["rationale"].strip()
                or response.get("text_sha256") != request["text_sha256"]
            ):
                raise AnnotationSamplingError(f"invalid labeler {slot} response: {clause_id}")
        outputs[slot] = response_by_id

    evaluation_ids = {
        item["clause_id"]
        for item in json.loads((experiment_dir / "human-evaluation-sample.json").read_text())["records"]
    }
    holdout_documents = set(manifest["holdout_documents"])
    requests_a = {
        item["clause_id"]: item
        for item in _load_jsonl(experiment_dir / "labeler-a-requests.jsonl")
    }
    accepted: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for clause_id, request in requests_a.items():
        a, b = outputs["A"][clause_id], outputs["B"][clause_id]
        agreed = a["label"] == b["label"]
        confident = min(float(a["confidence"]), float(b["confidence"])) >= minimum_confidence
        held_out = request["document_id"] in holdout_documents
        item = {
            "clause_id": clause_id,
            "document_id": request["document_id"],
            "regulator": request["regulator"],
            "text": request["text"],
            "text_sha256": request["text_sha256"],
            "label_a": a["label"],
            "confidence_a": a["confidence"],
            "label_b": b["label"],
            "confidence_b": b["confidence"],
            "held_out_from_training": held_out,
            "human_evaluation_clause": clause_id in evaluation_ids,
        }
        if agreed and confident and not held_out:
            accepted.append({**item, "label": a["label"], "label_source": "ai_consensus_silver"})
        else:
            review.append({**item, "reason": "held_out" if held_out else "disagreement_or_low_confidence"})
    report = {
        "schema_version": "regimpact-silver-consensus-report-v1",
        "accepted_training_labels": len(accepted),
        "routed_for_review": len(review),
        "evaluation_clauses": len(evaluation_ids),
        "minimum_confidence": minimum_confidence,
        "label_distribution": dict(sorted(Counter(item["label"] for item in accepted).items())),
        "experimental_training_eligible": len(accepted) >= 500,
        "silver_labels_are_human_ground_truth": False,
        "production_promotion_authorized": False,
        "model_training_authorized": False,
    }
    return accepted, review, report


def human_evaluation_progress(experiment_dir: Path, completed_path: Path) -> dict[str, Any]:
    package = validate_annotation_package(
        experiment_dir / "human-evaluation-sample.json", completed_path, expected_slot="A"
    )
    completed = sum(task.get("label") is not None for task in package["tasks"])
    return {
        "schema_version": "regimpact-human-evaluation-progress-v1",
        "completed": completed,
        "target": len(package["tasks"]),
        "status": "complete" if completed == len(package["tasks"]) else "in_progress",
        "single_human_review": True,
        "production_promotion_authorized": False,
    }



def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def prepare_silver_adjudication(
    experiment_dir: Path,
    *,
    labeler_c_id: str,
    model_c: str,
    minimum_confidence: float = 0.80,
) -> dict[str, Any]:
    """Create an immutable third-model stream for non-held-out A/B disagreements."""
    if not labeler_c_id.strip() or not model_c.strip():
        raise AnnotationSamplingError("third labeler and model identities are required")
    if not 0 <= minimum_confidence <= 1:
        raise AnnotationSamplingError("minimum confidence must be between zero and one")
    manifest_path = experiment_dir / "silver-adjudication-manifest.json"
    requests_path = experiment_dir / "labeler-c-requests.jsonl"
    if manifest_path.exists() or requests_path.exists():
        raise AnnotationSamplingError("silver adjudication artifacts already exist")

    experiment = json.loads(
        (experiment_dir / "silver-experiment-manifest.json").read_text(encoding="utf-8")
    )
    if experiment.get("schema_version") != SILVER_SCHEMA_VERSION:
        raise AnnotationSamplingError("invalid silver experiment manifest")
    identities = experiment.get("labelers")
    if not isinstance(identities, dict):
        raise AnnotationSamplingError("invalid silver labeler identities")
    for slot in ("A", "B"):
        identity = identities.get(slot)
        if not isinstance(identity, dict):
            raise AnnotationSamplingError("invalid silver labeler identity")
        if labeler_c_id == identity.get("labeler_id") or model_c == identity.get("model_id"):
            raise AnnotationSamplingError("third adjudicator must use a distinct identity and model")

    accepted, review, _ = compile_silver_consensus(
        experiment_dir, minimum_confidence=minimum_confidence
    )
    disagreements = [
        item
        for item in review
        if not item["held_out_from_training"] and item["label_a"] != item["label_b"]
    ]
    requests = [
        _request(item, slot="C", labeler_id=labeler_c_id, model_id=model_c)
        for item in disagreements
    ]
    _write_jsonl(requests_path, requests)

    manifest = {
        "schema_version": ADJUDICATION_SCHEMA_VERSION,
        "status": "awaiting_third_model",
        "source_experiment_schema_version": experiment["schema_version"],
        "source_experiment_seed": experiment["seed"],
        "minimum_confidence": minimum_confidence,
        "base_accepted_labels": len(accepted),
        "eligible_disagreements": len(disagreements),
        "held_out_clauses_excluded": sum(
            bool(item["held_out_from_training"]) for item in review
        ),
        "source_response_sha256": {
            "A": _sha256_file(experiment_dir / "labeler-a-responses.jsonl"),
            "B": _sha256_file(experiment_dir / "labeler-b-responses.jsonl"),
        },
        "requests_sha256": _sha256_file(requests_path),
        "labeler": {
            "slot": "C",
            "labeler_id": labeler_c_id,
            "model_id": model_c,
            "prompt_version": PROMPT_VERSIONS["C"],
        },
        "silver_labels_are_human_ground_truth": False,
        "model_training_authorized": False,
        "production_promotion_authorized": False,
    }
    _write_json(manifest_path, manifest)
    return manifest


def compile_silver_adjudication(
    experiment_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Compile strict two-of-three silver consensus without touching held-out clauses."""
    manifest_path = experiment_dir / "silver-adjudication-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != ADJUDICATION_SCHEMA_VERSION:
        raise AnnotationSamplingError("invalid silver adjudication manifest")

    for slot in ("A", "B"):
        path = experiment_dir / f"labeler-{slot.lower()}-responses.jsonl"
        if _sha256_file(path) != manifest["source_response_sha256"].get(slot):
            raise AnnotationSamplingError(f"source labeler {slot} response fingerprint mismatch")

    requests_path = experiment_dir / "labeler-c-requests.jsonl"
    if _sha256_file(requests_path) != manifest.get("requests_sha256"):
        raise AnnotationSamplingError("third-labeler request fingerprint mismatch")

    threshold = float(manifest["minimum_confidence"])
    base_accepted, review, _ = compile_silver_consensus(
        experiment_dir, minimum_confidence=threshold
    )
    disputes = {
        item["clause_id"]: item
        for item in review
        if not item["held_out_from_training"] and item["label_a"] != item["label_b"]
    }
    requests = _load_jsonl(requests_path)
    request_by_id = {str(item.get("clause_id")): item for item in requests}
    if (
        len(request_by_id) != len(requests)
        or set(request_by_id) != set(disputes)
        or len(disputes) != manifest.get("eligible_disagreements")
    ):
        raise AnnotationSamplingError("third-labeler disagreement coverage mismatch")

    responses = _load_jsonl(experiment_dir / "labeler-c-responses.jsonl")
    response_by_id = {str(item.get("clause_id")): item for item in responses}
    if len(response_by_id) != len(responses) or set(response_by_id) != set(request_by_id):
        raise AnnotationSamplingError("third-labeler response coverage mismatch")

    expected = manifest.get("labeler")
    if not isinstance(expected, dict):
        raise AnnotationSamplingError("invalid third-labeler identity")
    adjudicated: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for clause_id, dispute in disputes.items():
        request = request_by_id[clause_id]
        response = response_by_id[clause_id]
        if (
            response.get("schema_version") != RESPONSE_SCHEMA_VERSION
            or response.get("clause_id") != clause_id
            or response.get("text_sha256") != request.get("text_sha256")
            or response.get("labeler_id") != expected.get("labeler_id")
            or response.get("model_id") != expected.get("model_id")
            or response.get("prompt_version") != expected.get("prompt_version")
        ):
            raise AnnotationSamplingError(f"invalid labeler C response: {clause_id}")
        _parse_model_answer(
            _canonical(
                {
                    "label": response.get("label"),
                    "confidence": response.get("confidence"),
                    "rationale": response.get("rationale"),
                }
            )
        )
        label_c = str(response["label"])
        confidence_c = float(response["confidence"])
        supporting_confidence: float | None = None
        supporting_slot: str | None = None
        if label_c == dispute["label_a"]:
            supporting_confidence = float(dispute["confidence_a"])
            supporting_slot = "A"
        elif label_c == dispute["label_b"]:
            supporting_confidence = float(dispute["confidence_b"])
            supporting_slot = "B"

        lineage = {
            **dispute,
            "label_c": label_c,
            "confidence_c": confidence_c,
            "labeler_c_id": expected["labeler_id"],
            "model_c_id": expected["model_id"],
            "prompt_c_version": expected["prompt_version"],
        }
        if (
            supporting_confidence is not None
            and min(supporting_confidence, confidence_c) >= threshold
        ):
            adjudicated.append(
                {
                    **lineage,
                    "label": label_c,
                    "label_source": "ai_two_of_three_silver",
                    "supporting_slots": [supporting_slot, "C"],
                }
            )
        else:
            reason = (
                "third_model_low_confidence"
                if supporting_confidence is not None
                else "three_way_disagreement"
            )
            unresolved.append({**lineage, "reason": reason})

    accepted = [*base_accepted, *adjudicated]
    distribution = dict(sorted(Counter(item["label"] for item in accepted).items()))
    report = {
        "schema_version": "regimpact-silver-adjudication-report-v1",
        "base_accepted_labels": len(base_accepted),
        "adjudicated_labels_accepted": len(adjudicated),
        "total_accepted_training_labels": len(accepted),
        "eligible_disagreements": len(disputes),
        "unresolved_disagreements": len(unresolved),
        "held_out_clauses_excluded": manifest["held_out_clauses_excluded"],
        "minimum_confidence": threshold,
        "label_distribution": distribution,
        "experimental_training_eligible": len(accepted) >= 500,
        "silver_labels_are_human_ground_truth": False,
        "model_training_authorized": False,
        "production_promotion_authorized": False,
    }
    return accepted, unresolved, report
