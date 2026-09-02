import asyncio
from unittest import TestCase

import httpx

from regimpact.main import create_app


class ApiContractTests(TestCase):
    async def request(self, method: str, path: str, **kwargs):
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    def test_health_preserves_supplied_request_id(self):
        response = asyncio.run(
            self.request("GET", "/health", headers={"X-Request-ID": "trace-123"})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "trace-123")

    def test_validation_error_uses_stable_envelope_and_generated_request_id(self):
        response = asyncio.run(
            self.request(
                "POST",
                "/api/v1/organizations",
                headers={"X-Organization-ID": "11111111-1111-4111-8111-111111111111"},
                json={"name": "N"},
            )
        )
        body = response.json()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(body["error"]["code"], "request_validation_failed")
        self.assertEqual(body["error"]["request_id"], response.headers["X-Request-ID"])
