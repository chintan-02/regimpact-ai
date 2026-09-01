"""Versioned control catalogue and evidence-linked mapping suggestions."""

import json
import re
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db_models import (
    AuditEventRecord,
    ControlRecord,
    ControlVersionRecord,
    ObligationControlMappingRecord,
    ObligationRecord,
)
from .repository import RegulationNotFoundError

METHOD = "token-overlap-v1"
TOKEN = re.compile(r"[a-z0-9]+")
EXPLANATION_STOPWORDS = frozenset(
    {"a", "an", "and", "for", "in", "of", "on", "or", "the", "to", "with"}
)


def add_control(
    session: Session,
    *,
    organization_id: UUID,
    control_key: str,
    title: str,
    description: str,
    owner: str,
    evidence_requirement: str,
) -> tuple[ControlRecord, ControlVersionRecord]:
    control = session.scalar(
        select(ControlRecord).where(
            ControlRecord.organization_id == organization_id,
            ControlRecord.control_key == control_key,
        )
    )
    if control is None:
        control = ControlRecord(
            organization_id=organization_id, control_key=control_key, title=title
        )
        session.add(control)
        session.flush()
    latest = (
        session.scalar(
            select(func.max(ControlVersionRecord.ordinal)).where(
                ControlVersionRecord.control_id == control.id
            )
        )
        or 0
    )
    body = f"{description}|{owner}|{evidence_requirement}"
    digest = sha256(body.encode()).hexdigest()
    existing = session.scalar(
        select(ControlVersionRecord).where(
            ControlVersionRecord.control_id == control.id,
            ControlVersionRecord.content_hash == digest,
        )
    )
    if existing:
        return control, existing
    previous = (
        session.scalar(
            select(ControlVersionRecord).where(
                ControlVersionRecord.control_id == control.id,
                ControlVersionRecord.ordinal == latest,
            )
        )
        if latest
        else None
    )
    version = ControlVersionRecord(
        control_id=control.id,
        ordinal=latest + 1,
        description=description,
        owner=owner,
        evidence_requirement=evidence_requirement,
        content_hash=digest,
    )
    session.add(version)
    session.flush()
    if previous:
        from .review_workflow import supersede_control_version_decisions

        supersede_control_version_decisions(
            session,
            organization_id=organization_id,
            control_version_id=previous.id,
        )
    return control, version


def suggest_mappings(
    session: Session, *, organization_id: UUID, obligation_id: UUID, actor_id: str, limit: int = 3
) -> list[ObligationControlMappingRecord]:
    obligation = session.scalar(
        select(ObligationRecord).where(
            ObligationRecord.id == obligation_id,
            ObligationRecord.organization_id == organization_id,
        )
    )
    if obligation is None:
        raise RegulationNotFoundError("obligation not found")
    existing = session.scalars(
        select(ObligationControlMappingRecord)
        .where(
            ObligationControlMappingRecord.organization_id == organization_id,
            ObligationControlMappingRecord.obligation_id == obligation_id,
            ObligationControlMappingRecord.mapping_method == METHOD,
        )
        .order_by(ObligationControlMappingRecord.score.desc())
    ).all()
    if existing:
        return list(existing)
    latest = (
        select(
            ControlVersionRecord.control_id, func.max(ControlVersionRecord.ordinal).label("ordinal")
        )
        .group_by(ControlVersionRecord.control_id)
        .subquery()
    )
    rows = session.execute(
        select(ControlRecord, ControlVersionRecord)
        .join(ControlVersionRecord, ControlVersionRecord.control_id == ControlRecord.id)
        .join(
            latest,
            (latest.c.control_id == ControlRecord.id)
            & (latest.c.ordinal == ControlVersionRecord.ordinal),
        )
        .where(ControlRecord.organization_id == organization_id, ControlRecord.active.is_(True))
    ).all()
    source = set(TOKEN.findall((obligation.text + " " + obligation.action).lower()))
    scored = []
    for control, version in rows:
        target = set(
            TOKEN.findall(
                (
                    control.title + " " + version.description + " " + version.evidence_requirement
                ).lower()
            )
        )
        overlap = sorted(source & target)
        explanation_terms = [term for term in overlap if term not in EXPLANATION_STOPWORDS]
        score = len(overlap) / len(source | target) if source | target else 0.0
        if score > 0:
            scored.append((score, overlap, control, version))
    scored.sort(key=lambda row: row[0], reverse=True)
    selected = scored[:limit]
    ambiguous = len(selected) > 1 and selected[0][0] - selected[1][0] < 0.08
    mappings = []
    for rank, (score, overlap, control, version) in enumerate(selected):
        status = (
            "ambiguous"
            if ambiguous and rank < 2
            else ("suggested" if score >= 0.12 else "needs_review")
        )
        record = ObligationControlMappingRecord(
            organization_id=organization_id,
            obligation_id=obligation_id,
            control_version_id=version.id,
            score=Decimal(str(round(score, 3))),
            status=status,
            explanation_json=json.dumps(
                {
                    "matched_terms": explanation_terms,
                    "raw_overlap_count": len(overlap),
                    "control_key": control.control_key,
                },
                sort_keys=True,
            ),
            mapping_method=METHOD,
        )
        session.add(record)
        mappings.append(record)
    session.add(
        AuditEventRecord(
            organization_id=organization_id,
            actor_id=actor_id,
            event_type="control_mappings.suggested",
            entity_type="obligation",
            entity_id=obligation_id,
            detail_json=json.dumps(
                {"count": len(mappings), "unmapped": not mappings, "method": METHOD}, sort_keys=True
            ),
        )
    )
    session.flush()
    return mappings
