"""Fail-closed legacy and Microsoft Entra access-token validation."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, Protocol
from uuid import UUID

import httpx
import jwt
from jwt import PyJWK

from .config import Settings

TokenFamily = Literal["legacy", "entra"]
MAX_TOKEN_BYTES = 16_384
MAX_JWKS_BYTES = 1_048_576
MAX_JWKS_KEYS = 32


class TokenValidationError(Exception):
    """A safe token-rejection category suitable for structured security logs."""

    def __init__(self, category: str, family: TokenFamily | None = None) -> None:
        super().__init__(category)
        self.category = category
        self.family = family


class JwksError(Exception):
    """A safe JWKS failure category."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class SigningKeyProvider(Protocol):
    def get_signing_key(self, key_id: str) -> Any:
        """Return the public key for a trusted key ID or raise ``JwksError``."""


@dataclass(frozen=True)
class ValidatedAccessToken:
    family: TokenFamily
    user_id: UUID | None
    external_oid: UUID | None
    organization_id: UUID | None
    claimed_role: str | None
    tenant_id: str | None
    subject_id: str
    object_id: str | None
    client_id: str | None
    delegated_scopes: frozenset[str]
    application_roles: frozenset[str]


class _DuplicateJsonKeyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError
        result[key] = value
    return result


def _decode_json_segment(value: str) -> dict[str, object]:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        decoded = json.loads(raw, object_pairs_hook=_unique_object)
    except (
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
        _DuplicateJsonKeyError,
        ValueError,
    ) as exc:
        raise TokenValidationError("malformed_token") from exc
    if not isinstance(decoded, dict):
        raise TokenValidationError("malformed_token")
    return decoded


def _token_parts(token: str) -> tuple[str, str, str, dict[str, object], dict[str, object]]:
    if not token or len(token.encode()) > MAX_TOKEN_BYTES:
        raise TokenValidationError("malformed_token")
    parts = token.split(".")
    if len(parts) != 3 or not parts[0] or not parts[1]:
        raise TokenValidationError("malformed_token")
    header_part, payload_part, signature_part = parts
    return (
        header_part,
        payload_part,
        signature_part,
        _decode_json_segment(header_part),
        _decode_json_segment(payload_part),
    )


def classify_token(token: str, settings: Settings) -> TokenFamily:
    """Classify once from strict structure; validation never crosses token families."""

    _, _, _, header, claims = _token_parts(token)
    algorithm = header.get("alg")
    if header.get("typ") != "JWT" or not isinstance(algorithm, str):
        raise TokenValidationError("malformed_token")
    if algorithm == "none":
        raise TokenValidationError("unsigned_token")

    issuer = claims.get("iss")
    audience = claims.get("aud")
    has_legacy_marker = issuer == "regimpact-api" or audience == "regimpact-web"
    has_entra_marker = issuer == settings.entra_issuer or audience == settings.entra_api_audience
    if has_legacy_marker and has_entra_marker:
        raise TokenValidationError("ambiguous_token")

    if algorithm == "HS256":
        if has_entra_marker:
            raise TokenValidationError("algorithm_confusion", "entra")
        return "legacy"
    if algorithm == "RS256":
        if has_legacy_marker:
            raise TokenValidationError("algorithm_confusion", "legacy")
        return "entra"
    raise TokenValidationError("unsupported_algorithm")


def _validate_legacy(token: str, settings: Settings) -> ValidatedAccessToken:
    try:
        header_part, payload_part, signature_part, header, claims = _token_parts(token)
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise TokenValidationError("legacy_invalid", "legacy")
        expected = hmac.new(
            settings.jwt_secret.encode(),
            f"{header_part}.{payload_part}".encode(),
            hashlib.sha256,
        ).digest()
        padded_signature = signature_part + "=" * (-len(signature_part) % 4)
        actual = base64.b64decode(padded_signature, altchars=b"-_", validate=True)
        if not hmac.compare_digest(expected, actual):
            raise TokenValidationError("invalid_signature", "legacy")
        if claims.get("iss") != "regimpact-api" or claims.get("aud") != "regimpact-web":
            raise TokenValidationError("legacy_invalid", "legacy")
        expires_at = claims["exp"]
        if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float, str)):
            raise TokenValidationError("legacy_invalid", "legacy")
        if int(expires_at) <= int(time.time()):
            raise TokenValidationError("expired", "legacy")
        user_id = UUID(str(claims["sub"]))
        organization_id = UUID(str(claims["org"]))
        role = claims.get("role")
        if not isinstance(role, str):
            raise TokenValidationError("missing_identity_claim", "legacy")
    except TokenValidationError:
        raise
    except (ValueError, TypeError, KeyError, binascii.Error) as exc:
        raise TokenValidationError("legacy_invalid", "legacy") from exc
    return ValidatedAccessToken(
        family="legacy",
        user_id=user_id,
        external_oid=None,
        organization_id=organization_id,
        claimed_role=role,
        tenant_id=None,
        subject_id=str(user_id),
        object_id=None,
        client_id=None,
        delegated_scopes=frozenset(),
        application_roles=frozenset(),
    )


