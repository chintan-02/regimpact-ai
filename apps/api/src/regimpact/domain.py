"""Dependency-free domain types for versioned regulatory content."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


def content_hash(content: str) -> str:
    """Hash normalized content so line-ending differences do not create versions."""
    normalized = "\n".join(line.rstrip() for line in content.replace("\r\n", "\n").split("\n"))
    return sha256(normalized.strip().encode("utf-8")).hexdigest()


class ChangeType(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"


class ObligationModality(StrEnum):
    MUST = "must"
    MUST_NOT = "must_not"
    SHALL = "shall"
    SHALL_NOT = "shall_not"
    REQUIRED_TO = "required_to"


@dataclass(frozen=True, slots=True)
class Section:
    key: str
    heading: str
    text: str
    page: int | None = None

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("section key must not be empty")
        if not self.text.strip():
            raise ValueError("section text must not be empty")


@dataclass(frozen=True, slots=True)
class Regulation:
    id: UUID
    organization_id: UUID
    source_key: str
    title: str
    jurisdiction: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RegulationVersion:
    id: UUID
    regulation_id: UUID
    ordinal: int
    hash: str
    effective_date: date | None
    source_uri: str
    sections: tuple[Section, ...]
    ingested_at: datetime


@dataclass(frozen=True, slots=True)
class SectionChange:
    id: UUID
    regulation_id: UUID
    previous_version_id: UUID | None
    current_version_id: UUID
    section_key: str
    heading: str
    change_type: ChangeType
    previous_text: str | None
    current_text: str | None
    previous_page: int | None
    current_page: int | None

    @classmethod
    def create(cls, **values: object) -> SectionChange:
        return cls(id=uuid4(), **values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ObligationCandidate:
    text: str
    evidence_quote: str
    subject: str | None
    action: str
    modality: ObligationModality
    deadline_text: str | None
    raw_confidence: float
    confidence: float
    requires_review: bool
    rule_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.text.strip() or not self.evidence_quote.strip():
            raise ValueError("obligation text and evidence must not be empty")
        if not self.action.strip():
            raise ValueError("obligation action must not be empty")
        if not 0 <= self.raw_confidence <= 1 or not 0 <= self.confidence <= 1:
            raise ValueError("obligation confidence must be between zero and one")
