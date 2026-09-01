"""Version creation service with explicit idempotency semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID, uuid4

from .change_detection import detect_changes
from .domain import RegulationVersion, Section, SectionChange, content_hash, utc_now


@dataclass(frozen=True, slots=True)
class IngestionResult:
    version: RegulationVersion
    changes: tuple[SectionChange, ...]
    created: bool


class InMemoryVersionRepository:
    """Test adapter. PostgreSQL becomes the production adapter in v0.1 slice 2."""

    def __init__(self) -> None:
        self._versions: dict[UUID, list[RegulationVersion]] = {}

    def latest(self, regulation_id: UUID) -> RegulationVersion | None:
        versions = self._versions.get(regulation_id, [])
        return versions[-1] if versions else None

    def add(self, version: RegulationVersion, changes: tuple[SectionChange, ...]) -> None:
        self._versions.setdefault(version.regulation_id, []).append(version)


class VersionRepository(Protocol):
    def latest(self, regulation_id: UUID) -> RegulationVersion | None: ...

    def add(self, version: RegulationVersion, changes: tuple[SectionChange, ...]) -> None: ...


class VersioningService:
    def __init__(self, repository: VersionRepository) -> None:
        self._repository = repository

    def ingest(
        self,
        *,
        regulation_id: UUID,
        source_uri: str,
        raw_content: str,
        sections: tuple[Section, ...],
        effective_date: date | None = None,
    ) -> IngestionResult:
        if not source_uri.strip():
            raise ValueError("source_uri must not be empty")
        if not sections:
            raise ValueError("at least one section is required")

        digest = content_hash(raw_content)
        previous = self._repository.latest(regulation_id)
        if previous and previous.hash == digest:
            return IngestionResult(version=previous, changes=(), created=False)

        version = RegulationVersion(
            id=uuid4(),
            regulation_id=regulation_id,
            ordinal=(previous.ordinal + 1) if previous else 1,
            hash=digest,
            effective_date=effective_date,
            source_uri=source_uri,
            sections=sections,
            ingested_at=utc_now(),
        )
        changes = detect_changes(previous, version)
        self._repository.add(version, changes)
        return IngestionResult(version=version, changes=changes, created=True)
