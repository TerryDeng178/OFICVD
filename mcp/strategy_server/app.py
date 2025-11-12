# -*- coding: utf-8 -*-
"""Strategy Server MCP thin shell.

集成IExecutor执行层，从signals读取信号并执行订单
"""

from __future__ import annotations

import argparse
import builtins
import json
import logging
import signal as signal_module
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, Iterator, Optional, Set, Tuple, List, Any

import yaml

from alpha_core.executors import create_executor, IExecutor, Order, Side, OrderType
from alpha_core.backtest.reader import DataReader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class _FeaturesImportGuard:
    """TASK-B1: Import层硬闸 - 拦截features包导入"""

    def __init__(self):
        self.blocked_patterns = ['features', 'features.']

    def find_spec(self, fullname, path, target=None):
        """拦截模块导入"""
        if any(fullname.startswith(pattern) for pattern in self.blocked_patterns):
            logger.error(f"[TASK-B1] BLOCKED_IMPORT: 禁止导入features相关模块: {fullname}")
            raise ImportError(f"[TASK-B1] TASK_B1_BOUNDARY_VIOLATION: Strategy层禁止访问features: {fullname}")
        return None

class _PathAccessGuard:
    """TASK-B1: 路径层硬闸 - 检测文件系统访问"""

    def __init__(self):
        self.blocked_patterns = ['features', 'features/', 'features\\', '/features', '\\features']

    def _check_path_blocked(self, path_str: str) -> bool:
        """检查路径是否被阻塞"""
        path_lower = path_str.lower()
        return any(pattern in path_lower for pattern in self.blocked_patterns)

    def patched_open(self, original_open):
        """包装open函数"""
        def wrapper(file, mode='r', buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
            if self._check_path_blocked(str(file)):
                logger.error(f"[TASK-B1] BLOCKED_PATH: 禁止访问features路径: {file}")
                raise PermissionError(f"[TASK-B1] TASK_B1_BOUNDARY_VIOLATION: Strategy层禁止访问features路径: {file}")
            return original_open(file, mode, buffering, encoding, errors, newline, closefd, opener)
        return wrapper

    def patched_path_init(self, original_init):
        """包装Path.__init__"""
        def wrapper(self, *args, **kwargs):
            result = original_init(self, *args, **kwargs)
            path_str = str(self)
            if self._check_path_blocked(path_str):
                logger.error(f"[TASK-B1] BLOCKED_PATH: 禁止访问features路径: {path_str}")
                raise PermissionError(f"[TASK-B1] TASK_B1_BOUNDARY_VIOLATION: Strategy层禁止访问features路径: {path_str}")
            return result
        return wrapper

def _install_boundary_hard_gates():
    """TASK-B1: 安装三层硬闸 - Import/路径/IO"""
    # 1. Import层：注册meta_path拦截器
    import_guard = _FeaturesImportGuard()
    sys.meta_path.insert(0, import_guard)

    # 2. IO层：包装open函数
    path_guard = _PathAccessGuard()
    original_open = open
    builtins.open = path_guard.patched_open(original_open)

    # 3. 路径层：包装Path初始化（如果可用）
    try:
        from pathlib import Path
        original_path_init = Path.__init__
        Path.__init__ = path_guard.patched_path_init(original_path_init)
    except ImportError:
        pass  # Python < 3.4 没有pathlib

    logger.info("[TASK-B1] HARD_GATES_INSTALLED: 三层硬闸已激活 - Import/路径/IO层features访问拦截")

def _validate_signals_only_boundary() -> None:
    """TASK-B1: 信号边界固化 - fail-fast 断言

    确保Strategy层只读signals，禁止任何features访问。
    此断言在启动时执行，如果发现features相关代码立即退出。
    """
    import inspect

    # 检查当前调用栈中是否有features相关的导入或访问
    current_frame = inspect.currentframe()
    try:
        while current_frame:
            frame_info = inspect.getframeinfo(current_frame)
            source_lines = frame_info.code_context or []

            for line in source_lines:
                line_lower = line.lower().strip()
                # 检查是否包含features路径访问
                if any(keyword in line_lower for keyword in [
                    'features/', 'features\\', '/features', '\\features',
                    'from features', 'import features'
                ]):
                    logger.error(f"[TASK-B1] ERROR: 检测到禁止的features访问: {line.strip()}")
                    logger.error(f"[TASK-B1] ERROR: 文件: {frame_info.filename}:{frame_info.lineno}")
                    logger.error("[TASK-B1] ERROR: Strategy层必须只读signals，禁止访问features")
                    sys.exit(1)

            current_frame = current_frame.f_back
    finally:
        del current_frame

    logger.info("[TASK-B1] OK: 信号边界验证通过：Strategy仅读signals")


def load_config(config_path: Optional[str]) -> Dict:
    """加载配置文件"""
    if not config_path:
        return {}
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}


