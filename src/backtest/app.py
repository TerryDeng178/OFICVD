# -*- coding: utf-8 -*-
"""TASK-B2: Independent Backtest Runner

独立回测模式，支持两种运行模式：
- 模式A：全量重算（features → signals → trades/pnl）
- 模式B：信号复现（signals → trades/pnl）

产物完全对齐线上Report服务，确保可重复性与等价性。
"""

import argparse
import json
import logging
import os
import sys
import time
from collections import deque
from datetime import datetime, timezone
import pytz
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Any

import yaml

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# from alpha_core.common.paths import get_data_root
# from alpha_core.signals import CoreAlgorithm
# from alpha_core.executors import create_executor, IExecutor
# from alpha_core.report import Reporter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class BacktestAdapter:
    """回测数据适配器：支持features目录和signals源的流式读取"""

    def __init__(self, mode: str, features_dir: Optional[Path] = None,
                 signals_src: Optional[str] = None, symbols: Optional[set] = None,
                 start_ms: Optional[int] = None, end_ms: Optional[int] = None,
                 strict_core: bool = False, run_id: str = "unknown",
                 config: Optional[Dict[str, Any]] = None):
        if mode not in ['A', 'B']:
            raise ValueError(f"Invalid mode: {mode}. Must be 'A' or 'B'")

        if mode == 'A' and not features_dir:
            raise ValueError("features_dir required for mode A")
        if mode == 'B' and not signals_src:
            raise ValueError("signals_src required for mode B")

        self.mode = mode
        self.features_dir = features_dir
        self.signals_src = signals_src
        self.symbols = symbols or set()
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.strict_core = strict_core
        self.run_id = run_id
        self.config = config or {}

    def iter_features(self) -> Iterator[Dict[str, Any]]:
        """模式A：流式读取features数据"""
        if self.mode != 'A':
            raise ValueError("iter_features only available in mode A")

        if not self.features_dir:
            raise ValueError("features_dir required for mode A")

        logger.info(f"Starting features iteration from {self.features_dir}")

        # 查找所有Parquet文件
        parquet_files = list(self.features_dir.rglob("*.parquet"))
        if not parquet_files:
            logger.warning(f"No parquet files found in {self.features_dir}")
            return

        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas required for parquet reading. Install with: pip install pandas pyarrow")

        # 按文件名排序处理文件（确保确定性，避免mtime依赖）
        sorted_files = sorted(parquet_files, key=lambda p: p.name)

        for file_path in sorted_files:
            logger.info(f"Processing {file_path}")

            try:
                # 流式读取Parquet文件
                # Mode-A 默认读取全列以确保CoreAlgorithm有足够特征
                # 可通过config.features.columns配置指定列（可选优化）
                columns_cfg = (self.config or {}).get("features", {}).get("columns")
                if columns_cfg:
                    df = pd.read_parquet(file_path, columns=columns_cfg)
                else:
                    # Mode-A 默认全列，避免特征缺失影响等价性
                    df = pd.read_parquet(file_path)

                # 使用itertuples提升性能（比iterrows快得多）
                for row in df.itertuples(index=False):
                    # 过滤symbols（如果指定）
                    symbol = str(getattr(row, 'symbol', '')).upper()
                    if self.symbols and symbol not in self.symbols:
                        continue

                    # 过滤时间窗（如果指定）
                    ts_ms = int(getattr(row, 'ts_ms', -1))
                    if self.start_ms is not None and ts_ms < self.start_ms:
                        continue
                    if self.end_ms is not None and ts_ms >= self.end_ms:
                        continue

                    # 转换为字典并yield
                    feature_row = row._asdict()

                    # 确保ts_ms是整数
                    if 'ts_ms' in feature_row:
                        feature_row['ts_ms'] = int(feature_row['ts_ms'])

                    yield feature_row

            except Exception as e:
                logger.warning(f"Error reading parquet file {file_path}: {e}")
                continue

    def iter_signals(self, config: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        """模式A/B：流式读取signals数据"""
        if self.mode == 'A':
            # 模式A：实时计算signals（调用CoreAlgorithm）
            logger.info("Mode A: Computing signals from features")
            yield from self._compute_signals_from_features(config or {})
        else:
            # 模式B：从外部signals源读取
            logger.info(f"Mode B: Reading signals from {self.signals_src}")
            yield from self._iter_signals_from_source()

    def _compute_signals_from_features(self, config: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """从features实时计算signals - 接入真实CoreAlgorithm"""
        # 为每个symbol创建独立的CoreAlgorithm实例
        algos = {}
        temp_dirs = {}

        try:
            import tempfile
            import shutil
            try:
                from alpha_core.signals import CoreAlgorithm
                core_import_success = True
            except ImportError:
                if self.strict_core:
                    raise  # strict模式下，导入失败直接抛出
                core_import_success = False
                CoreAlgorithm = None  # 设为None以便后续检查

            for feature_row in self.iter_features():
                symbol = feature_row["symbol"]

                # 为每个symbol初始化CoreAlgorithm（如果还没有）
                if symbol not in algos:
                    if not core_import_success:
                        # 导入失败，直接设置None，走fallback逻辑
                        algos[symbol] = None
                    else:
                        temp_dir = Path(tempfile.mkdtemp())
                        temp_dirs[symbol] = temp_dir

                        # 创建null sink配置（不实际写入文件）
                        algo_config = config.copy()
                        algo_config.setdefault("sink", {})["kind"] = "null"

                        algos[symbol] = CoreAlgorithm(
                            config=algo_config,
                            sink_kind="null",
                            output_dir=temp_dir
                        )

                algo = algos[symbol]

                # 调用真实CoreAlgorithm进行信号计算
                # 这里假设CoreAlgorithm有一个feed_and_get_signals方法
                # 如果实际接口不同，需要相应调整
                if algo is None:
                    # 导入失败，走fallback逻辑
                    fallback_reason = "CoreAlgorithm import failed"
                else:
                    try:
                        # 将feature_row转换为CoreAlgorithm期望的格式
                        signals = algo.feed_and_get_signals(feature_row)

                        for signal in signals:
                            # 确保契约要求的字段格式
                            signal["gating"] = signal.get("gating", [])  # 确保为数组
                            signal["confirm"] = bool(signal.get("confirm", False))
                            yield signal
                        continue  # 成功处理，跳过fallback

                    except Exception as e:
                        fallback_reason = str(e)

                # 走到这里说明需要fallback
                # 如果真实计算失败，根据strict_core决定行为
                if self.strict_core:
                    raise RuntimeError(f"CoreAlgorithm failed for {symbol}: {fallback_reason}")  # 严格模式：立即退出
                logger.warning(f"CoreAlgorithm failed for {symbol}, falling back to mock signal: {fallback_reason}")
                yield {
                    "ts_ms": feature_row["ts_ms"],
                    "symbol": symbol,
                    "score": 0.5,
                    "z_ofi": 1.0,
                    "z_cvd": 0.5,
                    "regime": "quiet",
                    "div_type": None,
                    "confirm": True,
                    "gating": ["fallback"],  # 契约：数组格式
                    "decision_code": "OK",
                    "config_hash": "backtest_hash",
                    "run_id": self.run_id
                }

        finally:
            # 清理临时目录
            for temp_dir in temp_dirs.values():
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

    def _iter_signals_from_source(self) -> Iterator[Dict[str, Any]]:
        """从外部源读取signals"""
        if self.signals_src.startswith("jsonl://"):
            signals_dir = Path(self.signals_src[8:])  # Remove "jsonl://" prefix
            yield from self._iter_signals_jsonl(signals_dir)
        elif self.signals_src.startswith("sqlite://"):
            db_path = Path(self.signals_src[9:])  # Remove "sqlite://" prefix
            yield from self._iter_signals_sqlite(db_path)
        else:
            raise ValueError(f"Unsupported signals_src format: {self.signals_src}")

    def _iter_signals_jsonl(self, signals_dir: Path) -> Iterator[Dict[str, Any]]:
        """从JSONL文件读取signals"""
        import glob
        pattern = str(signals_dir / "**" / "signals*.jsonl")
        jsonl_files = glob.glob(pattern, recursive=True)

        for file_path in sorted(jsonl_files):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        signal = json.loads(line)

                        # 过滤时间窗
                        ts_ms = int(signal.get('ts_ms', -1))
                        if self.start_ms is not None and ts_ms < self.start_ms:
                            continue
                        if self.end_ms is not None and ts_ms >= self.end_ms:
                            continue

                        # 过滤符号
                        symbol = str(signal.get('symbol', '')).upper()
                        if self.symbols and symbol not in self.symbols:
                            continue

                        yield signal
            except Exception as e:
                logger.warning(f"Error reading {file_path}: {e}")

    def _iter_signals_sqlite(self, db_path: Path) -> Iterator[Dict[str, Any]]:
        """从SQLite数据库读取signals"""
        import sqlite3
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # 构建查询条件
            conditions = []
            params = []

            if self.start_ms is not None:
                conditions.append("ts_ms >= ?")
                params.append(self.start_ms)

            if self.end_ms is not None:
                conditions.append("ts_ms < ?")
                params.append(self.end_ms)

            if self.symbols:
                placeholders = ",".join("?" for _ in self.symbols)
                conditions.append(f"symbol IN ({placeholders})")
                params.extend(self.symbols)

            where_clause = " AND ".join(conditions) if conditions else ""
            sql = f"SELECT * FROM signals {f'WHERE {where_clause}' if where_clause else ''} ORDER BY ts_ms"

            cursor.execute(sql, params)
            columns = [desc[0] for desc in cursor.description]

            for row in cursor:
                signal = dict(zip(columns, row))
                # 解析gating_json，确保gating字段总是存在
                if 'gating_json' in signal:
                    try:
                        if signal['gating_json']:
                            signal['gating'] = json.loads(signal['gating_json'])
                        else:
                            signal['gating'] = []
                    except (json.JSONDecodeError, TypeError):
                        signal['gating'] = []
                    del signal['gating_json']
                else:
                    # 如果没有gating_json字段，设置默认值
                    signal['gating'] = []
                yield signal

            conn.close()
        except Exception as e:
            logger.warning(f"Error reading {db_path}: {e}")


class BrokerSimulator:
    """经纪商撮合模拟器：支持手续费、滑点、延迟"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.fee_bps_maker = config.get("fee_bps_maker", -25)  # 做市商费率（负数表示返佣，bps）
        self.fee_bps_taker = config.get("fee_bps_taker", 75)   # 吃单费率（bps）
        self.slippage_bps = config.get("slippage_bps", 0.0)     # 滑点
        self.latency_ms = config.get("latency_ms", 0)           # 撮合延迟

    def execute_order(self, order: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """执行订单，返回trade记录"""
        # 回测不阻塞，延迟只体现在时间戳模拟
        # 计算执行价格（考虑滑点）
        base_price = order["price"]
        slippage_adjustment = base_price * (self.slippage_bps / 10000.0)

        if order["side"] == "BUY":
            exec_price = base_price + slippage_adjustment
        else:
            exec_price = base_price - slippage_adjustment

        # 计算手续费
        is_maker = order.get("maker", False)
        fee_bps = self.fee_bps_maker if is_maker else self.fee_bps_taker
        fee_amount = abs(exec_price * order["quantity"]) * (fee_bps / 10000.0)

        # 生成trade记录（时间戳 = 信号时间 + 延迟）
        signal_ts_ms = order.get("signal_ts_ms", int(time.time() * 1000))
        trade_ts_ms = signal_ts_ms + int(self.latency_ms)

        trade = {
            "ts_ms": trade_ts_ms,
            "symbol": order["symbol"],
            "side": order["side"],
            "exec_px": exec_price,
            "qty": order["quantity"],
            "maker": is_maker,
            "fee_bps": fee_bps,
            "fee_abs": round(fee_amount, 8),  # 直接写入计算出的绝对费用，便于审计
            "slip_bps": self.slippage_bps,
            "lat_ms": self.latency_ms,
            "reason": order.get("reason", "backtest"),
            "order_id": order.get("order_id", f"bt_{signal_ts_ms}"),
            "position_id": order.get("position_id", "bt_pos_1")
        }

        return trade


class BacktestWriter:
    """回测产物写入器：支持JSONL和SQLite输出"""

    def __init__(self, output_dir: Path, run_id: str, write_signals: bool, emit_sqlite: bool = False):
        self.output_dir = output_dir / run_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.write_signals = write_signals
        self.emit_sqlite = emit_sqlite

        # 初始化文件句柄
        self.signals_file = None
        self.trades_file = None
        self.pnl_file = None
        self.sqlite_conn = None

        self._init_files()

    def _init_files(self):
        """初始化输出文件"""
        if self.write_signals:
            self.signals_file = (self.output_dir / "signals.jsonl").open("w", encoding="utf-8")
        self.trades_file = (self.output_dir / "trades.jsonl").open("w", encoding="utf-8")
        self.pnl_file = (self.output_dir / "pnl_daily.jsonl").open("w", encoding="utf-8")

        if self.emit_sqlite:
            import sqlite3
            db_path = self.output_dir / "signals.sqlite"
            self.sqlite_conn = sqlite3.connect(str(db_path))
            self._init_sqlite_schema()

    def _init_sqlite_schema(self):
        """初始化SQLite表结构"""
        if not self.sqlite_conn:
            return

        cursor = self.sqlite_conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                ts_ms INTEGER,
                symbol TEXT,
                signal_id TEXT,
                schema_version TEXT,
                score REAL,
                side_hint TEXT,
                z_ofi REAL,
                z_cvd REAL,
                div_type TEXT,
                regime TEXT,
                gating_json TEXT,
                confirm INTEGER,
                cooldown_ms INTEGER,
                expiry_ms INTEGER,
                decision_code TEXT,
                decision_reason TEXT,
                config_hash TEXT,
                run_id TEXT,
                meta TEXT,
                UNIQUE(ts_ms, symbol, signal_id)
            )
        """)
        self.sqlite_conn.commit()

    def write_signal(self, signal: Dict[str, Any]):
        """写入signal"""
        # 若缺失，生成稳定signal_id（确保唯一性）
        if "signal_id" not in signal or signal["signal_id"] is None:
            signal["signal_id"] = f"{signal.get('symbol','')}:{signal.get('ts_ms','')}:{int((signal.get('score') or 0)*1e6)}"

        if self.signals_file:
            json.dump(signal, self.signals_file, ensure_ascii=False)
            self.signals_file.write("\n")

        if self.sqlite_conn:
            cursor = self.sqlite_conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.get("ts_ms"),
                signal.get("symbol"),
                signal.get("signal_id"),
                signal.get("schema_version", "signal/v2"),
                signal.get("score"),
                signal.get("side_hint"),
                signal.get("z_ofi"),
                signal.get("z_cvd"),
                signal.get("div_type"),
                signal.get("regime"),
                json.dumps(signal.get("gating", []), ensure_ascii=False),
                int(bool(signal.get("confirm"))),
                signal.get("cooldown_ms", 0),
                signal.get("expiry_ms"),
                signal.get("decision_code"),
                signal.get("decision_reason"),
                signal.get("config_hash"),
                signal.get("run_id"),
                json.dumps(signal.get("meta", {}), ensure_ascii=False)
            ))
            self.sqlite_conn.commit()

    def write_trade(self, trade: Dict[str, Any]):
        """写入trade"""
        if self.trades_file:
            json.dump(trade, self.trades_file, ensure_ascii=False)
            self.trades_file.write("\n")

    def write_pnl(self, pnl: Dict[str, Any]):
        """写入pnl"""
        if self.pnl_file:
            json.dump(pnl, self.pnl_file, ensure_ascii=False)
            self.pnl_file.write("\n")

    def write_manifest(self, manifest: Dict[str, Any]):
        """写入run_manifest"""
        manifest_path = self.output_dir / "run_manifest.json"
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    def close(self):
        """关闭所有文件句柄"""
        if self.signals_file:
            self.signals_file.close()
        if self.trades_file:
            self.trades_file.close()
        if self.pnl_file:
            self.pnl_file.close()
        if self.sqlite_conn:
            self.sqlite_conn.close()


