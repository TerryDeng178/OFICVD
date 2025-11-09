#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P1.7: 跨平台metrics差异比较脚本

比较Windows和Unix平台的回测metrics差异，确保跨平台一致性
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


def load_metrics(file_path: str) -> Dict[str, Any]:
    """加载metrics JSON文件"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load metrics from {file_path}: {e}")
        raise


def compare_metrics(
    windows_metrics: Dict[str, Any],
    unix_metrics: Dict[str, Any],
    threshold: float = 0.05,
) -> bool:
    """比较两个平台的metrics差异
    
    Args:
        windows_metrics: Windows平台的metrics
        unix_metrics: Unix平台的metrics
        threshold: 允许的最大相对差异（默认5%）
    
    Returns:
        True if differences are within threshold, False otherwise
    """
    # 需要比较的关键指标
    key_metrics = [
        "total_trades",
        "total_pnl",
        "total_fee",
        "total_slippage",
        "total_turnover",
        "win_rate",
        "risk_reward_ratio",
        "sharpe_ratio",
        "sortino_ratio",
        "max_drawdown",
        "MAR",
        "avg_hold_sec",
    ]
    
    differences = []
    all_within_threshold = True
    
    logger.info("Comparing metrics between Windows and Unix platforms:")
    logger.info("=" * 80)
    
    for metric in key_metrics:
        win_value = windows_metrics.get(metric)
        unix_value = unix_metrics.get(metric)
        
        if win_value is None and unix_value is None:
            continue
        
        if win_value is None:
            logger.warning(f"  {metric}: Windows missing, Unix={unix_value}")
            differences.append((metric, None, unix_value, "missing"))
            all_within_threshold = False
            continue
        
        if unix_value is None:
            logger.warning(f"  {metric}: Unix missing, Windows={win_value}")
            differences.append((metric, win_value, None, "missing"))
            all_within_threshold = False
            continue
        
        # 处理无穷大和NaN
        if isinstance(win_value, float) and (not (win_value == win_value) or win_value == float("inf") or win_value == float("-inf")):
            if isinstance(unix_value, float) and (not (unix_value == unix_value) or unix_value == float("inf") or unix_value == float("-inf")):
                logger.info(f"  {metric}: Both are inf/NaN (Windows={win_value}, Unix={unix_value})")
                continue
            else:
                logger.warning(f"  {metric}: Windows is inf/NaN, Unix={unix_value}")
                differences.append((metric, win_value, unix_value, "inf/nan"))
                all_within_threshold = False
                continue
        
        if isinstance(unix_value, float) and (not (unix_value == unix_value) or unix_value == float("inf") or unix_value == float("-inf")):
            logger.warning(f"  {metric}: Unix is inf/NaN, Windows={win_value}")
            differences.append((metric, win_value, unix_value, "inf/nan"))
            all_within_threshold = False
            continue
        
        # 计算相对差异
        if isinstance(win_value, (int, float)) and isinstance(unix_value, (int, float)):
            if win_value == 0 and unix_value == 0:
                logger.info(f"  {metric}: Both are 0")
                continue
            
            # 使用较大的绝对值作为分母
            denominator = max(abs(win_value), abs(unix_value), 1e-10)
            diff = abs(win_value - unix_value) / denominator
            
            if diff > threshold:
                logger.error(
                    f"  {metric}: DIFF EXCEEDS THRESHOLD ({diff*100:.2f}% > {threshold*100:.2f}%)"
                )
                logger.error(f"    Windows: {win_value}")
                logger.error(f"    Unix: {unix_value}")
                differences.append((metric, win_value, unix_value, diff))
                all_within_threshold = False
            else:
                logger.info(
                    f"  {metric}: OK (diff={diff*100:.2f}%, Windows={win_value}, Unix={unix_value})"
                )
        else:
            # 非数值类型，直接比较
            if win_value != unix_value:
                logger.warning(f"  {metric}: Different (Windows={win_value}, Unix={unix_value})")
                differences.append((metric, win_value, unix_value, "different"))
                all_within_threshold = False
            else:
                logger.info(f"  {metric}: OK (Windows={win_value}, Unix={unix_value})")
    
    logger.info("=" * 80)
    
    if differences:
        logger.error(f"\nFound {len(differences)} metrics with differences:")
        for metric, win_val, unix_val, diff in differences:
            logger.error(f"  - {metric}: Windows={win_val}, Unix={unix_val}, diff={diff}")
    else:
        logger.info("\n✓ All metrics are within threshold")
    
    return all_within_threshold


def main():
    parser = argparse.ArgumentParser(
        description="Compare backtest metrics between Windows and Unix platforms"
    )
    parser.add_argument(
        "--windows-metrics",
        required=True,
        help="Path to Windows platform metrics JSON file",
    )
    parser.add_argument(
        "--unix-metrics",
        required=True,
        help="Path to Unix platform metrics JSON file",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.05,
        help="Maximum allowed relative difference (default: 0.05 = 5%%)",
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
    
    # 加载metrics
    logger.info(f"Loading Windows metrics from: {args.windows_metrics}")
    windows_metrics = load_metrics(args.windows_metrics)
    
    logger.info(f"Loading Unix metrics from: {args.unix_metrics}")
    unix_metrics = load_metrics(args.unix_metrics)
    
    # 比较metrics
    success = compare_metrics(windows_metrics, unix_metrics, args.threshold)
    
    if success:
        logger.info("✓ Cross-platform metrics comparison PASSED")
        sys.exit(0)
    else:
        logger.error("✗ Cross-platform metrics comparison FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()

