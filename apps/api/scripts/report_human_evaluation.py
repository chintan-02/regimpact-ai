#!/usr/bin/env python3
"""Validate progress for the single-human held-out evaluation package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.silver_labeling import human_evaluation_progress


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--completed", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = human_evaluation_progress(args.experiment_dir, args.completed)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
