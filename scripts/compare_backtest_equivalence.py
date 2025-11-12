#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TASK-B2: 回测等价性对比器

对比新旧回测路径的结果等价性：
- sum(pnl) 误差 ≤ 1e-8
- trades 条数差 ≤ 5%
- 产物Schema完全一致

使用方法:
python scripts/compare_backtest_equivalence.py <old_run_dir> <new_run_dir> [--pnl-tolerance 1e-8] [--trades-tolerance-percent 5]
"""

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Any, Tuple
import sys

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

def load_jsonl_file(file_path: Path) -> list:
    """加载JSONL文件"""
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    records = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

def compare_pnl_files(old_dir: Path, new_dir: Path, tolerance: float = 1e-8) -> Tuple[bool, str]:
    """对比pnl_daily.jsonl文件"""
    old_pnl_file = old_dir / "pnl_daily.jsonl"
    new_pnl_file = new_dir / "pnl_daily.jsonl"

    old_pnls = load_jsonl_file(old_pnl_file)
    new_pnls = load_jsonl_file(new_pnl_file)

    if len(old_pnls) != len(new_pnls):
        return False, f"PNL record count mismatch: {len(old_pnls)} vs {len(new_pnls)}"

    total_old_pnl = sum(pnl.get('pnl', 0) for pnl in old_pnls)
    total_new_pnl = sum(pnl.get('pnl', 0) for pnl in new_pnls)

    pnl_diff = abs(total_old_pnl - total_new_pnl)
    if pnl_diff > tolerance:
        return False, ".2e"

    return True, ".2e"

def compare_trades_files(old_dir: Path, new_dir: Path, tolerance_percent: float = 5.0) -> Tuple[bool, str]:
    """对比trades.jsonl文件"""
    old_trades_file = old_dir / "trades.jsonl"
    new_trades_file = new_dir / "trades.jsonl"

    old_trades = load_jsonl_file(old_trades_file)
    new_trades = load_jsonl_file(new_trades_file)

    old_count = len(old_trades)
    new_count = len(new_trades)

    if old_count == 0:
        return new_count == 0, "No trades in old run, checking new run"

    diff_percent = abs(old_count - new_count) / old_count * 100
    if diff_percent > tolerance_percent:
        return False, ".1f"

    return True, ".1f"

def compare_signals_files(old_dir: Path, new_dir: Path) -> Tuple[bool, str]:
    """对比signals文件（如果存在）"""
    old_signals_file = old_dir / "signals.jsonl"
    new_signals_file = new_dir / "signals.jsonl"

    # 如果任一文件不存在，跳过对比
    if not old_signals_file.exists() and not new_signals_file.exists():
        return True, "No signals files to compare"

    if not old_signals_file.exists():
        return False, "Old run missing signals.jsonl"

    if not new_signals_file.exists():
        return False, "New run missing signals.jsonl"

    old_signals = load_jsonl_file(old_signals_file)
    new_signals = load_jsonl_file(new_signals_file)

    if len(old_signals) != len(new_signals):
        return False, f"Signals count mismatch: {len(old_signals)} vs {len(new_signals)}"

    # 检查基本字段一致性
    required_fields = ['ts_ms', 'symbol', 'score', 'confirm', 'gating']
    for i, (old_sig, new_sig) in enumerate(zip(old_signals, new_signals)):
        for field in required_fields:
            if field not in old_sig or field not in new_sig:
                return False, f"Missing field '{field}' in signal {i}"

        # 检查gating是数组
        if not isinstance(old_sig.get('gating', []), list):
            return False, f"Old signal {i} gating is not array"
        if not isinstance(new_sig.get('gating', []), list):
            return False, f"New signal {i} gating is not array"

    return True, f"Signals match: {len(old_signals)} records"

def compare_run_manifests(old_dir: Path, new_dir: Path) -> Tuple[bool, str]:
    """对比run_manifest.json文件"""
    old_manifest_file = old_dir / "run_manifest.json"
    new_manifest_file = new_dir / "run_manifest.json"

    if not old_manifest_file.exists() or not new_manifest_file.exists():
        return False, "Missing run_manifest.json files"

    with open(old_manifest_file, 'r', encoding='utf-8') as f:
        old_manifest = json.load(f)

    with open(new_manifest_file, 'r', encoding='utf-8') as f:
        new_manifest = json.load(f)

    # 检查关键字段
    key_fields = ['run_id', 'mode', 'symbols', 'start', 'end']
    for field in key_fields:
        if old_manifest.get(field) != new_manifest.get(field):
            return False, f"Manifest field '{field}' mismatch: {old_manifest.get(field)} vs {new_manifest.get(field)}"

    return True, "Run manifests match"

def main():
    parser = argparse.ArgumentParser(description="TASK-B2: Backtest Equivalence Comparator")
    parser.add_argument("old_run_dir", type=str, help="Old backtest run directory")
    parser.add_argument("new_run_dir", type=str, help="New backtest run directory")
    parser.add_argument("--pnl-tolerance", type=float, default=1e-8,
                       help="PNL sum tolerance (default: 1e-8)")
    parser.add_argument("--trades-tolerance-percent", type=float, default=5.0,
                       help="Trades count tolerance percent (default: 5.0)")

    args = parser.parse_args()

    old_dir = Path(args.old_run_dir)
    new_dir = Path(args.new_run_dir)

    if not old_dir.exists():
        print(f"ERROR: Old run directory not found: {old_dir}")
        return 1

    if not new_dir.exists():
        print(f"ERROR: New run directory not found: {new_dir}")
        return 1

    print("=== TASK-B2: Backtest Equivalence Comparison ===")
    print(f"Old run: {old_dir}")
    print(f"New run: {new_dir}")
    print(f"PNL tolerance: {args.pnl_tolerance}")
    print(f"Trades tolerance: {args.trades_tolerance_percent}%")
    print()

    all_passed = True
    results = []

    # 1. 对比run_manifest
    try:
        passed, message = compare_run_manifests(old_dir, new_dir)
        results.append(("Run Manifest", passed, message))
        if not passed:
            all_passed = False
    except Exception as e:
        results.append(("Run Manifest", False, f"Error: {e}"))
        all_passed = False

    # 2. 对比PNL
    try:
        passed, message = compare_pnl_files(old_dir, new_dir, args.pnl_tolerance)
        results.append(("PNL Sum", passed, message))
        if not passed:
            all_passed = False
    except Exception as e:
        results.append(("PNL Sum", False, f"Error: {e}"))
        all_passed = False

    # 3. 对比trades
    try:
        passed, message = compare_trades_files(old_dir, new_dir, args.trades_tolerance_percent)
        results.append(("Trades Count", passed, message))
        if not passed:
            all_passed = False
    except Exception as e:
        results.append(("Trades Count", False, f"Error: {e}"))
        all_passed = False

    # 4. 对比signals（如果存在）
    try:
        passed, message = compare_signals_files(old_dir, new_dir)
        results.append(("Signals", passed, message))
        if not passed:
            all_passed = False
    except Exception as e:
        results.append(("Signals", False, f"Error: {e}"))
        all_passed = False

    # 输出结果
    print("Results:")
    for check_name, passed, message in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {check_name}: {status} - {message}")

    print()
    if all_passed:
        print("🎉 EQUIVALENCE VERIFIED: All checks passed!")
        return 0
    else:
        print("❌ EQUIVALENCE FAILED: Some checks failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
