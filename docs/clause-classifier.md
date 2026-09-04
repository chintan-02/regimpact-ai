# Evaluated regulatory-clause classifier

## Purpose and boundary

v0.6 adds the governed ML path for classifying regulatory clauses. The classifier supports analyst
triage; it does not make a legal determination and cannot approve a finding or modify a control.
Predictions below the promoted artifact's confidence threshold are stored as `needs_review`.

The deterministic obligation extractor remains the default production path until a transformer
artifact passes every data-diversity, held-out quality, calibration, and selective-prediction gate.
The repository intentionally does not claim that its 14-row engineering fixture is training data.

## Label taxonomy

| Label | Annotation rule |
| --- | --- |
| `reporting_requirement` | A binding duty to notify, disclose, file, report, or submit information |
| `record_retention_requirement` | A binding duty to retain, preserve, or maintain records for a period |
| `prohibition` | Conduct explicitly forbidden by `must not`, `shall not`, or equivalent language |
| `permission` | Conduct explicitly allowed or discretionary, commonly using `may` |
| `definition` | A clause defining a term or scope without independently creating a duty |
| `obligation` | A binding duty that is not a more specific reporting or retention requirement |
| `non_obligation` | Context, guidance, examples, history, headings, or descriptive text |

Specific labels take precedence over the general `obligation` label. Annotators classify the legal
function of the complete clause in context, not the presence of a keyword. Historical quotations,
examples, and glossary text containing words such as `must` remain `non_obligation` unless they
create a current duty.

## Dataset contract

Training data uses versioned JSON Lines with one clause per row:

```json
{"clause_id":"aer-060-v13-4.2-a","document_id":"aer-060-v13","regulator":"AER","text":"Operators must notify the regulator within 24 hours.","label":"reporting_requirement"}
```

Required controls:

- globally unique `clause_id` values;
- stable document/version groups through `document_id`;
- regulator provenance without tenant or personal data;
- exact source text, with any permitted normalization recorded upstream;
- dual annotation and adjudication for the promoted corpus;
- a versioned dataset ID and SHA-256 fingerprint in every artifact and prediction;
- licensing and source-use review before clauses enter the training corpus.

The loader fails on unknown labels, missing fields, duplicate clause IDs, or empty data. Splitting is
deterministic and occurs by `document_id`, preventing clauses from the same regulation version from
appearing in both training and evaluation.

## Evaluation design

The deterministic rules remain the first baseline. The v0.6 ML extra also provides a TF-IDF plus
class-weighted logistic-regression baseline:

```bash
cd apps/api
pip install -e '.[ml]'
python scripts/evaluate_clause_baseline.py \
  --dataset /path/to/clauses-v1.jsonl \
  --dataset-id clauses-v1 \
  --dataset-audit /path/to/clauses-v1-audit.json \
  --output /path/to/clauses-v1-tfidf.json
```

The transformer experiment fine-tunes a legal-domain encoder, estimates a validation-set
temperature for probability calibration, selects an abstention threshold on validation data, and
reports the final metrics once on the isolated test set:

```bash
python scripts/train_clause_classifier.py \
  --dataset /path/to/clauses-v1.jsonl \
  --dataset-id clauses-v1 \
  --dataset-audit /path/to/clauses-v1-audit.json \
  --output /secure/model-registry/regimpact-clause-v1 \
  --base-model-revision IMMUTABLE_HUGGING_FACE_COMMIT \
  --training-commit FULL_40_CHARACTER_GIT_SHA
```

The manifest records the base model and immutable revision, training commit, runtime packages,
exact dataset hash, label order, temperature, abstention
threshold, macro-F1, per-class inputs, calibration error, coverage, and accuracy on covered
predictions. The training command exits with status `2` if the artifact fails promotion.

Training refuses to begin unless the independently generated v0.6A audit is ready and matches the
dataset ID and fingerprint. A qualifying manifest is still not sufficient for serving: an
authorized reviewer must create `promotion.json`, which binds the audit, manifest, artifact hash,
training commit, approver, and timestamp. Runtime loading fails closed without that receipt or after
artifact changes. See the [v0.6B runbook](clause-classifier-training-runbook.md).

## Promotion policy

An artifact is blocked unless all of the following are true:

| Gate | Minimum requirement |
| --- | --- |
| Labelled examples | 500 |
| Regulation documents/versions | 25 |
| Regulators | 3 |
| Test macro-F1 | 0.75 |
| Test F1 for every class | 0.55 |
| Expected calibration error | at most 0.10 |
| Accuracy on non-abstained predictions | 0.85 |
| Non-abstained coverage | 0.60 |

These are minimum engineering gates, not a claim of legal adequacy. Per-class precision and recall,
confusion patterns, regulator slices, temporal slices, and reviewer workload must also be inspected.
A rare or safety-sensitive class may require a stricter threshold even when aggregate gates pass.

## Runtime and persistence

Serving is disabled by default. To use a promoted artifact:

```bash
export REGIMPACT_CLAUSE_CLASSIFIER_MODE=transformer
export REGIMPACT_CLAUSE_CLASSIFIER_ARTIFACT_DIR=/models/regimpact-clause-v1
```

The runtime loads `manifest.json` first and refuses an unpromoted artifact before importing model
weights. `POST /api/v1/versions/{version_id}/clauses/classify` is administrator-only. Results are
read through `GET /api/v1/clause-classifications` and include:

- regulation version, section, page, and exact clause text;
- predicted label, calibrated confidence, complete class probabilities, and abstention state;
- model ID, dataset ID, and dataset SHA-256;
- review status and append-only classification audit event.

Runs are idempotent per immutable version and model ID. A new model creates new predictions instead
of overwriting historical lineage.

## Monitoring and retraining

Production monitoring should measure input volume, label distribution, confidence distribution,
abstention rate, latency, reviewer overrides, class-specific precision from reviewed samples, and
drift by regulator and time period. Retraining requires a new dataset version and model ID; no model
may silently replace another artifact. Rollback selects the prior promoted artifact and preserves
both prediction histories.

## Current evidence status

The checked-in 14-clause fixture covers all seven labels across five synthetic regulator documents.
It validates contracts, splitting, metrics, lineage, abstention, and failure behavior only. It fails
the dataset-size promotion gates by design. A model becomes portfolio-claimable as “fine-tuned and
evaluated” only after a separately reviewed corpus produces a promoted manifest and reproducible
evaluation report.

## v0.6A dataset construction

The governed corpus workflow is implemented separately from model training. It registers candidate
sources and blocks retrieval until rights approval, preserves source-artifact and clause hashes,
builds stable annotation candidates, requires two independent labels, routes disagreements to an
independent adjudicator, and audits diversity, lineage, document-isolated splits, unresolved items,
and cross-document duplicates. See the [annotation guidelines](clause-annotation-guidelines.md) and
[dataset workspace](../datasets/clause-classifier/v0.6a/README.md).

The repository does not check in regulatory source text or claim a completed corpus. The initial
three official source candidates remain `review_required`; this is an explicit release gate rather
than a synthetic-data shortcut.
