import asyncio
import json
from io import StringIO
from unittest import TestCase

import httpx

from regimpact.main import create_app
from regimpact.observability import JsonFormatter, trace_context


class ObservabilityTests(TestCase):
    async def request(self, path: str, headers: dict[str, str] | None = None):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
        ) as client:
            return await client.get(path, headers=headers)

    def test_traceparent_is_propagated_with_new_span(self):
        trace_id = "0123456789abcdef0123456789abcdef"
        response = asyncio.run(
            self.request("/health", {"traceparent": f"00-{trace_id}-0123456789abcdef-01"})
        )
        self.assertEqual(response.headers["X-Trace-ID"], trace_id)
        self.assertTrue(response.headers["traceparent"].startswith(f"00-{trace_id}-"))

    def test_metrics_are_prometheus_formatted(self):
        asyncio.run(self.request("/health"))
        response = asyncio.run(self.request("/metrics"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("regimpact_http_requests_total", response.text)
        self.assertIn("regimpact_http_request_duration_seconds", response.text)
        self.assertIn("regimpact_ingestion_jobs", response.text)
        self.assertIn("regimpact_outbox_events", response.text)

    def test_json_formatter_produces_machine_readable_event(self):
        import logging

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("regimpact.test")
        logger.handlers = [handler]
        logger.propagate = False
        logger.warning("observable")
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["message"], "observable")
        self.assertEqual(payload["level"], "warning")

    def test_invalid_traceparent_creates_valid_trace(self):
        trace_id, parent = trace_context("invalid")
        self.assertEqual(len(trace_id), 32)
        self.assertTrue(parent.startswith(f"00-{trace_id}-"))
