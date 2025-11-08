#!/usr/bin/env python3
"""检查数据时间范围"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime

# 检查JSONL时间范围
jsonl_dir = Path("runtime/ready/signal")
jsonl_files = sorted(jsonl_dir.rglob("*.jsonl"))
print(f"JSONL文件数: {len(jsonl_files)}")

jsonl_times = []
for jsonl_file in jsonl_files[:10]:  # 只检查前10个文件
    with open(jsonl_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                signal = json.loads(line)
                ts_ms = signal.get("ts_ms", 0)
                if ts_ms > 0:
                    jsonl_times.append(ts_ms)
            except:
                continue

if jsonl_times:
    min_ts = min(jsonl_times)
    max_ts = max(jsonl_times)
    print(f"JSONL时间范围: {datetime.fromtimestamp(min_ts/1000)} - {datetime.fromtimestamp(max_ts/1000)}")
    print(f"  ts_ms范围: {min_ts} - {max_ts}")

# 检查SQLite时间范围
db = Path("runtime/signals.db")
if db.exists():
    conn = sqlite3.connect(str(db))
    cursor = conn.cursor()
    ts_range = cursor.execute("SELECT MIN(ts_ms), MAX(ts_ms) FROM signals").fetchone()
    if ts_range[0]:
        print(f"SQLite时间范围: {datetime.fromtimestamp(ts_range[0]/1000)} - {datetime.fromtimestamp(ts_range[1]/1000)}")
        print(f"  ts_ms范围: {ts_range[0]} - {ts_range[1]}")
    conn.close()

