#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P1.1: Pushgateway集成测试脚本

验证回测指标是否成功推送到Pushgateway
"""
import argparse
import logging
import sys
from typing import Dict, List, Set

try:
    import requests
except ImportError:
    print("ERROR: requests library not available. Install with: pip install requests")
    sys.exit(1)

logger = logging.getLogger(__name__)

# 预期的11个backtest_*指标
EXPECTED_METRICS = {
    "backtest_total_pnl",
    "backtest_sharpe",
    "backtest_sortino",
    "backtest_mar",
    "backtest_win_rate",
    "backtest_rr",
    "backtest_avg_hold_sec",
    "backtest_trades_total",
    "backtest_turnover",
    "backtest_fee_total",
    "backtest_slippage_total",
}


def fetch_pushgateway_metrics(pushgateway_url: str) -> str:
    """从Pushgateway获取所有指标"""
    try:
        response = requests.get(f"{pushgateway_url}/metrics", timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"Failed to fetch metrics from Pushgateway: {e}")
        raise


def parse_metrics(metrics_text: str, run_id: str) -> Dict[str, List[str]]:
    """解析指标文本，提取指定run_id的指标"""
    found_metrics = {}
    
    for line in metrics_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        
        # Prometheus格式: metric_name{labels} value timestamp
        if f'run_id="{run_id}"' in line or f"run_id=\"{run_id}\"" in line:
            # 提取指标名（在{之前）
            if "{" in line:
                metric_name = line.split("{")[0]
            else:
                metric_name = line.split()[0]
            
            if metric_name.startswith("backtest_"):
                if metric_name not in found_metrics:
                    found_metrics[metric_name] = []
                found_metrics[metric_name].append(line)
    
    return found_metrics


def verify_metrics(
    pushgateway_url: str,
    run_id: str,
    expected_count: int = 11,
    expected_metrics: Set[str] = None,
) -> bool:
    """验证指标是否成功推送
    
    Args:
        pushgateway_url: Pushgateway URL
        run_id: 回测run_id
        expected_count: 预期指标数量
        expected_metrics: 预期指标名称集合
    
    Returns:
        True if all metrics are found, False otherwise
    """
    if expected_metrics is None:
        expected_metrics = EXPECTED_METRICS
    
    logger.info(f"Fetching metrics from Pushgateway: {pushgateway_url}")
    logger.info(f"Looking for run_id: {run_id}")
    
    try:
        metrics_text = fetch_pushgateway_metrics(pushgateway_url)
        found_metrics = parse_metrics(metrics_text, run_id)
        
        logger.info(f"Found {len(found_metrics)} metrics for run_id={run_id}")
        
        # 检查是否找到所有预期指标
        missing_metrics = expected_metrics - set(found_metrics.keys())
        unexpected_metrics = set(found_metrics.keys()) - expected_metrics
        
        if missing_metrics:
            logger.error(f"Missing metrics ({len(missing_metrics)}): {missing_metrics}")
            for metric in missing_metrics:
                logger.error(f"  - {metric}")
        
        if unexpected_metrics:
            logger.warning(f"Unexpected metrics ({len(unexpected_metrics)}): {unexpected_metrics}")
        
        # 验证指标数量
        if len(found_metrics) < expected_count:
            logger.error(
                f"Expected at least {expected_count} metrics, but found {len(found_metrics)}"
            )
            return False
        
        # 验证所有预期指标都存在
        if missing_metrics:
            logger.error(f"Missing {len(missing_metrics)} expected metrics")
            return False
        
        # 打印找到的指标
        logger.info("Found metrics:")
        for metric_name in sorted(found_metrics.keys()):
            logger.info(f"  ✓ {metric_name}")
            for line in found_metrics[metric_name]:
                logger.debug(f"    {line}")
        
        logger.info(f"✓ All {len(found_metrics)} expected metrics found")
        return True
        
    except Exception as e:
        logger.error(f"Error verifying metrics: {e}", exc_info=True)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Verify Pushgateway integration for backtest metrics"
    )
    parser.add_argument(
        "--pushgateway-url",
        default="http://localhost:9091",
        help="Pushgateway URL (default: http://localhost:9091)",
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="Backtest run_id to verify",
    )
    parser.add_argument(
        "--expected-metrics",
        type=int,
        default=11,
        help="Expected number of metrics (default: 11)",
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
    
    # 验证指标
    success = verify_metrics(
        pushgateway_url=args.pushgateway_url,
        run_id=args.run_id,
        expected_count=args.expected_metrics,
    )
    
    if success:
        logger.info("✓ Pushgateway integration test PASSED")
        sys.exit(0)
    else:
        logger.error("✗ Pushgateway integration test FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()

