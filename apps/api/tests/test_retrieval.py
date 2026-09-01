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
from regimpact.embeddings import (
    EMBEDDING_DIMENSIONS,
    FeatureHashEmbeddingProvider,
    configured_embedding_provider,
)
from regimpact.main import create_app
from regimpact.repository import (
    RegulationNotFoundError,
    SqlAlchemyVersionRepository,
    ensure_organization,
)
from regimpact.retrieval import hybrid_search, index_version
from regimpact.versioning import VersioningService


class HybridRetrievalTests(TestCase):
    organization_id = UUID("11111111-1111-4111-8111-111111111111")

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.regulation_id = uuid4()
        with self.session.begin():
            ensure_organization(self.session, self.organization_id, "Northstar")
            self.session.add(
                RegulationRecord(
                    id=self.regulation_id,
                    organization_id=self.organization_id,
                    source_key="TEST-R",
                    title="Test rule",
                    jurisdiction="Alberta",
                )
            )
            result = VersioningService(
                SqlAlchemyVersionRepository(self.session, self.organization_id, "test")
            ).ingest(
                regulation_id=self.regulation_id,
                source_uri="https://example.test/rule.pdf",
                raw_content="v1",
                sections=(
                    Section(
                        "4.2",
                        "Incident notification",
                        "Operators must report a release within 24 hours.",
                        12,
                    ),
                    Section(
                        "6.1",
                        "Records",
                        "Measurement records must be retained for seven years.",
                        22,
                    ),
                    Section("8.4", "Training", "Workers must complete annual safety training.", 31),
                ),
            )
            self.version_id = result.version.id
        self.provider = FeatureHashEmbeddingProvider()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_embeddings_are_deterministic_normalized_and_dimensioned(self):
        first = self.provider.embed(("incident reporting",))[0]
        second = self.provider.embed(("incident reporting",))[0]
        self.assertEqual(first, second)
        self.assertEqual(len(first), EMBEDDING_DIMENSIONS)

    def test_local_baseline_fails_closed_outside_local_environment(self):
        with self.assertRaisesRegex(RuntimeError, "restricted to local"):
            configured_embedding_provider(
                environment="production",
                provider_name="feature_hash",
                model_name="unused",
            )

    def test_index_is_idempotent_and_search_returns_citation_lineage(self):
        with self.session.begin():
            first = index_version(
                self.session,
                organization_id=self.organization_id,
                version_id=self.version_id,
                provider=self.provider,
            )
        with self.session.begin():
            second = index_version(
                self.session,
                organization_id=self.organization_id,
                version_id=self.version_id,
                provider=self.provider,
            )
        hits = hybrid_search(
            self.session,
            organization_id=self.organization_id,
            query="report incident within 24 hours",
            provider=self.provider,
        )
        self.assertEqual(first, (3, 0))
        self.assertEqual(second, (0, 3))
        self.assertEqual(hits[0].section_key, "4.2")
        self.assertEqual(hits[0].page, 12)
        self.assertEqual(hits[0].version_ordinal, 1)
        self.assertEqual(hits[0].source_uri, "https://example.test/rule.pdf")

    def test_tenant_isolation_applies_to_index_and_search(self):
        with self.assertRaises(RegulationNotFoundError), self.session.begin():
            index_version(
                self.session,
                organization_id=uuid4(),
                version_id=self.version_id,
                provider=self.provider,
            )
        self.assertEqual(
            hybrid_search(
                self.session, organization_id=uuid4(), query="incident", provider=self.provider
            ),
            [],
        )

    def test_api_contract_indexes_and_searches(self):
        app = create_app()

        def override():
            yield self.session

        app.dependency_overrides[get_session] = override

        async def run():
            transport = httpx.ASGITransport(app=app)
            headers = {"X-Organization-ID": str(self.organization_id)}
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                indexed = await client.post(
                    f"/api/v1/versions/{self.version_id}/search-index", headers=headers
                )
                searched = await client.get(
                    "/api/v1/search", params={"q": "incident report"}, headers=headers
                )
                return indexed, searched

        indexed, searched = asyncio.run(run())
        self.assertEqual(indexed.status_code, 200)
        self.assertEqual(searched.status_code, 200)
        self.assertEqual(searched.json()["results"][0]["section_key"], "4.2")
