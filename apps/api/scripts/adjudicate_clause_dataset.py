#!/usr/bin/env python3
"""Resolve dual annotations into a versioned training dataset and lineage ledger."""

from __future__ import annotations

import argparse
from pathlib import Path

from regimpact.clause_annotations import (
    ClauseCandidate,
    adjudicate_annotations,
    load_adjudications,
    load_annotations,
    load_json_records,
    write_jsonl,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--adjudications", type=Path)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--lineage", type=Path, required=True)
    parser.add_argument("--unresolved", type=Path, required=True)
    args = parser.parse_args()
    candidates = tuple(ClauseCandidate(**item) for item in load_json_records(args.candidates))
    decisions = load_adjudications(args.adjudications) if args.adjudications else ()
    result = adjudicate_annotations(candidates, load_annotations(args.annotations), decisions)
    write_jsonl(args.dataset, result.rows)
    write_jsonl(args.lineage, result.lineage)
    write_jsonl(args.unresolved, ({"clause_id": item} for item in result.unresolved_clause_ids))
    print(
        f"resolved={len(result.rows)} unresolved={len(result.unresolved_clause_ids)} "
        f"agreement_rate={result.agreement_rate:.4f}"
    )


if __name__ == "__main__":
    main()
