import json
import os
from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from regimpact.database import Base
from regimpact.db_models import (
    IngestionJobRecord,
    OrganizationRecord,
    OutboxEventRecord,
    RegulationRecord,
)
from regimpact.domain import utc_now
from regimpact.ingestion_service import (
    IngestionLeaseUnavailable,
    claim_ingestion_job,
    replay_dead_letter,
    retry_delay_seconds,
)
from regimpact.outbox import publish_pending


class IngestionReliabilityTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(os.getenv("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:"))
        if cls.engine.url.drivername.startswith("sqlite"):
            Base.metadata.create_all(cls.engine)

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.session = Session(bind=self.connection, expire_on_commit=False)
        self.org_id = uuid4()
        self.regulation_id = uuid4()
        self.session.add(OrganizationRecord(id=self.org_id, name="Reliability tenant"))
        self.session.add(RegulationRecord(id=self.regulation_id, organization_id=self.org_id, source_key=str(uuid4()), title="Test", jurisdiction="CA"))
        self.session.flush()

    def tearDown(self):
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def job(self, status: str = "queued") -> IngestionJobRecord:
        job = IngestionJobRecord(
            organization_id=self.org_id,
            regulation_id=self.regulation_id,
            actor_id="admin@example.test",
            status=status,
            original_filename="directive.html",
            media_type="text/html",
            size_bytes=10,
            content_hash=uuid4().hex.ljust(64, "0"),
            storage_uri="local://document",
        )
        self.session.add(job)
        self.session.flush()
        return job

    def test_live_lease_prevents_duplicate_worker_claim(self):
        job = self.job()
        first = claim_ingestion_job(self.session, job_id=job.id, organization_id=self.org_id, lease_seconds=60)
        self.assertIsNotNone(first)
        with self.assertRaises(IngestionLeaseUnavailable):
            claim_ingestion_job(self.session, job_id=job.id, organization_id=self.org_id, lease_seconds=60)

    def test_expired_lease_can_be_reclaimed(self):
        job = self.job("processing")
        previous_token = uuid4()
        job.lease_token = previous_token
        job.lease_expires_at = utc_now() - timedelta(seconds=1)
        claimed = claim_ingestion_job(self.session, job_id=job.id, organization_id=self.org_id, lease_seconds=60)
        self.assertIsNotNone(claimed)
        self.assertNotEqual(claimed[1], previous_token)

    def test_admin_replay_resets_failure_and_writes_outbox(self):
        job = self.job("dead_letter")
        job.attempt_count = 5
        job.error_code = "TimeoutError"
        replay_dead_letter(self.session, job=job, actor_id="admin@example.test")
        self.session.flush()
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.attempt_count, 0)
        self.assertEqual(job.replay_count, 1)
        self.assertIsNotNone(self.session.query(OutboxEventRecord).one_or_none())

    def test_backoff_is_bounded(self):
        for attempt in range(1, 20):
            delay = retry_delay_seconds(attempt, base=5, cap=300)
            self.assertGreaterEqual(delay, 5)
            self.assertLessEqual(delay, 300)

    def test_outbox_exhaustion_is_dead_lettered(self):
        event = OutboxEventRecord(
            organization_id=self.org_id,
            topic="ingestion.process",
            payload_json=json.dumps({"job_id": str(uuid4()), "organization_id": str(self.org_id)}),
            attempt_count=9,
        )
        self.session.add(event)
        self.session.flush()
        with patch("regimpact.outbox.process_ingestion.send", side_effect=OSError("broker down")):
            self.assertEqual(publish_pending(self.session), 0)
        self.assertIsNotNone(event.dead_lettered_at)
