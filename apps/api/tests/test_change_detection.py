from datetime import date
from unittest import TestCase
from uuid import uuid4

from regimpact.change_detection import detect_changes
from regimpact.domain import ChangeType, RegulationVersion, Section, content_hash, utc_now
from regimpact.versioning import InMemoryVersionRepository, VersioningService


def version(regulation_id, ordinal, sections):
    return RegulationVersion(
        id=uuid4(),
        regulation_id=regulation_id,
        ordinal=ordinal,
        hash=content_hash("".join(section.text for section in sections)),
        effective_date=date(2026, 10, 1),
        source_uri="https://regulator.example/rule",
        sections=tuple(sections),
        ingested_at=utc_now(),
    )


class ChangeDetectionTests(TestCase):
    def test_detects_added_modified_and_removed_sections(self):
        regulation_id = uuid4()
        previous = version(
            regulation_id,
            1,
            [
                Section("1", "Scope", "Old scope", 1),
                Section("2", "Reporting", "Report annually", 2),
                Section("3", "Legacy", "Retired clause", 3),
            ],
        )
        current = version(
            regulation_id,
            2,
            [
                Section("1", "Scope", "New scope", 1),
                Section("2", "Reporting", "Report annually", 2),
                Section("4", "Incident notice", "Notify within 24 hours", 4),
            ],
        )

        changes = detect_changes(previous, current)
        self.assertEqual([c.section_key for c in changes], ["1", "3", "4"])
        self.assertEqual(
            [c.change_type for c in changes],
            [ChangeType.MODIFIED, ChangeType.REMOVED, ChangeType.ADDED],
        )

    def test_rejects_duplicate_section_keys(self):
        regulation_id = uuid4()
        current = version(
            regulation_id,
            1,
            [Section("1", "One", "A"), Section("1", "Duplicate", "B")],
        )
        with self.assertRaisesRegex(ValueError, "duplicate section key"):
            detect_changes(None, current)


class VersioningTests(TestCase):
    def test_identical_normalized_content_is_idempotent(self):
        service = VersioningService(InMemoryVersionRepository())
        regulation_id = uuid4()
        kwargs = {
            "regulation_id": regulation_id,
            "source_uri": "https://regulator.example/rule",
            "sections": (Section("1", "Scope", "Applies to operators", 1),),
        }
        first = service.ingest(raw_content="Rule text  \r\n", **kwargs)
        second = service.ingest(raw_content="Rule text\n", **kwargs)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.version.id, second.version.id)
        self.assertEqual(second.changes, ())

    def test_changed_content_increments_version(self):
        service = VersioningService(InMemoryVersionRepository())
        regulation_id = uuid4()
        first = service.ingest(
            regulation_id=regulation_id,
            source_uri="https://regulator.example/rule",
            raw_content="First",
            sections=(Section("1", "Scope", "First"),),
        )
        second = service.ingest(
            regulation_id=regulation_id,
            source_uri="https://regulator.example/rule",
            raw_content="Second",
            sections=(Section("1", "Scope", "Second"),),
        )
        self.assertEqual(first.version.ordinal, 1)
        self.assertEqual(second.version.ordinal, 2)
        self.assertEqual(second.changes[0].change_type, ChangeType.MODIFIED)
