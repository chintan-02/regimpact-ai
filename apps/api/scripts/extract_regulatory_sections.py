#!/usr/bin/env python3
"""Extract stable section records from approved Justice Canada XML artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.clause_annotations import load_source_registry, write_jsonl
from regimpact.corpus_execution import load_source_approvals
from regimpact.xml_section_extraction import extract_approved_corpus_sections


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--approvals", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--sections", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    sections, receipt = extract_approved_corpus_sections(
        load_source_registry(args.sources),
        load_source_approvals(args.approvals),
        artifact_root=args.artifact_root,
    )
    write_jsonl(args.sections, sections)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