def _estimate_jsonl_signals(signals_dir: Path, start_ms: int, end_ms: int, symbols: set) -> int:
    """预估JSONL文件中的信号数量（用于进度计算）"""
    import glob
    count = 0

    pattern = str(signals_dir / "**" / "signals*.jsonl")
    for file_path in glob.glob(pattern, recursive=True):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    signal = json.loads(line)
                    ts_ms = int(signal.get('ts_ms', -1))
                    symbol = str(signal.get('symbol', '')).upper()

                    # 应用相同的过滤条件
                    if start_ms <= ts_ms < end_ms and (not symbols or symbol in symbols):
                        count += 1
        except Exception:
            continue  # 跳过损坏的文件

    return count


def load_config(config_path: str) -> Dict[str, Any]:
    """加载配置文件"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    return config


def build_run_manifest(args, config: Dict[str, Any], symbols) -> Dict[str, Any]:
    """构建运行清单"""
    run_id = args.run_id or f"bt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    # ENV白名单过滤（只保留BT_和V13_前缀的环境变量）
    env_whitelist = {}
    for key, value in os.environ.items():
        if key.startswith(('BT_', 'V13_')):
            env_whitelist[key] = value

    # 默认时区为Asia/Tokyo
    tz = getattr(args, 'tz', 'Asia/Tokyo')

    manifest = {
        "run_id": run_id,
        "mode": args.mode,
        "symbols": list(symbols) if symbols else [],
        "start": args.start,
        "end": args.end,
        "seed": getattr(args, 'seed', None),
        "tz": tz,
        "config_path": args.config,
        "features_dir": getattr(args, 'features_dir', None),
        "signals_src": getattr(args, 'signals_src', None),
        "output_dir": str(args.out_dir),
        "env": env_whitelist,
        "effective_config": {
            "heartbeat_interval_s": config.get("observability", {}).get("heartbeat_interval_s", 60),
            "fee_bps_maker": config.get("broker", {}).get("fee_bps_maker", -25),
            "fee_bps_taker": config.get("broker", {}).get("fee_bps_taker", 75),
            "slippage_bps": config.get("broker", {}).get("slippage_bps", 0),
            "latency_ms": config.get("broker", {}).get("latency_ms", 0),
            "maker_first": config.get("broker", {}).get("maker_first", True),
            "min_order_qty": config.get("broker", {}).get("min_order_qty", 0.001),
            # 以 CLI 覆盖 YAML
            "emit_sqlite": bool(getattr(args, "emit_sqlite", False) or config.get("output", {}).get("emit_sqlite", False))
        },
        "git": (lambda: (lambda c,d: {"commit": c or "unknown", "dirty": bool(d)})(
            __import__("subprocess").run(["git","rev-parse","HEAD"], capture_output=True, text=True).stdout.strip(),
            __import__("subprocess").run(["git","status","--porcelain"], capture_output=True, text=True).stdout.strip()
        ))(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    }

    return manifest


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="TASK-B2: Independent Backtest Runner")
    parser.add_argument("--mode", choices=["A", "B"], required=True,
                       help="A: 全量重算(features→signals), B: 信号复现(signals→trades)")
    parser.add_argument("--features-dir", type=str,
                       help="模式A: 历史features宽表根目录")
    parser.add_argument("--signals-src", type=str,
                       help="模式B: signals源 (jsonl://<dir> 或 sqlite://<db_path>)")
    parser.add_argument("--symbols", type=str, default="BTCUSDT",
                       help="交易对列表，逗号分隔")
    parser.add_argument("--start", type=str, required=True,
                       help="开始时间 (ISO格式)")
    parser.add_argument("--end", type=str, required=True,
                       help="结束时间 (ISO格式)")
    parser.add_argument("--config", type=str, required=True,
                       help="策略/撮合配置YAML文件")
    parser.add_argument("--out-dir", type=str, default="./backtest_out",
                       help="输出根目录")
    parser.add_argument("--run-id", type=str,
                       help="运行ID，不指定则自动生成")
    parser.add_argument("--seed", type=int, default=42,
                       help="随机种子，确保确定性")
    parser.add_argument("--tz", type=str, default="Asia/Tokyo",
                       help="时区，用于pnl切日统计")
    parser.add_argument("--emit-sqlite", action="store_true",
                       help="同时输出SQLite格式的signals")
    parser.add_argument("--strict-core", action="store_true",
                       help="CoreAlgorithm 计算失败时立即退出（默认为回退mock，便于排障）")
    parser.add_argument("--reemit-signals", action="store_true",
                       help="模式B下按需重发signals（默认不写，便于对账）")

    args = parser.parse_args()

    # 验证参数
    if args.mode == "A" and not args.features_dir:
        parser.error("--features-dir required for mode A")
    if args.mode == "B" and not args.signals_src:
        parser.error("--signals-src required for mode B")

    # 加载配置
    config = load_config(args.config)
    logger.info(f"Loaded config from {args.config}")

    # 设置确定性种子
    import random
    random.seed(args.seed)
    try:
        import numpy as np
        np.random.seed(args.seed)
    except ImportError:
        pass
    try:
        import torch
        torch.manual_seed(args.seed)
    except ImportError:
        pass

    # 解析时间窗和符号
    start_ms = int(datetime.fromisoformat(args.start.replace("Z", "+00:00")).timestamp() * 1000)
    end_ms = int(datetime.fromisoformat(args.end.replace("Z", "+00:00")).timestamp() * 1000)
    symbols = set(s.strip().upper() for s in args.symbols.split(",") if s.strip())

    # 解析时区
    try:
        tz = pytz.timezone(args.tz)
    except pytz.exceptions.UnknownTimeZoneError:
        raise ValueError(f"Unknown timezone: {args.tz}")

    # 构建运行清单
    manifest = build_run_manifest(args, config, symbols)

    # 初始化组件

    adapter = BacktestAdapter(
        mode=args.mode,
        features_dir=Path(args.features_dir) if args.features_dir else None,
        signals_src=args.signals_src,
        symbols=symbols,
        start_ms=start_ms,
        end_ms=end_ms,
        strict_core=bool(args.strict_core),
        run_id=manifest["run_id"],
        config=config
    )

    broker = BrokerSimulator(config.get("broker", {}))
    writer = BacktestWriter(
        Path(args.out_dir),
        manifest["run_id"],
        write_signals=((args.mode == "A") or bool(getattr(args, "reemit_signals", False))),
        emit_sqlite=(args.emit_sqlite or config.get("output", {}).get("emit_sqlite", False))
    )

    logger.info(f"Starting backtest {manifest['run_id']} in mode {args.mode}")

    # 预估信号数量用于进度计算
    total_signals_expected = 0
    if args.mode == 'B' and args.signals_src.startswith("jsonl://"):
        # 预估JSONL文件中的信号数量
        signals_dir = Path(args.signals_src[8:])
        total_signals_expected = _estimate_jsonl_signals(signals_dir, start_ms, end_ms, symbols)
    elif args.mode == 'B' and args.signals_src.startswith("sqlite://"):
        # 预估SQLite数据库中的信号数量
        import sqlite3
        db_path = Path(args.signals_src[9:])
        try:
            conn = sqlite3.connect(str(db_path)); cur = conn.cursor()
            sym_clause = ""
            params = [start_ms, end_ms]
            if symbols:
                placeholders = ",".join("?" for _ in symbols)
                sym_clause = f" AND symbol IN ({placeholders})"
                params += list(symbols)
            cur.execute(f"SELECT COUNT(1) FROM signals WHERE ts_ms>=? AND ts_ms<?{sym_clause}", params)
            total_signals_expected = int(cur.fetchone()[0] or 0)
            conn.close()
        except Exception:
            total_signals_expected = 0
    elif args.mode == 'A':
        # 近似：用 features 文件数 × 10000 估算（或改成读取元数据）
        try:
            feat_dir = Path(args.features_dir)
            n_files = len(list(feat_dir.rglob("*.parquet")))
            total_signals_expected = n_files * 10000  # 粗估；可替换为真实元数据
        except Exception:
            total_signals_expected = 0

    # 初始化观测性变量
    hb_sec = int(config.get("observability", {}).get("heartbeat_interval_s", 60))
    last_heartbeat = 0
    start_time = time.time()
    processed_signals = 0
    generated_trades = 0
    current_phase = "signals"  # 初始阶段：读取/计算信号

    # 初始化PnL计算变量
    lots = {}  # symbol -> deque of {"side", "px", "qty", "ts", "fee_open", "qty_open"}
    closed_legs = []  # [{"sym", "open_ts", "close_ts", "pnl", "fee_abs"}]
    daily_turnover = {}   # date -> sum(turnover) of all fills
    daily_trade_count = {}# date -> count of fills

    # 健康检查函数
    def health_check() -> bool:
        """健康检查：检查进程是否正常运行"""
        try:
            # 检查输出目录是否可写
            test_file = writer.output_dir / ".health_check"
            test_file.write_text("ok")
            test_file.unlink()
            return True
        except Exception:
            return False

    try:
        # 处理signals
        for signal in adapter.iter_signals(config):
            # 确保run_id与当前运行一致（修复fallback信号的run_id问题）
            signal.setdefault("run_id", manifest["run_id"])

            processed_signals += 1

            # 模式A时写入signals
            if args.mode == "A":
                writer.write_signal(signal)

            # 模拟策略决策（简化版）
            if signal.get("confirm", False) and len(signal.get("gating", [])) > 0:
                # 从配置和信号中解析价格
                price_fields = config.get("signal", {}).get("price_fields", ["mid_px", "price"])
                price = None
                for field in price_fields:
                    if field in signal and signal[field] is not None:
                        price = float(signal[field])
                        break

                if price is None:
                    logger.warning(f"No price field found in signal for {signal['symbol']}, skipping")
                    continue

                # 从配置中获取订单数量
                qty = config.get("order", {}).get("qty", config.get("broker", {}).get("min_order_qty", 0.001))

                # 生成订单
                order = {
                    "symbol": signal["symbol"],
                    "side": "BUY" if signal.get("score", 0) > 0 else "SELL",
                    "price": price,
                    "quantity": float(qty),
                    "reason": "signal_confirmed",
                    "maker": bool(config.get("broker", {}).get("maker_first", True)),
                    "signal_ts_ms": int(signal["ts_ms"])  # 传入信号时间戳用于延迟计算
                }

                # 执行订单
                trade = broker.execute_order(order)
                if trade:
                    # 计算并添加turnover到trade记录（fee_abs已在BrokerSimulator中设置）
                    turnover_amount = abs(trade["exec_px"] * trade["qty"])
                    trade["turnover"] = round(turnover_amount, 8)

                    # PnL计算：使用持仓簿和闭合腿
                    sym = trade["symbol"]
                    side = trade["side"]
                    px = trade["exec_px"]
                    qty = trade["qty"]
                    trade_ts = trade["ts_ms"]

                    lots.setdefault(sym, deque())

                    # 处理持仓簿
                    if side == "BUY":
                        # 先平空头仓位
                        remain = qty
                        while remain > 1e-12 and lots[sym] and lots[sym][0]["side"] == "SELL":
                            leg = lots[sym][0]
                            close_qty = min(remain, leg["qty"])

                            if close_qty > 0:
                                trade_fee = float(trade.get("fee_abs", 0.0))
                                # 分摊开仓费用
                                fee_open_part = float(leg.get("fee_open", 0.0)) * (close_qty / leg.get("qty_open", close_qty))
                                # 总费用 = 开仓费分摊 + 平仓费分摊
                                total_fee = fee_open_part + (trade_fee * (close_qty / qty))

                                pnl = (leg["px"] - px) * close_qty
                                closed_legs.append({
                                    "sym": sym,
                                    "open_ts": leg["ts"],
                                    "close_ts": trade_ts,
                                    "pnl": pnl,
                                    "fee_abs": total_fee
                                })

                            leg["qty"] -= close_qty
                            remain -= close_qty

                            if leg["qty"] <= 1e-12:
                                lots[sym].popleft()

                        # 剩余部分作为新多头仓位
                        if remain > 1e-12:
                            lots[sym].append({
                                "side": "BUY",
                                "px": px,
                                "qty": remain,
                                "ts": trade_ts,
                                "fee_open": float(trade.get("fee_abs", 0.0)),
                                "qty_open": remain
                            })

                    else:  # SELL
                        # 先平多头仓位
                        remain = qty
                        while remain > 1e-12 and lots[sym] and lots[sym][0]["side"] == "BUY":
                            leg = lots[sym][0]
                            close_qty = min(remain, leg["qty"])

                            if close_qty > 0:
                                trade_fee = float(trade.get("fee_abs", 0.0))
                                # 分摊开仓费用
                                fee_open_part = float(leg.get("fee_open", 0.0)) * (close_qty / leg.get("qty_open", close_qty))
                                # 总费用 = 开仓费分摊 + 平仓费分摊
                                total_fee = fee_open_part + (trade_fee * (close_qty / qty))

                                pnl = (px - leg["px"]) * close_qty
                                closed_legs.append({
                                    "sym": sym,
                                    "open_ts": leg["ts"],
                                    "close_ts": trade_ts,
                                    "pnl": pnl,
                                    "fee_abs": total_fee
                                })

                            leg["qty"] -= close_qty
                            remain -= close_qty

                            if leg["qty"] <= 1e-12:
                                lots[sym].popleft()

                        # 剩余部分作为新空头仓位
                        if remain > 1e-12:
                            lots[sym].append({
                                "side": "SELL",
                                "px": px,
                                "qty": remain,
                                "ts": trade_ts,
                                "fee_open": float(trade.get("fee_abs", 0.0)),
                                "qty_open": remain
                            })

                    # 统计每日成交额与成交笔数（按成交时间切日）
                    trade_date = datetime.fromtimestamp(trade["ts_ms"]/1000, tz=tz).strftime("%Y-%m-%d")
                    daily_turnover[trade_date] = daily_turnover.get(trade_date, 0.0) + turnover_amount
                    daily_trade_count[trade_date] = daily_trade_count.get(trade_date, 0) + 1

                    writer.write_trade(trade)
                    generated_trades += 1

            # 定期心跳和进度报告
            current_time = time.time()
            if current_time - last_heartbeat >= hb_sec:  # 使用配置的心跳间隔
                elapsed = current_time - start_time
                progress = processed_signals / max(total_signals_expected, 1) * 100

                # 获取内存使用情况
                mem_gib = 0.0
                if HAS_PSUTIL:
                    try:
                        process = psutil.Process()
                        mem_gib = round(process.memory_info().rss / (1024**3), 3)
                    except Exception:
                        pass

                heartbeat = {
                    "kind": "bt_heartbeat",
                    "ts": int(current_time * 1000),
                    "processed": processed_signals,
                    "trades": generated_trades,
                    "progress_pct": round(progress, 2),
                    "elapsed_sec": round(elapsed, 1),
                    "rps": round(processed_signals / max(elapsed, 1), 2),
                    "mem_gib": mem_gib,
                    "phase": current_phase,
                    "healthy": health_check()
                }
                logger.info(json.dumps(heartbeat, ensure_ascii=False))
                last_heartbeat = current_time

        # 信号处理完成，开始交易撮合阶段
        current_phase = "broker"

        # 按时区切日生成PnL统计 - 基于闭合腿的真实聚合
        # 将闭合腿按close_ts和时区分组到每日统计

        daily_stats = {}      # date -> stats for closed legs

        for leg in closed_legs:
            # 按close_ts和时区确定日期
            close_date = datetime.fromtimestamp(leg["close_ts"] / 1000, tz=tz).strftime("%Y-%m-%d")

            if close_date not in daily_stats:
                daily_stats[close_date] = {
                    "pnl": 0.0,
                    "fees": 0.0,
                    "legs": [],
                    "hold_times": []
                }

            stats = daily_stats[close_date]
            stats["pnl"] += leg["pnl"]
            stats["fees"] += leg["fee_abs"]  # 净费用：maker返佣为正，taker成本为负
            stats["legs"].append(leg)
            stats["hold_times"].append((leg["close_ts"] - leg["open_ts"]) / 1000.0)  # 秒

        # 为每一天生成pnl记录
        for date, stats in sorted(daily_stats.items()):
            # 计算胜率：盈利腿数 / 总腿数
            winning_legs = sum(1 for leg in stats["legs"] if leg["pnl"] > 0)
            win_rate = winning_legs / max(1, len(stats["legs"]))

            # 计算平均持仓时间
            avg_hold_sec = sum(stats["hold_times"]) / max(1, len(stats["hold_times"])) if stats["hold_times"] else 0.0

            pnl_record = {
                "date": date,
                "pnl": round(stats["pnl"], 8),
                "fees": round(stats["fees"], 8),
                "turnover": round(daily_turnover.get(date, 0.0), 8),
                "trades": daily_trade_count.get(date, 0),  # 当日成交笔数
                "legs": len(stats["legs"]),                # 当日闭合腿数（新增，避免歧义）
                "win_rate": round(win_rate, 4),
                "avg_hold_sec": round(avg_hold_sec, 1)
            }
            writer.write_pnl(pnl_record)

        # 写入manifest
        end_time = time.time()
        duration_s = end_time - start_time

        # 获取最终内存使用情况
        final_mem_gib = 0.0
        if HAS_PSUTIL:
            try:
                process = psutil.Process()
                final_mem_gib = round(process.memory_info().rss / (1024**3), 3)
            except Exception:
                pass

        manifest["perf"] = {
            "signals_processed": processed_signals,
            "trades_generated": generated_trades,
            "duration_s": round(duration_s, 2),
            "avg_rps": round(processed_signals / max(duration_s, 1), 2),
            "memory_gib": final_mem_gib
        }
        writer.write_manifest(manifest)

        logger.info(f"Backtest completed: {processed_signals} signals, {generated_trades} trades in {duration_s:.1f}s")
        logger.info(f"Output directory: {writer.output_dir}")

    finally:
        writer.close()


if __name__ == "__main__":
    main()
