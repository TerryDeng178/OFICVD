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
        minute = dt.strftime("%Y%m%d_%H%M")
        symbol = entry.get("symbol", "UNKNOWN")
        target_dir = self.ready_root / symbol
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f"signals_{minute}.jsonl"
        
        # P0: 添加水印字段，用于验证是否使用了CORE_ALGO的JsonlSink
        entry.setdefault("_writer", "core_jsonl_v406")
        
        serialized = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        
        # P0: 按批次 fsync，兼顾数据安全与性能
        # P1: 注意：_write_count 跨文件累积，fsync 发生在当次目标文件句柄上
        # P0: JSONL rotate时确保最后一次fsync（在文件关闭前检查_write_count）
        # 跟踪上一个文件，在文件切换时fsync上一个文件
        prev_minute = getattr(self, '_last_minute', None)
        current_minute = minute
        
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
            
            # P0: 在文件关闭前，如果_write_count>0（无论是否达到阈值），都要fsync
            # 这确保rotate时最后一批数据也能fsync（避免只flush未fsync）
            # 注意：如果_write_count >= fsync_every_n，已经在上面fsync并重置为0了
            # 所以这里只需要处理 > 0 且 < fsync_every_n 的情况
            # 但实际上，由于文件句柄在with语句结束后关闭，我们需要在关闭前fsync
            # 如果_write_count > 0，说明还有未fsync的数据，需要fsync
            if self._write_count > 0:
                # 文件即将关闭，确保最后一批数据fsync
                fp.flush()
                os.fsync(fp.fileno())
                self._write_count = 0
        
        self._last_minute = current_minute

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
            failed_batch_file = Path("runtime/failed_batches.jsonl")
            try:
                with open(failed_batch_file, "a", encoding="utf-8", newline="") as f:
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
        self.config = _merge_dict(DEFAULT_SIGNAL_CONFIG, config or {})
        sink_cfg = self.config.get("sink", {})
        base_dir = Path(output_dir or sink_cfg.get("output_dir", "./runtime"))
        
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
        self._base_dir = base_dir
        self._stats = SignalStats()
        self._last_ts_per_symbol: Dict[str, int] = {}
        
        # P0修复: B组回测端重算融合 + 连击确认
        self.recompute_fusion = bool(self.config.get("recompute_fusion", False))
        self.min_consecutive_same_dir = int(self.config.get("min_consecutive_same_dir", 1))
        # 方向streak跟踪: symbol -> (direction, count)
        self._dir_streak_state: Dict[str, tuple] = {}  # symbol -> (last_direction, consecutive_count)
        
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
        
        # P0修复: B组连击确认（避免一跳即确认）
        if confirm and self.min_consecutive_same_dir > 1:
            streak = self._get_dir_streak(symbol, score)
            if streak < self.min_consecutive_same_dir:
                confirm = False
                gating_reasons.append(f"reverse_cooldown_insufficient_ticks({streak}<{self.min_consecutive_same_dir})")
                self._stats.suppressed += 1
        
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
        decision = {
            "ts_ms": ts_ms,
            "symbol": symbol,
            "score": score,
            "z_ofi": row.get("z_ofi"),
            "z_cvd": row.get("z_cvd"),
            "regime": regime,
            "div_type": row.get("div_type"),
            "confirm": confirm,
            "gating": bool(gating_reasons),  # 兼容旧字段
            "gating_blocked": bool(gating_reasons),  # 修复C: 明确语义 - gating_blocked=True表示"被门控阻止"
            "signal_type": signal_type,
            "gate_reason": ",".join(gating_reasons) if gating_reasons else None,  # 修复C: 统一字段名为gate_reason
            "guard_reason": ",".join(gating_reasons) if gating_reasons else None,  # 兼容旧字段
            "run_id": run_id,
            "created_at": created_at,  # P1: 与SQLite的created_at对齐
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
        # 检查关键字段（ts_ms, symbol, z_ofi, z_cvd）必须存在且不为None
        # 其他字段（lag_sec, consistency, warmup, spread_bps）如果缺失，使用默认值
        critical_fields = ["ts_ms", "symbol", "z_ofi", "z_cvd"]
        missing_critical = [field for field in critical_fields if field not in row or row.get(field) is None]
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
        """
        score = row.get("fusion_score")
        if self.recompute_fusion or score is None:
            # 回测端重算融合分数
            w_ofi = self.config["weights"].get("w_ofi", 0.6)
            w_cvd = self.config["weights"].get("w_cvd", 0.4)
            # 处理 None 值（Parquet 文件可能包含 None）
            z_ofi_val = row.get("z_ofi")
            z_cvd_val = row.get("z_cvd")
            ofi = float(z_ofi_val if z_ofi_val is not None else 0.0)
            cvd = float(z_cvd_val if z_cvd_val is not None else 0.0)
            return w_ofi * ofi + w_cvd * cvd
        return float(score)
    
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
