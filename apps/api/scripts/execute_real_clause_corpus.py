#!/usr/bin/env python3
"""Verify real source evidence and create an immutable annotation queue receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.clause_annotations import load_source_registry, write_jsonl
from regimpact.corpus_execution import execute_corpus, load_source_approvals


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--approvals", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--sections", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    candidates, receipt = execute_corpus(
        load_source_registry(args.sources),
        load_source_approvals(args.approvals),
        artifact_root=args.artifact_root,
        sections_path=args.sections,
    )
    write_jsonl(args.candidates, candidates)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
