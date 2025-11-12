#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Risk Module Regression Test Script

回归测试：切换 RISK_INLINE_ENABLED 前后的PnL、成交率、拒单占比对比（±5%阈值）
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp.strategy_server.risk import (
    initialize_risk_manager,
    pre_order_check,
    OrderCtx,
    get_metrics,
    reset_metrics,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class RegressionTester:
    """回归测试器"""
    
    def __init__(self, test_data_path: str, threshold: float = 0.05):
        """初始化回归测试器
        
        Args:
            test_data_path: 测试数据路径（JSONL文件）
            threshold: 阈值（默认5%，即0.05）
        """
        self.test_data_path = Path(test_data_path)
        self.threshold = threshold
    
    def load_test_data(self) -> List[Dict]:
        """加载测试数据
        
        Returns:
            测试数据列表
        """
        test_data = []
        
        if not self.test_data_path.exists():
            logger.error(f"Test data file not found: {self.test_data_path}")
            return test_data
        
        with self.test_data_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    test_data.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse line: {e}")
        
        logger.info(f"Loaded {len(test_data)} test cases from {self.test_data_path}")
        return test_data
    
    def run_test_with_config(self, config: Dict, label: str) -> Dict:
        """使用指定配置运行测试
        
        Args:
            config: 配置字典
            label: 测试标签（用于区分legacy/inline）
            
        Returns:
            测试结果统计
        """
        # 初始化风险管理器
        initialize_risk_manager(config)
        reset_metrics()
        
        # 加载测试数据
        test_data = self.load_test_data()
        
        if not test_data:
            logger.warning("No test data loaded, using synthetic data")
            # 生成合成测试数据
            test_data = self._generate_synthetic_data()
        
        # 运行测试
        passed_count = 0
        denied_count = 0
        total_notional = 0.0
        
        for item in test_data:
            # 构造OrderCtx
            order_ctx = OrderCtx(
                symbol=item.get("symbol", "BTCUSDT"),
                side=item.get("side", "buy"),
                order_type=item.get("order_type", "market"),
                qty=item.get("qty", 0.1),
                price=item.get("price", 50000.0),
                guards=item.get("guards", {
                    "spread_bps": 1.2,
                    "event_lag_sec": 0.04,
                    "activity_tpm": 15.0,
                }),
            )
            
            # 执行风控检查
            decision = pre_order_check(order_ctx)
            
            if decision.passed:
                passed_count += 1
                total_notional += order_ctx.qty * (order_ctx.price or 0.0)
            else:
                denied_count += 1
        
        total_count = len(test_data)
        pass_rate = passed_count / total_count if total_count > 0 else 0.0
        deny_rate = denied_count / total_count if total_count > 0 else 0.0
        
        # 获取指标
        metrics = get_metrics()
        latency_stats = metrics.get_latency_seconds_stats()
        
        result = {
            "label": label,
            "total_count": total_count,
            "passed_count": passed_count,
            "denied_count": denied_count,
            "pass_rate": pass_rate,
            "deny_rate": deny_rate,
            "total_notional": total_notional,
            "avg_latency_seconds": latency_stats.get("avg", 0.0),
            "p95_latency_seconds": latency_stats.get("p95", 0.0),
        }
        
        logger.info(
            f"[{label}] Total: {total_count}, Passed: {passed_count}, "
            f"Denied: {denied_count}, Pass Rate: {pass_rate:.2%}, "
            f"Deny Rate: {deny_rate:.2%}"
        )
        
        return result
    
    def _generate_synthetic_data(self, count: int = 1000) -> List[Dict]:
        """生成合成测试数据
        
        Args:
            count: 生成数量
            
        Returns:
            测试数据列表
        """
        import random
        
        test_data = []
        for i in range(count):
            test_data.append({
                "symbol": "BTCUSDT",
                "side": "buy" if i % 2 == 0 else "sell",
                "order_type": "market",
                "qty": 0.1 + random.uniform(-0.05, 0.05),
                "price": 50000.0 + random.uniform(-1000, 1000),
                "guards": {
                    "spread_bps": 1.2 + random.uniform(0, 10),
                    "event_lag_sec": 0.04 + random.uniform(0, 2),
                    "activity_tpm": 15.0 + random.uniform(-10, 10),
                },
            })
        
        return test_data
    
    def compare_results(self, legacy_result: Dict, inline_result: Dict) -> Dict:
        """对比legacy和inline的结果
        
        Args:
            legacy_result: Legacy模式结果
            inline_result: Inline模式结果
            
        Returns:
            对比结果
        """
        comparison = {
            "pass_rate_diff": abs(inline_result["pass_rate"] - legacy_result["pass_rate"]),
            "deny_rate_diff": abs(inline_result["deny_rate"] - legacy_result["deny_rate"]),
            "notional_diff_pct": abs(
                (inline_result["total_notional"] - legacy_result["total_notional"]) /
                max(legacy_result["total_notional"], 1.0)
            ),
            "latency_diff_pct": abs(
                (inline_result["avg_latency_seconds"] - legacy_result["avg_latency_seconds"]) /
                max(legacy_result["avg_latency_seconds"], 1e-6)
            ),
        }
        
        # 判断是否通过（±5%阈值）
        comparison["pass_rate_ok"] = comparison["pass_rate_diff"] <= self.threshold
        comparison["deny_rate_ok"] = comparison["deny_rate_diff"] <= self.threshold
        comparison["notional_ok"] = comparison["notional_diff_pct"] <= self.threshold
        comparison["latency_ok"] = comparison["latency_diff_pct"] <= self.threshold
        
        comparison["all_ok"] = (
            comparison["pass_rate_ok"] and
            comparison["deny_rate_ok"] and
            comparison["notional_ok"] and
            comparison["latency_ok"]
        )
        
        return comparison
    
    def run_regression_test(self) -> bool:
        """运行回归测试
        
        Returns:
            是否通过
        """
        logger.info("=" * 80)
        logger.info("Risk Module Regression Test")
        logger.info("=" * 80)
        
        # 基础配置
        base_config = {
            "risk": {
                "enabled": True,
                "guards": {
                    "spread_bps_max": 8.0,
                    "lag_sec_cap": 1.5,
                    "activity_min_tpm": 10.0,
                },
                "position": {
                    "max_notional_usd": 20000.0,
                    "max_leverage": 5.0,
                    "symbol_limits": {},
                },
            }
        }
        
        # 1. Legacy模式（RISK_INLINE_ENABLED=false）
        logger.info("\n[Step 1] Running test with RISK_INLINE_ENABLED=false (Legacy)")
        legacy_config = base_config.copy()
        legacy_config["risk"]["enabled"] = False
        legacy_result = self.run_test_with_config(legacy_config, "Legacy")
        
        # 2. Inline模式（RISK_INLINE_ENABLED=true）
        logger.info("\n[Step 2] Running test with RISK_INLINE_ENABLED=true (Inline)")
        inline_config = base_config.copy()
        inline_config["risk"]["enabled"] = True
        inline_result = self.run_test_with_config(inline_config, "Inline")
        
        # 3. 对比结果
        logger.info("\n[Step 3] Comparing results")
        comparison = self.compare_results(legacy_result, inline_result)
        
        # 4. 输出报告
        logger.info("\n" + "=" * 80)
        logger.info("Regression Test Results")
        logger.info("=" * 80)
        logger.info(f"Pass Rate Diff: {comparison['pass_rate_diff']:.4f} "
                   f"({'OK' if comparison['pass_rate_ok'] else 'FAIL'})")
        logger.info(f"Deny Rate Diff: {comparison['deny_rate_diff']:.4f} "
                   f"({'OK' if comparison['deny_rate_ok'] else 'FAIL'})")
        logger.info(f"Notional Diff: {comparison['notional_diff_pct']:.2%} "
                   f"({'OK' if comparison['notional_ok'] else 'FAIL'})")
        logger.info(f"Latency Diff: {comparison['latency_diff_pct']:.2%} "
                   f"({'OK' if comparison['latency_ok'] else 'FAIL'})")
        logger.info("=" * 80)
        
        if comparison["all_ok"]:
            logger.info("✅ Regression test PASSED (all metrics within ±5% threshold)")
        else:
            logger.error("❌ Regression test FAILED (some metrics exceed ±5% threshold)")
        
        return comparison["all_ok"]


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Risk Module Regression Test")
    parser.add_argument(
        "--test-data",
        type=str,
        default="./runtime/test_signals.jsonl",
        help="Test data file path (JSONL format)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.05,
        help="Threshold for comparison (default: 0.05, i.e., 5%)",
    )
    
    args = parser.parse_args()
    
    tester = RegressionTester(args.test_data, args.threshold)
    success = tester.run_regression_test()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

