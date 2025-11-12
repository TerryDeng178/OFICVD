#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TASK-B2: 回测确定性校验器

检查相同配置和输入的多次运行结果是否哈希一致

使用方法:
python scripts/check_backtest_determinism.py <run_dir1> <run_dir2> [<run_dir3> ...]
"""

import argparse
import json
import hashlib
from pathlib import Path
from typing import Dict, Any
import sys

def calculate_file_hash(file_path: Path) -> str:
    """计算文件内容的SHA256哈希"""
    if not file_path.exists():
        return ""

    hasher = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def load_json_file(file_path: Path) -> Dict[str, Any]:
    """加载JSON文件，排除非确定性字段"""
    if not file_path.exists():
        return {}

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 排除非确定性字段
    exclude_fields = ['created_at', 'git.commit', 'perf.duration_s', 'perf.memory_gib']
    for field in exclude_fields:
        keys = field.split('.')
        current = data
        for key in keys[:-1]:
            if key in current:
                current = current[key]
            else:
                break
        else:
            if keys[-1] in current:
                del current[keys[-1]]

    return data

def calculate_run_hash(run_dir: Path) -> str:
    """计算整个运行结果的综合哈希"""
    hashes = []

    # 哈希各个产物文件
    files_to_hash = ['signals.jsonl', 'trades.jsonl', 'pnl_daily.jsonl']
    for filename in files_to_hash:
        file_path = run_dir / filename
        if file_path.exists():
            hashes.append(calculate_file_hash(file_path))

    # 哈希run_manifest（排除时间戳等非确定性字段）
    manifest_file = run_dir / "run_manifest.json"
    if manifest_file.exists():
        manifest = load_json_file(manifest_file)
        # 对排序后的JSON计算哈希
        manifest_str = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
        hashes.append(hashlib.sha256(manifest_str.encode('utf-8')).hexdigest())

    # 计算综合哈希
    combined = '|'.join(hashes)
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()

def main():
    parser = argparse.ArgumentParser(description="TASK-B2: Backtest Determinism Checker")
    parser.add_argument("run_dirs", nargs='+', type=str,
                       help="Backtest run directories to compare")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show detailed hash information")

    args = parser.parse_args()

    run_dirs = [Path(d) for d in args.run_dirs]

    # 检查目录存在性
    for run_dir in run_dirs:
        if not run_dir.exists():
            print(f"ERROR: Run directory not found: {run_dir}")
            return 1

    print("=== TASK-B2: Backtest Determinism Check ===")
    print(f"Comparing {len(run_dirs)} runs:")
    for i, run_dir in enumerate(run_dirs, 1):
        print(f"  Run {i}: {run_dir}")
    print()

    # 计算各运行的哈希
    run_hashes = []
    for run_dir in run_dirs:
        run_hash = calculate_run_hash(run_dir)
        run_hashes.append(run_hash)

        if args.verbose:
            print(f"Hash for {run_dir.name}: {run_hash}")

    # 检查哈希一致性
    first_hash = run_hashes[0]
    all_match = all(h == first_hash for h in run_hashes)

    print(f"Results:")
    print(f"  Reference hash: {first_hash}")

    for i, (run_dir, run_hash) in enumerate(zip(run_dirs, run_hashes), 1):
        status = "✓ MATCH" if run_hash == first_hash else "✗ MISMATCH"
        print(f"  Run {i} ({run_dir.name}): {status}")

    print()
    if all_match:
        print("🎉 DETERMINISM VERIFIED: All runs produced identical results!")
        return 0
    else:
        print("❌ DETERMINISM FAILED: Runs produced different results!")
        print("This indicates non-deterministic behavior in the backtest system.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
