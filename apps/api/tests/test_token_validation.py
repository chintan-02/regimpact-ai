import base64
import hashlib
import hmac
import json
import time
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regimpact.auth import CurrentUser, get_current_user, require_roles
from regimpact.config import Settings
from regimpact.database import Base
from regimpact.db_models import ExternalIdentityRecord, OrganizationRecord, UserRecord
from regimpact.token_validation import (
    HttpJwksProvider,
    JwksError,
    TokenValidationError,
    validate_access_token,
)

TENANT_ID = "11111111-1111-4111-8111-111111111111"
API_AUDIENCE = "22222222-2222-4222-8222-222222222222"
ISSUER = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
JWKS_URL = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
LEGACY_SECRET = "test-legacy-secret-that-is-long-enough"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _json_segment(value: dict[str, object]) -> str:
    return _b64(json.dumps(value, separators=(",", ":")).encode())


def _legacy_token(user_id: UUID | None = None, organization_id: UUID | None = None) -> str:
    now = int(time.time())
    header = _json_segment({"alg": "HS256", "typ": "JWT"})
    payload = _json_segment(
        {
            "sub": str(user_id or uuid4()),
            "org": str(organization_id or uuid4()),
            "role": "analyst",
            "iat": now,
            "exp": now + 600,
            "iss": "regimpact-api",
            "aud": "regimpact-web",
        }
    )
    unsigned = f"{header}.{payload}"
    signature = hmac.new(LEGACY_SECRET.encode(), unsigned.encode(), hashlib.sha256).digest()
    return f"{unsigned}.{_b64(signature)}"


def _settings(mode: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "auth_mode": mode,
        "jwt_secret": LEGACY_SECRET,
        "entra_tenant_id": TENANT_ID,
        "entra_issuer": ISSUER,
        "entra_api_audience": API_AUDIENCE,
        "entra_jwks_url": JWKS_URL,
        "entra_clock_skew_seconds": 0,
        "entra_jwks_timeout_seconds": 1,
        "entra_jwks_cache_seconds": 60,
    }
    values.update(overrides)
    return Settings(**values)


def _integer_b64(value: int) -> str:
    return _b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def _jwk(public_key: rsa.RSAPublicKey, key_id: str) -> dict[str, str]:
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": key_id,
        "n": _integer_b64(numbers.n),
        "e": _integer_b64(numbers.e),
    }


class _StaticKeyProvider:
    def __init__(self, key_id: str, public_key: rsa.RSAPublicKey) -> None:
        self.key_id = key_id
        self.public_key = public_key
        self.calls = 0

    def get_signing_key(self, key_id: str) -> rsa.RSAPublicKey:
        self.calls += 1
        if key_id != self.key_id:
            raise JwksError("unknown_key_id")
        return self.public_key


class DualTokenValidatorTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_key = cls.private_key.public_key()
        cls.key_id = "entra-signing-key"

    def entra_token(self, **overrides: object) -> str:
        now = int(time.time())
        claims: dict[str, object] = {
            "iss": ISSUER,
            "aud": API_AUDIENCE,
            "tid": TENANT_ID,
            "oid": str(uuid4()),
            "sub": "pairwise-user-subject",
            "azp": "33333333-3333-4333-8333-333333333333",
            "idtyp": "user",
            "ver": "2.0",
            "uti": "safe-token-id",
            "iat": now,
            "nbf": now - 1,
            "exp": now + 600,
            "scp": "evidence:read reviews:read",
        }
        claims.update(overrides)
        return jwt.encode(
            claims,
            self.private_key,
            algorithm="RS256",
            headers={"kid": self.key_id, "typ": "JWT"},
        )

    def provider(self) -> _StaticKeyProvider:
        return _StaticKeyProvider(self.key_id, self.public_key)

    def assert_rejected(
        self,
        token: str,
        *,
        mode: str = "dual",
        category: str | None = None,
    ) -> TokenValidationError:
        with self.assertRaises(TokenValidationError) as caught:
            validate_access_token(token, _settings(mode), self.provider())
        if category is not None:
            self.assertEqual(caught.exception.category, category)
        return caught.exception

    def test_valid_legacy_token_in_legacy_and_dual_modes(self) -> None:
        token = _legacy_token()
        for mode in ("legacy", "dual"):
            with self.subTest(mode=mode):
                validated = validate_access_token(token, _settings(mode), self.provider())
                self.assertEqual(validated.family, "legacy")
                self.assertEqual(validated.claimed_role, "analyst")

    def test_token_families_are_explicitly_allowed_by_mode(self) -> None:
        legacy = _legacy_token()
        entra = self.entra_token()
        self.assert_rejected(legacy, mode="entra", category="token_family_not_allowed")
        self.assert_rejected(entra, mode="legacy", category="token_family_not_allowed")
        for mode in ("dual", "entra"):
            with self.subTest(mode=mode):
                self.assertEqual(
                    validate_access_token(entra, _settings(mode), self.provider()).family,
                    "entra",
                )

    def test_entra_rejects_wrong_issuer_audience_and_tenant(self) -> None:
        self.assert_rejected(
            self.entra_token(iss="https://issuer.invalid/v2.0"), category="invalid_issuer"
        )
        self.assert_rejected(self.entra_token(aud=str(uuid4())), category="invalid_audience")
        self.assert_rejected(self.entra_token(tid=str(uuid4())), category="wrong_tenant")

    def test_entra_rejects_expired_and_not_yet_valid_tokens(self) -> None:
        now = int(time.time())
        self.assert_rejected(
            self.entra_token(iat=now - 20, nbf=now - 20, exp=now - 1), category="expired"
        )
        self.assert_rejected(
            self.entra_token(iat=now, nbf=now + 60, exp=now + 600),
            category="not_yet_valid",
        )

    def test_default_and_configured_maximum_token_lifetimes(self) -> None:
        now = int(time.time())
        default_settings = _settings("entra")
        self.assertEqual(default_settings.entra_max_token_lifetime_seconds, 5_400)
        accepted = validate_access_token(
            self.entra_token(iat=now, nbf=now, exp=now + 5_400),
            default_settings,
            self.provider(),
        )
        self.assertEqual(accepted.family, "entra")
        with self.assertRaises(TokenValidationError) as default_excessive:
            validate_access_token(
                self.entra_token(iat=now, nbf=now, exp=now + 5_401),
                default_settings,
                self.provider(),
            )
        self.assertEqual(default_excessive.exception.category, "invalid_token_lifetime")

        configured_settings = _settings("entra", entra_max_token_lifetime_seconds=600)
        validate_access_token(
            self.entra_token(iat=now, nbf=now, exp=now + 600),
            configured_settings,
            self.provider(),
        )
        with self.assertRaises(TokenValidationError) as configured_excessive:
            validate_access_token(
                self.entra_token(iat=now, nbf=now, exp=now + 601),
                configured_settings,
                self.provider(),
            )
        self.assertEqual(configured_excessive.exception.category, "invalid_token_lifetime")

    def test_entra_requires_subject_and_object_identity(self) -> None:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": API_AUDIENCE,
            "tid": TENANT_ID,
            "sub": "subject",
            "azp": str(uuid4()),
            "idtyp": "user",
            "ver": "2.0",
            "uti": "token-id",
            "iat": now,
            "nbf": now - 1,
            "exp": now + 600,
        }
        token = jwt.encode(
            claims,
            self.private_key,
            algorithm="RS256",
            headers={"kid": self.key_id, "typ": "JWT"},
        )
        self.assert_rejected(token, category="missing_required_claim")

    def test_entra_rejects_malformed_object_identity_before_lookup(self) -> None:
        self.assert_rejected(
            self.entra_token(oid="not-a-uuid"),
            category="invalid_identity_claim",
        )

    def test_unsigned_and_unsupported_algorithm_tokens_are_rejected(self) -> None:
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": API_AUDIENCE, "exp": now + 600}
        unsigned = f"{_json_segment({'alg': 'none', 'typ': 'JWT'})}.{_json_segment(claims)}."
        self.assert_rejected(unsigned, category="unsigned_token")
        unsupported = (
            f"{_json_segment({'alg': 'HS512', 'typ': 'JWT'})}.{_json_segment(claims)}.signature"
        )
        self.assert_rejected(unsupported, category="unsupported_algorithm")

    def test_hs_rs_algorithm_confusion_and_ambiguous_tokens_are_rejected(self) -> None:
        now = int(time.time())
        entra_claims = {
            "iss": ISSUER,
            "aud": API_AUDIENCE,
            "exp": now + 600,
        }
        header = _json_segment({"alg": "HS256", "typ": "JWT"})
        payload = _json_segment(entra_claims)
        unsigned = f"{header}.{payload}"
        confused = f"{unsigned}.{_b64(hmac.new(b'public-key-bytes', unsigned.encode(), hashlib.sha256).digest())}"
        self.assert_rejected(confused, category="algorithm_confusion")

        legacy_claims = {
            "iss": "regimpact-api",
            "aud": "regimpact-web",
            "exp": now + 600,
        }
        rs_legacy = jwt.encode(
            legacy_claims,
            self.private_key,
            algorithm="RS256",
            headers={"kid": self.key_id, "typ": "JWT"},
        )
        self.assert_rejected(rs_legacy, category="algorithm_confusion")

        ambiguous_payload = _json_segment({"iss": "regimpact-api", "aud": API_AUDIENCE})
        ambiguous_unsigned = f"{header}.{ambiguous_payload}"
        ambiguous = f"{ambiguous_unsigned}.{_b64(hmac.new(LEGACY_SECRET.encode(), ambiguous_unsigned.encode(), hashlib.sha256).digest())}"
        self.assert_rejected(ambiguous, category="ambiguous_token")

    def test_failed_entra_token_does_not_fall_back_to_legacy(self) -> None:
        attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = jwt.encode(
            jwt.decode(self.entra_token(), options={"verify_signature": False}),
            attacker_key,
            algorithm="RS256",
            headers={"kid": self.key_id, "typ": "JWT"},
        )
        error = self.assert_rejected(token, category="invalid_signature")
        self.assertEqual(error.family, "entra")

    def test_delegated_scopes_and_application_roles_remain_distinct(self) -> None:
        validated = validate_access_token(
            self.entra_token(
                scp="evidence:read reviews:read",
                roles=["Evidence.Read.All", "Reviews.Read.All"],
            ),
            _settings("dual"),
            self.provider(),
        )
        self.assertEqual(validated.delegated_scopes, {"evidence:read", "reviews:read"})
        self.assertEqual(
            validated.application_roles,
            {"Evidence.Read.All", "Reviews.Read.All"},
        )

    def test_token_roles_do_not_grant_existing_rbac_permissions(self) -> None:
        viewer = CurrentUser(
            id=uuid4(),
            organization_id=uuid4(),
            organization_name="Tenant",
            email="viewer@example.test",
            display_name="Viewer",
            role="viewer",
            token_family="entra",
            application_roles=frozenset({"AdminUser", "Evidence.Read.All"}),
        )
        with self.assertRaises(HTTPException) as caught:
            require_roles("admin")(viewer)
        self.assertEqual(caught.exception.status_code, 403)

    def test_unknown_key_id_refreshes_once(self) -> None:
        old_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
        documents = [
            {"keys": [_jwk(old_key, "old-key")]},
            {"keys": [_jwk(self.public_key, self.key_id)]},
        ]
        calls = 0

        def fetch() -> object:
            nonlocal calls
            document = documents[min(calls, len(documents) - 1)]
            calls += 1
            return document

        provider = HttpJwksProvider(
            JWKS_URL,
            timeout_seconds=1,
            cache_seconds=60,
            fetch_json=fetch,
        )
        validated = validate_access_token(self.entra_token(), _settings("entra"), provider)
        self.assertEqual(validated.family, "entra")
        self.assertEqual(calls, 2)

    def test_jwks_cache_expires_at_its_configured_boundary(self) -> None:
        calls = 0
        now = 100.0

        def fetch() -> object:
            nonlocal calls
            calls += 1
            return {"keys": [_jwk(self.public_key, self.key_id)]}

        provider = HttpJwksProvider(
            JWKS_URL,
            timeout_seconds=1,
            cache_seconds=60,
            fetch_json=fetch,
            clock=lambda: now,
        )
        provider.get_signing_key(self.key_id)
        provider.get_signing_key(self.key_id)
        self.assertEqual(calls, 1)
        now = 160.0
        provider.get_signing_key(self.key_id)
        self.assertEqual(calls, 2)

    def test_unavailable_and_malformed_jwks_fail_closed(self) -> None:
        def unavailable() -> object:
            raise RuntimeError("network unavailable")

        providers = (
            HttpJwksProvider(
                JWKS_URL,
                timeout_seconds=1,
                cache_seconds=60,
                fetch_json=unavailable,
            ),
            HttpJwksProvider(
                JWKS_URL,
                timeout_seconds=1,
                cache_seconds=60,
                fetch_json=lambda: {"keys": "not-a-list"},
            ),
        )
        expected = ("jwks_unavailable", "jwks_malformed")
        for provider, category in zip(providers, expected, strict=True):
            with self.subTest(category=category):
                with self.assertRaises(TokenValidationError) as caught:
                    validate_access_token(self.entra_token(), _settings("entra"), provider)
                self.assertEqual(caught.exception.category, category)


