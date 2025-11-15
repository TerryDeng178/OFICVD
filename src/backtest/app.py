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
import math
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


# 导入策略层组件
from alpha_core.strategy.policy import (
    SOFT_GATING,
    HARD_ALWAYS_BLOCK,
    is_tradeable,
    StrategyEmulator,
)



def resolve_features_price_dir(cli_features_price_dir: Optional[str] = None,
                               config: Optional[Dict[str, Any]] = None) -> Path:
    """解析features价格目录，按优先级：CLI > ENV > config > 默认值

    Args:
        cli_features_price_dir: CLI参数--features-price-dir的值
        config: 加载的YAML配置字典

    Returns:
        最终解析的价格数据根目录路径
    """
    # 优先级1: CLI参数最高优先级
    if cli_features_price_dir:
        resolved_path = Path(cli_features_price_dir)
        logger.info(f"Using features-price-dir from CLI: {resolved_path}")
        return resolved_path

    # 优先级2: 环境变量
    env_dir = os.getenv("BT_FEATURES_PRICE_DIR")
    if env_dir:
        resolved_path = Path(env_dir)
        logger.info(f"Using features-price-dir from ENV BT_FEATURES_PRICE_DIR: {resolved_path}")
        return resolved_path

    # 优先级3: 配置文件
    if config:
        config_dir = config.get("data", {}).get("features_price_dir")
        if config_dir:
            resolved_path = Path(config_dir)
            logger.info(f"Using features-price-dir from config: {resolved_path}")
            return resolved_path

    # 默认值兜底
    default_path = Path("deploy/data/ofi_cvd")
    logger.info(f"Using default features-price-dir: {default_path}")
    return default_path



