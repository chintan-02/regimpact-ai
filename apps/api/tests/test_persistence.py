import json
import os
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from regimpact.database import Base
from regimpact.db_models import (
    AuditEventRecord,
    OrganizationRecord,
    OutboxEventRecord,
    RegulationRecord,
    RegulatorySourceRecord,
)
from regimpact.domain import Section, utc_now
from regimpact.ingestion import DevelopmentAllowScanner, validate_upload
from regimpact.ingestion_service import process_ingestion_job, queue_ingestion
from regimpact.outbox import publish_pending
from regimpact.repository import RegulationNotFoundError, SqlAlchemyVersionRepository
from regimpact.source_monitor import claim_due_sources
from regimpact.storage import LocalObjectStorage
from regimpact.versioning import VersioningService


class PersistenceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.getenv("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
        cls.engine = create_engine(url)
        if url.startswith("sqlite"):
            Base.metadata.create_all(cls.engine)

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.session = Session(bind=self.connection, expire_on_commit=False)
        self.org_a = uuid4()
        self.org_b = uuid4()
        self.regulation_id = uuid4()
        self.session.add_all(
            [
                OrganizationRecord(id=self.org_a, name="Northstar Energy"),
                OrganizationRecord(id=self.org_b, name="Other Tenant"),
                RegulationRecord(
                    id=self.regulation_id,
                    organization_id=self.org_a,
                    source_key=f"AER-D060-{uuid4()}",
                    title="AER Directive 060",
                    jurisdiction="Alberta",
                ),
            ]
        )
        self.session.flush()

    def tearDown(self):
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def test_version_sections_changes_and_audit_are_atomic(self):
        repository = SqlAlchemyVersionRepository(self.session, self.org_a, "analyst@example.test")
        service = VersioningService(repository)
        first = service.ingest(
            regulation_id=self.regulation_id,
            source_uri="https://regulator.example/directive-060-v1.pdf",
            raw_content="Report within 72 hours",
            sections=(Section("4.2", "Incident notice", "Report within 72 hours", 41),),
        )
        second = service.ingest(
            regulation_id=self.regulation_id,
            source_uri="https://regulator.example/directive-060-v2.pdf",
            raw_content="Report within 24 hours",
            sections=(Section("4.2", "Incident notice", "Report within 24 hours", 41),),
        )
        self.session.flush()

        self.assertEqual(first.version.ordinal, 1)
        self.assertEqual(second.version.ordinal, 2)
        self.assertEqual(len(second.changes), 1)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(AuditEventRecord)), 2)

    def test_tenant_cannot_read_another_organizations_regulation(self):
        repository = SqlAlchemyVersionRepository(self.session, self.org_b, "intruder@example.test")
        with self.assertRaises(RegulationNotFoundError):
            repository.latest(self.regulation_id)

    def test_queued_html_ingestion_is_deduplicated_and_processed(self):
        document = validate_upload(
            filename="directive.html",
            declared_media_type="text/html",
            content=b"<html><body><h1>4.2 Reporting</h1><p>Report in 24 hours.</p></body></html>",
            max_bytes=10_000,
            scanner=DevelopmentAllowScanner(),
        )
        with TemporaryDirectory() as directory:
            storage = LocalObjectStorage(directory)
            job, created = queue_ingestion(
                self.session,
                organization_id=self.org_a,
                regulation_id=self.regulation_id,
                actor_id="analyst@example.test",
                document=document,
                storage=storage,
            )
            duplicate, duplicate_created = queue_ingestion(
                self.session,
                organization_id=self.org_a,
                regulation_id=self.regulation_id,
                actor_id="analyst@example.test",
                document=document,
                storage=storage,
            )
            processed = process_ingestion_job(
                self.session,
                job_id=job.id,
                organization_id=self.org_a,
                storage=storage,
                max_pdf_pages=10,
            )
            self.session.flush()

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(job.id, duplicate.id)
        self.assertEqual(processed.status, "completed")
        self.assertIsNotNone(processed.resulting_version_id)

    def test_due_source_claim_and_dispatch_are_transactional(self):
        source = RegulatorySourceRecord(
            organization_id=self.org_a,
            regulation_id=self.regulation_id,
            name="Directive source",
            url="https://regulator.example/directive.html",
            allowed_host="regulator.example",
            poll_interval_minutes=60,
            next_check_at=utc_now(),
        )
        self.session.add(source)
        self.session.flush()
        claimed = claim_due_sources(self.session)
        self.session.flush()
        event = self.session.scalar(
            select(OutboxEventRecord).where(OutboxEventRecord.topic == "source.check")
        )
        self.assertEqual(claimed, 1)
        self.assertIsNotNone(event)

    def test_outbox_marks_event_only_after_broker_publish(self):
        event = OutboxEventRecord(
            organization_id=self.org_a,
            topic="ingestion.process",
            payload_json=json.dumps({"job_id": str(uuid4()), "organization_id": str(self.org_a)}),
        )
        self.session.add(event)
        self.session.flush()
        with patch("regimpact.outbox.process_ingestion.send") as send:
            published = publish_pending(self.session)
        self.assertEqual(published, 1)
        send.assert_called_once()
        self.assertIsNotNone(event.published_at)
