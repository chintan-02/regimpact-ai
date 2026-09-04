# v0.6B classifier training and promotion runbook

## Release boundary

v0.6B turns one independently audited v0.6A corpus into reproducible baseline and encoder
experiments. Code readiness is not model readiness. Until a real dataset audit reports `ready`, no
training result or fine-tuned-model claim is valid.

## Environment

Use a pinned Python 3.12 environment and an isolated GPU runner for the encoder experiment:

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,ml,notebook]'
```

Record the GPU type, driver/runtime, duration, package lock or environment export, repository
commit, base-model revision, and storage URI in the model card. Source datasets and model artifacts
must remain outside Git; only redacted reports and templates belong in the repository.

## Required inputs

- adjudicated JSONL dataset;
- matching v0.6A audit with `status: ready`, no failures, and zero unresolved labels;
- dataset ID and SHA-256 matching the audit;
- completed source-rights and annotation review evidence.

Both baseline and encoder commands re-hash the dataset and refuse a missing, blocked, or mismatched
audit before fitting a model.

## Experiments

Run the classical baseline first:

```bash
python scripts/evaluate_clause_baseline.py \
  --dataset /secure/clauses-v1.jsonl \
  --dataset-id clauses-v1 \
  --dataset-audit /secure/clauses-v1-audit.json \
  --output /secure/reports/clauses-v1-tfidf.json
```

Then run the legal-domain encoder once the baseline report is retained:

```bash
python scripts/train_clause_classifier.py \
  --dataset /secure/clauses-v1.jsonl \
  --dataset-id clauses-v1 \
  --dataset-audit /secure/clauses-v1-audit.json \
  --output /secure/model-registry/regimpact-clause-v1 \
  --base-model nlpaueb/legal-bert-base-uncased \
  --epochs 3 --seed 42
```

The trainer uses document-isolated partitions, fits temperature scaling and the abstention threshold
on validation data, and evaluates the test set once. Exit code `2` means the artifact was produced
for analysis but failed at least one promotion gate.

## Review and promotion

Before approval, complete the model card and inspect the confusion matrix, every class, regulator
and temporal slices, calibration, abstention workload, mislabeled candidates, and the difference
from the deterministic and TF-IDF baselines. Do not tune hyperparameters after inspecting test
results; create a new experiment plan if another run is required.

An authorized reviewer promotes a qualifying artifact explicitly:

```bash
python scripts/promote_clause_classifier.py \
  --artifact /secure/model-registry/regimpact-clause-v1 \
  --dataset-audit /secure/clauses-v1-audit.json \
  --approver reviewer-id \
  --approved-at 2026-09-04T00:00:00+00:00 \
  --training-commit FULL_40_CHARACTER_GIT_SHA
```

`promotion.json` cryptographically binds the audit, manifest, complete artifact, training commit,
approver, and approval time. Runtime loading fails if the receipt is absent or the manifest/model
files change afterward.

## Reproducible notebook

Open [`notebooks/v0.6b-clause-classifier.ipynb`](../notebooks/v0.6b-clause-classifier.ipynb) from
the repository root. It calls the same tested commands rather than maintaining a second training
implementation. Promotion remains disabled until the explicit approval environment variables are
set.
