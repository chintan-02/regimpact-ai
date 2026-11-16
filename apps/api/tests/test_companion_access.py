import asyncio
import json
import time
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from redis.exceptions import RedisError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regimpact.companion_access import DELEGATED_SCOPES
from regimpact.companion_grant_operations import (
    CHANGE_ACKNOWLEDGEMENT,
    DISABLE_ACKNOWLEDGEMENT,
    GRANT_ACKNOWLEDGEMENT,
    CompanionGrantOperationError,
    change_companion_grant_scopes,
    create_companion_grant,
    disable_companion_grant,
)
from regimpact.config import Settings
from regimpact.database import Base, get_session
from regimpact.db_models import (
    AuditEventRecord,
    CompanionClientGrantRecord,
    ExternalIdentityRecord,
    OrganizationRecord,
    RegulationRecord,
    UserRecord,
)
from regimpact.main import create_app
from regimpact.token_validation import SigningKeyProvider

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
API_AUDIENCE = UUID("22222222-2222-4222-8222-222222222222")
CLIENT_ID = UUID("33333333-3333-4333-8333-333333333333")
ISSUER = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"


class StaticKeyProvider(SigningKeyProvider):
    def __init__(self, key_id: str, public_key: object) -> None:
        self.key_id = key_id
        self.public_key = public_key

    def get_signing_key(self, key_id: str) -> object:
        assert key_id == self.key_id
        return self.public_key


class MemoryRateLimitStore:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def increment(self, key: str, ttl_seconds: int) -> int:
        del ttl_seconds
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]


class UnavailableRateLimitStore:
    def increment(self, key: str, ttl_seconds: int) -> int:
        del key, ttl_seconds
        raise RedisError("unavailable")


class CompanionAccessTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.organization_id = uuid4()
        self.other_organization_id = uuid4()
        self.user_id = uuid4()
        self.external_oid = uuid4()
        self.grant_id = uuid4()
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.key_id = "companion-test-key"
        self.provider = StaticKeyProvider(self.key_id, self.private_key.public_key())
        self.settings = Settings(
            environment="test",
            auth_mode="entra",
            entra_tenant_id=str(TENANT_ID),
            entra_issuer=ISSUER,
            entra_api_audience=str(API_AUDIENCE),
            entra_jwks_url="http://test.local/keys",
            companion_access_enabled=True,
            companion_client_id=str(CLIENT_ID),
            companion_rate_limit_per_minute=10,
            companion_search_rate_limit_per_minute=2,
        )
        with Session(self.engine) as session, session.begin():
            session.add_all(
                [
                    OrganizationRecord(id=self.organization_id, name="Companion tenant"),
                    OrganizationRecord(id=self.other_organization_id, name="Foreign tenant"),
                ]
            )
            session.add(
                UserRecord(
                    id=self.user_id,
                    organization_id=self.organization_id,
                    email="viewer@example.test",
                    display_name="Viewer",
                    role="viewer",
                    password_hash="disabled",
                    active=True,
                )
            )
            session.add(
                ExternalIdentityRecord(
                    provider="entra",
                    tenant_id=TENANT_ID,
                    external_oid=self.external_oid,
                    user_id=self.user_id,
                    organization_id=self.organization_id,
                    active=True,
                    created_by_actor_id="test",
                    updated_by_actor_id="test",
                )
            )
            session.add(
                CompanionClientGrantRecord(
                    id=self.grant_id,
                    organization_id=self.organization_id,
                    tenant_id=TENANT_ID,
                    client_id=CLIENT_ID,
                    delegated_scopes_json=json.dumps(sorted(DELEGATED_SCOPES)),
                    active=True,
                    created_by_actor_id="operator:test",
                    updated_by_actor_id="operator:test",
                )
            )
            session.add(
                RegulationRecord(
                    organization_id=self.organization_id,
                    source_key="COMP-1",
                    title="Companion regulation",
                    jurisdiction="CA",
                )
            )
            session.add(
                RegulationRecord(
                    organization_id=self.other_organization_id,
                    source_key="FOREIGN-1",
                    title="Foreign regulation",
                    jurisdiction="CA",
                )
            )
        self.rate_store: MemoryRateLimitStore | UnavailableRateLimitStore = (
            MemoryRateLimitStore()
        )
        with patch("regimpact.main.get_settings", return_value=self.settings):
            self.app = create_app()

        def session_override():
            with Session(self.engine, expire_on_commit=False) as session:
                yield session

        self.app.dependency_overrides[get_session] = session_override

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.engine.dispose()

    def token(
        self,
        *,
        scopes: str = "regulations:read",
        client_id: UUID = CLIENT_ID,
        audience: UUID = API_AUDIENCE,
        identity_type: str = "user",
    ) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "aud": str(audience),
                "azp": str(client_id),
                "exp": now + 600,
                "iat": now,
                "idtyp": identity_type,
                "iss": ISSUER,
                "nbf": now - 1,
                "oid": str(self.external_oid),
                "sub": "pairwise-subject",
                "tid": str(TENANT_ID),
                "uti": "companion-test-token",
                "ver": "2.0",
                "scp": scopes,
            },
            self.private_key,
            algorithm="RS256",
            headers={"kid": self.key_id, "typ": "JWT"},
        )

    async def request(self, path: str, *, token: str | None = None) -> httpx.Response:
        transport = httpx.ASGITransport(app=self.app)
        headers = {"Authorization": f"Bearer {token or self.token()}"}
        with (
            patch("regimpact.auth.get_settings", return_value=self.settings),
            patch("regimpact.auth.get_jwks_provider", return_value=self.provider),
            patch(
                "regimpact.companion_access.get_rate_limit_store",
                return_value=self.rate_store,
            ),
        ):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(path, headers=headers)

    def test_valid_delegated_access_is_audited(self) -> None:
        response = asyncio.run(self.request("/api/v1/regulations"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["source_key"] for item in response.json()], ["COMP-1"])
        with Session(self.engine) as session:
            event = session.scalar(
                select(AuditEventRecord).where(
                    AuditEventRecord.event_type == "companion.api_call_authorized"
                )
            )
            assert event is not None
            self.assertIn("regulations:read", event.detail_json)
            self.assertNotIn(str(self.external_oid), event.detail_json)

    def test_wrong_scope_unapproved_client_and_prohibited_route_are_denied(self) -> None:
        missing_scope = asyncio.run(
            self.request("/api/v1/regulations", token=self.token(scopes=""))
        )
        wrong_scope = asyncio.run(
            self.request("/api/v1/regulations", token=self.token(scopes="changes:read"))
        )
        wrong_client = asyncio.run(
            self.request("/api/v1/regulations", token=self.token(client_id=uuid4()))
        )
        prohibited = asyncio.run(self.request("/api/v1/auth/me"))
        self.assertEqual(missing_scope.status_code, 403)
        self.assertEqual(wrong_scope.status_code, 403)
        self.assertEqual(wrong_client.status_code, 403)
        self.assertEqual(prohibited.status_code, 403)
        with Session(self.engine) as session:
            self.assertGreaterEqual(
                len(
                    list(
                        session.scalars(
                            select(AuditEventRecord).where(
                                AuditEventRecord.event_type == "companion.api_call_denied"
                            )
                        )
                    )
                ),
                4,
            )

    def test_disabled_grant_and_rate_limit_dependency_fail_closed(self) -> None:
        with Session(self.engine) as session, session.begin():
            grant = session.get(CompanionClientGrantRecord, self.grant_id)
            assert grant is not None
            grant.active = False
            grant.disabled_at = grant.updated_at
        disabled = asyncio.run(self.request("/api/v1/regulations"))
        self.assertEqual(disabled.status_code, 403)

        with Session(self.engine) as session, session.begin():
            grant = session.get(CompanionClientGrantRecord, self.grant_id)
            assert grant is not None
            grant.active = True
            grant.disabled_at = None
        self.rate_store = UnavailableRateLimitStore()
        unavailable = asyncio.run(self.request("/api/v1/regulations"))
        self.assertEqual(unavailable.status_code, 503)

    def test_emergency_shutdown_and_rate_limit_fail_closed(self) -> None:
        disabled = self.settings.model_copy(update={"companion_access_enabled": False})
        self.settings = disabled
        shutdown = asyncio.run(self.request("/api/v1/regulations"))
        self.assertEqual(shutdown.status_code, 403)

        self.settings = disabled.model_copy(
            update={"companion_access_enabled": True, "companion_rate_limit_per_minute": 1}
        )
        self.rate_store.values.clear()
        rate_token = self.token()
        with patch("regimpact.companion_access.time.time", return_value=120):
            first = asyncio.run(self.request("/api/v1/regulations", token=rate_token))
            second = asyncio.run(self.request("/api/v1/regulations", token=rate_token))
        with patch("regimpact.companion_access.time.time", return_value=180):
            reset = asyncio.run(self.request("/api/v1/regulations", token=rate_token))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertGreaterEqual(int(second.headers["Retry-After"]), 1)
        self.assertEqual(reset.status_code, 200)

    def test_app_principal_and_wrong_audience_are_rejected(self) -> None:
        app = asyncio.run(
            self.request("/api/v1/regulations", token=self.token(identity_type="app"))
        )
        wrong_audience = asyncio.run(
            self.request("/api/v1/regulations", token=self.token(audience=uuid4()))
        )
        self.assertEqual(app.status_code, 401)
        self.assertEqual(wrong_audience.status_code, 401)


class CompanionGrantOperationTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.organization_id = uuid4()
        self.admin_id = uuid4()
        with self.session.begin():
            self.session.add(OrganizationRecord(id=self.organization_id, name="Tenant"))
            self.session.add(
                UserRecord(
                    id=self.admin_id,
                    organization_id=self.organization_id,
                    email="admin@example.test",
                    display_name="Admin",
                    role="admin",
                    password_hash="disabled",
                    active=True,
                )
            )
        self.settings = Settings(
            environment="test",
            auth_mode="entra",
            entra_tenant_id=str(TENANT_ID),
            entra_issuer=ISSUER,
            entra_api_audience=str(API_AUDIENCE),
            entra_jwks_url="http://test.local/keys",
            companion_client_id=str(CLIENT_ID),
        )

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_offline_lifecycle_is_scoped_and_audited(self) -> None:
        grant = create_companion_grant(
            self.session,
            self.settings,
            admin_user_id=self.admin_id,
            scopes=("regulations:read", "evidence:read"),
            acknowledgement=GRANT_ACKNOWLEDGEMENT,
        )
        changed = change_companion_grant_scopes(
            self.session,
            grant_id=grant.id,
            admin_user_id=self.admin_id,
            scopes=("regulations:read",),
            acknowledgement=CHANGE_ACKNOWLEDGEMENT,
        )
        self.assertEqual(changed.delegated_scopes_json, '["regulations:read"]')
        disabled = disable_companion_grant(
            self.session,
            grant_id=grant.id,
            admin_user_id=self.admin_id,
            acknowledgement=DISABLE_ACKNOWLEDGEMENT,
        )
        self.assertFalse(disabled.active)
        self.assertEqual(
            len(list(self.session.scalars(select(AuditEventRecord)))),
            3,
        )

    def test_wildcard_and_conflicting_grants_are_rejected_and_audited(self) -> None:
        with self.assertRaises(CompanionGrantOperationError):
            create_companion_grant(
                self.session,
                self.settings,
                admin_user_id=self.admin_id,
                scopes=("*",),
                acknowledgement=GRANT_ACKNOWLEDGEMENT,
            )
        create_companion_grant(
            self.session,
            self.settings,
            admin_user_id=self.admin_id,
            scopes=("regulations:read",),
            acknowledgement=GRANT_ACKNOWLEDGEMENT,
        )
        with self.assertRaises(CompanionGrantOperationError):
            create_companion_grant(
                self.session,
                self.settings,
                admin_user_id=self.admin_id,
                scopes=("regulations:read",),
                acknowledgement=GRANT_ACKNOWLEDGEMENT,
            )
        rejected = self.session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.event_type == "companion.client_grant_create_rejected"
            )
        )
        self.assertIsNotNone(rejected)

    def test_companion_configuration_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            Settings(
                environment="test",
                auth_mode="legacy",
                companion_access_enabled=True,
                companion_client_id=str(CLIENT_ID),
            )
        with self.assertRaises(ValueError):
            Settings(
                environment="test",
                auth_mode="entra",
                entra_tenant_id=str(TENANT_ID),
                entra_issuer=ISSUER,
                entra_api_audience=str(API_AUDIENCE),
                entra_jwks_url="http://test.local/keys",
                companion_access_enabled=True,
                companion_client_id="not-a-uuid",
            )
