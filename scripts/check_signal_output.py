#!/usr/bin/env python3
"""检查signal进程输出"""
import json
import sys
from pathlib import Path
from datetime import datetime

def check_signal_output(run_id: str):
    """检查signal进程的输出"""
    jsonl_dir = Path("runtime/ready/signal")
    sqlite_db = Path("runtime/signals.db")
    
    print(f"检查RUN_ID: {run_id}")
    print("=" * 80)
    
    # 检查JSONL
    jsonl_files = sorted(jsonl_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    jsonl_count = 0
    jsonl_with_run_id = 0
    
    for f in jsonl_files[:20]:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        signal = json.loads(line)
                        jsonl_count += 1
                        if signal.get("run_id") == run_id:
                            jsonl_with_run_id += 1
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"[WARN] 读取文件失败 {f}: {e}", file=sys.stderr)
            continue
    
    print(f"JSONL统计（前20个文件）:")
    print(f"  总记录数: {jsonl_count}")
    print(f"  匹配run_id的记录: {jsonl_with_run_id}")
    print()
    
    # 检查SQLite
    import sqlite3
    sqlite_count = 0
    sqlite_with_run_id = 0
    
    if sqlite_db.exists():
        try:
            conn = sqlite3.connect(str(sqlite_db))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM signals")
            sqlite_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM signals WHERE run_id = ?", (run_id,))
            sqlite_with_run_id = cursor.fetchone()[0]
            conn.close()
        except Exception as e:
            print(f"[ERROR] 读取SQLite失败: {e}", file=sys.stderr)
    
    print(f"SQLite统计:")
    print(f"  总记录数: {sqlite_count}")
    print(f"  匹配run_id的记录: {sqlite_with_run_id}")
    print()
    
    # 检查最新JSONL文件的run_id分布
    if jsonl_files:
        latest_file = jsonl_files[0]
        print(f"最新JSONL文件: {latest_file.name}")
        run_ids = {}
        try:
            with open(latest_file, "r", encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        signal = json.loads(line)
                        rid = signal.get("run_id", "MISSING")
                        run_ids[rid] = run_ids.get(rid, 0) + 1
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"[ERROR] 读取最新文件失败: {e}", file=sys.stderr)
        
        print(f"run_id分布（前100行）:")
        for rid, count in sorted(run_ids.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"  {rid}: {count}条")
    
    print()
    print("=" * 80)
    
    if jsonl_with_run_id == 0 and sqlite_with_run_id == 0:
        print("⚠️  警告: 未找到匹配run_id的记录")
        print("可能原因:")
        print("  1. signal进程未成功处理数据")
        print("  2. 数据源问题（preview数据可能已处理过）")
        print("  3. signal进程在处理过程中出错")
        return 1
    else:
        print("✅ 找到匹配run_id的记录")
        return 0

if __name__ == "__main__":
    run_id = sys.argv[1] if len(sys.argv) > 1 else "task07b_smoke_20251108_224745"
    sys.exit(check_signal_output(run_id))

