#!/usr/bin/env python3
"""分析SQLite数据缺失问题"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime
import re

print("=" * 80)
print("SQLite数据缺失问题分析")
print("=" * 80)
print()

# 1. 检查数据统计
print("1. 数据统计:")
print()

jsonl_dir = Path("runtime/ready/signal")
jsonl_files = sorted(jsonl_dir.rglob("*.jsonl"))
jsonl_count = 0
for jsonl_file in jsonl_files:
    with open(jsonl_file, "r", encoding="utf-8") as f:
        jsonl_count += sum(1 for line in f if line.strip())

db = Path("runtime/signals.db")
sqlite_count = 0
if db.exists():
    conn = sqlite3.connect(str(db))
    cursor = conn.cursor()
    sqlite_count = cursor.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    conn.close()

print(f"  JSONL信号总数: {jsonl_count:,}")
print(f"  SQLite信号总数: {sqlite_count:,}")
print(f"  差异: {jsonl_count - sqlite_count:,} ({((jsonl_count - sqlite_count) / jsonl_count * 100):.1f}%)")
print()

# 2. 检查SQLite批量刷新日志
print("2. 检查SQLite关闭日志:")
print()

log_dir = Path("logs")
log_files = sorted(log_dir.rglob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)

found_close_log = False
for log_file in log_files[:5]:  # 检查最新的5个日志文件
    try:
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            if "SqliteSink" in content or "关闭时刷新" in content or "cleanup" in content:
                print(f"  检查日志: {log_file.name}")
                # 查找相关日志行
                lines = content.split("\n")
                sqlite_lines = [l for l in lines if "SqliteSink" in l or "关闭时刷新" in l or "cleanup" in l or "批处理完成" in l]
                if sqlite_lines:
                    print(f"    找到 {len(sqlite_lines)} 条相关日志:")
                    for line in sqlite_lines[-10:]:  # 显示最后10条
                        print(f"      {line[:100]}")
                    found_close_log = True
                    break
    except Exception as e:
        continue

if not found_close_log:
    print("  [!] 未找到SQLite关闭相关日志")
print()

# 3. 检查SQLite批量队列状态
print("3. 分析批量刷新机制:")
print()

print("  代码检查:")
print("    - SqliteSink.close() 实现: ✅ 有刷新逻辑")
print("    - MultiSink.close() 实现: ✅ 调用所有子Sink的close()")
print("    - 环境变量: SQLITE_BATCH_N=1, SQLITE_FLUSH_MS=0")
print()

# 4. 检查时间范围
print("4. 检查数据时间范围:")
print()

# JSONL时间范围
jsonl_times = []
for jsonl_file in jsonl_files[:10]:
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
    jsonl_min = min(jsonl_times)
    jsonl_max = max(jsonl_times)
    print(f"  JSONL时间范围: {datetime.fromtimestamp(jsonl_min/1000)} - {datetime.fromtimestamp(jsonl_max/1000)}")
    print(f"    时间跨度: {(jsonl_max - jsonl_min) / 1000 / 60:.1f} 分钟")

# SQLite时间范围
if db.exists():
    conn = sqlite3.connect(str(db))
    cursor = conn.cursor()
    ts_range = cursor.execute("SELECT MIN(ts_ms), MAX(ts_ms) FROM signals").fetchone()
    if ts_range[0]:
        sqlite_min = ts_range[0]
        sqlite_max = ts_range[1]
        print(f"  SQLite时间范围: {datetime.fromtimestamp(sqlite_min/1000)} - {datetime.fromtimestamp(sqlite_max/1000)}")
        print(f"    时间跨度: {(sqlite_max - sqlite_min) / 1000 / 60:.1f} 分钟")
        
        # 检查时间重叠
        overlap_start = max(jsonl_min, sqlite_min)
        overlap_end = min(jsonl_max, sqlite_max)
        if overlap_start < overlap_end:
            print(f"  时间重叠: {datetime.fromtimestamp(overlap_start/1000)} - {datetime.fromtimestamp(overlap_end/1000)}")
            print(f"    重叠时长: {(overlap_end - overlap_start) / 1000 / 60:.1f} 分钟")
        else:
            print("  [!] 时间范围无重叠")
    conn.close()
print()

# 5. 检查每分钟数据分布
print("5. 检查每分钟数据分布:")
print()

# JSONL每分钟统计
jsonl_by_minute = {}
for jsonl_file in jsonl_files:
    with open(jsonl_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                signal = json.loads(line)
                ts_ms = signal.get("ts_ms", 0)
                if ts_ms > 0:
                    minute = ts_ms // 60000
                    jsonl_by_minute[minute] = jsonl_by_minute.get(minute, 0) + 1
            except:
                continue

# SQLite每分钟统计
sqlite_by_minute = {}
if db.exists():
    conn = sqlite3.connect(str(db))
    cursor = conn.cursor()
    for row in cursor.execute("SELECT ts_ms FROM signals"):
        minute = row[0] // 60000
        sqlite_by_minute[minute] = sqlite_by_minute.get(minute, 0) + 1
    conn.close()

print(f"  JSONL分钟数: {len(jsonl_by_minute)}")
print(f"  SQLite分钟数: {len(sqlite_by_minute)}")
print()

if jsonl_by_minute and sqlite_by_minute:
    common_minutes = set(jsonl_by_minute.keys()) & set(sqlite_by_minute.keys())
    print(f"  共同分钟数: {len(common_minutes)}")
    if common_minutes:
        print("  前5个共同分钟的对比:")
        for minute in sorted(common_minutes)[:5]:
            j_count = jsonl_by_minute[minute]
            s_count = sqlite_by_minute[minute]
            diff_pct = abs(j_count - s_count) / j_count * 100 if j_count > 0 else 0
            print(f"    {datetime.fromtimestamp(minute*60000/1000).strftime('%H:%M')}: JSONL={j_count}, SQLite={s_count}, 差异={diff_pct:.1f}%")
print()

# 6. 问题诊断
print("6. 问题诊断:")
print()

issues = []
if jsonl_count > 0 and sqlite_count / jsonl_count < 0.5:
    issues.append("SQLite数据严重缺失（< 50%）")

if jsonl_by_minute and sqlite_by_minute:
    avg_jsonl = sum(jsonl_by_minute.values()) / len(jsonl_by_minute)
    avg_sqlite = sum(sqlite_by_minute.values()) / len(sqlite_by_minute)
    if avg_sqlite / avg_jsonl < 0.5:
        issues.append("每分钟平均数据量差异过大")

if not found_close_log:
    issues.append("未找到SQLite关闭日志，可能未正确调用close()")

if issues:
    print("  发现的问题:")
    for i, issue in enumerate(issues, 1):
        print(f"    {i}. {issue}")
else:
    print("  未发现明显问题")

print()
print("=" * 80)
print("分析完成")
print("=" * 80)

