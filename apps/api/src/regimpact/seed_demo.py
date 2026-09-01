"""Idempotent reference tenant for the end-to-end analyst workflow."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from .control_mapping import add_control, suggest_mappings
from .database import SessionFactory
from .db_models import (
    IngestionJobRecord,
    ObligationRecord,
    RegulationRecord,
    RegulationVersionRecord,
    RegulatorySourceRecord,
)
from .domain import Section, content_hash, utc_now
from .embeddings import FeatureHashEmbeddingProvider
from .obligation_service import extract_and_store_obligations
from .repository import SqlAlchemyVersionRepository, ensure_organization
from .retrieval import index_version
from .review_workflow import decide_mapping
from .versioning import VersioningService

ORGANIZATION_ID = UUID("11111111-1111-4111-8111-111111111111")
REGULATION_ID = UUID("22222222-2222-4222-8222-222222222222")
SOURCE_PAGE = "https://www.aer.ca/regulations-and-compliance-enforcement/rules-and-regulations/directives/directive-060"


def seed() -> None:
    with SessionFactory() as session, session.begin():
        ensure_organization(session, ORGANIZATION_ID, "Northstar Energy")
        regulation = session.scalar(
            select(RegulationRecord).where(RegulationRecord.id == REGULATION_ID)
        )
        if regulation is None:
            regulation = RegulationRecord(
                id=REGULATION_ID,
                organization_id=ORGANIZATION_ID,
                source_key="AER-D060",
                title="Directive 060 — Upstream Petroleum Industry Flaring",
                jurisdiction="Alberta, Canada",
            )
            session.add(regulation)
            session.flush()
        else:
            regulation.source_key = "AER-D060"
            regulation.title = "Directive 060 — Upstream Petroleum Industry Flaring"
            regulation.jurisdiction = "Alberta, Canada"

        first_content = "v12|4.2|72 hours|2.6|legacy exemption"
        second_content = "v13|4.2|24 hours|7.1|assurance records"
        versions = {
            version.content_hash: version
            for version in session.scalars(
                select(RegulationVersionRecord).where(
                    RegulationVersionRecord.regulation_id == REGULATION_ID
                )
            )
        }
        first_version = versions.get(content_hash(first_content))
        second_version = versions.get(content_hash(second_content))
        if (first_version is None) != (second_version is None) or (
            versions and (first_version is None or second_version is None)
        ):
            raise RuntimeError("demo regulation exists with unexpected version history")

        service = VersioningService(
            SqlAlchemyVersionRepository(session, ORGANIZATION_ID, "system:demo-seed")
        )
        if first_version is None:
            first = service.ingest(
                regulation_id=REGULATION_ID,
                source_uri=f"{SOURCE_PAGE}#edition-12",
                raw_content=first_content,
                sections=(
                    Section(
                        "4.2",
                        "Incident notification",
                        "Operators must notify the regulator within 72 hours of a reportable incident.",
                        41,
                    ),
                    Section(
                        "2.6",
                        "Legacy facility exemption",
                        "Facilities commissioned before 2000 may use the legacy reporting exemption.",
                        18,
                    ),
                    Section(
                        "6.4",
                        "Measurement records",
                        "Measurement records must be retained for five years.",
                        58,
                    ),
                ),
            )
            session.flush()
            second = service.ingest(
                regulation_id=REGULATION_ID,
                source_uri=f"{SOURCE_PAGE}#edition-13",
                raw_content=second_content,
                sections=(
                    Section(
                        "4.2",
                        "Incident notification",
                        "Operators must notify the regulator within 24 hours of a reportable "
                        "incident and preserve the submission receipt.",
                        43,
                    ),
                    Section(
                        "6.4",
                        "Measurement records",
                        "Measurement records must be retained for five years.",
                        61,
                    ),
                    Section(
                        "7.1",
                        "Assurance evidence",
                        "Operators must retain evidence demonstrating quarterly control "
                        "verification for seven years.",
                        67,
                    ),
                ),
            )
            session.flush()
            first_version = session.get(RegulationVersionRecord, first.version.id)
            second_version = session.get(RegulationVersionRecord, second.version.id)

        if first_version is None or second_version is None:
            raise RuntimeError("demo versions could not be resolved")

        first_version.source_uri = f"{SOURCE_PAGE}#edition-12"
        second_version.source_uri = f"{SOURCE_PAGE}#edition-13"

        extract_and_store_obligations(
            session,
            organization_id=ORGANIZATION_ID,
            version_id=second_version.id,
            actor_id="system:demo-seed",
        )
        index_version(
            session,
            organization_id=ORGANIZATION_ID,
            version_id=second_version.id,
            provider=FeatureHashEmbeddingProvider(),
        )

        controls = (
            (
                "REG-IR-01",
                "Regulatory incident notification",
                "Notify the regulator of reportable incidents within the prescribed reporting window.",
                "Regulatory Compliance",
                "Submission receipt, incident record, and escalation log",
            ),
            (
                "ASSUR-07",
                "Quarterly control assurance",
                "Perform quarterly control verification and retain assurance evidence for the required period.",
                "Operational Assurance",
                "Approved quarterly test record and supporting evidence package",
            ),
            (
                "DOC-RET-05",
                "Regulatory evidence retention",
                "Retain regulated operating and measurement records in an accessible evidence repository.",
                "Records Management",
                "Retention schedule, repository record, and disposition approval",
            ),
        )
        for control_key, title, description, owner, evidence_requirement in controls:
            add_control(
                session,
                organization_id=ORGANIZATION_ID,
                control_key=control_key,
                title=title,
                description=description,
                owner=owner,
                evidence_requirement=evidence_requirement,
            )

        all_mappings = []
        for obligation in session.scalars(
            select(ObligationRecord).where(
                ObligationRecord.organization_id == ORGANIZATION_ID,
                ObligationRecord.version_id == second_version.id,
            )
        ):
            all_mappings.extend(
                suggest_mappings(
                    session,
                    organization_id=ORGANIZATION_ID,
                    obligation_id=obligation.id,
                    actor_id="system:reference-data",
                )
            )

        seeded_decisions = (
            ("accepted", "Evidence requirement and reporting workflow align."),
            ("rejected", "Candidate shares terms but does not address this obligation."),
            ("deferred", "Control owner confirmation is required before disposition."),
        )
        for mapping, (decision, rationale) in zip(all_mappings, seeded_decisions, strict=False):
            decide_mapping(
                session,
                organization_id=ORGANIZATION_ID,
                obligation_id=mapping.obligation_id,
                mapping_id=mapping.id,
                decision=decision,
                rationale=rationale,
                actor_id="development:reference-analyst",
                idempotency_key=f"reference-{decision}-{mapping.id}",
                expected_revision=0,
            )

        source = session.scalar(
            select(RegulatorySourceRecord).where(
                RegulatorySourceRecord.regulation_id == REGULATION_ID
            )
        )
        if source is None:
            session.add(
                RegulatorySourceRecord(
                    organization_id=ORGANIZATION_ID,
                    regulation_id=REGULATION_ID,
                    name="Alberta Energy Regulator — Directive 060",
                    url=SOURCE_PAGE,
                    allowed_host="www.aer.ca",
                    poll_interval_minutes=1_440,
                    last_checked_at=utc_now(),
                    next_check_at=utc_now() + timedelta(days=1),
                )
            )
        else:
            source.name = "Alberta Energy Regulator — Directive 060"
            source.url = SOURCE_PAGE
            source.allowed_host = "www.aer.ca"

        existing_jobs = session.scalars(
            select(IngestionJobRecord).where(IngestionJobRecord.regulation_id == REGULATION_ID)
        ).all()
        existing_hashes = {job.content_hash for job in existing_jobs}
        for ordinal, version in ((12, first_version), (13, second_version)):
            if version.content_hash in existing_hashes:
                continue
            completed = version.ingested_at
            session.add(
                IngestionJobRecord(
                    organization_id=ORGANIZATION_ID,
                    regulation_id=REGULATION_ID,
                    actor_id="system:demo-seed",
                    status="completed",
                    original_filename=f"directive-060-v{ordinal}.pdf",
                    media_type="application/pdf",
                    size_bytes=184_320 + ordinal,
                    content_hash=version.content_hash,
                    storage_uri=f"local://demo/directive-060-v{ordinal}.pdf",
                    resulting_version_id=version.id,
                    attempt_count=1,
                    started_at=completed,
                    completed_at=completed,
                )
            )


if __name__ == "__main__":
    seed()
    print("RegImpact reference tenant is ready.")
