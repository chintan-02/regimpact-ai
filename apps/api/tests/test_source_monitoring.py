from unittest import TestCase

import httpx

from regimpact.source_client import (
    SafeSourceClient,
    SourceFetchError,
    UnsafeSourceUrlError,
    validate_source_url,
)

PUBLIC_RESOLVER = lambda hostname: {"93.184.216.34"}


class SourceUrlSecurityTests(TestCase):
    def test_requires_https_and_exact_allowlist(self):
        with self.assertRaisesRegex(UnsafeSourceUrlError, "HTTPS"):
            validate_source_url(
                "http://regulator.example/rule.pdf",
                allowed_hosts=frozenset({"regulator.example"}),
                resolver=PUBLIC_RESOLVER,
            )
        with self.assertRaisesRegex(UnsafeSourceUrlError, "allowlisted"):
            validate_source_url(
                "https://evil.example/rule.pdf",
                allowed_hosts=frozenset({"regulator.example"}),
                resolver=PUBLIC_RESOLVER,
            )

    def test_rejects_private_dns_results(self):
        with self.assertRaisesRegex(UnsafeSourceUrlError, "non-public"):
            validate_source_url(
                "https://regulator.example/rule.pdf",
                allowed_hosts=frozenset({"regulator.example"}),
                resolver=lambda hostname: {"127.0.0.1"},
            )


class ConditionalSourceClientTests(TestCase):
    def client(self, handler, *, max_bytes=10_000):
        return SafeSourceClient(
            allowed_hosts=frozenset({"regulator.example"}),
            max_bytes=max_bytes,
            timeout_seconds=5,
            resolver=PUBLIC_RESOLVER,
            transport=httpx.MockTransport(handler),
        )

    def test_304_uses_conditional_headers_and_returns_unchanged(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["If-None-Match"], '"abc"')
            self.assertEqual(request.headers["If-Modified-Since"], "Mon, 24 Aug 2026 12:00:00 GMT")
            return httpx.Response(304, headers={"ETag": '"abc"'})

        result = self.client(handler).fetch(
            "https://regulator.example/rule.pdf",
            etag='"abc"',
            last_modified="Mon, 24 Aug 2026 12:00:00 GMT",
        )
        self.assertFalse(result.changed)
        self.assertIsNone(result.content)

    def test_redirects_are_rejected(self):
        client = self.client(
            lambda request: httpx.Response(
                302, headers={"Location": "https://internal.example/secret"}
            )
        )
        with self.assertRaisesRegex(UnsafeSourceUrlError, "redirect"):
            client.fetch("https://regulator.example/rule.pdf")

    def test_streamed_response_limit_is_enforced(self):
        client = self.client(
            lambda request: httpx.Response(
                200,
                headers={"Content-Type": "application/pdf"},
                content=b"%PDF-" + b"x" * 100,
            ),
            max_bytes=20,
        )
        with self.assertRaisesRegex(SourceFetchError, "byte limit"):
            client.fetch("https://regulator.example/rule.pdf")
