#!/usr/bin/env python3
"""Create a deterministic, batched production annotation campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.annotation_campaign import prepare_campaign
from regimpact.annotation_sampling import load_candidate_queue, verify_candidate_queue


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--queue-receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--campaign-id", default="v0.6c6-production-v1")
    parser.add_argument("--target", type=int, default=700)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--seed", default="v0.6c6-production-v1")
    args = parser.parse_args()

    candidates = load_candidate_queue(args.candidates)
    receipt = verify_candidate_queue(candidates, args.queue_receipt)
    manifest = prepare_campaign(
        candidates,
        candidate_queue_sha256=str(receipt["candidate_queue_sha256"]),
        output_dir=args.output_dir,
        campaign_id=args.campaign_id,
        target=args.target,
        batch_size=args.batch_size,
        seed=args.seed,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