class PriceCache:
    """价格缓存：支持preview/ready双格式自动探测及窗口加载"""

    def __init__(self, root_dir: Path, symbols: set, start_ms: Optional[int] = None,
                 end_ms: Optional[int] = None, config: Optional[Dict[str, Any]] = None):
        """初始化价格缓存

        Args:
            root_dir: 价格数据根目录 (features_price_dir)
            symbols: 需要加载价格的交易对集合
            start_ms: 时间窗口开始时间戳(毫秒)
            end_ms: 时间窗口结束时间戳(毫秒)
            config: 配置字典，用于读取price.fields等配置
        """
        self.root_dir = root_dir
        self.symbols = symbols
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.config = config or {}

        # 价格缓存: symbol -> sorted list of (ts_ms, price)
        self._cache = {}
        self._loaded = False

        # 质量检查标志
        self._failure = False
        self._error_msg = None

        # 配置：价格字段优先级
        self.price_fields = self.config.get("price", {}).get("fields", ["mid_px", "price"])

    def load(self) -> Dict[str, Any]:
        """加载价格缓存，返回质量报告"""
        if self._loaded:
            return self._get_quality_report()

        logger.info("Loading price cache...")

        try:
            # 自动探测格式：preview优先
            if (self.root_dir / "preview").exists():
                self._load_preview_format()
            elif (self.root_dir / "ready").exists():
                self._load_ready_format()
            else:
                self._failure = True
                self._error_msg = f"Neither preview nor ready format found in {self.root_dir}"
                logger.warning(self._error_msg)

            self._loaded = True

            # fail-fast检查
            total_points = sum(len(prices) for prices in self._cache.values())
            if total_points == 0:
                self._failure = True
                self._error_msg = "CRITICAL: No price data loaded for any symbol. This will result in unrealistic default prices being used for all trades."
                logger.error(self._error_msg)

            return self._get_quality_report()

        except Exception as e:
            self._failure = True
            self._error_msg = f"Failed to load price cache: {e}"
            logger.error(self._error_msg)
            return self._get_quality_report()

    def lookup(self, symbol: str, ts_ms: int) -> Optional[float]:
        """查找指定时间点的价格（使用二分查找）"""
        symbol_prices = self._cache.get(symbol.upper())
        if not symbol_prices:
            return None

        # 二分查找最接近的时间点
        from bisect import bisect_left
        idx = bisect_left(symbol_prices, (ts_ms,), key=lambda x: x[0])

        if idx == 0:
            # 第一个点之前，返回None或第一个点
            return symbol_prices[0][1] if symbol_prices else None
        elif idx >= len(symbol_prices):
            # 最后一个点之后，返回最后一个点
            return symbol_prices[-1][1]
        else:
            # 在两个点之间，选择更接近的一个
            prev_ts, prev_price = symbol_prices[idx - 1]
            curr_ts, curr_price = symbol_prices[idx]

            if abs(ts_ms - prev_ts) <= abs(ts_ms - curr_ts):
                return prev_price
            else:
                return curr_price

    def _get_quality_report(self) -> Dict[str, Any]:
        """生成质量报告"""
        total_points = sum(len(prices) for prices in self._cache.values())

        return {
            "price_cache_loaded": total_points,
            "price_cache_failure": self._failure,
            "price_cache_error": self._error_msg,
            "price_points_total": total_points,
            "symbols_loaded": list(self._cache.keys())
        }

    def _load_ready_format(self):
        """加载ready格式价格数据"""
        features_base = self.root_dir / "ready" / "features"
        logger.info(f"Loading ready format from {features_base}")

        for symbol in self.symbols:
            symbol_cache = []
            symbol_dir = features_base / symbol.upper()

            if not symbol_dir.exists():
                logger.warning(f"Features directory not found for {symbol}: {symbol_dir}")
                continue

            # 读取该symbol的所有features文件
            import glob
            pattern = str(symbol_dir / "features*.jsonl")
            feature_files = glob.glob(pattern)

            for file_path in sorted(feature_files):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue

                            feature = json.loads(line)
                            ts_ms = int(feature.get('ts_ms', 0))

                            # 按优先级查找价格字段
                            price = None
                            for field in self.price_fields:
                                if field in feature and feature[field]:
                                    price = float(feature[field])
                                    break

                            if ts_ms > 0 and price and price > 0:
                                # 时间窗口过滤
                                if (self.start_ms is None or ts_ms >= self.start_ms) and \
                                   (self.end_ms is None or ts_ms < self.end_ms):
                                    symbol_cache.append((ts_ms, price))

                except Exception as e:
                    logger.warning(f"Error reading features file {file_path}: {e}")

            # 排序并存储
            if symbol_cache:
                symbol_cache.sort(key=lambda x: x[0])
                self._cache[symbol.upper()] = symbol_cache
                logger.info(f"Loaded {len(symbol_cache)} price points from ready format for {symbol}")

    def _load_preview_format(self):
        """加载preview格式价格数据"""
        logger.info(f"Loading preview format from {self.root_dir}")
        try:
            import pyarrow.parquet as pq
        except ImportError:
            logger.error("pyarrow not available for preview format")
            return

        for symbol in self.symbols:
            symbol_cache = []
            symbol_lower = symbol.lower()

            # 遍历所有日期目录
            preview_dir = self.root_dir / "preview"
            if not preview_dir.exists():
                continue

            date_dirs = list(preview_dir.glob("date=*"))
            for date_dir in sorted(date_dirs):
                if not date_dir.is_dir():
                    continue

                # 遍历所有小时目录
                for hour_dir in sorted(date_dir.glob("hour=*")):
                    if not hour_dir.is_dir():
                        continue

                    # 查找对应的symbol目录
                    symbol_dir = hour_dir / f"symbol={symbol_lower}"
                    if not symbol_dir.exists():
                        continue

                    # 查找features目录
                    features_dir = symbol_dir / "kind=features"
                    if not features_dir.exists():
                        continue

                    # 读取该目录下的所有parquet文件
                    parquet_files = list(features_dir.glob("*.parquet"))
                    for parquet_file in sorted(parquet_files):
                        try:
                            # 读取parquet文件（跳过schema不一致的文件）
                            try:
                                table = pq.read_table(parquet_file)
                                df = table.to_pandas()
                            except Exception as schema_error:
                                logger.warning(f"Skipping {parquet_file.name}: schema error - {schema_error}")
                                continue

                            # 检查必要的列是否存在
                            if 'ts_ms' not in df.columns:
                                logger.warning(f"Skipping {parquet_file.name}: missing ts_ms column")
                                continue

                            # 检查是否有价格列
                            price_col = None
                            for field in self.price_fields:
                                if field in df.columns:
                                    price_col = field
                                    break

                            if not price_col:
                                logger.warning(f"Skipping {parquet_file.name}: no price columns found in {self.price_fields}")
                                continue

                            # 时间和价格过滤
                            mask = (
                                (df['ts_ms'] > 0) &
                                (df[price_col].notna()) &
                                (df[price_col] > 0)
                            )

                            # 时间窗口过滤
                            if self.start_ms is not None:
                                mask &= (df['ts_ms'] >= self.start_ms)
                            if self.end_ms is not None:
                                mask &= (df['ts_ms'] < self.end_ms)

                            filtered_df = df[mask]
                            if len(filtered_df) > 0:
                                for _, row in filtered_df.iterrows():
                                    symbol_cache.append((int(row['ts_ms']), float(row[price_col])))

                        except Exception as e:
                            logger.warning(f"Error reading parquet file {parquet_file}: {e}")

            # 排序并存储
            if symbol_cache:
                symbol_cache.sort(key=lambda x: x[0])
                self._cache[symbol.upper()] = symbol_cache
                logger.info(f"Loaded {len(symbol_cache)} price points from preview format for {symbol}")


