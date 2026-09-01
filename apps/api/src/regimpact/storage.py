"""Immutable object-storage boundary and local development adapter."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol
from uuid import UUID


class ObjectStorage(Protocol):
    def put_document(
        self, *, organization_id: UUID, object_key: str, filename: str, content: bytes
    ) -> str: ...

    def get_document(self, uri: str) -> bytes: ...


class LocalObjectStorage:
    """Local adapter with atomic writes. Azure Blob implements the same boundary later."""

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def put_document(
        self, *, organization_id: UUID, object_key: str, filename: str, content: bytes
    ) -> str:
        if len(object_key) != 64 or any(char not in "0123456789abcdef" for char in object_key):
            raise ValueError("object key must be a lowercase SHA-256 digest")
        suffix = Path(filename).suffix.lower()
        target = (self.root / str(organization_id) / f"{object_key}{suffix}").resolve()
        if self.root not in target.parents:
            raise ValueError("invalid object-storage target")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.part")
        if not target.exists():
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
        return target.as_uri()

    def get_document(self, uri: str) -> bytes:
        target = Path(uri.removeprefix("file://")).resolve()
        if self.root not in target.parents:
            raise ValueError("object URI is outside the configured storage root")
        return target.read_bytes()
