# -*- coding: utf-8 -*-
"""T08.3: Feeder - Drive CORE_ALGO in replay mode"""
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterator, Optional
from collections import deque, defaultdict

from alpha_core.signals.core_algo import CoreAlgorithm, build_sink

logger = logging.getLogger(__name__)

class ReplayFeeder:
    """Feed historical data to CORE_ALGO in replay mode"""
    
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        output_dir: Optional[Path] = None,
        sink_kind: str = "jsonl",
    ):
        """
        Args:
            config: Signal configuration (merged with defaults)
            output_dir: Output directory for signals
            sink_kind: Sink type (jsonl/sqlite/null)
        """
        # Ensure replay_mode is enabled
        if config is None:
            config = {}
        config["replay_mode"] = 1
        
        # Set environment variable for CORE_ALGO
        os.environ["V13_REPLAY_MODE"] = "1"
        
        # Build sink
        base_dir = Path(output_dir or config.get("output_dir", "./runtime"))
        sink = build_sink(sink_kind, base_dir)
        
        # Initialize CORE_ALGO
        self.algo = CoreAlgorithm(config=config, sink=sink, output_dir=base_dir)
        
        # P2修复: 打印生效参数快照（用于对比search space覆盖是否成功）
        self._log_effective_params(config)
        
        # TASK09X: 活动度字段注入器（用于回放时计算trade_rate和quote_rate）
        self._activity_injector = ActivityInjector()
        
        logger.info(f"[ReplayFeeder] Initialized with sink={sink_kind}, replay_mode=1")
    
    def _log_effective_params(self, config: Dict[str, Any]) -> None:
        """P2修复: 打印生效参数快照
        
        打印CoreAlgorithm/融合模块的关键阈值，用于对比search space覆盖是否成功
        """
        effective_params = {}
        
        # 信号阈值
        thresholds = config.get("thresholds", {})
        active_thresholds = thresholds.get("active", {})
        effective_params["signal.thresholds.active.buy"] = active_thresholds.get("buy")
        effective_params["signal.thresholds.active.sell"] = active_thresholds.get("sell")
        
        # 一致性阈值
        effective_params["signal.consistency_min"] = config.get("consistency_min")
        effective_params["signal.weak_signal_threshold"] = config.get("weak_signal_threshold")
        
        # 融合权重和参数（从components.fusion获取）
        components = config.get("components", {})
        fusion_config = components.get("fusion", {})
        effective_params["components.fusion.w_ofi"] = fusion_config.get("w_ofi")
        effective_params["components.fusion.w_cvd"] = fusion_config.get("w_cvd")
        effective_params["components.fusion.adaptive_cooldown_k"] = fusion_config.get("adaptive_cooldown_k")
        effective_params["components.fusion.flip_rearm_margin"] = fusion_config.get("flip_rearm_margin")
        
        # 打印生效参数
        logger.info("[ReplayFeeder] 生效参数快照:")
        for key, value in effective_params.items():
            if value is not None:
                logger.info(f"  {key} = {value}")
        
        # 保存到实例变量，供后续使用
        self.effective_params = effective_params
    
    def feed_features(self, features: Iterator[Dict[str, Any]]) -> int:
        """Feed features to CORE_ALGO and return signal count
        
        P1: 传递feature数据到signal，用于gate_reason_breakdown汇总Aligner质量位
        TASK09X: 注入活动度字段（trade_rate和quote_rate）
        """
        signal_count = 0
        
        for feature_row in features:
            try:
                # 字段名标准化：将ofi_z/cvd_z映射到z_ofi/z_cvd（兼容不同数据格式）
                normalized_row = dict(feature_row)
                if "ofi_z" in normalized_row and "z_ofi" not in normalized_row:
                    normalized_row["z_ofi"] = normalized_row["ofi_z"]
                if "cvd_z" in normalized_row and "z_cvd" not in normalized_row:
                    normalized_row["z_cvd"] = normalized_row["cvd_z"]
                
                # TASK09X: 注入活动度字段（如果缺失）
                ts_ms = normalized_row.get("ts_ms")
                symbol = normalized_row.get("symbol", "")
                if ts_ms and symbol:
                    # Features文件中的每一行通常同时包含orderbook和trade信息
                    # 因为features是按秒聚合的数据
                    # 我们假设每个feature行都代表一次数据更新（包含orderbook和trade）
                    has_orderbook = any(k in normalized_row for k in ["best_bid", "best_ask", "spread_bps"])
                    has_trade = any(k in normalized_row for k in ["mid", "return_1s", "price", "z_ofi", "z_cvd"])
                    
                    # 如果字段已存在，跳过注入；否则注入
                    if "trade_rate" not in normalized_row or "quote_rate" not in normalized_row:
                        activity_fields = self._activity_injector.inject(
                            symbol=symbol,
                            ts_ms=ts_ms,
                            has_orderbook=has_orderbook,
                            has_trade=has_trade
                        )
                        # 只注入缺失的字段
                        for key, value in activity_fields.items():
                            if key not in normalized_row:
                                normalized_row[key] = value
                
                # P0修复: 注入固定lag_sec（用于强制触发lag检查）
                if hasattr(self.algo, 'config') and self.algo.config.get("inject_lag_sec") is not None:
                    inject_lag = self.algo.config.get("inject_lag_sec")
                    normalized_row["lag_sec"] = inject_lag
                    logger.debug(f"[ReplayFeeder] Injected lag_sec={inject_lag} for lag trigger test")
                
                # Process feature row
                signal = self.algo.process_feature_row(normalized_row)
                if signal:
                    # P1: 将feature数据附加到signal，用于TradeSim汇总Aligner质量位
                    # P1增强: 传递市场上下文（spread/vol/scenario/fee_tier/session）用于情境化滑点和费用
                    # P1-2: 统一在_feature_data中显式包含return_1s
                    signal["_feature_data"] = {
                        "lag_bad_price": feature_row.get("lag_bad_price", 0),
                        "lag_bad_orderbook": feature_row.get("lag_bad_orderbook", 0),
                        "is_gap_second": feature_row.get("is_gap_second", 0),
                        # P1增强: 市场上下文
                        "spread_bps": feature_row.get("spread_bps"),
                        "vol_bps": feature_row.get("vol_bps"),  # 如果有vol_bps字段
                        "scenario_2x2": feature_row.get("scenario_2x2"),
                        "fee_tier": feature_row.get("fee_tier"),
                        "session": feature_row.get("session"),
                        "return_1s": feature_row.get("return_1s"),  # P1-2: 显式包含return_1s
                    }
                    signal_count += 1
            except Exception as e:
                logger.error(f"Error processing feature row: {e}", exc_info=True)
                continue
        
        logger.info(f"[ReplayFeeder] Processed features, generated {signal_count} signals")
        return signal_count
    
    def close(self) -> None:
        """Close the feeder and flush remaining signals"""
        if hasattr(self.algo, "_sink") and self.algo._sink:
            self.algo._sink.close()
        logger.info("[ReplayFeeder] Closed")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        stats_dict = {}
        if hasattr(self.algo, "_stats"):
            stats = self.algo._stats
            emitted = stats.emitted
            stats_dict = {
                "processed": stats.processed,
                "emitted": emitted,
                "signals_emitted": emitted,  # P0-5: 添加signals_emitted别名，避免Pushgateway取不到字段
                "suppressed": stats.suppressed,
                "deduplicated": stats.deduplicated,
            }
        
        # P1: 添加sink健康度指标
        if hasattr(self.algo, "_sink") and self.algo._sink:
            if hasattr(self.algo._sink, "get_health"):
                try:
                    sink_health = self.algo._sink.get_health()
                    stats_dict["sink_health"] = sink_health
                except Exception as e:
                    logger.warning(f"[ReplayFeeder] Failed to get sink health: {e}")
        
        return stats_dict


