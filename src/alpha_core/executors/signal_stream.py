# -*- coding: utf-8 -*-
"""信号流抽象模块

实现从 signal_server 产物中持续拉取信号的抽象接口
支持 JSONL 和 SQLite 两种存储格式
"""
import asyncio
import json
import os
import sqlite3
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExecutionSignal:
    """执行信号数据结构"""

    ts_ms: int
    symbol: str
    score: float
    z_ofi: float
    z_cvd: float
    regime: str
    div_type: str
    confirm: bool
    gating: str
    guard_reason: Optional[str]
    signal_id: str  # 幂等键

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionSignal":
        """从字典创建执行信号"""
        return cls(
            ts_ms=data["ts_ms"],
            symbol=data["symbol"],
            score=data["score"],
            z_ofi=data["z_ofi"],
            z_cvd=data["z_cvd"],
            regime=data["regime"],
            div_type=data["div_type"],
            confirm=data["confirm"],
            gating=data["gating"],
            guard_reason=data.get("guard_reason"),
            signal_id=cls._generate_signal_id(data),
        )

    @staticmethod
    def _generate_signal_id(data: Dict[str, Any]) -> str:
        """生成信号幂等ID"""
        # 使用 harvester 的 stable_row_id 思路
        key_parts = [
            data["symbol"],
            str(data["ts_ms"]),
            ".4f",  # 格式化分数到4位小数
            data["regime"],
            data["div_type"],
        ]
        key_string = "|".join(key_parts)
        # 使用简单的哈希而不是导入额外依赖
        import hashlib
        return hashlib.md5(key_string.encode("utf-8")).hexdigest()[:16]


class SignalStream(ABC):
    """信号流抽象基类"""

    def __init__(self, base_dir: str, symbols: List[str]):
        self.base_dir = Path(base_dir)
        self.symbols = symbols
        self._high_water_marks: Dict[str, int] = {}  # symbol -> max_ts_ms

    @abstractmethod
    async def iter_signals(self, symbol: str) -> AsyncIterator[ExecutionSignal]:
        """异步迭代指定交易对的信号"""
        pass

    def get_high_water_mark(self, symbol: str) -> int:
        """获取指定交易对的高水位标记"""
        return self._high_water_marks.get(symbol, 0)

    def update_high_water_mark(self, symbol: str, ts_ms: int) -> None:
        """更新指定交易对的高水位标记"""
        self._high_water_marks[symbol] = max(
            self._high_water_marks.get(symbol, 0), ts_ms
        )


class JsonlSignalStream(SignalStream):
    """JSONL 文件信号流实现"""

    async def iter_signals(self, symbol: str) -> AsyncIterator[ExecutionSignal]:
        """从 JSONL 文件中异步迭代信号"""
        signal_dir = self.base_dir / "ready" / "signal" / symbol

        if not signal_dir.exists():
            logger.warning(f"信号目录不存在: {signal_dir}")
            return

        # 获取所有信号文件，按时间排序
        jsonl_files = sorted(signal_dir.glob("signals_*.jsonl"))

        high_water = self.get_high_water_mark(symbol)

        for jsonl_file in jsonl_files:
            try:
                async for signal in self._iter_file_signals(jsonl_file, high_water):
                    yield signal
                    # 更新高水位
                    self.update_high_water_mark(symbol, signal.ts_ms)

            except Exception as e:
                logger.error(f"处理信号文件失败 {jsonl_file}: {e}")
                continue

    async def _iter_file_signals(
        self, file_path: Path, high_water: int
    ) -> AsyncIterator[ExecutionSignal]:
        """迭代单个 JSONL 文件中的信号"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        signal = ExecutionSignal.from_dict(data)

                        # 跳过已处理过的信号
                        if signal.ts_ms <= high_water:
                            continue

                        yield signal

                    except json.JSONDecodeError as e:
                        logger.warning(f"解析JSON行失败 {file_path}:{line_num}: {e}")
                        continue
                    except KeyError as e:
                        logger.warning(f"信号数据缺少必要字段 {file_path}:{line_num}: {e}")
                        continue

        except FileNotFoundError:
            logger.debug(f"信号文件不存在: {file_path}")
        except Exception as e:
            logger.error(f"读取信号文件失败 {file_path}: {e}")


class SqliteSignalStream(SignalStream):
    """SQLite 数据库信号流实现"""

    def __init__(self, base_dir: str, symbols: List[str], db_name: str = "signals.db"):
        super().__init__(base_dir, symbols)
        self.db_path = self.base_dir / db_name
        self._connections: Dict[str, sqlite3.Connection] = {}

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接（复用连接）"""
        conn_key = str(self.db_path)
        if conn_key not in self._connections:
            self._connections[conn_key] = sqlite3.connect(
                str(self.db_path), check_same_thread=False
            )
            # 设置行工厂
            self._connections[conn_key].row_factory = sqlite3.Row
        return self._connections[conn_key]

    async def iter_signals(self, symbol: str) -> AsyncIterator[ExecutionSignal]:
        """从 SQLite 数据库中异步迭代信号"""
        if not self.db_path.exists():
            logger.warning(f"信号数据库不存在: {self.db_path}")
            return

        conn = self._get_connection()
        high_water = self.get_high_water_mark(symbol)

        try:
            # 查询指定交易对的新信号
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM signals
                WHERE symbol = ? AND ts_ms > ?
                ORDER BY ts_ms ASC, id ASC
            """, (symbol, high_water))

            for row in cursor.fetchall():
                try:
                    data = dict(row)
                    signal = ExecutionSignal.from_dict(data)

                    yield signal

                    # 更新高水位
                    self.update_high_water_mark(symbol, signal.ts_ms)

                except Exception as e:
                    logger.error(f"处理信号记录失败 id={row['id']}: {e}")
                    continue

        except sqlite3.Error as e:
            logger.error(f"查询信号数据库失败: {e}")
        except Exception as e:
            logger.error(f"处理信号数据库失败: {e}")

    def close(self):
        """关闭所有数据库连接"""
        for conn in self._connections.values():
            try:
                conn.close()
            except Exception as e:
                logger.warning(f"关闭数据库连接失败: {e}")
        self._connections.clear()


def create_signal_stream(
    sink_type: str, base_dir: str, symbols: List[str], **kwargs
) -> SignalStream:
    """创建信号流实例的工厂函数"""

    if sink_type.lower() == "jsonl":
        return JsonlSignalStream(base_dir, symbols)
    elif sink_type.lower() == "sqlite":
        db_name = kwargs.get("db_name", "signals.db")
        return SqliteSignalStream(base_dir, symbols, db_name)
    else:
        raise ValueError(f"不支持的 sink 类型: {sink_type}")
