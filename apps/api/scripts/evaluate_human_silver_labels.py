#!/usr/bin/env python3
"""Evaluate both silver labelers against the single-human held-out reference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.silver_labeling import evaluate_human_silver_labels


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--completed", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--disagreements", "--errors", dest="disagreements", type=Path, required=True)
    args = parser.parse_args()
    report, records = evaluate_human_silver_labels(args.experiment_dir, args.completed)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.disagreements.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.disagreements.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
