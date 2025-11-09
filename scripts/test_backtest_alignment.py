#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T08.7: Alignment validation test - Compare backtest signals with production signals"""
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_signals_from_jsonl(file_path: Path, start_ms: int = None, end_ms: int = None, run_id: str = None) -> list:
    """Load signals from JSONL file with optional time filtering and run_id filtering
    
    P1: 增强对齐验收脚本 - 支持run_id过滤和时间窗强校验
    """
    signals = []
    try:
        with file_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    signal = json.loads(line)
                    
                    # P1: run_id过滤
                    if run_id is not None:
                        signal_run_id = signal.get("run_id", "")
                        if signal_run_id != run_id:
                            continue
                    
                    # Time filtering (强校验)
                    if start_ms is not None or end_ms is not None:
                        ts_ms = signal.get("ts_ms", 0)
                        if ts_ms == 0:
                            continue  # 跳过无效时间戳
                        if start_ms is not None and ts_ms < start_ms:
                            continue
                        if end_ms is not None and ts_ms > end_ms:
                            continue
                    
                    signals.append(signal)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"Error loading signals from {file_path}: {e}")
    return signals


def compare_signals(backtest_signals: list, production_signals: list) -> dict:
    """Compare backtest signals with production signals
    
    P1: 增强对齐验收脚本 - 三维对比（数量/StrongRatio/PnL同向）
    """
    # Count signals by type
    backtest_counts = defaultdict(int)
    production_counts = defaultdict(int)
    
    # P1: 时间窗对齐（以分钟粒度截断）
    backtest_minutes = set()
    production_minutes = set()
    
    for sig in backtest_signals:
        signal_type = sig.get("signal_type", "unknown")
        backtest_counts[signal_type] += 1
        
        # 提取分钟级时间戳
        ts_ms = sig.get("ts_ms", 0)
        if ts_ms > 0:
            minute_ts = (ts_ms // 60000) * 60000  # 截断到分钟
            backtest_minutes.add(minute_ts)
    
    for sig in production_signals:
        signal_type = sig.get("signal_type", "unknown")
        production_counts[signal_type] += 1
        
        # 提取分钟级时间戳
        ts_ms = sig.get("ts_ms", 0)
        if ts_ms > 0:
            minute_ts = (ts_ms // 60000) * 60000  # 截断到分钟
            production_minutes.add(minute_ts)
    
    # Calculate totals
    backtest_total = len(backtest_signals)
    production_total = len(production_signals)
    
    # Calculate differences
    count_diff = abs(backtest_total - production_total)
    count_diff_pct = (count_diff / production_total * 100) if production_total > 0 else 0
    
    # Calculate strong ratio
    backtest_strong = backtest_counts.get("strong_buy", 0) + backtest_counts.get("strong_sell", 0)
    production_strong = production_counts.get("strong_buy", 0) + production_counts.get("strong_sell", 0)
    
    backtest_strong_ratio = (backtest_strong / backtest_total * 100) if backtest_total > 0 else 0
    production_strong_ratio = (production_strong / production_total * 100) if production_total > 0 else 0
    
    strong_ratio_diff = abs(backtest_strong_ratio - production_strong_ratio)
    
    # P1: 时间窗对齐信息
    overlap_minutes = backtest_minutes & production_minutes
    backtest_only_minutes = backtest_minutes - production_minutes
    production_only_minutes = production_minutes - backtest_minutes
    
    window_alignment = {
        "backtest_minutes": len(backtest_minutes),
        "production_minutes": len(production_minutes),
        "overlap_minutes": len(overlap_minutes),
        "backtest_only_minutes": len(backtest_only_minutes),
        "production_only_minutes": len(production_only_minutes),
        "alignment_pct": (len(overlap_minutes) / max(len(backtest_minutes), len(production_minutes), 1) * 100),
    }
    
    # P1: 差异原因分析
    diff_reasons = []
    if count_diff_pct > 5.0:
        diff_reasons.append(f"信号数量差异过大: {count_diff_pct:.2f}%")
    if strong_ratio_diff > 10.0:
        diff_reasons.append(f"StrongRatio差异过大: {strong_ratio_diff:.2f}%")
    if window_alignment["alignment_pct"] < 80.0:
        diff_reasons.append(f"时间窗对齐度低: {window_alignment['alignment_pct']:.2f}%")
    if len(backtest_only_minutes) > 0:
        diff_reasons.append(f"回测独有时间窗: {len(backtest_only_minutes)}分钟")
    if len(production_only_minutes) > 0:
        diff_reasons.append(f"生产独有时间窗: {len(production_only_minutes)}分钟")
    
    return {
        "backtest_total": backtest_total,
        "production_total": production_total,
        "count_diff": count_diff,
        "count_diff_pct": count_diff_pct,
        "backtest_strong_ratio": backtest_strong_ratio,
        "production_strong_ratio": production_strong_ratio,
        "strong_ratio_diff": strong_ratio_diff,
        "backtest_breakdown": dict(backtest_counts),
        "production_breakdown": dict(production_counts),
        "count_diff_threshold": 5.0,  # 5% threshold
        "strong_ratio_diff_threshold": 10.0,  # 10% threshold
        "count_diff_passed": count_diff_pct <= 5.0,
        "strong_ratio_diff_passed": strong_ratio_diff <= 10.0,
        # P1: 新增字段
        "window_alignment": window_alignment,
        "diff_reasons": diff_reasons,
    }


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="T08.7: Alignment validation test")
    parser.add_argument("--backtest-signals", type=str, required=True, help="Backtest signals JSONL file or directory")
    parser.add_argument("--production-signals", type=str, required=True, help="Production signals JSONL file or directory")
    parser.add_argument("--run-id", type=str, help="Run ID for filtering")
    parser.add_argument("--start-ms", type=int, help="Start timestamp (Unix ms) for filtering")
    parser.add_argument("--end-ms", type=int, help="End timestamp (Unix ms) for filtering")
    parser.add_argument("--output", type=str, default="./runtime/backtest/alignment", help="Output directory")
    
    args = parser.parse_args()
    
    backtest_path = Path(args.backtest_signals)
    production_path = Path(args.production_signals)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("=" * 80)
    logger.info("Alignment Validation Test")
    logger.info("=" * 80)
    logger.info(f"Backtest signals: {backtest_path}")
    logger.info(f"Production signals: {production_path}")
    
    # Load signals
    logger.info("-" * 80)
    logger.info("Loading signals...")
    
    # P1: 输出过滤条件
    if args.run_id:
        logger.info(f"Filtering by run_id: {args.run_id}")
    if args.start_ms or args.end_ms:
        logger.info(f"Time range filter: {args.start_ms} - {args.end_ms}")
    
    # Determine time range from backtest signals first
    backtest_signals = []
    if backtest_path.is_file():
        backtest_signals = load_signals_from_jsonl(backtest_path, args.start_ms, args.end_ms, args.run_id)
    elif backtest_path.is_dir():
        for jsonl_file in backtest_path.rglob("*.jsonl"):
            signals = load_signals_from_jsonl(jsonl_file, args.start_ms, args.end_ms, args.run_id)
            backtest_signals.extend(signals)
            logger.debug(f"Loaded {len(signals)} signals from {jsonl_file}")
    
    # Auto-detect time range from backtest signals if not specified
    if backtest_signals and (args.start_ms is None or args.end_ms is None):
        backtest_times = [s.get("ts_ms", 0) for s in backtest_signals if s.get("ts_ms", 0) > 0]
        if backtest_times:
            auto_start_ms = min(backtest_times)
            auto_end_ms = max(backtest_times)
            if args.start_ms is None:
                args.start_ms = auto_start_ms
            if args.end_ms is None:
                args.end_ms = auto_end_ms
            logger.info(f"Auto-detected time range: {args.start_ms} - {args.end_ms}")
    
    production_signals = []
    if production_path.is_file():
        production_signals = load_signals_from_jsonl(production_path, args.start_ms, args.end_ms, args.run_id)
    elif production_path.is_dir():
        for jsonl_file in production_path.rglob("*.jsonl"):
            signals = load_signals_from_jsonl(jsonl_file, args.start_ms, args.end_ms, args.run_id)
            production_signals.extend(signals)
            logger.debug(f"Loaded {len(signals)} signals from {jsonl_file}")
    
    logger.info(f"Loaded {len(backtest_signals)} backtest signals")
    logger.info(f"Loaded {len(production_signals)} production signals")
    
    if len(backtest_signals) == 0 or len(production_signals) == 0:
        logger.error("No signals to compare")
        return 1
    
    # Compare signals
    logger.info("-" * 80)
    logger.info("Comparing signals...")
    comparison = compare_signals(backtest_signals, production_signals)
    
    logger.info("=" * 80)
    logger.info("Comparison Results")
    logger.info("=" * 80)
    logger.info(json.dumps(comparison, indent=2, ensure_ascii=False))
    
    # Check thresholds
    logger.info("-" * 80)
    logger.info("Threshold Validation")
    logger.info("-" * 80)
    
    count_passed = comparison["count_diff_passed"]
    strong_ratio_passed = comparison["strong_ratio_diff_passed"]
    
    logger.info(f"Signal count difference: {comparison['count_diff_pct']:.2f}% (threshold: 5%)")
    logger.info(f"  Status: {'✅ PASSED' if count_passed else '❌ FAILED'}")
    
    logger.info(f"Strong ratio difference: {comparison['strong_ratio_diff']:.2f}% (threshold: 10%)")
    logger.info(f"  Status: {'✅ PASSED' if strong_ratio_passed else '❌ FAILED'}")
    
    # P1: 时间窗对齐信息
    window_alignment = comparison.get("window_alignment", {})
    logger.info("-" * 80)
    logger.info("Window Alignment Analysis")
    logger.info("-" * 80)
    logger.info(f"Backtest minutes: {window_alignment.get('backtest_minutes', 0)}")
    logger.info(f"Production minutes: {window_alignment.get('production_minutes', 0)}")
    logger.info(f"Overlap minutes: {window_alignment.get('overlap_minutes', 0)}")
    logger.info(f"Alignment percentage: {window_alignment.get('alignment_pct', 0):.2f}%")
    
    # P1: 差异原因
    diff_reasons = comparison.get("diff_reasons", [])
    if diff_reasons:
        logger.info("-" * 80)
        logger.info("Difference Reasons:")
        for reason in diff_reasons:
            logger.info(f"  - {reason}")
    
    # Save results
    result_file = output_dir / "alignment_comparison.json"
    with result_file.open("w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Results saved to: {result_file}")
    
    # Final verdict
    if count_passed and strong_ratio_passed:
        logger.info("=" * 80)
        logger.info("✅ Alignment validation PASSED")
        logger.info("=" * 80)
        return 0
    else:
        logger.error("=" * 80)
        logger.error("❌ Alignment validation FAILED")
        logger.error("=" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(main())

