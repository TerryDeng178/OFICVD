# -*- coding: utf-8 -*-
"""执行存储模块

提供幂等状态存储和执行记录管理
使用 SQLite 作为存储后端，支持高水位恢复
"""
import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging


logger = logging.getLogger(__name__)


@dataclass
class ExecutionRecord:
    """执行记录"""

    exec_ts_ms: int  # 执行时间戳
    signal_ts_ms: int  # 信号时间戳
    symbol: str
    signal_id: str
    order_id: str
    side: str  # "long"/"short"/"flat"/"skip"
    qty: float  # 执行数量（0表示仅记录观察信号）
    price: Optional[float]  # 执行价格
    gating: str  # 风控门状态（JSON字符串）
    guard_reason: Optional[str]  # 护栏原因
    status: str  # "success"/"skip"/"failed"/"retry"
    error_code: Optional[str] = None
    error_msg: Optional[str] = None
    meta_json: str = "{}"  # 额外元数据 JSON

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            "exec_ts_ms": self.exec_ts_ms,
            "signal_ts_ms": self.signal_ts_ms,
            "symbol": self.symbol,
            "signal_id": self.signal_id,
            "order_id": self.order_id,
            "side": self.side,
            "qty": self.qty,
            "price": self.price,
            "gating": self.gating,
            "guard_reason": self.guard_reason,
            "status": self.status,
            "error_code": self.error_code,
            "error_msg": self.error_msg,
            "meta_json": self.meta_json,
        }
        return result


