#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P1.1: 从signals中提取gate统计

从JSONL/SQLite信号产物中提取gate统计（weak_signal, low_consistency, passed等），
用于Gate双跑基线对比
"""
import argparse
import json
import logging
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


def extract_from_jsonl(signals_dir: Path) -> Dict[str, Any]:
    """从JSONL信号文件中提取gate统计"""
    gate_stats = {
        "total_signals": 0,
        "passed": 0,  # confirm=True
        "gated": 0,  # confirm=False
        "gate_reasons": defaultdict(int),
        "by_scenario": defaultdict(lambda: {"passed": 0, "gated": 0}),
        "by_mode": defaultdict(lambda: {"passed": 0, "gated": 0}),  # quiet/active
    }
    
    # 查找所有JSONL文件
    jsonl_files = list(signals_dir.glob("**/*.jsonl"))
    
    if not jsonl_files:
        logger.warning(f"No JSONL files found in {signals_dir}")
        return gate_stats
    
    for jsonl_file in jsonl_files:
        try:
            with jsonl_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        signal = json.loads(line)
                        gate_stats["total_signals"] += 1
                        
                        confirm = signal.get("confirm", False)
                        gating = signal.get("gating", False)
                        guard_reason = signal.get("guard_reason", "")
                        regime = signal.get("regime", "unknown")
                        
                        # 提取scenario（从_feature_data或signal本身）
                        feature_data = signal.get("_feature_data", {})
                        scenario = feature_data.get("scenario_2x2", "unknown")
                        
                        if confirm:
                            gate_stats["passed"] += 1
                            gate_stats["by_scenario"][scenario]["passed"] += 1
                            gate_stats["by_mode"][regime]["passed"] += 1
                        else:
                            gate_stats["gated"] += 1
                            gate_stats["by_scenario"][scenario]["gated"] += 1
                            gate_stats["by_mode"][regime]["gated"] += 1
                            
                            # 解析gate原因（逗号分隔）
                            if guard_reason:
                                for reason in guard_reason.split(","):
                                    reason = reason.strip()
                                    if reason:
                                        gate_stats["gate_reasons"][reason] += 1
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON in {jsonl_file}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Error reading {jsonl_file}: {e}")
            continue
    
    # 转换为普通dict
    gate_stats["gate_reasons"] = dict(gate_stats["gate_reasons"])
    gate_stats["by_scenario"] = {k: dict(v) for k, v in gate_stats["by_scenario"].items()}
    gate_stats["by_mode"] = {k: dict(v) for k, v in gate_stats["by_mode"].items()}
    
    return gate_stats


def extract_from_sqlite(db_path: Path) -> Dict[str, Any]:
    """从SQLite信号数据库中提取gate统计"""
    gate_stats = {
        "total_signals": 0,
        "passed": 0,
        "gated": 0,
        "gate_reasons": defaultdict(int),
        "by_scenario": defaultdict(lambda: {"passed": 0, "gated": 0}),
        "by_mode": defaultdict(lambda: {"passed": 0, "gated": 0}),
    }
    
    if not db_path.exists():
        logger.warning(f"SQLite database not found: {db_path}")
        return gate_stats
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 查询signals表
        cursor.execute("SELECT confirm, gating, guard_reason, regime FROM signals")
        
        for row in cursor.fetchall():
            confirm, gating, guard_reason, regime = row
            gate_stats["total_signals"] += 1
            
            if confirm:
                gate_stats["passed"] += 1
                gate_stats["by_mode"][regime or "unknown"]["passed"] += 1
            else:
                gate_stats["gated"] += 1
                gate_stats["by_mode"][regime or "unknown"]["gated"] += 1
                
                if guard_reason:
                    for reason in guard_reason.split(","):
                        reason = reason.strip()
                        if reason:
                            gate_stats["gate_reasons"][reason] += 1
        
        conn.close()
    except Exception as e:
        logger.error(f"Error reading SQLite database {db_path}: {e}")
    
    # 转换为普通dict
    gate_stats["gate_reasons"] = dict(gate_stats["gate_reasons"])
    gate_stats["by_scenario"] = {k: dict(v) for k, v in gate_stats["by_scenario"].items()}
    gate_stats["by_mode"] = {k: dict(v) for k, v in gate_stats["by_mode"].items()}
    
    return gate_stats


def extract_gate_stats(signals_path: Path) -> Dict[str, Any]:
    """从signals路径提取gate统计（自动识别JSONL或SQLite）"""
    if signals_path.is_file() and signals_path.suffix == ".db":
        return extract_from_sqlite(signals_path)
    elif signals_path.is_dir():
        # 查找JSONL文件或SQLite数据库
        db_files = list(signals_path.glob("**/*.db"))
        if db_files:
            return extract_from_sqlite(db_files[0])
        else:
            return extract_from_jsonl(signals_path)
    else:
        logger.error(f"Invalid signals path: {signals_path}")
        return {}


def compare_gate_stats(
    enforce_stats: Dict[str, Any],
    ignore_stats: Dict[str, Any],
    threshold_pct: float = 3.0,
) -> Dict[str, Any]:
    """对比两种模式的gate统计
    
    Args:
        enforce_stats: enforce模式的gate统计
        ignore_stats: ignore模式的gate统计
        threshold_pct: 允许的最大差异百分比（默认3%）
    
    Returns:
        对比结果
    """
    comparison = {
        "passed": True,
        "differences": [],
        "summary": {},
    }
    
    # 对比总通过率
    enforce_total = enforce_stats.get("total_signals", 0)
    ignore_total = ignore_stats.get("total_signals", 0)
    
    if enforce_total == 0 or ignore_total == 0:
        comparison["passed"] = False
        comparison["differences"].append("One mode has zero signals")
        return comparison
    
    enforce_passed = enforce_stats.get("passed", 0)
    ignore_passed = ignore_stats.get("passed", 0)
    
    enforce_pass_rate = enforce_passed / enforce_total if enforce_total > 0 else 0.0
    ignore_pass_rate = ignore_passed / ignore_total if ignore_total > 0 else 0.0
    
    pass_rate_diff_pct = abs(ignore_pass_rate - enforce_pass_rate) * 100
    
    comparison["summary"]["enforce_pass_rate"] = enforce_pass_rate
    comparison["summary"]["ignore_pass_rate"] = ignore_pass_rate
    comparison["summary"]["pass_rate_diff_pct"] = pass_rate_diff_pct
    
    if pass_rate_diff_pct > threshold_pct:
        comparison["passed"] = False
        comparison["differences"].append(
            f"Pass rate difference ({pass_rate_diff_pct:.2f}%) exceeds threshold ({threshold_pct}%)"
        )
    
    # 对比gate原因分布
    enforce_reasons = enforce_stats.get("gate_reasons", {})
    ignore_reasons = ignore_stats.get("gate_reasons", {})
    
    all_reasons = set(enforce_reasons.keys()) | set(ignore_reasons.keys())
    
    for reason in all_reasons:
        enforce_count = enforce_reasons.get(reason, 0)
        ignore_count = ignore_reasons.get(reason, 0)
        
        if enforce_count == 0:
            diff_pct = 100.0 if ignore_count > 0 else 0.0
        else:
            diff_pct = abs(ignore_count - enforce_count) / enforce_count * 100
        
        if diff_pct > threshold_pct:
            comparison["differences"].append(
                f"Gate reason '{reason}': enforce={enforce_count}, ignore={ignore_count}, diff={diff_pct:.2f}%"
            )
    
    return comparison


def main():
    parser = argparse.ArgumentParser(
        description="Extract gate statistics from signals for baseline comparison"
    )
    parser.add_argument(
        "--signals-path",
        required=True,
        help="Path to signals directory (JSONL) or database (SQLite)",
    )
    parser.add_argument(
        "--output",
        help="Output JSON file (default: gate_stats.json)",
    )
    parser.add_argument(
        "--compare-with",
        help="Path to another signals path for comparison",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=3.0,
        help="Maximum allowed difference percentage (default: 3.0%%)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    
    args = parser.parse_args()
    
    # 配置日志
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    
    # 提取gate统计
    signals_path = Path(args.signals_path)
    logger.info(f"Extracting gate statistics from: {signals_path}")
    
    gate_stats = extract_gate_stats(signals_path)
    
    if not gate_stats:
        logger.error("Failed to extract gate statistics")
        sys.exit(1)
    
    # 保存统计
    output_file = Path(args.output) if args.output else Path("gate_stats.json")
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(gate_stats, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Gate statistics saved to: {output_file}")
    
    # 打印摘要
    print("\n" + "=" * 80)
    print("Gate Statistics Summary")
    print("=" * 80)
    print(f"Total Signals: {gate_stats.get('total_signals', 0)}")
    print(f"Passed: {gate_stats.get('passed', 0)} ({gate_stats.get('passed', 0) / gate_stats.get('total_signals', 1) * 100:.2f}%)")
    print(f"Gated: {gate_stats.get('gated', 0)} ({gate_stats.get('gated', 0) / gate_stats.get('total_signals', 1) * 100:.2f}%)")
    
    print("\nTop Gate Reasons:")
    gate_reasons = gate_stats.get("gate_reasons", {})
    for reason, count in sorted(gate_reasons.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {reason}: {count}")
    
    # 如果提供了对比路径，进行对比
    if args.compare_with:
        compare_path = Path(args.compare_with)
        logger.info(f"Comparing with: {compare_path}")
        
        compare_stats = extract_gate_stats(compare_path)
        
        if compare_stats:
            comparison = compare_gate_stats(gate_stats, compare_stats, args.threshold)
            
            print("\n" + "=" * 80)
            print("Gate Statistics Comparison")
            print("=" * 80)
            print(f"Enforce Pass Rate: {comparison['summary'].get('enforce_pass_rate', 0)*100:.2f}%")
            print(f"Ignore Pass Rate: {comparison['summary'].get('ignore_pass_rate', 0)*100:.2f}%")
            print(f"Pass Rate Difference: {comparison['summary'].get('pass_rate_diff_pct', 0):.2f}%")
            
            if comparison["passed"]:
                print("\n✓ Comparison PASSED (within threshold)")
                sys.exit(0)
            else:
                print("\n✗ Comparison FAILED (exceeds threshold)")
                print("\nDifferences:")
                for diff in comparison["differences"]:
                    print(f"  - {diff}")
                sys.exit(1)
    
    print("=" * 80)
    sys.exit(0)


if __name__ == "__main__":
    main()