def read_signals_from_jsonl(signals_dir: Path, symbols: Optional[list] = None, processed_files: Optional[Set[str]] = None, last_positions: Optional[Dict[str, int]] = None) -> Iterator[Dict]:
    """从JSONL文件读取信号
    
    Args:
        signals_dir: 信号目录（ready/signal/<symbol>/signals-*.jsonl 或 signals_*.jsonl）
        symbols: 交易对列表（可选）
        processed_files: 已处理文件集合（用于增量读取）
        last_positions: 文件上次读取位置（用于增量读取）
        
    Yields:
        信号字典
        
    Note:
        - v2 标准命名：signals-YYYYMMDD-HH.jsonl（连字符，按小时轮转）
        - v1 兼容命名：signals_YYYYMMDD_HHMM.jsonl（下划线，按分钟轮转）
        - 优先读取 v2 格式，兼容 v1 格式
    """
    if not signals_dir.exists():
        logger.warning(f"Signals directory not found: {signals_dir}")
        return
    
    if processed_files is None:
        processed_files = set()
    if last_positions is None:
        last_positions = {}
    
    # TASK-B1: 补扫顶层signals文件（P0修复）
    # 先处理顶层signals-*.jsonl / signals_*.jsonl文件
    top_level_files_v2 = sorted(signals_dir.glob("signals-*.jsonl"))
    top_level_files_v1 = sorted(signals_dir.glob("signals_*.jsonl"))
    top_level_files = top_level_files_v2 + top_level_files_v1

    for jsonl_file in top_level_files:
        file_key = str(jsonl_file)
        try:
            with jsonl_file.open("r", encoding="utf-8") as f:
                # 如果是增量读取，跳转到上次位置
                if file_key in last_positions:
                    f.seek(last_positions[file_key])

                # 读取新内容
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    signal = json.loads(line)
                    yield signal

                # 更新最后位置
                if processed_files is not None:
                    processed_files.add(file_key)

        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Error reading top-level JSONL file {jsonl_file}: {e}")
            continue

    # 查找所有JSONL文件（兼容v2和v1命名）
    if symbols:
        symbol_dirs = [signals_dir / symbol.upper() for symbol in symbols]
    else:
        symbol_dirs = [d for d in signals_dir.iterdir() if d.is_dir()]

    for symbol_dir in symbol_dirs:
        if not symbol_dir.exists():
            continue

        # TASK-A4优化：同时匹配v2格式（signals-*.jsonl）和v1格式（signals_*.jsonl）
        # 优先v2格式（新标准），然后兼容v1格式
        jsonl_files_v2 = sorted(symbol_dir.glob("signals-*.jsonl"))
        jsonl_files_v1 = sorted(symbol_dir.glob("signals_*.jsonl"))
        jsonl_files = jsonl_files_v2 + jsonl_files_v1
        for jsonl_file in jsonl_files:
            file_key = str(jsonl_file)
            try:
                with jsonl_file.open("r", encoding="utf-8") as f:
                    # 如果是增量读取，跳转到上次位置
                    if file_key in last_positions:
                        f.seek(last_positions[file_key])
                    
                    # 读取新内容
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        signal = json.loads(line)
                        yield signal
                    
                    # 更新位置
                    last_positions[file_key] = f.tell()
                    processed_files.add(file_key)
            except Exception as e:
                logger.error(f"Failed to read {jsonl_file}: {e}")


