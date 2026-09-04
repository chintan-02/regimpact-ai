#!/usr/bin/env python3
"""Export two complete blinded packages to adjudication-compatible JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.annotation_sampling import export_completed_annotations
from regimpact.clause_annotations import write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--package-a", type=Path, required=True)
    parser.add_argument("--package-b", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    args = parser.parse_args()
    annotations, report = export_completed_annotations(args.sample, args.package_a, args.package_b)
    write_jsonl(args.annotations, annotations)
    print(
        json.dumps(
            {
                "status": "ready_for_adjudication",
                "annotations": len(annotations),
                "sample_count": report["sample_count"],
                "agreements": report["agreements"],
                "disagreements": report["disagreements"],
                "model_training_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
