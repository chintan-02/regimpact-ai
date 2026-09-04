"""Fine-tune and evaluate a regulatory-clause encoder.

This command never marks an artifact promoted unless the held-out, document-isolated
evaluation and dataset-diversity gates all pass.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from regimpact.classifier_evaluation import ScoredPrediction, evaluate, select_abstention_threshold
from regimpact.classifier_training_governance import load_ready_dataset_audit
from regimpact.clause_classifier import (
    ClauseLabel,
    ModelManifest,
    PromotionPolicy,
    training_recipe_fingerprint,
)
from regimpact.clause_dataset import dataset_summary, load_jsonl, split_by_document

LEARNING_RATE = 2e-5
TRAIN_BATCH_SIZE = 16
EVAL_BATCH_SIZE = 32
WEIGHT_DECAY = 0.01
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-model", default="nlpaueb/legal-bert-base-uncased")
    parser.add_argument("--base-model-revision", required=True)
    parser.add_argument("--training-commit", required=True)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not _GIT_SHA.fullmatch(args.training_commit):
        raise SystemExit("--training-commit must be a full lowercase commit SHA")
    if not args.base_model_revision.strip() or args.base_model_revision == "main":
        raise SystemExit("--base-model-revision must be an immutable model revision, not main")
    started_at = datetime.now(UTC).isoformat()
    try:
        import numpy as np
        from datasets import Dataset
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            DataCollatorWithPadding,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        raise SystemExit("install the API 'ml' extra before training") from exc

    bundle = load_jsonl(args.dataset, dataset_id=args.dataset_id)
    load_ready_dataset_audit(
        args.dataset_audit,
        dataset_id=bundle.dataset_id,
        dataset_sha256=bundle.sha256,
    )
    split = split_by_document(bundle.rows, seed=f"{args.seed}:{args.dataset_id}")
    labels = tuple(ClauseLabel)
    label_to_id = {label: index for index, label in enumerate(labels)}
    tokenizer = AutoTokenizer.from_pretrained(
        args.base_model, revision=args.base_model_revision
    )

    def make_dataset(rows):
        dataset = Dataset.from_dict(
            {
                "text": [row.text for row in rows],
                "label": [label_to_id[row.label] for row in rows],
            }
        )
        return dataset.map(lambda batch: tokenizer(batch["text"], truncation=True), batched=True)

    train_set = make_dataset(split.train)
    validation_set = make_dataset(split.validation)
    test_set = make_dataset(split.test)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model,
        revision=args.base_model_revision,
        num_labels=len(labels),
        id2label={index: label.value for index, label in enumerate(labels)},
        label2id={label.value: index for index, label in enumerate(labels)},
    )
    training_args = TrainingArguments(
        output_dir=str(args.output / "checkpoints"),
        learning_rate=LEARNING_RATE,
        per_device_train_batch_size=TRAIN_BATCH_SIZE,
        per_device_eval_batch_size=EVAL_BATCH_SIZE,
        num_train_epochs=args.epochs,
        weight_decay=WEIGHT_DECAY,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        seed=args.seed,
        report_to="none",
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_set,
        eval_dataset=validation_set,
        processing_class=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
    )
    trainer.train()

    def probabilities(logits, temperature=1.0):
        scaled_logits = logits / temperature
        probabilities = np.exp(scaled_logits - scaled_logits.max(axis=1, keepdims=True))
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        return probabilities

    validation_logits = trainer.predict(validation_set).predictions
    validation_labels = np.array([label_to_id[row.label] for row in split.validation])
    temperatures = np.linspace(0.5, 3.0, 101)
    losses = []
    for temperature in temperatures:
        candidate = probabilities(validation_logits, float(temperature))
        losses.append(-np.log(candidate[np.arange(len(candidate)), validation_labels] + 1e-12).mean())
    temperature = float(temperatures[int(np.argmin(losses))])

    def scored(logits, rows, *, temperature):
        probabilities_ = probabilities(logits, temperature)
        predicted_ids = probabilities_.argmax(axis=1)
        return tuple(
            ScoredPrediction(
                expected=row.label,
                predicted=labels[int(predicted_id)],
                confidence=float(probability[int(predicted_id)]),
            )
            for row, predicted_id, probability in zip(
                rows, predicted_ids, probabilities_, strict=True
            )
        )

    validation_predictions = scored(validation_logits, split.validation, temperature=temperature)
    policy = PromotionPolicy()
    threshold = select_abstention_threshold(
        validation_predictions,
        minimum_covered_accuracy=policy.minimum_covered_accuracy,
        minimum_coverage=policy.minimum_coverage,
    )
    test_logits = trainer.predict(test_set).predictions
    test_report = evaluate(scored(test_logits, split.test, temperature=temperature), confidence_threshold=threshold)
    summary = dataset_summary(bundle.rows)
    training_recipe = {
        "base_model": args.base_model,
        "base_model_revision": args.base_model_revision,
        "dataset_sha256": bundle.sha256,
        "epochs": args.epochs,
        "eval_batch_size": EVAL_BATCH_SIZE,
        "learning_rate": LEARNING_RATE,
        "seed": args.seed,
        "split_strategy": "document-sha256-v1",
        "train_batch_size": TRAIN_BATCH_SIZE,
        "weight_decay": WEIGHT_DECAY,
        "training_commit": args.training_commit,
    }
    recipe_sha256 = training_recipe_fingerprint(training_recipe)
    model_id = (
        f"{args.base_model}@{args.dataset_id}:"
        f"{bundle.sha256[:12]}-{recipe_sha256[:12]}"
    )
    manifest = ModelManifest(
        model_id=model_id,
        base_model=args.base_model,
        dataset_id=args.dataset_id,
        dataset_sha256=bundle.sha256,
        labels=labels,
        confidence_threshold=threshold,
        temperature=temperature,
        example_count=int(summary["examples"]),
        document_count=int(summary["documents"]),
        regulator_count=int(summary["regulators"]),
        macro_f1=test_report.macro_f1,
        per_class_f1={label: metrics["f1"] for label, metrics in test_report.per_class.items()},
        covered_accuracy=test_report.covered_accuracy,
        expected_calibration_error=test_report.expected_calibration_error,
        coverage=test_report.coverage,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    trainer.save_model(args.output)
    tokenizer.save_pretrained(args.output)
    payload = asdict(manifest)
    payload["labels"] = [label.value for label in labels]
    payload["per_class_f1"] = {
        label.value: score for label, score in manifest.per_class_f1.items()
    }
    payload["promotion_failures"] = list(manifest.promotion_failures(policy))
    payload["promoted"] = manifest.promoted
    payload["training_recipe"] = training_recipe
    payload["training_recipe_sha256"] = recipe_sha256
    payload["execution"] = {
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("datasets", "numpy", "torch", "transformers")
        },
    }
    (args.output / "manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    evaluation = {
        "model_id": model_id,
        "dataset_id": bundle.dataset_id,
        "dataset_sha256": bundle.sha256,
        "split_seed": f"{args.seed}:{args.dataset_id}",
        "split_examples": {
            "train": len(split.train),
            "validation": len(split.validation),
            "test": len(split.test),
        },
        "accuracy": test_report.accuracy,
        "macro_f1": test_report.macro_f1,
        "per_class": {
            label.value: metrics for label, metrics in test_report.per_class.items()
        },
        "confusion_matrix": {
            expected.value: {predicted.value: count for predicted, count in values.items()}
            for expected, values in test_report.confusion_matrix.items()
        },
        "expected_calibration_error": test_report.expected_calibration_error,
        "confidence_threshold": threshold,
        "coverage": test_report.coverage,
        "covered_accuracy": test_report.covered_accuracy,
    }
    (args.output / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if manifest.promoted else 2


if __name__ == "__main__":
    raise SystemExit(main())
