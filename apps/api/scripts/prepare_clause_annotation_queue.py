#!/usr/bin/env python3
"""Build a rights-approved, lineage-preserving annotation queue."""

from __future__ import annotations

import argparse
from pathlib import Path

from regimpact.clause_annotations import (
    build_candidates,
    load_sections,
    load_source_registry,
    write_jsonl,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--sections", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidates = build_candidates(load_source_registry(args.sources), load_sections(args.sections))
    write_jsonl(args.output, candidates)
    print(f"wrote {len(candidates)} candidates to {args.output}")


if __name__ == "__main__":
    main()
