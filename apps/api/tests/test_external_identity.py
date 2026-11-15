import asyncio
import logging
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regimpact.auth import CurrentUser, get_current_user
from regimpact.config import get_settings
from regimpact.database import Base, get_session
from regimpact.db_models import (
    AuditEventRecord,
    ExternalIdentityRecord,
    OrganizationRecord,
    UserRecord,
)
from regimpact.external_identities import (
    ExternalIdentityConflictError,
    ExternalIdentityForbiddenError,
    ExternalIdentityNotFoundError,
    create_external_identity_mapping,
    disable_external_identity_mapping,
    list_external_identity_mappings,
)
from regimpact.main import create_app

TENANT_ID = uuid4()


class ExternalIdentityMappingTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with self.engine.connect() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.organization_id = uuid4()
        self.other_organization_id = uuid4()
        self.admin_id = uuid4()
        self.target_id = uuid4()
        self.other_target_id = uuid4()
        self.foreign_target_id = uuid4()
        with self.session.begin():
            self.session.add_all(
                [
                    OrganizationRecord(id=self.organization_id, name="Northstar Energy"),
                    OrganizationRecord(id=self.other_organization_id, name="Other tenant"),
                    self.user(self.admin_id, self.organization_id, "admin", "admin@example.test"),
                    self.user(
                        self.target_id,
                        self.organization_id,
                        "viewer",
                        "target@example.test",
                    ),
                    self.user(
                        self.other_target_id,
                        self.organization_id,
                        "analyst",
                        "other@example.test",
                    ),
                    self.user(
                        self.foreign_target_id,
                        self.other_organization_id,
                        "viewer",
                        "foreign@example.test",
                    ),
                ]
            )
        self.admin = self.current_user(self.admin_id, "admin")
        self.viewer = self.current_user(self.target_id, "viewer")
        self.service_admin = CurrentUser(
            **{**self.admin.__dict__, "principal_type": "service"}
        )
        self.app = create_app()

        def session_override():  # type: ignore[no-untyped-def]
            yield self.session

        self.app.dependency_overrides[get_session] = session_override

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    @staticmethod
    def user(user_id, organization_id, role: str, email: str) -> UserRecord:  # type: ignore[no-untyped-def]
        return UserRecord(
            id=user_id,
            organization_id=organization_id,
            email=email,
            display_name=email,
            role=role,
            password_hash="not-used",
        )

    def current_user(self, user_id, role: str) -> CurrentUser:  # type: ignore[no-untyped-def]
        return CurrentUser(
            id=user_id,
            organization_id=self.organization_id,
            organization_name="Northstar Energy",
            email=f"{role}@example.test",
            display_name=role.title(),
            role=role,
        )

    async def request(self, method: str, path: str, **kwargs):  # type: ignore[no-untyped-def]
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    def create_mapping(self, *, user_id=None, external_oid=None):  # type: ignore[no-untyped-def]
        return create_external_identity_mapping(
            self.session,
            self.admin,
            tenant_id=TENANT_ID,
            external_oid=external_oid or uuid4(),
            user_id=user_id or self.target_id,
        )

    def audit_events(self) -> list[AuditEventRecord]:
        return list(
            self.session.scalars(
                select(AuditEventRecord).order_by(AuditEventRecord.created_at, AuditEventRecord.id)
            )
        )

    def test_create_list_disable_lifecycle_is_audited_without_external_oid(self) -> None:
        external_oid = uuid4()
        record = self.create_mapping(external_oid=external_oid)
        listed = list_external_identity_mappings(
            self.session,
            self.admin,
            tenant_id=TENANT_ID,
            limit=50,
            offset=0,
        )
        self.assertEqual([item.id for item in listed], [record.id])
        disabled = disable_external_identity_mapping(
            self.session,
            self.admin,
            mapping_id=record.id,
            tenant_id=TENANT_ID,
            auth_mode="legacy",
        )
        self.assertFalse(disabled.active)
        self.assertIsNotNone(disabled.disabled_at)
        self.assertEqual(disabled.updated_by_actor_id, self.admin.actor_id)
        with self.assertRaises(ExternalIdentityConflictError):
            disable_external_identity_mapping(
                self.session,
                self.admin,
                mapping_id=record.id,
                tenant_id=TENANT_ID,
                auth_mode="legacy",
            )
        events = self.audit_events()
        self.assertEqual(
            [event.event_type for event in events],
            [
                "identity.external_mapping_created",
                "identity.external_mapping_disabled",
                "identity.external_mapping_disable_rejected",
            ],
        )
        self.assertNotIn(str(external_oid), "".join(event.detail_json for event in events))

    def test_conflicting_relink_and_self_link_are_rejected_and_audited(self) -> None:
        external_oid = uuid4()
        original = self.create_mapping(external_oid=external_oid)
        with self.assertRaises(ExternalIdentityConflictError):
            self.create_mapping(user_id=self.other_target_id, external_oid=external_oid)
        with self.assertRaises(ExternalIdentityConflictError):
            self.create_mapping(user_id=self.admin_id)
        persisted = self.session.get(ExternalIdentityRecord, original.id)
        assert persisted is not None
        self.assertEqual(persisted.user_id, self.target_id)
        rejected = [
            event
            for event in self.audit_events()
            if event.event_type == "identity.external_mapping_create_rejected"
        ]
        self.assertEqual(len(rejected), 2)
        self.assertTrue(all(str(external_oid) not in event.detail_json for event in rejected))

    def test_cross_organization_or_unknown_target_is_not_linked(self) -> None:
        for user_id in (self.foreign_target_id, uuid4()):
            with self.subTest(user_id=user_id), self.assertRaises(
                ExternalIdentityNotFoundError
            ):
                self.create_mapping(user_id=user_id)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(ExternalIdentityRecord)),
            0,
        )

    def test_database_constraints_prevent_duplicate_and_unsafe_user_deletion(self) -> None:
        external_oid = uuid4()
        self.create_mapping(external_oid=external_oid)
        duplicate = ExternalIdentityRecord(
            provider="entra",
            tenant_id=TENANT_ID,
            external_oid=external_oid,
            user_id=self.other_target_id,
            organization_id=self.organization_id,
            active=True,
            created_by_actor_id=self.admin.actor_id,
            updated_by_actor_id=self.admin.actor_id,
        )
        self.session.add(duplicate)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

        duplicate_user_mapping = ExternalIdentityRecord(
            provider="entra",
            tenant_id=TENANT_ID,
            external_oid=uuid4(),
            user_id=self.target_id,
            organization_id=self.organization_id,
            active=True,
            created_by_actor_id=self.admin.actor_id,
            updated_by_actor_id=self.admin.actor_id,
        )
        self.session.add(duplicate_user_mapping)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

        invalid_provider = ExternalIdentityRecord(
            provider="ENTRA",
            tenant_id=TENANT_ID,
            external_oid=uuid4(),
            user_id=self.other_target_id,
            organization_id=self.organization_id,
            active=True,
            created_by_actor_id=self.admin.actor_id,
            updated_by_actor_id=self.admin.actor_id,
        )
        self.session.add(invalid_provider)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

        cross_organization = ExternalIdentityRecord(
            provider="entra",
            tenant_id=TENANT_ID,
            external_oid=uuid4(),
            user_id=self.other_target_id,
            organization_id=self.other_organization_id,
            active=True,
            created_by_actor_id=self.admin.actor_id,
            updated_by_actor_id=self.admin.actor_id,
        )
        self.session.add(cross_organization)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

        target = self.session.get(UserRecord, self.target_id)
        assert target is not None
        self.session.delete(target)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

    def test_concurrent_uniqueness_race_fails_closed_and_is_audited(self) -> None:
        external_oid = uuid4()
        original = self.create_mapping(external_oid=external_oid)
        with (
            patch("regimpact.external_identities._find_identity_mapping", return_value=None),
            self.assertRaises(ExternalIdentityConflictError),
        ):
            self.create_mapping(user_id=self.other_target_id, external_oid=external_oid)
        persisted = self.session.get(ExternalIdentityRecord, original.id)
        assert persisted is not None
        self.assertEqual(persisted.user_id, self.target_id)
        event = self.session.scalar(
            select(AuditEventRecord)
            .where(AuditEventRecord.event_type == "identity.external_mapping_create_rejected")
            .order_by(AuditEventRecord.created_at.desc())
        )
        assert event is not None
        self.assertIn("database_identity_conflict", event.detail_json)
        self.assertNotIn(str(external_oid), event.detail_json)
        with Session(self.engine) as verification_session:
            durable_event = verification_session.get(AuditEventRecord, event.id)
            self.assertIsNotNone(durable_event)
        subsequent = self.create_mapping(
            user_id=self.other_target_id,
            external_oid=uuid4(),
        )
        self.assertEqual(subsequent.user_id, self.other_target_id)

    def test_non_admin_and_service_principal_management_are_denied_and_audited(self) -> None:
        for actor in (self.viewer, self.service_admin):
            with self.subTest(actor=actor.principal_type), self.assertRaises(
                ExternalIdentityForbiddenError
            ):
                create_external_identity_mapping(
                    self.session,
                    actor,
                    tenant_id=TENANT_ID,
                    external_oid=uuid4(),
                    user_id=self.other_target_id,
                )
        record = self.create_mapping()
        with self.assertRaises(ExternalIdentityForbiddenError):
            disable_external_identity_mapping(
                self.session,
                self.viewer,
                mapping_id=record.id,
                tenant_id=TENANT_ID,
                auth_mode="legacy",
            )
        self.session.refresh(record)
        self.assertTrue(record.active)
        denied = [
            event
            for event in self.audit_events()
            if event.event_type == "identity.external_mapping_management_rejected"
        ]
        self.assertEqual(len(denied), 3)

    def test_inactive_administrator_cannot_manage_mappings(self) -> None:
        admin_record = self.session.get(UserRecord, self.admin_id)
        assert admin_record is not None
        admin_record.active = False
        self.session.commit()
        with self.assertRaises(ExternalIdentityForbiddenError):
            list_external_identity_mappings(
                self.session,
                self.admin,
                tenant_id=TENANT_ID,
                limit=50,
                offset=0,
            )
        self.assertEqual(
            self.audit_events()[-1].event_type,
            "identity.external_mapping_management_rejected",
        )

    def test_self_and_last_admin_mapping_disable_are_blocked(self) -> None:
        self_mapping = ExternalIdentityRecord(
            provider="entra",
            tenant_id=TENANT_ID,
            external_oid=uuid4(),
            user_id=self.admin_id,
            organization_id=self.organization_id,
            active=True,
            created_by_actor_id="operator:bootstrap",
            updated_by_actor_id="operator:bootstrap",
        )
        self.session.add(self_mapping)
        self.session.commit()
        with self.assertRaises(ExternalIdentityConflictError):
            disable_external_identity_mapping(
                self.session,
                self.admin,
                mapping_id=self_mapping.id,
                tenant_id=TENANT_ID,
                auth_mode="entra",
            )

        second_admin_id = uuid4()
        second_admin = self.user(
            second_admin_id,
            self.organization_id,
            "admin",
            "second-admin@example.test",
        )
        self.session.add(second_admin)
        self.session.commit()
        second_admin_mapping = ExternalIdentityRecord(
            provider="entra",
            tenant_id=TENANT_ID,
            external_oid=uuid4(),
            user_id=second_admin_id,
            organization_id=self.organization_id,
            active=True,
            created_by_actor_id=self.admin.actor_id,
            updated_by_actor_id=self.admin.actor_id,
        )
        self.session.add(second_admin_mapping)
        self.session.commit()
        disabled = disable_external_identity_mapping(
            self.session,
            self.admin,
            mapping_id=second_admin_mapping.id,
            tenant_id=TENANT_ID,
            auth_mode="entra",
        )
        self.assertFalse(disabled.active)

    def test_last_other_admin_mapping_is_blocked_in_entra_mode(self) -> None:
        second_admin_id = uuid4()
        self.session.add(
            self.user(
                second_admin_id,
                self.organization_id,
                "admin",
                "second-admin@example.test",
            )
        )
        self.session.commit()
        mapping = self.create_mapping(user_id=second_admin_id)
        with self.assertRaises(ExternalIdentityConflictError):
            disable_external_identity_mapping(
                self.session,
                self.admin,
                mapping_id=mapping.id,
                tenant_id=TENANT_ID,
                auth_mode="entra",
            )
        self.session.refresh(mapping)
        self.assertTrue(mapping.active)
        self.assertIn("last_active_admin_mapping", self.audit_events()[-1].detail_json)

        disabled = disable_external_identity_mapping(
            self.session,
            self.admin,
            mapping_id=mapping.id,
            tenant_id=TENANT_ID,
            auth_mode="legacy",
        )
        self.assertFalse(disabled.active)

    def test_admin_http_endpoints_create_inspect_and_disable_mapping(self) -> None:
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        external_oid = uuid4()
        configured = SimpleNamespace(
            entra_tenant_id=str(TENANT_ID),
            auth_mode="legacy",
        )
        with patch(
            "regimpact.auth_api.get_settings",
            return_value=configured,
        ):
            created = asyncio.run(
                self.request(
                    "POST",
                    "/api/v1/auth/external-identities",
                    json={"user_id": str(self.target_id), "external_oid": str(external_oid)},
                )
            )
            self.assertEqual(created.status_code, 201)
            self.assertNotIn("external_oid", created.json())
            self.assertEqual(len(created.json()["external_oid_fingerprint"]), 12)
            mapping_id = created.json()["id"]
            listed = asyncio.run(
                self.request("GET", "/api/v1/auth/external-identities?limit=1&offset=0")
            )
            self.assertEqual(listed.status_code, 200)
            self.assertEqual([item["id"] for item in listed.json()], [mapping_id])
            disabled = asyncio.run(
                self.request(
                    "POST",
                    f"/api/v1/auth/external-identities/{mapping_id}/disable",
                )
            )
            self.assertEqual(disabled.status_code, 200)
            self.assertFalse(disabled.json()["active"])

    def test_management_request_is_strict_and_pagination_is_bounded(self) -> None:
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        configured = SimpleNamespace(
            entra_tenant_id=str(TENANT_ID),
            auth_mode="legacy",
        )
        with patch("regimpact.auth_api.get_settings", return_value=configured):
            unexpected = asyncio.run(
                self.request(
                    "POST",
                    "/api/v1/auth/external-identities",
                    json={
                        "user_id": str(self.target_id),
                        "external_oid": str(uuid4()),
                        "role": "admin",
                    },
                )
            )
            oversized = asyncio.run(
                self.request("GET", "/api/v1/auth/external-identities?limit=101")
            )
        self.assertEqual(unexpected.status_code, 422)
        self.assertEqual(oversized.status_code, 422)

    def test_foreign_mapping_cannot_be_enumerated_or_disabled(self) -> None:
        foreign_mapping = ExternalIdentityRecord(
            provider="entra",
            tenant_id=TENANT_ID,
            external_oid=uuid4(),
            user_id=self.foreign_target_id,
            organization_id=self.other_organization_id,
            active=True,
            created_by_actor_id="user:foreign-admin",
            updated_by_actor_id="user:foreign-admin",
        )
        self.session.add(foreign_mapping)
        self.session.commit()
        listed = list_external_identity_mappings(
            self.session,
            self.admin,
            tenant_id=TENANT_ID,
            limit=50,
            offset=0,
        )
        self.assertEqual(listed, [])
        with self.assertRaises(ExternalIdentityNotFoundError):
            disable_external_identity_mapping(
                self.session,
                self.admin,
                mapping_id=foreign_mapping.id,
                tenant_id=TENANT_ID,
                auth_mode="legacy",
            )

    def test_unauthorized_http_management_is_denied_and_audited(self) -> None:
        self.app.dependency_overrides[get_current_user] = lambda: self.viewer
        external_oid = uuid4()
        with patch(
            "regimpact.auth_api.get_settings",
            return_value=SimpleNamespace(entra_tenant_id=str(TENANT_ID)),
        ):
            denied_create = asyncio.run(
                self.request(
                    "POST",
                    "/api/v1/auth/external-identities",
                    json={
                        "user_id": str(self.other_target_id),
                        "external_oid": str(external_oid),
                    },
                )
            )
        self.assertEqual(denied_create.status_code, 403)
        self.assertEqual(
            self.session.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(
                    AuditEventRecord.event_type
                    == "identity.external_mapping_management_rejected"
                )
            ),
            1,
        )
        event = self.audit_events()[0]
        self.assertNotIn(str(external_oid), event.detail_json)


