"""v1 regulation, change and obligation endpoints."""

import json
from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from .auth import AdminUser, Authenticated
from .calibration import CURRENT_POLICY
from .classifier_runtime import (
    TransformerClauseClassifier,
    UnpromotedModelError,
    load_promoted_classifier,
)
from .clause_classification_service import classify_and_store_clauses
from .config import get_settings
from .database import get_session
from .db_models import (
    ClauseClassificationRecord,
    IngestionJobRecord,
    ObligationRecord,
    OutboxEventRecord,
    RegulationRecord,
    RegulationVersionRecord,
    RegulatorySourceRecord,
    SectionChangeRecord,
    SectionRecord,
)
from .domain import Section, utc_now
from .embeddings import configured_embedding_provider
from .ingestion import DevelopmentAllowScanner, MalwareScanner, UnavailableScanner, validate_upload
from .ingestion_service import queue_ingestion, replay_dead_letter
from .obligation_service import extract_and_store_obligations
from .repository import RegulationNotFoundError, SqlAlchemyVersionRepository, create_regulation
from .retrieval import hybrid_search, index_version
from .schemas import (
    CalibrationBinResponse,
    CalibrationPolicyResponse,
    ChangeDetail,
    ChangeRegisterItem,
    ChangeResponse,
    CitationResponse,
    ClauseClassificationResponse,
    ClauseClassificationRunResponse,
    HybridSearchResponse,
    IngestionJobResponse,
    IngestionJobState,
    ObligationExtractionResponse,
    ObligationResponse,
    OrganizationCreate,
    OrganizationResponse,
    RegulationCreate,
    RegulationListItem,
    RegulationResponse,
    RegulatorySourceCreate,
    RegulatorySourceResponse,
    RetrievalHitResponse,
    SearchIndexResponse,
    VersionCreate,
    VersionResponse,
    VersionSummary,
)
from .source_client import system_resolver, validate_source_url
from .storage import ObjectStorage, configured_object_storage
from .versioning import VersioningService

router = APIRouter(prefix="/api/v1", tags=["regulations"])
DbSession = Annotated[Session, Depends(get_session)]


def organization_header(user: Authenticated) -> UUID:
    return user.organization_id


def actor_header(user: Authenticated) -> str:
    return user.actor_id


def object_storage() -> ObjectStorage:
    return configured_object_storage(get_settings())


def clause_classifier() -> TransformerClauseClassifier:
    settings = get_settings()
    if settings.clause_classifier_mode != "transformer":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="clause classifier is disabled; deterministic extraction remains active",
        )
    try:
        return load_promoted_classifier(settings.clause_classifier_artifact_dir)
    except (OSError, ValueError, KeyError, UnpromotedModelError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"clause classifier unavailable: {exc}",
        ) from exc


def malware_scanner() -> MalwareScanner:
    settings = get_settings()
    if settings.environment == "local" and settings.malware_scanner_mode == "development_allow":
        return DevelopmentAllowScanner()
    return UnavailableScanner()


@router.post(
    "/organizations", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED
)
def add_organization(
    body: OrganizationCreate, session: DbSession, _admin: AdminUser
) -> OrganizationResponse:
    del body, session
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Organization provisioning is restricted to platform operations.",
    )


@router.post("/regulations", response_model=RegulationResponse, status_code=status.HTTP_201_CREATED)
def add_regulation(
    body: RegulationCreate,
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    _admin: AdminUser,
) -> RegulationResponse:
    with session.begin():
        record = create_regulation(
            session,
            organization_id=organization_id,
            source_key=body.source_key,
            title=body.title,
            jurisdiction=body.jurisdiction,
        )
    return RegulationResponse.model_validate(record)


