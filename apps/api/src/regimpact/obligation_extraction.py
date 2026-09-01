"""Deterministic, evidence-preserving obligation extraction baseline."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .calibration import CURRENT_POLICY
from .domain import ObligationCandidate, ObligationModality, Section

EXTRACTION_METHOD = "deterministic-rules-v1"

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_SPACE = re.compile(r"\s+")
_MODALITY = re.compile(
    r"\b(?P<subject>[A-Z][A-Za-z0-9 &'()/-]{1,100}?)\s+"
    r"(?P<modal>must\s+not|shall\s+not|must|shall|(?:is|are)\s+required\s+to)\s+"
    r"(?P<action>[^.!?]+)",
    re.IGNORECASE,
)
_DEADLINE = re.compile(
    r"\b(?:within\s+\d+\s+(?:hours?|days?|business\s+days?|months?|years?)|"
    r"no\s+later\s+than\s+[^,.;]+|by\s+(?:the\s+)?[^,.;]+|"
    r"(?:daily|weekly|monthly|quarterly|annually))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SectionObligations:
    section: Section
    candidates: tuple[ObligationCandidate, ...]


def _normalize(value: str) -> str:
    return _SPACE.sub(" ", value).strip()


def _sentences(text: str) -> tuple[str, ...]:
    normalized = _normalize(text)
    return tuple(part.strip() for part in _SENTENCE_BOUNDARY.split(normalized) if part.strip())


def _modality(value: str) -> ObligationModality:
    normalized = _normalize(value).lower()
    return {
        "must": ObligationModality.MUST,
        "must not": ObligationModality.MUST_NOT,
        "shall": ObligationModality.SHALL,
        "shall not": ObligationModality.SHALL_NOT,
        "is required to": ObligationModality.REQUIRED_TO,
        "are required to": ObligationModality.REQUIRED_TO,
    }[normalized]


def extract_obligations(section: Section) -> tuple[ObligationCandidate, ...]:
    """Extract high-precision candidates with auditable confidence features."""
    candidates: list[ObligationCandidate] = []
    for sentence in _sentences(section.text):
        for match in _MODALITY.finditer(sentence):
            subject = _normalize(match.group("subject")).rstrip(",")
            action = _normalize(match.group("action"))
            deadline = _DEADLINE.search(action)
            rule_ids = ["binding_modality", "explicit_subject"]
            confidence = 0.72
            if len(action.split()) >= 3:
                confidence += 0.08
                rule_ids.append("action_phrase")
            if deadline:
                confidence += 0.10
                rule_ids.append("temporal_constraint")
            if _modality(match.group("modal")) in {
                ObligationModality.MUST_NOT,
                ObligationModality.SHALL_NOT,
            }:
                confidence += 0.04
                rule_ids.append("explicit_prohibition")
            raw_confidence = min(round(confidence, 3), 0.98)
            confidence = CURRENT_POLICY.calibrate(raw_confidence)
            candidates.append(
                ObligationCandidate(
                    text=sentence,
                    evidence_quote=sentence,
                    subject=subject,
                    action=action,
                    modality=_modality(match.group("modal")),
                    deadline_text=_normalize(deadline.group(0)) if deadline else None,
                    raw_confidence=raw_confidence,
                    confidence=confidence,
                    requires_review=CURRENT_POLICY.requires_review(confidence),
                    rule_ids=tuple(rule_ids),
                )
            )
    return tuple(candidates)


def extract_version_sections(sections: tuple[Section, ...]) -> tuple[SectionObligations, ...]:
    return tuple(
        SectionObligations(section=section, candidates=extract_obligations(section))
        for section in sections
    )