def _select_top_signals(signals: List[Dict]) -> Tuple[List[Dict], int]:
    """按 (symbol, ts_ms) 选择 |score| 最大的信号"""
    best: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for index, signal in enumerate(signals):
        symbol = signal.get("symbol") or signal.get("symbol_id")
        ts_ms = signal.get("ts_ms")
        if symbol is None or ts_ms is None:
            continue
        key = (str(symbol).upper(), int(ts_ms))
        score_val = signal.get("score")
        if score_val is None:
            # fallback: 部分旧信号可能只提供 meta.score
            score_val = signal.get("meta", {}).get("score")
        try:
            abs_score = abs(float(score_val)) if score_val is not None else 0.0
        except (TypeError, ValueError):
            abs_score = 0.0
        best_entry = best.get(key)
        if not best_entry or abs_score > best_entry["abs_score"] or (
            abs_score == best_entry["abs_score"] and index < best_entry["index"]
        ):
            best[key] = {
                "signal": signal,
                "abs_score": abs_score,
                "index": index,
            }
    filtered = [entry["signal"] for entry in sorted(best.values(), key=lambda item: item["index"])]
    removed = len(signals) - len(filtered)
    return filtered, removed


def read_signals_from_sqlite(db_path: Path, symbols: Optional[list] = None, last_ts_ms: Optional[int] = None) -> Iterator[Dict]:
    """从SQLite读取信号（支持增量读取）
    
    Args:
        db_path: SQLite数据库路径
        symbols: 交易对列表（可选）
        last_ts_ms: 上次读取的最大时间戳（用于增量读取）
        
    Yields:
        信号字典
    """
    if not db_path.exists():
        logger.warning(f"SQLite database not found: {db_path}")
        return
    
    try:
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        
        # 检测表结构：优先使用 signal/v2 字段
        cursor = conn.execute("PRAGMA table_info(signals)")
        columns = [row[1] for row in cursor.fetchall()]
        is_v2 = "side_hint" in columns and "schema_version" in columns
        
        if is_v2:
            # Signal v2 格式
            query = "SELECT ts_ms, symbol, signal_id, score, side_hint, z_ofi, z_cvd, regime, div_type, confirm, gating, decision_code, decision_reason, config_hash, run_id, meta FROM signals"
        else:
            # Signal v1 格式（向后兼容）
            query = "SELECT ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, signal_type, confirm, gating, guard_reason, run_id FROM signals"
        
        conditions = []
        params = []
        
        if symbols:
            placeholders = ",".join("?" * len(symbols))
            conditions.append(f"symbol IN ({placeholders})")
            params.extend([s.upper() for s in symbols])
        
        # 增量读取：只读取新信号
        if last_ts_ms is not None:
            conditions.append("ts_ms > ?")
            params.append(last_ts_ms)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY ts_ms, symbol"
        
        cursor = conn.execute(query, params)
        for row in cursor:
            if is_v2:
                signal = {
                    "ts_ms": row["ts_ms"],
                    "symbol": row["symbol"],
                    "signal_id": row["signal_id"],
                    "score": row["score"],
                    "side_hint": row["side_hint"],
                    "z_ofi": row["z_ofi"],
                    "z_cvd": row["z_cvd"],
                    "regime": row["regime"],
                    "div_type": row["div_type"],
                    "confirm": bool(row["confirm"]),  # SQLite 存储为 INTEGER
                    "gating": row["gating"],
                    "decision_code": row["decision_code"],
                    "decision_reason": row["decision_reason"],
                    "config_hash": row["config_hash"],
                    "run_id": row["run_id"],
                    "meta": json.loads(row["meta"]) if row["meta"] else None,
                }
            else:
                # v1 格式：转换为 v2 兼容格式
                # TASK-A4优化: 统一使用decision_reason字段（v1的guard_reason映射为decision_reason）
                signal = {
                    "ts_ms": row["ts_ms"],
                    "symbol": row["symbol"],
                    "score": row["score"],
                    "z_ofi": row["z_ofi"],
                    "z_cvd": row["z_cvd"],
                    "regime": row["regime"],
                    "div_type": row["div_type"],
                    "signal_type": row["signal_type"],  # v1 字段（保留用于兼容）
                    "confirm": bool(row["confirm"]),
                    "gating": row["gating"],
                    "decision_reason": row["guard_reason"],  # v1的guard_reason统一映射为decision_reason
                    "guard_reason": row["guard_reason"],  # 保留旧字段名用于向后兼容
                    "run_id": row["run_id"],
                }
            yield signal
        
        conn.close()
    except Exception as e:
        logger.error(f"Failed to read from SQLite: {e}")


