#!/usr/bin/env python3
"""Summarize CORE_ALGO signal outputs written to JSONL files."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


def _safe_load(line: str) -> Dict[str, object] | None:
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except Exception:
        return None


def summarize(signal_dir: Path) -> dict:
    files = sorted(signal_dir.rglob("signals_*.jsonl"))
    total_lines = 0
    confirm_count = 0
    gating_count = 0
    symbol_totals: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "confirm": 0, "gated": 0, "suppressed": 0})
    guard_reason_counter: Counter[str] = Counter()
    signal_type_counter: Counter[str] = Counter()
    guard_symbol_regime_counter: Counter[Tuple[str, str, str]] = Counter()
    min_ts: int | None = None
    max_ts: int | None = None
    sample_record: dict[str, object] | None = None
    regime_counter: Counter[str] = Counter()
    regime_by_symbol: Dict[str, Counter[str]] = defaultdict(Counter)
    heatmap: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for fp in files:
        symbol = fp.parent.name
        with fp.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                record = _safe_load(raw_line)
                if record is None:
                    continue
                total_lines += 1
                ts_val = record.get("ts_ms")
                if isinstance(ts_val, (int, float)):
                    ts_int = int(ts_val)
                    if min_ts is None or ts_int < min_ts:
                        min_ts = ts_int
                    if max_ts is None or ts_int > max_ts:
                        max_ts = ts_int
                regime = record.get("regime")
                if isinstance(regime, str) and regime:
                    regime_counter[regime] += 1
                    regime_by_symbol[symbol][regime] += 1
                else:
                    regime_counter["<none>"] += 1
                    regime_by_symbol[symbol]["<none>"] += 1
                if sample_record is None:
                    sample_record = record.copy()
                confirm = bool(record.get("confirm"))
                gating = bool(record.get("gating"))
                guard_reason = record.get("guard_reason")
                signal_type = record.get("signal_type")
                symbol_stats = symbol_totals[symbol]
                symbol_stats["total"] += 1
                if confirm:
                    confirm_count += 1
                    symbol_stats["confirm"] += 1
                else:
                    symbol_stats["suppressed"] += 1
                    if gating:
                        gating_count += 1
                        symbol_stats["gated"] += 1
                        reason = guard_reason if isinstance(guard_reason, str) and guard_reason else "<none>"
                        guard_reason_counter[reason] += 1
                        regime = record.get("regime")
                        if not isinstance(regime, str) or not regime:
                            regime = "<none>"
                        guard_symbol_regime_counter[(symbol, regime, reason)] += 1
                        heatmap[(symbol, regime)][reason] += 1
                    elif isinstance(guard_reason, str) and guard_reason:
                        guard_reason_counter[guard_reason] += 1
                if isinstance(signal_type, str) and signal_type:
                    signal_type_counter[signal_type] += 1

    suppressed_count = total_lines - confirm_count
    summary = {
        "files": len(files),
        "total_lines": total_lines,
        "confirm": confirm_count,
        "suppressed": suppressed_count,
        "gated": gating_count,
        "symbols": symbol_totals,
        "guard_reasons": guard_reason_counter.most_common(),
        "guard_symbol_regime": [(sym, regime, reason, count) for (sym, regime, reason), count in guard_symbol_regime_counter.most_common()],
        "signal_types": signal_type_counter.most_common(),
        "regime_distribution": dict(regime_counter.most_common()),
        "regime_by_symbol": {sym: dict(regime_counter.most_common()) for sym, regime_counter in regime_by_symbol.items()},
        "heatmap": {f"{sym}/{regime}": dict(reasons) for (sym, regime), reasons in heatmap.items()},
        "min_ts": min_ts,
        "max_ts": max_ts,
        "sample_record": sample_record,
        "sample_file": str(files[-1]) if files else None,
    }
    return summary


def print_summary(summary: dict) -> None:
    print("files:", summary["files"])
    print("total lines:", summary["total_lines"])
    print("confirm:", summary["confirm"])
    print("suppressed:", summary["suppressed"])
    print("gated:", summary["gated"])
    if summary["symbols"]:
        print("per symbol totals:")
        for sym in sorted(summary["symbols"].keys()):
            stats = summary["symbols"][sym]
            print(f"  {sym}: total={stats['total']} confirm={stats['confirm']} gated={stats['gated']} suppressed={stats['suppressed']}")
    guards: List = summary["guard_reasons"] or []
    if guards:
        print("guard_reason top5:")
        for reason, count in guards[:5]:
            print(f"  {reason}: {count}")
    signal_types: List = summary["signal_types"] or []
    if signal_types:
        print("signal_type distribution (top5):")
        for sig, count in signal_types[:5]:
            print(f"  {sig}: {count}")
    regime_dist = summary.get("regime_distribution")
    if regime_dist:
        print("regime distribution:")
        for regime, count in sorted(regime_dist.items(), key=lambda x: -x[1])[:5]:
            print(f"  {regime}: {count}")
    regime_by_sym = summary.get("regime_by_symbol")
    if regime_by_sym:
        print("regime by symbol (top3 per symbol):")
        for sym in sorted(regime_by_sym.keys())[:3]:
            regimes = regime_by_sym[sym]
            print(f"  {sym}: {dict(sorted(regimes.items(), key=lambda x: -x[1])[:3])}")
    sample = summary.get("sample_record")
    if sample:
        print("sample record (first row):")
        sample_str = json.dumps(sample, ensure_ascii=False, indent=2)
        for line in sample_str.split("\n")[:10]:
            print(f"  {line}")
    heatmap_data = summary.get("heatmap")
    if heatmap_data:
        print("guard heatmap (top5 symbol/regime combinations):")
        heatmap_items = []
        for key, reasons in heatmap_data.items():
            total = sum(reasons.values())
            top_reason = max(reasons.items(), key=lambda x: x[1]) if reasons else ("<none>", 0)
            heatmap_items.append((key, total, top_reason[0], top_reason[1]))
        heatmap_items.sort(key=lambda x: -x[1])
        for key, total, top_reason, top_count in heatmap_items[:5]:
            print(f"  {key}: total={total}, top_reason={top_reason}({top_count})")
    if summary["sample_file"]:
        print("sample file:", summary["sample_file"])


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize JSONL signal outputs")
    parser.add_argument("--signal-dir", required=True, help="Path to signal directory (ready/signal)")
    parser.add_argument("--summary-json", help="Optional path to write JSON summary")
    args = parser.parse_args(argv)

    signal_dir = Path(args.signal_dir)
    if not signal_dir.exists():
        parser.error(f"signal directory not found: {signal_dir}")

    summary = summarize(signal_dir)
    print_summary(summary)

    if args.summary_json:
        out_path = Path(args.summary_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fp:
            json.dump(summary, fp, ensure_ascii=False, indent=2)

    # return 1 when no lines were processed to signal missing data
    if summary["total_lines"] == 0:
        return 1
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
