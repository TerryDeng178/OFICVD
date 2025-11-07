# -*- coding: utf-8 -*-
"""CORE_ALGO signal service.

This module consumes FeaturePipe output rows, applies configurable guards, and
emits trading signals to pluggable sinks (JSONL / SQLite / Null).

The implementation is intentionally lightweight: Feature calculations already
happen upstream (TASK-04).  Here we focus on:
  * contract validation & deduplication
  * regime-aware score thresholds
  * guard reasons (warmup / spread / lag / consistency / weak signal)
  * sink abstraction that matches the JSONL / SQLite DoD in TASK-05
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    from alpha_core.risk.strategy_mode import StrategyModeManager, MarketActivity
    STRATEGY_MODE_AVAILABLE = True
except ImportError:
    STRATEGY_MODE_AVAILABLE = False

logger = logging.getLogger(__name__)
if not STRATEGY_MODE_AVAILABLE:
    logger.warning("StrategyModeManager not available, falling back to simple regime inference")

REQUIRED_FIELDS: List[str] = [
    "ts_ms",
    "symbol",
    "z_ofi",
    "z_cvd",
    "spread_bps",
    "lag_sec",
    "consistency",
    "warmup",
]

DEFAULT_SIGNAL_CONFIG: Dict[str, Any] = {
    "dedupe_ms": 250,
    "weak_signal_threshold": 0.2,
    "consistency_min": 0.15,
    # 分模式/分场景的一致性阈值（优先级高于 consistency_min）
    "consistency_min_per_regime": {
        "active": 0.10,
        "quiet": 0.15
    },
    "spread_bps_cap": 20.0,
    "lag_cap_sec": 3.0,
    "weights": {"w_ofi": 0.6, "w_cvd": 0.4},
    "activity": {"active_min_tps": 3.0, "normal_min_tps": 1.0},
    # P0: consistency 保守底座配置（略微抬高）
    "consistency_floor": 0.10,
    "consistency_floor_when_abs_score_ge": 0.45,  # 从 0.40 提升到 0.45
    "consistency_floor_on_divergence": 0.15,  # 从 0.12 提升到 0.15
    "thresholds": {
        "base": {"buy": 0.6, "strong_buy": 1.2, "sell": -0.6, "strong_sell": -1.2},
        "active": {"buy": 0.5, "strong_buy": 1.0, "sell": -0.5, "strong_sell": -1.0},
        "quiet": {"buy": 0.7, "strong_buy": 1.4, "sell": -0.7, "strong_sell": -1.4},
    },
    "sink": {"kind": "jsonl", "output_dir": "./runtime"},
}


def _merge_dict(base: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not override:
        return dict(base)
    merged: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass
class SignalStats:
    processed: int = 0
    emitted: int = 0
    suppressed: int = 0
    deduplicated: int = 0
    warmup_blocked: int = 0


class SignalSink:
    """Sink interface for downstream persistence."""

    def emit(self, entry: Dict[str, Any]) -> None:
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - default no-op
        return None

    def get_health(self) -> Dict[str, Any]:  # pragma: no cover - default no-op
        return {}


class NullSink(SignalSink):
    def emit(self, entry: Dict[str, Any]) -> None:  # pragma: no cover - trivial
        return None


class JsonlSink(SignalSink):
    """Append-only JSONL sink matching TASK-05 contract."""

    def __init__(self, base_dir: Path, fsync_every_n: int = 50) -> None:
        self.base_dir = Path(base_dir)
        self.ready_root = self.base_dir / "ready" / "signal"
        self.ready_root.mkdir(parents=True, exist_ok=True)
        # P0: JSONL Writer 的 fsync 频率改为可配置
        # 引入 FSYNC_EVERY_N 环境变量（默认 50），在后台线程场景下按批次 fsync
        self.fsync_every_n = int(os.getenv("FSYNC_EVERY_N", str(fsync_every_n)))
        self._write_count = 0

    def emit(self, entry: Dict[str, Any]) -> None:
        ts_ms = int(entry["ts_ms"])
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        minute = dt.strftime("%Y%m%d_%H%M")
        symbol = entry.get("symbol", "UNKNOWN")
        target_dir = self.ready_root / symbol
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f"signals_{minute}.jsonl"
        serialized = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        
        # P0: 按批次 fsync，兼顾数据安全与性能
        with target_file.open("a", encoding="utf-8") as fp:
            fp.write(serialized + "\n")
            self._write_count += 1
            # 每 N 次写入执行一次 fsync
            if self._write_count >= self.fsync_every_n:
                fp.flush()
                os.fsync(fp.fileno())
                self._write_count = 0
            else:
                # 仍然 flush，但不 fsync（减少系统调用）
                fp.flush()

    def get_health(self) -> Dict[str, Any]:
        return {"kind": "jsonl", "base_dir": str(self.base_dir)}


class SqliteSink(SignalSink):
    """SQLite sink (WAL) with async batch processing for better throughput."""

    def __init__(self, base_dir: Path, batch_n: int = 500, flush_ms: int = 500) -> None:
        base_dir = Path(base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = base_dir / "signals.db"
        self.conn = sqlite3.connect(self.db_path)
        # P1: SQLite 性能优化，减少"吞吐差"
        # 启用 WAL 模式、降低同步级别、使用内存临时存储、增大缓存
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA temp_store=MEMORY;")
        self.conn.execute("PRAGMA cache_size=-20000;")  # 约 80MB
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                ts_ms INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                score REAL,
                z_ofi REAL,
                z_cvd REAL,
                regime TEXT,
                div_type TEXT,
                signal_type TEXT,
                confirm INTEGER,
                gating INTEGER,
                guard_reason TEXT,
                created_at TEXT DEFAULT (DATETIME('now')),
                PRIMARY KEY (ts_ms, symbol)
            );
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, ts_ms);"
        )
        self.conn.commit()
        
        # P0: 统一并默认启用"异步批量 SQLite Sink"
        # 队列+批量 executemany，显著缩小 JSONL vs SQLite 的吞吐差
        self.batch_n = int(os.getenv("SQLITE_BATCH_N", str(batch_n)))
        self.flush_ms = int(os.getenv("SQLITE_FLUSH_MS", str(flush_ms)))
        self._batch_queue: List[tuple] = []
        self._last_flush_time = time.time()
        self._lock = threading.Lock()

    def emit(self, entry: Dict[str, Any]) -> None:
        payload = (
            int(entry["ts_ms"]),
            entry.get("symbol"),
            entry.get("score"),
            entry.get("z_ofi"),
            entry.get("z_cvd"),
            entry.get("regime"),
            entry.get("div_type"),
            entry.get("signal_type"),
            1 if entry.get("confirm") else 0,
            1 if entry.get("gating") else 0,
            entry.get("guard_reason"),
        )
        
        # P0: 批量处理模式
        with self._lock:
            self._batch_queue.append(payload)
            current_time = time.time()
            should_flush = (
                len(self._batch_queue) >= self.batch_n or
                (current_time - self._last_flush_time) * 1000 >= self.flush_ms
            )
            
            if should_flush:
                self._flush_batch()
    
    def _flush_batch(self) -> None:
        """批量写入数据库"""
        if not self._batch_queue:
            return
        
        try:
            # 使用 executemany 批量插入
            self.conn.executemany(
                "INSERT OR REPLACE INTO signals (ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, signal_type, confirm, gating, guard_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?);",
                self._batch_queue,
            )
            self.conn.commit()
            self._batch_queue.clear()
            self._last_flush_time = time.time()
        except Exception as e:
            logger.error(f"SQLite batch flush failed: {e}")
            # 失败时清空队列，避免数据堆积
            self._batch_queue.clear()
    
    def close(self) -> None:
        """关闭时刷新剩余批次"""
        with self._lock:
            if self._batch_queue:
                self._flush_batch()
        if self.conn:
            self.conn.close()

    def get_health(self) -> Dict[str, Any]:
        return {"kind": "sqlite", "path": str(self.db_path)}


class MultiSink(SignalSink):
    """同时写入多个 Sink（用于双 Sink 等价性测试）"""
    
    def __init__(self, sinks: List[SignalSink]) -> None:
        self.sinks = sinks
    
    def emit(self, entry: Dict[str, Any]) -> None:
        for sink in self.sinks:
            sink.emit(entry)
    
    def close(self) -> None:
        for sink in self.sinks:
            sink.close()
    
    def get_health(self) -> Dict[str, Any]:
        return {
            "kind": "multi",
            "sinks": [sink.get_health() for sink in self.sinks]
        }


def build_sink(kind: str, output_dir: Path) -> SignalSink:
    kind = (kind or "jsonl").lower()
    if kind == "sqlite":
        return SqliteSink(output_dir)
    if kind == "null":
        return NullSink()
    if kind == "dual":
        # P0: 双 Sink 模式（同时写入 JSONL 和 SQLite）
        return MultiSink([JsonlSink(output_dir), SqliteSink(output_dir)])
    return JsonlSink(output_dir)


class CoreAlgorithm:
    """Process FeaturePipe rows and emit signals to sinks."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        sink: Optional[SignalSink] = None,
        *,
        sink_kind: Optional[str] = None,
        output_dir: Optional[str | Path] = None,
    ) -> None:
        self.config = _merge_dict(DEFAULT_SIGNAL_CONFIG, config or {})
        sink_cfg = self.config.get("sink", {})
        base_dir = Path(output_dir or sink_cfg.get("output_dir", "./runtime"))
        if sink is None:
            sink = build_sink(sink_kind or sink_cfg.get("kind", "jsonl"), base_dir)
        self._sink = sink
        self._base_dir = base_dir
        self._stats = SignalStats()
        self._last_ts_per_symbol: Dict[str, int] = {}
        
        # P0: StrategyMode 可观测性（每 10s 心跳快照）
        self._last_strategy_mode_log_per_symbol: Dict[str, int] = {}
        self._strategy_mode_log_interval_ms = 10000  # 10 seconds
        
        # P0: SMOKE 兜底：用特征行到达率估算 tps（仅当缺少 trade_rate/quote_rate）
        from collections import deque
        self._arrival_ts_window: Dict[str, deque] = {}  # symbol -> deque of ts_ms
        self._arrival_window_ms = 60000  # 60 seconds
        
        # Initialize StrategyModeManager if available
        self._strategy_mode_managers: Dict[str, StrategyModeManager] = {}
        if STRATEGY_MODE_AVAILABLE:
            strategy_cfg = self.config.get("strategy_mode", {})
            if strategy_cfg:
                # Create a shared config dict for StrategyModeManager
                triggers_cfg = strategy_cfg.get("triggers", {})
                market_cfg = triggers_cfg.get("market", {})
                manager_config = {
                    "strategy": {
                        "mode": strategy_cfg.get("mode", "auto"),
                        "hysteresis": strategy_cfg.get("hysteresis", {
                            "window_secs": 60,
                            "min_active_windows": 2,
                            "min_quiet_windows": 4,
                        }),
                        "triggers": {
                            "combine_logic": triggers_cfg.get("combine_logic", "OR"),
                            # P0: 默认开启 schedule，空窗口=全天有效（配合 StrategyModeManager 实现）
                            "schedule": triggers_cfg.get("schedule", {"enabled": True, "active_windows": []}),
                            "market": {
                                "enabled": market_cfg.get("enabled", True),
                                "window_secs": market_cfg.get("window_secs", 60),
                                "basic_gate_multiplier": market_cfg.get("basic_gate_multiplier", 0.5),
                                "min_trades_per_min": market_cfg.get("min_trades_per_min", 30),
                                "min_quote_updates_per_sec": market_cfg.get("min_quote_updates_per_sec", 5),
                                "max_spread_bps": market_cfg.get("max_spread_bps", 15),
                                "min_volatility_bps": market_cfg.get("min_volatility_bps", 0.5),
                                "min_volume_usd": market_cfg.get("min_volume_usd", 10000),
                                "use_median": market_cfg.get("use_median", True),
                                "winsorize_percentile": market_cfg.get("winsorize_percentile", 95),
                            },
                        },
                    },
                }
                # Store config for per-symbol initialization
                self._strategy_mode_config = manager_config
                logger.info(f"[StrategyMode] Config loaded: mode={strategy_cfg.get('mode')}, "
                           f"schedule_enabled={triggers_cfg.get('schedule', {}).get('enabled')}, "
                           f"market_enabled={market_cfg.get('enabled')}, "
                           f"basic_gate_multiplier={market_cfg.get('basic_gate_multiplier', 0.5)}")
            else:
                self._strategy_mode_config = None
                logger.debug("[StrategyMode] No strategy_mode config found, using fallback")

    @property
    def stats(self) -> SignalStats:
        return self._stats

    def close(self) -> None:
        if self._sink:
            self._sink.close()

    def process_feature_row(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._validate_row(row):
            return None

        ts_ms = int(row["ts_ms"])
        symbol = str(row["symbol"])

        if self._is_duplicate(symbol, ts_ms):
            return None

        self._stats.processed += 1

        score = self._resolve_score(row)
        # 处理 None 值（Parquet 文件可能包含 None）
        consistency_val = row.get("consistency")
        spread_bps_val = row.get("spread_bps")
        lag_sec_val = row.get("lag_sec")
        consistency = float(consistency_val if consistency_val is not None else 0.0)
        spread_bps = float(spread_bps_val if spread_bps_val is not None else 0.0)
        lag_sec = float(lag_sec_val if lag_sec_val is not None else 0.0)
        warmup = bool(row.get("warmup", False))
        reason_codes = row.get("reason_codes", []) or []
        
        # P0: consistency 保守底座（避免 93% 被 low_consistency 一刀切）
        if consistency <= 0.0:
            consistency_floor_when_abs_score_ge = self.config.get("consistency_floor_when_abs_score_ge", 0.4)
            consistency_floor = self.config.get("consistency_floor", 0.10)
            consistency_floor_on_divergence = self.config.get("consistency_floor_on_divergence", 0.12)
            
            if abs(score) >= consistency_floor_when_abs_score_ge:
                consistency = max(consistency, consistency_floor)
            elif row.get("div_type"):  # 出现任何背离信号
                consistency = max(consistency, consistency_floor_on_divergence)

        regime = self._infer_regime(row)
        thresholds = self._thresholds_for_regime(regime)
        
        # 分模式/分场景的一致性阈值（优先级高于全局 consistency_min）
        consistency_min_per_regime = self.config.get("consistency_min_per_regime", {})
        if consistency_min_per_regime and regime in consistency_min_per_regime:
            effective_consistency_min = consistency_min_per_regime[regime]
        else:
            effective_consistency_min = self.config["consistency_min"]

        gating_reasons: List[str] = []
        if warmup:
            gating_reasons.append("warmup")
            self._stats.warmup_blocked += 1
        if spread_bps > self.config["spread_bps_cap"]:
            gating_reasons.append(f"spread_bps>{self.config['spread_bps_cap']}")
        if lag_sec > self.config["lag_cap_sec"]:
            gating_reasons.append(f"lag_sec>{self.config['lag_cap_sec']}")
        if consistency < effective_consistency_min:
            gating_reasons.append("low_consistency")
        if abs(score) < self.config["weak_signal_threshold"] and not warmup:
            gating_reasons.append("weak_signal")
        if reason_codes:
            gating_reasons.extend(f"reason:{code}" for code in reason_codes)

        candidate_direction = 0
        if score >= thresholds["buy"]:
            candidate_direction = 1
        elif score <= thresholds["sell"]:
            candidate_direction = -1

        confirm = candidate_direction != 0 and not gating_reasons
        signal_type = "neutral"
        if confirm:
            if candidate_direction > 0:
                signal_type = "strong_buy" if score >= thresholds["strong_buy"] else "buy"
            else:
                signal_type = "strong_sell" if score <= thresholds["strong_sell"] else "sell"
        elif candidate_direction != 0:
            signal_type = "pending"

        decision = {
            "ts_ms": ts_ms,
            "symbol": symbol,
            "score": score,
            "z_ofi": row.get("z_ofi"),
            "z_cvd": row.get("z_cvd"),
            "regime": regime,
            "div_type": row.get("div_type"),
            "confirm": confirm,
            "gating": bool(gating_reasons),
            "signal_type": signal_type,
            "guard_reason": ",".join(gating_reasons) if gating_reasons else None,  # 保存所有原因（逗号分隔）
        }

        if confirm:
            self._stats.emitted += 1
        else:
            self._stats.suppressed += 1

        try:
            self._sink.emit(decision)
        except Exception:  # pragma: no cover - robust against sink errors
            logger.exception("failed to emit signal for %s", symbol)

        return decision

    def process_rows(self, rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        emitted: List[Dict[str, Any]] = []
        for row in rows:
            decision = self.process_feature_row(row)
            if decision is not None:
                emitted.append(decision)
        return emitted

    def _validate_row(self, row: Dict[str, Any]) -> bool:
        missing = [field for field in REQUIRED_FIELDS if field not in row]
        if missing:
            logger.warning("feature row missing fields: %s", missing)
            return False
        return True

    def _is_duplicate(self, symbol: str, ts_ms: int) -> bool:
        last_ts = self._last_ts_per_symbol.get(symbol)
        if last_ts is not None:
            if abs(ts_ms - last_ts) < self.config["dedupe_ms"]:
                self._stats.deduplicated += 1
                return True
        self._last_ts_per_symbol[symbol] = ts_ms
        return False

    def _resolve_score(self, row: Dict[str, Any]) -> float:
        score = row.get("fusion_score")
        if score is not None:
            return float(score)
        w_ofi = self.config["weights"].get("w_ofi", 0.6)
        w_cvd = self.config["weights"].get("w_cvd", 0.4)
        # 处理 None 值（Parquet 文件可能包含 None）
        z_ofi_val = row.get("z_ofi")
        z_cvd_val = row.get("z_cvd")
        ofi = float(z_ofi_val if z_ofi_val is not None else 0.0)
        cvd = float(z_cvd_val if z_cvd_val is not None else 0.0)
        return w_ofi * ofi + w_cvd * cvd

    def _get_strategy_mode_manager(self, symbol: str) -> Optional[StrategyModeManager]:
        """Get or create StrategyModeManager for a symbol."""
        if not STRATEGY_MODE_AVAILABLE or not self._strategy_mode_config:
            return None
        if symbol not in self._strategy_mode_managers:
            self._strategy_mode_managers[symbol] = StrategyModeManager(
                runtime_cfg=self._strategy_mode_config
            )
            logger.debug(f"[StrategyMode] Created manager for {symbol}")
        return self._strategy_mode_managers[symbol]

    def _create_market_activity(self, row: Dict[str, Any]) -> Optional[MarketActivity]:
        """Create MarketActivity from FeatureRow."""
        if not STRATEGY_MODE_AVAILABLE:
            return None
        
        activity = MarketActivity()
        
        # P0: 优先使用 FeaturePipe 提供的真实活动度字段
        # Extract trade_rate (trades per minute)
        trade_rate = row.get("trade_rate")
        if trade_rate is not None and trade_rate > 0:
            activity.trades_per_min = float(trade_rate)
        else:
            # Fallback: 从 activity.tps 推导
            activity_data = row.get("activity", {})
            tps = activity_data.get("tps")
            if tps is not None and tps > 0:
                activity.trades_per_min = float(tps) * 60.0
            else:
                # P0: 兜底：用"特征行到达率"估算（SMOKE/预览场景）
                symbol = str(row.get("symbol", "UNK"))
                ts_ms = int(row.get("ts_ms", 0))
                if ts_ms > 0:
                    from collections import deque
                    dq = self._arrival_ts_window.setdefault(symbol, deque(maxlen=6000))
                    dq.append(ts_ms)
                    # 修剪 60s 窗口
                    while dq and (ts_ms - dq[0]) > self._arrival_window_ms:
                        dq.popleft()
                    if len(dq) > 1:
                        secs = max(1.0, (dq[-1] - dq[0]) / 1000.0)
                        est_tps = (len(dq) - 1) / secs
                        activity.trades_per_min = est_tps * 60.0
                    else:
                        activity.trades_per_min = 0.0
                else:
                    activity.trades_per_min = 0.0
        
        # Extract quote_rate (quote updates per second)
        quote_rate = row.get("quote_rate")
        if quote_rate is not None and quote_rate > 0:
            activity.quote_updates_per_sec = float(quote_rate)
        else:
            # P0: 兜底：经验比率（避免 0 触发器）
            activity.quote_updates_per_sec = max(activity.trades_per_min / 60.0 * 2.0, 0.5)
        
        # Extract spread_bps
        spread_bps = row.get("spread_bps")
        if spread_bps is not None and spread_bps > 0:
            activity.spread_bps = float(spread_bps)
        else:
            # Default to a reasonable spread if not available
            activity.spread_bps = 2.0  # 2 bps is reasonable for major pairs
        
        # Extract volatility_bps (realized_vol_bps)
        realized_vol = row.get("realized_vol_bps")
        if realized_vol is not None and realized_vol > 0:
            activity.volatility_bps = float(realized_vol)
        else:
            # Fallback: Estimate from z_ofi/z_cvd
            # 处理 None 值（Parquet 文件可能包含 None）
            z_ofi_val = row.get("z_ofi")
            z_cvd_val = row.get("z_cvd")
            z_ofi = abs(float(z_ofi_val if z_ofi_val is not None else 0.0))
            z_cvd = abs(float(z_cvd_val if z_cvd_val is not None else 0.0))
            activity.volatility_bps = max(z_ofi, z_cvd) * 3.0 + 1.0  # Minimum 1 bps
        
        # Extract volume_usd
        volume_usd = row.get("volume_usd")
        if volume_usd is not None and volume_usd > 0:
            activity.volume_usd = float(volume_usd)
        else:
            # Fallback: Estimate from trade_rate
            if activity.trades_per_min > 0:
                activity.volume_usd = max(activity.trades_per_min * 2000.0, 10000.0)
            else:
                activity.volume_usd = 0.0
        
        return activity

    def _infer_regime(self, row: Dict[str, Any]) -> str:
        """Infer regime using StrategyModeManager if available, otherwise fallback to simple logic."""
        symbol = str(row.get("symbol", "UNKNOWN"))
        ts_ms = int(row.get("ts_ms", 0))
        
        # Try using StrategyModeManager
        manager = self._get_strategy_mode_manager(symbol)
        if manager:
            activity = self._create_market_activity(row)
            if activity:
                try:
                    manager.update_mode(activity)
                    current_mode = manager.get_current_mode()
                    
                    # P0: 调试日志（每 1000 行打印一次）
                    if self._stats.processed % 1000 == 0:
                        mode_stats = manager.get_mode_stats()
                        triggers = manager._get_trigger_snapshot(activity)
                        logger.debug(
                            f"[StrategyMode Debug] {symbol} @ {ts_ms}: "
                            f"mode={current_mode.value}, "
                            f"trades/min={activity.trades_per_min:.1f}, "
                            f"quotes/sec={activity.quote_updates_per_sec:.1f}, "
                            f"spread_bps={activity.spread_bps:.2f}, "
                            f"volatility_bps={activity.volatility_bps:.2f}, "
                            f"volume_usd={activity.volume_usd:.0f}, "
                            f"schedule_active={triggers.get('schedule_active', False)}, "
                            f"market_active={triggers.get('market_active', False)}, "
                            f"history_size={len(manager.activity_history)}"
                        )
                    
                    # P0: StrategyMode 可观测性日志（每 10s 心跳快照）
                    # P1: JSON 格式便于后续用 jq 汇总分析
                    last_log_ts = self._last_strategy_mode_log_per_symbol.get(symbol, 0)
                    if ts_ms - last_log_ts >= self._strategy_mode_log_interval_ms:
                        mode_stats = manager.get_mode_stats()
                        triggers = manager._get_trigger_snapshot(activity)
                        snapshot = {
                            "ts_ms": ts_ms,
                            "symbol": symbol,
                            "mode": current_mode.value,
                            "trades_per_min": round(activity.trades_per_min, 1),
                            "quotes_per_sec": round(activity.quote_updates_per_sec, 1),
                            "spread_bps": round(activity.spread_bps, 2),
                            "volatility_bps": round(activity.volatility_bps, 2),
                            "volume_usd": round(activity.volume_usd, 0),
                            "schedule_active": triggers.get("schedule_active", False),
                            "market_active": triggers.get("market_active", False),
                            "history_size": len(manager.activity_history),
                        }
                        logger.info(f"[StrategyMode] {json.dumps(snapshot, ensure_ascii=False)}")
                        self._last_strategy_mode_log_per_symbol[symbol] = ts_ms
                    
                    regime_map = {"active": "active", "quiet": "quiet"}
                    regime = regime_map.get(current_mode.value, "normal")
                    return regime
                except Exception:
                    logger.exception("Failed to update StrategyModeManager, falling back")
        
        # Fallback to simple logic
        activity_data = row.get("activity", {})
        tps = activity_data.get("tps")
        if tps is None:
            trade_rate = row.get("trade_rate")
            tps = (float(trade_rate) / 60.0) if trade_rate is not None else None
        if tps is None:
            return "normal"
        active_min = self.config["activity"].get("active_min_tps", 3.0)
        normal_min = self.config["activity"].get("normal_min_tps", 1.0)
        if tps >= active_min:
            return "active"
        if tps >= normal_min:
            return "normal"
        return "quiet"

    def _thresholds_for_regime(self, regime: str) -> Dict[str, float]:
        thresholds = self.config["thresholds"]
        regime = regime or "base"
        regime_cfg = thresholds.get(regime, {})
        base_cfg = thresholds.get("base", {})
        return _merge_dict(base_cfg, regime_cfg)
