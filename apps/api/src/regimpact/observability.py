"""Low-cardinality metrics, JSON logging, and trace-context correlation."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
from collections import Counter, defaultdict
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter

request_id_context: ContextVar[str] = ContextVar("request_id", default="")
trace_id_context: ContextVar[str] = ContextVar("trace_id", default="")
actor_id_context: ContextVar[str] = ContextVar("actor_id", default="")
organization_id_context: ContextVar[str] = ContextVar("organization_id", default="")

TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "service": "regimpact-api",
        }
        context_fields: dict[str, str] = {
            "request_id": request_id_context.get(),
            "trace_id": trace_id_context.get(),
            "actor_id": actor_id_context.get(),
            "organization_id": organization_id_context.get(),
        }
        for key, value in context_fields.items():
            if value:
                payload[key] = value
        for key in ("method", "route", "status_code", "duration_ms", "event"):
            extra_value = getattr(record, key, None)
            if extra_value is not None:
                payload[key] = extra_value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


def configure_cloud_telemetry() -> None:
    """Enable Azure Monitor only when its deployment connection string is present."""
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection_string:
        return
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(connection_string=connection_string)


def trace_context(value: str | None) -> tuple[str, str]:
    match = TRACEPARENT_RE.fullmatch((value or "").lower())
    trace_id = match.group(1) if match and match.group(1) != "0" * 32 else secrets.token_hex(16)
    span_id = secrets.token_hex(8)
    return trace_id, f"00-{trace_id}-{span_id}-01"


@dataclass
class Metrics:
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    requests: Counter[tuple[str, str, str]] = field(default_factory=Counter)
    latency_count: Counter[tuple[str, str]] = field(default_factory=Counter)
    latency_sum: dict[tuple[str, str], float] = field(default_factory=lambda: defaultdict(float))
    latency_buckets: Counter[tuple[str, str, float]] = field(default_factory=Counter)
    inflight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def begin(self) -> float:
        with self._lock:
            self.inflight += 1
        return perf_counter()

    def finish(self, method: str, route: str, status_code: int, started: float) -> float:
        duration = perf_counter() - started
        status = str(status_code)
        with self._lock:
            self.inflight -= 1
            self.requests[(method, route, status)] += 1
            self.latency_count[(method, route)] += 1
            self.latency_sum[(method, route)] += duration
            for bucket in LATENCY_BUCKETS:
                if duration <= bucket:
                    self.latency_buckets[(method, route, bucket)] += 1
        return duration

    def render(self) -> str:
        lines = [
            "# HELP regimpact_http_requests_total HTTP requests processed.",
            "# TYPE regimpact_http_requests_total counter",
        ]
        with self._lock:
            for (method, route, status), value in sorted(self.requests.items()):
                lines.append(
                    f'regimpact_http_requests_total{{method="{method}",route="{route}",status="{status}"}} {value}'
                )
            lines.extend(
                [
                    "# HELP regimpact_http_requests_inflight Requests currently executing.",
                    "# TYPE regimpact_http_requests_inflight gauge",
                    f"regimpact_http_requests_inflight {self.inflight}",
                    "# HELP regimpact_http_request_duration_seconds HTTP request latency.",
                    "# TYPE regimpact_http_request_duration_seconds histogram",
                ]
            )
            for method, route in sorted(self.latency_count):
                for bucket in LATENCY_BUCKETS:
                    value = self.latency_buckets[(method, route, bucket)]
                    lines.append(
                        f'regimpact_http_request_duration_seconds_bucket{{method="{method}",route="{route}",le="{bucket}"}} {value}'
                    )
                count = self.latency_count[(method, route)]
                total = self.latency_sum[(method, route)]
                labels = f'method="{method}",route="{route}"'
                lines.append(f"regimpact_http_request_duration_seconds_count{{{labels}}} {count}")
                lines.append(f"regimpact_http_request_duration_seconds_sum{{{labels}}} {total:.6f}")
        lines.extend(
            [
                "# HELP regimpact_process_uptime_seconds Process uptime.",
                "# TYPE regimpact_process_uptime_seconds gauge",
                f"regimpact_process_uptime_seconds {(datetime.now(UTC) - self.started_at).total_seconds():.3f}",
            ]
        )
        return "\n".join(lines) + "\n"


metrics = Metrics()
