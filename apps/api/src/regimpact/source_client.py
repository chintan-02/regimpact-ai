"""Restricted conditional HTTP client for approved public regulatory sources."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class UnsafeSourceUrlError(ValueError):
    pass


class SourceFetchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SourceFetchResult:
    status_code: int
    changed: bool
    content: bytes | None
    media_type: str | None
    filename: str | None
    etag: str | None
    last_modified: str | None


Resolver = Callable[[str], set[str]]


def system_resolver(hostname: str) -> set[str]:
    return {str(item[4][0]) for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}


def validate_source_url(url: str, *, allowed_hosts: frozenset[str], resolver: Resolver) -> str:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https":
        raise UnsafeSourceUrlError("regulatory sources must use HTTPS")
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise UnsafeSourceUrlError("source URL credentials and non-standard ports are not allowed")
    if not hostname or hostname not in allowed_hosts:
        raise UnsafeSourceUrlError("source hostname is not explicitly allowlisted")
    try:
        addresses = resolver(hostname)
    except OSError as exc:
        raise SourceFetchError("source DNS resolution failed") from exc
    if not addresses:
        raise SourceFetchError("source DNS returned no addresses")
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise UnsafeSourceUrlError("source resolves to a non-public network address")
    return hostname


class SafeSourceClient:
    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str],
        max_bytes: int,
        timeout_seconds: float,
        resolver: Resolver = system_resolver,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.allowed_hosts = allowed_hosts
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self.resolver = resolver
        self.transport = transport

    def fetch(
        self, url: str, *, etag: str | None = None, last_modified: str | None = None
    ) -> SourceFetchResult:
        validate_source_url(url, allowed_hosts=self.allowed_hosts, resolver=self.resolver)
        headers = {"Accept": "application/pdf,text/html;q=0.9", "User-Agent": "RegImpact/0.1"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        try:
            with (
                httpx.Client(
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                    transport=self.transport,
                ) as client,
                client.stream("GET", url, headers=headers) as response,
            ):
                if response.status_code in {301, 302, 303, 307, 308}:
                    raise UnsafeSourceUrlError("source redirects are not followed")
                if response.status_code == 304:
                    return SourceFetchResult(
                        status_code=304,
                        changed=False,
                        content=None,
                        media_type=None,
                        filename=None,
                        etag=response.headers.get("ETag") or etag,
                        last_modified=response.headers.get("Last-Modified") or last_modified,
                    )
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > self.max_bytes:
                    raise SourceFetchError("source document exceeds the configured byte limit")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise SourceFetchError("source document exceeds the configured byte limit")
                    chunks.append(chunk)
                content = b"".join(chunks)
        except httpx.HTTPError as exc:
            raise SourceFetchError("source HTTP request failed") from exc

        path_name = urlsplit(url).path.rsplit("/", 1)[-1] or "regulation"
        return SourceFetchResult(
            status_code=response.status_code,
            changed=True,
            content=content,
            media_type=response.headers.get("Content-Type"),
            filename=path_name,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
        )
