#!/usr/bin/env python3
"""检查JSONL文件中的run_id字段"""
import json
import sys
from pathlib import Path

def main():
    jsonl_dir = Path("runtime/ready/signal")
    files = sorted(jsonl_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    if not files:
        print("[!] 未找到JSONL文件")
        return 1
    
    # 检查最新的文件
    sample_file = files[0]
    print(f"检查文件: {sample_file.name}")
    print()
    
    # 读取前5行
    with open(sample_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()][:5]
    
    print("前5行数据:")
    for i, line in enumerate(lines, 1):
        try:
            data = json.loads(line)
            has_run_id = "run_id" in data
            run_id_value = data.get("run_id", "")
            print(f"  {i}. run_id存在: {has_run_id}, 值: {run_id_value}")
            if not has_run_id:
                print(f"     字段列表: {list(data.keys())[:10]}")
        except Exception as e:
            print(f"  {i}. 解析失败: {e}")
    
    print()
    
    # 统计run_id分布
    run_id_counts = {}
    total = 0
    for jsonl_file in files[:10]:  # 只检查前10个文件
        try:
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        total += 1
                        run_id = data.get("run_id", "")
                        run_id_counts[run_id] = run_id_counts.get(run_id, 0) + 1
                    except Exception:
                        continue
        except Exception:
            continue
    
    print(f"统计（前10个文件，共{total}条）:")
    for run_id, count in sorted(run_id_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        pct = count / total * 100 if total > 0 else 0
        print(f"  run_id='{run_id}': {count:,} ({pct:.2f}%)")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

