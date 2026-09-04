#!/usr/bin/env python3
"""Create a deterministic pilot sample and two blinded annotation packages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.annotation_sampling import (
    build_blinded_package,
    load_candidate_queue,
    sample_payload,
    sample_pilot,
    sampling_report,
    verify_candidate_queue,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--queue-receipt", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--package-a", type=Path, required=True)
    parser.add_argument("--package-b", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--target", type=int, default=350)
    parser.add_argument("--seed", default="v0.6c4-pilot-v1")
    args = parser.parse_args()

    candidates = load_candidate_queue(args.candidates)
    receipt = verify_candidate_queue(candidates, args.queue_receipt)
    sample = sample_pilot(candidates, target=args.target, seed=args.seed)
    queue_hash = str(receipt["candidate_queue_sha256"])
    _write_json(
        args.sample,
        {"schema_version": "regimpact-sampled-clauses-v1", "records": sample_payload(sample)},
    )
    _write_json(
        args.package_a,
        build_blinded_package(sample, slot="A", seed=args.seed, candidate_queue_sha256=queue_hash),
    )
    _write_json(
        args.package_b,
        build_blinded_package(sample, slot="B", seed=args.seed, candidate_queue_sha256=queue_hash),
    )
    report = sampling_report(candidates, sample, seed=args.seed)
    _write_json(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
