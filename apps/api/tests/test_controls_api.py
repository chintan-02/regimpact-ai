import asyncio
from unittest import TestCase
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regimpact.control_mapping import add_control, suggest_mappings
from regimpact.database import Base, get_session
from regimpact.db_models import ObligationRecord, OrganizationRecord, RegulationRecord
from regimpact.domain import Section
from regimpact.main import create_app
from regimpact.obligation_service import extract_and_store_obligations
from regimpact.repository import SqlAlchemyVersionRepository
from regimpact.versioning import VersioningService


class ControlsApiTests(TestCase):
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
        regulation_id = uuid4()
        with self.session.begin():
            self.session.add_all(
                [
                    OrganizationRecord(id=self.organization_id, name="Northstar Energy"),
                    OrganizationRecord(id=self.other_organization_id, name="Other Tenant"),
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
                raw_content="current edition",
                sections=(
                    Section(
                        "4.2",
                        "Incident notification",
                        "Operators must report incidents within 24 hours.",
                        43,
                    ),
                ),
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
                title="Regulatory incident notification",
                description="Report incidents within the prescribed window.",
                owner="Regulatory Compliance",
                evidence_requirement="Submission receipt",
            )
            obligation = self.session.scalar(select(ObligationRecord))
            assert obligation is not None
            suggest_mappings(
                self.session,
                organization_id=self.organization_id,
                obligation_id=obligation.id,
                actor_id="test-suite",
            )

        self.app = create_app()

        def session_override():  # type: ignore[no-untyped-def]
            yield self.session

        self.app.dependency_overrides[get_session] = session_override

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    async def request(self, path: str, organization_id=None):  # type: ignore[no-untyped-def]
        transport = httpx.ASGITransport(app=self.app)
        headers = {
            "X-Organization-ID": str(organization_id or self.organization_id),
        }
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, headers=headers)

    def test_catalogue_and_mapping_read_models_include_control_context(self) -> None:
        controls = asyncio.run(self.request("/api/v1/controls"))
        mappings = asyncio.run(self.request("/api/v1/control-mappings"))

        self.assertEqual(controls.status_code, 200)
        self.assertEqual(controls.json()[0]["control_key"], "REG-IR-01")
        self.assertEqual(mappings.status_code, 200)
        self.assertEqual(mappings.json()[0]["control_title"], "Regulatory incident notification")

    def test_catalogue_and_mappings_enforce_organization_boundary(self) -> None:
        controls = asyncio.run(
            self.request("/api/v1/controls", organization_id=self.other_organization_id)
        )
        mappings = asyncio.run(
            self.request("/api/v1/control-mappings", organization_id=self.other_organization_id)
        )

        self.assertEqual(controls.json(), [])
        self.assertEqual(mappings.json(), [])