@router.get("/regulations", response_model=list[RegulationListItem])
def list_regulations(
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
) -> list[RegulationListItem]:
    latest = (
        select(
            RegulationVersionRecord.regulation_id.label("regulation_id"),
            func.max(RegulationVersionRecord.ordinal).label("latest_ordinal"),
            func.max(RegulationVersionRecord.ingested_at).label("latest_ingested_at"),
        )
        .group_by(RegulationVersionRecord.regulation_id)
        .subquery()
    )
    changes = (
        select(
            SectionChangeRecord.regulation_id.label("regulation_id"),
            func.count(SectionChangeRecord.id).label("total_changes"),
        )
        .group_by(SectionChangeRecord.regulation_id)
        .subquery()
    )
    sources = (
        select(
            RegulatorySourceRecord.regulation_id.label("regulation_id"),
            func.count(RegulatorySourceRecord.id).label("monitored_sources"),
        )
        .where(RegulatorySourceRecord.enabled.is_(True))
        .group_by(RegulatorySourceRecord.regulation_id)
        .subquery()
    )
    rows = session.execute(
        select(
            RegulationRecord,
            latest.c.latest_ordinal,
            latest.c.latest_ingested_at,
            func.coalesce(changes.c.total_changes, 0),
            func.coalesce(sources.c.monitored_sources, 0),
        )
        .outerjoin(latest, latest.c.regulation_id == RegulationRecord.id)
        .outerjoin(changes, changes.c.regulation_id == RegulationRecord.id)
        .outerjoin(sources, sources.c.regulation_id == RegulationRecord.id)
        .where(RegulationRecord.organization_id == organization_id)
        .order_by(RegulationRecord.title)
    ).all()
    return [
        RegulationListItem(
            **RegulationResponse.model_validate(record).model_dump(),
            latest_version_ordinal=latest_ordinal,
            latest_ingested_at=latest_ingested_at,
            total_changes=total_changes,
            monitored_sources=monitored_sources,
        )
        for record, latest_ordinal, latest_ingested_at, total_changes, monitored_sources in rows
    ]


