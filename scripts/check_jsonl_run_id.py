#!/usr/bin/env python3
"""检查JSONL文件中的run_id"""
import json
import sys
from pathlib import Path

def main():
    jsonl_dir = Path("runtime/ready/signal")
    if not jsonl_dir.exists():
        print(f"[ERROR] JSONL目录不存在: {jsonl_dir}")
        return 1
    
    # 找到最新的JSONL文件
    jsonl_files = sorted(jsonl_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not jsonl_files:
        print("[ERROR] 未找到JSONL文件")
        return 1
    
    print(f"检查最新文件: {jsonl_files[0].name}")
    print()
    
    # 读取前10行
    run_id_stats = {}
    total = 0
    with open(jsonl_files[0], "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 10:
                break
            line = line.strip()
            if not line:
                continue
            
            try:
                data = json.loads(line)
                total += 1
                run_id = data.get("run_id", "MISSING")
                run_id_stats[run_id] = run_id_stats.get(run_id, 0) + 1
                
                print(f"行 {i+1}:")
                print(f"  run_id: {repr(run_id)}")
                print(f"  所有字段: {list(data.keys())}")
                print()
            except Exception as e:
                print(f"行 {i+1}: JSON解析失败: {e}")
                print()
    
    print(f"统计（前{total}行）:")
    for run_id, count in sorted(run_id_stats.items(), key=lambda x: x[1], reverse=True):
        pct = count / total * 100 if total > 0 else 0
        print(f"  {repr(run_id)}: {count} ({pct:.1f}%)")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