def signal_to_order(signal: Dict, executor_cfg: Dict) -> Optional[Order]:
    """将信号转换为订单（支持 signal/v1 和 signal/v2）
    
    Args:
        signal: 信号字典
        executor_cfg: executor配置
        
    Returns:
        Order对象，如果信号未确认或被门控则返回None
    """
    # TASK-A4: 只处理 confirm=true 的信号（单点判定）
    confirm = signal.get("confirm", False)
    if not confirm:
        return None
    
    # TASK-A4: v2 格式下，confirm=true 意味着 gating=1，不需要再检查
    # 但为了兼容 v1，仍然检查 gating
    gating = signal.get("gating", 1)
    if isinstance(gating, bool):
        gating = 1 if gating else 0
    if gating != 1:
        return None
    
    # 确定方向：优先使用 v2 的 side_hint，回退到 v1 的 signal_type
    side_hint = signal.get("side_hint")
    if side_hint:
        # Signal v2 格式
        if side_hint == "buy":
            side = Side.BUY
        elif side_hint == "sell":
            side = Side.SELL
        else:
            return None  # flat 或未知
    else:
        # Signal v1 格式（向后兼容）
        signal_type = signal.get("signal_type", "neutral")
        if signal_type in ("buy", "strong_buy"):
            side = Side.BUY
        elif signal_type in ("sell", "strong_sell"):
            side = Side.SELL
        else:
            return None
    
    # 计算订单数量（使用order_size_usd）
    order_size_usd = executor_cfg.get("order_size_usd", 100)
    
    # 获取价格：优先从 meta 获取，其次从 signal 直接获取
    mid_price = None
    if signal.get("meta") and isinstance(signal["meta"], dict):
        mid_price = signal["meta"].get("mid_price") or signal["meta"].get("price")
    if not mid_price:
        mid_price = signal.get("mid_price") or signal.get("price", 0.0)
    
    # 如果没有价格，使用默认价格估算（仅用于计算数量，实际成交价由交易所决定）
    if not mid_price or mid_price <= 0:
        # 优先从 executor_cfg 获取显式覆盖
        override_mid = executor_cfg.get("default_mid_price")
        if override_mid:
            mid_price = float(override_mid)
        else:
            # 使用一个合理的默认值（BTC 约 50000，ETH 约 2000）
            symbol = signal.get("symbol", "").upper()
            if "BTC" in symbol:
                mid_price = 50000.0  # 与等价性测试保持一致
            elif "ETH" in symbol:
                mid_price = 2000.0
            else:
                mid_price = 1000.0  # 默认值

        logger.debug(f"No price in signal, using default mid_price={mid_price} for {symbol}")
    
    qty = order_size_usd / mid_price if mid_price > 0 else 0.0
    
    # 生成client_order_id（幂等键）
    ts_ms = signal.get("ts_ms", 0)
    symbol = signal.get("symbol", "UNKNOWN")
    signal_id = signal.get("signal_id")
    run_id = signal.get("run_id", "default")

    # 生成 ≤36 且确定唯一的 client_order_id
    if signal_id and len(signal_id) <= 36:
        client_order_id = signal_id
    else:
        run_id_short   = (run_id or "default")[:10]
        ts_short       = str(ts_ms)[-6:]
        seq_short      = f"{int(signal.get('seq', 0))%100:02d}"
        symbol_short   = (symbol or "UNK")[-4:]
        client_order_id = f"{run_id_short}-{ts_short}-{seq_short}-{symbol_short}"
    
    # 创建Order对象
    order = Order(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        qty=qty,
        order_type=OrderType.MARKET,  # 默认市价单
        ts_ms=ts_ms,
        metadata={
            "mid_price": mid_price,
            "score": signal.get("score"),
            "z_ofi": signal.get("z_ofi"),
            "z_cvd": signal.get("z_cvd"),
            "regime": signal.get("regime"),
            "div_type": signal.get("div_type"),
            "decision_code": signal.get("decision_code"),
            "signal_id": signal_id,
        },
    )
    
    return order


