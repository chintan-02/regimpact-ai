#!/usr/bin/env python3
"""Compile two validated AI response streams into silver consensus and review queues."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.silver_labeling import compile_silver_consensus


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(value, sort_keys=True) + "\n" for value in values))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--silver-labels", type=Path, required=True)
    parser.add_argument("--review-queue", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--minimum-confidence", type=float)
    args = parser.parse_args()
    accepted, review, report = compile_silver_consensus(
        args.experiment_dir, minimum_confidence=args.minimum_confidence
    )
    _write_jsonl(args.silver_labels, accepted)
    _write_jsonl(args.review_queue, review)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
