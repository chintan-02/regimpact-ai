#!/usr/bin/env python3
"""Export a complete production campaign into adjudication-compatible JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.annotation_campaign import export_campaign_annotations
from regimpact.clause_annotations import write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    args = parser.parse_args()
    annotations, report = export_campaign_annotations(args.campaign_dir)
    write_jsonl(args.annotations, annotations)
    print(
        json.dumps(
            {
                "status": "ready_for_adjudication",
                "annotations": len(annotations),
                "clauses": report["target"],
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
