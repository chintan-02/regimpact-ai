"""Tenant-scoped control catalogue and obligation mapping endpoints."""

from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .control_mapping import add_control, suggest_mappings
from .database import get_session
from .db_models import ControlRecord, ControlVersionRecord, ObligationControlMappingRecord
from .schemas import (
    ControlCreate,
    ControlMappingListItem,
    ControlResponse,
    MappingResponse,
    MappingSuggestionResponse,
)

router = APIRouter(prefix="/api/v1", tags=["controls"])


def organization_header(x_organization_id: Annotated[UUID, Header()]) -> UUID:
    return x_organization_id


def actor_header(x_actor_id: Annotated[str, Header(min_length=1, max_length=200)]) -> str:
    return x_actor_id


def _latest_control_versions():  # type: ignore[no-untyped-def]
    return (
        select(
            ControlVersionRecord.control_id,
            func.max(ControlVersionRecord.ordinal).label("ordinal"),
        )
        .group_by(ControlVersionRecord.control_id)
        .subquery()
    )


@router.post(
    "/controls",
    response_model=ControlResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or version a control",
)
def create_control(
    body: ControlCreate,
    session: Annotated[Session, Depends(get_session)],
    organization_id: Annotated[UUID, Depends(organization_header)],
) -> ControlResponse:
    with session.begin():
        control, version = add_control(
            session,
            organization_id=organization_id,
            control_key=body.control_key,
            title=body.title,
            description=body.description,
            owner=body.owner,
            evidence_requirement=body.evidence_requirement,
        )
    return ControlResponse(
        id=control.id,
        control_key=control.control_key,
        title=control.title,
        version_id=version.id,
        ordinal=version.ordinal,
        description=version.description,
        owner=version.owner,
        evidence_requirement=version.evidence_requirement,
    )


@router.get("/controls", response_model=list[ControlResponse], summary="List active controls")
def list_controls(
    session: Annotated[Session, Depends(get_session)],
    organization_id: Annotated[UUID, Depends(organization_header)],
) -> list[ControlResponse]:
    latest = _latest_control_versions()
    rows = session.execute(
        select(ControlRecord, ControlVersionRecord)
        .join(ControlVersionRecord, ControlVersionRecord.control_id == ControlRecord.id)
        .join(
            latest,
            (latest.c.control_id == ControlRecord.id)
            & (latest.c.ordinal == ControlVersionRecord.ordinal),
        )
        .where(
            ControlRecord.organization_id == organization_id,
            ControlRecord.active.is_(True),
        )
        .order_by(ControlRecord.control_key)
    ).all()
    return [
        ControlResponse(
            id=control.id,
            control_key=control.control_key,
            title=control.title,
            version_id=version.id,
            ordinal=version.ordinal,
            description=version.description,
            owner=version.owner,
            evidence_requirement=version.evidence_requirement,
        )
        for control, version in rows
    ]


@router.get(
    "/control-mappings",
    response_model=list[ControlMappingListItem],
    summary="List obligation-to-control mappings",
)
def list_control_mappings(
    session: Annotated[Session, Depends(get_session)],
    organization_id: Annotated[UUID, Depends(organization_header)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ControlMappingListItem]:
    rows = session.execute(
        select(ObligationControlMappingRecord, ControlRecord)
        .join(
            ControlVersionRecord,
            ControlVersionRecord.id == ObligationControlMappingRecord.control_version_id,
        )
        .join(ControlRecord, ControlRecord.id == ControlVersionRecord.control_id)
        .where(ObligationControlMappingRecord.organization_id == organization_id)
        .order_by(ObligationControlMappingRecord.score.desc())
        .limit(limit)
    ).all()
    return [
        ControlMappingListItem(
            id=mapping.id,
            obligation_id=mapping.obligation_id,
            control_version_id=mapping.control_version_id,
            control_key=control.control_key,
            control_title=control.title,
            score=float(mapping.score),
            status=mapping.status,
            explanation=json.loads(mapping.explanation_json),
            mapping_method=mapping.mapping_method,
        )
        for mapping, control in rows
    ]


@router.post(
    "/obligations/{obligation_id}/control-mappings/suggest",
    response_model=MappingSuggestionResponse,
    summary="Generate evidence-linked control candidates",
)
def suggest_control_mappings(
    obligation_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    organization_id: Annotated[UUID, Depends(organization_header)],
    actor_id: Annotated[str, Depends(actor_header)],
) -> MappingSuggestionResponse:
    with session.begin():
        records = suggest_mappings(
            session,
            organization_id=organization_id,
            obligation_id=obligation_id,
            actor_id=actor_id,
        )
    mappings = [
        MappingResponse(
            id=record.id,
            obligation_id=record.obligation_id,
            control_version_id=record.control_version_id,
            score=float(record.score),
            status=record.status,
            explanation=json.loads(record.explanation_json),
            mapping_method=record.mapping_method,
        )
        for record in records
    ]
    state = (
        "unmapped"
        if not mappings
        else "ambiguous"
        if any(mapping.status == "ambiguous" for mapping in mappings)
        else "suggested"
    )
    return MappingSuggestionResponse(
        obligation_id=obligation_id,
        state=state,
        mappings=mappings,
    )
