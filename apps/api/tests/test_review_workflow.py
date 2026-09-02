import asyncio
import os
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regimpact.auth import hash_password, issue_access_token
from regimpact.config import get_settings
from regimpact.control_mapping import add_control, suggest_mappings
from regimpact.database import Base, get_session
from regimpact.db_models import (
    AuditEventRecord,
    MappingDecisionRecord,
    ObligationControlMappingRecord,
    ObligationRecord,
    OrganizationRecord,
    RegulationRecord,
    UserRecord,
)
from regimpact.domain import Section
from regimpact.main import create_app
from regimpact.obligation_service import extract_and_store_obligations
from regimpact.repository import SqlAlchemyVersionRepository
from regimpact.versioning import VersioningService


class ReviewWorkflowTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.organization_id = uuid4()
        self.other_organization_id = uuid4()
        self.user_id = uuid4()
        with self.session.begin():
            regulation_id = uuid4()
            self.session.add_all(
                [
                    OrganizationRecord(id=self.organization_id, name="Northstar Energy"),
                    OrganizationRecord(id=self.other_organization_id, name="Other Tenant"),
                    UserRecord(
                        id=self.user_id,
                        organization_id=self.organization_id,
                        email="admin@example.test",
                        display_name="Test Administrator",
                        role="admin",
                        password_hash=hash_password("Correct-Horse-2026!"),
                    ),
                    RegulationRecord(
                        id=regulation_id,
                        organization_id=self.organization_id,
                        source_key="AER-D060",
                        title="Directive 060",
                        jurisdiction="Alberta",
                    ),
                ]
            )
            self.session.flush()
            version = VersioningService(
                SqlAlchemyVersionRepository(self.session, self.organization_id, "test-suite")
            ).ingest(
                regulation_id=regulation_id,
                source_uri="https://www.aer.ca/directive-060",
                raw_content="current",
                sections=(Section("4.2", "Notification", "Operators must report incidents.", 43),),
            )
            extract_and_store_obligations(
                self.session,
                organization_id=self.organization_id,
                version_id=version.version.id,
                actor_id="test-suite",
            )
            add_control(
                self.session,
                organization_id=self.organization_id,
                control_key="REG-IR-01",
                title="Incident reporting",
                description="Report regulatory incidents.",
                owner="Compliance",
                evidence_requirement="Submission receipt",
            )
            obligation = self.session.scalar(select(ObligationRecord))
            assert obligation is not None
            self.obligation_id = obligation.id
            mappings = suggest_mappings(
                self.session,
                organization_id=self.organization_id,
                obligation_id=obligation.id,
                actor_id="test-suite",
            )
            self.mapping_id = mappings[0].id
        self.app = create_app()

        def session_override():  # type: ignore[no-untyped-def]
            yield self.session

        self.app.dependency_overrides[get_session] = session_override

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    async def request(self, method: str, path: str, organization_id=None, **kwargs):  # type: ignore[no-untyped-def]
        headers = {
            "X-Organization-ID": str(organization_id or self.organization_id),
            "X-Actor-ID": "development:test-analyst",
        }
        headers.update(kwargs.pop("headers", {}))
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, headers=headers, **kwargs)

    def test_queue_exposes_evidence_candidate_and_pagination(self) -> None:
        response = asyncio.run(self.request("GET", "/api/v1/review-queue?limit=1"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(
            body["items"][0]["obligation"]["evidence_quote"], "Operators must report incidents."
        )
        self.assertEqual(body["items"][0]["candidates"][0]["control_key"], "REG-IR-01")

    def test_queue_filters_by_search_control_and_confidence_range(self) -> None:
        detail = asyncio.run(self.request("GET", f"/api/v1/review-queue/{self.obligation_id}"))
        control_version_id = detail.json()["candidates"][0]["control_version_id"]
        response = asyncio.run(
            self.request(
                "GET",
                "/api/v1/review-queue"
                f"?q=incident&control_version_id={control_version_id}"
                "&min_confidence=0.5&max_confidence=1",
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        excluded = asyncio.run(
            self.request("GET", "/api/v1/review-queue?q=unrelated&min_confidence=0")
        )
        self.assertEqual(excluded.json()["total"], 0)

    def test_decision_is_idempotent_audited_and_stale_safe(self) -> None:
        path = f"/api/v1/obligations/{self.obligation_id}/mapping-decisions?mapping_id={self.mapping_id}"
        payload = {
            "decision": "accepted",
            "rationale": "The submission receipt directly evidences the reporting duty.",
            "expected_revision": 0,
            "idempotency_key": "review-action-0001",
        }
        first = asyncio.run(self.request("POST", path, json=payload))
        repeated = asyncio.run(self.request("POST", path, json=payload))
        stale = asyncio.run(
            self.request("POST", path, json={**payload, "idempotency_key": "review-action-0002"})
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(repeated.json()["id"], first.json()["id"])
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(MappingDecisionRecord)), 1
        )
        self.assertEqual(
            self.session.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(AuditEventRecord.event_type == "mapping_decision.accepted")
            ),
            1,
        )

    def test_database_authenticated_user_can_record_decision(self) -> None:
        user = self.session.get(UserRecord, self.user_id)
        assert user is not None

        def independent_session_override():  # type: ignore[no-untyped-def]
            with Session(self.engine, expire_on_commit=False) as session:
                yield session

        self.app.dependency_overrides[get_session] = independent_session_override
        path = (
            f"/api/v1/obligations/{self.obligation_id}/mapping-decisions"
            f"?mapping_id={self.mapping_id}"
        )
        with patch.dict(os.environ, {"REGIMPACT_AUTH_MODE": "jwt"}):
            get_settings.cache_clear()
            try:
                token, _ = issue_access_token(user)
                response = asyncio.run(
                    self.request(
                        "POST",
                        path,
                        headers={"Authorization": f"Bearer {token}"},
                        json={
                            "decision": "deferred",
                            "rationale": "Control-owner confirmation is required.",
                            "expected_revision": 0,
                            "idempotency_key": "authenticated-review-action",
                        },
                    )
                )
            finally:
                get_settings.cache_clear()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["decision"], "deferred")
        self.assertEqual(response.json()["actor_id"], f"user:{self.user_id}")

    def test_tenant_cannot_read_or_decide_another_tenants_work(self) -> None:
        queue = asyncio.run(self.request("GET", "/api/v1/review-queue", self.other_organization_id))
        self.session.rollback()
        path = f"/api/v1/obligations/{self.obligation_id}/mapping-decisions?mapping_id={self.mapping_id}"
        decision = asyncio.run(
            self.request(
                "POST",
                path,
                self.other_organization_id,
                json={
                    "decision": "rejected",
                    "rationale": "Not this tenant's decision.",
                    "expected_revision": 0,
                    "idempotency_key": "cross-tenant-action",
                },
            )
        )
        self.assertEqual(queue.json()["items"], [])
        self.assertEqual(decision.status_code, 404)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(ObligationControlMappingRecord)), 1
        )

    def test_confirmed_unmapped_rejects_candidate_target(self) -> None:
        path = f"/api/v1/obligations/{self.obligation_id}/mapping-decisions?mapping_id={self.mapping_id}"
        response = asyncio.run(
            self.request(
                "POST",
                path,
                json={
                    "decision": "confirmed_unmapped",
                    "rationale": "No existing control applies.",
                    "expected_revision": 0,
                    "idempotency_key": "invalid-unmapped-action",
                },
            )
        )
        self.assertEqual(response.status_code, 422)

    def test_new_control_version_supersedes_prior_decision(self) -> None:
        path = f"/api/v1/obligations/{self.obligation_id}/mapping-decisions?mapping_id={self.mapping_id}"
        accepted = asyncio.run(
            self.request(
                "POST",
                path,
                json={
                    "decision": "accepted",
                    "rationale": "Current control evidence is sufficient.",
                    "expected_revision": 0,
                    "idempotency_key": "versioned-decision-0001",
                },
            )
        )
        self.assertEqual(accepted.status_code, 201)
        with self.session.begin():
            add_control(
                self.session,
                organization_id=self.organization_id,
                control_key="REG-IR-01",
                title="Incident reporting",
                description="Report and escalate regulatory incidents.",
                owner="Compliance",
                evidence_requirement="Submission receipt and escalation log",
            )
        decisions = self.session.scalars(
            select(MappingDecisionRecord).order_by(MappingDecisionRecord.revision)
        ).all()
        self.assertEqual([item.decision for item in decisions], ["accepted", "superseded"])
        self.assertEqual(decisions[1].supersedes_id, decisions[0].id)
