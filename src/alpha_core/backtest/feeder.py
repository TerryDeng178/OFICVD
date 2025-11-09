# -*- coding: utf-8 -*-
"""T08.3: Feeder - Drive CORE_ALGO in replay mode"""
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

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
        
        logger.info(f"[ReplayFeeder] Initialized with sink={sink_kind}, replay_mode=1")
    
    def feed_features(self, features: Iterator[Dict[str, Any]]) -> int:
        """Feed features to CORE_ALGO and return signal count
        
        P1: 传递feature数据到signal，用于gate_reason_breakdown汇总Aligner质量位
        """
        signal_count = 0
        
        for feature_row in features:
            try:
                # Process feature row
                signal = self.algo.process_feature_row(feature_row)
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

