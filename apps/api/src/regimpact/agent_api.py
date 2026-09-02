"""Controlled agent workflow HTTP boundary."""

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_workflow import create_workflow, decide_workflow, latest_decision_revision
from .auth import AdminUser, Authenticated, ReviewerUser
from .database import get_session
from .db_models import AgentWorkflowDecisionRecord, AgentWorkflowRunRecord
from .repository import RegulationNotFoundError
from .schemas import (
    AgentWorkflowCreate,
    AgentWorkflowDecisionCreate,
    AgentWorkflowDecisionResponse,
    AgentWorkflowResponse,
)

router = APIRouter(prefix="/api/v1/agent-workflows", tags=["controlled-agent-workflows"])


def _response(
    session: Session, run: AgentWorkflowRunRecord, *, created: bool = True
) -> AgentWorkflowResponse:
    latest = session.scalar(
        select(AgentWorkflowDecisionRecord)
        .where(AgentWorkflowDecisionRecord.workflow_run_id == run.id)
        .order_by(AgentWorkflowDecisionRecord.revision.desc())
        .limit(1)
    )
    return AgentWorkflowResponse(
        id=run.id,
        obligation_id=run.obligation_id,
        status=run.status,
        risk_level=run.risk_level,
        goal=run.goal,
        plan=json.loads(run.plan_json),
        evidence=json.loads(run.evidence_json),
        proposal=json.loads(run.proposal_json),
        policy_results=json.loads(run.policy_results_json),
        agent_version=run.agent_version,
        evaluation_score=float(run.evaluation_score),
        created_by=run.created_by,
        created_at=run.created_at,
        decided_at=run.decided_at,
        revision=latest_decision_revision(session, run.id),
        latest_decision=(AgentWorkflowDecisionResponse.model_validate(latest) if latest else None),
        created=created,
    )


@router.post("", response_model=AgentWorkflowResponse, status_code=status.HTTP_201_CREATED)
def start_workflow(
    body: AgentWorkflowCreate,
    session: Annotated[Session, Depends(get_session)],
    user: ReviewerUser,
) -> AgentWorkflowResponse:
    with session.begin():
        run, created = create_workflow(
            session,
            organization_id=user.organization_id,
            obligation_id=body.obligation_id,
            goal=body.goal,
            actor_id=user.actor_id,
            idempotency_key=body.idempotency_key,
        )
    return _response(session, run, created=created)


@router.get("", response_model=list[AgentWorkflowResponse])
def list_workflows(
    session: Annotated[Session, Depends(get_session)],
    user: Authenticated,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AgentWorkflowResponse]:
    runs = session.scalars(
        select(AgentWorkflowRunRecord)
        .where(AgentWorkflowRunRecord.organization_id == user.organization_id)
        .order_by(AgentWorkflowRunRecord.created_at.desc())
        .limit(limit)
    ).all()
    return [_response(session, run) for run in runs]


@router.get("/{run_id}", response_model=AgentWorkflowResponse)
def get_workflow(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    user: Authenticated,
) -> AgentWorkflowResponse:
    run = session.scalar(
        select(AgentWorkflowRunRecord).where(
            AgentWorkflowRunRecord.id == run_id,
            AgentWorkflowRunRecord.organization_id == user.organization_id,
        )
    )
    if run is None:
        raise RegulationNotFoundError("workflow run not found")
    return _response(session, run)


@router.post("/{run_id}/decisions", response_model=AgentWorkflowDecisionResponse)
def record_workflow_decision(
    run_id: UUID,
    body: AgentWorkflowDecisionCreate,
    session: Annotated[Session, Depends(get_session)],
    admin: AdminUser,
) -> AgentWorkflowDecisionResponse:
    with session.begin():
        decision = decide_workflow(
            session,
            organization_id=admin.organization_id,
            run_id=run_id,
            decision=body.decision,
            rationale=body.rationale,
            actor_id=admin.actor_id,
            idempotency_key=body.idempotency_key,
            expected_revision=body.expected_revision,
        )
    return AgentWorkflowDecisionResponse.model_validate(decision)