class BacktestAdapter:
    """回测数据适配器：支持features目录和signals源的流式读取"""

    def __init__(self, mode: str, features_dir: Optional[Path] = None,
                 signals_src: Optional[str] = None, symbols: Optional[set] = None,
                 start_ms: Optional[int] = None, end_ms: Optional[int] = None,
                 strict_core: bool = False, run_id: str = "unknown",
                 config: Optional[Dict[str, Any]] = None,
                 cli_features_price_dir: Optional[str] = None,
                 consistency_qa_mode: bool = False):
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

        # 价格缓存：使用新的PriceCache类
        self._price_cache = None  # PriceCache实例
        self._price_cache_loaded = False
        # 价格缓存质量检查标志
        self._price_cache_failure = False
        self._price_cache_error_msg = None
        self._cli_features_price_dir = cli_features_price_dir  # CLI价格目录参数
        self.run_id = run_id
        self.config = config or {}
        self.consistency_qa_mode = consistency_qa_mode

        # CoreAlgorithm实例缓存（按symbol）
        self._algos = {}

    def close(self):
        """关闭所有CoreAlgorithm实例"""
        for symbol, algo in self._algos.items():
            if algo is not None:
                try:
                    algo.close()
                    logger.debug(f"Closed CoreAlgorithm for {symbol}")
                except Exception as e:
                    logger.warning(f"Error closing CoreAlgorithm for {symbol}: {e}")
        self._algos.clear()

    def _load_price_cache(self):
        """加载价格缓存：使用PriceCache类"""
        if self._price_cache_loaded or self.mode != 'B':
            return

        logger.info("Loading price cache...")

        try:
            # 获取features价格目录（通过resolve_features_price_dir处理优先级）
            price_dir = resolve_features_price_dir(
                cli_features_price_dir=self._cli_features_price_dir,
                config=self.config
            )

            # 初始化PriceCache
            self._price_cache = PriceCache(
                root_dir=price_dir,
                symbols=self.symbols,
                start_ms=self.start_ms,
                end_ms=self.end_ms,
                config=self.config
            )

            # 加载价格数据并获取质量报告
            quality_report = self._price_cache.load()

            self._price_cache_loaded = True
            self._price_cache_failure = quality_report.get("price_cache_failure", False)
            self._price_cache_error_msg = quality_report.get("price_cache_error")

            logger.info(f"Price cache loaded: {quality_report.get('price_points_total', 0)} points for {len(quality_report.get('symbols_loaded', []))} symbols")

        except Exception as e:
            logger.error(f"Failed to load price cache: {e}")
            self._price_cache_failure = True
            self._price_cache_error_msg = str(e)


    def get_price_at_time(self, symbol: str, ts_ms: int) -> Optional[float]:
        """在指定时间点获取最接近的价格"""
        if not self._price_cache_loaded:
            self._load_price_cache()

        if self._price_cache is None:
            return None

        return self._price_cache.lookup(symbol, ts_ms)

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

            processed_rows = 0
            # 添加全局统计计数器
            total_no_signal_rows = 0
            total_fallback_import = 0
            total_fallback_exception = 0
            total_real_signals = 0

            # QA模式：收集真实信号用于一致性分布分析
            qa_signals = []
            gating_counts = {}  # gating原因计数
            confirm_true_count = 0  # confirm=True的信号数量
            passed_signals = 0  # 通过所有护栏的信号数量

            logger.info(f"[DEBUG] Starting to process features, core_import_success={core_import_success}")
            features_iter = self.iter_features()
            logger.info(f"[DEBUG] Created features iterator: {features_iter}")
            for feature_row in features_iter:
                symbol = feature_row["symbol"]
                processed_rows += 1
                if processed_rows % 1000 == 0:
                    logger.info(f"[DEBUG] Processed {processed_rows} rows")
                if processed_rows == 1:  # 只在第一行显示一次
                    logger.info(f"[DEBUG] First feature_row: symbol={symbol}, ts_ms={feature_row.get('ts_ms')}")
                    logger.info(f"[DEBUG] First feature_row keys: {list(feature_row.keys())}")
                    logger.info(f"[DEBUG] First feature_row z_ofi: {feature_row.get('z_ofi')}")
                    logger.info(f"[DEBUG] First feature_row z_cvd: {feature_row.get('z_cvd')}")
                    logger.info(f"[DEBUG] First feature_row fusion_score: {feature_row.get('fusion_score')}")

                # 为每个symbol初始化CoreAlgorithm（如果还没有）
                if symbol not in self._algos:
                    if not core_import_success:
                        # 导入失败，直接设置None，走fallback逻辑
                        self._algos[symbol] = None
                    else:
                        temp_dir = Path(tempfile.mkdtemp())
                        temp_dirs[symbol] = temp_dir

                        # 创建null sink配置（不实际写入文件）
                        algo_config = config.copy()
                        algo_config.setdefault("sink", {})["kind"] = "null"

                        self._algos[symbol] = CoreAlgorithm(
                            config=algo_config,
                            sink_kind="null",
                            output_dir=temp_dir
                        )

                algo = self._algos[symbol]

                # 调用真实CoreAlgorithm进行信号计算

                # 存储当前处理的行信息，用于异常日志
                current_row_info = {
                    "ts_ms": feature_row.get("ts_ms"),
                    "symbol": feature_row.get("symbol"),
                    "z_ofi": feature_row.get("z_ofi"),
                    "ofi_z": feature_row.get("ofi_z"),
                    "z_cvd": feature_row.get("z_cvd"),
                    "cvd_z": feature_row.get("cvd_z"),
                    "fusion_score": feature_row.get("fusion_score"),
                    "consistency": feature_row.get("consistency"),
                    "regime": feature_row.get("regime"),
                    "scenario_2x2": feature_row.get("scenario_2x2")
                }

                if algo is None:
                    # 导入失败，走fallback逻辑
                    fallback_reason = "CoreAlgorithm import failed"
                    total_fallback_import += 1
                else:
                    try:
                        # 调用CoreAlgorithm的process_feature_row方法
                        logger.debug(f"[DEBUG] Calling CoreAlgorithm.process_feature_row for {symbol}")
                        signal = algo.process_feature_row(feature_row)
                        logger.debug(f"[DEBUG] CoreAlgorithm returned: {signal is not None}")

                        if signal is None:
                            # ✅ 正常情况：这行feature没有产生信号，直接跳过
                            total_no_signal_rows += 1
                            continue

                        # ✅ 真正的信号路径：处理gating和价格注入
                        total_real_signals += 1

                        # 修复 gating 语义：使用 gating_blocked / decision_reason 来生成列表
                        gating_blocked = signal.get("gating_blocked", False)
                        reason = signal.get("decision_reason") or signal.get("gate_reason") or signal.get("guard_reason")

                        if gating_blocked:
                            if reason:
                                # 多个 reason 用逗号分隔，转为列表
                                signal["gating"] = [r.strip() for r in reason.split(",") if r.strip()]
                            else:
                                signal["gating"] = ["guarded"]
                        else:
                            signal["gating"] = []  # 通过护栏

                        signal["confirm"] = bool(signal.get("confirm", False))

                        # 从 feature_row 注入价格字段，供 Mode A 下单使用
                        for price_field in ("mid_px", "price", "mid"):
                            if price_field in feature_row and price_field not in signal:
                                signal[price_field] = feature_row[price_field]

                        # QA模式：收集信号用于一致性分布分析
                        qa_signals.append({
                            'score': signal.get('score'),
                            'consistency': signal.get('consistency', 0.0),  # TASK-CORE-CONFIRM: 从信号获取实际用于gating的consistency
                            'z_ofi': feature_row.get('z_ofi') or feature_row.get('ofi_z'),
                            'z_cvd': feature_row.get('z_cvd') or feature_row.get('cvd_z'),
                            'gating': signal.get('gating', []),
                            'confirm': signal.get('confirm', False)
                        })

                        # 收集gating统计
                        gating_list = signal.get('gating', [])
                        if gating_list:
                            for reason in gating_list:
                                gating_counts[reason] = gating_counts.get(reason, 0) + 1
                        else:
                            gating_counts['none'] = gating_counts.get('none', 0) + 1

                        # 统计confirm=True的信号
                        if signal.get('confirm', False):
                            confirm_true_count += 1

                        logger.debug(f"[DEBUG] Signal score: {signal.get('score')}, confirm: {signal.get('confirm')}, gating: {signal.get('gating')}")
                        logger.debug(f"[DEBUG] Yielding real signal for {symbol}: confirm={signal.get('confirm')}, gating={signal.get('gating')}")
                        yield signal
                        continue  # 成功处理，跳过fallback

                    except Exception as e:
                        fallback_reason = f"CoreAlgorithm exception: {e}"
                        total_fallback_exception += 1

                        # 只对前20个异常打详细日志，避免日志爆炸
                        if total_fallback_exception <= 20:
                            logger.exception(
                                "[BACKTEST] CoreAlgorithm exception #%d on row: ts_ms=%s symbol=%s raw_data=%s",
                                total_fallback_exception,
                                current_row_info.get("ts_ms"),
                                current_row_info.get("symbol"),
                                current_row_info
                            )

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

            # 输出处理统计信息
            logger.info(
                f"[SUMMARY] Processed {processed_rows} feature rows: "
                f"no_signal_rows={total_no_signal_rows}, "
                f"real_signals={total_real_signals}, "
                f"fallback_import={total_fallback_import}, "
                f"fallback_exception={total_fallback_exception}"
            )

            # 如果启用了QA模式，做一致性分布统计
            if getattr(self, 'consistency_qa_mode', False):
                consistency_buckets = {
                    '< 0.00': 0,
                    '[0.00, 0.05)': 0,
                    '[0.05, 0.10)': 0,
                    '[0.10, 0.15)': 0,
                    '[0.15, 0.20)': 0,
                    '>= 0.20': 0
                }
                weak_signal_count = 0
                low_consistency_count = 0
                passed_signals = 0

                for signal in qa_signals:
                    # 一致性分布统计
                    consistency = signal.get('consistency')
                    if consistency is not None:
                        if consistency < 0.0:
                            consistency_buckets['< 0.00'] += 1
                        elif consistency < 0.05:
                            consistency_buckets['[0.00, 0.05)'] += 1
                        elif consistency < 0.10:
                            consistency_buckets['[0.05, 0.10)'] += 1
                        elif consistency < 0.15:
                            consistency_buckets['[0.10, 0.15)'] += 1
                        elif consistency < 0.20:
                            consistency_buckets['[0.15, 0.20)'] += 1
                        else:
                            consistency_buckets['>= 0.20'] += 1

                    # 弱信号和低一致性统计
                    gating = signal.get('gating', [])
                    if 'weak_signal' in gating:
                        weak_signal_count += 1
                    if 'low_consistency' in gating:
                        low_consistency_count += 1
                    if not gating and signal.get('confirm', False):
                        passed_signals += 1

                logger.info("[CONSISTENCY_QA] Real signals distribution:")
                logger.info(f"  Total real signals: {len(qa_signals)}")
                if qa_signals:
                    for bucket, count in consistency_buckets.items():
                        if count > 0:
                            logger.info(f"  Consistency {bucket}: {count} ({count/len(qa_signals)*100:.1f}%)")
                    logger.info(f"  Weak signal gated: {weak_signal_count} ({weak_signal_count/len(qa_signals)*100:.1f}%)")
                    logger.info(f"  Low consistency gated: {low_consistency_count} ({low_consistency_count/len(qa_signals)*100:.1f}%)")
                    logger.info(f"  Passed all gates: {passed_signals} ({passed_signals/len(qa_signals)*100:.1f}%)")
                else:
                    logger.info("  No signals to analyze")

            # consistency分布QA检查
            consistency_buckets = {
                '< 0.00': 0,
                '[0.00, 0.05)': 0,
                '[0.05, 0.15)': 0,
                '[0.15, 0.30)': 0,
                '[0.30, 0.50)': 0,
                '[0.50, 0.70)': 0,
                '[0.70, 1.00]': 0,
                '> 1.00': 0
            }

            for signal in qa_signals:
                consistency = signal.get('consistency', 0.0)
                if consistency < 0.0:
                    consistency_buckets['< 0.00'] += 1
                elif consistency < 0.05:
                    consistency_buckets['[0.00, 0.05)'] += 1
                elif consistency < 0.15:
                    consistency_buckets['[0.05, 0.15)'] += 1
                elif consistency < 0.30:
                    consistency_buckets['[0.15, 0.30)'] += 1
                elif consistency < 0.50:
                    consistency_buckets['[0.30, 0.50)'] += 1
                elif consistency < 0.70:
                    consistency_buckets['[0.50, 0.70)'] += 1
                elif consistency <= 1.0:
                    consistency_buckets['[0.70, 1.00]'] += 1
                else:
                    consistency_buckets['> 1.00'] += 1

            # 断言：consistency不能为负数
            if consistency_buckets['< 0.00'] > 0:
                logger.error(f"[CONSISTENCY_QA] ERROR: Found {consistency_buckets['< 0.00']} signals with negative consistency!")
                raise ValueError(f"Negative consistency detected: {consistency_buckets['< 0.00']} signals")

            logger.info("[CONSISTENCY_QA] Consistency distribution:")
            for bucket, count in consistency_buckets.items():
                if count > 0:
                    logger.info(f"  {bucket}: {count} ({count/len(qa_signals)*100:.1f}%)")

            # 输出gating QA快照
            if qa_signals:
                gating_qa_summary = {
                    "total_signals": len(qa_signals),
                    "confirm_true_ratio": confirm_true_count / len(qa_signals) if qa_signals else 0.0,
                    "gating_counts": gating_counts,
                    "gating_distribution": {
                        reason: count / len(qa_signals) * 100
                        for reason, count in gating_counts.items()
                    },
                    "passed_signals": passed_signals,
                    "passed_ratio": passed_signals / len(qa_signals) * 100 if qa_signals else 0.0,
                    "consistency_buckets": consistency_buckets,
                    "consistency_distribution": {
                        bucket: count / len(qa_signals) * 100
                        for bucket, count in consistency_buckets.items()
                    }
                }

                # 写入gating_qa_summary.json（如果有output_dir的话）
                # 注意：BacktestAdapter可能没有output_dir，这里只是为了兼容性
                if hasattr(self, 'output_dir'):
                    gating_qa_path = self.output_dir / "gating_qa_summary.json"
                    with gating_qa_path.open("w", encoding="utf-8") as f:
                        json.dump(gating_qa_summary, f, ensure_ascii=False, indent=2)
                    logger.info(f"[GATING_QA] Saved gating QA summary to {gating_qa_path}")

                    # 写入详细的gating_qa.jsonl（可选，用于更详细分析）
                    if getattr(self, 'consistency_qa_mode', False):
                        gating_qa_detail_path = self.output_dir / "gating_qa_detail.jsonl"
                        with gating_qa_detail_path.open("w", encoding="utf-8") as f:
                            for signal in qa_signals:
                                f.write(json.dumps(signal, ensure_ascii=False) + "\n")
                        logger.info(f"[GATING_QA] Saved detailed gating QA to {gating_qa_detail_path}")

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
            db_path_str = self.signals_src[9:]  # Remove "sqlite://" prefix
            # 解析相对路径为绝对路径
            db_path = Path(db_path_str).absolute()
            yield from self._iter_signals_sqlite(db_path)
        else:
            raise ValueError(f"Unsupported signals_src format: {self.signals_src}")

    def validate_signals_data_quality(self) -> Dict[str, Any]:
        """验证signals源数据质量，返回质量报告"""
        quality_report = {
            "total_signals": 0,
            "timestamp_monotonic": True,
            "violations": []
        }

        # 收集所有信号进行验证
        all_signals = list(self._iter_signals_from_source())
        quality_report["total_signals"] = len(all_signals)

        if not all_signals:
            return quality_report

        # 验证时间戳单调递增
        prev_ts = None
        violations = []

        for i, signal in enumerate(all_signals):
            ts = signal.get("ts_ms")
            if ts is None:
                violations.append({
                    "type": "missing_timestamp",
                    "index": i,
                    "signal": signal
                })
                continue

            if prev_ts is not None and ts < prev_ts:
                violations.append({
                    "type": "timestamp_violation",
                    "index": i,
                    "ts_ms": ts,
                    "prev_ts_ms": prev_ts,
                    "diff_ms": ts - prev_ts
                })
                quality_report["timestamp_monotonic"] = False

            prev_ts = ts

        quality_report["violations"] = violations

        if violations:
            logger.warning(f"DATA QUALITY ISSUE: {len(violations)} data quality violations found")
            for violation in violations[:3]:  # 只记录前3个违规
                logger.warning(f"Violation: {violation}")
        else:
            logger.info(f"DATA QUALITY CHECK: {len(all_signals)} signals passed all quality checks ✅")

        return quality_report


    def _iter_signals_jsonl(self, signals_dir: Path) -> Iterator[Dict[str, Any]]:
        """从JSONL文件读取signals（带去重逻辑）"""
        import glob
        pattern = str(signals_dir / "**" / "signals*.jsonl")
        jsonl_files = glob.glob(pattern, recursive=True)

        # 用于去重的集合：(ts_ms, symbol, signal_type, score)
        seen_signals = set()

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

                        # 去重：使用(ts_ms, symbol, signal_type, score)作为唯一标识
                        # 保留最新的run_id（通过文件排序，后面文件优先）
                        signal_key = (
                            ts_ms,
                            symbol,
                            signal.get('signal_type', ''),
                            signal.get('score', 0.0)
                        )

                        if signal_key not in seen_signals:
                            seen_signals.add(signal_key)
                            yield signal
                        # 否则跳过重复信号（静默跳过，避免日志污染）

            except Exception as e:
                logger.warning(f"Error reading {file_path}: {e}")

    def _iter_signals_sqlite(self, db_path: Path) -> Iterator[Dict[str, Any]]:
        """从SQLite数据库读取signals"""
        import sqlite3
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # 读取节流窗口
            dedupe_ms = int((self.config or {}).get("signal", {}).get("dedupe_ms", 0))
            seen = set()
            last_ts_per_sym = {}

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

            row_count = 0
            for row in cursor:
                row_count += 1
                signal = dict(zip(columns, row))
                # 解析gating_json/gating，确保 signal['gating'] 最终是"原因列表"
                raw_gating = signal.get("gating", None)
                if 'gating_json' in signal:
                    try:
                        if signal['gating_json']:
                            parsed = json.loads(signal['gating_json'])
                            # 允许 gating_json 是 bool/list，全部规范成 list
                            if isinstance(parsed, list):
                                signal['gating'] = parsed
                            elif isinstance(parsed, (bool, int)):
                                signal['gating'] = [] if not parsed else [signal.get('guard_reason') or 'guarded']
                            else:
                                signal['gating'] = []
                        else:
                            signal['gating'] = []
                    except Exception:
                        signal['gating'] = []
                    del signal['gating_json']
                elif raw_gating is not None:
                    # 兼容 CORE_ALGO 的 gating=0/1
                    if isinstance(raw_gating, (bool, int)):
                        signal['gating'] = [] if not raw_gating else [signal.get('guard_reason') or 'guarded']
                    elif isinstance(raw_gating, list):
                        signal['gating'] = raw_gating
                    else:
                        signal['gating'] = []
                else:
                    signal['gating'] = []

                # 轻度去重：ts_ms + symbol + signal_id
                key = (signal.get("ts_ms"), signal.get("symbol"), signal.get("signal_id"))
                if key in seen:
                    continue
                seen.add(key)

                # 时间节流：同一 symbol 在 dedupe_ms 窗口内仅保留首个
                if dedupe_ms > 0:
                    ts, sym = int(signal.get("ts_ms", 0)), str(signal.get("symbol","")).upper()
                    last = last_ts_per_sym.get(sym, -10**18)
                    if ts - last < dedupe_ms:
                        continue
                    last_ts_per_sym[sym] = ts

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

        # 定义允许的文件类型
        self.allowed_extensions = {'.jsonl', '.json', '.sqlite', '.log'}
        self.allowed_filenames = {
            'signals.jsonl', 'signals.sqlite', 'trades.jsonl',
            'pnl_daily.jsonl', 'run_manifest.json',
            'gating_qa_summary.json', 'gating_qa_detail.jsonl'
        }

        # 初始化文件句柄
        self.signals_file = None
        self.trades_file = None
        self.pnl_file = None
        self.sqlite_conn = None

        self._validate_output_directory()
        self._init_files()

    def _validate_output_directory(self):
        """验证输出目录约束"""
        # 检查目录是否存在意外文件
        if self.output_dir.exists():
            existing_files = list(self.output_dir.glob("*"))
            if existing_files:
                logger.warning(f"Output directory {self.output_dir} is not empty: {existing_files}")
                # 不强制清理，让用户自己处理

    def validate_output_structure(self):
        """验证输出结构约束：在写入完成后检查"""
        try:
            all_files = list(self.output_dir.glob("*"))
            logger.info(f"Validating output structure: found {len(all_files)} files")

            violations = []
            for file_path in all_files:
                if file_path.is_file():
                    filename = file_path.name
                    extension = file_path.suffix

                    # 检查是否为允许的文件名或扩展名
                    if filename not in self.allowed_filenames and extension not in self.allowed_extensions:
                        violations.append(f"Unexpected file: {filename}")

            if violations:
                logger.error(f"OUTPUT STRUCTURE VIOLATIONS: {len(violations)} unexpected files")
                for violation in violations:
                    logger.error(f"  {violation}")
                raise ValueError(f"Output directory contains unexpected files: {violations}")

            # 检查必需文件是否存在
            required_files = ['trades.jsonl', 'pnl_daily.jsonl', 'run_manifest.json']
            if self.write_signals:
                required_files.append('signals.jsonl')
            if self.emit_sqlite:
                required_files.append('signals.sqlite')

            missing_files = []
            for req_file in required_files:
                if not (self.output_dir / req_file).exists():
                    missing_files.append(req_file)

            if missing_files:
                logger.error(f"OUTPUT STRUCTURE VIOLATIONS: Missing required files: {missing_files}")
                raise ValueError(f"Missing required output files: {missing_files}")

            logger.info(f"OUTPUT STRUCTURE VALIDATION PASSED: {len(all_files)} files, all constraints satisfied ✅")

        except Exception as e:
            logger.error(f"Output structure validation failed: {e}")
            raise

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
            score = signal.get('score') or 0
            # 处理NaN值
            if isinstance(score, float) and math.isnan(score):
                score = 0
            signal["signal_id"] = f"{signal.get('symbol','')}:{signal.get('ts_ms','')}:{int(score*1e6)}"

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


