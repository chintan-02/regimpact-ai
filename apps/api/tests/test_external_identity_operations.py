import io
from contextlib import redirect_stderr, redirect_stdout
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from regimpact.config import Settings
from regimpact.database import Base
from regimpact.db_models import (
    AuditEventRecord,
    ExternalIdentityRecord,
    OrganizationRecord,
    UserRecord,
)
from regimpact.external_identity_cli import main
from regimpact.external_identity_operations import (
    BOOTSTRAP_ACKNOWLEDGEMENT,
    BOOTSTRAP_ROLLBACK_ACKNOWLEDGEMENT,
    EXTERNAL_IDENTITY_REVISION,
    ROLLBACK_ACKNOWLEDGEMENT,
    ExternalIdentityOperationError,
    bootstrap_first_admin_mapping,
    rollback_bootstrap_mapping,
    validate_cutover_readiness,
)

TENANT_ID = "11111111-1111-4111-8111-111111111111"
API_AUDIENCE = "22222222-2222-4222-8222-222222222222"


def settings(mode: str = "dual") -> Settings:
    return Settings(
        environment="test",
        auth_mode=mode,
        jwt_secret="test-legacy-secret-that-is-long-enough",
        entra_tenant_id=TENANT_ID,
        entra_issuer=f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
        entra_api_audience=API_AUDIENCE,
        entra_jwks_url=(
            f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
        ),
    )


class ExternalIdentityOperatorTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.organization_id = uuid4()
        self.admin_id = uuid4()
        self.viewer_id = uuid4()
        with self.session.begin():
            self.session.add(OrganizationRecord(id=self.organization_id, name="Northstar"))
            self.session.add_all(
                [
                    UserRecord(
                        id=self.admin_id,
                        organization_id=self.organization_id,
                        email="admin@example.test",
                        display_name="Admin",
                        role="admin",
                        password_hash="not-used",
                    ),
                    UserRecord(
                        id=self.viewer_id,
                        organization_id=self.organization_id,
                        email="viewer@example.test",
                        display_name="Viewer",
                        role="viewer",
                        password_hash="not-used",
                    ),
                ]
            )
            self.session.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            )
            self.session.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": EXTERNAL_IDENTITY_REVISION},
            )

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def bootstrap(self, oid=None):  # type: ignore[no-untyped-def]
        return bootstrap_first_admin_mapping(
            self.session,
            settings(),
            user_id=self.admin_id,
            external_oid=oid or uuid4(),
            acknowledgement=BOOTSTRAP_ACKNOWLEDGEMENT,
        )

    def test_bootstrap_creates_only_first_active_admin_mapping_and_safe_audit(self) -> None:
        oid = uuid4()
        user_count = self.session.scalar(select(func.count()).select_from(UserRecord))
        mapping = self.bootstrap(oid)
        self.assertEqual(mapping.user_id, self.admin_id)
        self.assertEqual(str(mapping.tenant_id), TENANT_ID)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(UserRecord)),
            user_count,
        )
        event = self.session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.event_type == "identity.external_mapping_bootstrapped"
            )
        )
        assert event is not None
        self.assertNotIn(str(oid), event.detail_json)
        with self.assertRaises(ExternalIdentityOperationError) as repeated:
            self.bootstrap(uuid4())
        self.assertEqual(repeated.exception.category, "bootstrap_not_first_mapping")
        self.assertIsNotNone(
            self.session.scalar(
                select(AuditEventRecord).where(
                    AuditEventRecord.event_type
                    == "identity.external_mapping_bootstrap_rejected"
                )
            )
        )

    def test_bootstrap_requires_acknowledgement_and_active_local_admin(self) -> None:
        with self.assertRaises(ExternalIdentityOperationError) as acknowledgement:
            bootstrap_first_admin_mapping(
                self.session,
                settings(),
                user_id=self.admin_id,
                external_oid=uuid4(),
                acknowledgement="yes",
            )
        self.assertEqual(
            acknowledgement.exception.category,
            "bootstrap_acknowledgement_required",
        )
        for user_id in (self.viewer_id, uuid4()):
            with self.subTest(user_id=user_id), self.assertRaises(
                ExternalIdentityOperationError
            ) as invalid_admin:
                bootstrap_first_admin_mapping(
                    self.session,
                    settings(),
                    user_id=user_id,
                    external_oid=uuid4(),
                    acknowledgement=BOOTSTRAP_ACKNOWLEDGEMENT,
                )
            self.assertEqual(invalid_admin.exception.category, "active_local_admin_required")

        with self.assertRaises(ExternalIdentityOperationError) as wrong_mode:
            bootstrap_first_admin_mapping(
                self.session,
                settings("entra"),
                user_id=self.admin_id,
                external_oid=uuid4(),
                acknowledgement=BOOTSTRAP_ACKNOWLEDGEMENT,
            )
        self.assertEqual(wrong_mode.exception.category, "dual_mode_required_for_bootstrap")

    def test_cutover_preflight_is_read_only_and_requires_admin_mapping(self) -> None:
        before_events = self.session.scalar(select(func.count()).select_from(AuditEventRecord))
        with self.assertRaises(ExternalIdentityOperationError) as missing:
            validate_cutover_readiness(
                self.session,
                settings(),
                rollback_acknowledgement=ROLLBACK_ACKNOWLEDGEMENT,
            )
        self.assertEqual(missing.exception.category, "active_admin_mapping_required")
        mapping = self.bootstrap()
        before_mappings = self.session.scalar(
            select(func.count()).select_from(ExternalIdentityRecord)
        )
        result = validate_cutover_readiness(
            self.session,
            settings(),
            rollback_acknowledgement=ROLLBACK_ACKNOWLEDGEMENT,
        )
        self.assertEqual(result.migration_revision, EXTERNAL_IDENTITY_REVISION)
        self.assertEqual(result.active_admin_mapping_count, 1)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(ExternalIdentityRecord)),
            before_mappings,
        )
        self.assertEqual(mapping.user_id, self.admin_id)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(AuditEventRecord)),
            before_events + 1,
        )

    def test_bootstrap_rollback_is_narrow_audited_and_not_available_in_entra(self) -> None:
        mapping = self.bootstrap()
        with self.assertRaises(ExternalIdentityOperationError) as wrong_mode:
            rollback_bootstrap_mapping(
                self.session,
                settings("entra"),
                mapping_id=mapping.id,
                acknowledgement=BOOTSTRAP_ROLLBACK_ACKNOWLEDGEMENT,
            )
        self.assertEqual(
            wrong_mode.exception.category,
            "legacy_or_dual_mode_required_for_rollback",
        )
        rolled_back = rollback_bootstrap_mapping(
            self.session,
            settings(),
            mapping_id=mapping.id,
            acknowledgement=BOOTSTRAP_ROLLBACK_ACKNOWLEDGEMENT,
        )
        self.assertFalse(rolled_back.active)
        self.assertIsNotNone(rolled_back.disabled_at)
        self.assertEqual(
            self.audit_events_of_type("identity.external_mapping_bootstrap_rolled_back"),
            1,
        )
        with self.assertRaises(ExternalIdentityOperationError) as repeated:
            rollback_bootstrap_mapping(
                self.session,
                settings(),
                mapping_id=mapping.id,
                acknowledgement=BOOTSTRAP_ROLLBACK_ACKNOWLEDGEMENT,
            )
        self.assertEqual(repeated.exception.category, "bootstrap_mapping_already_disabled")

    def test_bootstrap_rollback_rejects_non_bootstrap_mapping(self) -> None:
        mapping = ExternalIdentityRecord(
            provider="entra",
            tenant_id=UUID(TENANT_ID),
            external_oid=uuid4(),
            user_id=self.admin_id,
            organization_id=self.organization_id,
            active=True,
            created_by_actor_id="user:another-admin",
            updated_by_actor_id="user:another-admin",
        )
        self.session.add(mapping)
        self.session.commit()
        with self.assertRaises(ExternalIdentityOperationError) as caught:
            rollback_bootstrap_mapping(
                self.session,
                settings(),
                mapping_id=mapping.id,
                acknowledgement=BOOTSTRAP_ROLLBACK_ACKNOWLEDGEMENT,
            )
        self.assertEqual(caught.exception.category, "bootstrap_mapping_not_found")
        self.session.refresh(mapping)
        self.assertTrue(mapping.active)

    def test_preflight_rejects_missing_ack_mode_revision_and_wrong_tenant(self) -> None:
        mapping = self.bootstrap()
        cases = (
            (settings(), "wrong acknowledgement", "legacy_rollback_acknowledgement_required"),
            (settings("legacy"), ROLLBACK_ACKNOWLEDGEMENT, "dual_or_entra_mode_required"),
        )
        for configured, acknowledgement, category in cases:
            with self.subTest(category=category), self.assertRaises(
                ExternalIdentityOperationError
            ) as caught:
                validate_cutover_readiness(
                    self.session,
                    configured,
                    rollback_acknowledgement=acknowledgement,
                )
            self.assertEqual(caught.exception.category, category)

        mapping.tenant_id = uuid4()
        self.session.commit()
        with self.assertRaises(ExternalIdentityOperationError) as wrong_tenant:
            validate_cutover_readiness(
                self.session,
                settings(),
                rollback_acknowledgement=ROLLBACK_ACKNOWLEDGEMENT,
            )
        self.assertEqual(
            wrong_tenant.exception.category,
            "active_mapping_for_unconfigured_tenant",
        )
        mapping.tenant_id = UUID(TENANT_ID)
        self.session.commit()

        self.session.execute(text("UPDATE alembic_version SET version_num = 'old_revision'"))
        self.session.commit()
        with self.assertRaises(ExternalIdentityOperationError) as migration:
            validate_cutover_readiness(
                self.session,
                settings(),
                rollback_acknowledgement=ROLLBACK_ACKNOWLEDGEMENT,
            )
        self.assertEqual(
            migration.exception.category,
            "external_identity_migration_not_applied",
        )

    def test_cli_output_never_prints_external_oid(self) -> None:
        oid = uuid4()
        factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        output = io.StringIO()
        errors = io.StringIO()
        with (
            patch("regimpact.external_identity_cli.get_settings", return_value=settings()),
            patch("regimpact.external_identity_cli.SessionFactory", factory),
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            result = main(
                [
                    "bootstrap",
                    "--user-id",
                    str(self.admin_id),
                    "--entra-oid",
                    str(oid),
                    "--acknowledge",
                    BOOTSTRAP_ACKNOWLEDGEMENT,
                ]
            )
        self.assertEqual(result, 0)
        self.assertNotIn(str(oid), output.getvalue())
        self.assertEqual(errors.getvalue(), "")

        invalid_oid = "sensitive-invalid-oid-value"
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = main(
                [
                    "bootstrap",
                    "--user-id",
                    str(self.admin_id),
                    "--entra-oid",
                    invalid_oid,
                    "--acknowledge",
                    BOOTSTRAP_ACKNOWLEDGEMENT,
                ]
            )
        self.assertEqual(result, 2)
        self.assertNotIn(invalid_oid, output.getvalue() + errors.getvalue())

    def test_cli_preflight_is_read_only(self) -> None:
        self.bootstrap()
        before = self.session.scalar(select(func.count()).select_from(AuditEventRecord))
        factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        output = io.StringIO()
        errors = io.StringIO()
        with (
            patch("regimpact.external_identity_cli.get_settings", return_value=settings()),
            patch("regimpact.external_identity_cli.SessionFactory", factory),
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            result = main(
                [
                    "preflight",
                    "--acknowledge-legacy-rollback",
                    ROLLBACK_ACKNOWLEDGEMENT,
                ]
            )
        self.assertEqual(result, 0)
        self.assertIn("Cutover preflight passed", output.getvalue())
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(AuditEventRecord)),
            before,
        )

    def audit_events_of_type(self, event_type: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(AuditEventRecord.event_type == event_type)
            )
            or 0
        )
