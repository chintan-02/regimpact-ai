"""Relational source-of-truth models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .domain import utc_now
from .vector_type import VectorType


class OrganizationRecord(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UserRecord(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_user_org_email"),
        Index("ix_users_org_role", "organization_id", "role"),
    )

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RegulationRecord(Base):
    __tablename__ = "regulations"
    __table_args__ = (
        UniqueConstraint("organization_id", "source_key", name="uq_regulation_org_source"),
        Index("ix_regulations_org", "organization_id"),
    )

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    source_key: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    versions: Mapped[list[RegulationVersionRecord]] = relationship(
        back_populates="regulation", cascade="all, delete-orphan"
    )


class RegulationVersionRecord(Base):
    __tablename__ = "regulation_versions"
    __table_args__ = (
        UniqueConstraint("regulation_id", "ordinal", name="uq_version_regulation_ordinal"),
        UniqueConstraint("regulation_id", "content_hash", name="uq_version_regulation_hash"),
        Index("ix_versions_regulation_ingested", "regulation_id", "ingested_at"),
    )

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    regulation_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    regulation: Mapped[RegulationRecord] = relationship(back_populates="versions")
    sections: Mapped[list[SectionRecord]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="SectionRecord.position"
    )


class SectionRecord(Base):
    __tablename__ = "regulation_sections"
    __table_args__ = (
        UniqueConstraint("version_id", "section_key", name="uq_section_version_key"),
        Index("ix_sections_version", "version_id"),
    )

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulation_versions.id", ondelete="CASCADE"), nullable=False
    )
    section_key: Mapped[str] = mapped_column(String(160), nullable=False)
    heading: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[RegulationVersionRecord] = relationship(back_populates="sections")


class SectionChangeRecord(Base):
    __tablename__ = "section_changes"
    __table_args__ = (
        Index("ix_changes_regulation_current", "regulation_id", "current_version_id"),
    )

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True)
    regulation_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False
    )
    previous_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("regulation_versions.id", ondelete="RESTRICT"), nullable=True
    )
    current_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulation_versions.id", ondelete="CASCADE"), nullable=False
    )
    section_key: Mapped[str] = mapped_column(String(160), nullable=False)
    heading: Mapped[str] = mapped_column(String(500), nullable=False)
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    previous_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_page: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_org_created", "organization_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(SAUuid, nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class IngestionJobRecord(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "regulation_id", "content_hash", name="uq_ingestion_org_reg_hash"
        ),
        Index("ix_ingestion_org_status_created", "organization_id", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    regulation_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    original_filename: Mapped[str] = mapped_column(String(240), nullable=False)
    media_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    resulting_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("regulation_versions.id", ondelete="SET NULL"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    failure_class: Mapped[str | None] = mapped_column(String(30), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(SAUuid, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxEventRecord(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_pending_created", "published_at", "created_at"),)

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RegulatorySourceRecord(Base):
    __tablename__ = "regulatory_sources"
    __table_args__ = (
        UniqueConstraint("organization_id", "url", name="uq_source_org_url"),
        Index("ix_source_due", "enabled", "next_check_at"),
    )

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    regulation_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_host: Mapped[str] = mapped_column(String(253), nullable=False)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1_440)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    etag: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SourceCheckRecord(Base):
    __tablename__ = "source_checks"
    __table_args__ = (Index("ix_source_checks_source_started", "source_id", "started_at"),)

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulatory_sources.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingestion_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ObligationRecord(Base):
    __tablename__ = "obligations"
    __table_args__ = (
        UniqueConstraint("version_id", "fingerprint", name="uq_obligation_version_fingerprint"),
        Index("ix_obligations_org_status", "organization_id", "status"),
        Index("ix_obligations_regulation_version", "regulation_id", "version_id"),
    )

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    regulation_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulation_versions.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulation_sections.id", ondelete="CASCADE"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(String(240), nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    modality: Mapped[str] = mapped_column(String(30), nullable=False)
    deadline_text: Mapped[str | None] = mapped_column(String(240), nullable=True)
    raw_confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    calibration_policy_id: Mapped[str] = mapped_column(String(80), nullable=False)
    requires_review: Mapped[bool] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="candidate")
    extraction_method: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ObligationExtractionRunRecord(Base):
    __tablename__ = "obligation_extraction_runs"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "extraction_method", name="uq_obligation_run_version_method"
        ),
        Index("ix_obligation_runs_org_created", "organization_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulation_versions.id", ondelete="CASCADE"), nullable=False
    )
    extraction_method: Mapped[str] = mapped_column(String(80), nullable=False)
    calibration_policy_id: Mapped[str] = mapped_column(String(80), nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ClauseClassificationRecord(Base):
    __tablename__ = "clause_classifications"
    __table_args__ = (
        UniqueConstraint(
            "section_id", "clause_hash", "model_id", name="uq_clause_classification_model"
        ),
        Index("ix_clause_classification_org_status", "organization_id", "status"),
        Index("ix_clause_classification_version", "version_id", "section_id"),
    )

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    regulation_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulation_versions.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulation_sections.id", ondelete="CASCADE"), nullable=False
    )
    clause_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    abstained: Mapped[bool] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    model_id: Mapped[str] = mapped_column(String(240), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(120), nullable=False)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    probabilities_json: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ClauseClassificationRunRecord(Base):
    __tablename__ = "clause_classification_runs"
    __table_args__ = (
        UniqueConstraint("version_id", "model_id", name="uq_clause_run_version_model"),
        Index("ix_clause_run_org_created", "organization_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulation_versions.id", ondelete="CASCADE"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(240), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(120), nullable=False)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    clause_count: Mapped[int] = mapped_column(Integer, nullable=False)
    abstained_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SectionSearchRecord(Base):
    __tablename__ = "section_search_index"
    __table_args__ = (
        UniqueConstraint("section_id", "embedding_model_id", name="uq_search_section_model"),
        Index("ix_search_org_version", "organization_id", "version_id"),
    )

    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    regulation_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulation_versions.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[UUID] = mapped_column(
        ForeignKey("regulation_sections.id", ondelete="CASCADE"), nullable=False
    )
    embedding_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    searchable_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VectorType(384), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ControlRecord(Base):
    __tablename__ = "controls"
    __table_args__ = (
        UniqueConstraint("organization_id", "control_key", name="uq_control_org_key"),
    )
    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    control_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ControlVersionRecord(Base):
    __tablename__ = "control_versions"
    __table_args__ = (UniqueConstraint("control_id", "ordinal", name="uq_control_version_ordinal"),)
    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    control_id: Mapped[UUID] = mapped_column(
        ForeignKey("controls.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_requirement: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ObligationControlMappingRecord(Base):
    __tablename__ = "obligation_control_mappings"
    __table_args__ = (
        UniqueConstraint(
            "obligation_id", "control_version_id", name="uq_mapping_obligation_control_version"
        ),
        Index("ix_mapping_org_status", "organization_id", "status"),
    )
    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    obligation_id: Mapped[UUID] = mapped_column(
        ForeignKey("obligations.id", ondelete="CASCADE"), nullable=False
    )
    control_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_versions.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    explanation_json: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_method: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MappingDecisionRecord(Base):
    """Append-only analyst decisions; machine suggestions remain immutable evidence."""

    __tablename__ = "mapping_decisions"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_decision_org_key"),
        UniqueConstraint("mapping_id", "revision", name="uq_decision_mapping_revision"),
        Index("ix_decision_org_state", "organization_id", "decision"),
    )
    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    obligation_id: Mapped[UUID] = mapped_column(
        ForeignKey("obligations.id", ondelete="CASCADE"), nullable=False
    )
    mapping_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("obligation_control_mappings.id", ondelete="CASCADE"), nullable=True
    )
    control_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("control_versions.id", ondelete="RESTRICT"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("mapping_decisions.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentWorkflowRunRecord(Base):
    """Immutable proposal inputs plus controlled workflow state."""

    __tablename__ = "agent_workflow_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_agent_run_org_key"),
        Index("ix_agent_run_org_status", "organization_id", "status", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    obligation_id: Mapped[UUID] = mapped_column(
        ForeignKey("obligations.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_json: Mapped[str] = mapped_column(Text, nullable=False)
    policy_results_json: Mapped[str] = mapped_column(Text, nullable=False)
    agent_version: Mapped[str] = mapped_column(String(80), nullable=False)
    evaluation_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentWorkflowDecisionRecord(Base):
    """Append-only human decisions; agent proposals are never rewritten."""

    __tablename__ = "agent_workflow_decisions"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_agent_decision_org_key"),
        UniqueConstraint("workflow_run_id", "revision", name="uq_agent_decision_revision"),
        Index("ix_agent_decision_org_created", "organization_id", "decided_at"),
    )
    id: Mapped[UUID] = mapped_column(SAUuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_workflow_decisions.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
