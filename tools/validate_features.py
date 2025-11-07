#!/usr/bin/env python3
"""Validate FeaturePipe JSONL output against CoreAlgorithm requirements."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from alpha_core.signals.core_algo import REQUIRED_FIELDS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate feature JSONL against REQUIRED_FIELDS")
    parser.add_argument("--features", required=True, help="Path to features.jsonl")
    parser.add_argument("--limit", type=int, default=5, help="Number of rows to check (default 5)")
    args = parser.parse_args(argv)

    features_path = Path(args.features)
    if not features_path.exists():
        parser.error(f"features file not found: {features_path}")

    required = set(REQUIRED_FIELDS)
    checked = 0
    with features_path.open("r", encoding="utf-8") as fp:
        for line_no, line in enumerate(fp, 1):
            if not line.strip():
                continue
            data = json.loads(line)
            missing = [field for field in required if field not in data]
            if missing:
                print(f"ERROR: line {line_no} missing required fields: {missing}")
                return 1
            checked += 1
            if checked >= args.limit:
                break

    if checked == 0:
        print("WARNING: no valid rows were checked (file may be empty)")
        return 1

    print(f"OK: validated {checked} rows, REQUIRED_FIELDS={sorted(required)}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