class ActivityInjector:
    """活动度字段注入器（用于回放时计算trade_rate和quote_rate）"""
    
    def __init__(self):
        # 每个symbol维护一个滑动窗口（60秒）
        self.trade_windows: Dict[str, deque] = defaultdict(lambda: deque(maxlen=3000))
        self.quote_windows: Dict[str, deque] = defaultdict(lambda: deque(maxlen=6000))
    
    def inject(
        self,
        symbol: str,
        ts_ms: int,
        has_orderbook: bool = False,
        has_trade: bool = False
    ) -> Dict[str, Any]:
        """注入活动度字段
        
        Args:
            symbol: 交易对
            ts_ms: 时间戳（毫秒）
            has_orderbook: 是否包含orderbook更新
            has_trade: 是否包含trade更新
        
        Returns:
            包含trade_rate和quote_rate的字典
        """
        result = {}
        
        # 更新窗口
        if has_orderbook:
            self.quote_windows[symbol].append(ts_ms)
        if has_trade:
            self.trade_windows[symbol].append(ts_ms)
        
        # 计算trade_rate（每分钟交易数）
        trade_window = self.trade_windows[symbol]
        # 修剪过期数据（保留最近60秒）
        while trade_window and (ts_ms - trade_window[0]) > 60000:
            trade_window.popleft()
        trade_count = len(trade_window)
        trade_rate = (trade_count / 60.0) * 60.0 if trade_count > 0 else 0.0  # trades per minute
        
        # 计算quote_rate（每秒报价更新数）
        quote_window = self.quote_windows[symbol]
        # 修剪过期数据（保留最近60秒）
        while quote_window and (ts_ms - quote_window[0]) > 60000:
            quote_window.popleft()
        quote_count = len(quote_window)
        quote_rate = (quote_count / 60.0) if quote_count > 0 else 0.0  # updates per second
        
        # 如果字段已存在，不覆盖；否则注入
        result["trade_rate"] = trade_rate
        result["quote_rate"] = quote_rate
        result["trades_per_min"] = trade_rate  # 别名
        result["quote_updates_per_sec"] = quote_rate  # 别名
        
        return result

