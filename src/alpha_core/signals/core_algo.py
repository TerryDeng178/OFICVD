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
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# TASK-A4: 导入 signal/v2 相关组件
try:
    from .decision_engine import DecisionEngine
    from .signal_writer import SignalWriterV2
    from .signal_schema import SignalV2, SideHint, Regime, DecisionCode, DivType
    from .config_hash import calculate_config_hash, extract_core_config
    SIGNAL_V2_AVAILABLE = True
except ImportError:
    DecisionEngine = None
    SignalWriterV2 = None
    SignalV2 = None
    SideHint = None
    Regime = None
    DecisionCode = None
    DivType = None
    calculate_config_hash = None
    extract_core_config = None
    SIGNAL_V2_AVAILABLE = False

# TASK-A4 修复: logger 提前定义，避免在 ImportError 分支中使用未定义的 logger
import logging
logger = logging.getLogger(__name__)

# 导入Fusion引擎用于consistency计算
try:
    from alpha_core.microstructure.fusion import OFI_CVD_Fusion, OFICVDFusionConfig
    FUSION_AVAILABLE = True
except ImportError:
    OFI_CVD_Fusion = None
    OFICVDFusionConfig = None
    FUSION_AVAILABLE = False
    logger.warning("[CoreAlgorithm] Fusion engine not available for consistency calculation")

# 如果 v2 组件不可用，记录警告
if not SIGNAL_V2_AVAILABLE:
    logger.warning("[CoreAlgorithm] Signal v2 components not available, falling back to v1")

# P0: 三级回退导入（alpha_core → 本地 → 不可用）
try:
    from alpha_core.risk.strategy_mode import StrategyModeManager, StrategyMode, MarketActivity
    STRATEGY_MODE_AVAILABLE = True
except Exception:
    try:
        from strategy_mode_manager import StrategyModeManager, StrategyMode, MarketActivity
        STRATEGY_MODE_AVAILABLE = True
    except Exception:
        StrategyModeManager = None
        StrategyMode = None
        MarketActivity = None
        STRATEGY_MODE_AVAILABLE = False
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
    "strong_threshold": 0.8,  # Phase C: strong 档位阈值（|score| >= 0.8）
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

    # TASK_CONFIRM_PIPELINE_TUNING: Phase A - 确认漏斗诊断统计
    # 漏斗各层通过计数
    total_signals: int = 0
    pass_weak_signal_filter: int = 0
    pass_consistency_filter: int = 0
    candidate_confirm_true: int = 0
    reverse_prevention_blocked: int = 0
    confirm_true: int = 0

    # TASK_CONFIRM_PIPELINE_TUNING: Phase C - 质量分档统计
    # strong/normal/weak 分档计数
    strong_tier_signals: int = 0
    normal_tier_signals: int = 0
    weak_tier_signals: int = 0
    # 各档位确认统计
    strong_tier_confirm: int = 0
    normal_tier_confirm: int = 0
    weak_tier_confirm: int = 0


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
        self._last_minute = None  # P0: 跟踪上一个文件的minute，用于检测文件切换
        
        # P0.5: 启动时打印最终生效的fsync策略，便于复现与比对
        logger.info(f"[JsonlSink] fsync策略: every_n={self.fsync_every_n}（每{self.fsync_every_n}次写入执行一次fsync）")

    def emit(self, entry: Dict[str, Any]) -> None:
        # P0: 在JSONL中追加run_id字段，用于按run_id对账
        # P1: 统一run_id贯穿JSONL/SQLite，确保JSONL包含所有必需字段（signal_type、created_at）
        # 强制从环境变量读取run_id（覆盖entry中可能存在的空值）
        run_id_env = os.getenv("RUN_ID", "")
        # 始终设置run_id字段（即使环境变量为空，也要写入字段）
        entry["run_id"] = run_id_env
        
        # P1: 确保signal_type字段存在（与SQLite对齐）
        if "signal_type" not in entry:
            entry["signal_type"] = "neutral"
        
        # P1: 确保created_at字段存在（与SQLite对齐）
        if "created_at" not in entry:
            entry["created_at"] = datetime.now(timezone.utc).isoformat()
        
        ts_ms = int(entry["ts_ms"])
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        # P0 修复5: JSONL 命名/轮转与路径风格统一 - 统一到 v2 风格（小时轮转、连字符）
        hour_str = dt.strftime("%Y%m%d-%H")
        symbol = entry.get("symbol", "UNKNOWN")
        target_dir = self.ready_root / symbol
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f"signals-{hour_str}.jsonl"
        
        # P0: 添加水印字段，用于验证是否使用了CORE_ALGO的JsonlSink
        entry.setdefault("_writer", "core_jsonl_v406")
        
        # TASK-A4 修复6: 稳定序列化统一，JSONL 写入统一 sort_keys=True
        serialized = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        
        # TASK-A4 修复2: 按批次 fsync，仅在达到阈值或小时轮转时 fsync
        # 移除收尾兜底 fsync，避免每条写入都 fsync（抵消批量策略）
        # P0 修复5: 统一到小时轮转（与 v2 风格一致）
        prev_hour = getattr(self, '_last_minute', None)  # 保持变量名兼容，但实际是小时
        current_hour = hour_str
        
        # 如果文件切换（小时轮转），对上一个文件执行补偿 fsync
        if prev_hour is not None and prev_hour != current_hour:
            prev_file = target_dir / f"signals-{prev_hour}.jsonl"
            if prev_file.exists():
                try:
                    with prev_file.open("r+b") as prev_fp:
                        prev_fp.flush()
                        os.fsync(prev_fp.fileno())
                except Exception as e:
                    logger.warning(f"[JsonlSink] Failed to fsync previous file {prev_file}: {e}")
        
        with target_file.open("a", encoding="utf-8") as fp:
            fp.write(serialized + "\n")
            self._write_count += 1
            
            # TASK-A4 修复2: 只在达到阈值时 fsync，移除收尾兜底 fsync
            if self._write_count >= self.fsync_every_n:
                fp.flush()
                os.fsync(fp.fileno())
                self._write_count = 0
            else:
                # 仍然 flush，但不 fsync（减少系统调用）
                fp.flush()
        
        self._last_minute = current_hour  # P0 修复5: 实际存储的是小时字符串

    def close(self) -> None:
        """P0: 关闭时清理状态"""
        # 由于JsonlSink每次emit都打开和关闭文件，且在文件关闭前已fsync
        # 这里只需要清理状态
        if self._write_count > 0:
            logger.warning(f"[JsonlSink] 关闭时检测到未fsync的写入计数: {self._write_count}（应在emit中处理）")
        self._write_count = 0
        self._last_minute = None
    
    def get_health(self) -> Dict[str, Any]:
        """P1: 返回健康度指标（目前JsonlSink无队列，返回基础信息）"""
        return {
            "kind": "jsonl",
            "base_dir": str(self.base_dir),
            "queue_size": 0,  # JsonlSink无队列
            "dropped_count": 0,  # JsonlSink无dropped计数
        }


