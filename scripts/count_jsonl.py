#!/usr/bin/env python3
"""统计JSONL文件行数"""
import sys
from pathlib import Path

def main():
    jsonl_dir = Path("runtime/ready/signal")
    jsonl_files = sorted(jsonl_dir.rglob("*.jsonl"))
    
    total_count = 0
    for jsonl_file in jsonl_files:
        try:
            with open(jsonl_file, "r", encoding="utf-8") as f:
                count = sum(1 for line in f if line.strip())
                total_count += count
        except Exception as e:
            print(f"[WARNING] 读取 {jsonl_file} 失败: {e}", file=sys.stderr)
    
    print(f"JSONL总行数: {total_count:,}")
    return 0

if __name__ == "__main__":
    sys.exit(main())

