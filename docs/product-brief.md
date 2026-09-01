# Product brief

## Primary users

- Compliance analyst: investigates detected changes and drafts impact findings.
- Reviewer: approves, rejects or amends findings supported by cited evidence.
- Auditor: reads finalized findings and immutable decision history.
- Administrator: manages sources, users and organization configuration.

## Core story

When a regulator publishes a new document version, RegImpact detects the changed sections, identifies potential obligations, connects them to internal controls and evidence, escalates uncertain conclusions, and produces an approved impact record with complete lineage.

## Non-goals

- Autonomous legal conclusions
- Generic conversational document Q&A
- Unreviewed remediation or policy changes
- Claiming production security before identity and threat-model milestones are verified

## v0.1 acceptance criteria

1. Identical content does not create another version.
2. A changed document preserves both versions and their hashes.
3. Section comparison reports additions, modifications and removals.
4. Every change references the source version and section.
5. Core change logic is deterministic and unit tested.
6. API responses carry a request ID and use a stable error envelope.
