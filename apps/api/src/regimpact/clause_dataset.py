"""Versioned clause-dataset loading and document-isolated splitting."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .clause_classifier import ClauseLabel, LabelledClause, dataset_fingerprint


@dataclass(frozen=True, slots=True)
class DatasetBundle:
    dataset_id: str
    rows: tuple[LabelledClause, ...]
    sha256: str


@dataclass(frozen=True, slots=True)
class DatasetSplit:
    train: tuple[LabelledClause, ...]
    validation: tuple[LabelledClause, ...]
    test: tuple[LabelledClause, ...]

    def __post_init__(self) -> None:
        groups = [
            {row.document_id for row in self.train},
            {row.document_id for row in self.validation},
            {row.document_id for row in self.test},
        ]
        if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
            raise ValueError("document leakage detected across dataset splits")


def load_jsonl(path: Path, *, dataset_id: str) -> DatasetBundle:
    rows: list[LabelledClause] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            row = LabelledClause(
                clause_id=value["clause_id"],
                document_id=value["document_id"],
                regulator=value["regulator"],
                text=value["text"],
                label=ClauseLabel(value["label"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid annotation at line {line_number}: {exc}") from exc
        if row.clause_id in seen:
            raise ValueError(f"duplicate clause_id: {row.clause_id}")
        seen.add(row.clause_id)
        rows.append(row)
    if not rows:
        raise ValueError("dataset must contain at least one annotation")
    frozen = tuple(rows)
    return DatasetBundle(dataset_id=dataset_id, rows=frozen, sha256=dataset_fingerprint(frozen))


def _bucket(document_id: str, seed: str) -> int:
    return int(sha256(f"{seed}:{document_id}".encode()).hexdigest()[:8], 16) % 100


def split_by_document(
    rows: tuple[LabelledClause, ...],
    *,
    seed: str = "regimpact-v0.6",
    train_percent: int = 70,
    validation_percent: int = 15,
) -> DatasetSplit:
    """Assign complete documents to deterministic train/validation/test partitions."""
    if not 1 <= train_percent < 100 or not 1 <= validation_percent < 100:
        raise ValueError("split percentages must be between one and 99")
    if train_percent + validation_percent >= 100:
        raise ValueError("train and validation percentages must leave a test partition")
    partitions: list[list[LabelledClause]] = [[], [], []]
    for row in rows:
        value = _bucket(row.document_id, seed)
        index = 0 if value < train_percent else 1 if value < train_percent + validation_percent else 2
        partitions[index].append(row)
    split = DatasetSplit(*(tuple(items) for items in partitions))
    if any(not items for items in (split.train, split.validation, split.test)):
        raise ValueError("each dataset partition must contain at least one document")
    return split


def dataset_summary(rows: tuple[LabelledClause, ...]) -> dict[str, object]:
    return {
        "examples": len(rows),
        "documents": len({row.document_id for row in rows}),
        "regulators": len({row.regulator for row in rows}),
        "labels": dict(sorted(Counter(row.label.value for row in rows).items())),
    }
