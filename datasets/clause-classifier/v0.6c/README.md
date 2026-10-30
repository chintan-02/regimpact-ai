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

## v0.6C-3 XML extraction and annotation queue

After a named human has finalized all 25 source decisions, extract stable operative sections from
the exact hash-approved XML bytes. The extractor reads only top-level sections in each document's
`Body`, preserves document/section/heading lineage, excludes labels, marginal notes from clause
text, historical notes, footnotes, repealed markers and coming-into-force metadata, and refuses
malformed or empty documents. Justice Canada XML has no page coordinates, so `page` is explicitly
`null`; the official URL plus document and section identifiers provide the source locator.

```bash
cd apps/api
python scripts/extract_regulatory_sections.py \
  --sources "$REGIMPACT_CORPUS_ROOT/approved-source-registry.json" \
  --approvals "$REGIMPACT_CORPUS_ROOT/source-approvals.json" \
  --artifact-root "$REGIMPACT_CORPUS_ROOT/raw" \
  --sections "$REGIMPACT_CORPUS_ROOT/sections.jsonl" \
  --receipt "$REGIMPACT_CORPUS_ROOT/section-extraction-receipt.json"

python scripts/execute_real_clause_corpus.py \
  --sources "$REGIMPACT_CORPUS_ROOT/approved-source-registry.json" \
  --approvals "$REGIMPACT_CORPUS_ROOT/source-approvals.json" \
  --artifact-root "$REGIMPACT_CORPUS_ROOT/raw" \
  --sections "$REGIMPACT_CORPUS_ROOT/sections.jsonl" \
  --candidates "$REGIMPACT_CORPUS_ROOT/candidates.jsonl" \
  --receipt "$REGIMPACT_CORPUS_ROOT/candidate-queue-receipt.json"
```

Both commands re-verify approval coverage and every raw-file SHA-256. Candidate IDs are stable
functions of document, section, sentence position and normalized text. The receipts retain
per-document section counts and hashes while explicitly keeping model training unauthorized.

Do not run either command against the checked-in pending review packet. Do not bulk-approve the
packet, and do not commit raw XML, extracted legal text, candidate queues or reviewer identities.

## v0.6C-4 deterministic pilot sampling

The complete candidate queue is an extraction artifact, not a practical request to label every
clause. Build a 350-clause pilot that covers all 25 documents and uses transparent lexical strata
to enrich likely examples of the seven taxonomy classes. Strata affect selection only; they are
never written into the annotators' tasks as suggested or ground-truth labels.

```bash
cd apps/api
PYTHONPATH=src python scripts/prepare_annotation_pilot.py \
  --candidates "$REGIMPACT_CORPUS_ROOT/candidates.jsonl" \
  --queue-receipt "$REGIMPACT_CORPUS_ROOT/candidate-queue-receipt.json" \
  --sample "$REGIMPACT_CORPUS_ROOT/pilot-sample.json" \
  --package-a "$REGIMPACT_CORPUS_ROOT/pilot-annotator-a.json" \
  --package-b "$REGIMPACT_CORPUS_ROOT/pilot-annotator-b.json" \
  --report "$REGIMPACT_CORPUS_ROOT/pilot-sampling-report.json" \
  --target 350 \
  --seed v0.6c4-pilot-v1
```

The command verifies the exact 13,370-candidate fingerprint before sampling. Packages A and B
contain the same clause IDs in independently deterministic orders, no prefilled labels and no
annotator identity. Give each file to a different human and never disclose one person's labels to
the other before both are complete. Each annotator sets the package-level `annotator_id` and fills
`label` plus a timezone-aware `annotated_at` for each task without modifying source fields.

Check progress or agreement at any time:

```bash
PYTHONPATH=src python scripts/report_annotation_pilot.py \
  --sample "$REGIMPACT_CORPUS_ROOT/pilot-sample.json" \
  --package-a "$REGIMPACT_CORPUS_ROOT/pilot-annotator-a.json" \
  --package-b "$REGIMPACT_CORPUS_ROOT/pilot-annotator-b.json" \
  --report "$REGIMPACT_CORPUS_ROOT/pilot-progress.json"
```

The validator rejects changed text/lineage, incomplete label/timestamp pairs, duplicate human
identities and obsolete guidelines. When both packages are complete it reports raw agreement and
the exact disagreements requiring an independent third reviewer. Heuristic balance does not prove
final class balance; adjudicate the pilot, inspect actual labels, and construct a targeted second
batch before attempting the 500-example dataset gate.

After both packages report complete, export the validated decisions into the JSONL schema accepted
by `adjudicate_clause_dataset.py`:

```bash
PYTHONPATH=src python scripts/export_annotation_pilot.py \
  --sample "$REGIMPACT_CORPUS_ROOT/pilot-sample.json" \
  --package-a "$REGIMPACT_CORPUS_ROOT/pilot-annotator-a.json" \
  --package-b "$REGIMPACT_CORPUS_ROOT/pilot-annotator-b.json" \
  --annotations "$REGIMPACT_CORPUS_ROOT/pilot-annotations.jsonl"
```