class AuthenticationConfigurationTests(TestCase):
    def test_dual_and_entra_require_complete_configuration(self) -> None:
        for mode in ("dual", "entra"):
            with self.subTest(mode=mode), self.assertRaisesRegex(
                ValueError, "requires REGIMPACT_ENTRA_TENANT_ID"
            ):
                Settings(environment="test", auth_mode=mode, jwt_secret=LEGACY_SECRET)

    def test_entra_configuration_rejects_mismatched_issuer(self) -> None:
        with self.assertRaisesRegex(ValueError, "tenant-specific Entra v2 issuer"):
            _settings("entra", entra_issuer="https://issuer.invalid/v2.0")

    def test_entra_configuration_bounds_skew_lifetime_timeout_and_cache(self) -> None:
        invalid_values = (
            {"entra_clock_skew_seconds": 301},
            {"entra_max_token_lifetime_seconds": 599},
            {"entra_max_token_lifetime_seconds": 86_401},
            {"entra_jwks_timeout_seconds": 31},
            {"entra_jwks_cache_seconds": 59},
            {"entra_jwks_cache_seconds": 21_601},
        )
        for values in invalid_values:
            with self.subTest(values=values), self.assertRaises(ValueError):
                _settings("entra", **values)

    def test_production_jwks_url_is_tenant_specific_and_ssrf_safe(self) -> None:
        wrong_tenant = "99999999-9999-4999-8999-999999999999"
        unsafe_urls = (
            f"http://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys",
            f"https://example.test/{TENANT_ID}/discovery/v2.0/keys",
            f"https://login.microsoftonline.com.example.test/{TENANT_ID}/discovery/v2.0/keys",
            f"https://user:password@login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys",
            f"https://login.microsoftonline.com:443/{TENANT_ID}/discovery/v2.0/keys",
            f"https://login.microsoftonline.com/{wrong_tenant}/discovery/v2.0/keys",
            "https://login.microsoftonline.com/common/discovery/v2.0/keys",
            f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys?source=other",
            f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys#fragment",
        )
        for url in unsafe_urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                _settings("entra", environment="production", entra_jwks_url=url)

    def test_test_environment_preserves_injected_local_jwks_support(self) -> None:
        settings = _settings(
            "entra",
            environment="test",
            entra_jwks_url="http://127.0.0.1:8765/test-keys",
        )
        self.assertEqual(settings.entra_jwks_url, "http://127.0.0.1:8765/test-keys")

    def test_invalid_identifiers_and_missing_production_legacy_secret_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be UUIDs"):
            _settings("entra", entra_tenant_id="not-a-tenant-id")
        with self.assertRaisesRegex(ValueError, "must be UUIDs"):
            _settings("entra", entra_api_audience="not-an-audience")
        with self.assertRaisesRegex(ValueError, "production requires REGIMPACT_JWT_SECRET"):
            Settings(environment="production", auth_mode="legacy", jwt_secret="")

    def test_production_entra_mode_does_not_require_legacy_secret(self) -> None:
        settings = _settings("entra", environment="production", jwt_secret="")
        self.assertEqual(settings.jwt_secret, "")


