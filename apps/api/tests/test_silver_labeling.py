import json
from hashlib import sha256
from pathlib import Path

import pytest

from regimpact.annotation_campaign import prepare_campaign
from regimpact.annotation_sampling import AnnotationSamplingError
from regimpact.clause_annotations import ClauseCandidate
from regimpact.silver_labeling import (
    PROMPT_VERSIONS,
    RESPONSE_SCHEMA_VERSION,
    SILVER_RESPONSE_FORMAT,
    _parse_model_answer,
    _prompt,
    compile_silver_adjudication,
    compile_silver_consensus,
    prepare_silver_adjudication,
    prepare_silver_experiment,
    run_openai_compatible_labeler,
)


def _candidate(index: int) -> ClauseCandidate:
    document = index % 25
    text = f"Every institution shall maintain controls for example {index}."
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


def _write_responses(experiment: Path, slot: str, *, confidence: float = 0.9) -> None:
    manifest = json.loads((experiment / "silver-experiment-manifest.json").read_text())
    config = manifest["labelers"][slot]
    requests = [
        json.loads(line)
        for line in (experiment / f"labeler-{slot.lower()}-requests.jsonl")
        .read_text()
        .splitlines()
    ]
    responses = [
        {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "clause_id": item["clause_id"],
            "text_sha256": item["text_sha256"],
            "labeler_id": config["labeler_id"],
            "model_id": config["model_id"],
            "prompt_version": config["prompt_version"],
            "label": "obligation",
            "confidence": confidence,
            "rationale": "The clause imposes a mandatory action.",
        }
        for item in requests
    ]
    (experiment / f"labeler-{slot.lower()}-responses.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in responses)
    )