@router.post(
    "/regulations/{regulation_id}/versions",
    response_model=VersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_version(
    regulation_id: UUID,
    body: VersionCreate,
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    actor_id: Annotated[str, Depends(actor_header)],
    _admin: AdminUser,
) -> VersionResponse:
    with session.begin():
        repository = SqlAlchemyVersionRepository(session, organization_id, actor_id)
        result = VersioningService(repository).ingest(
            regulation_id=regulation_id,
            source_uri=str(body.source_uri),
            raw_content=body.raw_content,
            effective_date=body.effective_date,
            sections=tuple(
                Section(key=s.key, heading=s.heading, text=s.text, page=s.page)
                for s in body.sections
            ),
        )
    return VersionResponse(
        id=result.version.id,
        regulation_id=result.version.regulation_id,
        ordinal=result.version.ordinal,
        content_hash=result.version.hash,
        created=result.created,
        change_count=len(result.changes),
        changes=[
            ChangeResponse(
                section_key=c.section_key,
                heading=c.heading,
                change_type=c.change_type.value,
                previous_page=c.previous_page,
                current_page=c.current_page,
            )
            for c in result.changes
        ],
    )


@router.get("/regulations/{regulation_id}/versions", response_model=list[VersionSummary])
def list_versions(
    regulation_id: UUID,
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
) -> list[VersionSummary]:
    SqlAlchemyVersionRepository(session, organization_id, "system:read").owned_regulation(
        regulation_id
    )
    section_counts = (
        select(SectionRecord.version_id, func.count(SectionRecord.id).label("count"))
        .group_by(SectionRecord.version_id)
        .subquery()
    )
    change_counts = (
        select(
            SectionChangeRecord.current_version_id.label("version_id"),
            func.count(SectionChangeRecord.id).label("count"),
        )
        .group_by(SectionChangeRecord.current_version_id)
        .subquery()
    )
    rows = session.execute(
        select(
            RegulationVersionRecord,
            func.coalesce(section_counts.c.count, 0),
            func.coalesce(change_counts.c.count, 0),
        )
        .outerjoin(section_counts, section_counts.c.version_id == RegulationVersionRecord.id)
        .outerjoin(change_counts, change_counts.c.version_id == RegulationVersionRecord.id)
        .where(RegulationVersionRecord.regulation_id == regulation_id)
        .order_by(RegulationVersionRecord.ordinal.desc())
    ).all()
    return [
        VersionSummary(
            id=version.id,
            regulation_id=version.regulation_id,
            ordinal=version.ordinal,
            content_hash=version.content_hash,
            effective_date=version.effective_date,
            source_uri=version.source_uri,
            ingested_at=version.ingested_at,
            section_count=section_count,
            change_count=change_count,
        )
        for version, section_count, change_count in rows
    ]


@router.get("/changes", response_model=list[ChangeRegisterItem])
def list_changes(
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    regulation_id: UUID | None = None,
    latest_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ChangeRegisterItem]:
    current = aliased(RegulationVersionRecord)
    previous = aliased(RegulationVersionRecord)
    latest = (
        select(
            RegulationVersionRecord.regulation_id.label("regulation_id"),
            func.max(RegulationVersionRecord.ordinal).label("ordinal"),
        )
        .group_by(RegulationVersionRecord.regulation_id)
        .subquery()
    )
    statement = (
        select(SectionChangeRecord, RegulationRecord, current, previous)
        .join(RegulationRecord, RegulationRecord.id == SectionChangeRecord.regulation_id)
        .join(current, current.id == SectionChangeRecord.current_version_id)
        .outerjoin(previous, previous.id == SectionChangeRecord.previous_version_id)
        .where(RegulationRecord.organization_id == organization_id)
        .order_by(current.ingested_at.desc(), SectionChangeRecord.section_key)
        .limit(limit)
        .offset(offset)
    )
    if regulation_id:
        statement = statement.where(RegulationRecord.id == regulation_id)
    if latest_only:
        statement = statement.join(
            latest,
            (latest.c.regulation_id == current.regulation_id)
            & (latest.c.ordinal == current.ordinal),
        )
    rows = session.execute(statement).all()
    return [
        _change_register_item(change, regulation, current_version, previous_version)
        for change, regulation, current_version, previous_version in rows
    ]


@router.get("/changes/{change_id}", response_model=ChangeDetail)
def get_change(
    change_id: UUID,
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
) -> ChangeDetail:
    current = aliased(RegulationVersionRecord)
    previous = aliased(RegulationVersionRecord)
    row = session.execute(
        select(SectionChangeRecord, RegulationRecord, current, previous)
        .join(RegulationRecord, RegulationRecord.id == SectionChangeRecord.regulation_id)
        .join(current, current.id == SectionChangeRecord.current_version_id)
        .outerjoin(previous, previous.id == SectionChangeRecord.previous_version_id)
        .where(
            SectionChangeRecord.id == change_id,
            RegulationRecord.organization_id == organization_id,
        )
    ).one_or_none()
    if row is None:
        raise RegulationNotFoundError("change not found")
    change, regulation, current_version, previous_version = row
    base = _change_register_item(change, regulation, current_version, previous_version)
    return ChangeDetail(
        **base.model_dump(),
        previous_text=change.previous_text,
        current_text=change.current_text,
        previous_citation=(
            CitationResponse(
                version_id=previous_version.id,
                version_ordinal=previous_version.ordinal,
                page=change.previous_page,
                source_uri=previous_version.source_uri,
            )
            if previous_version
            else None
        ),
        current_citation=CitationResponse(
            version_id=current_version.id,
            version_ordinal=current_version.ordinal,
            page=change.current_page,
            source_uri=current_version.source_uri,
        ),
    )


def _change_register_item(
    change: SectionChangeRecord,
    regulation: RegulationRecord,
    current: RegulationVersionRecord,
    previous: RegulationVersionRecord | None,
) -> ChangeRegisterItem:
    return ChangeRegisterItem(
        id=change.id,
        regulation_id=regulation.id,
        source_key=regulation.source_key,
        regulation_title=regulation.title,
        jurisdiction=regulation.jurisdiction,
        section_key=change.section_key,
        heading=change.heading,
        change_type=change.change_type,
        previous_version_ordinal=previous.ordinal if previous else None,
        current_version_ordinal=current.ordinal,
        previous_page=change.previous_page,
        current_page=change.current_page,
        detected_at=current.ingested_at,
    )


@router.post(
    "/regulations/{regulation_id}/ingestions",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_regulation_document(
    regulation_id: UUID,
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    actor_id: Annotated[str, Depends(actor_header)],
    _admin: AdminUser,
    upload: Annotated[UploadFile, File(description="Signature-verified PDF or HTML")],
) -> IngestionJobResponse:
    settings = get_settings()
    content = await upload.read(settings.max_upload_bytes + 1)
    await upload.close()
    document = validate_upload(
        filename=upload.filename or "",
        declared_media_type=upload.content_type,
        content=content,
        max_bytes=settings.max_upload_bytes,
        scanner=malware_scanner(),
    )
    with session.begin():
        job, created = queue_ingestion(
            session,
            organization_id=organization_id,
            regulation_id=regulation_id,
            actor_id=actor_id,
            document=document,
            storage=object_storage(),
            max_attempts=settings.ingestion_max_attempts,
        )
    response = IngestionJobResponse.model_validate(job)
    return response.model_copy(update={"created": created})


@router.get("/ingestions/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job(
    job_id: UUID,
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
) -> IngestionJobResponse:
    job = session.scalar(
        select(IngestionJobRecord).where(
            IngestionJobRecord.id == job_id,
            IngestionJobRecord.organization_id == organization_id,
        )
    )
    if job is None:
        raise RegulationNotFoundError("ingestion job not found")
    return IngestionJobResponse.model_validate(job)


@router.get("/ingestions", response_model=list[IngestionJobState])
def list_ingestions(
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[IngestionJobState]:
    jobs = session.scalars(
        select(IngestionJobRecord)
        .where(IngestionJobRecord.organization_id == organization_id)
        .order_by(IngestionJobRecord.created_at.desc())
        .limit(limit)
    ).all()
    return [IngestionJobState.model_validate(job) for job in jobs]


@router.post("/ingestions/{job_id}/replay", response_model=IngestionJobState)
def replay_ingestion(
    job_id: UUID,
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    actor_id: Annotated[str, Depends(actor_header)],
    _admin: AdminUser,
) -> IngestionJobState:
    with session.begin():
        job = session.scalar(
            select(IngestionJobRecord)
            .where(
                IngestionJobRecord.id == job_id,
                IngestionJobRecord.organization_id == organization_id,
            )
            .with_for_update()
        )
        if job is None:
            raise RegulationNotFoundError("ingestion job not found")
        try:
            replay_dead_letter(session, job=job, actor_id=actor_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return IngestionJobState.model_validate(job)


@router.post(
    "/sources", response_model=RegulatorySourceResponse, status_code=status.HTTP_201_CREATED
)
def add_regulatory_source(
    body: RegulatorySourceCreate,
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    _admin: AdminUser,
) -> RegulatorySourceResponse:
    settings = get_settings()
    url = str(body.url)
    host = validate_source_url(
        url, allowed_hosts=settings.allowed_source_domains, resolver=system_resolver
    )
    with session.begin():
        SqlAlchemyVersionRepository(
            session, organization_id, "system:source-config"
        ).owned_regulation(body.regulation_id)
        record = RegulatorySourceRecord(
            organization_id=organization_id,
            regulation_id=body.regulation_id,
            name=body.name,
            url=url,
            allowed_host=host,
            poll_interval_minutes=body.poll_interval_minutes,
            next_check_at=utc_now(),
        )
        session.add(record)
    return RegulatorySourceResponse.model_validate(record)


@router.get("/sources", response_model=list[RegulatorySourceResponse])
def list_regulatory_sources(
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
) -> list[RegulatorySourceResponse]:
    sources = session.scalars(
        select(RegulatorySourceRecord)
        .where(RegulatorySourceRecord.organization_id == organization_id)
        .order_by(RegulatorySourceRecord.name)
    ).all()
    return [RegulatorySourceResponse.model_validate(source) for source in sources]


@router.get("/system/queue-health")
def queue_health(
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
) -> dict[str, int]:
    pending_outbox = session.scalar(
        select(func.count())
        .select_from(OutboxEventRecord)
        .where(
            OutboxEventRecord.organization_id == organization_id,
            OutboxEventRecord.published_at.is_(None),
            OutboxEventRecord.dead_lettered_at.is_(None),
        )
    )
    exhausted_outbox = session.scalar(
        select(func.count())
        .select_from(OutboxEventRecord)
        .where(
            OutboxEventRecord.organization_id == organization_id,
            OutboxEventRecord.published_at.is_(None),
            OutboxEventRecord.dead_lettered_at.is_not(None),
        )
    )
    dead_letters = session.scalar(
        select(func.count())
        .select_from(IngestionJobRecord)
        .where(
            IngestionJobRecord.organization_id == organization_id,
            IngestionJobRecord.status == "dead_letter",
        )
    )
    return {
        "pending_outbox": int(pending_outbox or 0),
        "exhausted_outbox": int(exhausted_outbox or 0),
        "dead_letter_ingestions": int(dead_letters or 0),
    }


def _obligation_response(
    obligation: ObligationRecord,
    section: SectionRecord,
    version: RegulationVersionRecord,
) -> ObligationResponse:
    return ObligationResponse(
        id=obligation.id,
        regulation_id=obligation.regulation_id,
        version_id=obligation.version_id,
        section_id=obligation.section_id,
        section_key=section.section_key,
        heading=section.heading,
        text=obligation.text,
        evidence_quote=obligation.evidence_quote,
        subject=obligation.subject,
        action=obligation.action,
        modality=obligation.modality,
        deadline_text=obligation.deadline_text,
        raw_confidence=float(obligation.raw_confidence),
        confidence=float(obligation.confidence),
        calibration_policy_id=obligation.calibration_policy_id,
        requires_review=obligation.requires_review,
        status=obligation.status,
        extraction_method=obligation.extraction_method,
        rule_ids=json.loads(obligation.rule_ids_json),
        page=obligation.page,
        source_uri=version.source_uri,
        version_ordinal=version.ordinal,
        created_at=obligation.created_at,
    )


def _clause_classification_response(
    classification: ClauseClassificationRecord,
    section: SectionRecord,
    version: RegulationVersionRecord,
) -> ClauseClassificationResponse:
    return ClauseClassificationResponse(
        id=classification.id,
        regulation_id=classification.regulation_id,
        version_id=classification.version_id,
        section_id=classification.section_id,
        section_key=section.section_key,
        heading=section.heading,
        text=classification.text,
        label=classification.label,
        confidence=float(classification.confidence),
        abstained=classification.abstained,
        status=classification.status,
        model_id=classification.model_id,
        dataset_id=classification.dataset_id,
        dataset_sha256=classification.dataset_sha256,
        probabilities=json.loads(classification.probabilities_json),
        page=classification.page,
        source_uri=version.source_uri,
        version_ordinal=version.ordinal,
        created_at=classification.created_at,
    )


def _classification_responses_for_records(
    session: Session,
    *,
    organization_id: UUID,
    records: tuple[ClauseClassificationRecord, ...],
) -> list[ClauseClassificationResponse]:
    """Serialize exactly one classification run without pagination or history mixing."""
    record_ids = tuple(record.id for record in records)
    if not record_ids:
        return []
    statement = (
        select(ClauseClassificationRecord, SectionRecord, RegulationVersionRecord)
        .join(SectionRecord, SectionRecord.id == ClauseClassificationRecord.section_id)
        .join(
            RegulationVersionRecord,
            RegulationVersionRecord.id == ClauseClassificationRecord.version_id,
        )
        .join(RegulationRecord, RegulationRecord.id == ClauseClassificationRecord.regulation_id)
        .where(
            RegulationRecord.organization_id == organization_id,
            ClauseClassificationRecord.id.in_(record_ids),
        )
        .order_by(SectionRecord.position, ClauseClassificationRecord.id)
    )
    return [
        _clause_classification_response(classification, section, version)
        for classification, section, version in session.execute(statement).all()
    ]


@router.post(
    "/versions/{version_id}/obligations/extract",
    response_model=ObligationExtractionResponse,
)
def extract_version_obligations(
    version_id: UUID,
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    actor_id: Annotated[str, Depends(actor_header)],
    _admin: AdminUser,
) -> ObligationExtractionResponse:
    with session.begin():
        result = extract_and_store_obligations(
            session,
            organization_id=organization_id,
            version_id=version_id,
            actor_id=actor_id,
        )
    obligations = list_obligations(
        session=session,
        organization_id=organization_id,
        regulation_id=None,
        version_id=version_id,
        status_filter=None,
        limit=500,
        offset=0,
    )
    return ObligationExtractionResponse(
        version_id=result.version_id,
        created_count=result.created_count,
        existing_count=result.existing_count,
        obligations=obligations,
    )


@router.get("/obligations", response_model=list[ObligationResponse])
def list_obligations(
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    regulation_id: UUID | None = None,
    version_id: UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=30)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ObligationResponse]:
    statement = (
        select(ObligationRecord, SectionRecord, RegulationVersionRecord)
        .join(SectionRecord, SectionRecord.id == ObligationRecord.section_id)
        .join(RegulationVersionRecord, RegulationVersionRecord.id == ObligationRecord.version_id)
        .join(RegulationRecord, RegulationRecord.id == ObligationRecord.regulation_id)
        .where(RegulationRecord.organization_id == organization_id)
        .order_by(
            RegulationVersionRecord.ordinal.desc(), SectionRecord.position, ObligationRecord.id
        )
        .limit(limit)
        .offset(offset)
    )
    if regulation_id:
        statement = statement.where(ObligationRecord.regulation_id == regulation_id)
    if version_id:
        statement = statement.where(ObligationRecord.version_id == version_id)
    if status_filter:
        statement = statement.where(ObligationRecord.status == status_filter)
    return [
        _obligation_response(obligation, section, version)
        for obligation, section, version in session.execute(statement).all()
    ]


@router.post(
    "/versions/{version_id}/clauses/classify",
    response_model=ClauseClassificationRunResponse,
)
def classify_version_clauses(
    version_id: UUID,
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    actor_id: Annotated[str, Depends(actor_header)],
    classifier: Annotated[TransformerClauseClassifier, Depends(clause_classifier)],
    _admin: AdminUser,
) -> ClauseClassificationRunResponse:
    with session.begin():
        result = classify_and_store_clauses(
            session,
            organization_id=organization_id,
            version_id=version_id,
            actor_id=actor_id,
            classifier=classifier,
        )
    classifications = _classification_responses_for_records(
        session=session,
        organization_id=organization_id,
        records=result.classifications,
    )
    return ClauseClassificationRunResponse(
        version_id=result.version_id,
        created_count=result.created_count,
        existing_count=result.existing_count,
        abstained_count=result.abstained_count,
        classifications=classifications,
    )


@router.get("/clause-classifications", response_model=list[ClauseClassificationResponse])
def list_clause_classifications(
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    version_id: UUID | None = None,
    model_id: Annotated[str | None, Query(max_length=240)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=30)] = None,
    limit: Annotated[int, Query(ge=1, le=2_000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ClauseClassificationResponse]:
    statement = (
        select(ClauseClassificationRecord, SectionRecord, RegulationVersionRecord)
        .join(SectionRecord, SectionRecord.id == ClauseClassificationRecord.section_id)
        .join(
            RegulationVersionRecord,
            RegulationVersionRecord.id == ClauseClassificationRecord.version_id,
        )
        .join(RegulationRecord, RegulationRecord.id == ClauseClassificationRecord.regulation_id)
        .where(RegulationRecord.organization_id == organization_id)
        .order_by(
            RegulationVersionRecord.ordinal.desc(),
            SectionRecord.position,
            ClauseClassificationRecord.id,
        )
        .limit(limit)
        .offset(offset)
    )
    if version_id:
        statement = statement.where(ClauseClassificationRecord.version_id == version_id)
    if model_id:
        statement = statement.where(ClauseClassificationRecord.model_id == model_id)
    if status_filter:
        statement = statement.where(ClauseClassificationRecord.status == status_filter)
    return [
        _clause_classification_response(classification, section, version)
        for classification, section, version in session.execute(statement).all()
    ]


@router.get("/system/calibration-policy", response_model=CalibrationPolicyResponse)
def calibration_policy() -> CalibrationPolicyResponse:
    return CalibrationPolicyResponse(
        policy_id=CURRENT_POLICY.policy_id,
        dataset_id=CURRENT_POLICY.dataset_id,
        dataset_size=CURRENT_POLICY.dataset_size,
        calibration_candidate_count=CURRENT_POLICY.calibration_candidate_count,
        review_threshold=CURRENT_POLICY.review_threshold,
        minimum_precision=CURRENT_POLICY.minimum_precision,
        bins=[
            CalibrationBinResponse(
                upper_bound=item.upper_bound,
                calibrated_confidence=item.calibrated_confidence,
                training_count=item.training_count,
            )
            for item in CURRENT_POLICY.bins
        ],
    )


@router.post("/versions/{version_id}/search-index", response_model=SearchIndexResponse)
def create_search_index(
    version_id: UUID,
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    _admin: AdminUser,
) -> SearchIndexResponse:
    settings = get_settings()
    provider = configured_embedding_provider(
        environment=settings.environment,
        provider_name=settings.embedding_provider,
        model_name=settings.embedding_model,
    )
    with session.begin():
        created, existing = index_version(
            session, organization_id=organization_id, version_id=version_id, provider=provider
        )
    return SearchIndexResponse(
        version_id=version_id,
        created_count=created,
        existing_count=existing,
        embedding_model_id=provider.model_id,
    )


@router.get("/search", response_model=HybridSearchResponse)
def search_regulatory_evidence(
    session: DbSession,
    organization_id: Annotated[UUID, Depends(organization_header)],
    q: Annotated[str, Query(min_length=2, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> HybridSearchResponse:
    settings = get_settings()
    provider = configured_embedding_provider(
        environment=settings.environment,
        provider_name=settings.embedding_provider,
        model_name=settings.embedding_model,
    )
    hits = hybrid_search(
        session,
        organization_id=organization_id,
        query=q,
        provider=provider,
        limit=limit,
    )
    return HybridSearchResponse(
        query=q,
        result_count=len(hits),
        results=[RetrievalHitResponse(**asdict(hit)) for hit in hits],
    )