class EntraPrincipalMappingTests(TestCase):
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
        self.external_oid = uuid4()
        with self.session.begin():
            self.session.add(
                OrganizationRecord(id=self.organization_id, name="Mapped tenant")
            )
            self.session.add(
                UserRecord(
                    id=self.user_id,
                    organization_id=self.organization_id,
                    email="mapped@example.test",
                    display_name="Mapped Viewer",
                    role="viewer",
                    password_hash="not-used-for-entra-validation",
                )
            )
            self.session.add(
                ExternalIdentityRecord(
                    provider="entra",
                    tenant_id=UUID(TENANT_ID),
                    external_oid=self.external_oid,
                    user_id=self.user_id,
                    organization_id=self.organization_id,
                    active=True,
                    created_by_actor_id="user:test-admin",
                    updated_by_actor_id="user:test-admin",
                )
            )
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.key_id = "mapping-test-key"
        self.provider = _StaticKeyProvider(self.key_id, self.private_key.public_key())
        self.settings = _settings("entra")

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def token(
        self,
        object_id: str,
        *,
        private_key: rsa.RSAPrivateKey | None = None,
        subject: str = "mapped-subject",
    ) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "iss": ISSUER,
                "aud": API_AUDIENCE,
                "tid": TENANT_ID,
                "oid": object_id,
                "sub": subject,
                "azp": str(uuid4()),
                "idtyp": "user",
                "ver": "2.0",
                "uti": "mapping-token-id",
                "iat": now,
                "nbf": now - 1,
                "exp": now + 600,
                "scp": "evidence:read",
                "roles": ["AdminUser", "Evidence.Read.All"],
            },
            private_key or self.private_key,
            algorithm="RS256",
            headers={"kid": self.key_id, "typ": "JWT"},
        )

    def authenticate(self, token: str) -> CurrentUser:
        with (
            patch("regimpact.auth.get_settings", return_value=self.settings),
            patch("regimpact.auth.get_jwks_provider", return_value=self.provider),
        ):
            return get_current_user(self.session, f"Bearer {token}", None, None)

    def test_entra_claims_map_to_existing_user_without_granting_token_roles(self) -> None:
        current = self.authenticate(self.token(str(self.external_oid)))
        self.assertEqual(current.id, self.user_id)
        self.assertEqual(current.organization_id, self.organization_id)
        self.assertEqual(current.role, "viewer")
        self.assertEqual(current.delegated_scopes, {"evidence:read"})
        self.assertEqual(
            current.application_roles,
            {"AdminUser", "Evidence.Read.All"},
        )
        with self.assertRaises(HTTPException) as caught:
            require_roles("admin")(current)
        self.assertEqual(caught.exception.status_code, 403)

    def test_unknown_oid_fails_closed_without_auto_provisioning(self) -> None:
        user_count = self.session.scalar(select(func.count()).select_from(UserRecord))
        unknown_oid = uuid4()
        with self.assertRaises(HTTPException) as caught:
            self.authenticate(self.token(str(unknown_oid)))
        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(UserRecord)),
            user_count,
        )
        self.assertIsNone(self.session.get(UserRecord, unknown_oid))

    def test_direct_oid_to_user_id_fallback_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self.authenticate(self.token(str(self.user_id)))
        self.assertEqual(caught.exception.status_code, 401)

    def test_disabled_mapping_and_inactive_local_user_are_rejected(self) -> None:
        mapping = self.session.scalar(
            select(ExternalIdentityRecord).where(
                ExternalIdentityRecord.external_oid == self.external_oid
            )
        )
        assert mapping is not None
        mapping.active = False
        mapping.disabled_at = mapping.updated_at
        self.session.commit()
        with self.assertRaises(HTTPException) as disabled:
            self.authenticate(self.token(str(self.external_oid)))
        self.assertEqual(disabled.exception.status_code, 401)

        mapping.active = True
        mapping.disabled_at = None
        user = self.session.get(UserRecord, self.user_id)
        assert user is not None
        user.active = False
        self.session.commit()
        with self.assertRaises(HTTPException) as inactive:
            self.authenticate(self.token(str(self.external_oid)))
        self.assertEqual(inactive.exception.status_code, 401)

    def test_entra_mode_rejects_legacy_header_identity(self) -> None:
        with (
            patch("regimpact.auth.get_settings", return_value=self.settings),
            self.assertRaises(HTTPException) as caught,
        ):
            get_current_user(
                self.session,
                None,
                self.organization_id,
                "spoofed-admin",
            )
        self.assertEqual(caught.exception.status_code, 401)

    def test_failed_entra_token_log_excludes_token_and_identity_claims(self) -> None:
        attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = "sensitive-pairwise-subject"
        token = self.token(str(self.external_oid), private_key=attacker_key, subject=subject)
        with (
            self.assertLogs("regimpact.auth", level="WARNING") as logs,
            self.assertRaises(HTTPException),
        ):
            self.authenticate(token)
        logged = "\n".join(logs.output)
        self.assertNotIn(token, logged)
        self.assertNotIn(str(self.user_id), logged)
        self.assertNotIn(subject, logged)
        self.assertEqual(logs.records[0].auth_failure_category, "invalid_signature")
        self.assertEqual(logs.records[0].token_family, "entra")
