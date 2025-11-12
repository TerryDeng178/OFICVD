# -*- coding: utf-8 -*-
"""Adapter Event Sink

适配器事件落地：JSONL/SQLite WAL
"""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .base_adapter import AdapterOrder, AdapterResp

logger = logging.getLogger(__name__)


class AdapterEventSink:
    """适配器事件Sink抽象接口"""
    
    def write_event(
        self,
        ts_ms: int,
        mode: str,
        symbol: str,
        event: str,
        order: Optional["AdapterOrder"] = None,
        resp: Optional["AdapterResp"] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """写入适配器事件
        
        Args:
            ts_ms: 时间戳（ms）
            mode: 模式（backtest|testnet|live）
            symbol: 交易对
            event: 事件类型（submit|cancel|rules.refresh|retry|rate.limit）
            order: 订单对象（可选）
            resp: 响应对象（可选）
            meta: 元数据（可选）
        """
        raise NotImplementedError
    
    def close(self) -> None:
        """关闭Sink"""
        pass


class JsonlAdapterEventSink(AdapterEventSink):
    """JSONL适配器事件Sink（线程安全）"""
    
    def __init__(self, output_dir: Path):
        """初始化JSONL Sink
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = Path(output_dir)
        self.ready_root = self.output_dir / "ready" / "adapter"
        self.ready_root.mkdir(parents=True, exist_ok=True)
        # P0: 文件句柄键改为 (symbol, hour_str) 元组，避免跨小时乱序
        self._file_handles: Dict[Tuple[str, str], Any] = {}  # (symbol, hour_str) -> file handle
        self._lock = threading.Lock()  # P0: 线程安全锁
    
    def _get_file_path(self, symbol: str, ts_ms: int) -> Path:
        """获取文件路径（按小时轮转）
        
        Args:
            symbol: 交易对
            ts_ms: 时间戳（ms）
            
        Returns:
            文件路径
        """
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        hour_str = dt.strftime("%Y%m%d-%H")
        
        symbol_dir = self.ready_root / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"adapter_event-{hour_str}.jsonl"
        return symbol_dir / filename
    
    def write_event(
        self,
        ts_ms: int,
        mode: str,
        symbol: str,
        event: str,
        order: Optional["AdapterOrder"] = None,
        resp: Optional["AdapterResp"] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """写入适配器事件到JSONL（线程安全，P1: 包含契约版本）"""
        # P1: 确保 contract_ver 在事件中
        if meta is None:
            meta = {}
        if "contract_ver" not in meta:
            meta["contract_ver"] = "v1"
        
        # 构建事件记录
        record = {
            "ts_ms": ts_ms,
            "mode": mode,
            "symbol": symbol,
            "event": event,
            "contract_ver": meta.get("contract_ver", "v1"),  # P1: 契约版本显式化
        }
        
        # 添加订单信息
        if order:
            record["order"] = {
                "id": order.client_order_id,
                "side": order.side,
                "qty": order.qty,
                "type": order.order_type,
                "price": order.price,
            }
        
        # 添加响应信息
        if resp:
            record["resp"] = {
                "ok": resp.ok,
                "code": resp.code,
                "msg": resp.msg,
                "broker_order_id": resp.broker_order_id,
            }
        
        # 添加元数据
        if meta:
            record["meta"] = meta
        
        # 获取文件路径和小时字符串
        file_path = self._get_file_path(symbol, ts_ms)
        hour_str = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y%m%d-%H")
        handle_key = (symbol, hour_str)
        
        # P0: 线程安全写入
        with self._lock:
            # 检查是否需要打开新文件（新小时或新symbol）
            if handle_key not in self._file_handles:
                # 关闭旧文件（如果存在同symbol但不同hour的文件）
                keys_to_close = [k for k in self._file_handles.keys() if k[0] == symbol and k[1] != hour_str]
                for k in keys_to_close:
                    try:
                        self._file_handles[k].close()
                    except Exception as e:
                        logger.warning(f"[JsonlAdapterEventSink] Failed to close old file handle: {e}")
                    del self._file_handles[k]
                
                # 打开新文件（追加模式）
                self._file_handles[handle_key] = open(file_path, "a", encoding="utf-8", newline="")
            
            # 写入JSONL行
            json_line = json.dumps(record, ensure_ascii=False)
            self._file_handles[handle_key].write(json_line + "\n")
            self._file_handles[handle_key].flush()
    
    def close(self) -> None:
        """关闭所有文件句柄（线程安全）"""
        with self._lock:
            for fh in self._file_handles.values():
                try:
                    fh.close()
                except Exception as e:
                    logger.warning(f"[JsonlAdapterEventSink] Failed to close file handle: {e}")
            self._file_handles.clear()


class SqliteAdapterEventSink(AdapterEventSink):
    """SQLite适配器事件Sink（WAL模式，线程安全）"""
    
    def __init__(self, output_dir: Path, db_name: str = "signals.db"):
        """初始化SQLite Sink
        
        Args:
            output_dir: 输出目录
            db_name: 数据库文件名
        """
        self.output_dir = Path(output_dir)
        self.db_path = self.output_dir / db_name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # P0: 持久连接 + 线程安全
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._pending_writes: List[Tuple] = []  # 批量写入队列
        self._batch_size = 10  # 批量写入大小
        
        # 初始化数据库
        self._init_db()
    
    def _init_db(self) -> None:
        """初始化数据库表（使用持久连接）"""
        # P0: 使用持久连接，避免频繁连接/断开
        # check_same_thread=False 允许跨线程使用（配合锁保证线程安全）
        self._conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")  # 5秒超时，避免 database is locked
        
        # P0: 取消唯一约束，改为普通索引，避免重试事件被覆盖
        # P1: 添加 contract_ver 列（契约版本显式化）
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS adapter_events (
                ts_ms INTEGER NOT NULL,
                mode TEXT NOT NULL,
                symbol TEXT NOT NULL,
                event TEXT NOT NULL,
                code TEXT,
                order_id TEXT,
                broker_order_id TEXT,
                latency_ms REAL,
                retries INT,
                attempt INT,
                contract_ver TEXT DEFAULT 'v1',
                note TEXT
            )
        """)
        
        # 普通索引（不唯一），保留历史事件
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_adapter_events_key ON adapter_events(symbol, event, ts_ms)")
        
        # 创建索引
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_adapter_events_symbol_ts ON adapter_events(symbol, ts_ms)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_adapter_events_event ON adapter_events(event)")
        
        self._conn.commit()
    
    def write_event(
        self,
        ts_ms: int,
        mode: str,
        symbol: str,
        event: str,
        order: Optional["AdapterOrder"] = None,
        resp: Optional["AdapterResp"] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """写入适配器事件到SQLite（线程安全，批量写入）"""
        # P1: 优先使用 broker_order_id（用于撤单事件）
        order_id = order.client_order_id if order else None
        broker_order_id = None
        if resp and resp.broker_order_id:
            broker_order_id = resp.broker_order_id
        elif meta and "broker_order_id" in meta:
            broker_order_id = meta["broker_order_id"]
        
        code = resp.code if resp else None
        latency_ms = meta.get("latency_ms") if meta else None
        retries = meta.get("retries") if meta else None
        attempt = meta.get("attempt") if meta else None  # P0: 记录第几次尝试
        contract_ver = meta.get("contract_ver", "v1") if meta else "v1"  # P1: 契约版本
        note = resp.msg if resp else None
        
        # P0: 线程安全批量写入
        with self._lock:
            if not self._conn:
                # 重新连接（如果连接丢失）
                self._init_db()
            
            # 添加到批量写入队列（包含 attempt 和 contract_ver）
            self._pending_writes.append((
                ts_ms, mode, symbol, event, code, order_id, broker_order_id,
                latency_ms, retries, attempt, contract_ver, note
            ))
            
            # 达到批量大小时执行批量写入
            if len(self._pending_writes) >= self._batch_size:
                self._flush_batch()
    
    def _flush_batch(self) -> None:
        """批量写入待写入的事件"""
        if not self._pending_writes:
            return
        
        try:
            # P0: 改为 INSERT（取消唯一索引后，不再需要 REPLACE）
            # P1: 包含 contract_ver 列
            self._conn.executemany("""
                INSERT INTO adapter_events
                (ts_ms, mode, symbol, event, code, order_id, broker_order_id, latency_ms, retries, attempt, contract_ver, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, self._pending_writes)
            self._conn.commit()
            self._pending_writes.clear()
        except sqlite3.OperationalError as e:
            logger.error(f"[SqliteAdapterEventSink] Failed to flush batch: {e}")
            # 如果批量写入失败，尝试逐条写入
            for row in self._pending_writes:
                try:
                    self._conn.execute("""
                        INSERT INTO adapter_events
                        (ts_ms, mode, symbol, event, code, order_id, broker_order_id, latency_ms, retries, attempt, contract_ver, note)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, row)
                    self._conn.commit()
                except Exception as e2:
                    logger.error(f"[SqliteAdapterEventSink] Failed to write single event: {e2}")
            self._pending_writes.clear()
    
    def close(self) -> None:
        """关闭数据库连接（线程安全）"""
        with self._lock:
            # 刷新待写入的事件
            if self._pending_writes:
                self._flush_batch()
            
            # 关闭连接
            if self._conn:
                try:
                    self._conn.close()
                except Exception as e:
                    logger.warning(f"[SqliteAdapterEventSink] Failed to close connection: {e}")
                self._conn = None


class MultiAdapterEventSink(AdapterEventSink):
    """多 Sink 适配器（参考 TASK-07B 的 MultiSink 模式）
    
    同时写入 JSONL 和 SQLite，确保数据一致性
    """
    
    def __init__(self, output_dir: Path, db_name: str = "signals.db"):
        """初始化多 Sink
        
        Args:
            output_dir: 输出目录
            db_name: 数据库文件名
        """
        self.jsonl_sink = JsonlAdapterEventSink(output_dir)
        self.sqlite_sink = SqliteAdapterEventSink(output_dir, db_name)
    
    def write_event(
        self,
        ts_ms: int,
        mode: str,
        symbol: str,
        event: str,
        order: Optional["AdapterOrder"] = None,
        resp: Optional["AdapterResp"] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """写入事件到两个 Sink（参考 TASK-07B：确保一致性）"""
        # 同时写入两个 Sink
        try:
            self.jsonl_sink.write_event(ts_ms, mode, symbol, event, order, resp, meta)
        except Exception as e:
            logger.error(f"[MultiAdapterEventSink] JSONL write failed: {e}")
        
        try:
            self.sqlite_sink.write_event(ts_ms, mode, symbol, event, order, resp, meta)
        except Exception as e:
            logger.error(f"[MultiAdapterEventSink] SQLite write failed: {e}")
    
    def close(self) -> None:
        """关闭所有 Sink（参考 TASK-07B：顺序关闭，确保无残留）"""
        try:
            self.sqlite_sink.close()  # 先关闭 SQLite（确保数据提交）
        except Exception as e:
            logger.error(f"[MultiAdapterEventSink] SQLite close failed: {e}")
        
        try:
            self.jsonl_sink.close()  # 再关闭 JSONL（确保文件 rotate）
        except Exception as e:
            logger.error(f"[MultiAdapterEventSink] JSONL close failed: {e}")


def build_adapter_event_sink(kind: str, output_dir: Path, db_name: str = "signals.db") -> AdapterEventSink:
    """构建适配器事件Sink（支持双 Sink 模式，参考 TASK-07B）
    
    Args:
        kind: Sink类型（jsonl|sqlite|dual）
        output_dir: 输出目录
        db_name: 数据库文件名（仅sqlite使用）
        
    Returns:
        适配器事件Sink实例（dual 模式返回 MultiAdapterEventSink）
    """
    if kind == "jsonl":
        return JsonlAdapterEventSink(output_dir)
    elif kind == "sqlite":
        return SqliteAdapterEventSink(output_dir, db_name)
    elif kind == "dual":
        # 参考 TASK-07B：双 Sink 模式，同时写入 JSONL 和 SQLite
        return MultiAdapterEventSink(output_dir, db_name)
    else:
        raise ValueError(f"Unknown sink kind: {kind}")

