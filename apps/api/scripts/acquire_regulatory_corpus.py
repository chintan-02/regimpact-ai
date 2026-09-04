#!/usr/bin/env python3
"""Acquire the pinned v0.6C-1 corpus and write hash-bound evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.corpus_acquisition import (
    acquire_corpus,
    load_corpus_manifest,
    verify_acquisition_lock,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    documents = load_corpus_manifest(args.manifest)
    if args.validate_only:
        lock = verify_acquisition_lock(documents, args.lock) if args.lock else None
        print(
            json.dumps(
                {
                    "documents": len(documents),
                    "lock_verified": lock is not None,
                    "status": "valid",
                },
                sort_keys=True,
            )
        )
        return
    receipt = acquire_corpus(documents, output_dir=args.output_dir)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
