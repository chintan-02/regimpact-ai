"""Approve a qualifying clause-classifier artifact and write its evidence receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.classifier_training_governance import promote_artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--dataset-audit", type=Path, required=True)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--approved-at", required=True)
    parser.add_argument("--training-commit", required=True)
    args = parser.parse_args()
    receipt = promote_artifact(
        args.artifact,
        dataset_audit_path=args.dataset_audit,
        approver=args.approver,
        approved_at=args.approved_at,
        training_commit=args.training_commit,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