def build_run_manifest(args, config: Dict[str, Any], symbols, features_price_dir: Optional[Path] = None) -> Dict[str, Any]:
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
        "gating_mode": getattr(args, 'gating_mode', 'strict'),
        "legacy_backtest_mode": bool(getattr(args, 'legacy_backtest_mode', False)),
        "quality_mode": getattr(args, 'quality_mode', 'all'),
        "env": env_whitelist,
        "effective_config": {
            "features_price_dir": str(features_price_dir) if features_price_dir else None,
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
    parser.add_argument("--features-price-dir", type=str,
                       help="价格数据根目录，覆盖config.yaml中的data.features_price_dir")
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
    parser.add_argument("--consistency-qa", action="store_true",
                       help="一致性QA模式：输出真实信号的一致性分布统计")
    parser.add_argument("--reemit-signals", action="store_true",
                       help="模式B下按需重发signals（默认不写，便于对账）")
    parser.add_argument("--gating-mode", choices=["strict", "ignore_soft", "ignore_all"],
                       default="strict",
                       help="Backtest gating mode: "
                            "strict=production style; "
                            "ignore_soft=忽略 weak_signal/low_consistency 等软护栏; "
                            "ignore_all=完全忽略 gating（只看 confirm）")
    parser.add_argument("--legacy-backtest-mode", action="store_true",
                       help="Legacy backtest mode: 完全忽略confirm和gating，只基于direction/score交易 "
                            "(仅用于诊断对比，不进入正式评估/CI)")
    parser.add_argument("--quality-mode", choices=["conservative", "balanced", "aggressive", "all"],
                       default="all",
                       help="Quality tier filtering mode: "
                            "conservative=only strong tier; "
                            "balanced=strong + normal (no low_consistency); "
                            "aggressive=all confirmed signals; "
                            "all=no quality filtering")

    args = parser.parse_args()

    # 验证参数
    if args.mode == "A" and not args.features_dir:
        parser.error("--features-dir required for mode A")
    if args.mode == "B" and not args.signals_src:
        parser.error("--signals-src required for mode B")

    # 验证signals-src协议格式（仅模式B）
    if args.mode == "B":
        src = args.signals_src
        if not (src.startswith("jsonl://") or src.startswith("sqlite://")):
            # 温和自动补全：如果以.db结尾，自动添加sqlite://前缀
            if src.endswith(".db"):
                args.signals_src = f"sqlite://{src}"
                logger.info(f"Auto-corrected signals-src to: {args.signals_src}")
            else:
                parser.error("signals-src must start with jsonl:// or sqlite://, got: %s" % src)

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

    # 解析最终的features_price_dir路径（用于manifest记录）
    final_features_price_dir = resolve_features_price_dir(
        cli_features_price_dir=getattr(args, 'features_price_dir', None),
        config=config
    )

    # 构建运行清单
    manifest = build_run_manifest(args, config, symbols, final_features_price_dir)

    # 初始化组件

    adapter = BacktestAdapter(
        mode=args.mode,
        features_dir=Path(args.features_dir) if args.features_dir else None,
        signals_src=args.signals_src,
        symbols=symbols,
        start_ms=start_ms,
        end_ms=end_ms,
        strict_core=bool(args.strict_core),
        consistency_qa_mode=bool(args.consistency_qa),
        run_id=manifest["run_id"],
        config=config,
        cli_features_price_dir=getattr(args, 'features_price_dir', None)
    )

    broker = BrokerSimulator(config.get("broker", {}))
    strategy_emulator = StrategyEmulator(config, gating_mode=args.gating_mode,
                                        legacy_backtest_mode=getattr(args, 'legacy_backtest_mode', False),
                                        quality_mode=getattr(args, 'quality_mode', 'all'))
    writer = BacktestWriter(
        Path(args.out_dir),
        manifest["run_id"],
        write_signals=((args.mode == "A") or bool(getattr(args, "reemit_signals", False))),
        emit_sqlite=(args.emit_sqlite or config.get("output", {}).get("emit_sqlite", False))
    )

    logger.info(f"Starting backtest {manifest['run_id']} in mode {args.mode}")

    # 模式B：验证signals数据质量
    data_quality_report = None
    if args.mode == 'B':
        logger.info("Performing signals data quality validation...")
        data_quality_report = adapter.validate_signals_data_quality()
        logger.info(f"Data quality check complete: {data_quality_report['total_signals']} signals validated")

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

            # 策略仿真器：判断是否可交易和交易方向
            can_trade, skip_reason = strategy_emulator.should_trade(signal)
            if not can_trade:
                logger.debug(f"Signal skipped: {skip_reason}")
                continue

            # 根据信号决定交易方向
            side = strategy_emulator.decide_side(signal)
            if not side:
                continue   # 仍无法判定方向则跳过

            # 信号可交易且方向明确，开始处理订单
            # 从配置和信号中解析价格
            price_fields = config.get("signal", {}).get("price_fields", ["mid_px", "price", "mid"])
            price = None
            for field in price_fields:
                if field in signal and signal[field] is not None:
                    price = float(signal[field])
                    break

            # 如果信号中没有价格，尝试从features数据获取真实价格
            if price is None:
                # 优先从features数据获取实时价格
                real_price = adapter.get_price_at_time(signal.get("symbol", ""), signal.get("ts_ms", 0))
                if real_price is not None and real_price > 0:
                    price = real_price
                    logger.debug(f"Using real price from features: {signal['symbol']} @ {price}")
                else:
                    # 找不到价格，加"no_price" gating，跳过该信号
                    logger.warning(f"No price available for {signal['symbol']} at {signal.get('ts_ms', 0)}, skipping")
                    continue

            if price is None or price <= 0:
                logger.warning(f"Invalid price {price} for {signal['symbol']}, skipping")
                continue

            # 从配置中获取订单数量
            qty = config.get("order", {}).get("qty", config.get("broker", {}).get("min_order_qty", 0.001))

            # 生成订单
            order = {
                "symbol": signal["symbol"],
                "side": side,
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

        # 检查价格缓存质量并添加到manifest
        if adapter._price_cache is not None:
            price_source_info = adapter._price_cache._get_quality_report()
        else:
            price_source_info = {
                "price_cache_loaded": 0,
                "price_cache_failure": adapter._price_cache_failure,
                "price_cache_error": adapter._price_cache_error_msg,
                "price_points_total": 0,
                "symbols_loaded": []
            }

        perf_info = {
            "signals_processed": processed_signals,
            "trades_generated": generated_trades,
            "duration_s": round(duration_s, 2),
            "avg_rps": round(processed_signals / max(duration_s, 1), 2),
            "memory_gib": final_mem_gib,
            "price_source": price_source_info
        }

        # 添加数据质量报告（如果有）
        if data_quality_report:
            perf_info["data_quality"] = data_quality_report

        manifest["perf"] = perf_info

        # 如果价格缓存失败，在日志中再次强调
        if adapter._price_cache_failure:
            logger.error(f"BACKTEST QUALITY WARNING: {adapter._price_cache_error_msg}")
            logger.error("This backtest used unrealistic default prices. Results may not reflect real market conditions.")
        writer.write_manifest(manifest)

        # 验证输出结构约束
        try:
            writer.validate_output_structure()
        except Exception as e:
            logger.error(f"Output structure validation failed: {e}")
            raise

        logger.info(f"Backtest completed: {processed_signals} signals, {generated_trades} trades in {duration_s:.1f}s")
        logger.info(f"Output directory: {writer.output_dir}")

    finally:
        writer.close()
        adapter.close()


if __name__ == "__main__":
    main()
