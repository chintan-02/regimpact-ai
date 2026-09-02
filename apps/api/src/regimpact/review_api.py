"""Analyst review queue and decision endpoints."""

from __future__ import annotations

import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import _obligation_response
from .auth import Authenticated, ReviewerUser
from .database import get_session
from .db_models import (
    ControlRecord,
    ControlVersionRecord,
    ObligationControlMappingRecord,
    ObligationRecord,
    RegulationRecord,
    RegulationVersionRecord,
    SectionRecord,
)
from .repository import RegulationNotFoundError
from .review_workflow import decide_mapping, latest_decisions
from .schemas import (
    ControlMappingListItem,
    MappingDecisionCreate,
    MappingDecisionResponse,
    ReviewCandidate,
    ReviewQueueItem,
    ReviewQueueResponse,
)

router = APIRouter(prefix="/api/v1", tags=["analyst-review"])


def organization_header(user: Authenticated) -> UUID:
    return user.organization_id


def actor_header(user: Authenticated) -> str:
    return user.actor_id


def _decision_response(record):  # type: ignore[no-untyped-def]
    return MappingDecisionResponse(
        id=record.id,
        obligation_id=record.obligation_id,
        mapping_id=record.mapping_id,
        control_version_id=record.control_version_id,
        decision=record.decision,
        rationale=record.rationale,
        actor_id=record.actor_id,
        revision=record.revision,
        supersedes_id=record.supersedes_id,
        decided_at=record.decided_at,
    )


def _review_items(session: Session, organization_id: UUID) -> list[ReviewQueueItem]:
    decisions = latest_decisions(session, organization_id)
    obligation_rows = session.execute(
        select(
            ObligationRecord,
            SectionRecord,
            RegulationVersionRecord,
            RegulationRecord,
        )
        .join(SectionRecord, SectionRecord.id == ObligationRecord.section_id)
        .join(RegulationVersionRecord, RegulationVersionRecord.id == ObligationRecord.version_id)
        .join(RegulationRecord, RegulationRecord.id == ObligationRecord.regulation_id)
        .where(ObligationRecord.organization_id == organization_id)
        .order_by(ObligationRecord.requires_review.desc(), ObligationRecord.confidence)
    ).all()
    mapping_rows = session.execute(
        select(ObligationControlMappingRecord, ControlRecord)
        .join(
            ControlVersionRecord,
            ControlVersionRecord.id == ObligationControlMappingRecord.control_version_id,
        )
        .join(ControlRecord, ControlRecord.id == ControlVersionRecord.control_id)
        .where(ObligationControlMappingRecord.organization_id == organization_id)
        .order_by(ObligationControlMappingRecord.score.desc())
    ).all()
    by_obligation: dict[UUID, list[ReviewCandidate]] = {}
    for mapping, control in mapping_rows:
        decision = decisions.get(mapping.id)
        base = ControlMappingListItem(
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
        by_obligation.setdefault(mapping.obligation_id, []).append(
            ReviewCandidate(
                **base.model_dump(), decision=_decision_response(decision) if decision else None
            )
        )
    items = []
    for obligation, section, version, regulation in obligation_rows:
        candidates = by_obligation.get(obligation.id, [])
        obligation_decision = decisions.get(obligation.id)
        active = [candidate.decision for candidate in candidates if candidate.decision]
        review_state = (
            obligation_decision.decision
            if obligation_decision
            else "accepted"
            if any(item and item.decision == "accepted" for item in active)
            else "deferred"
            if any(item and item.decision == "deferred" for item in active)
            else "superseded"
            if active and all(item and item.decision == "superseded" for item in active)
            else "rejected"
            if candidates
            and len(active) == len(candidates)
            and all(item and item.decision == "rejected" for item in active)
            else "pending"
        )
        revision = max(
            [decision.revision for decision in active if decision]
            + ([obligation_decision.revision] if obligation_decision else [0])
        )
        items.append(
            ReviewQueueItem(
                obligation=_obligation_response(obligation, section, version),
                regulation_key=regulation.source_key,
                regulation_title=regulation.title,
                review_state=review_state,
                candidates=candidates,
                obligation_revision=revision,
            )
        )
    return items


@router.get("/review-queue", response_model=ReviewQueueResponse)
def review_queue(
    session: Annotated[Session, Depends(get_session)],
    organization_id: Annotated[UUID, Depends(organization_header)],
    state: str | None = None,
    regulation_id: UUID | None = None,
    section: Annotated[str | None, Query(max_length=160)] = None,
    control_id: UUID | None = None,
    control_version_id: UUID | None = None,
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    max_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    sort: Literal["confidence_asc", "confidence_desc", "section"] = "confidence_asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReviewQueueResponse:
    items = _review_items(session, organization_id)
    if state:
        items = [item for item in items if item.review_state == state]
    if regulation_id:
        items = [item for item in items if item.obligation.regulation_id == regulation_id]
    if section:
        items = [item for item in items if item.obligation.section_key == section]
    selected_control_version = control_version_id or control_id
    if selected_control_version:
        items = [
            item
            for item in items
            if any(
                candidate.control_version_id == selected_control_version
                for candidate in item.candidates
            )
        ]
    if q:
        search_text = q.casefold().strip()
        items = [
            item
            for item in items
            if search_text
            in " ".join(
                [
                    item.regulation_key,
                    item.regulation_title,
                    item.obligation.section_key,
                    item.obligation.heading,
                    item.obligation.action,
                    item.obligation.evidence_quote,
                    *(candidate.control_key for candidate in item.candidates),
                    *(candidate.control_title for candidate in item.candidates),
                ]
            ).casefold()
        ]
    if min_confidence is not None:
        items = [item for item in items if item.obligation.confidence >= min_confidence]
    if max_confidence is not None:
        items = [item for item in items if item.obligation.confidence <= max_confidence]
    if sort == "confidence_desc":
        items.sort(key=lambda item: item.obligation.confidence, reverse=True)
    elif sort == "section":
        items.sort(key=lambda item: (item.regulation_key, item.obligation.section_key))
    else:
        items.sort(key=lambda item: item.obligation.confidence)
    return ReviewQueueResponse(
        items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset
    )


@router.get("/review-queue/{obligation_id}", response_model=ReviewQueueItem)
def review_detail(
    obligation_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    organization_id: Annotated[UUID, Depends(organization_header)],
) -> ReviewQueueItem:
    item = next(
        (
            item
            for item in _review_items(session, organization_id)
            if item.obligation.id == obligation_id
        ),
        None,
    )
    if item is None:
        raise RegulationNotFoundError("review item not found")
    return item


@router.post(
    "/obligations/{obligation_id}/mapping-decisions",
    response_model=MappingDecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_decision(
    obligation_id: UUID,
    body: MappingDecisionCreate,
    session: Annotated[Session, Depends(get_session)],
    organization_id: Annotated[UUID, Depends(organization_header)],
    actor_id: Annotated[str, Depends(actor_header)],
    _reviewer: ReviewerUser,
    mapping_id: UUID | None = None,
) -> MappingDecisionResponse:
    with session.begin():
        record = decide_mapping(
            session,
            organization_id=organization_id,
            obligation_id=obligation_id,
            mapping_id=mapping_id,
            decision=body.decision,
            rationale=body.rationale,
            actor_id=actor_id,
            idempotency_key=body.idempotency_key,
            expected_revision=body.expected_revision,
        )
    return _decision_response(record)
