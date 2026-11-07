#!/usr/bin/env python3
"""Validate governed adjudication and compile text-free final human labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.human_annotation_adjudication import compile_human_adjudication


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--completed-a", type=Path, required=True)
    parser.add_argument("--completed-b", type=Path, required=True)
    parser.add_argument("--adjudication-package", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--resolved-labels", type=Path, required=True)
    args = parser.parse_args()
    report, records = compile_human_adjudication(
        args.experiment_dir,
        args.completed_a,
        args.completed_b,
        args.adjudication_package,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.resolved_labels.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.resolved_labels.write_text(
        "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in records),
        encoding="utf-8",
    )
    args.report.chmod(0o600)
    args.resolved_labels.chmod(0o600)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
