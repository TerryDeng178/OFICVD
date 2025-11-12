# -*- coding: utf-8 -*-
"""Execution Log Sink

执行日志写入模块：支持JSONL和SQLite两种Sink
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

from .base_executor import Order, Fill, OrderState

logger = logging.getLogger(__name__)


class ExecLogSink:
    """执行日志Sink抽象接口"""
    
    def write_event(
        self,
        ts_ms: int,
        symbol: str,
        event: str,
        order: Optional[Order] = None,
        fill: Optional[Fill] = None,
        state: Optional[OrderState] = None,
        reason: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """写入执行事件
        
        Args:
            ts_ms: 时间戳（ms）
            symbol: 交易对
            event: 事件类型（submit/ack/partial/filled/canceled/rejected）
            order: 订单对象（可选）
            fill: 成交对象（可选）
            state: 订单状态（可选）
            reason: 拒绝原因（可选）
            meta: 元数据（可选）
        """
        raise NotImplementedError


class JsonlExecLogSink(ExecLogSink):
    """JSONL执行日志Sink"""
    
    def __init__(self, output_dir: Path):
        """初始化JSONL Sink
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = Path(output_dir)
        self.ready_root = self.output_dir / "ready" / "execlog"
        self.ready_root.mkdir(parents=True, exist_ok=True)
        self._write_count = 0
        self.fsync_every_n = 100  # 每100次写入执行一次fsync
        self._last_minute = None
    
    def write_event(
        self,
        ts_ms: int,
        symbol: str,
        event: str,
        order: Optional[Order] = None,
        fill: Optional[Fill] = None,
        state: Optional[OrderState] = None,
        reason: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """写入执行事件到JSONL"""
        # 构建事件记录
        record = {
            "ts_ms": ts_ms,
            "symbol": symbol,
            "event": event,
            "state": state.value if state else None,
            "reason": reason,
            "meta": meta or {},
        }
        
        # 添加订单信息
        if order:
            record["order"] = {
                "id": order.client_order_id,
                "side": order.side.value,
                "qty": order.qty,
                "type": order.order_type.value,
                "price": order.price,
            }
        
        # 添加成交信息
        if fill:
            record["fill"] = {
                "price": fill.price,
                "qty": fill.qty,
                "fee": fill.fee,
                "liquidity": fill.liquidity,
            }
        
        # 写入文件（按分钟轮转）
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        minute = dt.strftime("%Y%m%d_%H%M")
        target_dir = self.ready_root / symbol
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f"exec_log_{minute}.jsonl"
        
        serialized = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        
        with target_file.open("a", encoding="utf-8") as fp:
            fp.write(serialized + "\n")
            self._write_count += 1
            
            # 每N次写入执行一次fsync
            if self._write_count >= self.fsync_every_n:
                fp.flush()
                os.fsync(fp.fileno())
                self._write_count = 0
            else:
                fp.flush()
        
        self._last_minute = minute


class SqliteExecLogSink(ExecLogSink):
    """SQLite执行日志Sink"""
    
    def __init__(self, output_dir: Path, db_name: str = "signals.db"):
        """初始化SQLite Sink
        
        Args:
            output_dir: 输出目录
            db_name: 数据库文件名
        """
        self.output_dir = Path(output_dir)
        self.db_path = self.output_dir / db_name
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA busy_timeout=5000;")
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self._init_table()
    
    def _init_table(self):
        """初始化exec_events表"""
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exec_events (
                ts_ms INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                event TEXT NOT NULL,
                state TEXT,
                order_id TEXT,
                broker_order_id TEXT,
                price REAL,
                qty REAL,
                fee REAL,
                reason TEXT,
                liquidity TEXT,
                meta TEXT,
                created_at TEXT DEFAULT (DATETIME('now')),
                PRIMARY KEY (ts_ms, symbol, order_id, event)
            );
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_exec_events_symbol_ts ON exec_events(symbol, ts_ms);"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_exec_events_order_id ON exec_events(order_id);"
        )
        self.conn.commit()
    
    def write_event(
        self,
        ts_ms: int,
        symbol: str,
        event: str,
        order: Optional[Order] = None,
        fill: Optional[Fill] = None,
        state: Optional[OrderState] = None,
        reason: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """写入执行事件到SQLite"""
        order_id = order.client_order_id if order else None
        broker_order_id = fill.broker_order_id if fill else None
        price = fill.price if fill else (order.price if order else None)
        qty = fill.qty if fill else (order.qty if order else None)
        fee = fill.fee if fill else None
        liquidity = fill.liquidity if fill else None
        meta_json = json.dumps(meta or {}, ensure_ascii=False) if meta else None
        
        try:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO exec_events 
                (ts_ms, symbol, event, state, order_id, broker_order_id, price, qty, fee, reason, liquidity, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts_ms,
                    symbol,
                    event,
                    state.value if state else None,
                    order_id,
                    broker_order_id,
                    price,
                    qty,
                    fee,
                    reason,
                    liquidity,
                    meta_json,
                ),
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"[ExecLogSink] Failed to write exec event: {e}")
            self.conn.rollback()
    
    def close(self):
        """关闭数据库连接"""
        self.conn.close()


def build_exec_log_sink(kind: str, output_dir: Path, db_name: str = "signals.db", use_outbox: bool = False) -> ExecLogSink:
    """构建执行日志Sink
    
    Args:
        kind: Sink类型（jsonl/sqlite/dual）
        output_dir: 输出目录
        db_name: 数据库文件名（仅SQLite使用）
        use_outbox: 是否使用Outbox模式（仅jsonl/dual）
        
    Returns:
        ExecLogSink实例
    """
    if kind == "jsonl":
        if use_outbox:
            from .exec_log_sink_outbox import JsonlExecLogSinkOutbox
            return JsonlExecLogSinkOutbox(output_dir)
        else:
            return JsonlExecLogSink(output_dir)
    elif kind == "sqlite":
        return SqliteExecLogSink(output_dir, db_name)
    elif kind == "dual":
        class DualExecLogSink(ExecLogSink):
            """双Sink（JSONL + SQLite）"""
            
            def __init__(self, output_dir: Path, db_name: str = "signals.db", use_outbox: bool = False):
                if use_outbox:
                    from .exec_log_sink_outbox import JsonlExecLogSinkOutbox
                    self.jsonl_sink = JsonlExecLogSinkOutbox(output_dir)
                else:
                    self.jsonl_sink = JsonlExecLogSink(output_dir)
                self.sqlite_sink = SqliteExecLogSink(output_dir, db_name)
            
            def write_event(self, *args, **kwargs):
                self.jsonl_sink.write_event(*args, **kwargs)
                self.sqlite_sink.write_event(*args, **kwargs)
            
            def flush(self):
                if hasattr(self.jsonl_sink, 'flush'):
                    self.jsonl_sink.flush()
            
            def close(self):
                if hasattr(self.jsonl_sink, 'close'):
                    self.jsonl_sink.close()
                self.sqlite_sink.close()
        
        return DualExecLogSink(output_dir, db_name, use_outbox)
    else:
        raise ValueError(f"Unknown sink kind: {kind}")

