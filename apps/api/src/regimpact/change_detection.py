"""Deterministic section-level change detection."""

from __future__ import annotations

from .domain import ChangeType, RegulationVersion, Section, SectionChange


def _index(sections: tuple[Section, ...]) -> dict[str, Section]:
    indexed: dict[str, Section] = {}
    for section in sections:
        if section.key in indexed:
            raise ValueError(f"duplicate section key: {section.key}")
        indexed[section.key] = section
    return indexed


def detect_changes(
    previous: RegulationVersion | None,
    current: RegulationVersion,
) -> tuple[SectionChange, ...]:
    """Return a stable, section-key-ordered change set."""
    before = _index(previous.sections) if previous else {}
    after = _index(current.sections)
    changes: list[SectionChange] = []

    for key in sorted(before.keys() | after.keys()):
        old = before.get(key)
        new = after.get(key)
        if old is None and new is not None:
            change_type = ChangeType.ADDED
        elif new is None and old is not None:
            change_type = ChangeType.REMOVED
        elif (
            old
            and new
            and (old.heading.strip(), old.text.strip())
            != (
                new.heading.strip(),
                new.text.strip(),
            )
        ):
            change_type = ChangeType.MODIFIED
        else:
            continue

        changes.append(
            SectionChange.create(
                regulation_id=current.regulation_id,
                previous_version_id=previous.id if previous else None,
                current_version_id=current.id,
                section_key=key,
                heading=(new or old).heading,  # type: ignore[union-attr]
                change_type=change_type,
                previous_text=old.text if old else None,
                current_text=new.text if new else None,
                previous_page=old.page if old else None,
                current_page=new.page if new else None,
            )
        )
    return tuple(changes)
