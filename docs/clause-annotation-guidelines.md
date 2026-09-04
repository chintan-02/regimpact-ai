# Regulatory-clause annotation guidelines

## Objective and boundary

v0.6A constructs a reviewable corpus for the seven-class regulatory-clause classifier. The dataset
supports research and analyst triage; labels are not legal conclusions. No model training or
promotion occurs in this milestone, and no real clause enters the corpus until its source-use basis
is approved and recorded.

## Decision hierarchy

Annotate the legal function of the complete clause in context. Apply the first matching category:

1. `reporting_requirement` — binding notification, disclosure, filing, reporting, or submission.
2. `record_retention_requirement` — binding retention, preservation, or maintenance for a period.
3. `prohibition` — conduct expressly forbidden.
4. `permission` — conduct expressly allowed or discretionary.
5. `definition` — defines a term or scope without independently creating a duty.
6. `obligation` — another binding duty.
7. `non_obligation` — context, examples, headings, history, or non-binding guidance.

Do not label by keyword alone. A historical quotation containing “must,” for example, may still be
`non_obligation`. Annotators should use the heading, section, page, document version, and regulator
metadata when the sentence alone is ambiguous.

## Source governance

Every source is registered before extraction with regulator, jurisdiction, official HTTPS URL,
document/version identity, rights status, and rights basis. An approved record also requires a
timezone-aware retrieval timestamp and the SHA-256 of the exact downloaded bytes. Candidate
generation refuses sources unless `rights_status` is `approved`.

The checked-in registry contains official source candidates only. Its `review_required` entries are
not permission to download, redistribute, or train on the material.

## Candidate construction

Extracted sections use this shape:

```json
{"document_id":"aer-060-v1","section_id":"4.2","heading":"Reporting","page":12,"text":"Exact extracted section text."}
```

Generate the immutable queue after rights approval:

```bash
cd apps/api
python scripts/prepare_clause_annotation_queue.py \
  --sources ../../datasets/clause-classifier/v0.6a/source-registry.json \
  --sections /secure/sections.jsonl \
  --output /secure/candidates.jsonl
```

Each candidate carries source and document IDs, regulator and jurisdiction, URL, rights basis,
retrieval timestamp, content hash, section, heading, page, sentence position, exact text, and text
hash. Clause IDs are stable functions of document, section, page, position, and text.

## Independent annotation and adjudication

- Two trained annotators label each candidate independently using the same guideline version.
- Annotators must not see one another's labels before both are submitted.
- Agreement becomes the accepted label.
- Disagreement remains unresolved until a third reviewer, who is not either annotator, records a
  label and rationale.
- Missing, duplicate, unknown, or extra adjudications fail closed.
- The raw agreement rate is reported as a process-quality signal, not model performance.

Resolve annotations into separate training, lineage, and unresolved ledgers:

```bash
python scripts/adjudicate_clause_dataset.py \
  --candidates /secure/candidates.jsonl \
  --annotations /secure/annotations.jsonl \
  --adjudications /secure/adjudications.jsonl \
  --dataset /secure/clauses-v1.jsonl \
  --lineage /secure/clauses-v1-lineage.jsonl \
  --unresolved /secure/clauses-v1-unresolved.jsonl
```

## Dataset audit and release gates

The audit requires at least 500 adjudicated examples, 25 document/version groups, three regulators,
30 examples per label, zero unresolved items, complete approved-source lineage, no exact or
near-duplicate text across documents, and non-empty deterministic document-isolated
train/validation/test partitions.

```bash
python scripts/audit_clause_dataset.py \
  --dataset /secure/clauses-v1.jsonl --dataset-id clauses-v1 \
  --lineage /secure/clauses-v1-lineage.jsonl \
  --unresolved /secure/clauses-v1-unresolved.jsonl \
  --agreement-rate 0.00 --adjudicated-count 0 \
  --report /secure/clauses-v1-audit.json \
  --card /secure/clauses-v1-card.md
```

The command exits with status 2 while blocked. A dataset release must retain the immutable dataset
fingerprint, audit report, dataset card, guideline version, label counts, source approvals,
agreement/adjudication summary, split assignment, and reviewer sign-off. v0.6B may train only from a
dataset release that passes this audit.