def _string_set(value: object, *, claim: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if claim == "scp":
        if not isinstance(value, str):
            raise TokenValidationError("invalid_claim", "entra")
        values = value.split()
    else:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise TokenValidationError("invalid_claim", "entra")
        values = value
    if any(not item or len(item) > 120 for item in values):
        raise TokenValidationError("invalid_claim", "entra")
    return frozenset(values)


def _validate_entra(
    token: str,
    settings: Settings,
    key_provider: SigningKeyProvider,
) -> ValidatedAccessToken:
    _, _, _, header, _ = _token_parts(token)
    key_id = header.get("kid")
    if header.get("alg") != "RS256" or header.get("typ") != "JWT":
        raise TokenValidationError("unsupported_algorithm", "entra")
    if not isinstance(key_id, str) or not key_id or len(key_id) > 256:
        raise TokenValidationError("missing_key_id", "entra")
    try:
        signing_key = key_provider.get_signing_key(key_id)
    except JwksError as exc:
        raise TokenValidationError(exc.category, "entra") from exc

    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.entra_api_audience,
            issuer=settings.entra_issuer,
            leeway=settings.entra_clock_skew_seconds,
            options={
                "require": [
                    "aud",
                    "azp",
                    "exp",
                    "iat",
                    "idtyp",
                    "iss",
                    "nbf",
                    "oid",
                    "sub",
                    "tid",
                    "uti",
                    "ver",
                ],
                "strict_aud": True,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenValidationError("expired", "entra") from exc
    except jwt.ImmatureSignatureError as exc:
        raise TokenValidationError("not_yet_valid", "entra") from exc
    except jwt.InvalidIssuerError as exc:
        raise TokenValidationError("invalid_issuer", "entra") from exc
    except jwt.InvalidAudienceError as exc:
        raise TokenValidationError("invalid_audience", "entra") from exc
    except jwt.MissingRequiredClaimError as exc:
        raise TokenValidationError("missing_required_claim", "entra") from exc
    except jwt.InvalidSignatureError as exc:
        raise TokenValidationError("invalid_signature", "entra") from exc
    except jwt.PyJWTError as exc:
        raise TokenValidationError("invalid_claim", "entra") from exc

    if claims.get("tid") != settings.entra_tenant_id:
        raise TokenValidationError("wrong_tenant", "entra")
    if claims.get("aud") != settings.entra_api_audience:
        raise TokenValidationError("invalid_audience", "entra")
    if claims.get("ver") != "2.0" or claims.get("idtyp") != "user":
        raise TokenValidationError("invalid_principal_type", "entra")
    subject_id = claims.get("sub")
    object_id = claims.get("oid")
    client_id = claims.get("azp")
    token_id = claims.get("uti")
    if (
        not isinstance(subject_id, str)
        or not subject_id
        or not isinstance(object_id, str)
        or not object_id
        or not isinstance(client_id, str)
        or not client_id
        or not isinstance(token_id, str)
        or not token_id
    ):
        raise TokenValidationError("missing_identity_claim", "entra")
    try:
        user_id = UUID(object_id)
        UUID(client_id)
    except ValueError as exc:
        raise TokenValidationError("invalid_identity_claim", "entra") from exc
    time_claims = (claims["iat"], claims["nbf"], claims["exp"])
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in time_claims):
        raise TokenValidationError("invalid_time_claim", "entra")
    issued_at = float(claims["iat"])
    expires_at = float(claims["exp"])
    if (
        expires_at <= issued_at
        or expires_at - issued_at > settings.entra_max_token_lifetime_seconds
    ):
        raise TokenValidationError("invalid_token_lifetime", "entra")

    return ValidatedAccessToken(
        family="entra",
        user_id=None,
        external_oid=user_id,
        organization_id=None,
        claimed_role=None,
        tenant_id=settings.entra_tenant_id,
        subject_id=subject_id,
        object_id=object_id,
        client_id=client_id,
        delegated_scopes=_string_set(claims.get("scp"), claim="scp"),
        application_roles=_string_set(claims.get("roles"), claim="roles"),
    )


def validate_access_token(
    token: str,
    settings: Settings,
    key_provider: SigningKeyProvider | None = None,
) -> ValidatedAccessToken:
    family = classify_token(token, settings)
    if settings.auth_mode == "legacy" and family != "legacy":
        raise TokenValidationError("token_family_not_allowed", family)
    if settings.auth_mode == "entra" and family != "entra":
        raise TokenValidationError("token_family_not_allowed", family)
    if settings.auth_mode not in {"legacy", "dual", "entra"}:
        raise TokenValidationError("token_authentication_disabled", family)
    if family == "legacy":
        return _validate_legacy(token, settings)
    if key_provider is None:
        raise TokenValidationError("jwks_unavailable", "entra")
    return _validate_entra(token, settings, key_provider)


class HttpJwksProvider:
    """Bounded in-memory JWKS cache with one forced refresh for an unknown key."""

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float,
        cache_seconds: int,
        fetch_json: Callable[[], object] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.cache_seconds = cache_seconds
        self._fetch_json = fetch_json or self._fetch_remote
        self._clock = clock
        self._keys: dict[str, Any] = {}
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def _fetch_remote(self) -> object:
        timeout = httpx.Timeout(
            self.timeout_seconds,
            connect=self.timeout_seconds,
            read=self.timeout_seconds,
        )
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                response = client.get(self.url, headers={"Accept": "application/json"})
                response.raise_for_status()
                if len(response.content) > MAX_JWKS_BYTES:
                    raise JwksError("jwks_malformed")
                return response.json()
        except JwksError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise JwksError("jwks_unavailable") from exc

    def _refresh(self) -> None:
        try:
            document = self._fetch_json()
        except JwksError:
            raise
        except Exception as exc:
            raise JwksError("jwks_unavailable") from exc
        if not isinstance(document, Mapping):
            raise JwksError("jwks_malformed")
        keys = document.get("keys")
        if not isinstance(keys, list) or not keys or len(keys) > MAX_JWKS_KEYS:
            raise JwksError("jwks_malformed")
        parsed: dict[str, Any] = {}
        for value in keys:
            if not isinstance(value, dict):
                raise JwksError("jwks_malformed")
            key_id = value.get("kid")
            if not isinstance(key_id, str) or not key_id or len(key_id) > 256:
                raise JwksError("jwks_malformed")
            if key_id in parsed:
                raise JwksError("jwks_malformed")
            if value.get("kty") != "RSA" or value.get("use", "sig") != "sig":
                continue
            if value.get("alg", "RS256") != "RS256":
                continue
            try:
                parsed[key_id] = PyJWK.from_dict(value, algorithm="RS256").key
            except (jwt.PyJWTError, ValueError, TypeError) as exc:
                raise JwksError("jwks_malformed") from exc
        if not parsed:
            raise JwksError("jwks_malformed")
        self._keys = parsed
        self._expires_at = self._clock() + self.cache_seconds

    def get_signing_key(self, key_id: str) -> Any:
        with self._lock:
            if not self._keys or self._clock() >= self._expires_at:
                self._refresh()
            key = self._keys.get(key_id)
            if key is not None:
                return key
            self._refresh()
            key = self._keys.get(key_id)
            if key is None:
                raise JwksError("unknown_key_id")
            return key


@lru_cache(maxsize=8)
def _cached_http_jwks_provider(
    url: str, timeout_seconds: float, cache_seconds: int
) -> HttpJwksProvider:
    return HttpJwksProvider(
        url,
        timeout_seconds=timeout_seconds,
        cache_seconds=cache_seconds,
    )


def get_jwks_provider(settings: Settings) -> SigningKeyProvider:
    return _cached_http_jwks_provider(
        settings.entra_jwks_url,
        settings.entra_jwks_timeout_seconds,
        settings.entra_jwks_cache_seconds,
    )
