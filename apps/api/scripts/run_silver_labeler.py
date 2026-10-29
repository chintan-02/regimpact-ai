#!/usr/bin/env python3
"""Run a resumable silver-label stream through an OpenAI-compatible API."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from regimpact.silver_labeling import run_openai_compatible_labeler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--labeler-id", required=True)
    parser.add_argument("--api-key-env")
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()
    api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
    if args.api_key_env and not api_key:
        parser.error(f"environment variable is not set: {args.api_key_env}")
    report = run_openai_compatible_labeler(
        args.requests,
        args.responses,
        base_url=args.base_url,
        model_id=args.model,
        labeler_id=args.labeler_id,
        api_key=api_key,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