class ExternalIdentityMigrationTests(TestCase):
    def test_migration_upgrades_and_downgrades_external_identity_schema(self) -> None:
        with TemporaryDirectory() as directory:
            logger_states = {
                name: logger.disabled
                for name, logger in logging.Logger.manager.loggerDict.items()
                if isinstance(logger, logging.Logger)
            }
            database_url = f"sqlite+pysqlite:///{directory}/migration.sqlite"
            with patch.dict(
                os.environ,
                {
                    "REGIMPACT_AUTH_MODE": "legacy_headers",
                    "REGIMPACT_DATABASE_URL": database_url,
                },
            ):
                get_settings.cache_clear()
                try:
                    config = Config("alembic.ini")
                    command.upgrade(config, "head")
                    engine = create_engine(database_url)
                    schema = inspect(engine)
                    self.assertIn("external_identities", schema.get_table_names())
                    unique_names = {
                        constraint["name"]
                        for constraint in schema.get_unique_constraints("external_identities")
                    }
                    self.assertIn(
                        "uq_external_identity_provider_tenant_oid",
                        unique_names,
                    )
                    self.assertIn(
                        "uq_external_identity_provider_tenant_user",
                        unique_names,
                    )
                    check_names = {
                        constraint["name"]
                        for constraint in schema.get_check_constraints("external_identities")
                    }
                    self.assertEqual(
                        check_names,
                        {
                            "ck_external_identity_active_state",
                            "ck_external_identity_provider",
                        },
                    )
                    foreign_keys = schema.get_foreign_keys("external_identities")
                    self.assertTrue(
                        any(
                            key["referred_table"] == "users"
                            and key["constrained_columns"] == ["user_id", "organization_id"]
                            for key in foreign_keys
                        )
                    )
                    engine.dispose()

                    command.downgrade(config, "20260903_0012")
                    downgraded_engine = create_engine(database_url)
                    downgraded_schema = inspect(downgraded_engine)
                    self.assertNotIn(
                        "external_identities",
                        downgraded_schema.get_table_names(),
                    )
                    self.assertNotIn(
                        "ux_users_id_org",
                        {index["name"] for index in downgraded_schema.get_indexes("users")},
                    )
                    downgraded_engine.dispose()
                finally:
                    get_settings.cache_clear()
                    for name, disabled in logger_states.items():
                        logging.getLogger(name).disabled = disabled
