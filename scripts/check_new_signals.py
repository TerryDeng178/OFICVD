#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check new production signals"""
import json
from pathlib import Path
from datetime import datetime

def check_signals():
    """Check new production signals"""
    signal_dir = Path("runtime/ready/signal")
    if not signal_dir.exists():
        print("Signal directory not found")
        return
    
    # Find recent files (last 2 hours)
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(hours=2)
    
    files = list(signal_dir.rglob("*.jsonl"))
    recent_files = [f for f in files if datetime.fromtimestamp(f.stat().st_mtime) > cutoff]
    
    print(f"Total signal files: {len(files)}")
    print(f"Recent files (last 2 hours): {len(recent_files)}")
    
    if recent_files:
        print("\nChecking recent files...")
        all_times = []
        for f in recent_files[:5]:
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
                            if len(all_times) >= 10:
                                break
                    except:
                        pass
                if len(all_times) >= 10:
                    break
        
        if all_times:
            min_ts = min(all_times)
            max_ts = max(all_times)
            print(f"\nTime range: {datetime.fromtimestamp(min_ts/1000)} - {datetime.fromtimestamp(max_ts/1000)}")
            print(f"Timestamp range: {min_ts} - {max_ts}")
    
    # Check backtest time range
    backtest_dir = Path("runtime/backtest/integration_20251109_051348/signals")
    if backtest_dir.exists():
        print("\nChecking backtest signals...")
        backtest_times = []
        for f in list(backtest_dir.rglob("*.jsonl"))[:1]:
            with f.open("r", encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        s = json.loads(line)
                        ts_ms = s.get("ts_ms", 0)
                        if ts_ms > 0:
                            backtest_times.append(ts_ms)
                            if len(backtest_times) >= 10:
                                break
                    except:
                        pass
                if len(backtest_times) >= 10:
                    break
        
        if backtest_times:
            min_ts = min(backtest_times)
            max_ts = max(backtest_times)
            print(f"\nBacktest time range: {datetime.fromtimestamp(min_ts/1000)} - {datetime.fromtimestamp(max_ts/1000)}")
            print(f"Backtest timestamp range: {min_ts} - {max_ts}")

if __name__ == "__main__":
    check_signals()

