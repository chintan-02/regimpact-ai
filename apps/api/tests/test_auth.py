import asyncio
import os
import secrets
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regimpact.auth import CurrentUser, get_current_user, hash_password, issue_access_token
from regimpact.config import get_settings
from regimpact.database import Base, get_session
from regimpact.db_models import AuditEventRecord, OrganizationRecord, UserRecord
from regimpact.main import create_app


class AuthenticationTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.organization_id = uuid4()
        self.user_id = uuid4()
        self.password = secrets.token_urlsafe(24)
        with self.session.begin():
            self.session.add(OrganizationRecord(id=self.organization_id, name="Northstar Energy"))
            self.session.add(
                UserRecord(
                    id=self.user_id,
                    organization_id=self.organization_id,
                    email="analyst@example.test",
                    display_name="Reference Analyst",
                    role="analyst",
                    password_hash=hash_password(self.password),
                )
            )
        self.user = self.session.get(UserRecord, self.user_id)
        assert self.user is not None
        self.app = create_app()

        def session_override():  # type: ignore[no-untyped-def]
            yield self.session

        self.app.dependency_overrides[get_session] = session_override

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    async def request(self, method: str, path: str, **kwargs):  # type: ignore[no-untyped-def]
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    def test_login_returns_short_lived_token_and_audits_success(self) -> None:
        response = asyncio.run(
            self.request(
                "POST",
                "/api/v1/auth/login",
                json={"email": "ANALYST@example.test", "password": self.password},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["role"], "analyst")
        self.assertEqual(response.json()["token_type"], "bearer")
        self.assertGreater(len(response.json()["access_token"]), 80)
        self.assertEqual(
            self.session.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(AuditEventRecord.event_type == "authentication.login_succeeded")
            ),
            1,
        )

    def test_invalid_password_does_not_create_audit_event(self) -> None:
        response = asyncio.run(
            self.request(
                "POST",
                "/api/v1/auth/login",
                json={"email": "analyst@example.test", "password": f"{self.password}-wrong"},
            )
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.session.scalar(select(func.count()).select_from(AuditEventRecord)), 0)

    def test_demo_login_is_hidden_by_default(self) -> None:
        response = asyncio.run(
            self.request("POST", "/api/v1/auth/demo-login", json={"role": "analyst"})
        )
        self.assertEqual(response.status_code, 404)

    def test_demo_login_uses_real_user_and_is_audited(self) -> None:
        demo_password = secrets.token_urlsafe(24)
        self.user.email = "analyst@northstar.local"
        self.user.password_hash = hash_password(demo_password)
        self.session.commit()
        with patch.dict(
            os.environ,
            {
                "REGIMPACT_DEMO_MODE": "true",
                "REGIMPACT_ENVIRONMENT": "local",
                "REGIMPACT_DEMO_ADMIN_PASSWORD": secrets.token_urlsafe(24),
                "REGIMPACT_DEMO_ANALYST_PASSWORD": demo_password,
                "REGIMPACT_DEMO_VIEWER_PASSWORD": secrets.token_urlsafe(24),
            },
        ):
            get_settings.cache_clear()
            try:
                response = asyncio.run(
                    self.request("POST", "/api/v1/auth/demo-login", json={"role": "analyst"})
                )
            finally:
                get_settings.cache_clear()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], str(self.user_id))
        event = self.session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.event_type == "authentication.login_succeeded"
            )
        )
        self.assertIsNotNone(event)
        assert event is not None
        self.assertIn("demo_role_selector", event.detail_json)

    def test_production_rejects_demo_mode_configuration(self) -> None:
        with patch.dict(
            os.environ,
            {
                "REGIMPACT_DEMO_MODE": "true",
                "REGIMPACT_ENVIRONMENT": "production",
                "REGIMPACT_JWT_SECRET": secrets.token_urlsafe(32),
            },
        ):
            get_settings.cache_clear()
            try:
                with self.assertRaisesRegex(ValueError, "must be disabled in production"):
                    get_settings()
            finally:
                get_settings.cache_clear()

    def test_viewer_cannot_create_controls(self) -> None:
        self.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=uuid4(),
            organization_id=self.organization_id,
            organization_name="Northstar Energy",
            email="viewer@example.test",
            display_name="Read-only Reviewer",
            role="viewer",
        )
        response = asyncio.run(
            self.request(
                "POST",
                "/api/v1/controls",
                json={
                    "control_key": "TEST-01",
                    "title": "Unauthorized control",
                    "description": "Must not be created.",
                    "owner": "Viewer",
                    "evidence_requirement": "None",
                },
            )
        )
        self.assertEqual(response.status_code, 403)

    def test_signed_token_resolves_database_identity_and_rejects_tampering(self) -> None:
        with patch.dict(os.environ, {"REGIMPACT_AUTH_MODE": "jwt"}):
            get_settings.cache_clear()
            try:
                token, _ = issue_access_token(self.user)
                current = get_current_user(self.session, f"Bearer {token}", None, None)
                self.assertEqual(current.id, self.user_id)
                self.assertEqual(current.organization_id, self.organization_id)
                self.assertEqual(current.role, "analyst")
                with self.assertRaises(HTTPException) as caught:
                    get_current_user(self.session, f"Bearer {token}tampered", None, None)
                self.assertEqual(caught.exception.status_code, 401)
            finally:
                get_settings.cache_clear()

    def test_operational_snapshot_is_admin_only(self) -> None:
        analyst = CurrentUser(
            id=self.user_id,
            organization_id=self.organization_id,
            organization_name="Northstar Energy",
            email="analyst@example.test",
            display_name="Reference Analyst",
            role="analyst",
        )
        self.app.dependency_overrides[get_current_user] = lambda: analyst
        denied = asyncio.run(self.request("GET", "/api/v1/operations/snapshot"))
        self.assertEqual(denied.status_code, 403)

        self.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            **{**analyst.__dict__, "role": "admin"}
        )
        allowed = asyncio.run(self.request("GET", "/api/v1/operations/snapshot"))
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("requests", allowed.json())
        self.assertIn("outbox_pending", allowed.json())