class ExecutionStore:
    """执行存储管理器

    负责存储执行记录，维护幂等状态，支持高水位恢复
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # 线程锁保护数据库连接
        self._lock = threading.Lock()
        self._connection: Optional[sqlite3.Connection] = None

        # 初始化数据库
        self._init_db()

        # 高水位缓存
        self._high_water_marks: Dict[str, int] = {}
        self._load_high_water_marks()

    def _init_db(self) -> None:
        """初始化数据库和表结构"""
        with self._lock:
            self._connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._connection.execute("PRAGMA journal_mode=WAL")  # 启用 WAL 模式提高并发性能
            self._connection.execute("PRAGMA synchronous=NORMAL")  # 平衡性能和安全性

            # 创建执行记录表
            self._connection.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exec_ts_ms INTEGER NOT NULL,
                    signal_ts_ms INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    signal_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    price REAL,
                    gating TEXT NOT NULL,
                    guard_reason TEXT,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    error_msg TEXT,
                    meta_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL DEFAULT (strftime('%s', 'now') * 1000),

                    -- 幂等唯一索引
                    UNIQUE(symbol, signal_id, order_id)
                )
            """)

            # 创建索引以提高查询性能
            self._connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_executions_symbol_ts
                ON executions(symbol, signal_ts_ms)
            """)

            self._connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_executions_status
                ON executions(status)
            """)

            self._connection.commit()

    def _load_high_water_marks(self) -> None:
        """加载高水位标记"""
        try:
            with self._lock:
                cursor = self._connection.cursor()
                cursor.execute("""
                    SELECT symbol, MAX(signal_ts_ms) as max_ts
                    FROM executions
                    GROUP BY symbol
                """)

                for row in cursor.fetchall():
                    self._high_water_marks[row[0]] = row[1]

        except Exception as e:
            logger.warning(f"加载高水位标记失败: {e}")

    async def is_already_executed(self, symbol: str, signal_id: str, order_id: str) -> bool:
        """检查信号是否已经执行过"""
        def _check():
            with self._lock:
                cursor = self._connection.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM executions
                    WHERE symbol = ? AND signal_id = ? AND order_id = ?
                """, (symbol, signal_id, order_id))
                return cursor.fetchone()[0] > 0

        # 在线程池中执行数据库操作
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _check)

    async def record_execution(self, record: ExecutionRecord) -> None:
        """记录执行结果"""
        def _insert():
            with self._lock:
                try:
                    cursor = self._connection.cursor()
                    cursor.execute("""
                        INSERT OR IGNORE INTO executions
                        (exec_ts_ms, signal_ts_ms, symbol, signal_id, order_id, side, qty, price,
                         gating, guard_reason, status, error_code, error_msg, meta_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        record.exec_ts_ms,
                        record.signal_ts_ms,
                        record.symbol,
                        record.signal_id,
                        record.order_id,
                        record.side,
                        record.qty,
                        record.price,
                        record.gating,
                        record.guard_reason,
                        record.status,
                        record.error_code,
                        record.error_msg,
                        record.meta_json,
                    ))

                    # 如果是成功的插入，更新高水位
                    if cursor.rowcount > 0:
                        current_hw = self._high_water_marks.get(record.symbol, 0)
                        if record.signal_ts_ms > current_hw:
                            self._high_water_marks[record.symbol] = record.signal_ts_ms

                    self._connection.commit()
                    return cursor.rowcount > 0

                except sqlite3.IntegrityError:
                    # 唯一键冲突，说明已经存在
                    logger.debug(f"执行记录已存在: {record.symbol}/{record.signal_id}/{record.order_id}")
                    return False
                except Exception as e:
                    logger.error(f"记录执行失败: {e}")
                    self._connection.rollback()
                    raise

        # 在线程池中执行数据库操作
        loop = asyncio.get_event_loop()
        inserted = await loop.run_in_executor(None, _insert)

        if inserted:
            logger.debug(f"记录执行成功: {record.symbol}/{record.signal_id}")
        else:
            logger.debug(f"执行记录已存在，跳过: {record.symbol}/{record.signal_id}")

    def get_high_water_mark(self, symbol: str) -> int:
        """获取指定交易对的高水位标记"""
        return self._high_water_marks.get(symbol, 0)

    async def get_execution_stats(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """获取执行统计信息"""
        def _query():
            with self._lock:
                cursor = self._connection.cursor()

                # 构建查询条件
                where_clause = ""
                params = []
                if symbol:
                    where_clause = "WHERE symbol = ?"
                    params = [symbol]

                # 统计总数量
                cursor.execute(f"SELECT COUNT(*) FROM executions {where_clause}", params)
                total_count = cursor.fetchone()[0]

                # 按状态统计
                cursor.execute(f"""
                    SELECT status, COUNT(*) as count
                    FROM executions
                    {where_clause}
                    GROUP BY status
                """, params)

                status_counts = {row[0]: row[1] for row in cursor.fetchall()}

                # 获取最新的执行时间
                cursor.execute(f"""
                    SELECT MAX(exec_ts_ms) FROM executions {where_clause}
                """, params)
                latest_exec_ts = cursor.fetchone()[0] or 0

                # 获取最新的信号时间
                cursor.execute(f"""
                    SELECT MAX(signal_ts_ms) FROM executions {where_clause}
                """, params)
                latest_signal_ts = cursor.fetchone()[0] or 0

                return {
                    "total_executions": total_count,
                    "status_counts": status_counts,
                    "latest_exec_ts_ms": latest_exec_ts,
                    "latest_signal_ts_ms": latest_signal_ts,
                }

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _query)

    async def export_executions_to_jsonl(
        self,
        output_path: Path,
        symbol: Optional[str] = None,
        start_ts_ms: Optional[int] = None,
        end_ts_ms: Optional[int] = None
    ) -> int:
        """导出执行记录到 JSONL 文件"""
        def _export():
            with self._lock:
                cursor = self._connection.cursor()

                # 构建查询条件
                conditions = []
                params = []

                if symbol:
                    conditions.append("symbol = ?")
                    params.append(symbol)

                if start_ts_ms is not None:
                    conditions.append("signal_ts_ms >= ?")
                    params.append(start_ts_ms)

                if end_ts_ms is not None:
                    conditions.append("signal_ts_ms <= ?")
                    params.append(end_ts_ms)

                where_clause = " AND ".join(conditions) if conditions else ""

                query = f"""
                    SELECT * FROM executions
                    {"WHERE " + where_clause if where_clause else ""}
                    ORDER BY exec_ts_ms ASC
                """

                cursor.execute(query, params)

                # 确保输出目录存在
                output_path.parent.mkdir(parents=True, exist_ok=True)

                count = 0
                with open(output_path, "w", encoding="utf-8") as f:
                    for row in cursor.fetchall():
                        # 将行转换为字典
                        record_dict = {
                            "id": row[0],
                            "exec_ts_ms": row[1],
                            "signal_ts_ms": row[2],
                            "symbol": row[3],
                            "signal_id": row[4],
                            "order_id": row[5],
                            "side": row[6],
                            "qty": row[7],
                            "price": row[8],
                            "gating": row[9],
                            "guard_reason": row[10],
                            "status": row[11],
                            "error_code": row[12],
                            "error_msg": row[13],
                            "meta_json": row[14],
                            "created_at": row[15],
                        }

                        # 解析 meta_json
                        try:
                            record_dict["meta"] = json.loads(row[14])
                        except json.JSONDecodeError:
                            record_dict["meta"] = {}

                        # 写入 JSONL
                        f.write(json.dumps(record_dict, ensure_ascii=False) + "\n")
                        count += 1

                return count

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _export)

    async def close(self) -> None:
        """关闭存储管理器"""
        def _close():
            with self._lock:
                if self._connection:
                    try:
                        self._connection.close()
                        self._connection = None
                    except Exception as e:
                        logger.warning(f"关闭数据库连接失败: {e}")

        if self._connection:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _close)

    def __del__(self):
        """析构函数，确保连接被关闭"""
        if hasattr(self, '_connection') and self._connection:
            try:
                self._connection.close()
            except:
                pass
