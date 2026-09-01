# Obligation extraction baseline

## Purpose

v0.2A introduces an auditable, deterministic baseline for identifying binding duties in immutable regulation versions. It is a precision-oriented candidate generator, not a legal conclusion and not the fine-tuned classifier planned for v0.4.

## Candidate contract

Every stored candidate includes:

- organization, regulation, version and section identifiers;
- exact evidence sentence and source page;
- normalized modality, subject, action and temporal constraint;
- confidence score and the rules that contributed to it;
- extraction-method version and review status;
- source URI and version ordinal through the read API.

Binding patterns cover `must`, `must not`, `shall`, `shall not`, and `is/are required to`. Advisory `may` and `should` statements are excluded by design.

## Confidence calibration

The raw score remains an explainable ranking signal based on binding modality, explicit subject, actionable phrase length, temporal constraints and explicit prohibition. v0.2B maps raw scores through versioned, Laplace-smoothed empirical bins derived from a 24-sentence curated corpus containing 18 extracted candidates. Raw and calibrated values are both retained.

The review threshold is selected as the lowest observed calibrated score that satisfies the policy's minimum precision constraint. Candidates below `0.80` are routed to `needs_review`. The current fixture produces a Brier score and expected calibration error gate in CI, but it is intentionally too small and narrow to establish production calibration quality.

`GET /api/v1/system/calibration-policy` exposes the policy ID, corpus ID, sentence count, candidate count, review threshold, precision constraint and bins. Each obligation and extraction run records the policy ID used.

## Idempotency

The immutable version is locked during extraction. A unique extraction-run record marks completion even when no candidates are found. Candidate fingerprints prevent duplicate evidence rows, and only the first completed run writes an extraction audit event.

## Evaluation

The frozen regression fixture includes positive duties, prohibitions, multiple obligations, advisory language and non-obligation prose. CI requires at least 0.95 precision, 0.90 recall and 0.92 F1 on this small baseline fixture. These numbers prevent regressions but are not evidence of production model quality; broader annotated regulatory corpora are required in v0.2B and v0.4.
