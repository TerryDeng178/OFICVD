#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TASK-A5: Equivalence Test Runner

统一入口脚本：运行回测 vs 执行器的等价性测试
真正实现双路对比：BacktestExecutor vs Replay/Strategy Executor
"""

import argparse
import json
import logging
import os
import sys
import random
import time
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any, Iterator, Tuple
from datetime import datetime
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from alpha_core.executors.backtest_executor import BacktestExecutor
from alpha_core.executors.testnet_executor import TestnetExecutor
from alpha_core.executors.executor_factory import create_executor
from alpha_core.executors.base_executor import Order, Side, OrderType, Fill

# Import from mcp.strategy_server.app
# Note: These functions are used for signal processing
try:
    from mcp.strategy_server.app import (
        read_signals_from_jsonl,
        read_signals_from_sqlite,
        signal_to_order,
        process_signals,
        _select_top_signals,
    )
except ImportError:
    # Fallback: define minimal versions if import fails
    logger.warning("[equiv_run] Could not import from mcp.strategy_server.app, using fallback")
    def read_signals_from_jsonl(*args, **kwargs):
        return iter([])
    def read_signals_from_sqlite(*args, **kwargs):
        return iter([])
    def signal_to_order(*args, **kwargs):
        return None
    def process_signals(*args, **kwargs):
        return {}
    def _select_top_signals(signals):
        return signals, 0

EPSILON = 1e-8  # 等价性容差（double 精度门限）


def load_config(config_path: Path) -> Dict[str, Any]:
    """加载配置文件"""
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return {}


def read_signals(
    output_dir: Path,
    sink: str,
    symbols: List[str],
    t_min: Optional[int] = None,
    t_max: Optional[int] = None,
    run_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """读取 v2 信号（支持 JSONL 和 SQLite）
    
    Args:
        output_dir: 输出目录
        sink: Sink 类型（jsonl/sqlite/dual）
        symbols: 交易对列表
        t_min: 开始时间戳（ms）
        t_max: 结束时间戳（ms）
        run_id: 运行ID（可选）
    
    Returns:
        信号列表
    """
    signals = []
    
    # 优先从 SQLite 读取（如果存在）
    if sink in ("sqlite", "dual"):
        db_path = output_dir / "signals_v2.db"
        if not db_path.exists():
            db_path = output_dir / "signals.db"
        
        if db_path.exists():
            logger.info(f"[equiv_run] Reading signals from SQLite: {db_path}")
            for signal in read_signals_from_sqlite(db_path, symbols):
                # 时间窗口过滤
                if t_min and signal.get("ts_ms", 0) < t_min:
                    continue
                if t_max and signal.get("ts_ms", 0) > t_max:
                    continue
                # run_id 过滤
                if run_id and signal.get("run_id") != run_id:
                    continue
                signals.append(signal)
    
    # 从 JSONL 读取（如果 SQLite 没有或 sink=jsonl）
    if sink in ("jsonl", "dual") and (not signals or sink == "jsonl"):
        jsonl_dir = output_dir / "ready" / "signal"
        if jsonl_dir.exists():
            logger.info(f"[equiv_run] Reading signals from JSONL: {jsonl_dir}")
            jsonl_signals = []
            for signal in read_signals_from_jsonl(jsonl_dir, symbols):
                # 时间窗口过滤
                if t_min and signal.get("ts_ms", 0) < t_min:
                    continue
                if t_max and signal.get("ts_ms", 0) > t_max:
                    continue
                # run_id 过滤
                if run_id and signal.get("run_id") != run_id:
                    continue
                jsonl_signals.append(signal)
            
            # 如果 SQLite 没有数据，使用 JSONL
            if not signals:
                signals = jsonl_signals
            # 如果 dual sink，合并去重
            elif sink == "dual":
                # 按 (symbol, ts_ms, signal_id) 去重
                signal_map = {(s.get("symbol"), s.get("ts_ms"), s.get("signal_id")): s for s in signals}
                for s in jsonl_signals:
                    key = (s.get("symbol"), s.get("ts_ms"), s.get("signal_id"))
                    if key not in signal_map:
                        signal_map[key] = s
                signals = list(signal_map.values())
    
    # 应用 Top-1 选择（同 (symbol, ts_ms) 仅保留 |score| 最大的一条）
    signals, removed = _select_top_signals(signals)
    if removed > 0:
        logger.info(f"[equiv_run] Top-1 filter removed {removed} duplicate signal(s)")
    
    # 契约校验：confirm=true ⇒ gating=1 && decision_code=OK
    valid_signals = []
    for sig in signals:
        if sig.get("confirm") is True:
            gating = sig.get("gating", 1)
            if isinstance(gating, bool):
                gating = 1 if gating else 0
            decision_code = sig.get("decision_code")
            
            if gating != 1 or (decision_code is not None and decision_code != "OK"):
                logger.warning(
                    f"[Contract] Skipping invalid signal: signal_id={sig.get('signal_id')}, "
                    f"gating={gating}, decision_code={decision_code}"
                )
                continue
        
        valid_signals.append(sig)
    
    logger.info(f"[equiv_run] Loaded {len(valid_signals)} valid signals (filtered from {len(signals)})")
    return valid_signals


def run_path_a_backtest(
    signals: List[Dict[str, Any]],
    config: Dict[str, Any],
    executor_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """路径A：BacktestExecutor
    
    Args:
        signals: 信号列表
        config: 配置字典
        executor_cfg: executor配置
    
    Returns:
        执行结果统计
    """
    logger.info("[equiv_run] Path A: Running BacktestExecutor...")
    
    executor = BacktestExecutor()
    executor_config = config.copy()
    executor_config["executor"]["mode"] = "backtest"
    executor.prepare(executor_config)
    
    # 处理确认信号（confirm=true）
    confirmed_signals = [s for s in signals if s.get("confirm") is True]
    logger.info(f"[equiv_run] Path A: Processing {len(confirmed_signals)} confirmed signals")
    
    mid_price = 50000.0  # 默认中间价（实际应从行情获取）
    
    for sig in confirmed_signals:
        side = Side.BUY if sig.get("side_hint") == "buy" else Side.SELL
        order = Order(
            client_order_id=sig.get("signal_id", f"backtest-{sig.get('ts_ms')}"),
            symbol=sig.get("symbol", "BTCUSDT"),
            side=side,
            qty=executor_cfg.get("order_size_usd", 100) / mid_price,  # 简化：使用固定价格计算数量
            ts_ms=sig.get("ts_ms", 0),
            metadata={"mid_price": mid_price},
        )
        executor.submit(order)
    
    # 获取成交记录
    fills = executor.fetch_fills()
    positions = executor.positions  # 直接访问 positions 属性
    
    # 计算统计信息
    total_notional = sum(f.price * f.qty for f in fills)
    total_fee = sum(f.fee for f in fills)
    fee_bps = (total_fee / total_notional * 10000) if total_notional > 0 else 0
    
    # 计算 PNL（简化：基于持仓和成交）
    pnl = 0.0
    for symbol, qty in positions.items():
        # 简化：假设平仓价格为当前中间价
        # 实际应该跟踪开仓价格
        pnl += qty * mid_price  # 简化计算
    
    return {
        "fills": fills,
        "positions": positions,
        "total_notional": total_notional,
        "total_fee": total_fee,
        "fee_bps": fee_bps,
        "pnl": pnl,
        "total_orders": len(confirmed_signals),
        "total_fills": len(fills),
    }


def run_path_b_replay(
    signals: List[Dict[str, Any]],
    config: Dict[str, Any],
    executor_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """路径B：Replay/Strategy Executor（dry-run模式）
    
    Args:
        signals: 信号列表
        config: 配置字典
        executor_cfg: executor配置
    
    Returns:
        执行结果统计
    """
    logger.info("[equiv_run] Path B: Running Replay Executor (dry-run)...")
    
    # 使用 TestnetExecutor 的 dry-run 模式
    executor = TestnetExecutor()
    executor_config = config.copy()
    executor_config["executor"]["mode"] = "testnet"
    executor_config["broker"]["dry_run"] = True  # 启用 dry-run
    executor.prepare(executor_config)
    
    # 使用 process_signals 处理信号（与 Strategy Server 一致）
    stats = process_signals(executor, iter(signals), executor_cfg)
    
    # 获取成交记录
    fills = executor.fetch_fills()
    positions = executor.positions  # 直接访问 positions 属性
    
    # 计算统计信息
    total_notional = sum(f.price * f.qty for f in fills)
    total_fee = sum(f.fee for f in fills)
    fee_bps = (total_fee / total_notional * 10000) if total_notional > 0 else 0
    
    # 计算 PNL（简化：基于持仓和成交）
    mid_price = 50000.0  # 默认中间价
    pnl = 0.0
    for symbol, qty in positions.items():
        pnl += qty * mid_price  # 简化计算
    
    return {
        "fills": fills,
        "positions": positions,
        "total_notional": total_notional,
        "total_fee": total_fee,
        "fee_bps": fee_bps,
        "pnl": pnl,
        "total_orders": stats.get("orders_submitted", 0),
        "total_fills": len(fills),
    }


def compare_results(
    path_a: Dict[str, Any],
    path_b: Dict[str, Any],
    run_id: str,
) -> Dict[str, Any]:
    """对比两条路径的结果
    
    Args:
        path_a: 路径A（BacktestExecutor）的结果
        path_b: 路径B（Replay Executor）的结果
        run_id: 运行ID
    
    Returns:
        对比结果字典
    """
    logger.info("[equiv_run] Comparing results...")
    
    diff = {
        "run_id": run_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "comparison": {},
        "violations": [],
        "max_errors": {},
    }
    
    # 1. 对比成交数量
    fills_a = path_a["fills"]
    fills_b = path_b["fills"]
    diff["comparison"]["fill_count"] = {
        "path_a": len(fills_a),
        "path_b": len(fills_b),
        "diff": abs(len(fills_a) - len(fills_b)),
    }
    
    if len(fills_a) != len(fills_b):
        diff["violations"].append({
            "type": "fill_count_mismatch",
            "path_a": len(fills_a),
            "path_b": len(fills_b),
        })
    
    # 2. 逐笔成交对比（方向/数量/价格）
    fills_a_sorted = sorted(fills_a, key=lambda f: (f.ts_ms, f.client_order_id))
    fills_b_sorted = sorted(fills_b, key=lambda f: (f.ts_ms, f.client_order_id))
    
    fill_errors = []
    max_fill_error = {
        "price_diff": 0.0,
        "qty_diff": 0.0,
        "fee_diff": 0.0,
    }
    
    for i, (fill_a, fill_b) in enumerate(zip(fills_a_sorted, fills_b_sorted)):
        # 方向一致
        if fill_a.side != fill_b.side:
            fill_errors.append({
                "index": i,
                "type": "side_mismatch",
                "path_a": fill_a.side.value if fill_a.side else None,
                "path_b": fill_b.side.value if fill_b.side else None,
            })
        
        # 价格一致（允许误差）
        price_diff = abs(fill_a.price - fill_b.price)
        if price_diff > EPSILON:
            fill_errors.append({
                "index": i,
                "type": "price_mismatch",
                "path_a": fill_a.price,
                "path_b": fill_b.price,
                "diff": price_diff,
            })
            max_fill_error["price_diff"] = max(max_fill_error["price_diff"], price_diff)
        
        # 数量一致（允许误差）
        qty_diff = abs(fill_a.qty - fill_b.qty)
        if qty_diff > EPSILON:
            fill_errors.append({
                "index": i,
                "type": "qty_mismatch",
                "path_a": fill_a.qty,
                "path_b": fill_b.qty,
                "diff": qty_diff,
            })
            max_fill_error["qty_diff"] = max(max_fill_error["qty_diff"], qty_diff)
        
        # 费用一致（允许误差）
        fee_diff = abs(fill_a.fee - fill_b.fee)
        if fee_diff > EPSILON:
            fill_errors.append({
                "index": i,
                "type": "fee_mismatch",
                "path_a": fill_a.fee,
                "path_b": fill_b.fee,
                "diff": fee_diff,
            })
            max_fill_error["fee_diff"] = max(max_fill_error["fee_diff"], fee_diff)
    
    diff["comparison"]["fill_errors"] = fill_errors
    diff["max_errors"]["fills"] = max_fill_error
    
    # 3. 对比费用模型
    diff["comparison"]["fee_bps"] = {
        "path_a": path_a["fee_bps"],
        "path_b": path_b["fee_bps"],
        "diff": abs(path_a["fee_bps"] - path_b["fee_bps"]),
    }
    
    if abs(path_a["fee_bps"] - path_b["fee_bps"]) > 1.0:  # 允许1 bps误差
        diff["violations"].append({
            "type": "fee_bps_mismatch",
            "path_a": path_a["fee_bps"],
            "path_b": path_b["fee_bps"],
        })
    
    # 4. 对比持仓路径
    positions_a = path_a["positions"]
    positions_b = path_b["positions"]
    
    position_errors = []
    for symbol in set(list(positions_a.keys()) + list(positions_b.keys())):
        qty_a = positions_a.get(symbol, 0.0)
        qty_b = positions_b.get(symbol, 0.0)
        qty_diff = abs(qty_a - qty_b)
        
        if qty_diff > EPSILON:
            position_errors.append({
                "symbol": symbol,
                "path_a": qty_a,
                "path_b": qty_b,
                "diff": qty_diff,
            })
    
    diff["comparison"]["position_errors"] = position_errors
    
    # 5. 对比 PNL
    pnl_diff = abs(path_a["pnl"] - path_b["pnl"])
    diff["comparison"]["pnl"] = {
        "path_a": path_a["pnl"],
        "path_b": path_b["pnl"],
        "diff": pnl_diff,
    }
    
    if pnl_diff > EPSILON:
        diff["violations"].append({
            "type": "pnl_mismatch",
            "path_a": path_a["pnl"],
            "path_b": path_b["pnl"],
            "diff": pnl_diff,
        })
        diff["max_errors"]["pnl_diff"] = pnl_diff
    
    # 6. 汇总
    diff["summary"] = {
        "total_violations": len(diff["violations"]),
        "fill_errors_count": len(fill_errors),
        "position_errors_count": len(position_errors),
        "passed": len(diff["violations"]) == 0,
    }
    
    return diff


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
    signals_dir: Optional[Path] = None,
    run_id: Optional[str] = None,
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
        signals_dir: 信号目录（如果指定，从此读取信号）
        run_id: 运行ID（如果指定，过滤特定运行）
    
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
    if run_id is None:
        run_id = f"equiv_{int(time.time())}"
    
    # 9. 读取信号
    if signals_dir:
        signals_dir = Path(signals_dir)
    else:
        signals_dir = output_dir
    
    logger.info(f"[equiv_run] Reading signals from {signals_dir} (sink={sink}, run_id={run_id})")
    signals = read_signals(signals_dir, sink, symbols, t_min, t_max, run_id)
    
    if not signals:
        logger.warning("[equiv_run] No signals found, cannot run equivalence test")
        return {
            "run_id": run_id,
            "error": "No signals found",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    
    logger.info(f"[equiv_run] Loaded {len(signals)} signals")
    
    # 10. 执行路径A：BacktestExecutor
    executor_cfg = config.get("executor", {})
    path_a_result = run_path_a_backtest(signals, config, executor_cfg)
    
    # 11. 执行路径B：Replay Executor（dry-run）
    path_b_result = run_path_b_replay(signals, config, executor_cfg)
    
    # 12. 对比结果
    diff_result = compare_results(path_a_result, path_b_result, run_id)
    
    # 13. 保存差异快照
    diff_file = output_dir / f"equiv_diff_{run_id}.json"
    with open(diff_file, "w", encoding="utf-8") as f:
        json.dump(diff_result, f, indent=2, ensure_ascii=False, default=str)
    
    logger.info(f"[equiv_run] Difference snapshot saved to {diff_file}")
    
    # 14. 断言等价性
    if not diff_result["summary"]["passed"]:
        logger.error(f"[equiv_run] Equivalence test FAILED: {diff_result['summary']['total_violations']} violations")
        logger.error(f"[equiv_run] Violations: {diff_result['violations']}")
        logger.error(f"[equiv_run] Max errors: {diff_result['max_errors']}")
        return diff_result
    
    logger.info("[equiv_run] Equivalence test PASSED: All comparisons within tolerance")
    
    return diff_result


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
    parser.add_argument("--signals-dir", type=Path, help="Signals directory (if different from output_dir)")
    parser.add_argument("--run-id", type=str, help="Run ID to filter signals")
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
            signals_dir=args.signals_dir,
            run_id=args.run_id,
            symbols=args.symbols,
        )
        
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        
        # 如果测试失败，返回非零退出码
        if result.get("summary", {}).get("passed", False) is False:
            return 1
        
        return 0
    except Exception as e:
        logger.error(f"[equiv_run] Test failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
