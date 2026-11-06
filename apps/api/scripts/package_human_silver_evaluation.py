#!/usr/bin/env python3
"""Create a reproducible evidence package for the single-human silver evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.human_evaluation_evidence import package_human_silver_evaluation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--completed", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--implementation-commit", required=True)
    args = parser.parse_args()
    receipt = package_human_silver_evaluation(
        args.experiment_dir,
        args.completed,
        args.output_dir,
        implementation_commit=args.implementation_commit,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
