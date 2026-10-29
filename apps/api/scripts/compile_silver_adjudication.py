#!/usr/bin/env python3
"""Compile governed two-of-three AI silver-label adjudication."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.silver_labeling import compile_silver_adjudication


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(value, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--silver-labels", type=Path, required=True)
    parser.add_argument("--unresolved-review", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    accepted, unresolved, report = compile_silver_adjudication(args.experiment_dir)
    _write_jsonl(args.silver_labels, accepted)
    _write_jsonl(args.unresolved_review, unresolved)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.report.chmod(0o600)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