def test_silver_experiment_is_document_isolated_and_never_promotable(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    prepare_campaign(
        tuple(_candidate(index) for index in range(700)),
        candidate_queue_sha256="f" * 64,
        output_dir=campaign,
        target=700,
        batch_size=100,
        seed="fixed",
    )
    experiment = tmp_path / "experiment"
    manifest = prepare_silver_experiment(
        campaign,
        experiment,
        labeler_a_id="labeler-a",
        model_a="model-a@revision-1",
        labeler_b_id="labeler-b",
        model_b="model-b@revision-2",
    )
    assert manifest["evaluation_clauses"] == 70
    assert manifest["training_clauses"] >= 500
    assert manifest["production_promotion_authorized"] is False
    assert manifest["model_training_authorized"] is False
    evaluation = json.loads((experiment / "human-evaluation-sample.json").read_text())["records"]
    assert {item["document_id"] for item in evaluation} <= set(manifest["holdout_documents"])

    _write_responses(experiment, "A")
    _write_responses(experiment, "B")
    accepted, review, report = compile_silver_consensus(experiment)
    assert len(accepted) == manifest["training_clauses"]
    assert all(item["regulator"].startswith("Regulator") for item in accepted)
    assert len(review) == 700 - manifest["training_clauses"]
    assert sum(item["human_evaluation_clause"] for item in review) == 70
    assert report["experimental_training_eligible"] is True
    assert report["production_promotion_authorized"] is False


def test_silver_experiment_rejects_same_model_and_tampered_output(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    prepare_campaign(
        tuple(_candidate(index) for index in range(700)),
        candidate_queue_sha256="f" * 64,
        output_dir=campaign,
        target=700,
        seed="fixed",
    )
    with pytest.raises(AnnotationSamplingError, match="distinct"):
        prepare_silver_experiment(
            campaign,
            tmp_path / "bad",
            labeler_a_id="a",
            model_a="same",
            labeler_b_id="b",
            model_b="same",
        )

    experiment = tmp_path / "experiment"
    prepare_silver_experiment(
        campaign,
        experiment,
        labeler_a_id="a",
        model_a="model-a",
        labeler_b_id="b",
        model_b="model-b",
    )
    _write_responses(experiment, "A")
    _write_responses(experiment, "B")
    path = experiment / "labeler-a-responses.jsonl"
    values = path.read_text().splitlines()
    first = json.loads(values[0])
    first["text_sha256"] = "0" * 64
    values[0] = json.dumps(first)
    path.write_text("\n".join(values) + "\n")
    with pytest.raises(AnnotationSamplingError, match="invalid labeler A response"):
        compile_silver_consensus(experiment)


def test_model_answer_requires_strict_valid_json() -> None:
    assert _parse_model_answer(
        '{"label":"prohibition","confidence":0.91,"rationale":"It forbids conduct."}'
    ) == ("prohibition", 0.91, "It forbids conduct.")
    with pytest.raises(AnnotationSamplingError, match="strict JSON"):
        _parse_model_answer("```json\n{}\n```")
    with pytest.raises(AnnotationSamplingError, match="fields"):
        _parse_model_answer('{"label":"unknown","confidence":2,"rationale":""}')
    with pytest.raises(AnnotationSamplingError, match="fields"):
        _parse_model_answer(
            '{"label":"prohibition","confidence":0.9,"rationale":"Forbidden.","extra":true}'
        )


def test_silver_response_schema_constrains_taxonomy() -> None:
    schema = SILVER_RESPONSE_FORMAT["json_schema"]["schema"]
    assert SILVER_RESPONSE_FORMAT["type"] == "json_schema"
    assert SILVER_RESPONSE_FORMAT["json_schema"]["strict"] is True
    assert schema["properties"]["label"]["enum"] == [
        "obligation",
        "permission",
        "prohibition",
        "definition",
        "reporting_requirement",
        "record_retention_requirement",
        "non_obligation",
    ]
    assert schema["additionalProperties"] is False


def test_prompt_defines_legal_boundaries_without_inferred_duties() -> None:
    assert PROMPT_VERSIONS == {
        "A": "regimpact-silver-prompt-a-v2",
        "B": "regimpact-silver-prompt-b-v2",
        "C": "regimpact-silver-prompt-c-v1",
    }
    for slot in ("A", "B", "C"):
        prompt = _prompt(slot)
        assert "do not infer a duty" in prompt
        assert "evidentiary rules" in prompt
        assert "defenses, exemptions" in prompt
        assert "does not itself create a reporting or retention duty" in prompt


def test_labeler_rejects_cached_responses_from_other_stream(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    prepare_campaign(
        tuple(_candidate(index) for index in range(700)),
        candidate_queue_sha256="f" * 64,
        output_dir=campaign,
        target=700,
        seed="fixed",
    )
    experiment = tmp_path / "experiment"
    prepare_silver_experiment(
        campaign,
        experiment,
        labeler_a_id="labeler-a",
        model_a="model-a",
        labeler_b_id="labeler-b",
        model_b="model-b",
    )
    _write_responses(experiment, "A")

    with pytest.raises(AnnotationSamplingError, match="cached AI response identity mismatch"):
        run_openai_compatible_labeler(
            experiment / "labeler-b-requests.jsonl",
            experiment / "labeler-a-responses.jsonl",
            base_url="https://models.example/v1",
            model_id="model-b",
            labeler_id="labeler-b",
        )



def test_third_model_adjudication_excludes_holdout_and_requires_majority(
    tmp_path: Path,
) -> None:
    campaign = tmp_path / "campaign"
    prepare_campaign(
        tuple(_candidate(index) for index in range(700)),
        candidate_queue_sha256="f" * 64,
        output_dir=campaign,
        target=700,
        batch_size=100,
        seed="fixed",
    )
    experiment = tmp_path / "experiment"
    experiment_manifest = prepare_silver_experiment(
        campaign,
        experiment,
        labeler_a_id="labeler-a",
        model_a="model-a",
        labeler_b_id="labeler-b",
        model_b="model-b",
    )
    _write_responses(experiment, "A")
    _write_responses(experiment, "B")

    holdouts = set(experiment_manifest["holdout_documents"])
    path_b = experiment / "labeler-b-responses.jsonl"
    responses_b = [json.loads(line) for line in path_b.read_text().splitlines()]
    changed = 0
    for response in responses_b:
        index = int(response["clause_id"].split("-")[1])
        if f"document-{index % 25:02d}" not in holdouts and changed < 100:
            response["label"] = "permission"
            response["rationale"] = "The clause authorizes optional conduct."
            changed += 1
    path_b.write_text("".join(json.dumps(item) + "\n" for item in responses_b))
    assert changed == 100

    manifest = prepare_silver_adjudication(
        experiment,
        labeler_c_id="labeler-c",
        model_c="model-c",
    )
    assert manifest["eligible_disagreements"] == 100
    requests_c = [
        json.loads(line)
        for line in (experiment / "labeler-c-requests.jsonl").read_text().splitlines()
    ]
    assert not {item["document_id"] for item in requests_c} & holdouts

    responses_c = [
        {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "clause_id": item["clause_id"],
            "text_sha256": item["text_sha256"],
            "labeler_id": "labeler-c",
            "model_id": "model-c",
            "prompt_version": PROMPT_VERSIONS["C"],
            "label": "permission",
            "confidence": 0.9,
            "rationale": "The clause authorizes optional conduct.",
        }
        for item in requests_c
    ]
    (experiment / "labeler-c-responses.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in responses_c)
    )

    accepted, unresolved, report = compile_silver_adjudication(experiment)
    assert len(accepted) == experiment_manifest["training_clauses"]
    assert len(unresolved) == 0
    assert report["adjudicated_labels_accepted"] == 100
    assert report["held_out_clauses_excluded"] == 700 - experiment_manifest["training_clauses"]
    assert report["silver_labels_are_human_ground_truth"] is False
    assert report["production_promotion_authorized"] is False


def test_third_model_adjudicator_must_be_independent(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    prepare_campaign(
        tuple(_candidate(index) for index in range(700)),
        candidate_queue_sha256="f" * 64,
        output_dir=campaign,
        target=700,
        seed="fixed",
    )
    experiment = tmp_path / "experiment"
    prepare_silver_experiment(
        campaign,
        experiment,
        labeler_a_id="labeler-a",
        model_a="model-a",
        labeler_b_id="labeler-b",
        model_b="model-b",
    )
    _write_responses(experiment, "A")
    _write_responses(experiment, "B")
    with pytest.raises(AnnotationSamplingError, match="distinct"):
        prepare_silver_adjudication(
            experiment,
            labeler_c_id="labeler-c",
            model_c="model-a",
        )
