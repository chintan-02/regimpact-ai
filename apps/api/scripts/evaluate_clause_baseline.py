"""Evaluate the TF-IDF/logistic-regression baseline on document-isolated data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.classifier_evaluation import ScoredPrediction, evaluate
from regimpact.classifier_training_governance import load_ready_dataset_audit
from regimpact.clause_classifier import ClauseLabel
from regimpact.clause_dataset import load_jsonl, split_by_document


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", default="regimpact-v0.6-baseline")
    parser.add_argument("--confidence-threshold", type=float, default=0.80)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
    except ImportError as exc:
        raise SystemExit("install the API 'ml' extra before baseline evaluation") from exc

    bundle = load_jsonl(args.dataset, dataset_id=args.dataset_id)
    load_ready_dataset_audit(
        args.dataset_audit,
        dataset_id=bundle.dataset_id,
        dataset_sha256=bundle.sha256,
    )
    split = split_by_document(bundle.rows, seed=args.seed)
    train_labels = {row.label for row in split.train}
    missing = set(ClauseLabel) - train_labels
    if missing:
        names = ", ".join(sorted(label.value for label in missing))
        raise SystemExit(f"training split is missing labels: {names}")

    model = Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=2_000,
                    random_state=42,
                ),
            ),
        ]
    )
    model.fit([row.text for row in split.train], [row.label.value for row in split.train])
    probabilities = model.predict_proba([row.text for row in split.test])
    classes = tuple(ClauseLabel(value) for value in model.classes_)
    predictions = tuple(
        ScoredPrediction(
            expected=row.label,
            predicted=classes[int(scores.argmax())],
            confidence=float(scores.max()),
        )
        for row, scores in zip(split.test, probabilities, strict=True)
    )
    report = evaluate(predictions, confidence_threshold=args.confidence_threshold)
    payload = {
        "baseline": "tfidf-logistic-regression-v1",
        "dataset_id": bundle.dataset_id,
        "dataset_sha256": bundle.sha256,
        "split_seed": args.seed,
        "train_documents": len({row.document_id for row in split.train}),
        "validation_documents": len({row.document_id for row in split.validation}),
        "test_documents": len({row.document_id for row in split.test}),
        "macro_f1": report.macro_f1,
        "accuracy": report.accuracy,
        "expected_calibration_error": report.expected_calibration_error,
        "confidence_threshold": report.confidence_threshold,
        "coverage": report.coverage,
        "covered_accuracy": report.covered_accuracy,
        "per_class": {
            label.value: metrics for label, metrics in report.per_class.items()
        },
        "confusion_matrix": {
            expected.value: {predicted.value: count for predicted, count in values.items()}
            for expected, values in report.confusion_matrix.items()
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
