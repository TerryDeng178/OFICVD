# -*- coding: utf-8 -*-
"""
FeaturePipe - 特征计算接线（OFI + CVD + FUSION + DIVERGENCE）

统一输入 → 标准输出 → 最小可跑

功能：
1. 维护 per-symbol 状态（orderbook L1/LK、最近 trades）
2. 调用 OFI/CVD/FUSION/DIVERGENCE 组件
3. 产出 FeatureRow 并写入 sink（JSONL/SQLite）

Author: V13 OFI+CVD AI System
Date: 2025-11-06
"""

from __future__ import annotations
import json
import logging
import math
import sqlite3
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

# 导入组件
from .ofi.real_ofi_calculator import RealOFICalculator, OFIConfig
from .cvd.real_cvd_calculator import RealCVDCalculator, CVDConfig
from .fusion.ofi_cvd_fusion import OFI_CVD_Fusion, OFICVDFusionConfig
from .divergence.ofi_cvd_divergence import DivergenceDetector, DivergenceConfig

logger = logging.getLogger(__name__)


class FeaturePipe:
    """
    特征计算管道
    
    维护 per-symbol 状态，调用 OFI/CVD/FUSION/DIVERGENCE，产出 FeatureRow
    """
    
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        symbols: Optional[List[str]] = None,
        sink: str = "jsonl",
        output_dir: Optional[str] = None,
        dedupe_ms: int = 1000,
        max_lag_sec: float = 0.25
    ):
        """
        初始化特征管道
        
        Args:
            config: 配置字典（包含 features.ofi/cvd/fusion/divergence）
            symbols: 交易对列表，None 表示支持所有交易对
            sink: 输出类型（jsonl/sqlite）
            output_dir: 输出目录
            dedupe_ms: 去重窗口（毫秒）
            max_lag_sec: 最大滞后时间（秒）
        """
        self.config = config or {}
        self.symbols = symbols or []
        self.sink = sink.lower()
        self.output_dir = Path(output_dir or "./runtime")
        self.dedupe_ms = dedupe_ms
        self.max_lag_sec = max_lag_sec
        
        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载 features 配置
        features_cfg = self.config.get("features", {})
        ofi_cfg = features_cfg.get("ofi", {})
        cvd_cfg = features_cfg.get("cvd", {})
        fusion_cfg = features_cfg.get("fusion", {})
        div_cfg = features_cfg.get("divergence", {})
        
        # 初始化 per-symbol 状态
        self.states: Dict[str, SymbolState] = {}
        
        # 初始化 sink
        if self.sink == "jsonl":
            self.sink_file = self.output_dir / "features.jsonl"
            self.sink_fp = open(self.sink_file, "w", encoding="utf-8", newline="")
        elif self.sink == "sqlite":
            self.sink_file = self.output_dir / "features.db"
            self.conn = sqlite3.connect(str(self.sink_file))
            self._init_sqlite()
        else:
            raise ValueError(f"Unsupported sink type: {sink}")
        
        # 去重窗口（按 symbol）
        self._seen_rows: Dict[str, deque] = {}  # symbol -> deque of (ts_ms, row_id)
        
        logger.info(f"FeaturePipe initialized: sink={sink}, output_dir={self.output_dir}")
    
    def _init_sqlite(self):
        """初始化 SQLite 数据库表"""
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS features (
                ts_ms INTEGER,
                symbol TEXT,
                z_ofi REAL,
                z_cvd REAL,
                price REAL,
                lag_sec REAL,
                spread_bps REAL,
                fusion_score REAL,
                consistency REAL,
                dispersion REAL,
                sign_agree INTEGER,
                div_type TEXT,
                activity_tps REAL,
                warmup INTEGER,
                reason_codes TEXT,
                created_at TEXT,
                signal TEXT,
                PRIMARY KEY (ts_ms, symbol)
            )
        """)
        # 向后兼容：如果表已存在但缺少 signal 列，则添加
        # 先检查列是否存在，避免无谓的 ALTER 异常开销
        cur.execute("PRAGMA table_info(features)")
        cols = {row[1] for row in cur.fetchall()}
        if "signal" not in cols:
            cur.execute("ALTER TABLE features ADD COLUMN signal TEXT DEFAULT 'neutral'")
        self.conn.commit()
    
    def _get_or_create_state(self, symbol: str) -> SymbolState:
        """获取或创建 per-symbol 状态"""
        if symbol not in self.states:
            # 加载配置
            features_cfg = self.config.get("features", {})
            ofi_cfg = features_cfg.get("ofi", {})
            cvd_cfg = features_cfg.get("cvd", {})
            fusion_cfg = features_cfg.get("fusion", {})
            div_cfg = features_cfg.get("divergence", {})
            
            # 创建 OFI 计算器
            ofi_config = OFIConfig(
                levels=ofi_cfg.get("levels", 5),
                weights=ofi_cfg.get("weights", [0.4, 0.25, 0.2, 0.1, 0.05]),
                z_window=ofi_cfg.get("zscore_window", 30000) // 100,  # 转换为样本数
                ema_alpha=ofi_cfg.get("ema_alpha", 0.2)
            )
            ofi_calc = RealOFICalculator(symbol, ofi_config)
            
            # 创建 CVD 计算器
            cvd_config = CVDConfig(
                z_window=cvd_cfg.get("window_ms", 60000) // 100,  # 转换为样本数
                z_mode=cvd_cfg.get("z_mode", "delta")
            )
            cvd_calc = RealCVDCalculator(symbol, cvd_config)
            
            # 创建 FUSION 计算器
            fusion_config = OFICVDFusionConfig(
                w_ofi=fusion_cfg.get("w_ofi", 0.6),
                w_cvd=fusion_cfg.get("w_cvd", 0.4)
            )
            fusion_calc = OFI_CVD_Fusion(fusion_config)
            
            # 创建 DIVERGENCE 计算器
            # 将 lookback_bars 映射到 swing_L（枢轴检测窗口长度）
            div_config = DivergenceConfig(
                swing_L=div_cfg.get("lookback_bars", 60)
            )
            div_calc = DivergenceDetector(div_config)
            
            self.states[symbol] = SymbolState(
                symbol=symbol,
                ofi_calc=ofi_calc,
                cvd_calc=cvd_calc,
                fusion_calc=fusion_calc,
                div_calc=div_calc
            )
        
        return self.states[symbol]
    
    def on_row(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        处理单条输入行，返回 FeatureRow 或 None
        
        Args:
            row: 输入行（统一 Row Schema）
            
        Returns:
            FeatureRow 字典或 None（如果跳过）
        """
        try:
            # 提取基础字段
            ts_ms = row.get("ts_ms")
            symbol = row.get("symbol", "").upper()
            src = row.get("src", "")
            
            if not ts_ms or not symbol:
                logger.debug(f"Skip row: missing ts_ms or symbol")
                return None
            
            # 检查交易对白名单
            if self.symbols and symbol not in self.symbols:
                return None
            
            # 去重检查
            if self._is_duplicate(symbol, ts_ms, row.get("row_id")):
                logger.debug(f"Skip duplicate: {symbol} {ts_ms}")
                return None
            
            # 获取状态
            state = self._get_or_create_state(symbol)
            
            # 根据数据源类型处理
            if src in ("orderbook", "depth", "bookTicker"):
                # 更新订单簿状态
                bids = self._extract_bids(row)
                asks = self._extract_asks(row)
                if bids and asks:
                    state.last_orderbook = {
                        "bids": bids,
                        "asks": asks,
                        "ts_ms": ts_ms
                    }
                    # P0: 更新报价窗口（每次订单簿更新）
                    state.quote_ts_window.append(ts_ms)
            elif src in ("aggTrade", "trade"):
                # 更新成交状态
                price = row.get("price")
                qty = row.get("qty", 0.0)
                side = row.get("side")
                is_buy = None
                if side:
                    is_buy = side.lower() in ("buy", "b")
                elif price and state.last_price:
                    is_buy = price >= state.last_price
                
                state.last_trade = {
                    "price": price,
                    "qty": qty,
                    "is_buy": is_buy,
                    "ts_ms": ts_ms
                }
                if price:
                    # P0: 更新交易窗口和收益率窗口
                    state.trade_ts_window.append(ts_ms)
                    
                    # 计算收益率（对数收益）
                    if state.last_price and state.last_price > 0 and price > 0:
                        import math
                        ret = math.log(price / state.last_price)
                        state.ret_window.append(ret)
                    
                    # 更新成交额窗口
                    if qty > 0:
                        volume_usd = price * qty
                        state.vol_window.append((ts_ms, volume_usd))
                    
                    state.last_price = price
            
            # 计算特征（需要订单簿和成交都可用）
            if state.last_orderbook and state.last_trade:
                return self._compute_features(state, row)
            
            return None
            
        except Exception as e:
            logger.warning(f"Error processing row: {e}", exc_info=True)
            return None
    
    def _extract_bids(self, row: Dict[str, Any]) -> List[Tuple[float, float]]:
        """
        提取 bids 列表
        
        要求：bids 必须按价格从高到低排序（bids[0] 为最高买价）
        如输入未保证顺序，会先排序再取前 5 档
        """
        bids = row.get("bids", [])
        if isinstance(bids, list):
            result = []
            # 先转换为 (price, qty) 元组并过滤无效数据
            candidates = []
            for bid in bids:
                if isinstance(bid, (list, tuple)) and len(bid) >= 2:
                    try:
                        price = float(bid[0])
                        qty = float(bid[1])
                        if price > 0 and qty >= 0:
                            candidates.append((price, qty))
                    except (ValueError, TypeError):
                        continue
            # 按价格从高到低排序（bids 排序规则）
            candidates.sort(key=lambda x: x[0], reverse=True)
            # 取前 5 档
            return candidates[:5]
        return []
    
    def _extract_asks(self, row: Dict[str, Any]) -> List[Tuple[float, float]]:
        """
        提取 asks 列表
        
        要求：asks 必须按价格从低到高排序（asks[0] 为最低卖价）
        如输入未保证顺序，会先排序再取前 5 档
        """
        asks = row.get("asks", [])
        if isinstance(asks, list):
            result = []
            # 先转换为 (price, qty) 元组并过滤无效数据
            candidates = []
            for ask in asks:
                if isinstance(ask, (list, tuple)) and len(ask) >= 2:
                    try:
                        price = float(ask[0])
                        qty = float(ask[1])
                        if price > 0 and qty >= 0:
                            candidates.append((price, qty))
                    except (ValueError, TypeError):
                        continue
            # 按价格从低到高排序（asks 排序规则）
            candidates.sort(key=lambda x: x[0], reverse=False)
            # 取前 5 档
            return candidates[:5]
        return []
    
    def _rate_per_window(self, ts_window: deque, ts_ms: int, seconds: int = 60) -> float:
        """计算时间窗口内的速率（每分钟）"""
        # 修剪过期数据（保留最近 seconds 秒）
        while ts_window and (ts_ms - ts_window[0]) > seconds * 1000:
            ts_window.popleft()
        n = len(ts_window)
        return (n / seconds) * 60.0 if seconds > 0 else 0.0  # per min
    
    def _compute_features(self, state: SymbolState, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """计算特征"""
        try:
            ts_ms = row.get("ts_ms")
            symbol = row.get("symbol", "").upper()
            
            # 提取订单簿和成交
            ob = state.last_orderbook
            trade = state.last_trade
            
            if not ob or not trade:
                return None
            
            # 计算 lag
            lag_sec = (ts_ms - max(ob["ts_ms"], trade["ts_ms"])) / 1000.0
            if lag_sec > self.max_lag_sec:
                logger.debug(f"Skip: lag too high {lag_sec:.3f}s > {self.max_lag_sec}s")
                return None
            
            # P0: 计算真实活动度指标（60s 窗口）
            trades_per_min = self._rate_per_window(state.trade_ts_window, ts_ms, 60)
            quote_updates_per_sec = self._rate_per_window(state.quote_ts_window, ts_ms, 60) / 60.0
            
            # 计算 realized_vol_bps（近 60s 对数收益率标准差 × 10000）
            import numpy as np
            realized_vol_bps = 0.0
            if state.ret_window and len(state.ret_window) >= 2:
                ret_array = np.array(list(state.ret_window))
                realized_vol_bps = float(np.std(ret_array) * 10000.0)
            
            # 计算 volume_usd（近 60s 成交额汇总）
            volume_usd = 0.0
            while state.vol_window and (ts_ms - state.vol_window[0][0]) > 60000:
                state.vol_window.popleft()
            if state.vol_window:
                volume_usd = float(sum(v for _, v in state.vol_window))
            
            # 1. 计算 OFI
            bids = ob["bids"]
            asks = ob["asks"]
            ofi_result = state.ofi_calc.update_with_snapshot(
                bids=bids,
                asks=asks,
                event_time_ms=ts_ms
            )
            z_ofi = ofi_result.get("z_ofi")
            if z_ofi is None:
                z_ofi = 0.0  # warmup 期置为 0
            
            # 2. 计算 CVD
            cvd_result = state.cvd_calc.update_with_trade(
                price=trade["price"],
                qty=trade["qty"],
                is_buy=trade["is_buy"],
                event_time_ms=ts_ms
            )
            z_cvd = cvd_result.get("z_cvd")
            if z_cvd is None:
                z_cvd = 0.0  # warmup 期置为 0
            
            # 检查 warmup（在计算 FUSION 之前）
            warmup = (
                ofi_result.get("warmup", False) or
                cvd_result.get("warmup", False)
            )
            
            # 3. 计算 FUSION
            ts_sec = ts_ms / 1000.0
            price = trade.get("price") or row.get("price")
            fusion_result = state.fusion_calc.update(
                z_ofi=z_ofi,
                z_cvd=z_cvd,
                ts=ts_sec,
                price=price,
                lag_sec=lag_sec
            )
            fusion_score = fusion_result.get("fusion_score", 0.0)
            consistency = fusion_result.get("consistency", 0.0)
            signal = fusion_result.get("signal", "neutral")
            dispersion = fusion_result.get("dispersion", 0.0)
            sign_agree = 1 if (z_ofi * z_cvd >= 0) else -1
            
            # 4. 计算 DIVERGENCE
            div_result = state.div_calc.update(
                ts=ts_sec,
                price=price or 0.0,
                z_ofi=z_ofi,
                z_cvd=z_cvd,
                fusion_score=fusion_score,
                consistency=consistency,
                warmup=warmup,
                lag_sec=lag_sec
            )
            div_type = None
            if div_result:
                div_type_value = div_result.get("type") or div_result.get("divergence_type")
                if div_type_value:
                    # 如果是枚举，获取值
                    if hasattr(div_type_value, "value"):
                        div_type = div_type_value.value
                    else:
                        div_type = str(div_type_value)
            
            # 5. 计算 spread_bps
            spread_bps = row.get("best_spread_bps", 0.0)
            if not spread_bps and bids and asks:
                bid_price = bids[0][0] if bids else 0.0
                ask_price = asks[0][0] if asks else 0.0
                mid_price = (bid_price + ask_price) / 2.0 if (bid_price and ask_price) else price or 0.0
                if mid_price > 0:
                    spread_bps = ((ask_price - bid_price) / mid_price) * 10000.0
            
            # 6. 计算 activity
            if not isinstance(state.activity_window, deque):
                state.activity_window = deque(maxlen=100)
            state.activity_window.append(ts_ms)
            if len(state.activity_window) >= 2:
                window_ms = state.activity_window[-1] - state.activity_window[0]
                tps = (len(state.activity_window) - 1) / (window_ms / 1000.0) if window_ms > 0 else 0.0
            else:
                tps = 0.0
            
            # 构建 FeatureRow
            feature_row = {
                "ts_ms": ts_ms,
                "symbol": symbol,
                "z_ofi": z_ofi,
                "z_cvd": z_cvd,
                "price": price,
                "lag_sec": lag_sec,
                "spread_bps": spread_bps,
                "fusion_score": fusion_score,
                "consistency": consistency,
                "dispersion": dispersion,
                "sign_agree": sign_agree,
                "div_type": div_type,
                "activity": {"tps": tps},
                # P0: 添加真实活动度字段（用于 StrategyMode）
                "trade_rate": trades_per_min,
                "quote_rate": quote_updates_per_sec,
                "realized_vol_bps": realized_vol_bps,
                "volume_usd": volume_usd,
                "warmup": warmup,
                "signal": signal
            }
            
            # 写入 sink
            self._write_feature(feature_row)
            
            return feature_row
            
        except Exception as e:
            logger.warning(f"Error computing features: {e}", exc_info=True)
            return None
    
    def _is_duplicate(self, symbol: str, ts_ms: int, row_id: Optional[str]) -> bool:
        """检查是否重复"""
        if symbol not in self._seen_rows:
            self._seen_rows[symbol] = deque(maxlen=1000)
        
        seen = self._seen_rows[symbol]
        
        # 检查时间窗口
        while seen and (ts_ms - seen[0][0]) > self.dedupe_ms:
            seen.popleft()
        
        # 检查是否已存在
        for seen_ts, seen_id in seen:
            if seen_ts == ts_ms or (row_id and seen_id == row_id):
                return True
        
        # 添加新记录
        seen.append((ts_ms, row_id))
        return False
    
    def _write_feature(self, feature_row: Dict[str, Any]):
        """写入特征行到 sink（稳定 JSON 序列化，确保回放可复现）"""
        if self.sink == "jsonl":
            json_line = json.dumps(
                feature_row,
                ensure_ascii=False,
                sort_keys=True,  # 稳定排序，确保回放可复现
                separators=(",", ":")  # 紧凑格式，无空格
            )
            self.sink_fp.write(json_line + "\n")
            self.sink_fp.flush()
        elif self.sink == "sqlite":
            cur = self.conn.cursor()
            # 使用显式列名，避免与历史库错位，并确保前向兼容
            cur.execute("""
                INSERT OR REPLACE INTO features (
                    ts_ms, symbol, z_ofi, z_cvd, price, lag_sec, spread_bps,
                    fusion_score, consistency, dispersion, sign_agree, div_type,
                    activity_tps, warmup, reason_codes, created_at, signal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                feature_row["ts_ms"],
                feature_row["symbol"],
                feature_row["z_ofi"],
                feature_row["z_cvd"],
                feature_row["price"],
                feature_row["lag_sec"],
                feature_row["spread_bps"],
                feature_row["fusion_score"],
                feature_row["consistency"],
                feature_row["dispersion"],
                feature_row["sign_agree"],
                feature_row["div_type"],
                feature_row["activity"]["tps"],
                1 if feature_row["warmup"] else 0,
                json.dumps(feature_row.get("reason_codes", [])),
                datetime.now(timezone.utc).isoformat(),
                feature_row.get("signal", "neutral")  # 默认值 'neutral'
            ))
            self.conn.commit()
    
    def flush(self):
        """刷新缓冲区"""
        if self.sink == "jsonl":
            self.sink_fp.flush()
        elif self.sink == "sqlite":
            self.conn.commit()
    
    def close(self):
        """关闭资源"""
        if self.sink == "jsonl":
            self.sink_fp.close()
        elif self.sink == "sqlite":
            self.conn.close()


class SymbolState:
    """Per-symbol 状态"""
    
    def __init__(
        self,
        symbol: str,
        ofi_calc: RealOFICalculator,
        cvd_calc: RealCVDCalculator,
        fusion_calc: OFI_CVD_Fusion,
        div_calc: DivergenceDetector
    ):
        self.symbol = symbol
        self.ofi_calc = ofi_calc
        self.cvd_calc = cvd_calc
        self.fusion_calc = fusion_calc
        self.div_calc = div_calc
        
        # 状态缓存
        self.last_orderbook: Optional[Dict[str, Any]] = None
        self.last_trade: Optional[Dict[str, Any]] = None
        self.last_price: Optional[float] = None
        self.activity_window: deque = deque(maxlen=100)
        
        # P0: 真实活动度滑窗（用于 StrategyMode）
        self.trade_ts_window: deque = deque(maxlen=3000)  # 足够覆盖 60s 的 tick
        self.quote_ts_window: deque = deque(maxlen=6000)  # 订单簿更新更频繁
        self.ret_window: deque = deque(maxlen=600)  # 收益率窗口（用于 realized_vol）
        self.vol_window: deque = deque(maxlen=3000)  # 成交额窗口 (ts_ms, volume_usd)


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="FeaturePipe - 特征计算接线")
    parser.add_argument("--input", type=str, help="输入文件/目录（Parquet/JSONL）")
    parser.add_argument("--sink", type=str, default="jsonl", choices=["jsonl", "sqlite"])
    parser.add_argument("--out", type=str, default="./runtime/features.jsonl")
    parser.add_argument("--symbols", type=str, nargs="+", help="交易对列表")
    parser.add_argument("--config", type=str, default="./config/defaults.yaml")
    parser.add_argument("--dedupe-ms", type=int, default=1000)
    parser.add_argument("--max-lag-sec", type=float, default=0.25)
    
    args = parser.parse_args()
    
    # 加载配置
    config = {}
    if args.config:
        try:
            import yaml
            with open(args.config, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")
    
    # 创建 FeaturePipe
    output_dir = Path(args.out).parent
    pipe = FeaturePipe(
        config=config,
        symbols=args.symbols,
        sink=args.sink,
        output_dir=str(output_dir),
        dedupe_ms=args.dedupe_ms,
        max_lag_sec=args.max_lag_sec
    )
    
    try:
        # 读取输入文件
        if args.input:
            input_path = Path(args.input)
            logger.info(f"Reading from {args.input}")
            
            # 收集所有输入文件
            input_files = []
            if input_path.is_file():
                input_files = [input_path]
            elif input_path.is_dir():
                # 递归查找 Parquet 和 JSONL 文件
                input_files.extend(input_path.rglob("*.parquet"))
                input_files.extend(input_path.rglob("*.jsonl"))
            else:
                # 支持 glob 模式
                import glob
                input_files = [Path(f) for f in glob.glob(str(input_path))]
            
            if not input_files:
                logger.warning(f"No input files found: {args.input}")
                return 1
            
            logger.info(f"Found {len(input_files)} input files")
            
            # 处理每个文件
            total_rows = 0
            for file_path in sorted(input_files):
                logger.info(f"Processing {file_path}")
                file_rows = 0
                
                try:
                    if file_path.suffix.lower() == ".parquet":
                        # 读取 Parquet 文件
                        import pandas as pd
                        df = pd.read_parquet(file_path)
                        logger.debug(f"Loaded {len(df)} rows from {file_path}")
                        
                        # 转换为字典列表
                        for _, row in df.iterrows():
                            row_dict = row.to_dict()
                            # 转换 numpy 类型为 Python 原生类型
                            for k, v in row_dict.items():
                                if hasattr(v, 'item'):  # numpy scalar
                                    row_dict[k] = v.item()
                                elif isinstance(v, (list, tuple)) and len(v) > 0:
                                    # 处理列表中的 numpy 类型
                                    row_dict[k] = [x.item() if hasattr(x, 'item') else x for x in v]
                            
                            if pipe.on_row(row_dict):
                                file_rows += 1
                                total_rows += 1
                    elif file_path.suffix.lower() == ".jsonl":
                        # 读取 JSONL 文件
                        with open(file_path, 'r', encoding='utf-8') as f:
                            for line_num, line in enumerate(f, 1):
                                if not line.strip():
                                    continue
                                try:
                                    row = json.loads(line)
                                    if pipe.on_row(row):
                                        file_rows += 1
                                        total_rows += 1
                                except json.JSONDecodeError as e:
                                    logger.warning(f"Invalid JSON at {file_path}:{line_num}: {e}")
                                except Exception as e:
                                    logger.warning(f"Error processing line {file_path}:{line_num}: {e}")
                    else:
                        logger.warning(f"Unsupported file type: {file_path}")
                        continue
                    
                    logger.info(f"Processed {file_rows} feature rows from {file_path}")
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}", exc_info=True)
            
            logger.info(f"Total processed: {total_rows} feature rows from {len(input_files)} files")
        else:
            logger.info("Waiting for input rows from stdin...")
            # 从标准输入读取 JSONL
            import sys
            for line in sys.stdin:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    pipe.on_row(row)
                except Exception as e:
                    logger.warning(f"Error processing line: {e}")
    finally:
        pipe.flush()
        pipe.close()


if __name__ == "__main__":
    main()

