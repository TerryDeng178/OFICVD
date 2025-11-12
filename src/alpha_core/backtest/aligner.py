# -*- coding: utf-8 -*-
"""T08.2: Aligner - Time alignment and feature completion"""
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

class DataAligner:
    """Align raw data to seconds and compute features"""
    
    def __init__(self, max_lag_ms: int = 5000, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            max_lag_ms: Maximum lag for alignment (default 5000ms = 5s)
            config: Optional configuration dict for thresholds (代码.4)
        """
        self.max_lag_ms = max_lag_ms
        
        # 代码.4: Aligner门限外置到配置（支持默认值与环境变量覆盖）
        import os
        config = config or {}
        aligner_config = config.get("aligner", {})
        
        # lag_threshold_ms: 用于标记lag_bad的阈值（默认5000ms）
        self.lag_threshold_ms = int(
            aligner_config.get("lag_threshold_ms") or 
            os.getenv("ALIGNER_LAG_THRESHOLD_MS", "5000")
        )
        
        # spread_threshold: 用于scenario_2x2判断的spread阈值（默认2.0 bps）
        self.spread_threshold = float(
            aligner_config.get("spread_threshold") or 
            os.getenv("ALIGNER_SPREAD_THRESHOLD", "2.0")
        )
        
        # volatility_threshold: 用于scenario_2x2判断的波动阈值（默认5.0 bps）
        self.volatility_threshold = float(
            aligner_config.get("volatility_threshold") or 
            os.getenv("ALIGNER_VOLATILITY_THRESHOLD", "5.0")
        )
        
        logger.info(
            f"[DataAligner] Thresholds: lag={self.lag_threshold_ms}ms, "
            f"spread={self.spread_threshold}bps, vol={self.volatility_threshold}bps"
        )
        self.stats = {
            "aligned_rows": 0,
            "missing_data": 0,
            "fallback_used": 0,
            # P1: 可观测性补完
            "gap_seconds_count": 0,  # is_gap_second=1的行数
            "lag_bad_price_count": 0,  # lag_bad_price=1的行数
            "lag_bad_orderbook_count": 0,  # lag_bad_orderbook=1的行数
        }
        # P0: 保存历史价格用于计算return_1s
        self._price_history: Dict[str, List[Tuple[int, float]]] = defaultdict(list)  # symbol -> [(ts_ms, mid), ...]
        # P0-3: 保存上次观测时间用于计算观测间隔（obs_gap_ms）诊断指标
        self._last_obs_ts: Dict[str, Dict[str, int]] = defaultdict(lambda: {"price": 0, "orderbook": 0})  # symbol -> {price: ts_ms, orderbook: ts_ms}
        # P0-3: 观测间隔统计（用于可观测性）
        self._obs_gap_sum: Dict[str, Dict[str, int]] = defaultdict(lambda: {"price": 0, "orderbook": 0})  # 累计间隔
        self._obs_gap_count: Dict[str, Dict[str, int]] = defaultdict(lambda: {"price": 0, "orderbook": 0})  # 计数
    
    def align_to_seconds(
        self,
        prices: Iterator[Dict[str, Any]],
        orderbook: Iterator[Dict[str, Any]],
    ) -> Iterator[Dict[str, Any]]:
        """
        P0: 增强版本 - 计算return_1s和lag_ms_*，细化scenario_2x2
        
        Align prices and orderbook data to seconds and compute features
        
        Args:
            prices: Iterator of price data
            orderbook: Iterator of orderbook data
            
        Yields:
            Feature rows aligned to seconds with spread_bps, best_bid/ask, scenario_2x2, return_1s, lag_ms_*
        """
        # Buffer for recent data (last 5 seconds)
        price_buffer: Dict[int, Dict] = {}  # second_ts -> latest price
        orderbook_buffer: Dict[int, Dict] = {}  # second_ts -> latest orderbook
        
        # Process prices (track observation time for lag calculation)
        for price_row in prices:
            ts_ms = price_row.get("ts_ms", 0)
            if ts_ms <= 0:
                continue
            second_ts = ts_ms // 1000
            symbol = price_row.get("symbol", "")
            price_buffer[second_ts] = price_row
            # P0: 记录观测时间用于lag计算
            if symbol:
                self._last_obs_ts[symbol]["price"] = ts_ms
        
        # Process orderbook (track observation time for lag calculation)
        for ob_row in orderbook:
            ts_ms = ob_row.get("ts_ms", 0)
            if ts_ms <= 0:
                continue
            second_ts = ts_ms // 1000
            symbol = ob_row.get("symbol", "")
            orderbook_buffer[second_ts] = ob_row
            # P0-3: 计算观测间隔（obs_gap_ms）用于诊断
            if symbol:
                last_ts = self._last_obs_ts[symbol]["orderbook"]
                if last_ts > 0:
                    gap_ms = ts_ms - last_ts
                    if gap_ms > 0:  # 避免负值或0值
                        self._obs_gap_sum[symbol]["orderbook"] += gap_ms
                        self._obs_gap_count[symbol]["orderbook"] += 1
                self._last_obs_ts[symbol]["orderbook"] = ts_ms
        
        # Align and yield features
        all_seconds = sorted(set(price_buffer.keys()) | set(orderbook_buffer.keys()))
        
        for second_ts in all_seconds:
            price = price_buffer.get(second_ts)
            ob = orderbook_buffer.get(second_ts)
            
            # Fallback: use latest available data within max_lag_ms
            if not price:
                price = self._find_latest(price_buffer, second_ts, self.max_lag_ms // 1000)
                if price:
                    self.stats["fallback_used"] += 1
            
            if not ob:
                ob = self._find_latest(orderbook_buffer, second_ts, self.max_lag_ms // 1000)
                if ob:
                    self.stats["fallback_used"] += 1
            
            if not price or not ob:
                self.stats["missing_data"] += 1
                continue
            
            # P0修复: 先更新价格历史，再计算return_1s（确保时序正确）
            # 提取mid价格用于历史更新
            symbol = price.get("symbol") or ob.get("symbol", "")
            mid = price.get("mid") or price.get("price")
            
            if symbol and mid is not None and mid > 0:
                price_history = self._price_history[symbol]
                
                # Check for gap seconds
                is_gap_second = False
                if price_history:
                    last_ts = price_history[-1][0] if price_history else 0
                    current_ts = second_ts * 1000
                    gap_seconds = (current_ts - last_ts) / 1000
                    if gap_seconds > 1.5:  # More than 1 second gap
                        is_gap_second = True
                        # P1: 拉链式回填 - use previous valid price for return_1s calculation
                        if price_history:
                            prev_valid_price = price_history[-1][1]
                            # Fill gap with previous price (for return_1s calculation continuity)
                            for fill_ts in range(int(last_ts) + 1000, int(current_ts), 1000):
                                price_history.append((fill_ts, prev_valid_price))
                
                # P0修复: 先append当前秒的mid，再计算return_1s
                price_history.append((second_ts * 1000, mid))
                # 只保留最近2秒的数据
                self._price_history[symbol] = [p for p in price_history if p[0] >= (second_ts - 1) * 1000]
            
            # Compute features (with return_1s and lag calculation)
            # P0修复: 传入prev_mid用于return_1s计算（当前秒已append，使用[-2]和[-1]）
            prev_mid = None
            if symbol and symbol in self._price_history:
                price_history = self._price_history[symbol]
                if len(price_history) >= 2:
                    prev_mid = price_history[-2][1]  # 上一秒的mid
            
            feature_row = self._compute_features(price, ob, second_ts, prev_mid, is_gap_second)
            if feature_row:
                self.stats["aligned_rows"] += 1
                
                # P1: 统计gap秒数
                if is_gap_second:
                    self.stats["gap_seconds_count"] += 1
                
                # P1: 统计lag_bad（在_compute_features中已设置）
                if feature_row.get("lag_bad_price", 0) == 1:
                    self.stats["lag_bad_price_count"] += 1
                if feature_row.get("lag_bad_orderbook", 0) == 1:
                    self.stats["lag_bad_orderbook_count"] += 1
                
                yield feature_row
    
    def _find_latest(self, buffer: Dict[int, Dict[str, Any]], target_second: int, max_lag_seconds: int) -> Optional[Dict[str, Any]]:
        """Find latest data within max_lag_seconds"""
        for lag in range(1, max_lag_seconds + 1):
            ts = target_second - lag
            if ts in buffer:
                return buffer[ts]
        return None
    
    def _compute_features(self, price: Dict[str, Any], orderbook: Dict[str, Any], second_ts: int, prev_mid: Optional[float] = None, is_gap_second: bool = False) -> Optional[Dict[str, Any]]:
        """Compute features from aligned price and orderbook data
        
        P0修复: 接收prev_mid参数，避免时序偏移
        P0修复: 修复真假值判断（0值误判问题）
        P0修复: 修复lag_ms计算口径（使用该行的ts_ms与对齐秒边界）
        """
        try:
            symbol = price.get("symbol") or orderbook.get("symbol")
            if not symbol:
                return None
            
            # P0修复: 修复真假值判断（0值误判问题）
            mid = price.get("mid")
            if mid is None:
                mid = price.get("price")
            if mid is None or mid <= 0:
                return None
            
            # P0修复: 修复真假值判断（0值误判问题）
            # 修复：优先从orderbook_buf新增字段读取，如果没有则从bids/asks现算
            best_bid = orderbook.get("best_bid")
            if best_bid is None:
                best_bid = orderbook.get("bid_price")
            best_ask = orderbook.get("best_ask")
            if best_ask is None:
                best_ask = orderbook.get("ask_price")
            
            # 兜底：如果字段缺失，从bids/asks现算
            if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
                bids = orderbook.get("bids", [])
                asks = orderbook.get("asks", [])
                if bids and len(bids) > 0 and bids[0][0] > 0:
                    best_bid = bids[0][0]
                if asks and len(asks) > 0 and asks[0][0] > 0:
                    best_ask = asks[0][0]
            
            if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
                return None
            
            # 重新计算mid（如果之前没有）
            if mid is None or mid <= 0:
                mid = (best_bid + best_ask) / 2 if (best_bid > 0 and best_ask > 0) else 0.0
            
            # Compute spread_bps（优先从orderbook读取，如果没有则现算）
            spread_bps = orderbook.get("spread_bps")
            if spread_bps is None or spread_bps == 0.0:
                spread_bps = ((best_ask - best_bid) / mid) * 10000 if mid > 0 else 0.0
            
            # P0: 细化scenario_2x2标签
            # A/Q: 活跃度代理（每秒quote更新或trades/min）
            # H/L: 波动或spread中位数分位判断（≥p75记H，否则L）
            # 代码.4: 使用配置的阈值
            # P0修复: 计算return_1s（使用传入的prev_mid，避免时序偏移）
            return_1s = 0.0
            if prev_mid is not None and prev_mid > 0:
                return_1s = ((mid - prev_mid) / prev_mid) * 10000  # bps
            
            # P1-1: Aligner场景判定微调（is_active用spread，is_high_vol仅用return_1s）
            # 解耦A/Q与H/L两条轴，避免边界重叠
            is_active = spread_bps > self.spread_threshold  # A/Q轴：仅用spread判断活跃度
            is_high_vol = abs(return_1s) >= self.volatility_threshold  # H/L轴：仅用return_1s判断波动
            
            # A_H/A_L/Q_H/Q_L
            if is_active:
                scenario = "A_H" if is_high_vol else "A_L"
            else:
                scenario = "Q_H" if is_high_vol else "Q_L"
            
            # P0修复: 计算lag_ms_*（使用该行的ts_ms与对齐秒边界计算，而非全局last_obs_ts）
            # P1: 增加lag_bad标志位（用于gating统计归因）
            current_ts_ms = second_ts * 1000
            # P0修复: 使用该行的ts_ms与对齐秒边界计算滞后
            price_ts_ms = price.get("ts_ms", 0)
            ob_ts_ms = orderbook.get("ts_ms", 0)
            lag_ms_price = max(0, current_ts_ms - price_ts_ms) if price_ts_ms > 0 else 0
            lag_ms_orderbook = max(0, current_ts_ms - ob_ts_ms) if ob_ts_ms > 0 else 0
            
            # P1: lag_bad标志位（lag超过阈值时标记）
            # 代码.4: 使用配置的阈值
            lag_bad_price = 1 if lag_ms_price > self.lag_threshold_ms else 0
            lag_bad_orderbook = 1 if lag_ms_orderbook > self.lag_threshold_ms else 0
            
            # Build feature row (matching CORE_ALGO REQUIRED_FIELDS)
            # CORE_ALGO requires: ts_ms, symbol, z_ofi, z_cvd, spread_bps, lag_sec, consistency, warmup
            # P0-3: 添加vol_bps = abs(return_1s)，供线性/分段滑点模型读取
            vol_bps = abs(return_1s)
            
            feature_row = {
                "second_ts": second_ts,
                "ts_ms": second_ts * 1000,
                "symbol": symbol,
                "mid": mid,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_bps": spread_bps,
                "scenario_2x2": scenario,
                # P0: 填补关键特征
                "return_1s": return_1s,  # 已计算
                "vol_bps": vol_bps,  # P0-3: 新增vol_bps字段，供滑点模型读取
                "lag_ms_price": lag_ms_price,  # 已计算（保留用于诊断）
                "lag_ms_orderbook": lag_ms_orderbook,  # 已计算（保留用于诊断）
                # CORE_ALGO required fields
                "z_ofi": price.get("ofi_z") or price.get("z_ofi", 0.0),  # CORE_ALGO expects z_ofi
                "z_cvd": price.get("cvd_z") or price.get("z_cvd", 0.0),  # CORE_ALGO expects z_cvd
                "lag_sec": max(lag_ms_price, lag_ms_orderbook) / 1000.0 if lag_ms_price > 0 or lag_ms_orderbook > 0 else 0.0,  # Convert ms to seconds
                "lag_bad_price": lag_bad_price,  # P1: lag超过阈值标志位
                "lag_bad_orderbook": lag_bad_orderbook,  # P1: lag超过阈值标志位
                "is_gap_second": 1 if is_gap_second else 0,  # P1: gap秒标志位
                # P0修复: 修复真假值判断（0值误判问题）
                "consistency": price.get("consistency") if price.get("consistency") is not None else (orderbook.get("consistency") if orderbook.get("consistency") is not None else 0.0),
                "warmup": price.get("warmup") if price.get("warmup") is not None else (orderbook.get("warmup") if orderbook.get("warmup") is not None else False),
                # P1: 如果可获取，直接透传OFI/CVD/Fusion（保留别名）
                "ofi_z": price.get("ofi_z") or price.get("z_ofi", 0.0),
                "cvd_z": price.get("cvd_z") or price.get("z_cvd", 0.0),
                "fusion_score": price.get("fusion_score", 0.0),
            }
            
            return feature_row
        except Exception as e:
            logger.error(f"Error computing features: {e}", exc_info=True)
            return None
    
    def get_stats(self) -> Dict:
        """Get alignment statistics
        
        P1: 可观测性补完 - 添加aligner_gap_seconds统计
        """
        stats = dict(self.stats)
        # P1: 计算gap秒数比例（确保字段存在）
        gap_count = stats.get("gap_seconds_count", 0)
        lag_bad_price_count = stats.get("lag_bad_price_count", 0)
        lag_bad_orderbook_count = stats.get("lag_bad_orderbook_count", 0)
        aligned_rows = stats.get("aligned_rows", 0)
        
        if aligned_rows > 0:
            stats["gap_seconds_rate"] = gap_count / aligned_rows
            stats["lag_bad_price_rate"] = lag_bad_price_count / aligned_rows
            stats["lag_bad_orderbook_rate"] = lag_bad_orderbook_count / aligned_rows
        else:
            stats["gap_seconds_rate"] = 0.0
            stats["lag_bad_price_rate"] = 0.0
            stats["lag_bad_orderbook_rate"] = 0.0
        
        # 确保字段存在（即使为0）
        stats["gap_seconds_count"] = gap_count
        stats["lag_bad_price_count"] = lag_bad_price_count
        stats["lag_bad_orderbook_count"] = lag_bad_orderbook_count
        
        # P0-3: 计算平均观测间隔（obs_gap_ms）诊断指标
        obs_gap_price_sum = sum(self._obs_gap_sum[s]["price"] for s in self._obs_gap_sum)
        obs_gap_price_count = sum(self._obs_gap_count[s]["price"] for s in self._obs_gap_count)
        obs_gap_orderbook_sum = sum(self._obs_gap_sum[s]["orderbook"] for s in self._obs_gap_sum)
        obs_gap_orderbook_count = sum(self._obs_gap_count[s]["orderbook"] for s in self._obs_gap_count)
        
        stats["obs_gap_ms_price_avg"] = obs_gap_price_sum / obs_gap_price_count if obs_gap_price_count > 0 else 0.0
        stats["obs_gap_ms_orderbook_avg"] = obs_gap_orderbook_sum / obs_gap_orderbook_count if obs_gap_orderbook_count > 0 else 0.0
        
        return stats

