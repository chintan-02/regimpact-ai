import json
from unittest import TestCase
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from regimpact.control_mapping import add_control, suggest_mappings
from regimpact.database import Base
from regimpact.db_models import ObligationRecord, OrganizationRecord, RegulationRecord
from regimpact.domain import Section
from regimpact.obligation_service import extract_and_store_obligations
from regimpact.repository import SqlAlchemyVersionRepository
from regimpact.versioning import VersioningService


class ControlMappingTests(TestCase):
    def test_versioning_mapping_and_idempotency(self):
        e = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(e)
        s = Session(e, expire_on_commit=False)
        org = uuid4()
        reg = uuid4()
        with s.begin():
            s.add_all(
                [
                    OrganizationRecord(id=org, name="Org"),
                    RegulationRecord(
                        id=reg,
                        organization_id=org,
                        source_key="R1",
                        title="Rule",
                        jurisdiction="AB",
                    ),
                ]
            )
            s.flush()
            v = VersioningService(SqlAlchemyVersionRepository(s, org, "test")).ingest(
                regulation_id=reg,
                source_uri="https://example.test/r",
                raw_content="v1",
                sections=(
                    Section("1", "Incident", "Operators must report incidents within 24 hours.", 1),
                ),
            )
            extract_and_store_obligations(
                s, organization_id=org, version_id=v.version.id, actor_id="test"
            )
        obligation = s.scalar(select(ObligationRecord))
        s.commit()
        with s.begin():
            _, v1 = add_control(
                s,
                organization_id=org,
                control_key="INC-01",
                title="Incident reporting",
                description="Report incidents promptly",
                owner="Compliance",
                evidence_requirement="Incident submission receipt",
            )
            _, same = add_control(
                s,
                organization_id=org,
                control_key="INC-01",
                title="Incident reporting",
                description="Report incidents promptly",
                owner="Compliance",
                evidence_requirement="Incident submission receipt",
            )
            first = suggest_mappings(
                s, organization_id=org, obligation_id=obligation.id, actor_id="test"
            )
        with s.begin():
            second = suggest_mappings(
                s, organization_id=org, obligation_id=obligation.id, actor_id="test"
            )
        self.assertEqual(v1.id, same.id)
        self.assertEqual(first[0].id, second[0].id)
        self.assertIn(first[0].status, {"suggested", "needs_review", "ambiguous"})
        explanation = json.loads(first[0].explanation_json)
        self.assertNotIn("the", explanation["matched_terms"])
        s.close()
        e.dispose()
