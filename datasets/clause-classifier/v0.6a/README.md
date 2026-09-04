# v0.6A clause dataset workspace

This directory contains the governed dataset contract and source-candidate registry. It deliberately
does **not** contain copied regulatory text or fabricated labels.

| Readiness item | Current state |
| --- | --- |
| Registered authoritative source candidates | 3 |
| Sources approved for corpus use | 0 |
| Adjudicated examples | 0 |
| Promotion readiness | Blocked pending rights review, extraction, annotation, and audit |

Before retrieval, record the approved reuse basis, immutable retrieval timestamp, and SHA-256 of
each source artifact. Candidate generation fails closed for `review_required` or `rejected` sources.
Raw documents, working annotations, and dataset exports are ignored to prevent accidental
publication before review.

See [the annotation guidelines](../../../docs/clause-annotation-guidelines.md) for the complete
workflow, schemas, commands, and release gates.
