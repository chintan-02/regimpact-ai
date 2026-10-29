#!/usr/bin/env python3
"""Validate returned campaign batches and aggregate progress and agreement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from regimpact.annotation_campaign import campaign_progress_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = campaign_progress_report(args.campaign_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