class SqliteSink(SignalSink):
    """SQLite sink (WAL) with async batch processing for better throughput."""

    def __init__(self, base_dir: Path, batch_n: int = None, flush_ms: int = None) -> None:
        # TASK-07A: 支持环境变量调参，便于在不同盘型/Windows上调优批量提交
        if batch_n is None:
            batch_n = int(os.getenv("SQLITE_BATCH_N", "500"))
        if flush_ms is None:
            flush_ms = int(os.getenv("SQLITE_FLUSH_MS", "500"))
        base_dir = Path(base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = base_dir / "signals.db"
        
        # P0.5: 启动时打印最终生效的批量参数，便于复现与比对
        logger.info(f"[SqliteSink] 批量参数: batch_n={batch_n}, flush_ms={flush_ms}ms")
        
        self.conn = sqlite3.connect(self.db_path)
        # P1: SQLite 性能优化，减少"吞吐差"
        # 启用 WAL 模式、降低同步级别、使用内存临时存储、增大缓存
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA temp_store=MEMORY;")
        self.conn.execute("PRAGMA cache_size=-20000;")  # 约 20MB（负值单位是KB，20000 KB = 20 MB）
        
        # P0: 检查并迁移旧版表结构到统一版本（(run_id, ts_ms, symbol)主键）
        self._migrate_schema_if_needed()
        
        # P2: 模块导入时自检：PRAGMA table_info(signals) 缺列就迁移
        # 确保表结构符合统一版本（(run_id, ts_ms, symbol)主键，12+列含run_id）
        # 允许同一毫秒多次回放/多次测试而不互相覆盖
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
                run_id TEXT NOT NULL,
                created_at TEXT DEFAULT (DATETIME('now')),
                PRIMARY KEY (run_id, ts_ms, symbol)
            );
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, ts_ms);"
        )
        # TASK-07B: 设置busy_timeout，减少写锁报错
        self.conn.execute("PRAGMA busy_timeout=5000;")
        self.conn.commit()
        
        # P2: 自检表结构，确保符合统一版本（仅在表存在时检查，避免影响新表创建）
        # 注意：这个检查在_migrate_schema_if_needed()之后执行，主要用于验证迁移结果
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signals'")
            if cursor.fetchone():
                # 表存在，进行验证
                cursor.execute("PRAGMA table_info(signals)")
                columns = {row[1]: row[2] for row in cursor.fetchall()}
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='signals'")
                table_sql_result = cursor.fetchone()
                table_sql = (table_sql_result[0] if table_sql_result else "") or ""
                ddl_upper = table_sql.upper()
                
                # 检查主键是否为(run_id, ts_ms, symbol)
                has_pk_run_ts_symbol = (
                    "PRIMARY KEY" in ddl_upper and 
                    "RUN_ID" in ddl_upper and 
                    "TS_MS" in ddl_upper and 
                    "SYMBOL" in ddl_upper
                )
                
                # 检查必需列
                required_columns = ["ts_ms", "symbol", "score", "signal_type", "confirm", "gating", "guard_reason", "run_id", "created_at"]
                missing_columns = [col for col in required_columns if col not in columns]
                
                if has_pk_run_ts_symbol and not missing_columns:
                    logger.debug("[SqliteSink] 表结构验证通过：符合统一版本（(run_id, ts_ms, symbol)主键）")
                else:
                    logger.warning(f"[SqliteSink] 表结构验证：主键={has_pk_run_ts_symbol}, 缺失列={missing_columns}（已由_migrate_schema_if_needed处理）")
        except Exception as e:
            # 自检失败不影响正常功能，只记录警告
            logger.warning(f"[SqliteSink] 表结构自检失败（可忽略）: {e}")
        
        # P0: 统一并默认启用"异步批量 SQLite Sink"
        # 队列+批量 executemany，显著缩小 JSONL vs SQLite 的吞吐差
        # TASK-07B: 修复环境变量读取逻辑，确保env优先于参数
        if batch_n is None:
            batch_n = int(os.getenv("SQLITE_BATCH_N", "500"))
        if flush_ms is None:
            flush_ms = int(os.getenv("SQLITE_FLUSH_MS", "500"))
        self.batch_n = batch_n
        self.flush_ms = flush_ms
        self._batch_queue: List[tuple] = []
        # P1: 添加dropped计数（用于健康度指标）
        self._dropped_count = 0
        # TASK-07B: 初始化_last_flush_time为0，确保第一次emit时立即刷新（如果flush_ms>0）
        # 如果flush_ms=0，会在emit中特殊处理
        self._last_flush_time = 0.0  # 初始化为0，确保第一次刷新立即触发
        self._lock = threading.Lock()
        
        # TASK-07B: SQLite初始化时打印关键参数，便于验证环境变量是否生效
        env_source = "env" if os.getenv("SQLITE_BATCH_N") or os.getenv("SQLITE_FLUSH_MS") else "default"
        logger.info(
            f"[SqliteSink] 初始化完成: "
            f"db_path={self.db_path}, "
            f"journal_mode=WAL, "
            f"synchronous=NORMAL, "
            f"batch_n={self.batch_n} (来源: {env_source}), "
            f"flush_ms={self.flush_ms}ms (来源: {env_source})"
        )
    
    def _migrate_schema_if_needed(self) -> None:
        """P0: 迁移旧版表结构到统一版本（(run_id, ts_ms, symbol)主键）"""
        try:
            cursor = self.conn.cursor()
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signals'")
            if not cursor.fetchone():
                # 表不存在，直接创建新表（统一版本）
                return
            
            # 检查现有列
            cursor.execute("PRAGMA table_info(signals)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            
            # 检查主键类型
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='signals'")
            result = cursor.fetchone()
            table_sql = (result[0] if result else "") or ""
            ddl_upper = table_sql.upper()
            
            # P0: 检查主键类型
            has_pk_run_ts_symbol = (
                "PRIMARY KEY" in ddl_upper and 
                "RUN_ID" in ddl_upper and 
                "TS_MS" in ddl_upper and 
                "SYMBOL" in ddl_upper
            )
            has_pk_ts_symbol = (
                "PRIMARY KEY" in ddl_upper and 
                "TS_MS" in ddl_upper and 
                "SYMBOL" in ddl_upper and
                "RUN_ID" not in ddl_upper
            )
            has_pk_id_autoincrement = (
                "PRIMARY KEY" in ddl_upper and 
                "AUTOINCREMENT" in ddl_upper
            )
            
            needs_column_migration = False
            
            # 检查缺失的列
            if "signal_type" not in columns:
                cursor.execute("ALTER TABLE signals ADD COLUMN signal_type TEXT")
                needs_column_migration = True
                logger.info("[SqliteSink] 迁移：添加signal_type列")
            
            if "guard_reason" not in columns:
                cursor.execute("ALTER TABLE signals ADD COLUMN guard_reason TEXT")
                needs_column_migration = True
                logger.info("[SqliteSink] 迁移：添加guard_reason列")
            
            if "created_at" not in columns:
                cursor.execute("ALTER TABLE signals ADD COLUMN created_at TEXT DEFAULT (DATETIME('now'))")
                needs_column_migration = True
                logger.info("[SqliteSink] 迁移：添加created_at列")
            
            # P0: 检查run_id列（用于按run_id对账）
            if "run_id" not in columns:
                cursor.execute("ALTER TABLE signals ADD COLUMN run_id TEXT")
                needs_column_migration = True
                logger.info("[SqliteSink] 迁移：添加run_id列")
            
            # P0: 如果主键不是(run_id, ts_ms, symbol)，需要重建表
            # P2: 同时检查是否有遗留的id列（AUTOINCREMENT），需要移除
            if not has_pk_run_ts_symbol or has_pk_id_autoincrement:
                logger.warning("[SqliteSink] 迁移：检测到旧主键或遗留id列，将重建为 PRIMARY KEY(run_id, ts_ms, symbol)")
                self.conn.execute("BEGIN IMMEDIATE")
                try:
                    # 1) 创建新表（统一主键版本，无id列）
                    self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS signals_new (
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
                        run_id TEXT NOT NULL,
                        created_at TEXT DEFAULT (DATETIME('now')),
                        PRIMARY KEY (run_id, ts_ms, symbol)
                    );
                    """)
                    
                    # 2) 数据搬迁（保留所有数据，run_id设为空字符串如果为NULL，排除id列）
                    self.conn.execute("""
                    INSERT OR IGNORE INTO signals_new (ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, signal_type, confirm, gating, guard_reason, run_id, created_at)
                    SELECT ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, 
                           COALESCE(signal_type, NULL) AS signal_type,
                           confirm, gating, guard_reason, 
                           COALESCE(run_id, '') AS run_id,
                           COALESCE(created_at, DATETIME('now')) AS created_at
                    FROM signals
                    """)
                    
                    # 3) 替换旧表
                    self.conn.execute("DROP TABLE signals")
                    self.conn.execute("ALTER TABLE signals_new RENAME TO signals")
                    self.conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, ts_ms)")
                    self.conn.commit()
                    logger.info("[SqliteSink] 迁移完成：signals 使用 PRIMARY KEY(run_id, ts_ms, symbol)，已移除遗留id列")
                except Exception as e:
                    self.conn.rollback()
                    logger.error(f"[SqliteSink] 主键迁移失败: {e}", exc_info=True)
                    raise
            elif needs_column_migration:
                self.conn.commit()
                logger.info("[SqliteSink] 表结构迁移完成（列添加）")
                
        except Exception as e:
            logger.error(f"[SqliteSink] 表结构迁移失败: {e}", exc_info=True)

    def emit(self, entry: Dict[str, Any]) -> None:
        # P0: 从环境变量读取run_id，用于按run_id对账
        run_id = os.getenv("RUN_ID", "")
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
            run_id,
        )
        
        # P0: 批量处理模式
        # TASK-07B: 修复批量刷新逻辑，确保batch_n=1和flush_ms=0时立即刷新
        with self._lock:
            self._batch_queue.append(payload)
            current_time = time.time()
            # 修复：如果flush_ms=0，应该立即刷新（不考虑时间间隔）
            time_elapsed_ms = (current_time - self._last_flush_time) * 1000 if self.flush_ms > 0 else float('inf')
            should_flush = (
                len(self._batch_queue) >= self.batch_n or
                time_elapsed_ms >= self.flush_ms
            )
            
            if should_flush:
                self._flush_batch()
    
    def _flush_batch(self) -> None:
        """批量写入数据库"""
        if not self._batch_queue:
            return
        
        batch_size = len(self._batch_queue)
        try:
            # P0: 使用INSERT OR IGNORE，避免主键冲突导致整批失败
            # 主键(run_id, ts_ms, symbol)允许同一毫秒多次回放/多次测试而不互相覆盖
            # P1: executemany批量提交的异常保护（重试+补偿）
            self.conn.executemany(
                "INSERT OR IGNORE INTO signals (ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, signal_type, confirm, gating, guard_reason, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?);",
                self._batch_queue,
            )
            self.conn.commit()
            flushed_count = len(self._batch_queue)
            self._batch_queue.clear()
            self._last_flush_time = time.time()
            # TASK-07B: 添加批量刷新日志（短跑场景下总是输出，便于调试）
            if batch_size >= 10 or os.getenv("SQLITE_DEBUG", "0") == "1" or self.batch_n <= 10:
                logger.info(f"[SqliteSink] 批量刷新: {flushed_count}条数据已写入数据库（batch_n={self.batch_n}, flush_ms={self.flush_ms}ms）")
        except (sqlite3.IntegrityError, sqlite3.OperationalError, Exception) as e:
            logger.error(f"[SqliteSink] 批量刷新失败: {e}", exc_info=True)
            # P1: 失败时不丢弃，加入退避重试与本地补偿文件
            # 重试3次
            retry_count = 0
            max_retries = 3
            while retry_count < max_retries:
                try:
                    time.sleep(0.1 * (retry_count + 1))  # 退避：0.1s, 0.2s, 0.3s
                    self.conn.executemany(
                        "INSERT OR IGNORE INTO signals (ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, signal_type, confirm, gating, guard_reason, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?);",
                        self._batch_queue,
                    )
                    self.conn.commit()
                    logger.info(f"[SqliteSink] 批量刷新重试成功（第{retry_count + 1}次）")
                    flushed_count = len(self._batch_queue)
                    self._batch_queue.clear()
                    self._last_flush_time = time.time()
                    if batch_size >= 10 or os.getenv("SQLITE_DEBUG", "0") == "1" or self.batch_n <= 10:
                        logger.info(f"[SqliteSink] 批量刷新: {flushed_count}条数据已写入数据库（重试后）")
                    return
                except Exception as retry_e:
                    retry_count += 1
                    logger.warning(f"[SqliteSink] 批量刷新重试失败（第{retry_count}次）: {retry_e}")
            
            # 重试失败，写入补偿文件
            # P0 修复4: 失败批次补偿文件写入当前 output_dir（而非固定 runtime）
            failed_batch_file = self.base_dir / "failed_batches.jsonl"
            try:
                with failed_batch_file.open("a", encoding="utf-8", newline="") as f:
                    for payload in self._batch_queue:
                        # 将payload转换为字典格式写入
                        record = {
                            "ts_ms": payload[0],
                            "symbol": payload[1],
                            "score": payload[2],
                            "z_ofi": payload[3],
                            "z_cvd": payload[4],
                            "regime": payload[5],
                            "div_type": payload[6],
                            "signal_type": payload[7],
                            "confirm": payload[8],
                            "gating": payload[9],
                            "guard_reason": payload[10],
                            "run_id": payload[11] if len(payload) > 11 else "",
                        }
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                logger.error(f"[SqliteSink] 批量刷新失败，已写入补偿文件: {failed_batch_file} ({batch_size}条)")
            except Exception as save_e:
                logger.error(f"[SqliteSink] 写入补偿文件失败: {save_e}", exc_info=True)
            
            # 清空队列（已保存到补偿文件）
            # P1: 记录dropped计数
            self._dropped_count += batch_size
            self._batch_queue.clear()
    
    def close(self) -> None:
        """关闭时刷新剩余批次（确保所有队列数据写入数据库）"""
        # TASK-07B: 增强关闭流程，确保批量队列正确刷新
        try:
            queue_size = 0
            with self._lock:
                queue_size = len(self._batch_queue)
                if queue_size > 0:
                    logger.info(f"[SqliteSink] 关闭时刷新剩余批次: {queue_size}条数据")
                    self._flush_batch()
                else:
                    logger.debug("[SqliteSink] 关闭时批量队列为空，无需刷新")
            
            if self.conn:
                # TASK-07B: 执行WAL检查点，确保数据可见
                try:
                    self.conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
                    logger.debug("[SqliteSink] WAL检查点完成")
                except Exception as e:
                    logger.warning(f"[SqliteSink] WAL检查点失败: {e}")
                
                self.conn.close()
                # P0: SQLite关闭路径再确认：先刷剩余批次→checkpoint→close，并打印实际flush数
                logger.info(f"[SqliteSink] 关闭完成：已刷新剩余批次{queue_size}条数据，WAL检查点已执行，数据库连接已关闭")
        except Exception as e:
            logger.error(f"[SqliteSink] 关闭时出错: {e}", exc_info=True)

    def get_health(self) -> Dict[str, Any]:
        """P1: 返回健康度指标（queue_size, dropped_count）"""
        with self._lock:
            queue_size = len(self._batch_queue)
        return {
            "kind": "sqlite",
            "path": str(self.db_path),
            "queue_size": queue_size,
            "dropped_count": self._dropped_count,
        }


class MultiSink(SignalSink):
    """同时写入多个 Sink（用于双 Sink 等价性测试）"""
    
    def __init__(self, sinks: List[SignalSink]) -> None:
        self.sinks = sinks
    
    def emit(self, entry: Dict[str, Any]) -> None:
        # P0: 固定MultiSink顺序与数据一致性（每个子Sink独立副本，避免字段被"串改"）
        # 在循环内copy，确保每个子Sink都有独立的entry副本
        for sink in self.sinks:
            sink.emit(entry.copy())
    
    def close(self) -> None:
        """TASK-07A: 确保所有Sink正确关闭（只调用标准接口，不访问私有属性）
        
        TASK-07B修复: 优化关闭顺序，先关闭SQLite（确保提交），再关闭JSONL（确保rotate）
        这样可以减少关闭时序race导致的数据不一致
        """
        # TASK-07B: 先关闭SQLite（确保数据提交），再关闭JSONL（确保文件rotate）
        # 这样可以减少关闭时序race导致的数据不一致
        sqlite_sinks = [s for s in self.sinks if isinstance(s, SqliteSink)]
        jsonl_sinks = [s for s in self.sinks if isinstance(s, JsonlSink)]
        other_sinks = [s for s in self.sinks if s not in sqlite_sinks + jsonl_sinks]
        
        # 关闭顺序：其他Sink -> SQLite -> JSONL
        for sink in other_sinks + sqlite_sinks + jsonl_sinks:
            try:
                # 只调用标准接口，让每个Sink的close()自行处理内部刷新逻辑
                sink.close()
            except Exception as e:
                logger.error(f"关闭sink失败: {e}", exc_info=True)
    
    def get_health(self) -> Dict[str, Any]:
        """TASK-07A: 返回MultiSink的健康状态（包含子sink信息）"""
        sinks_info = []
        for sink in self.sinks:
            if hasattr(sink, 'get_health'):
                sinks_info.append(sink.get_health())
            else:
                sinks_info.append({"kind": type(sink).__name__.lower().replace('sink', '')})
        return {
            "kind": "multi",
            "sinks": sinks_info
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
        raw_cfg = config or {}

        # 如果是"总 config + signal 小节"的风格，则优先使用 signal 小节作为 Core 的配置
        # 条件：存在 raw_cfg["signal"]，且顶层没有显式传入 weak_signal_threshold / consistency_min 等
        if (
            isinstance(raw_cfg, dict)
            and "signal" in raw_cfg
            and not any(
                k in raw_cfg
                for k in (
                    "weak_signal_threshold",
                    "consistency_min",
                    "consistency_min_per_regime",
                    "thresholds",
                    "sink",
                    "activity",
                )
            )
        ):
            effective_cfg = dict(raw_cfg["signal"])  # 拿 signal 小节作为 core 的配置起点

            # 把跟 Core 相关的其他段落"抄"进来（strategy_mode / strategy / 版本信息等）
            for extra_key in ("strategy_mode", "strategy", "rules_ver", "features_ver"):
                if extra_key in raw_cfg and extra_key not in effective_cfg:
                    effective_cfg[extra_key] = raw_cfg[extra_key]
        else:
            # 兼容旧调用：直接认为整个 config 就是 Core 的配置
            effective_cfg = raw_cfg

        # 真正生效的配置 = 默认 + 用户覆写
        self.config = _merge_dict(DEFAULT_SIGNAL_CONFIG, effective_cfg)

        # 临时日志：验证配置生效（用于调试 config["signal"] 生效问题）
        logger.info(
            f"[CoreAlgorithm] thresholds: weak={self.config.get('weak_signal_threshold', 'NOT_SET')}, "
            f"consistency_min={self.config.get('consistency_min', 'NOT_SET')}, "
            f"strong_threshold={self.config.get('strong_threshold', 'NOT_SET')}, "
            f"confirm_mode={self.config.get('confirm_mode', 'NOT_SET')}"
        )
        logger.info(f"[CoreAlgorithm] config keys: {list(self.config.keys())}")

        sink_cfg = self.config.get("sink", {})
        base_dir = Path(output_dir or sink_cfg.get("output_dir", "./runtime"))
        
        # TASK-A4: 初始化 signal/v2 组件（如果可用）
        # 支持从 core.use_signal_v2 或顶层 use_signal_v2 读取
        use_signal_v2_config = self.config.get("use_signal_v2") or self.config.get("core", {}).get("use_signal_v2") or os.getenv("V13_SIGNAL_V2") == "1"
        self._use_v2 = SIGNAL_V2_AVAILABLE and bool(use_signal_v2_config)
        
        # TASK-A4 修复1: 启用 v2 时，不构建旧 _sink，避免双写路径不一致
        if self._use_v2:
            # v2 路径：只使用 SignalWriterV2
            self._sink = None
            logger.info("[CoreAlgorithm] Signal v2 enabled: skipping legacy sink initialization")
            
            # 提取 core.* 配置
            core_config = extract_core_config(self.config) if extract_core_config else {}
            
            # 初始化 Decision Engine（会应用 ENV 覆盖）
            self._decision_engine = DecisionEngine(core_config) if DecisionEngine else None
            
            # TASK-A4 修复5: 从实际 sink 对象映射到 sink_kind_v2（如果传入了外部 sink）
            if sink is not None:
                # 从 sink 对象推断类型
                sink_class_name = type(sink).__name__
                if "Jsonl" in sink_class_name or "jsonl" in sink_class_name.lower():
                    sink_kind_v2 = "jsonl"
                elif "Sqlite" in sink_class_name or "sqlite" in sink_class_name.lower():
                    sink_kind_v2 = "sqlite"
                elif "Multi" in sink_class_name or "dual" in sink_class_name.lower():
                    sink_kind_v2 = "dual"
                else:
                    sink_kind_v2 = "dual"  # 默认 dual
                logger.info(f"[CoreAlgorithm] Inferred sink_kind_v2={sink_kind_v2} from sink class {sink_class_name}")
            else:
                # 从配置推断
                final_sink_kind = sink_kind or sink_cfg.get("kind") or os.getenv("V13_SINK") or "dual"
                sink_kind_v2 = final_sink_kind
                logger.info(f"[CoreAlgorithm] Using sink_kind_v2={sink_kind_v2} from config/env")
            
            # 初始化 SignalWriterV2
            self._signal_writer_v2 = SignalWriterV2(base_dir, sink_kind=sink_kind_v2) if SignalWriterV2 else None
            
            # TASK-A4 修复4: 计算 config_hash（使用生效后的配置，包含 ENV 覆盖）
            # P1 修复4: config_hash 纳入规则版本和特征版本因子（rules_ver + features_ver）
            if self._decision_engine:
                # 获取生效后的配置（包含 ENV 覆盖）
                effective_config = self._decision_engine.get_effective_config()
                # 获取规则版本和特征版本（从配置或环境变量）
                rules_ver = os.getenv("CORE_RULES_VER", self.config.get("rules_ver", "core v1"))
                features_ver = os.getenv("CORE_FEATURES_VER", self.config.get("features_ver", "ofi/cvd v3"))
                # 将 rules_ver 和 features_ver 纳入哈希计算（确保一致性）
                effective_config_with_versions = effective_config.copy()
                effective_config_with_versions["rules_ver"] = rules_ver
                effective_config_with_versions["features_ver"] = features_ver
                self._config_hash = calculate_config_hash(effective_config_with_versions) if calculate_config_hash else "unknown"
            else:
                rules_ver = os.getenv("CORE_RULES_VER", self.config.get("rules_ver", "core v1"))
                features_ver = os.getenv("CORE_FEATURES_VER", self.config.get("features_ver", "ofi/cvd v3"))
                core_config_with_versions = core_config.copy()
                core_config_with_versions["rules_ver"] = rules_ver
                core_config_with_versions["features_ver"] = features_ver
                self._config_hash = calculate_config_hash(core_config_with_versions) if calculate_config_hash else "unknown"
            
            # 生成 run_id（如果环境变量未设置）
            self._run_id = os.getenv("RUN_ID", f"r{str(uuid.uuid4())[:8]}")
            # 信号序列号（用于 signal_id）
            self._signal_seq: Dict[str, int] = {}  # symbol -> seq
            logger.info(f"[CoreAlgorithm] Signal v2 enabled: config_hash={self._config_hash}, run_id={self._run_id}")
        else:
            # v1 路径：使用旧 sink
            # P0: 统一Sink选择口径（优先级：CLI/构造参数 > 配置 > 环境 > 默认）
            if sink is None:
                # 优先级：sink_kind参数 > config.sink.kind > V13_SINK环境变量 > 默认jsonl
                final_sink_kind = sink_kind or sink_cfg.get("kind") or os.getenv("V13_SINK") or "jsonl"
                sink = build_sink(final_sink_kind, base_dir)
                # P0: 启动时明确打印最终生效值
                logger.info(f"[CoreAlgorithm] Sink选择: sink_kind={sink_kind}, config.kind={sink_cfg.get('kind')}, V13_SINK={os.getenv('V13_SINK')}, 最终生效={final_sink_kind}")
            self._sink = sink
            # P0: 打印实际使用的sink类名，用于验证是否使用了CORE_ALGO的sink
            sink_class_name = type(self._sink).__name__
            logger.info(f"[CoreAlgorithm] sink_used={sink_class_name}")
            if sink_class_name == "MultiSink":
                # MultiSink: 打印子sink信息
                if hasattr(self._sink, 'sinks'):
                    for i, sub_sink in enumerate(self._sink.sinks):
                        sub_class_name = type(sub_sink).__name__
                        logger.info(f"[CoreAlgorithm]  子Sink[{i}]: {sub_class_name}")
            
            self._decision_engine = None
            self._signal_writer_v2 = None
            self._config_hash = None
            self._run_id = None
        
        self._base_dir = base_dir
        self._stats = SignalStats()
        self._last_ts_per_symbol: Dict[str, int] = {}
        
        # P0修复: B组回测端重算融合 + 连击确认
        self.recompute_fusion = bool(self.config.get("recompute_fusion", False))
        self.min_consecutive_same_dir = int(self.config.get("min_consecutive_same_dir", 1))
        # 方向streak跟踪: symbol -> (direction, count)
        self._dir_streak_state: Dict[str, tuple] = {}  # symbol -> (last_direction, consecutive_count)

        # TASK-CORE-CONFIRM: 初始化Fusion引擎用于consistency计算
        self._fusion_engine = None
        if FUSION_AVAILABLE and OFICVDFusionConfig is not None:
            try:
                # 从配置中获取fusion参数
                fusion_cfg = self.config.get("components", {}).get("fusion", {})
                fusion_config = OFICVDFusionConfig(
                    w_ofi=fusion_cfg.get("w_ofi", 0.6),
                    w_cvd=fusion_cfg.get("w_cvd", 0.4),
                    fuse_buy=fusion_cfg.get("fuse_buy", 0.95),
                    fuse_strong_buy=fusion_cfg.get("fuse_strong_buy", 1.70),
                    fuse_sell=fusion_cfg.get("fuse_sell", -0.95),
                    fuse_strong_sell=fusion_cfg.get("fuse_strong_sell", -1.70),
                    min_consistency=fusion_cfg.get("min_consistency", 0.15),
                    strong_min_consistency=fusion_cfg.get("strong_min_consistency", 0.6)
                )
                self._fusion_engine = OFI_CVD_Fusion(fusion_config)
                logger.info("[CoreAlgorithm] Fusion engine initialized for consistency calculation")
            except Exception as e:
                logger.warning(f"[CoreAlgorithm] Failed to initialize fusion engine: {e}")
                self._fusion_engine = None
        else:
            logger.warning("[CoreAlgorithm] Fusion engine not available, consistency calculation will use fallback")
        
        # F3修复: 退出后冷静期跟踪
        # 从strategy配置中读取cooldown_after_exit_sec
        strategy_cfg = self.config.get("strategy", {})
        self.cooldown_after_exit_sec = int(strategy_cfg.get("cooldown_after_exit_sec", 0))
        # 跟踪每个symbol的最后退出时间（ts_ms）
        self._last_exit_ts_per_symbol: Dict[str, int] = {}  # symbol -> last_exit_ts_ms
        if self.cooldown_after_exit_sec > 0:
            logger.info(f"[CoreAlgorithm] F3: 退出后冷静期已启用: cooldown_after_exit_sec={self.cooldown_after_exit_sec}s")
        
        if self.recompute_fusion:
            logger.info(f"[CoreAlgorithm] 回测端重算融合已启用: recompute_fusion=True, min_consecutive_same_dir={self.min_consecutive_same_dir}")
        
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
        # TASK_CONFIRM_PIPELINE_TUNING: Phase A - 输出确认漏斗统计
        enable_funnel_diagnostics = (
            self.config.get("enable_confirm_funnel_diagnostics") or
            self.config.get("signal", {}).get("enable_confirm_funnel_diagnostics", False)
        )
        funnel_output_mode = (
            self.config.get("funnel_output_mode") or
            self.config.get("signal", {}).get("funnel_output_mode", "log")
        )


        if enable_funnel_diagnostics and self._stats.total_signals > 0:
            funnel_stats = {
                "total_signals": self._stats.total_signals,
                "pass_weak_signal_filter": self._stats.pass_weak_signal_filter,
                "pass_consistency_filter": self._stats.pass_consistency_filter,
                "candidate_confirm_true": self._stats.candidate_confirm_true,
                "reverse_prevention_blocked": self._stats.reverse_prevention_blocked,
                "confirm_true": self._stats.confirm_true
            }

            # 计算漏斗各层通过率
            funnel_rates = {
                "weak_signal_pass_rate": self._stats.pass_weak_signal_filter / self._stats.total_signals * 100,
                "consistency_pass_rate": self._stats.pass_consistency_filter / self._stats.total_signals * 100,
                "candidate_confirm_rate": self._stats.candidate_confirm_true / self._stats.total_signals * 100,
                "confirm_true_rate": self._stats.confirm_true / self._stats.total_signals * 100,
                "reverse_prevention_impact": self._stats.reverse_prevention_blocked / self._stats.total_signals * 100
            }

            if funnel_output_mode in ("log", "both"):
                logger.info("[CONFIRM_FUNNEL_STATS] 确认漏斗统计:")
                logger.info(f"  总信号数: {funnel_stats['total_signals']}")
                logger.info(f"  弱信号过滤通过: {funnel_stats['pass_weak_signal_filter']} ({funnel_rates['weak_signal_pass_rate']:.1f}%)")
                logger.info(f"  一致性过滤通过: {funnel_stats['pass_consistency_filter']} ({funnel_rates['consistency_pass_rate']:.1f}%)")
                logger.info(f"  候选确认: {funnel_stats['candidate_confirm_true']} ({funnel_rates['candidate_confirm_rate']:.1f}%)")
                logger.info(f"  反向防抖拦截: {funnel_stats['reverse_prevention_blocked']} ({funnel_rates['reverse_prevention_impact']:.1f}%)")
                logger.info(f"  最终确认: {funnel_stats['confirm_true']} ({funnel_rates['confirm_true_rate']:.1f}%)")

            if funnel_output_mode in ("json", "both"):
                # 输出到JSON文件
                import json
                from pathlib import Path
                output_dir = Path(self.config.get("signal", {}).get("output_dir", "./runtime"))
                funnel_file = output_dir / "confirm_funnel_stats.json"
                funnel_file.parent.mkdir(parents=True, exist_ok=True)

                output_data = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "stats": funnel_stats,
                    "rates": funnel_rates,
                    "config_summary": {
                        "weak_signal_threshold": self.config.get("signal", {}).get("weak_signal_threshold"),
                        "consistency_min": self.config.get("signal", {}).get("consistency_min"),
                        "min_consecutive_same_dir": self.config.get("signal", {}).get("min_consecutive_same_dir")
                    }
                }

                with open(funnel_file, "w", encoding="utf-8") as f:
                    json.dump(output_data, f, ensure_ascii=False, indent=2)

                logger.info(f"[CONFIRM_FUNNEL_STATS] 漏斗统计已保存到: {funnel_file}")

        # TASK_CONFIRM_PIPELINE_TUNING: Phase C - 输出质量分档统计
        if enable_funnel_diagnostics and self._stats.total_signals > 0:
            quality_stats = {
                "strong_tier_signals": self._stats.strong_tier_signals,
                "normal_tier_signals": self._stats.normal_tier_signals,
                "weak_tier_signals": self._stats.weak_tier_signals,
                "strong_tier_confirm": self._stats.strong_tier_confirm,
                "normal_tier_confirm": self._stats.normal_tier_confirm,
                "weak_tier_confirm": self._stats.weak_tier_confirm
            }

            # 计算分档分布和确认率
            quality_distribution = {
                "strong_tier_ratio": self._stats.strong_tier_signals / self._stats.total_signals * 100,
                "normal_tier_ratio": self._stats.normal_tier_signals / self._stats.total_signals * 100,
                "weak_tier_ratio": self._stats.weak_tier_signals / self._stats.total_signals * 100
            }

            quality_confirm_rates = {
                "strong_confirm_rate": self._stats.strong_tier_confirm / self._stats.strong_tier_signals * 100 if self._stats.strong_tier_signals > 0 else 0,
                "normal_confirm_rate": self._stats.normal_tier_confirm / self._stats.normal_tier_signals * 100 if self._stats.normal_tier_signals > 0 else 0,
                "weak_confirm_rate": self._stats.weak_tier_confirm / self._stats.weak_tier_signals * 100 if self._stats.weak_tier_signals > 0 else 0
            }

            if funnel_output_mode in ("log", "both"):
                logger.info("[QUALITY_TIER_STATS] 质量分档统计:")
                logger.info(f"  Strong档: {quality_stats['strong_tier_signals']} 信号, {quality_stats['strong_tier_confirm']} 确认 ({quality_confirm_rates['strong_confirm_rate']:.1f}%)")
                logger.info(f"  Normal档: {quality_stats['normal_tier_signals']} 信号, {quality_stats['normal_tier_confirm']} 确认 ({quality_confirm_rates['normal_confirm_rate']:.1f}%)")
                logger.info(f"  Weak档: {quality_stats['weak_tier_signals']} 信号, {quality_stats['weak_tier_confirm']} 确认 ({quality_confirm_rates['weak_confirm_rate']:.1f}%)")

            if funnel_output_mode in ("json", "both"):
                # 在JSON文件中添加质量分档统计
                output_data["quality_stats"] = quality_stats
                output_data["quality_distribution"] = quality_distribution
                output_data["quality_confirm_rates"] = quality_confirm_rates

        # TASK-A4: 关闭 SignalWriterV2（如果使用）
        if self._use_v2 and self._signal_writer_v2:
            try:
                self._signal_writer_v2.close()
            except Exception as e:
                logger.error(f"[CoreAlgorithm] Failed to close SignalWriterV2: {e}")

        # TASK-A4 修复1: v2 路径不关闭旧 sink（因为未初始化）
        # P1: 打印sink使用摘要（类名和关键参数）
        if self._sink:
            sink_class_name = type(self._sink).__name__
            sink_info = {"class": sink_class_name}
            if hasattr(self._sink, 'get_health'):
                try:
                    health = self._sink.get_health()
                    sink_info.update(health)
                except Exception:
                    pass
            logger.info(f"[CoreAlgorithm] 关闭sink: {sink_info}")
            self._sink.close()

    def process_feature_row(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # TASK-CORE-CONFIRM: 添加早期退出诊断
        core_confirm_trace = self.config.get("debug", {}).get("core_confirm_trace", False)

        if core_confirm_trace:
            logger.info(f"[CORE_CONFIRM_TRACE_EARLY] Processing row: ts_ms={row.get('ts_ms')}, symbol={row.get('symbol')}")

        if not self._validate_row(row):
            if core_confirm_trace:
                logger.info(f"[CORE_CONFIRM_TRACE_EARLY] Row validation failed: {row.get('ts_ms')}, {row.get('symbol')}")
            return None

        ts_ms = int(row["ts_ms"])
        # P0 修复4: v1/v2 符号规范一致 - v1 路径也统一大写化（与 v2 契约一致）
        symbol = str(row["symbol"]).upper()

        if self._is_duplicate(symbol, ts_ms):
            if core_confirm_trace:
                logger.info(f"[CORE_CONFIRM_TRACE_EARLY] Duplicate detected: {ts_ms}, {symbol}")
            return None

        self._stats.processed += 1

        # TASK-A4: 如果启用 v2，使用 Decision Engine 进行单点判定
        if self._use_v2 and self._decision_engine and self._signal_writer_v2:
            return self._process_feature_row_v2(row, ts_ms, symbol)
        
        # 否则使用 v1 路径（向后兼容）
        score = self._resolve_score(row)
        # 处理 None 值（Parquet 文件可能包含 None）
        spread_bps_val = row.get("spread_bps")
        lag_sec_val = row.get("lag_sec")
        spread_bps = float(spread_bps_val if spread_bps_val is not None else 0.0)
        lag_sec = float(lag_sec_val if lag_sec_val is not None else 0.0)
        warmup = bool(row.get("warmup", False))
        reason_codes = row.get("reason_codes", []) or []

        # TASK-CORE-CONFIRM: 使用Fusion引擎计算consistency，而不是从feature文件读取
        consistency_raw = self._calculate_consistency_with_fusion(row)

        # P0: consistency 保守底座（避免 93% 被 low_consistency 一刀切）
        consistency = consistency_raw  # 初始化为raw值
        if consistency_raw <= 0.0:
            consistency_floor_when_abs_score_ge = self.config.get("consistency_floor_when_abs_score_ge", 0.4)
            consistency_floor = self.config.get("consistency_floor", 0.10)
            consistency_floor_on_divergence = self.config.get("consistency_floor_on_divergence", 0.12)
            
            if abs(score) >= consistency_floor_when_abs_score_ge:
                consistency = max(consistency, consistency_floor)
            elif row.get("div_type"):  # 出现任何背离信号
                consistency = max(consistency, consistency_floor_on_divergence)

        regime = self._infer_regime(row)
        
        # F4修复: 场景化阈值覆写
        scenario_2x2 = row.get("scenario_2x2")  # A_H, Q_H, A_L, Q_L
        effective_weak_signal_threshold = self.config["weak_signal_threshold"]
        effective_consistency_min = self.config["consistency_min"]
        effective_min_consecutive = self.min_consecutive_same_dir
        
        scenario_overrides = self.config.get("scenario_overrides", {})
        if scenario_overrides and scenario_2x2:
            scenario_override = scenario_overrides.get(scenario_2x2, {})
            if scenario_override:
                # 应用场景化偏移
                weak_offset = scenario_override.get("weak_signal_threshold_offset", 0.0)
                consistency_offset = scenario_override.get("consistency_min_offset", 0.0)
                min_consecutive_offset = scenario_override.get("min_consecutive_offset", 0)
                
                effective_weak_signal_threshold = self.config["weak_signal_threshold"] + weak_offset
                effective_consistency_min = self.config["consistency_min"] + consistency_offset
                effective_min_consecutive = self.min_consecutive_same_dir + min_consecutive_offset
                
                logger.debug(f"[CoreAlgorithm] F4: 场景{scenario_2x2}覆写: weak={effective_weak_signal_threshold:.3f}, consistency={effective_consistency_min:.3f}, min_consecutive={effective_min_consecutive}")
        
        thresholds = self._thresholds_for_regime(regime)
        
        # 分模式/分场景的一致性阈值（优先级高于全局 consistency_min）
        consistency_min_per_regime = self.config.get("consistency_min_per_regime", {})
        if consistency_min_per_regime and regime in consistency_min_per_regime:
            # 如果场景化覆写已应用，使用覆写后的值；否则使用regime特定值
            if not (scenario_overrides and scenario_2x2 and scenario_overrides.get(scenario_2x2)):
                effective_consistency_min = consistency_min_per_regime[regime]

        gating_reasons: List[str] = []

        # TASK_CONFIRM_PIPELINE_TUNING: Phase A - 漏斗统计初始化
        enable_funnel_diagnostics = (
            self.config.get("enable_confirm_funnel_diagnostics") or
            self.config.get("signal", {}).get("enable_confirm_funnel_diagnostics", False)
        )
        if enable_funnel_diagnostics:
            self._stats.total_signals += 1

        # F3修复: 退出后冷静期检查（需要在ReplayFeeder中调用record_exit来更新）
        if self.cooldown_after_exit_sec > 0:
            last_exit_ts = self._last_exit_ts_per_symbol.get(symbol)
            if last_exit_ts is not None:
                elapsed_sec = (ts_ms - last_exit_ts) / 1000.0
                if elapsed_sec < self.cooldown_after_exit_sec:
                    # 仍在冷静期内，阻止信号
                    gating_reasons.append(f"cooldown_after_exit({elapsed_sec:.1f}s<{self.cooldown_after_exit_sec}s)")
                    self._stats.suppressed += 1
        if warmup:
            gating_reasons.append("warmup")
            self._stats.warmup_blocked += 1
        if spread_bps > self.config["spread_bps_cap"]:
            gating_reasons.append(f"spread_bps>{self.config['spread_bps_cap']}")
        if lag_sec > self.config["lag_cap_sec"]:
            gating_reasons.append(f"lag_sec>{self.config['lag_cap_sec']}")

        # TASK_CONFIRM_PIPELINE_TUNING: Phase A - 一致性过滤统计
        consistency_passed = consistency >= effective_consistency_min
        if enable_funnel_diagnostics and consistency_passed:
            self._stats.pass_consistency_filter += 1

        if consistency < effective_consistency_min:
            gating_reasons.append("low_consistency")

        # TASK_CONFIRM_PIPELINE_TUNING: Phase A - 弱信号过滤统计
        weak_signal_passed = abs(score) >= effective_weak_signal_threshold or warmup
        if enable_funnel_diagnostics and weak_signal_passed:
            self._stats.pass_weak_signal_filter += 1

        if abs(score) < effective_weak_signal_threshold and not warmup:
            gating_reasons.append("weak_signal")
        if reason_codes:
            gating_reasons.extend(f"reason:{code}" for code in reason_codes)

        candidate_direction = 0
        if score >= thresholds["buy"]:
            candidate_direction = 1
        elif score <= thresholds["sell"]:
            candidate_direction = -1

        # TASK-CORE-CONFIRM: debug/QA 输出开关
        core_confirm_trace = self.config.get("debug", {}).get("core_confirm_trace", False)

        # TASK_CONFIRM_PIPELINE_TUNING: Phase A - 候选确认统计
        candidate_confirm = candidate_direction != 0 and not gating_reasons
        if enable_funnel_diagnostics and candidate_confirm:
            self._stats.candidate_confirm_true += 1

        # TASK_CONFIRM_PIPELINE_TUNING: Phase C - 三档质量分层逻辑
        confirm_mode = self.config.get("confirm_mode", "v1")  # 先尝试直接读取
        if confirm_mode == "v1":  # 如果没找到，尝试从signal小节读取
            confirm_mode = self.config.get("signal", {}).get("confirm_mode", "v1")

        # DEBUG: 记录confirm_mode读取结果
        if core_confirm_trace:
            logger.info(f"[CONFIRM_MODE_DEBUG] confirm_mode={confirm_mode}, config_keys={list(self.config.keys())}")

        # Phase C: 获取strong_threshold
        strong_threshold = self.config.get("strong_threshold", 0.8)
        effective_strong_threshold = strong_threshold  # TODO: 可以后续添加场景化覆写

        # Phase C: 质量分档 - 根据score绝对值确定档位
        abs_score = abs(score)
        if abs_score >= effective_strong_threshold:
            quality_tier = "strong"
            self._stats.strong_tier_signals += 1
        elif abs_score >= effective_weak_signal_threshold:
            quality_tier = "normal"
            self._stats.normal_tier_signals += 1
        else:
            quality_tier = "weak"
            self._stats.weak_tier_signals += 1

        # Phase C: 构建质量标签
        quality_flags = []
        if abs(score) < effective_weak_signal_threshold:
            quality_flags.append("weak_signal")
        if consistency < effective_consistency_min:
            quality_flags.append("low_consistency")

        # confirm_v1: 现有逻辑（向后兼容）
        confirm = candidate_direction != 0 and not gating_reasons

        # confirm_v2: Phase C - 三档质量分层逻辑
        confirm_v2 = False
        soft_guard_reasons = []

        if candidate_direction != 0:
            # 硬护栏：永远阻塞
            hard_gating_reasons = [
                reason for reason in gating_reasons
                if reason == "warmup"  # 完全匹配
                or reason.startswith("cooldown_after_exit")  # 前缀匹配，处理 "cooldown_after_exit(3.5s<10s)" 格式
                or reason.startswith(("spread_bps>", "lag_sec>", "reason:"))
            ]

            # Phase C: 三档策略判断
            if not hard_gating_reasons:
                if quality_tier == "strong":
                    # strong 档：只要 not hard_block ⇒ 可以 confirm=True（即使有 soft guard）
                    confirm_v2 = True
                    soft_guard_reasons = quality_flags  # 记录软护栏用于诊断，但不阻塞
                elif quality_tier == "normal":
                    # normal 档：需要 not hard_block AND not weak_signal AND consistency >= consistency_min
                    if not any(flag in ("weak_signal", "low_consistency") for flag in quality_flags):
                        confirm_v2 = True
                    else:
                        # 有软护栏时记录原因
                        soft_guard_reasons = quality_flags
                # weak 档：统一 confirm=False，不记录soft_guard_reasons（因为已经是weak档）
            else:
                # 有硬护栏时，记录所有原因到soft_guard_reasons用于诊断
                soft_guard_reasons = gating_reasons

        # TASK_CONFIRM_PIPELINE_TUNING: Phase B - 根据模式选择confirm逻辑
        if confirm_mode == "v2":
            # confirm_v2: 三档质量分层逻辑，硬护栏仍需检查
            confirm = confirm_v2
            # 在v2模式下，区分硬护栏和软护栏：
            # - gating字段只反映硬护栏状态（confirm=True ⇒ gating=1）
            # - 软护栏信息保留在soft_guard_reasons中用于诊断
        # confirm_v1: 保持现有逻辑不变（gating反映所有护栏）

        # Phase C: 记录各档位确认统计
        if confirm:
            if quality_tier == "strong":
                self._stats.strong_tier_confirm += 1
            elif quality_tier == "normal":
                self._stats.normal_tier_confirm += 1
            else:  # weak
                self._stats.weak_tier_confirm += 1

        # P0修复: B组连击确认（避免一跳即确认）
        # F4修复: 使用场景化覆写后的min_consecutive
        if confirm and effective_min_consecutive > 1:
            streak = self._get_dir_streak(symbol, score)
            if streak < effective_min_consecutive:
                confirm = False
                gating_reasons.append(f"reverse_cooldown_insufficient_ticks({streak}<{effective_min_consecutive})")
                self._stats.suppressed += 1
                # TASK_CONFIRM_PIPELINE_TUNING: Phase A - 反向防抖拦截统计
                if enable_funnel_diagnostics:
                    self._stats.reverse_prevention_blocked += 1

        # TASK-CORE-CONFIRM: debug/QA 输出 - 记录详细决策过程
        if core_confirm_trace:
            confirm_reason = "ok" if confirm else ",".join(gating_reasons) if gating_reasons else "no_direction"
            if confirm and effective_min_consecutive > 1:
                confirm_reason = f"streak_ok({streak}>={effective_min_consecutive})"

            debug_record = {
                "ts_ms": ts_ms,
                "symbol": symbol,
                "score": score,
                "direction": candidate_direction,
                "regime": regime,
                "activity_tps": row.get("activity_tps", 0),
                "consistency_score": consistency,
                "consistency_min": effective_consistency_min,
                "consistency_min_per_regime": consistency_min_per_regime.get(regime),
                "gating_reasons": gating_reasons,
                "is_weak_signal": abs(score) < effective_weak_signal_threshold,
                "is_low_consistency": consistency < effective_consistency_min,
                "confirm": confirm,
                "confirm_reason": confirm_reason,
                "min_consecutive": effective_min_consecutive,
                "streak": streak if effective_min_consecutive > 1 else None
            }

            # 输出到logger（结构化格式）
            logger.info(f"[CORE_CONFIRM_TRACE] {json.dumps(debug_record, default=str)}")
        
        signal_type = "neutral"
        if confirm:
            if candidate_direction > 0:
                signal_type = "strong_buy" if score >= thresholds["strong_buy"] else "buy"
            else:
                signal_type = "strong_sell" if score <= thresholds["strong_sell"] else "sell"
        elif candidate_direction != 0:
            signal_type = "pending"

        # P0: 从环境变量读取run_id，添加到decision中用于按run_id对账
        # P1: 统一run_id贯穿JSONL/SQLite，确保JSONL包含所有必需字段（signal_type、created_at）
        run_id = os.getenv("RUN_ID", "")
        # P1: 添加created_at字段，与SQLite的created_at对齐
        from datetime import datetime, timezone
        created_at = datetime.now(timezone.utc).isoformat()
        # P1 修复3: 契约字段统一 - v1 路径统一使用 decision_reason（与 v2 一致）
        # 保留 gate_reason/guard_reason 作为向后兼容字段，但主要使用 decision_reason
        decision_reason = ",".join(gating_reasons) if gating_reasons else None
        # TASK_CONFIRM_PIPELINE_TUNING: Phase B - 添加confirm_v2和软护栏诊断字段
        # 在v2模式下，gating字段只反映硬护栏状态，确保confirm=True ⇒ gating=1
        if confirm_mode == "v2":
            gating_value = 1 if not hard_gating_reasons else 0
            gating_blocked_value = bool(hard_gating_reasons)
        else:
            # v1模式：保持现有逻辑，所有护栏都影响gating
            gating_value = 1 if not gating_reasons else 0
            gating_blocked_value = bool(gating_reasons)

        decision = {
            "ts_ms": ts_ms,
            "symbol": symbol,
            "score": score,
            "z_ofi": row.get("z_ofi"),
            "z_cvd": row.get("z_cvd"),
            "regime": regime,
            "div_type": row.get("div_type"),
            "consistency_raw": consistency_raw,  # 原始consistency（Fusion输出）
            "consistency": consistency,  # 应用floor后的consistency（用于gating）
            "confirm": confirm,
            "confirm_v2": confirm_v2,  # Phase B: confirm_v2 并行输出
            "soft_guard_reasons": soft_guard_reasons,  # Phase B: 软护栏诊断信息
            "quality_tier": quality_tier,  # Phase C: 质量档位 (strong/normal/weak)
            "quality_flags": quality_flags,  # Phase C: 质量标签 (weak_signal/low_consistency)
            "gating": gating_value,  # TASK-A4 修复3: v2模式下只考虑硬护栏，确保语义一致性
            "gating_blocked": gating_blocked_value,  # v2模式下只反映硬护栏阻塞状态
            "signal_type": signal_type,
            "decision_reason": decision_reason,  # 统一字段名（与 v2 一致）
            "gate_reason": decision_reason,  # 兼容旧字段
            "guard_reason": decision_reason,  # 兼容旧字段
            "run_id": run_id,
            "created_at": created_at,  # P1: 与SQLite的created_at对齐
        }

        # TASK_CONFIRM_PIPELINE_TUNING: Phase A - 最终确认统计
        if enable_funnel_diagnostics and confirm:
            self._stats.confirm_true += 1

        if confirm:
            self._stats.emitted += 1
        else:
            self._stats.suppressed += 1

        try:
            self._sink.emit(decision)
        except Exception:  # pragma: no cover - robust against sink errors
            logger.exception("failed to emit signal for %s", symbol)

        return decision
    
    def _process_feature_row_v2(self, row: Dict[str, Any], ts_ms: int, symbol: str) -> Optional[Dict[str, Any]]:
        """TASK-A4: 使用 signal/v2 路径处理特征行（单点判定）"""
        # TASK_P3: 为v2路径添加漏斗诊断统计
        enable_funnel_diagnostics = (
            self.config.get("enable_confirm_funnel_diagnostics") or
            self.config.get("signal", {}).get("enable_confirm_funnel_diagnostics", False)
        )
        if enable_funnel_diagnostics:
            self._stats.total_signals += 1

        # Phase C: v2路径质量分档逻辑
        strong_threshold = self.config.get("strong_threshold", 0.8)
        effective_strong_threshold = strong_threshold
        weak_signal_threshold = self.config.get("weak_signal_threshold", 0.2)

        abs_score = abs(score)
        if abs_score >= effective_strong_threshold:
            quality_tier = "strong"
            self._stats.strong_tier_signals += 1
        elif abs_score >= weak_signal_threshold:
            quality_tier = "normal"
            self._stats.normal_tier_signals += 1
        else:
            quality_tier = "weak"
            self._stats.weak_tier_signals += 1

        # Phase C: 构建质量标签
        quality_flags = []
        if abs_score < weak_signal_threshold:
            quality_flags.append("weak_signal")
        # 注意：v2路径中consistency相关信息需要在decision_result中获取

        score = self._resolve_score(row)
        z_ofi = row.get("z_ofi")
        z_cvd = row.get("z_cvd")
        div_type_raw = row.get("div_type")
        
        # 转换 div_type 为字符串（如果存在）
        div_type = None
        if div_type_raw:
            if isinstance(div_type_raw, str):
                div_type = div_type_raw.lower()
            elif hasattr(div_type_raw, 'value'):
                div_type = div_type_raw.value.lower()
            else:
                div_type = str(div_type_raw).lower()
        
        # 使用 Decision Engine 进行单点判定
        # P0 修复1: 回放/E2E 过期判定失真 - 回测/回放时传 now_ms=ts_ms，避免历史数据被判为过期
        decision_result = self._decision_engine.decide(
            ts_ms=ts_ms,
            symbol=symbol,
            score=score,
            z_ofi=float(z_ofi) if z_ofi is not None else None,
            z_cvd=float(z_cvd) if z_cvd is not None else None,
            div_type=div_type,
            now_ms=ts_ms,  # 回测/回放确保不过期
        )
        
        # P0 修复3: 规范 symbol 大写化（与契约一致）
        symbol_upper = str(symbol).upper()
        
        # 生成 signal_id（幂等键：<run_id>-<symbol>-<ts_ms>-<seq>）
        if symbol_upper not in self._signal_seq:
            self._signal_seq[symbol_upper] = 0
        else:
            self._signal_seq[symbol_upper] += 1
        seq = self._signal_seq[symbol_upper]
        signal_id = f"{self._run_id}-{symbol_upper}-{ts_ms}-{seq}"
        
        # 转换枚举值
        regime_enum = decision_result["regime"]
        decision_code_enum = decision_result["decision_code"]
        side_hint_enum = decision_result["side_hint"]
        div_type_enum = None
        if div_type:
            try:
                div_type_enum = DivType(div_type) if DivType else None
            except ValueError:
                div_type_enum = None
        
        # P0 修复3: 规范 symbol 大写化（与契约一致）
        symbol_upper = str(symbol).upper()
        
        # 创建 SignalV2 对象
        signal_v2 = SignalV2(
            ts_ms=ts_ms,
            symbol=symbol_upper,
            signal_id=signal_id,
            score=score,
            side_hint=side_hint_enum,
            z_ofi=float(z_ofi) if z_ofi is not None else None,
            z_cvd=float(z_cvd) if z_cvd is not None else None,
            div_type=div_type_enum,
            regime=regime_enum,
            gating=decision_result["gating"],
            confirm=decision_result["confirm"],
            cooldown_ms=decision_result["cooldown_ms"],
            expiry_ms=decision_result["expiry_ms"],
            decision_code=decision_code_enum,
            decision_reason=decision_result["decision_reason"],
            config_hash=self._config_hash,
            run_id=self._run_id,
            meta={
                "window_ms": self.config.get("window_ms"),
                "features_ver": os.getenv("CORE_FEATURES_VER", self.config.get("features_ver", "ofi/cvd v3")),
                "rules_ver": os.getenv("CORE_RULES_VER", self.config.get("rules_ver", "core v1")),
                "quality_tier": quality_tier,  # Phase C: 质量档位
                "quality_flags": quality_flags,  # Phase C: 质量标签
            },
        )
        
        # 写入 signal/v2
        try:
            self._signal_writer_v2.write(signal_v2)
        except Exception as e:
            logger.error(f"[CoreAlgorithm] Failed to write signal v2: {e}")
        
        # TASK_P3: 更新v2路径漏斗统计
        if enable_funnel_diagnostics:
            if decision_result["confirm"]:
                self._stats.confirm_true += 1
                # 在v2路径中，confirm=True意味着通过了所有检查
                self._stats.pass_weak_signal_filter += 1
                self._stats.pass_consistency_filter += 1
                self._stats.candidate_confirm_true += 1

                # Phase C: 记录各档位确认统计
                if quality_tier == "strong":
                    self._stats.strong_tier_confirm += 1
                elif quality_tier == "normal":
                    self._stats.normal_tier_confirm += 1
                else:  # weak
                    self._stats.weak_tier_confirm += 1

        # 更新统计
        if decision_result["confirm"]:
            self._stats.emitted += 1
        else:
            self._stats.suppressed += 1
        
        # P0 修复2: gating_blocked 语义修复 - 仅当 gating==0 时才设置 gating_blocked 和 gate_reason
        gating = decision_result["gating"]
        confirm = decision_result["confirm"]
        gating_blocked = (gating == 0)
        gate_reason = decision_result["decision_reason"] if gating_blocked else None
        
        # 返回兼容格式（供下游使用）
        return {
            "ts_ms": ts_ms,
            "symbol": symbol_upper,  # P0 修复3: 使用大写 symbol
            "score": score,
            "z_ofi": z_ofi,
            "z_cvd": z_cvd,
            "regime": regime_enum.value if hasattr(regime_enum, 'value') else str(regime_enum),
            "div_type": div_type,
            "confirm": confirm,
            "gating": gating,
            "gating_blocked": gating_blocked,  # P0 修复2: 仅当 gating==0 时为 True
            "gate_reason": gate_reason,  # P0 修复2: 仅当 gating==0 时设置
            "guard_reason": gate_reason,  # 兼容旧字段
            "signal_type": "buy" if confirm and score > 0 else ("sell" if confirm and score < 0 else "neutral"),
            "run_id": self._run_id,
            "signal_id": signal_id,
            "decision_code": decision_code_enum.value if hasattr(decision_code_enum, 'value') else str(decision_code_enum),
            "decision_reason": decision_result["decision_reason"],
            "config_hash": self._config_hash,
        }

    def process_rows(self, rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        emitted: List[Dict[str, Any]] = []
        for row in rows:
            decision = self.process_feature_row(row)
            if decision is not None:
                emitted.append(decision)
        return emitted

    def _validate_row(self, row: Dict[str, Any]) -> bool:
        # P0 修复5: 输入校验过严导致丢行 - z_ofi/z_cvd 降级为可选（缺失告警但继续计算）
        # 检查关键字段（ts_ms, symbol）必须存在且不为None
        # z_ofi/z_cvd 缺失时告警但继续处理（后续逻辑会用 0.0 兜底）
        # 其他字段（lag_sec, consistency, warmup, spread_bps）如果缺失，使用默认值
        critical_fields = ["ts_ms", "symbol"]
        missing_critical = [field for field in critical_fields if field not in row or row.get(field) is None]
        
        # P0 修复5: z_ofi/z_cvd 缺失时告警但不丢弃
        if "z_ofi" not in row or row.get("z_ofi") is None:
            logger.debug(f"[CoreAlgorithm] z_ofi missing for symbol={row.get('symbol')}, will use 0.0")
        if "z_cvd" not in row or row.get("z_cvd") is None:
            logger.debug(f"[CoreAlgorithm] z_cvd missing for symbol={row.get('symbol')}, will use 0.0")
        if missing_critical:
            logger.warning("feature row missing critical fields: %s", missing_critical)
            return False
        
        # 其他字段如果缺失，记录警告但不阻止处理（会在process_feature_row中使用默认值）
        optional_fields = ["lag_sec", "consistency", "warmup", "spread_bps"]
        missing_optional = [field for field in optional_fields if field not in row or row.get(field) is None]
        if missing_optional:
            logger.debug("feature row missing optional fields (will use defaults): %s", missing_optional)
        
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
        """解析融合分数

        P0修复: 如果recompute_fusion启用，强制重算融合分数
        P1 修复3: 融合分数加温索化/截断（winsorize 或 tanh），减少极值一跳即确认
        """
        import math  # 导入math模块用于NaN检查

        score = row.get("fusion_score")
        if self.recompute_fusion or score is None:
            # 回测端重算融合分数
            w_ofi = self.config["weights"].get("w_ofi", 0.6)
            w_cvd = self.config["weights"].get("w_cvd", 0.4)
            # 处理 None 值（Parquet 文件可能包含 None）
            # 支持多种字段名格式：z_ofi/z_cvd 或 ofi_z/cvd_z
            z_ofi_val = row.get("z_ofi") or row.get("ofi_z")
            z_cvd_val = row.get("z_cvd") or row.get("cvd_z")
            # 确保转换为float，如果是NaN则使用0.0
            ofi = float(z_ofi_val) if z_ofi_val is not None and not (isinstance(z_ofi_val, float) and math.isnan(z_ofi_val)) else 0.0
            cvd = float(z_cvd_val) if z_cvd_val is not None and not (isinstance(z_cvd_val, float) and math.isnan(z_cvd_val)) else 0.0
            
            # P1 修复3: 对 z 值进行 tanh 截断（将极值限制在合理范围内）
            # tanh 函数将输入映射到 (-1, 1)，然后乘以一个缩放因子
            # 这里使用 tanh(z/3) * 5，将 z 值限制在约 [-5, 5] 范围内
            import math
            ofi_clipped = math.tanh(ofi / 3.0) * 5.0
            cvd_clipped = math.tanh(cvd / 3.0) * 5.0
            
            score = w_ofi * ofi_clipped + w_cvd * cvd_clipped
        else:
            score = float(score)
        
        # 对最终分数也进行 tanh 截断（双重保护）
        import math
        return math.tanh(score / 3.0) * 5.0

    def _calculate_consistency_with_fusion(self, row: Dict[str, Any]) -> float:
        """TASK-CORE-CONFIRM: 使用Fusion引擎计算consistency

        优先使用Fusion引擎，如果不可用则使用简化的计算作为fallback
        """
        # 获取z_ofi和z_cvd值
        z_ofi_val = row.get("z_ofi") or row.get("ofi_z")
        z_cvd_val = row.get("z_cvd") or row.get("cvd_z")

        if z_ofi_val is None or z_cvd_val is None:
            logger.debug("[CoreAlgorithm] Missing z_ofi or z_cvd for consistency calculation, using 0.0")
            return 0.0

        # 转换为float
        import math
        z_ofi = float(z_ofi_val)
        z_cvd = float(z_cvd_val)

        # 使用Fusion引擎计算consistency（如果可用）
        if self._fusion_engine is not None:
            try:
                # 计算时间戳（用于Fusion引擎）
                ts_sec = row.get("ts_ms", 0) / 1000.0
                price = float(row.get("mid", row.get("price", 0)) or 0)
                lag_sec = float(row.get("lag_sec", 0) or 0)

                # 调用Fusion引擎的update方法
                fusion_result = self._fusion_engine.update(
                    z_ofi=z_ofi,
                    z_cvd=z_cvd,
                    ts=ts_sec,
                    lag_sec=lag_sec
                )

                if fusion_result and 'consistency' in fusion_result:
                    consistency = fusion_result['consistency']
                    # clamp到[0,1]范围
                    consistency = max(0.0, min(1.0, consistency))
                    return consistency
                else:
                    logger.warning("[CoreAlgorithm] Fusion engine returned invalid result, using fallback")
            except Exception as e:
                logger.warning(f"[CoreAlgorithm] Fusion engine consistency calculation failed: {e}, using fallback")

        # Fallback: 使用简化的consistency计算
        eps = 1e-9
        if abs(z_ofi) < eps or abs(z_cvd) < eps:
            return 0.0

        # 方向不同 → 直接 0
        if math.copysign(1, z_ofi) != math.copysign(1, z_cvd):
            return 0.0

        # 强度一致性：较小 / 较大
        abs_ofi, abs_cvd = abs(z_ofi), abs(z_cvd)
        consistency = min(abs_ofi, abs_cvd) / max(abs_ofi, abs_cvd)

        # clamp到[0,1]范围
        consistency = max(0.0, min(1.0, consistency))
        return consistency
    
    def _get_dir_streak(self, symbol: str, score: float) -> int:
        """计算方向streak（连续同向tick数）
        
        P0修复: B组连击确认逻辑
        """
        direction = 1 if score > 0 else (-1 if score < 0 else 0)
        if symbol not in self._dir_streak_state:
            self._dir_streak_state[symbol] = (direction, 1)
            return 1
        
        last_dir, count = self._dir_streak_state[symbol]
        if direction == last_dir and direction != 0:
            count += 1
        else:
            count = 1 if direction != 0 else 0
        
        self._dir_streak_state[symbol] = (direction, count)
        return count

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
    
    def record_exit(self, symbol: str, ts_ms: int) -> None:
        """F3修复: 记录退出时间，用于退出后冷静期
        
        注意：此方法需要在TradeSimulator退出持仓时调用，以更新退出时间戳
        
        Args:
            symbol: 交易对符号
            ts_ms: 退出时间戳（毫秒）
        """
        if self.cooldown_after_exit_sec > 0:
            self._last_exit_ts_per_symbol[symbol] = ts_ms
            logger.debug(f"[CoreAlgorithm] F3: 记录退出时间 {symbol} @ {ts_ms}")
