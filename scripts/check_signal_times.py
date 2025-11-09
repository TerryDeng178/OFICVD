#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check signal timestamps"""
import json
from pathlib import Path
from datetime import datetime

def check_signals(signal_dir: Path, name: str):
    """Check signal timestamps"""
    print(f"\n检查 {name} 信号:")
    files = list(signal_dir.rglob("*.jsonl"))[:5]
    if not files:
        print("  未找到文件")
        return
    
    all_times = []
    all_run_ids = set()
    for f in files:
        with f.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    s = json.loads(line)
                    ts_ms = s.get("ts_ms", 0)
                    if ts_ms > 0:
                        all_times.append(ts_ms)
                    run_id = s.get("run_id")
                    if run_id:
                        all_run_ids.add(run_id)
                except:
                    pass
    
    if all_times:
        min_ts = min(all_times)
        max_ts = max(all_times)
        print(f"  时间范围: {datetime.fromtimestamp(min_ts/1000)} - {datetime.fromtimestamp(max_ts/1000)}")
        print(f"  时间戳范围: {min_ts} - {max_ts}")
        print(f"  信号数: {len(all_times)}")
    if all_run_ids:
        print(f"  Run IDs: {sorted(list(all_run_ids))[:5]}")

if __name__ == "__main__":
    check_signals(Path("runtime/backtest/integration_20251109_051348/signals"), "回测")
    check_signals(Path("runtime/ready/signal"), "生产")

