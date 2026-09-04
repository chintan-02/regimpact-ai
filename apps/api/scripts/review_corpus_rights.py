#!/usr/bin/env python3
"""Prepare or finalize the governed human source-rights review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from regimpact.corpus_acquisition import load_corpus_manifest, verify_acquisition_lock
from regimpact.rights_review import (
    finalize_rights_review,
    load_rights_review,
    prepare_rights_review,
    review_packet_payload,
    verify_review_coverage,
)


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "validate", "finalize"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--approvals", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--require-pending", action="store_true")
    args = parser.parse_args()

    documents = load_corpus_manifest(args.manifest)
    lock = verify_acquisition_lock(documents, args.lock)
    if args.command == "prepare":
        _write(args.review, review_packet_payload(prepare_rights_review(documents, lock)))
        print(json.dumps({"documents": len(documents), "status": "pending_human_review"}))
        return

    records = load_rights_review(args.review)
    verify_review_coverage(documents, lock, records)
    if args.command == "validate":
        decisions = {decision: 0 for decision in ("approved", "rejected", "pending")}
        for record in records:
            decisions[record.decision] += 1
        if args.require_pending and decisions != {"approved": 0, "rejected": 0, "pending": 25}:
            parser.error("checked-in review packet must contain exactly 25 pending decisions")
        print(json.dumps({"documents": len(records), "decisions": decisions}, sort_keys=True))
        return

    if not args.registry or not args.approvals or not args.receipt:
        parser.error("finalize requires --registry, --approvals and --receipt")
    registry, approvals, receipt = finalize_rights_review(documents, lock, records)
    _write(args.registry, registry)
    _write(args.approvals, approvals)
    _write(args.receipt, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
