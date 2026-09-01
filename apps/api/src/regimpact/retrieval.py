"""Idempotent indexing and tenant-scoped hybrid retrieval."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db_models import RegulationRecord, RegulationVersionRecord, SectionRecord, SectionSearchRecord
from .embeddings import EmbeddingProvider
from .repository import RegulationNotFoundError

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    section_id: UUID
    regulation_id: UUID
    version_id: UUID
    section_key: str
    heading: str
    body: str
    page: int | None
    source_uri: str
    version_ordinal: int
    score: float
    lexical_score: float
    vector_score: float
    embedding_model_id: str


def index_version(
    session: Session, *, organization_id: UUID, version_id: UUID, provider: EmbeddingProvider
) -> tuple[int, int]:
    rows = session.execute(
        select(SectionRecord, RegulationVersionRecord, RegulationRecord)
        .join(RegulationVersionRecord, RegulationVersionRecord.id == SectionRecord.version_id)
        .join(RegulationRecord, RegulationRecord.id == RegulationVersionRecord.regulation_id)
        .where(
            SectionRecord.version_id == version_id,
            RegulationRecord.organization_id == organization_id,
        )
        .order_by(SectionRecord.position)
    ).all()
    if not rows:
        raise RegulationNotFoundError("regulation version not found")
    existing = set(
        session.scalars(
            select(SectionSearchRecord.section_id).where(
                SectionSearchRecord.organization_id == organization_id,
                SectionSearchRecord.version_id == version_id,
                SectionSearchRecord.embedding_model_id == provider.model_id,
            )
        )
    )
    pending = [(section, version) for section, version, _ in rows if section.id not in existing]
    vectors = provider.embed(tuple(f"{section.heading}\n{section.body}" for section, _ in pending))
    for (section, version), vector in zip(pending, vectors, strict=True):
        searchable = f"{section.heading}\n{section.body}"
        session.add(
            SectionSearchRecord(
                organization_id=organization_id,
                regulation_id=version.regulation_id,
                version_id=version.id,
                section_id=section.id,
                embedding_model_id=provider.model_id,
                content_hash=sha256(searchable.encode()).hexdigest(),
                searchable_text=searchable,
                embedding=list(vector),
            )
        )
    session.flush()
    return len(pending), len(existing)


def _cosine(left: tuple[float, ...], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / denominator if denominator else 0.0


def hybrid_search(
    session: Session,
    *,
    organization_id: UUID,
    query: str,
    provider: EmbeddingProvider,
    limit: int = 10,
) -> list[RetrievalHit]:
    if not query.strip():
        raise ValueError("search query must not be empty")
    query_vector = provider.embed((query,))[0]
    if session.bind and session.bind.dialect.name == "postgresql":
        sql = text("""
        WITH lexical AS (
          SELECT id, row_number() OVER (ORDER BY ts_rank_cd(to_tsvector('english', searchable_text), plainto_tsquery('english', :query)) DESC) rank
          FROM section_search_index WHERE organization_id=:org AND embedding_model_id=:model
            AND to_tsvector('english', searchable_text) @@ plainto_tsquery('english', :query) LIMIT 50
        ), semantic AS (
          SELECT id, row_number() OVER (ORDER BY embedding <=> CAST(:embedding AS vector)) rank
          FROM section_search_index WHERE organization_id=:org AND embedding_model_id=:model LIMIT 50
        )
        SELECT s.id, COALESCE(1.0/(60+l.rank),0)+COALESCE(1.0/(60+v.rank),0) score,
               COALESCE(1.0/(60+l.rank),0) lexical_score, COALESCE(1.0/(60+v.rank),0) vector_score
        FROM section_search_index s LEFT JOIN lexical l ON l.id=s.id LEFT JOIN semantic v ON v.id=s.id
        WHERE s.organization_id=:org AND (l.id IS NOT NULL OR v.id IS NOT NULL)
        ORDER BY score DESC LIMIT :limit
        """)
        ranked = (
            session.execute(
                sql,
                {
                    "query": query,
                    "org": str(organization_id),
                    "model": provider.model_id,
                    "embedding": "[" + ",".join(map(str, query_vector)) + "]",
                    "limit": limit,
                },
            )
            .mappings()
            .all()
        )
        scores = {
            UUID(str(row["id"])): (
                float(row["score"]),
                float(row["lexical_score"]),
                float(row["vector_score"]),
            )
            for row in ranked
        }
    else:
        query_tokens = set(_TOKEN.findall(query.lower()))
        scores = {}
        indexed_records = session.scalars(
            select(SectionSearchRecord).where(
                SectionSearchRecord.organization_id == organization_id,
                SectionSearchRecord.embedding_model_id == provider.model_id,
            )
        ).all()
        for record in indexed_records:
            tokens = set(_TOKEN.findall(record.searchable_text.lower()))
            lexical = len(query_tokens & tokens) / len(query_tokens) if query_tokens else 0.0
            vector = max(0.0, _cosine(query_vector, record.embedding))
            scores[record.id] = (0.5 * lexical + 0.5 * vector, lexical, vector)
        scores = dict(sorted(scores.items(), key=lambda item: item[1][0], reverse=True)[:limit])
    joined_rows = session.execute(
        select(SectionSearchRecord, SectionRecord, RegulationVersionRecord)
        .join(SectionRecord, SectionRecord.id == SectionSearchRecord.section_id)
        .join(RegulationVersionRecord, RegulationVersionRecord.id == SectionSearchRecord.version_id)
        .where(
            SectionSearchRecord.id.in_(scores.keys()),
            SectionSearchRecord.organization_id == organization_id,
        )
    ).all()
    return sorted(
        (
            RetrievalHit(
                section_id=s.section_id,
                regulation_id=s.regulation_id,
                version_id=s.version_id,
                section_key=section.section_key,
                heading=section.heading,
                body=section.body,
                page=section.page,
                source_uri=version.source_uri,
                version_ordinal=version.ordinal,
                score=scores[s.id][0],
                lexical_score=scores[s.id][1],
                vector_score=scores[s.id][2],
                embedding_model_id=s.embedding_model_id,
            )
            for s, section, version in joined_rows
        ),
        key=lambda hit: hit.score,
        reverse=True,
    )