Export fails until every sampled clause has two complete annotations from different humans. The
output contains exactly two governed `Annotation` records per clause and can be passed directly as
the adjudication command's `--annotations` input.

## v0.6C-5 secure offline annotation workspace

Generate one self-contained HTML workspace for each blinded package. The builder first validates
the complete package against the immutable pilot sample. The resulting file has no server, CDN,
analytics or network API; progress stays in that browser's local storage until the annotator
exports JSON. Its content-security policy disables connections, objects, forms and embedded
resources. Source links are the only intentional navigation away from the file.

```bash
cd apps/api
PYTHONPATH=src python scripts/build_annotation_workspace.py \
  --sample "$REGIMPACT_CORPUS_ROOT/pilot-sample.json" \
  --package "$REGIMPACT_CORPUS_ROOT/pilot-annotator-a.json" \
  --output "$REGIMPACT_CORPUS_ROOT/pilot-annotator-a.html"

PYTHONPATH=src python scripts/build_annotation_workspace.py \
  --sample "$REGIMPACT_CORPUS_ROOT/pilot-sample.json" \
  --package "$REGIMPACT_CORPUS_ROOT/pilot-annotator-b.json" \
  --output "$REGIMPACT_CORPUS_ROOT/pilot-annotator-b.html"
```

Give workspace A only to human A and workspace B only to human B. Do not put either workspace or
its exported progress in Git, email both packages to one reviewer, or use a shared cloud editor.
Each reviewer enters a distinct assigned ID, labels independently, and regularly uses **Export
progress JSON**. The workspace permits partial exports for safe checkpoints and validates any
resumed file against the exact package, sample, candidate-queue fingerprint, policies, labels and
immutable clause lineage.

After receiving exports from both humans, validate them before any agreement calculation or
adjudication export:

```bash
PYTHONPATH=src python scripts/report_annotation_pilot.py \
  --sample "$REGIMPACT_CORPUS_ROOT/pilot-sample.json" \
  --package-a "$REGIMPACT_CORPUS_ROOT/v0.6c4-pilot-a-progress.json" \
  --package-b "$REGIMPACT_CORPUS_ROOT/v0.6c4-pilot-b-progress.json" \
  --report "$REGIMPACT_CORPUS_ROOT/pilot-progress.json"
```

The Python validator remains authoritative. The browser is a convenience interface, not a way to
bypass independent-human, complete-coverage, adjudication, dataset-audit or training gates.

## v0.6C-6 production annotation campaign

The production dataset gate requires at least 500 resolved clauses and 30 examples in every final
class. Because human disagreements and true-label imbalance reduce the admitted dataset, prepare a
700-clause campaign in seven manageable 100-clause batches. Every batch receives a unique package
identity and browser storage key, preventing one workspace from overwriting another. Sampling
strata remain enrichment heuristics only and are never exposed as answers.

```bash
cd apps/api
PYTHONPATH=src python scripts/prepare_annotation_campaign.py \
  --candidates "$REGIMPACT_CORPUS_ROOT/candidates.jsonl" \
  --queue-receipt "$REGIMPACT_CORPUS_ROOT/candidate-queue-receipt.json" \
  --output-dir "$REGIMPACT_CORPUS_ROOT/production-campaign-v1" \
  --campaign-id v0.6c6-production-v1 \
  --target 700 \
  --batch-size 100 \
  --seed v0.6c6-production-v1
```

Give each `workspace-a.html` and `workspace-b.html` to different humans for that clause. A reviewer
may work across multiple batches, but no person may provide both votes for the same clause. Returned
exports must be saved as `completed-a.json` and `completed-b.json` in their exact batch directory.
Do not copy labels between slots, use AI answers as human labels, or admit the invalidated random
pilot run.

Validate the entire campaign at any time:

```bash
PYTHONPATH=src python scripts/report_annotation_campaign.py \
  --campaign-dir "$REGIMPACT_CORPUS_ROOT/production-campaign-v1" \
  --report "$REGIMPACT_CORPUS_ROOT/production-campaign-v1/progress.json"
```

Only after every batch is complete, export two governed votes per clause:

```bash
PYTHONPATH=src python scripts/export_annotation_campaign.py \
  --campaign-dir "$REGIMPACT_CORPUS_ROOT/production-campaign-v1" \
  --annotations "$REGIMPACT_CORPUS_ROOT/production-campaign-v1/annotations.jsonl"
```

The export is still not a training dataset. Run independent third-party adjudication for every
disagreement, audit the resolved label distribution, and add a targeted follow-up batch if any
class remains below 30 examples. Training and promotion remain unauthorized until the existing
v0.6A and v0.6B gates pass.

## v0.6C-7 experimental silver labels

For solo experimentation, the production two-human gate remains unchanged. A separate weak-
supervision path can label the 700-clause campaign with two distinct AI models and reserve 70
clauses from whole holdout documents for one-person human evaluation. AI consensus labels are
silver training data, never human ground truth, and cannot produce a production promotion receipt.

Prepare the experiment with immutable model identities (prefer pinned model revisions):

