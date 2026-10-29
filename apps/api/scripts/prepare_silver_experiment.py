#!/usr/bin/env python3
"""Prepare governed dual-AI weak supervision and a human evaluation workspace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.silver_labeling import prepare_silver_experiment


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--labeler-a-id", required=True)
    parser.add_argument("--model-a", required=True)
    parser.add_argument("--labeler-b-id", required=True)
    parser.add_argument("--model-b", required=True)
    parser.add_argument("--evaluation-size", type=int, default=70)
    parser.add_argument("--seed", default="v0.6c7-silver-v1")
    args = parser.parse_args()
    result = prepare_silver_experiment(
        args.campaign_dir,
        args.output_dir,
        labeler_a_id=args.labeler_a_id,
        model_a=args.model_a,
        labeler_b_id=args.labeler_b_id,
        model_b=args.model_b,
        evaluation_size=args.evaluation_size,
        seed=args.seed,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
