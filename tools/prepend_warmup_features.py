#!/usr/bin/env python3
"""Prepend warmup history (2-5 minutes) to features file for smoke testing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    from alpha_core.signals.core_algo import REQUIRED_FIELDS
except ImportError:
    REQUIRED_FIELDS = ["ts_ms", "symbol", "z_ofi", "z_cvd", "spread_bps", "lag_sec", "consistency", "warmup"]


def find_warmup_features(preview_root: Path, symbols: list[str], target_start_ms: int, warmup_minutes: int = 3) -> list[dict]:
    """Find warmup features from preview data before target_start_ms."""
    warmup_end_ms = target_start_ms
    warmup_start_ms = target_start_ms - (warmup_minutes * 60 * 1000)
    
    required_fields_set = set(REQUIRED_FIELDS)
    warmup_records = []
    for sym in symbols:
        pattern = preview_root.glob(f"date=*/hour=*/symbol={sym}/kind=features/*.parquet")
        for fp in sorted(pattern):
            try:
                import pandas as pd
                df = pd.read_parquet(fp)
                if df.empty:
                    continue
                if "ts_ms" not in df.columns:
                    continue
                df_filtered = df[(df["ts_ms"] >= warmup_start_ms) & (df["ts_ms"] < warmup_end_ms)]
                if not df_filtered.empty:
                    for _, row in df_filtered.iterrows():
                        record = row.to_dict()
                        # Convert NaN to None and filter out None values for required fields
                        import math
                        for key, value in list(record.items()):
                            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                                record[key] = None
                        # Only include records with all required fields present and not None
                        record_fields = set(record.keys())
                        missing = required_fields_set - record_fields
                        if not missing:
                            # Check that required fields are not None
                            has_all_values = all(record.get(field) is not None for field in required_fields_set)
                            if has_all_values:
                                warmup_records.append(record)
            except Exception:
                continue
    
    warmup_records.sort(key=lambda x: int(x.get("ts_ms", 0)))
    return warmup_records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepend warmup history to features file")
    parser.add_argument("--features", required=True, help="Path to features.jsonl file")
    parser.add_argument("--preview-root", required=True, help="Path to preview data root")
    parser.add_argument("--symbols", nargs="+", required=True, help="Symbol list")
    parser.add_argument("--warmup-minutes", type=int, default=3, help="Warmup minutes (default 3)")
    parser.add_argument("--output", help="Output file path (default: overwrite input)")
    args = parser.parse_args(argv)

    features_path = Path(args.features)
    if not features_path.exists():
        parser.error(f"features file not found: {features_path}")
    
    preview_root = Path(args.preview_root)
    if not preview_root.exists():
        parser.error(f"preview root not found: {preview_root}")

    # Read existing features to find start time
    first_ts_ms = None
    with features_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                ts_ms = record.get("ts_ms")
                if isinstance(ts_ms, (int, float)):
                    first_ts_ms = int(ts_ms)
                    break
            except Exception:
                continue
    
    if first_ts_ms is None:
        print("WARNING: Could not determine start time from features file, skipping warmup")
        return 0

    # Find warmup records
    warmup_records = find_warmup_features(preview_root, args.symbols, first_ts_ms, args.warmup_minutes)
    
    if not warmup_records:
        print(f"WARNING: No warmup records found for {args.warmup_minutes} minutes before {first_ts_ms}")
        return 0

    # Read all existing features
    existing_records = []
    with features_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                existing_records.append(record)
            except Exception:
                continue

    # Combine warmup + existing
    output_path = Path(args.output) if args.output else features_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open("w", encoding="utf-8") as f:
        for record in warmup_records + existing_records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            f.write("\n")

    print(f"Prepended {len(warmup_records)} warmup records ({args.warmup_minutes} minutes) to {output_path}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))

