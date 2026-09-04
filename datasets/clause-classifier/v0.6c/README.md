# v0.6C real corpus execution workspace

This directory defines the checked-in contracts for executing the v0.6 pipeline on genuine
regulatory documents. Raw source bytes, extracted text, annotations, adjudications, datasets and
model weights remain outside Git because they may contain redistribution-restricted material.

`source-approval-template.json` records the human rights review that binds each approved registry
entry to the exact downloaded artifact. `run-manifest-template.json` records the external storage
locations and immutable identifiers for the annotation, training and model-review evidence.

The milestone is complete only when all of the following are true:

1. At least 25 document/version groups from at least three regulators have approved reuse evidence.
2. The real-corpus command emits a hash-bound candidate queue and receipt.
3. Two independent humans annotate every admitted clause; a third human adjudicates disagreements.
4. The v0.6A audit admits at least 500 resolved examples and 30 examples per class.
5. The v0.6B baseline and encoder run on that audit-bound dataset.
6. A human reviews the test, calibration, slice and abstention reports before explicit promotion.

No empty template, synthetic fixture, candidate queue, notebook execution or unreviewed model may
be described as genuine model training completion.

## v0.6C-1 corpus assembly

`corpus-manifest.json` selects exactly 25 English federal Acts and regulations across five
regulatory portfolios: OSFI, FINTRAC, the Office of the Privacy Commissioner, the Competition
Bureau and Health Canada. Every artifact URL is bound to Justice Canada's official XML repository
at commit `a782c13dbf0c710f33d8b2adc3e42377c94d0626`.

`acquisition-lock.json` proves that all 25 immutable XML files were retrieved on 2026-09-04. It
records the exact byte size and SHA-256 of each artifact without checking raw legal text into Git.
Its status is deliberately `acquired_pending_rights_review`: acquisition is not legal approval,
annotation completion or permission to train.

Validate the checked-in manifest:

```bash
cd apps/api
python scripts/acquire_regulatory_corpus.py \
  --manifest ../../datasets/clause-classifier/v0.6c/corpus-manifest.json \
  --lock ../../datasets/clause-classifier/v0.6c/acquisition-lock.json \
  --output-dir /tmp/regimpact-corpus \
  --receipt /tmp/regimpact-corpus-receipt.json \
  --validate-only
```

Acquire a fresh local copy into a new, empty external directory:

```bash
cd apps/api
python scripts/acquire_regulatory_corpus.py \
  --manifest ../../datasets/clause-classifier/v0.6c/corpus-manifest.json \
  --output-dir "$REGIMPACT_CORPUS_ROOT/raw" \
  --receipt "$REGIMPACT_CORPUS_ROOT/acquisition-receipt.json"
```

Before using these files, a named reviewer must verify the Open Government Licence and the
Reproduction of Federal Law Order, then create source approvals using
`source-approval-template.json`. The software never promotes `review_required` automatically.

## v0.6C-2 rights review

`rights-review-packet.json` is the generated 25-record reviewer packet. It is intentionally checked
in with every decision set to `pending`, no reviewer identity, and all checks false. Follow the
[rights-review runbook](../../../docs/corpus-rights-review-runbook.md) to complete it manually and
use `review_corpus_rights.py` to validate or finalize the evidence.

Finalization produces the approved source registry and source-approval contract required by the
existing real-corpus execution command. It authorizes XML extraction and human annotation only;
the dataset audit and separate promotion controls still gate genuine model training.
