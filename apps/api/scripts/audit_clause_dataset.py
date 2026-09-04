#!/usr/bin/env python3
"""Audit an adjudicated dataset against v0.6 promotion data gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.clause_annotations import AdjudicatedDataset, audit_dataset, load_json_records
from regimpact.clause_dataset import load_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--lineage", type=Path, required=True)
    parser.add_argument("--unresolved", type=Path, required=True)
    parser.add_argument("--agreement-rate", type=float, required=True)
    parser.add_argument("--adjudicated-count", type=int, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--card", type=Path, required=True)
    args = parser.parse_args()
    bundle = load_jsonl(args.dataset, dataset_id=args.dataset_id)
    unresolved = tuple(
        str(item["clause_id"]) for item in load_json_records(args.unresolved)
    )
    result = audit_dataset(
        AdjudicatedDataset(
            rows=bundle.rows,
            lineage=tuple(load_json_records(args.lineage)),
            unresolved_clause_ids=unresolved,
            agreement_rate=args.agreement_rate,
            adjudicated_count=args.adjudicated_count,
        )
    )
    result["dataset_id"] = args.dataset_id
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    failures = "None" if not result["failures"] else ", ".join(result["failures"])
    args.card.write_text(
        "# Clause dataset card\n\n"
        f"- Dataset: `{args.dataset_id}`\n"
        f"- Status: **{result['status']}**\n"
        f"- SHA-256: `{result['dataset_sha256']}`\n"
        f"- Examples: {result['examples']}\n"
        f"- Documents: {result['documents']}\n"
        f"- Regulators: {result['regulators']}\n"
        f"- Raw dual-annotation agreement: {result['agreement_rate']:.2%}\n"
        f"- Adjudicated disagreements: {result['adjudicated_count']}\n"
        f"- Blocking findings: {failures}\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "ready":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