```bash
cd apps/api
PYTHONPATH=src python scripts/prepare_silver_experiment.py \
  --campaign-dir "$REGIMPACT_CAMPAIGN_ROOT" \
  --output-dir "$REGIMPACT_SILVER_ROOT" \
  --labeler-a-id labeler-a-v1 \
  --model-a MODEL_A \
  --labeler-b-id labeler-b-v1 \
  --model-b MODEL_B \
  --evaluation-size 70 \
  --minimum-confidence 0.80
```

Run each stream against a separately selected OpenAI-compatible model endpoint. The runner resumes
from its append-only response file. Review provider retention, privacy and cost terms before sending
text; never place credentials in a command, repository file or manifest. The endpoint must support
OpenAI-compatible strict JSON-schema response formats: the runner constrains `label` to the seven
taxonomy values, bounds confidence to zero through one and rejects additional response fields.
Prompt v2 also distinguishes direct duties from evidentiary rules, enforcement mechanics,
defenses, exemptions and other provisions that must not be converted into inferred obligations.

```bash
PYTHONPATH=src python scripts/run_silver_labeler.py \
  --requests "$REGIMPACT_SILVER_ROOT/labeler-a-requests.jsonl" \
  --responses "$REGIMPACT_SILVER_ROOT/labeler-a-responses.jsonl" \
  --base-url "$LABELER_A_BASE_URL" \
  --model MODEL_A \
  --labeler-id labeler-a-v1 \
  --api-key-env LABELER_A_API_KEY

PYTHONPATH=src python scripts/run_silver_labeler.py \
  --requests "$REGIMPACT_SILVER_ROOT/labeler-b-requests.jsonl" \
  --responses "$REGIMPACT_SILVER_ROOT/labeler-b-responses.jsonl" \
  --base-url "$LABELER_B_BASE_URL" \
  --model MODEL_B \
  --labeler-id labeler-b-v1 \
  --api-key-env LABELER_B_API_KEY
```

Compile only high-confidence model agreement. All holdout-document clauses, disagreements and
low-confidence predictions are routed away from training:

```bash
PYTHONPATH=src python scripts/compile_silver_consensus.py \
  --experiment-dir "$REGIMPACT_SILVER_ROOT" \
  --silver-labels "$REGIMPACT_SILVER_ROOT/silver-training-labels.jsonl" \
  --review-queue "$REGIMPACT_SILVER_ROOT/silver-review-queue.jsonl" \
  --report "$REGIMPACT_SILVER_ROOT/silver-consensus-report.json" \
  --minimum-confidence 0.80
```

Open `human-evaluation-workspace.html`, label its 70 held-out clauses carefully and export the
result. This is a single-human evaluation set, not independently adjudicated gold data. The
experiment may support honest exploratory metrics, but `model_training_authorized` and
`production_promotion_authorized` remain false in every receipt.

After all 70 human labels are complete, evaluate both immutable model streams and export only
hash-bound identifiers, labels, confidences and error flags for review (not full regulatory text):

```bash
PYTHONPATH=src python scripts/evaluate_human_silver_labels.py \
  --experiment-dir "$REGIMPACT_SILVER_ROOT" \
  --completed "$REGIMPACT_SILVER_ROOT/v0.6c7-human-evaluation-a-progress.json" \
  --report "$REGIMPACT_SILVER_ROOT/human-silver-evaluation-report.json" \
  --disagreements "$REGIMPACT_SILVER_ROOT/human-silver-disagreements.jsonl"
```


## v0.6C-8 governed third-model adjudication

When the two silver labelers disagree, prepare a third independent model stream from only the
non-held-out disagreements. The command fingerprints both original response streams, excludes all
holdout-document clauses and refuses a model or labeler identity already used in slots A or B.

```bash
PYTHONPATH=src python scripts/prepare_silver_adjudication.py \
  --experiment-dir "$REGIMPACT_SILVER_ROOT" \
  --labeler-c-id labeler-c-v1 \
  --model-c MODEL_C \
  --minimum-confidence 0.80

PYTHONPATH=src python scripts/run_silver_labeler.py \
  --requests "$REGIMPACT_SILVER_ROOT/labeler-c-requests.jsonl" \
  --responses "$REGIMPACT_SILVER_ROOT/labeler-c-responses.jsonl" \
  --base-url "$LABELER_C_BASE_URL" \
  --model MODEL_C \
  --labeler-id labeler-c-v1
```

Compile the final experimental silver set only after slot C has complete validated coverage:

```bash
PYTHONPATH=src python scripts/compile_silver_adjudication.py \
  --experiment-dir "$REGIMPACT_SILVER_ROOT" \
  --silver-labels "$REGIMPACT_SILVER_ROOT/silver-adjudicated-labels.jsonl" \
  --unresolved-review "$REGIMPACT_SILVER_ROOT/silver-unresolved-review.jsonl" \
  --report "$REGIMPACT_SILVER_ROOT/silver-adjudication-report.json"
```

A disagreement is accepted only when C agrees with A or B and both supporting confidences meet the
recorded threshold. Three-way disagreement and low-confidence majority cases remain unresolved.
These outputs are AI silver labels, not human ground truth. The 70-clause document-isolated human
evaluation remains mandatory for any experimental quality claim, and production promotion remains
unauthorized.
