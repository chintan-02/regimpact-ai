#!/usr/bin/env python3
"""Compare independent held-out human annotations and create an adjudication package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.human_annotation_adjudication import compare_human_annotations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--completed-a", type=Path, required=True)
    parser.add_argument("--completed-b", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--adjudication-package", type=Path, required=True)
    args = parser.parse_args()
    report, adjudication = compare_human_annotations(
        args.experiment_dir, args.completed_a, args.completed_b
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.adjudication_package.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.adjudication_package.write_text(
        json.dumps(adjudication, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.report.chmod(0o600)
    args.adjudication_package.chmod(0o600)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
