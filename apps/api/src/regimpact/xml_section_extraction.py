"""Deterministic extraction of operative sections from Justice Canada XML."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from .clause_annotations import ExtractedSection, SourceRecord
from .corpus_execution import SourceApproval, verify_source_artifacts

_SPACE = re.compile(r"\s+")
_EXCLUDED = {
    "HistoricalNote",
    "HistoricalNoteSubItem",
    "Footnote",
    "Repealed",
    "ComingIntoForce",
}


class XmlSectionExtractionError(RuntimeError):
    """Raised when approved XML cannot be converted into governed sections."""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalized_text(element: ET.Element, *, excluded: set[str] | None = None) -> str:
    excluded = excluded or set()
    pieces: list[str] = []

    def visit(node: ET.Element) -> None:
        if _local_name(node.tag) in excluded:
            if node.tail:
                pieces.append(node.tail)
            return
        if node.text:
            pieces.append(node.text)
        for child in node:
            visit(child)
        if node.tail:
            pieces.append(node.tail)

    visit(element)
    return _SPACE.sub(" ", "".join(pieces)).strip()


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name:
            return _normalized_text(child)
    return ""


def _section_text(element: ET.Element) -> str:
    blocks: list[str] = []

    def collect(node: ET.Element) -> None:
        if _local_name(node.tag) in _EXCLUDED:
            return
        if _local_name(node.tag) == "Text":
            value = _normalized_text(node, excluded=_EXCLUDED)
            if value:
                blocks.append(value)
            return
        for child in node:
            collect(child)

    collect(element)
    return " ".join(blocks)


def extract_xml_sections(xml_path: Path, *, document_id: str) -> tuple[ExtractedSection, ...]:
    """Extract top-level operative Body sections with stable source-native identifiers."""
    try:
        root = ET.fromstring(xml_path.read_bytes())
    except (OSError, ET.ParseError) as error:
        raise XmlSectionExtractionError(f"invalid XML for {document_id}: {error}") from error

    body = next((item for item in root if _local_name(item.tag) == "Body"), None)
    if body is None:
        raise XmlSectionExtractionError(f"XML has no Body: {document_id}")

    sections: list[ExtractedSection] = []
    headings: dict[int, str] = {}
    seen_ids: set[str] = set()
    ordinal = 0
    for element in body:
        name = _local_name(element.tag)
        if name == "Heading":
            try:
                level = int(element.attrib.get("level", "1"))
            except ValueError:
                level = 1
            title = _child_text(element, "TitleText") or _normalized_text(element)
            if title:
                headings[level] = title
                headings = {key: value for key, value in headings.items() if key <= level}
            continue
        if name != "Section":
            continue

        ordinal += 1
        label = _child_text(element, "Label")
        native_id = next(
            (value for key, value in element.attrib.items() if _local_name(key) == "id"), ""
        )
        identity = label or native_id or str(ordinal)
        section_id = f"section-{identity}"
        if section_id in seen_ids:
            section_id = f"{section_id}-{ordinal}"
        seen_ids.add(section_id)

        marginal_note = _child_text(element, "MarginalNote")
        heading_path = " / ".join(headings[key] for key in sorted(headings))
        heading = marginal_note or heading_path or f"Section {identity}"
        text = _section_text(element)
        if not text:
            continue
        sections.append(
            ExtractedSection(
                document_id=document_id,
                section_id=section_id,
                heading=heading,
                page=None,
                text=text,
            )
        )
    if not sections:
        raise XmlSectionExtractionError(f"XML contains no non-empty Body sections: {document_id}")
    return tuple(sections)


def extract_approved_corpus_sections(
    sources: dict[str, SourceRecord],
    approvals: tuple[SourceApproval, ...],
    *,
    artifact_root: Path,
) -> tuple[tuple[ExtractedSection, ...], dict[str, Any]]:
    """Verify approved bytes before extracting every registered document exactly once."""
    hashes = verify_source_artifacts(sources, approvals, artifact_root=artifact_root)
    approval_by_source = {item.source_id: item for item in approvals}
    sections: list[ExtractedSection] = []
    per_document: dict[str, int] = {}
    for document_id, source in sorted(sources.items()):
        approval = approval_by_source[source.source_id]
        artifact = artifact_root / approval.artifact_path
        extracted = extract_xml_sections(artifact, document_id=document_id)
        sections.extend(extracted)
        per_document[document_id] = len(extracted)

    payload = "\n".join(
        json.dumps(asdict(item), sort_keys=True, separators=(",", ":")) for item in sections
    )
    receipt = {
        "schema_version": "regimpact-xml-section-extraction-v1",
        "status": "sections_ready_for_candidate_generation",
        "documents": len(per_document),
        "sections": len(sections),
        "sections_per_document": dict(sorted(per_document.items())),
        "source_artifact_sha256": dict(sorted(hashes.items())),
        "sections_sha256": sha256(payload.encode()).hexdigest(),
        "human_annotation_required": True,
        "model_training_authorized": False,
    }
    return tuple(sections), receipt
