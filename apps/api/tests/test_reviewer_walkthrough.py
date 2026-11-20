"""Release walkthrough using the synthetic Directive 060 seed and real login."""

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from regimpact import seed_demo
from regimpact.config import get_settings
from regimpact.database import Base, get_session
from regimpact.db_models import AuditEventRecord, MappingDecisionRecord
from regimpact.main import create_app


@pytest.mark.parametrize("run", range(1, 6))
def test_reviewer_walkthrough(run: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = create_engine(f"sqlite+pysqlite:///{tmp_path / 'review.sqlite'}")
    sessions = sessionmaker(bind=db, autoflush=False, expire_on_commit=False)
    with monkeypatch.context() as env:
        env.setenv("REGIMPACT_AUTH_MODE", "legacy")
        env.setenv("REGIMPACT_JWT_SECRET", "isolated-test-signing-key-for-walkthrough")
        env.setenv("REGIMPACT_DEMO_MODE", "false")
        for role in ("ADMIN", "ANALYST", "VIEWER"):
            env.setenv(f"REGIMPACT_DEMO_{role}_PASSWORD", f"test-only-{role.lower()}")
        get_settings.cache_clear()
        try:
            Base.metadata.create_all(db)
            env.setattr(seed_demo, "SessionFactory", sessions)
            seed_demo.seed()
            app = create_app()

            def session_override() -> Iterator[Session]:
                with sessions() as session:
                    yield session

            app.dependency_overrides[get_session] = session_override
            with TestClient(app) as client:
                decision_id, actor_id = verify_walkthrough(client, run, sessions)
            with sessions() as session:
                audit = session.scalars(
                    select(AuditEventRecord).where(
                        AuditEventRecord.entity_id == UUID(decision_id),
                        AuditEventRecord.entity_type == "mapping_decision",
                    )
                ).one()
                assert audit.actor_id == actor_id
                assert audit.event_type == "mapping_decision.deferred"
                assert audit.organization_id == seed_demo.ORGANIZATION_ID
        finally:
            db.dispose()
            get_settings.cache_clear()


def verify_walkthrough(
    client: TestClient, run: int, sessions: sessionmaker[Session]
) -> tuple[str, str]:
    settings = get_settings()

    def sign_in(email: str, password: str, role: str) -> tuple[dict[str, str], str]:
        response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200
        credentials = response.json()
        assert credentials["user"]["role"] == role
        return {"Authorization": f"Bearer {credentials['access_token']}"}, credentials["user"]["id"]

    analyst, analyst_id = sign_in(
        settings.demo_analyst_email, settings.demo_analyst_password, "analyst"
    )
    viewer, _ = sign_in(settings.demo_viewer_email, settings.demo_viewer_password, "viewer")
    register = client.get("/api/v1/changes", headers=analyst)
    assert register.status_code == 200
    change = next(
        row
        for row in register.json()
        if row["source_key"] == "AER-D060" and row["section_key"] == "4.2"
    )
    detail = client.get(f"/api/v1/changes/{change['id']}", headers=analyst)
    assert detail.status_code == 200
    clause = detail.json()
    assert clause["change_type"] == "modified"
    assert "72 hours" in clause["previous_text"]
    assert "24 hours" in clause["current_text"]

    queue = client.get("/api/v1/review-queue", headers=analyst)
    assert queue.status_code == 200
    item = next(
        row
        for row in queue.json()["items"]
        if row["regulation_key"] == "AER-D060" and row["obligation"]["section_key"] == "4.2"
    )
    obligation = item["obligation"]
    evidence = client.get(
        f"/api/v1/evidence/{obligation['section_id']}",
        headers=analyst,
        params={
            "version_id": obligation["version_id"],
            "version_content_hash": obligation["version_content_hash"],
            "section_hash": obligation["section_content_hash"],
        },
    )
    assert evidence.status_code == 200
    source = evidence.json()
    citation = clause["current_citation"]
    assert source["version_id"] == citation["version_id"] == obligation["version_id"]
    assert source["source_uri"] == citation["source_uri"] == obligation["source_uri"]
    assert source["page"] == citation["page"] == obligation["page"] == 43
    assert obligation["evidence_quote"]
    assert obligation["evidence_quote"] in source["body"] == clause["current_text"]

    mapping = next(row for row in item["candidates"] if row["control_key"] == "REG-IR-01")
    assert mapping["explanation"]
    revision = mapping["decision"]["revision"] if mapping["decision"] else 0
    review = f"/api/v1/review-queue/{obligation['id']}"
    path = f"/api/v1/obligations/{obligation['id']}/mapping-decisions"
    params = {"mapping_id": mapping["id"]}
    payload = {
        "decision": "deferred",
        "rationale": "Confirm the control owner can meet the shorter reporting window.",
        "expected_revision": revision,
        "idempotency_key": f"reviewer-walkthrough-{run}",
    }
    assert client.get(review, headers=viewer).status_code == 200
    assert client.post(path, headers=viewer, params=params, json=payload).status_code == 403
    with sessions() as session:
        assert (
            session.scalar(
                select(MappingDecisionRecord).where(
                    MappingDecisionRecord.idempotency_key == payload["idempotency_key"]
                )
            )
            is None
        )
    response = client.post(path, headers=analyst, params=params, json=payload)
    assert response.status_code == 201, response.text
    saved = response.json()
    actor = f"user:{analyst_id}"
    assert saved["actor_id"] == actor
    assert saved["decision"] == payload["decision"]
    assert saved["revision"] == revision + 1
    readback = client.get(review, headers=analyst)
    assert readback.status_code == 200
    updated = next(row for row in readback.json()["candidates"] if row["id"] == mapping["id"])
    for field in ("id", "actor_id", "decision", "rationale", "revision", "mapping_id"):
        assert updated["decision"][field] == saved[field]
    return saved["id"], actor
