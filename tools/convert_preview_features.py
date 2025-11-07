#!/usr/bin/env python3
"""Convert preview feature parquet files to JSONL for smoke testing.

Usage:
    python tools/convert_preview_features.py \
        --preview-root ./deploy/data/ofi_cvd/preview \
        --symbols BTCUSDT ETHUSDT \
        --output ./runtime/features.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import pandas as pd


def safe_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    if pd.isna(value):  # type: ignore[arg-type]
        return default
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    if pd.isna(value):  # type: ignore[arg-type]
        return default
    try:
        return int(value)
    except Exception:
        return default


def collect_feature_files(root: Path, symbols: list[str]) -> list[Path]:
    files: list[Path] = []
    for sym in symbols:
        pattern = f"date=*/hour=*/symbol={sym}/kind=features/*.parquet"
        files.extend(sorted(root.glob(pattern)))
    return files


def convert_to_feature_rows(df: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in df.to_dict(orient="records"):
        ts_ms = safe_int(record.get("ts_ms"))
        if ts_ms == 0 and record.get("second_ts") is not None:
            ts_ms = safe_int(record.get("second_ts")) * 1000
        symbol = record.get("symbol")
        price = record.get("mid")
        z_ofi_raw = record.get("ofi_z")
        z_cvd_raw = record.get("cvd_z")
        z_ofi = safe_float(z_ofi_raw)
        z_cvd = safe_float(z_cvd_raw)
        spread_bps = record.get("spread_bps")
        if spread_bps is None or pd.isna(spread_bps):  # type: ignore[arg-type]
            best_bid = record.get("best_bid") or record.get("best_buy_fill")
            best_ask = record.get("best_ask") or record.get("best_sell_fill")
            if best_bid is not None and best_ask is not None:
                try:
                    spread_bps = (float(best_ask) - float(best_bid)) / float(best_bid) * 1e4
                except Exception:
                    spread_bps = 0.0
            else:
                spread_bps = 0.0
        lag_ms = record.get("lag_ms_fusion")
        if lag_ms is None or pd.isna(lag_ms):  # type: ignore[arg-type]
            lag_ms = record.get("lag_ms_ofi") or 0.0
        lag_sec = safe_float(lag_ms) / 1000.0
        fusion_score = safe_float(record.get("fusion_score"))
        consistency = safe_float(record.get("consistency"))
        warmup = bool((z_ofi_raw is None or pd.isna(z_ofi_raw)) or (z_cvd_raw is None or pd.isna(z_cvd_raw)))  # type: ignore[arg-type]
        activity_tps = safe_float(record.get("activity_tps") or record.get("tps"))
        dispersion = safe_float(record.get("dispersion"))
        sign_agree = safe_float(record.get("sign_agree"))
        reason_codes = record.get("reason_codes") or []
        if isinstance(reason_codes, float) and math.isnan(reason_codes):
            reason_codes = []
        if isinstance(reason_codes, str):
            reason_codes = [reason_codes]
        row = {
            "ts_ms": ts_ms,
            "symbol": symbol,
            "price": price,
            "z_ofi": z_ofi,
            "z_cvd": z_cvd,
            "spread_bps": safe_float(spread_bps),
            "fusion_score": fusion_score,
            "consistency": consistency,
            "warmup": warmup,
            "lag_sec": lag_sec,
            "div_type": record.get("div_type"),
            "activity": {"tps": activity_tps},
            "reason_codes": reason_codes,
            "dispersion": dispersion,
            "sign_agree": int(sign_agree),
            "signal": record.get("signal") or "neutral",
        }
        rows.append(row)
    return rows


def convert_to_jsonl(files: list[Path], output_path: Path) -> int:
    count = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fp:
        for file_path in files:
            df = pd.read_parquet(file_path)
            if df.empty:
                continue
            feature_rows = convert_to_feature_rows(df)
            if not feature_rows:
                continue
            for row in feature_rows:
                fp.write(json.dumps(row, ensure_ascii=False))
                fp.write("\n")
            count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert preview feature parquet files to JSONL")
    parser.add_argument("--preview-root", required=True, help="Path to deploy/data/ofi_cvd/preview root")
    parser.add_argument("--symbols", nargs="+", required=True, help="Symbol list")
    parser.add_argument("--output", required=True, help="Output JSONL file path")
    args = parser.parse_args(argv)

    preview_root = Path(args.preview_root)
    if not preview_root.exists():
        parser.error(f"preview root not found: {preview_root}")

    output_path = Path(args.output)
    files = collect_feature_files(preview_root, args.symbols)
    if not files:
        print("ERROR: no preview feature files found", file=sys.stderr)
        return 1

    converted = convert_to_jsonl(files, output_path)
    print(f"wrote {converted} preview feature files -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
