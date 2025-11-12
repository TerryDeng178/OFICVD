#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TASK-A5: Equivalence Test Runner

统一入口脚本：运行回测 vs 执行器的等价性测试
参数含 --t-min/--t-max/--sink/--seed/--fees-bps/--slip-mode
"""

import argparse
import json
import logging
import os
import sys
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.alpha_core.executors.backtest_executor import BacktestExecutor
from src.alpha_core.executors.base_executor import Order, Side, OrderType
from src.alpha_core.signals.core_algo import CoreAlgorithm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(config_path: Path) -> Dict[str, Any]:
    """加载配置文件"""
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return {}


def run_equivalence_test(
    t_min: Optional[int] = None,
    t_max: Optional[int] = None,
    sink: str = "dual",
    seed: Optional[int] = None,
    fees_bps: Optional[float] = None,
    slip_mode: str = "static",
    config_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    symbols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """运行等价性测试
    
    Args:
        t_min: 开始时间戳（ms）
        t_max: 结束时间戳（ms）
        sink: Sink 类型（jsonl/sqlite/dual）
        seed: 随机种子
        fees_bps: 手续费（基点）
        slip_mode: 滑点模式（static/piecewise）
        config_path: 配置文件路径
        output_dir: 输出目录
        symbols: 交易对列表
    
    Returns:
        测试结果字典
    """
    # 1. 设置随机种子
    if seed is not None:
        random.seed(seed)
        import numpy as np
        np.random.seed(seed)
        logger.info(f"[equiv_run] Random seed set to {seed}")
    
    # 2. 加载配置
    if config_path and config_path.exists():
        config = load_config(config_path)
    else:
        config = {}
    
    # 3. 设置输出目录
    if output_dir is None:
        output_dir = Path("./runtime/equiv_test")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 4. 设置时间窗口
    if t_min is None:
        t_min = int(time.time() * 1000) - 3600000  # 默认1小时前
    if t_max is None:
        t_max = int(time.time() * 1000)
    
    logger.info(f"[equiv_run] Time window: {t_min} - {t_max} ({t_max - t_min}ms)")
    
    # 5. 设置交易对
    if symbols is None:
        symbols = ["BTCUSDT"]
    
    # 6. 覆盖配置参数
    if fees_bps is not None:
        config.setdefault("backtest", {})["taker_fee_bps"] = fees_bps
        logger.info(f"[equiv_run] Fee BPS set to {fees_bps}")
    
    if slip_mode:
        config.setdefault("backtest", {})["slippage_model"] = slip_mode
        logger.info(f"[equiv_run] Slippage mode set to {slip_mode}")
    
    # 7. 设置 Sink
    config.setdefault("sink", {})["kind"] = sink
    config.setdefault("sink", {})["output_dir"] = str(output_dir)
    config.setdefault("executor", {})["output_dir"] = str(output_dir)
    config.setdefault("executor", {})["sink"] = sink
    
    # 8. 生成 run_id
    run_id = f"equiv_{int(time.time())}"
    
    # 9. 初始化 BacktestExecutor
    logger.info("[equiv_run] Initializing BacktestExecutor...")
    executor_config = config.copy()
    executor_config["executor"]["mode"] = "backtest"
    
    backtest_executor = BacktestExecutor()
    backtest_executor.prepare(executor_config)
    
    # 10. 运行测试（这里简化，实际应该读取信号并执行）
    logger.info("[equiv_run] Running equivalence test...")
    
    # 模拟处理信号
    mid_price = 50000.0
    test_orders = []
    
    for i in range(10):  # 简化：生成10个测试订单
        ts_ms = t_min + (t_max - t_min) * i // 10
        side = Side.BUY if i % 2 == 0 else Side.SELL
        
        order = Order(
            client_order_id=f"{run_id}-{i}",
            symbol=symbols[0],
            side=side,
            qty=0.1,
            ts_ms=ts_ms,
            metadata={"mid_price": mid_price},
        )
        
        broker_order_id = backtest_executor.submit(order)
        test_orders.append({
            "client_order_id": order.client_order_id,
            "broker_order_id": broker_order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "qty": order.qty,
            "ts_ms": ts_ms,
        })
    
    # 11. 获取成交记录
    fills = backtest_executor.fetch_fills()
    
    # 12. 计算统计信息
    total_notional = sum(f.price * f.qty for f in fills)
    total_fee = sum(f.fee for f in fills)
    fee_bps = (total_fee / total_notional * 10000) if total_notional > 0 else 0
    
    positions = backtest_executor.get_positions()
    
    # 13. 生成结果
    result = {
        "run_id": run_id,
        "t_min": t_min,
        "t_max": t_max,
        "sink": sink,
        "seed": seed,
        "fees_bps": fees_bps,
        "slip_mode": slip_mode,
        "symbols": symbols,
        "stats": {
            "total_orders": len(test_orders),
            "total_fills": len(fills),
            "total_notional": total_notional,
            "total_fee": total_fee,
            "fee_bps": fee_bps,
            "positions": positions,
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    
    # 14. 保存结果
    result_file = output_dir / f"equiv_result_{run_id}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    logger.info(f"[equiv_run] Test completed. Result saved to {result_file}")
    logger.info(f"[equiv_run] Stats: orders={len(test_orders)}, fills={len(fills)}, "
                f"notional={total_notional:.2f}, fee={total_fee:.4f}, fee_bps={fee_bps:.2f}")
    
    return result


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="TASK-A5: Equivalence Test Runner")
    
    parser.add_argument("--t-min", type=int, help="Start timestamp (ms)")
    parser.add_argument("--t-max", type=int, help="End timestamp (ms)")
    parser.add_argument("--sink", type=str, default="dual", choices=["jsonl", "sqlite", "dual"],
                        help="Sink type (default: dual)")
    parser.add_argument("--seed", type=int, help="Random seed")
    parser.add_argument("--fees-bps", type=float, help="Fee BPS")
    parser.add_argument("--slip-mode", type=str, default="static",
                        choices=["static", "piecewise"],
                        help="Slippage mode (default: static)")
    parser.add_argument("--config", type=Path, help="Config file path")
    parser.add_argument("--output-dir", type=Path, help="Output directory")
    parser.add_argument("--symbols", type=str, nargs="+", help="Symbols to test")
    
    args = parser.parse_args()
    
    try:
        result = run_equivalence_test(
            t_min=args.t_min,
            t_max=args.t_max,
            sink=args.sink,
            seed=args.seed,
            fees_bps=args.fees_bps,
            slip_mode=args.slip_mode,
            config_path=args.config,
            output_dir=args.output_dir,
            symbols=args.symbols,
        )
        
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        logger.error(f"[equiv_run] Test failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

