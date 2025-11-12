# -*- coding: utf-8 -*-
"""Signal Writer v2

JSONL/SQLite 双 Sink 写入封装，支持 signal/v2 契约
参考 TASK-07B 的 MultiSink 模式
"""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from .signal_schema import SignalV2, validate_signal_v2

logger = logging.getLogger(__name__)


class SignalWriterV2:
    """Signal v2 Writer（JSONL/SQLite 双 Sink）
    
    参考 TASK-07B：同时写入 JSONL 和 SQLite，确保数据一致性
    """
    
    def __init__(self, output_dir: Path, sink_kind: str = "dual", db_name: str = "signals_v2.db"):
        """初始化 Signal Writer
        
        Args:
            output_dir: 输出目录
            sink_kind: Sink 类型（jsonl|sqlite|dual）
            db_name: 数据库文件名（仅 sqlite 使用）
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.sink_kind = sink_kind.lower()
        self.db_name = db_name
        
        # 初始化 Sink
        if self.sink_kind == "jsonl":
            self._jsonl_enabled = True
            self._sqlite_enabled = False
        elif self.sink_kind == "sqlite":
            self._jsonl_enabled = False
            self._sqlite_enabled = True
        elif self.sink_kind == "dual":
            self._jsonl_enabled = True
            self._sqlite_enabled = True
        else:
            raise ValueError(f"Unknown sink_kind: {sink_kind}")
        
        # JSONL 相关
        if self._jsonl_enabled:
            self.ready_root = self.output_dir / "ready" / "signal"
            self.ready_root.mkdir(parents=True, exist_ok=True)
            self._jsonl_lock = threading.Lock()
            # P0 修复1: 批量 fsync 配置（与 v1 JsonlSink 对齐）
            self._jsonl_fsync_every_n = int(os.getenv("FSYNC_EVERY_N", "50"))
            self._jsonl_write_count = 0
            self._jsonl_last_hour = None  # 跟踪上一个小时，用于检测文件切换
            logger.info(f"[SignalWriterV2] JSONL fsync策略: every_n={self._jsonl_fsync_every_n}")
        
        # SQLite 相关
        if self._sqlite_enabled:
            self.db_path = self.output_dir / db_name
            if db_name != "signals_v2.db":
                logger.warning(
                    "[SignalWriterV2] Unexpected SQLite db name '%s' (expected 'signals_v2.db');"
                    " ensure legacy v1 sinks已关闭", db_name
                )
            self._sqlite_lock = threading.Lock()
            # P1 修复4: v2 SQLite 批处理队列（参考 v1 SqliteSink）
            self._sqlite_batch_n = int(os.getenv("SQLITE_BATCH_N", "500"))
            self._sqlite_flush_ms = int(os.getenv("SQLITE_FLUSH_MS", "500"))
            self._sqlite_batch_queue: list = []
            self._sqlite_last_flush_time = 0.0
            self._sqlite_conn = None  # 持久连接（在首次写入时创建）
            logger.info(f"[SignalWriterV2] SQLite 批量参数: batch_n={self._sqlite_batch_n}, flush_ms={self._sqlite_flush_ms}ms")
            self._init_sqlite()
    
    def _init_sqlite(self) -> None:
        """初始化 SQLite 数据库（signal/v2 表结构）
        
        P1 修复4: 使用持久连接（在首次写入时创建），支持批处理队列
        P0 修复3: v2 数据库破坏式迁移风险 - 默认使用 signals_v2.db，避免与 v1 冲突
        """
        # 初始化时创建表结构（使用临时连接，表结构创建后关闭）
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        
        # P0 修复3: 检查表是否存在，如果存在则检查是否有 signal_id 列
        # 由于默认使用 signals_v2.db，通常不会与 v1 冲突，但仍需检查表结构
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signals'")
        table_exists = cursor.fetchone() is not None
        
        if table_exists:
            if not self._is_expected_schema(conn):
                logger.warning(
                    f"[SignalWriterV2] Detected legacy signal table schema, rebuilding (db={self.db_path.name})"
                )
                conn.execute("DROP TABLE IF EXISTS signals")
                table_exists = False
        
        if not table_exists:
            # 创建 signal/v2 表结构
            conn.execute("""
                CREATE TABLE signals (
                    ts_ms INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    signal_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL DEFAULT 'signal/v2',
                    score REAL NOT NULL,
                    side_hint TEXT NOT NULL,
                    z_ofi REAL,
                    z_cvd REAL,
                    div_type TEXT,
                    regime TEXT NOT NULL,
                    gating INTEGER NOT NULL,
                    confirm INTEGER NOT NULL,
                    cooldown_ms INTEGER NOT NULL,
                    expiry_ms INTEGER NOT NULL,
                    decision_code TEXT NOT NULL,
                    decision_reason TEXT,
                    config_hash TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    meta TEXT,
                    PRIMARY KEY(symbol, ts_ms, signal_id)
                ) WITHOUT ROWID;
            """)
            
            # P1 修复1: SQLite 索引评估
            # 主键 (symbol, ts_ms, signal_id) 已可满足 (symbol, ts_ms) 的左前缀查询
            # 但考虑到查询模式广泛使用 (symbol, ts_ms)，保留此索引以优化查询性能
            # 写放大影响相对较小（SQLite 索引维护成本不高）
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, ts_ms);"
            )
        
        conn.commit()
        conn.close()

    def _is_expected_schema(self, conn: sqlite3.Connection) -> bool:
        """检查现有 signals 表是否符合 signal/v2 结构"""
        try:
            cursor = conn.execute("PRAGMA table_info(signals)")
            rows = cursor.fetchall()
        except Exception as exc:
            logger.warning(f"[SignalWriterV2] Failed to inspect SQLite schema: {exc}")
            return False
        if not rows:
            return False
        expected_columns = {
            "ts_ms": "INTEGER",
            "symbol": "TEXT",
            "signal_id": "TEXT",
            "schema_version": "TEXT",
            "score": "REAL",
            "side_hint": "TEXT",
            "z_ofi": "REAL",
            "z_cvd": "REAL",
            "div_type": "TEXT",
            "regime": "TEXT",
            "gating": "INTEGER",
            "confirm": "INTEGER",
            "cooldown_ms": "INTEGER",
            "expiry_ms": "INTEGER",
            "decision_code": "TEXT",
            "decision_reason": "TEXT",
            "config_hash": "TEXT",
            "run_id": "TEXT",
            "meta": "TEXT",
        }
        existing_columns = {row[1]: row[2].upper() for row in rows}
        if set(existing_columns.keys()) != set(expected_columns.keys()):
            logger.debug(
                "[SignalWriterV2] SQLite columns mismatch: expected=%s, existing=%s",
                sorted(expected_columns.keys()),
                sorted(existing_columns.keys()),
            )
            return False
        for col, expected_type in expected_columns.items():
            existing_type = existing_columns.get(col, "").upper()
            if expected_type.upper() not in existing_type:
                logger.debug(
                    "[SignalWriterV2] Column type mismatch for %s: expected contains '%s', got '%s'",
                    col,
                    expected_type,
                    existing_type,
                )
                return False
        # 验证主键顺序 (symbol, ts_ms, signal_id)
        pk_info = sorted((row[1], row[5]) for row in rows if row[5] > 0)
        expected_pk = [("symbol", 1), ("ts_ms", 2), ("signal_id", 3)]
        if pk_info != expected_pk:
            logger.debug(
                "[SignalWriterV2] Primary key mismatch: expected=%s, got=%s",
                expected_pk,
                pk_info,
            )
            return False
        # 验证 schema_version 默认值
        schema_row = next((row for row in rows if row[1] == "schema_version"), None)
        if not schema_row or schema_row[4] not in ("'signal/v2'", '"signal/v2"', "signal/v2"):
            logger.debug(
                "[SignalWriterV2] schema_version default mismatch: %s", schema_row[4] if schema_row else None
            )
            return False
        return True
    
    def write(self, signal: SignalV2) -> None:
        """写入 signal/v2 信号
        
        Args:
            signal: SignalV2 实例
        """
        # 验证信号（SignalV2 实例已通过 pydantic 验证，这里跳过）
        # 如果需要额外验证，可以在这里添加
        
        # 写入 JSONL
        if self._jsonl_enabled:
            try:
                self._write_jsonl(signal)
            except Exception as e:
                logger.error(f"[SignalWriterV2] JSONL write failed: {e}")
        
        # 写入 SQLite
        if self._sqlite_enabled:
            try:
                self._write_sqlite(signal)
            except Exception as e:
                logger.error(f"[SignalWriterV2] SQLite write failed: {e}")
    
    def _write_jsonl(self, signal: SignalV2) -> None:
        """写入 JSONL（参考 TASK-07B：线程安全，按小时轮转，批量 fsync）
        
        P0 修复1: 与 v1 JsonlSink 对齐，支持批量 fsync（到阈值或跨小时才 fsync）
        """
        with self._jsonl_lock:
            data = signal.dict_for_jsonl()
            ts_ms = data["ts_ms"]
            # P0 修复3: 规范 symbol 大写化（与契约一致）
            symbol = str(data["symbol"]).upper()
            
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            hour_str = dt.strftime("%Y%m%d-%H")
            current_hour = (symbol, hour_str)
            
            # P0 修复1: 如果文件切换（小时轮转），对上一个文件执行补偿 fsync
            if self._jsonl_last_hour is not None and self._jsonl_last_hour != current_hour:
                prev_symbol, prev_hour_str = self._jsonl_last_hour
                prev_file = self.ready_root / prev_symbol / f"signals-{prev_hour_str}.jsonl"
                if prev_file.exists():
                    try:
                        with prev_file.open("r+b") as prev_fp:
                            prev_fp.flush()
                            os.fsync(prev_fp.fileno())
                    except Exception as e:
                        logger.warning(f"[SignalWriterV2] Failed to fsync previous file {prev_file}: {e}")
            
            # 获取或创建文件句柄（每次写入都打开文件，参考 TASK-07B）
            target_dir = self.ready_root / symbol
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file = target_dir / f"signals-{hour_str}.jsonl"
            
            # 写入数据（每次打开文件，确保线程安全）
            with target_file.open("a", encoding="utf-8") as fp:
                serialized = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                fp.write(serialized + "\n")
                self._jsonl_write_count += 1
                
                # P0 修复1: 只在达到阈值时 fsync，移除收尾兜底 fsync
                if self._jsonl_write_count >= self._jsonl_fsync_every_n:
                    fp.flush()
                    os.fsync(fp.fileno())
                    self._jsonl_write_count = 0
                else:
                    # 仍然 flush，但不 fsync（减少系统调用）
                    fp.flush()
            
            self._jsonl_last_hour = current_hour
    
    def _write_sqlite(self, signal: SignalV2) -> None:
        """写入 SQLite（P1 修复4: 批处理队列，参考 v1 SqliteSink）
        
        使用持久连接 + 批量提交，显著提升吞吐
        """
        import time
        with self._sqlite_lock:
            data = signal.dict_for_sqlite()
            
            # P0 修复2: v2 SQLite meta 避免二次序列化 - dict_for_sqlite() 已返回 JSON 字符串，直接使用
            payload = (
                data["ts_ms"], data["symbol"], data["signal_id"], data["schema_version"],
                data["score"], data["side_hint"], data.get("z_ofi"), data.get("z_cvd"),
                data.get("div_type"), data["regime"], data["gating"], int(data["confirm"]),
                data["cooldown_ms"], data["expiry_ms"], data["decision_code"],
                data.get("decision_reason"), data["config_hash"], data["run_id"],
                data.get("meta"),  # 这里直接用 dict_for_sqlite 返回的字符串（已序列化）
            )
            
            # 加入队列
            self._sqlite_batch_queue.append(payload)
            
            # 检查是否需要刷新（达到 batch_n 或 flush_ms）
            current_time = time.time()
            time_elapsed_ms = (current_time - self._sqlite_last_flush_time) * 1000 if self._sqlite_flush_ms > 0 else float('inf')
            should_flush = (
                len(self._sqlite_batch_queue) >= self._sqlite_batch_n or
                time_elapsed_ms >= self._sqlite_flush_ms
            )
            
            if should_flush:
                self._flush_sqlite_batch()
    
    def _flush_sqlite_batch(self) -> None:
        """批量刷新 SQLite（P1 修复4: 批量提交，参考 v1 SqliteSink）"""
        import time
        
        if not self._sqlite_batch_queue:
            return
        
        batch_size = len(self._sqlite_batch_queue)
        
        # 确保持久连接已创建
        if self._sqlite_conn is None:
            self._sqlite_conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._sqlite_conn.execute("PRAGMA journal_mode=WAL;")
            self._sqlite_conn.execute("PRAGMA synchronous=NORMAL;")
            self._sqlite_conn.execute("PRAGMA busy_timeout=5000;")
            self._sqlite_conn.execute("PRAGMA temp_store=MEMORY;")
            self._sqlite_conn.execute("PRAGMA cache_size=-20000;")  # 约 20MB
        
        try:
            # 批量提交
            self._sqlite_conn.executemany("""
                INSERT OR IGNORE INTO signals (
                    ts_ms, symbol, signal_id, schema_version, score, side_hint,
                    z_ofi, z_cvd, div_type, regime, gating, confirm,
                    cooldown_ms, expiry_ms, decision_code, decision_reason,
                    config_hash, run_id, meta
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, self._sqlite_batch_queue)
            self._sqlite_conn.commit()
            
            flushed_count = len(self._sqlite_batch_queue)
            self._sqlite_batch_queue.clear()
            self._sqlite_last_flush_time = time.time()
            
            # 日志（仅在批量较大时输出）
            if batch_size >= 10 or os.getenv("SQLITE_DEBUG", "0") == "1":
                logger.debug(f"[SignalWriterV2] SQLite 批量刷新: {flushed_count}条数据已写入数据库")
                
        except (sqlite3.IntegrityError, sqlite3.OperationalError, Exception) as e:
            logger.error(f"[SignalWriterV2] SQLite 批量刷新失败: {e}", exc_info=True)
            
            # 退避重试（最多 3 次）
            retry_count = 0
            max_retries = 3
            while retry_count < max_retries:
                try:
                    time.sleep(0.1 * (retry_count + 1))  # 退避：0.1s, 0.2s, 0.3s
                    self._sqlite_conn.executemany("""
                        INSERT OR IGNORE INTO signals (
                            ts_ms, symbol, signal_id, schema_version, score, side_hint,
                            z_ofi, z_cvd, div_type, regime, gating, confirm,
                            cooldown_ms, expiry_ms, decision_code, decision_reason,
                            config_hash, run_id, meta
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, self._sqlite_batch_queue)
                    self._sqlite_conn.commit()
                    
                    logger.info(f"[SignalWriterV2] SQLite 批量刷新重试成功（第{retry_count + 1}次）")
                    flushed_count = len(self._sqlite_batch_queue)
                    self._sqlite_batch_queue.clear()
                    self._sqlite_last_flush_time = time.time()
                    return
                except Exception as retry_e:
                    retry_count += 1
                    logger.warning(f"[SignalWriterV2] SQLite 批量刷新重试失败（第{retry_count}次）: {retry_e}")
            
            # 所有重试失败，写入补偿文件
            failed_batch_file = self.output_dir / "failed_batches.jsonl"
            try:
                with failed_batch_file.open("a", encoding="utf-8", newline="") as f:
                    for payload in self._sqlite_batch_queue:
                        record = {
                            "ts_ms": payload[0],
                            "symbol": payload[1],
                            "signal_id": payload[2],
                            "schema_version": payload[3],
                            "score": payload[4],
                            "side_hint": payload[5],
                            "z_ofi": payload[6],
                            "z_cvd": payload[7],
                            "div_type": payload[8],
                            "regime": payload[9],
                            "gating": payload[10],
                            "confirm": payload[11],
                            "cooldown_ms": payload[12],
                            "expiry_ms": payload[13],
                            "decision_code": payload[14],
                            "decision_reason": payload[15],
                            "config_hash": payload[16],
                            "run_id": payload[17],
                            "meta": payload[18],
                        }
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                logger.error(f"[SignalWriterV2] SQLite 批量刷新失败，已写入补偿文件: {failed_batch_file} ({batch_size}条)")
            except Exception as save_e:
                logger.error(f"[SignalWriterV2] 写入补偿文件失败: {save_e}", exc_info=True)
            
            # 清空队列（已保存到补偿文件）
            self._sqlite_batch_queue.clear()
    
    def close(self) -> None:
        """关闭所有 Sink（参考 TASK-07B：顺序关闭，确保无残留）
        
        P1 修复4: 关闭时刷新剩余批次，确保所有队列数据写入数据库
        TASK-A4优化: 确保JSONL当前文件也做fsync（优雅退出要求）
        """
        # 刷新 SQLite 剩余批次
        if self._sqlite_enabled:
            with self._sqlite_lock:
                if self._sqlite_batch_queue:
                    self._flush_sqlite_batch()
                # 关闭持久连接
                if self._sqlite_conn:
                    try:
                        self._sqlite_conn.close()
                    except Exception as e:
                        logger.error(f"[SignalWriterV2] Failed to close SQLite connection: {e}")
                    finally:
                        self._sqlite_conn = None
        
        # TASK-A4优化: JSONL 优雅退出 - 对当前小时文件执行最后一次 fsync
        # 虽然JSONL采用每次写入都打开/关闭文件的策略，但关闭时需要确保当前文件已fsync
        if self._jsonl_enabled and self._jsonl_last_hour is not None:
            with self._jsonl_lock:
                symbol, hour_str = self._jsonl_last_hour
                current_file = self.ready_root / symbol / f"signals-{hour_str}.jsonl"
                if current_file.exists():
                    try:
                        # 对当前文件执行最后一次 fsync，确保数据持久化
                        with current_file.open("r+b") as fp:
                            fp.flush()
                            os.fsync(fp.fileno())
                        logger.debug(f"[SignalWriterV2] Final fsync for {current_file.name}")
                    except Exception as e:
                        logger.warning(f"[SignalWriterV2] Failed to final fsync {current_file}: {e}")

