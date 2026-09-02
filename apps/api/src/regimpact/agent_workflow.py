"""Fail-closed, evidence-grounded regulatory impact workflow."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db_models import (
    AgentWorkflowDecisionRecord,
    AgentWorkflowRunRecord,
    AuditEventRecord,
    ControlRecord,
    ControlVersionRecord,
    ObligationControlMappingRecord,
    ObligationRecord,
    RegulationVersionRecord,
    SectionRecord,
)
from .domain import utc_now
from .repository import RegulationNotFoundError
from .review_workflow import ReviewConflictError

AGENT_VERSION = "controlled-impact-v1"
DECISIONS = {"approved", "rejected", "changes_requested"}


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def create_workflow(
    session: Session,
    *,
    organization_id: UUID,
    obligation_id: UUID,
    goal: str,
    actor_id: str,
    idempotency_key: str,
) -> tuple[AgentWorkflowRunRecord, bool]:
    existing = session.scalar(
        select(AgentWorkflowRunRecord).where(
            AgentWorkflowRunRecord.organization_id == organization_id,
            AgentWorkflowRunRecord.idempotency_key == idempotency_key,
        )
    )
    if existing:
        return existing, False
    row = session.execute(
        select(ObligationRecord, SectionRecord, RegulationVersionRecord)
        .join(SectionRecord, SectionRecord.id == ObligationRecord.section_id)
        .join(RegulationVersionRecord, RegulationVersionRecord.id == ObligationRecord.version_id)
        .where(
            ObligationRecord.id == obligation_id,
            ObligationRecord.organization_id == organization_id,
        )
    ).one_or_none()
    if row is None:
        raise RegulationNotFoundError("obligation not found")
    obligation, section, version = row
    mappings = session.execute(
        select(ObligationControlMappingRecord, ControlRecord, ControlVersionRecord)
        .join(
            ControlVersionRecord,
            ControlVersionRecord.id == ObligationControlMappingRecord.control_version_id,
        )
        .join(ControlRecord, ControlRecord.id == ControlVersionRecord.control_id)
        .where(
            ObligationControlMappingRecord.organization_id == organization_id,
            ObligationControlMappingRecord.obligation_id == obligation_id,
        )
        .order_by(ObligationControlMappingRecord.score.desc())
        .limit(3)
    ).all()
    evidence = {
        "obligation_id": str(obligation.id),
        "version_id": str(version.id),
        "version_ordinal": version.ordinal,
        "section_id": str(section.id),
        "section_key": section.section_key,
        "page": obligation.page,
        "source_uri": version.source_uri,
        "quote": obligation.evidence_quote,
        "content_hash": version.content_hash,
    }
    controls = [
        {
            "mapping_id": str(mapping.id),
            "control_version_id": str(control_version.id),
            "control_key": control.control_key,
            "title": control.title,
            "score": float(mapping.score),
            "owner": control_version.owner,
            "evidence_requirement": control_version.evidence_requirement,
        }
        for mapping, control, control_version in mappings
    ]
    confidence = float(obligation.confidence)
    policy_results = {
        "tenant_scope": True,
        "citation_complete": bool(obligation.evidence_quote and version.source_uri),
        "human_approval_required": True,
        "automatic_execution_disabled": True,
        "confidence_gate": confidence >= 0.70,
        "control_candidates_present": bool(controls),
    }
    score = sum(int(value) for value in policy_results.values() if isinstance(value, bool)) / len(
        policy_results
    )
    blocked = not all(
        policy_results[key]
        for key in (
            "tenant_scope",
            "citation_complete",
            "confidence_gate",
            "control_candidates_present",
        )
    )
    risk_level = "high" if obligation.modality in {"must", "must_not"} else "medium"
    proposal = {
        "summary": f"Assess control impact for {section.section_key}: {obligation.action}",
        "recommended_actions": [
            {
                "action": "validate_control_coverage",
                "control_key": item["control_key"],
                "owner": item["owner"],
                "requires_human_approval": True,
            }
            for item in controls
        ],
        "limitations": [
            "No external action has been executed.",
            "A human must verify the cited evidence and proposed control impact.",
        ],
    }
    record = AgentWorkflowRunRecord(
        organization_id=organization_id,
        obligation_id=obligation_id,
        status="blocked" if blocked else "awaiting_approval",
        risk_level=risk_level,
        goal=goal.strip(),
        plan_json=_json(
            {
                "steps": [
                    "collect_versioned_evidence",
                    "assess_obligation_impact",
                    "rank_control_candidates",
                    "evaluate_policy_gates",
                    "request_human_approval",
                ]
            }
        ),
        evidence_json=_json(evidence),
        proposal_json=_json(proposal),
        policy_results_json=_json(policy_results),
        agent_version=AGENT_VERSION,
        evaluation_score=Decimal(str(round(score, 3))),
        created_by=actor_id,
        idempotency_key=idempotency_key,
    )
    session.add(record)
    session.flush()
    session.add(
        AuditEventRecord(
            organization_id=organization_id,
            actor_id=actor_id,
            event_type=f"agent_workflow.{record.status}",
            entity_type="agent_workflow_run",
            entity_id=record.id,
            detail_json=_json(
                {"obligation_id": str(obligation_id), "agent_version": AGENT_VERSION}
            ),
        )
    )
    return record, True


def decide_workflow(
    session: Session,
    *,
    organization_id: UUID,
    run_id: UUID,
    decision: str,
    rationale: str,
    actor_id: str,
    idempotency_key: str,
    expected_revision: int,
) -> AgentWorkflowDecisionRecord:
    if decision not in DECISIONS:
        raise ValueError("unsupported workflow decision")
    run = session.scalar(
        select(AgentWorkflowRunRecord)
        .where(
            AgentWorkflowRunRecord.id == run_id,
            AgentWorkflowRunRecord.organization_id == organization_id,
        )
        .with_for_update()
    )
    if run is None:
        raise RegulationNotFoundError("workflow run not found")
    if run.status == "blocked" and decision == "approved":
        raise ValueError("a policy-blocked workflow cannot be approved")
    if run.created_by == actor_id and run.risk_level == "high" and decision == "approved":
        raise ValueError("high-risk workflows require a different human approver")
    existing = session.scalar(
        select(AgentWorkflowDecisionRecord).where(
            AgentWorkflowDecisionRecord.organization_id == organization_id,
            AgentWorkflowDecisionRecord.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if existing.workflow_run_id != run_id:
            raise ReviewConflictError("idempotency key belongs to another workflow")
        return existing
    current = session.scalar(
        select(AgentWorkflowDecisionRecord)
        .where(AgentWorkflowDecisionRecord.workflow_run_id == run_id)
        .order_by(AgentWorkflowDecisionRecord.revision.desc())
        .limit(1)
    )
    revision = current.revision if current else 0
    if revision != expected_revision:
        raise ReviewConflictError(
            f"stale workflow revision: expected {expected_revision}, current {revision}"
        )
    record = AgentWorkflowDecisionRecord(
        organization_id=organization_id,
        workflow_run_id=run_id,
        decision=decision,
        rationale=rationale.strip(),
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        revision=revision + 1,
        supersedes_id=current.id if current else None,
    )
    session.add(record)
    session.flush()
    run.status = decision
    run.decided_at = utc_now()
    session.add(
        AuditEventRecord(
            organization_id=organization_id,
            actor_id=actor_id,
            event_type=f"agent_workflow.{decision}",
            entity_type="agent_workflow_decision",
            entity_id=record.id,
            detail_json=_json({"workflow_run_id": str(run_id), "revision": record.revision}),
        )
    )
    return record


def latest_decision_revision(session: Session, run_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.max(AgentWorkflowDecisionRecord.revision), 0)).where(
                AgentWorkflowDecisionRecord.workflow_run_id == run_id
            )
        )
        or 0
    )
