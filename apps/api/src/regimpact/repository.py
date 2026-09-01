"""Organization-scoped SQLAlchemy repositories."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .db_models import (
    AuditEventRecord,
    OrganizationRecord,
    RegulationRecord,
    RegulationVersionRecord,
    SectionChangeRecord,
    SectionRecord,
)
from .domain import RegulationVersion, Section, SectionChange


class RegulationNotFoundError(LookupError):
    pass


class SqlAlchemyVersionRepository:
    def __init__(self, session: Session, organization_id: UUID, actor_id: str) -> None:
        self.session = session
        self.organization_id = organization_id
        self.actor_id = actor_id

    def owned_regulation(self, regulation_id: UUID) -> RegulationRecord:
        record = self.session.scalar(
            select(RegulationRecord).where(
                RegulationRecord.id == regulation_id,
                RegulationRecord.organization_id == self.organization_id,
            )
        )
        if record is None:
            raise RegulationNotFoundError("regulation not found")
        return record

    def latest(self, regulation_id: UUID) -> RegulationVersion | None:
        self.owned_regulation(regulation_id)
        record = self.session.scalar(
            select(RegulationVersionRecord)
            .options(selectinload(RegulationVersionRecord.sections))
            .where(RegulationVersionRecord.regulation_id == regulation_id)
            .order_by(RegulationVersionRecord.ordinal.desc())
            .limit(1)
        )
        return self._to_domain(record) if record else None

    def add(self, version: RegulationVersion, changes: tuple[SectionChange, ...]) -> None:
        self.owned_regulation(version.regulation_id)
        record = RegulationVersionRecord(
            id=version.id,
            regulation_id=version.regulation_id,
            ordinal=version.ordinal,
            content_hash=version.hash,
            effective_date=version.effective_date,
            source_uri=version.source_uri,
            ingested_at=version.ingested_at,
            sections=[
                SectionRecord(
                    section_key=section.key,
                    heading=section.heading,
                    body=section.text,
                    page=section.page,
                    position=position,
                )
                for position, section in enumerate(version.sections)
            ],
        )
        self.session.add(record)
        self.session.add_all(
            [
                SectionChangeRecord(
                    id=change.id,
                    regulation_id=change.regulation_id,
                    previous_version_id=change.previous_version_id,
                    current_version_id=change.current_version_id,
                    section_key=change.section_key,
                    heading=change.heading,
                    change_type=change.change_type.value,
                    previous_text=change.previous_text,
                    current_text=change.current_text,
                    previous_page=change.previous_page,
                    current_page=change.current_page,
                )
                for change in changes
            ]
        )
        self.session.add(
            AuditEventRecord(
                organization_id=self.organization_id,
                actor_id=self.actor_id,
                event_type="regulation.version_created",
                entity_type="regulation_version",
                entity_id=version.id,
                detail_json=json.dumps(
                    {"regulation_id": str(version.regulation_id), "ordinal": version.ordinal}
                ),
            )
        )

    @staticmethod
    def _to_domain(record: RegulationVersionRecord) -> RegulationVersion:
        return RegulationVersion(
            id=record.id,
            regulation_id=record.regulation_id,
            ordinal=record.ordinal,
            hash=record.content_hash,
            effective_date=record.effective_date,
            source_uri=record.source_uri,
            sections=tuple(
                Section(key=s.section_key, heading=s.heading, text=s.body, page=s.page)
                for s in record.sections
            ),
            ingested_at=record.ingested_at,
        )


def ensure_organization(session: Session, organization_id: UUID, name: str) -> None:
    if session.get(OrganizationRecord, organization_id) is None:
        session.add(OrganizationRecord(id=organization_id, name=name))


def create_regulation(
    session: Session,
    *,
    organization_id: UUID,
    source_key: str,
    title: str,
    jurisdiction: str,
) -> RegulationRecord:
    record = RegulationRecord(
        organization_id=organization_id,
        source_key=source_key,
        title=title,
        jurisdiction=jurisdiction,
    )
    session.add(record)
    session.flush()
    return record
