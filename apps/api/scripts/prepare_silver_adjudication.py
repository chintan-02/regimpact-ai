#!/usr/bin/env python3
"""Prepare an immutable third-model adjudication stream."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.silver_labeling import prepare_silver_adjudication


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--labeler-c-id", required=True)
    parser.add_argument("--model-c", required=True)
    parser.add_argument("--minimum-confidence", type=float)
    args = parser.parse_args()
    manifest = prepare_silver_adjudication(
        args.experiment_dir,
        labeler_c_id=args.labeler_c_id,
        model_c=args.model_c,
        minimum_confidence=args.minimum_confidence,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
