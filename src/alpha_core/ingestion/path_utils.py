# -*- coding: utf-8 -*-
"""
统一路径构造器 - HARVEST 数据目录规范实现
"""
from __future__ import annotations

import os
import re
import uuid
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone, tzinfo
from typing import Literal

Layer = Literal["raw", "preview"]

KIND_RAW = {"prices", "orderbook", "aggtrade", "depth"}
KIND_PREVIEW = {"ofi", "cvd", "fusion", "divergence", "events", "features"}


def norm_symbol(s: str) -> str:
    """标准化symbol名称（全小写，移除非法字符）"""
    s = s.strip().lower()
    return re.sub(r"[^a-z0-9_]", "", s)


def _tz(tzname: str) -> tzinfo:
    """解析时区名称"""
    if tzname.upper() == "UTC":
        return timezone.utc
    # 如需本地时区可扩展解析，这里固定 UTC 为规范
    return timezone.utc


class PathBuilder:
    """统一路径构造器"""
    
    def __init__(self, data_root: str, artifacts_root: str, tzname: str = "UTC"):
        """
        初始化路径构造器
        
        Args:
            data_root: 数据根目录
            artifacts_root: 工件根目录
            tzname: 时区名称（默认UTC）
        """
        self.data_root = Path(data_root)
        self.artifacts_root = Path(artifacts_root)
        self.tz = _tz(tzname)
        self.writerid = uuid.uuid4().hex[:8]  # 每个实例使用固定的writerid
    
    def partition(self, ts_ms: int):
        """
        根据时间戳生成分区路径组件
        
        Args:
            ts_ms: 时间戳（毫秒）
            
        Returns:
            (date_str, hour_str): 例如 ("date=2025-11-06", "hour=18")
        """
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=self.tz)
        return f"date={dt.strftime('%Y-%m-%d')}", f"hour={dt.strftime('%H')}"
    
    def data_dir(self, layer: Layer, ts_ms: int, symbol: str, kind: str) -> Path:
        """
        生成数据目录路径
        
        Args:
            layer: 层（raw/preview）
            ts_ms: 时间戳（毫秒）
            symbol: 交易对符号
            kind: 数据类型
            
        Returns:
            Path对象
        """
        symbol = norm_symbol(symbol)
        d, h = self.partition(ts_ms)
        return self.data_root / layer / d / h / f"symbol={symbol}" / f"kind={kind}"
    
    def part_paths(self, layer: Layer, start_ms: int, end_ms: int,
                   symbol: str, kind: str, rows: int, writerid: str | None = None):
        """
        生成part文件路径（parquet、sidecar、tmp）
        
        Args:
            layer: 层（raw/preview）
            start_ms: 开始时间戳（毫秒）
            end_ms: 结束时间戳（毫秒）
            symbol: 交易对符号
            kind: 数据类型
            rows: 行数
            writerid: 写入器ID（可选，默认使用实例的writerid）
            
        Returns:
            (parquet_path, sidecar_path, tmp_path): 三个Path对象
        """
        writerid = writerid or self.writerid
        base = self.data_dir(layer, start_ms, symbol, kind)
        base.mkdir(parents=True, exist_ok=True)
        stem = f"part-{start_ms}-{end_ms}-{rows}-{writerid}"
        return base / f"{stem}.parquet", base / f"{stem}.sidecar.json", base / f"{stem}.tmp"
    
    def dq_report_path(self, ts_ms: int, symbol: str, kind: str, writerid: str | None = None):
        """
        生成DQ报告路径
        
        Args:
            ts_ms: 时间戳（毫秒）
            symbol: 交易对符号
            kind: 数据类型
            writerid: 写入器ID（可选）
            
        Returns:
            Path对象
        """
        writerid = writerid or self.writerid
        symbol = norm_symbol(symbol)
        d, h = self.partition(ts_ms)
        p = self.artifacts_root / "dq_reports" / d / h / f"symbol={symbol}" / f"kind={kind}"
        p.mkdir(parents=True, exist_ok=True)
        return p / f"dq-{ts_ms}-{writerid}.json"
    
    def deadletter_path(self, ts_ms: int, symbol: str, kind: str, writerid: str | None = None):
        """
        生成死信目录路径
        
        Args:
            ts_ms: 时间戳（毫秒）
            symbol: 交易对符号
            kind: 数据类型
            writerid: 写入器ID（可选）
            
        Returns:
            Path对象
        """
        writerid = writerid or self.writerid
        symbol = norm_symbol(symbol)
        d, h = self.partition(ts_ms)
        p = self.artifacts_root / "deadletter" / d / h / f"symbol={symbol}" / f"kind={kind}"
        p.mkdir(parents=True, exist_ok=True)
        return p / f"bad-{ts_ms}-{writerid}.ndjson"
    
    @staticmethod
    def sha1(path: Path) -> str:
        """
        计算文件SHA1哈希值
        
        Args:
            path: 文件路径
            
        Returns:
            SHA1哈希值（十六进制字符串）
        """
        h = hashlib.sha1()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    
    def get_writerid(self) -> str:
        """获取当前实例的writerid"""
        return self.writerid