def process_signals(executor: IExecutor, signals: Iterator[Dict], executor_cfg: Dict) -> Dict:
    """处理信号并执行订单
    
    Args:
        executor: 执行器实例
        signals: 信号迭代器
        executor_cfg: executor配置
        
    Returns:
        处理统计信息
    """
    stats = {
        "total_signals": 0,
        "confirmed_signals": 0,
        "gated_signals": 0,
        "orders_submitted": 0,
        "orders_filled": 0,
        "orders_rejected": 0,
    }
    
    collected_signals = list(signals)
    stats["original_signals"] = len(collected_signals)
    filtered_signals, removed = _select_top_signals(collected_signals)
    if removed > 0:
        logger.info(
            "[StrategyServer] Top-1 filter removed %s duplicate signal(s) (grouped by symbol+ts_ms)",
            removed,
        )
    stats["total_signals"] = len(filtered_signals)
    stats["top1_filtered"] = removed

    for signal in filtered_signals:
        
        # TASK-A4: 只处理 confirm=true 的信号（单点判定）
        confirm = signal.get("confirm", False)
        if not confirm:
            continue
        stats["confirmed_signals"] += 1
        
        # TASK-A4优化：契约一致性检查（confirm=true ⇒ gating=1 && decision_code=OK）
        # 在Schema层已有校验，这里做防呆检查（读取v2时decision_code字段存在）
        if confirm:
            gating = signal.get("gating", 1)
            if isinstance(gating, bool):
                gating = 1 if gating else 0
            decision_code = signal.get("decision_code")
            
            if gating != 1 or (decision_code is not None and decision_code != "OK"):
                signal_id = signal.get("signal_id", "unknown")
                logger.error(
                    f"[Contract] confirm=true but gating!=1 or decision_code!=OK: "
                    f"signal_id={signal_id}, gating={gating}, decision_code={decision_code}"
                )
                stats["gated_signals"] += 1
                continue
        
        # 转换为订单（signal_to_order 会再次检查 confirm 和 gating）
        order = signal_to_order(signal, executor_cfg)
        if not order:
            continue
        
        # 提交订单
        try:
            broker_order_id = executor.submit(order)
            stats["orders_submitted"] += 1
            logger.info(
                f"[StrategyServer] Order submitted: {order.client_order_id}, "
                f"symbol={order.symbol}, side={order.side.value}, qty={order.qty}"
            )
        except Exception as e:
            logger.error(f"[StrategyServer] Failed to submit order: {e}")
            stats["orders_rejected"] += 1
    
    # 获取成交记录
    fills = executor.fetch_fills()
    stats["orders_filled"] = len(fills)
    
    return stats


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Strategy Server with IExecutor")
    parser.add_argument(
        "--config",
        type=str,
        default="./config/defaults.yaml",
        help="Configuration file path",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["backtest", "testnet", "live"],
        help="Execution mode (overrides config)",
    )
    parser.add_argument(
        "--signals-source",
        type=str,
        choices=["jsonl", "sqlite", "auto"],
        default="auto",
        help="Signals source type",
    )
    parser.add_argument(
        "--signals-dir",
        type=str,
        help="Signals directory (for JSONL source)",
    )
    parser.add_argument(
        "--sink",
        type=str,
        choices=["jsonl", "sqlite", "dual"],
        help="Sink type (overrides config)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output directory (overrides config)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        help="Symbols to process (e.g., BTCUSDT ETHUSDT)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch mode: continuously monitor for new signals",
    )
    parser.add_argument(
        "--check-interval",
        type=float,
        default=1.0,
        help="Check interval in seconds for watch mode (default: 1.0)",
    )
    
    args = parser.parse_args()
    
    # 加载配置
    cfg = load_config(args.config)

    # TASK-B1: 信号边界固化 - 安装三层硬闸
    logger.info("[TASK-B1] INSTALLING_HARD_GATES: 安装Import/路径/IO三层硬闸...")
    _install_boundary_hard_gates()

    # TASK-B1: 信号边界固化 - 验证Strategy仅读signals
    logger.info("[TASK-B1] CHECK: 执行信号边界验证...")
    _validate_signals_only_boundary()

    # 确定执行模式
    executor_cfg = cfg.get("executor", {})
    if args.mode:
        executor_cfg["mode"] = args.mode
    mode = executor_cfg.get("mode", "backtest")

    # 创建执行器
    logger.info(f"[StrategyServer] Creating {mode} executor...")
    executor = create_executor(mode, cfg)
    
    # 确定输出目录
    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = Path(executor_cfg.get("output_dir", "./runtime"))
    
    # 确定Sink类型
    if args.sink:
        executor_cfg["sink"] = args.sink
        cfg["sink"] = {"kind": args.sink}
    
    # 确定信号源
    signals_source = args.signals_source
    
    if signals_source == "auto":
        # 自动检测：优先SQLite（支持 signals_v2.db），其次JSONL
        # TASK-A4: 优先查找 signals_v2.db（v2 格式），回退到 signals.db（v1 格式）
        # TASK-A4优化: JSONL 优先探测 v2 格式（hour粒度），然后兼容 v1 格式（minute粒度）
        db_path_v2 = output_dir / "signals_v2.db"
        db_path_v1 = output_dir / cfg.get("sink", {}).get("db_name", "signals.db")
        
        if args.signals_dir:
            jsonl_dir = Path(args.signals_dir)
        else:
            jsonl_dir = output_dir / "ready" / "signal"
        
        if db_path_v2.exists():
            signals_source = "sqlite"
            db_path = db_path_v2
            logger.info(f"[StrategyServer] Auto-detected SQLite v2: {db_path}")
        elif db_path_v1.exists():
            signals_source = "sqlite"
            db_path = db_path_v1
            logger.info(f"[StrategyServer] Auto-detected SQLite v1: {db_path}")
        elif jsonl_dir.exists():
            # TASK-A4优化: 优先探测 v2 格式（signals-*.jsonl），然后兼容 v1 格式（signals_*.jsonl）
            # 检查是否有 v2 格式文件（hour粒度）
            has_v2 = any(jsonl_dir.rglob("signals-*.jsonl"))
            has_v1 = any(jsonl_dir.rglob("signals_*.jsonl"))
            
            if has_v2:
                logger.info(f"[StrategyServer] Auto-detected JSONL v2 (hour granularity): {jsonl_dir}")
            elif has_v1:
                logger.info(f"[StrategyServer] Auto-detected JSONL v1 (minute granularity): {jsonl_dir}")
            
            signals_source = "jsonl"
        else:
            if args.watch:
                # Watch 模式：允许信号源暂时不存在，等待创建
                logger.warning(f"No signals source found, waiting in watch mode...")
                if not jsonl_dir.exists():
                    jsonl_dir.mkdir(parents=True, exist_ok=True)
                signals_source = "jsonl"
            else:
                logger.error("No signals source found")
                sys.exit(1)
    
    # Watch 模式：持续监听新信号
    if args.watch:
        logger.info(f"[StrategyServer] Watch mode enabled (check interval: {args.check_interval}s)")
        logger.info(f"[StrategyServer] Reading signals from {signals_source}...")
        
        running = True
        
        def stop_handler(signum=None, frame=None):
            """停止处理函数"""
            nonlocal running
            logger.info("[StrategyServer] Received stop signal, shutting down...")
            running = False
        
        # 注册信号处理
        try:
            if hasattr(signal_module, 'SIGTERM'):
                signal_module.signal(signal_module.SIGTERM, stop_handler)
            signal_module.signal(signal_module.SIGINT, stop_handler)
        except (AttributeError, ValueError):
            pass
        
        # 用于增量读取的状态
        processed_files: Set[str] = set()
        last_positions: Dict[str, int] = {}
        last_ts_ms: Optional[int] = None
        cumulative_stats = {
            "total_signals": 0,
            "confirmed_signals": 0,
            "gated_signals": 0,
            "orders_submitted": 0,
            "orders_filled": 0,
            "orders_rejected": 0,
        }
        
        logger.info("[StrategyServer] Strategy Server started and ready (watch mode)")

        # TASK-B1: 信号边界固化 - 心跳日志用于健康检查
        last_heartbeat = 0

        while running:
            try:
                # TASK-B1: 每分钟输出心跳日志，用于健康检查
                current_time = time.time()
                if current_time - last_heartbeat >= 60:  # 每60秒输出一次心跳
                    logger.info("[TASK-B1] HEARTBEAT: Strategy Server heartbeat - signals processed: "
                               f"total={cumulative_stats['total_signals']}, "
                               f"confirmed={cumulative_stats['confirmed_signals']}, "
                               f"gated={cumulative_stats['gated_signals']}, "
                               f"orders={cumulative_stats['orders_submitted']}")
                    last_heartbeat = current_time

                # 读取新信号
                if signals_source == "sqlite":
                    db_path = output_dir / "signals_v2.db"
                    if not db_path.exists():
                        db_path = output_dir / cfg.get("sink", {}).get("db_name", "signals.db")
                    
                    if db_path.exists():
                        signals = read_signals_from_sqlite(db_path, args.symbols, last_ts_ms)
                        signal_list = list(signals)
                        if signal_list:
                            # 更新 last_ts_ms
                            last_ts_ms = max(s.get("ts_ms", 0) for s in signal_list)
                            # 处理信号
                            stats = process_signals(executor, iter(signal_list), executor_cfg)
                            # 累计统计
                            for key in cumulative_stats:
                                cumulative_stats[key] += stats.get(key, 0)
                else:
                    if args.signals_dir:
                        jsonl_dir = Path(args.signals_dir)
                    else:
                        jsonl_dir = output_dir / "ready" / "signal"
                    
                    if jsonl_dir.exists():
                        signals = read_signals_from_jsonl(jsonl_dir, args.symbols, processed_files, last_positions)
                        signal_list = list(signals)
                        if signal_list:
                            # 处理信号
                            stats = process_signals(executor, iter(signal_list), executor_cfg)
                            # 累计统计
                            for key in cumulative_stats:
                                cumulative_stats[key] += stats.get(key, 0)
                
                # 等待下次检查
                time.sleep(args.check_interval)
            except KeyboardInterrupt:
                logger.info("[StrategyServer] Interrupted by user")
                running = False
            except Exception as e:
                logger.error(f"[StrategyServer] Error in watch loop: {e}", exc_info=True)
                time.sleep(args.check_interval)
        
        # 输出累计统计信息
        logger.info("[StrategyServer] Watch mode completed:")
        logger.info(f"  Total signals: {cumulative_stats['total_signals']}")
        logger.info(f"  Confirmed signals: {cumulative_stats['confirmed_signals']}")
        logger.info(f"  Gated signals: {cumulative_stats['gated_signals']}")
        logger.info(f"  Orders submitted: {cumulative_stats['orders_submitted']}")
        logger.info(f"  Orders filled: {cumulative_stats['orders_filled']}")
        logger.info(f"  Orders rejected: {cumulative_stats['orders_rejected']}")
    else:
        # 批处理模式：一次性处理所有信号
        logger.info(f"[StrategyServer] Reading signals from {signals_source}...")
        if signals_source == "sqlite":
            db_path = output_dir / "signals_v2.db"
            if not db_path.exists():
                db_path = output_dir / cfg.get("sink", {}).get("db_name", "signals.db")
            signals = read_signals_from_sqlite(db_path, args.symbols)
        else:
            if args.signals_dir:
                jsonl_dir = Path(args.signals_dir)
            else:
                jsonl_dir = output_dir / "ready" / "signal"
            signals = read_signals_from_jsonl(jsonl_dir, args.symbols)
        
        # 处理信号
        logger.info("[StrategyServer] Processing signals...")
        stats = process_signals(executor, signals, executor_cfg)
        
        # 输出统计信息
        logger.info("[StrategyServer] Execution completed:")
        logger.info(f"  Total signals: {stats['total_signals']}")
        logger.info(f"  Confirmed signals: {stats['confirmed_signals']}")
        logger.info(f"  Gated signals: {stats['gated_signals']}")
        logger.info(f"  Orders submitted: {stats['orders_submitted']}")
        logger.info(f"  Orders filled: {stats['orders_filled']}")
        logger.info(f"  Orders rejected: {stats['orders_rejected']}")
    
    # 关闭执行器
    executor.close()
    
    logger.info("[StrategyServer] Strategy Server stopped")


if __name__ == "__main__":
    main()

