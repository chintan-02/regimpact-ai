"""Minimal PostgreSQL pgvector type with SQLite-compatible test serialization."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, cast

from sqlalchemy.types import UserDefinedType


class VectorType(UserDefinedType[list[float]]):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: Any) -> str:
        return f"VECTOR({self.dimensions})"

    def bind_processor(self, dialect):  # type: ignore[no-untyped-def]
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            if len(value) != self.dimensions:
                raise ValueError(f"embedding must have {self.dimensions} dimensions")
            return json.dumps(value, separators=(",", ":"))

        return process

    def result_processor(self, dialect, coltype):  # type: ignore[no-untyped-def]
        def process(value: object) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, str):
                return [float(item) for item in json.loads(value)]
            return [float(cast(Any, item)) for item in cast(Iterable[object], value)]

        return process
