import asyncio
import json
from unittest import TestCase
from uuid import UUID, uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regimpact.api import clause_classifier
from regimpact.clause_classification_service import classify_and_store_clauses
from regimpact.clause_classifier import ClauseLabel, ClausePrediction
from regimpact.database import Base, get_session
from regimpact.db_models import (
    AuditEventRecord,
    ClauseClassificationRecord,
    ClauseClassificationRunRecord,
    RegulationRecord,
)
from regimpact.domain import Section
from regimpact.main import create_app
from regimpact.repository import (
    RegulationNotFoundError,
    SqlAlchemyVersionRepository,
    ensure_organization,
)
from regimpact.versioning import VersioningService


class FakeClassifier:
    model_id = "test-legal-encoder@dataset-v1:abc123"
    dataset_id = "dataset-v1"
    dataset_sha256 = "a" * 64

    def predict(self, text: str) -> ClausePrediction:
        reporting = "notify" in text.lower()
        label = ClauseLabel.REPORTING_REQUIREMENT if reporting else ClauseLabel.PERMISSION
        confidence = 0.91 if reporting else 0.62
        return ClausePrediction(
            label=label,
            confidence=confidence,
            abstained=not reporting,
            model_id=self.model_id,
            dataset_id=self.dataset_id,
            probabilities={label: confidence, ClauseLabel.NON_OBLIGATION: 1 - confidence},
        )


class CurrentClassifier(FakeClassifier):
    model_id = "test-legal-encoder@dataset-v2:def456"
    dataset_id = "dataset-v2"
    dataset_sha256 = "b" * 64


class ClauseClassificationServiceTests(TestCase):
    organization_id = UUID("11111111-1111-4111-8111-111111111111")

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        regulation_id = uuid4()
        with self.session.begin():
            ensure_organization(self.session, self.organization_id, "Northstar Energy")
            self.session.add(
                RegulationRecord(
                    id=regulation_id,
                    organization_id=self.organization_id,
                    source_key="AER-D060-ML",
                    title="Directive 060 Classifier Fixture",
                    jurisdiction="Alberta",
                )
            )
            version = VersioningService(
                SqlAlchemyVersionRepository(self.session, self.organization_id, "test-suite")
            ).ingest(
                regulation_id=regulation_id,
                source_uri="https://regulator.example/directive.pdf",
                raw_content="classifier fixture",
                sections=(
                    Section(
                        "4.2",
                        "Incident notice",
                        "Operators must notify the regulator within 24 hours. Operators may attach photographs.",
                        43,
                    ),
                ),
            )
            self.version_id = version.version.id
        self.app = create_app()

        def session_override():  # type: ignore[no-untyped-def]
            yield self.session

        self.app.dependency_overrides[get_session] = session_override
        self.app.dependency_overrides[clause_classifier] = CurrentClassifier

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    def test_classification_is_idempotent_audited_and_abstains(self):
        classifier = FakeClassifier()
        with self.session.begin():
            first = classify_and_store_clauses(
                self.session,
                organization_id=self.organization_id,
                version_id=self.version_id,
                actor_id="admin@example.test",
                classifier=classifier,
            )
        with self.session.begin():
            second = classify_and_store_clauses(
                self.session,
                organization_id=self.organization_id,
                version_id=self.version_id,
                actor_id="admin@example.test",
                classifier=classifier,
            )
        self.assertEqual((first.created_count, first.existing_count, first.abstained_count), (2, 0, 1))
        self.assertEqual((second.created_count, second.existing_count, second.abstained_count), (0, 2, 1))
        records = self.session.scalars(
            select(ClauseClassificationRecord).order_by(ClauseClassificationRecord.text)
        ).all()
        self.assertEqual({record.status for record in records}, {"classified", "needs_review"})
        self.assertTrue(all(record.model_id == classifier.model_id for record in records))
        self.assertTrue(all(record.dataset_sha256 == classifier.dataset_sha256 for record in records))
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(ClauseClassificationRunRecord)), 1
        )
        event = self.session.scalar(
            select(AuditEventRecord).where(AuditEventRecord.event_type == "clauses.classified")
        )
        self.assertIsNotNone(event)
        detail = json.loads(event.detail_json)
        self.assertEqual(detail["abstained_count"], 1)
        self.assertEqual(detail["model_id"], classifier.model_id)

    def test_other_tenant_cannot_classify_version(self):
        with self.assertRaises(RegulationNotFoundError), self.session.begin():
            classify_and_store_clauses(
                self.session,
                organization_id=uuid4(),
                version_id=self.version_id,
                actor_id="intruder@example.test",
                classifier=FakeClassifier(),
            )

    def test_post_response_contains_only_the_current_model_run(self):
        with self.session.begin():
            classify_and_store_clauses(
                self.session,
                organization_id=self.organization_id,
                version_id=self.version_id,
                actor_id="historical-model",
                classifier=FakeClassifier(),
            )

        response = asyncio.run(
            self._request(
                "POST",
                f"/api/v1/versions/{self.version_id}/clauses/classify",
            )
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["created_count"], 2)
        self.assertEqual(len(body["classifications"]), 2)
        self.assertEqual(
            {item["model_id"] for item in body["classifications"]},
            {CurrentClassifier.model_id},
        )

    async def _request(self, method: str, path: str):
        transport = httpx.ASGITransport(app=self.app)
        headers = {
            "X-Organization-ID": str(self.organization_id),
            "X-Actor-ID": "admin@example.test",
        }
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, headers=headers)
import httpx
