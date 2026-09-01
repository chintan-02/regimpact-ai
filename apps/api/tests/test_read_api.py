import asyncio
from unittest import TestCase
from uuid import UUID, uuid4

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regimpact.database import Base, get_session
from regimpact.db_models import RegulationRecord
from regimpact.domain import Section
from regimpact.main import create_app
from regimpact.repository import SqlAlchemyVersionRepository, ensure_organization
from regimpact.versioning import VersioningService


class ReadApiTests(TestCase):
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
            ensure_organization(self.session, self.organization_id, "Test Organization")
            self.session.add(
                RegulationRecord(
                    id=self.regulation_id,
                    organization_id=self.organization_id,
                    source_key="TEST-100",
                    title="Test Regulation",
                    jurisdiction="Alberta",
                )
            )
            repository = SqlAlchemyVersionRepository(
                self.session, self.organization_id, "test-suite"
            )
            service = VersioningService(repository)
            service.ingest(
                regulation_id=self.regulation_id,
                source_uri="https://example.test/v1.pdf",
                raw_content="version one",
                sections=(Section("1", "Reporting", "Report within 72 hours.", 8),),
            )
            service.ingest(
                regulation_id=self.regulation_id,
                source_uri="https://example.test/v2.pdf",
                raw_content="version two",
                sections=(
                    Section("1", "Reporting", "Report within 24 hours.", 9),
                    Section("2", "Evidence", "Retain evidence for seven years.", 10),
                ),
            )

        self.app = create_app()

        def session_override():
            yield self.session

        self.app.dependency_overrides[get_session] = session_override

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    async def request(self, path: str, organization_id: UUID | None = None):
        transport = httpx.ASGITransport(app=self.app)
        headers = {"X-Organization-ID": str(organization_id or self.organization_id)}
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, headers=headers)

    def test_register_returns_latest_version_changes_and_citations(self):
        regulations = asyncio.run(self.request("/api/v1/regulations"))
        changes = asyncio.run(self.request("/api/v1/changes"))

        self.assertEqual(regulations.status_code, 200)
        self.assertEqual(regulations.json()[0]["latest_version_ordinal"], 2)
        self.assertEqual(len(changes.json()), 2)

        detail = asyncio.run(self.request(f"/api/v1/changes/{changes.json()[0]['id']}"))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["current_citation"]["version_ordinal"], 2)
        self.assertIn(detail.json()["change_type"], {"added", "modified"})

    def test_read_endpoints_enforce_organization_boundary(self):
        other_organization = uuid4()
        regulations = asyncio.run(
            self.request("/api/v1/regulations", organization_id=other_organization)
        )
        changes = asyncio.run(self.request("/api/v1/changes", organization_id=other_organization))
        owned_change = asyncio.run(self.request("/api/v1/changes")).json()[0]
        detail = asyncio.run(
            self.request(
                f"/api/v1/changes/{owned_change['id']}", organization_id=other_organization
            )
        )

        self.assertEqual(regulations.json(), [])
        self.assertEqual(changes.json(), [])
        self.assertEqual(detail.status_code, 404)
