import asyncio
import json
from pathlib import Path
from unittest import TestCase
from uuid import UUID, uuid4

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regimpact.database import Base, get_session
from regimpact.db_models import AuditEventRecord, ObligationRecord, RegulationRecord
from regimpact.domain import ObligationModality, Section
from regimpact.main import create_app
from regimpact.obligation_extraction import extract_obligations
from regimpact.obligation_service import extract_and_store_obligations
from regimpact.repository import (
    RegulationNotFoundError,
    SqlAlchemyVersionRepository,
    ensure_organization,
)
from regimpact.versioning import VersioningService


class ObligationExtractorTests(TestCase):
    def test_extracts_binding_duty_with_deadline_and_evidence(self):
        section = Section(
            "4.2",
            "Incident notice",
            "Operators must notify the regulator within 24 hours of a reportable incident.",
            43,
        )
        result = extract_obligations(section)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].subject, "Operators")
        self.assertEqual(result[0].modality, ObligationModality.MUST)
        self.assertEqual(result[0].deadline_text, "within 24 hours")
        self.assertEqual(result[0].evidence_quote, section.text)
        self.assertEqual(result[0].raw_confidence, 0.9)
        self.assertEqual(result[0].confidence, 0.875)
        self.assertGreaterEqual(result[0].confidence, 0.85)
        self.assertFalse(result[0].requires_review)

    def test_extracts_prohibition_and_rejects_advisory_language(self):
        prohibition = extract_obligations(
            Section("7", "Disclosure", "Licensees shall not disclose protected records.")
        )
        advisory = extract_obligations(
            Section("8", "Guidance", "Licensees may retain copies and should review them.")
        )
        self.assertEqual(prohibition[0].modality, ObligationModality.SHALL_NOT)
        self.assertEqual(advisory, ())

    def test_returns_each_evidence_sentence_independently(self):
        result = extract_obligations(
            Section(
                "9",
                "Records",
                "Operators must retain records for seven years. Auditors are required to review records annually.",
            )
        )
        self.assertEqual(len(result), 2)
        self.assertEqual([item.subject for item in result], ["Operators", "Auditors"])

    def test_frozen_baseline_evaluation_meets_precision_and_recall_gate(self):
        fixture_path = Path(__file__).parent / "fixtures" / "obligation_eval.json"
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))
        true_positive = false_positive = false_negative = 0
        for case in cases:
            predicted = {
                item.evidence_quote
                for item in extract_obligations(Section(case["id"], case["id"], case["text"]))
            }
            expected = set(case["expected"])
            true_positive += len(predicted & expected)
            false_positive += len(predicted - expected)
            false_negative += len(expected - predicted)
        precision = true_positive / (true_positive + false_positive)
        recall = true_positive / (true_positive + false_negative)
        f1 = 2 * precision * recall / (precision + recall)
        self.assertGreaterEqual(precision, 0.95)
        self.assertGreaterEqual(recall, 0.90)
        self.assertGreaterEqual(f1, 0.92)


class ObligationPersistenceAndApiTests(TestCase):
    organization_id = UUID("11111111-1111-4111-8111-111111111111")

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.regulation_id = uuid4()
        with self.session.begin():
            ensure_organization(self.session, self.organization_id, "Northstar Energy")
            self.session.add(
                RegulationRecord(
                    id=self.regulation_id,
                    organization_id=self.organization_id,
                    source_key="AER-D060-TEST",
                    title="Directive 060 Test",
                    jurisdiction="Alberta",
                )
            )
            result = VersioningService(
                SqlAlchemyVersionRepository(self.session, self.organization_id, "test-suite")
            ).ingest(
                regulation_id=self.regulation_id,
                source_uri="https://regulator.example/directive.pdf",
                raw_content="binding duties",
                sections=(
                    Section(
                        "4.2",
                        "Incident notice",
                        "Operators must notify the regulator within 24 hours. Operators may retain a courtesy copy.",
                        43,
                    ),
                ),
            )
            self.version_id = result.version.id

        self.app = create_app()

        def session_override():
            yield self.session

        self.app.dependency_overrides[get_session] = session_override

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    def test_extraction_is_idempotent_and_audited(self):
        with self.session.begin():
            first = extract_and_store_obligations(
                self.session,
                organization_id=self.organization_id,
                version_id=self.version_id,
                actor_id="analyst@example.test",
            )
        with self.session.begin():
            second = extract_and_store_obligations(
                self.session,
                organization_id=self.organization_id,
                version_id=self.version_id,
                actor_id="analyst@example.test",
            )
        self.assertEqual((first.created_count, first.existing_count), (1, 0))
        self.assertEqual((second.created_count, second.existing_count), (0, 1))
        self.assertEqual(self.session.scalar(select(func.count()).select_from(ObligationRecord)), 1)
        audit_count = self.session.scalar(
            select(func.count())
            .select_from(AuditEventRecord)
            .where(AuditEventRecord.event_type == "obligations.extracted")
        )
        self.assertEqual(audit_count, 1)

    def test_other_tenant_cannot_extract_or_list_obligations(self):
        with self.assertRaises(RegulationNotFoundError), self.session.begin():
            extract_and_store_obligations(
                self.session,
                organization_id=uuid4(),
                version_id=self.version_id,
                actor_id="intruder@example.test",
            )
        response = asyncio.run(self._request("GET", "/api/v1/obligations", uuid4()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_api_extracts_and_returns_version_page_lineage(self):
        response = asyncio.run(
            self._request(
                "POST",
                f"/api/v1/versions/{self.version_id}/obligations/extract",
                self.organization_id,
            )
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["created_count"], 1)
        self.assertEqual(body["obligations"][0]["section_key"], "4.2")
        self.assertEqual(body["obligations"][0]["page"], 43)
        self.assertEqual(body["obligations"][0]["version_ordinal"], 1)
        self.assertEqual(
            body["obligations"][0]["source_uri"], "https://regulator.example/directive.pdf"
        )
        self.assertEqual(body["obligations"][0]["raw_confidence"], 0.9)
        self.assertEqual(body["obligations"][0]["confidence"], 0.875)
        self.assertEqual(
            body["obligations"][0]["calibration_policy_id"], "obligation-calibration-v1"
        )

    def test_zero_candidate_extraction_is_also_idempotent(self):
        with self.session.begin():
            result = VersioningService(
                SqlAlchemyVersionRepository(self.session, self.organization_id, "test-suite")
            ).ingest(
                regulation_id=self.regulation_id,
                source_uri="https://regulator.example/guidance.pdf",
                raw_content="advisory only",
                sections=(Section("8", "Guidance", "Operators may retain a courtesy copy."),),
            )
            first = extract_and_store_obligations(
                self.session,
                organization_id=self.organization_id,
                version_id=result.version.id,
                actor_id="analyst@example.test",
            )
        with self.session.begin():
            second = extract_and_store_obligations(
                self.session,
                organization_id=self.organization_id,
                version_id=result.version.id,
                actor_id="analyst@example.test",
            )
        self.assertEqual((first.created_count, first.existing_count), (0, 0))
        self.assertEqual((second.created_count, second.existing_count), (0, 0))

    async def _request(self, method: str, path: str, organization_id: UUID):
        transport = httpx.ASGITransport(app=self.app)
        headers = {
            "X-Organization-ID": str(organization_id),
            "X-Actor-ID": "analyst@example.test",
        }
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, headers=headers)
