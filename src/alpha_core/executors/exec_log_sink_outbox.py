# -*- coding: utf-8 -*-
"""Execution Log Sink with Outbox Pattern

执行日志Outbox模式：spool/.part → ready/.jsonl 原子发布
支持Windows友好的重试机制
"""
import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

from .base_executor import OrderCtx, Order, Fill, OrderState, ExecResult

logger = logging.getLogger(__name__)


def _atomic_move_with_retry(src: Path, dst: Path, max_retries: int = 3, retry_delay: float = 0.1) -> bool:
    """原子移动文件（Windows友好重试）
    
    Args:
        src: 源文件路径
        dst: 目标文件路径
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
        
    Returns:
        是否成功
    """
    for attempt in range(max_retries):
        try:
            # 确保目标目录存在
            dst.parent.mkdir(parents=True, exist_ok=True)
            
            # Windows上使用replace而不是rename，避免句柄占用问题
            if os.name == 'nt':  # Windows
                # 如果目标文件存在，先删除
                if dst.exists():
                    dst.unlink()
                # 使用shutil.move（内部使用replace）
                shutil.move(str(src), str(dst))
            else:
                # Unix/Linux使用rename（原子操作）
                src.replace(dst)
            
            return True
        except (OSError, PermissionError) as e:
            if attempt < max_retries - 1:
                logger.debug(f"[AtomicMove] Retry {attempt + 1}/{max_retries}: {e}")
                time.sleep(retry_delay * (attempt + 1))  # 指数退避
            else:
                logger.error(f"[AtomicMove] Failed after {max_retries} attempts: {e}")
                return False
    return False


class JsonlExecLogSinkOutbox:
    """JSONL执行日志Sink（Outbox模式）
    
    采用spool/.part → ready/.jsonl原子发布模式
    事件Schema符合executor_contract/v1规范
    """
    
    def __init__(self, output_dir: Path, fsync_every_n: int = 100):
        """初始化Outbox模式的JSONL Sink
        
        Args:
            output_dir: 输出目录
            fsync_every_n: 每N次写入执行一次fsync
        """
        self.output_dir = Path(output_dir)
        self.spool_root = self.output_dir / "spool" / "execlog"
        self.ready_root = self.output_dir / "ready" / "execlog"
        self.spool_root.mkdir(parents=True, exist_ok=True)
        self.ready_root.mkdir(parents=True, exist_ok=True)
        
        self.fsync_every_n = fsync_every_n
        self._write_count = 0
        self._current_file: Optional[Path] = None
        self._current_file_handle = None
        self._current_minute: Optional[str] = None
        self._pending_files: List[Path] = []  # 待发布的文件列表
        
        logger.info(
            f"[JsonlExecLogSinkOutbox] Initialized: spool={self.spool_root}, "
            f"ready={self.ready_root}, fsync_every_n={self.fsync_every_n}"
        )
    
    def _get_file_path(self, ts_ms: int, symbol: str) -> tuple:
        """获取spool和ready文件路径
        
        Args:
            ts_ms: 时间戳（ms）
            symbol: 交易对
            
        Returns:
            (spool_file, ready_file) 路径元组
        """
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        minute = dt.strftime("%Y%m%d_%H%M")
        
        symbol_dir_spool = self.spool_root / symbol
        symbol_dir_ready = self.ready_root / symbol
        symbol_dir_spool.mkdir(parents=True, exist_ok=True)
        symbol_dir_ready.mkdir(parents=True, exist_ok=True)
        
        spool_file = symbol_dir_spool / f"exec_{minute}.part"
        ready_file = symbol_dir_ready / f"exec_{minute}.jsonl"
        
        return spool_file, ready_file
    
    def _rotate_file_if_needed(self, spool_file: Path) -> None:
        """如果需要，轮转文件（关闭旧文件并发布到ready）
        
        Args:
            spool_file: 当前spool文件路径
        """
        # 如果文件切换了，需要关闭并发布旧文件
        if self._current_file and self._current_file != spool_file:
            self._close_and_publish_file(self._current_file)
            self._current_file = None
        
        # 打开新文件
        if self._current_file != spool_file:
            self._current_file = spool_file
            if self._current_file_handle:
                self._current_file_handle.close()
                self._current_file_handle = None
            self._current_file_handle = self._current_file.open("a", encoding="utf-8", newline="")
    
    def _close_and_publish_file(self, spool_file: Path) -> None:
        """关闭spool文件并发布到ready目录
        
        Args:
            spool_file: spool文件路径
        """
        if self._current_file_handle and self._current_file == spool_file:
            # 确保最后一批数据fsync
            if self._write_count > 0:
                self._current_file_handle.flush()
                os.fsync(self._current_file_handle.fileno())
                self._write_count = 0
            
            self._current_file_handle.close()
            self._current_file_handle = None
        
        # 构建ready文件路径
        # spool_file格式：spool/execlog/{symbol}/exec_{minute}.part
        # ready_file格式：ready/execlog/{symbol}/exec_{minute}.jsonl
        symbol = spool_file.parent.name
        minute = spool_file.stem.replace("exec_", "")
        ready_file = self.ready_root / symbol / f"exec_{minute}.jsonl"
        
        # 原子移动到ready目录
        if spool_file.exists() and spool_file.stat().st_size > 0:
            if _atomic_move_with_retry(spool_file, ready_file):
                logger.debug(f"[JsonlExecLogSinkOutbox] Published: {spool_file} -> {ready_file}")
            else:
                logger.error(f"[JsonlExecLogSinkOutbox] Failed to publish: {spool_file}")
                # 保留在spool目录，等待下次重试
                self._pending_files.append(spool_file)
    
    def write_event(
        self,
        ts_ms: int,
        symbol: str,
        event: str,
        order_ctx: Optional[OrderCtx] = None,
        order: Optional[Order] = None,
        fill: Optional[Fill] = None,
        exec_result: Optional[ExecResult] = None,
        state: Optional[OrderState] = None,
        reason: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """写入执行事件（Outbox模式）
        
        Args:
            ts_ms: 时间戳（ms）
            symbol: 交易对
            event: 事件类型（submit/ack/partial/filled/canceled/rejected）
            order_ctx: 订单上下文（可选，包含上游状态）
            order: 订单对象（可选，向后兼容）
            fill: 成交对象（可选）
            exec_result: 执行结果（可选）
            state: 订单状态（可选）
            reason: 拒绝原因（可选）
            meta: 元数据（可选）
        """
        # 构建事件记录（符合executor_contract/v1 Schema）
        record: Dict[str, Any] = {
            "ts_ms": ts_ms,
            "symbol": symbol,
            "event": event,
            "status": state.value if state else None,
            "reason": reason,
        }
        
        # 从order_ctx提取字段（优先）
        if order_ctx:
            record["signal_row_id"] = order_ctx.signal_row_id
            record["client_order_id"] = order_ctx.client_order_id
            record["side"] = order_ctx.side.value
            record["qty"] = order_ctx.qty
            
            # 价格字段
            if order_ctx.price is not None:
                record["px_intent"] = order_ctx.price  # 意图价格
                record["px_sent"] = order_ctx.price    # 发送价格（初始等于意图价格）
            else:
                record["px_intent"] = None
                record["px_sent"] = None
            
            # 时间戳字段
            record["sent_ts_ms"] = order_ctx.ts_ms or ts_ms
            record["event_ts_ms"] = order_ctx.event_ts_ms
            
            # 上游状态字段
            if order_ctx.warmup:
                record["warmup"] = True
            if order_ctx.guard_reason:
                record["guard_reason"] = order_ctx.guard_reason
            if order_ctx.consistency is not None:
                record["consistency"] = order_ctx.consistency
            if order_ctx.scenario:
                record["scenario"] = order_ctx.scenario
            if order_ctx.regime:
                record["regime"] = order_ctx.regime
        elif order:
            # 向后兼容：从order对象提取
            record["client_order_id"] = order.client_order_id
            record["side"] = order.side.value
            record["qty"] = order.qty
            if order.price is not None:
                record["px_intent"] = order.price
                record["px_sent"] = order.price
            record["sent_ts_ms"] = order.ts_ms or ts_ms
        
        # 从exec_result提取字段
        if exec_result:
            record["exchange_order_id"] = exec_result.exchange_order_id
            if exec_result.reject_reason:
                record["reason"] = exec_result.reject_reason
            if exec_result.latency_ms is not None:
                record["latency_ms"] = exec_result.latency_ms
            if exec_result.slippage_bps is not None:
                record["slippage_bps"] = exec_result.slippage_bps
            if exec_result.rounding_applied:
                record["rounding_diff"] = exec_result.rounding_applied
            if exec_result.ack_ts_ms is not None:
                record["ack_ts_ms"] = exec_result.ack_ts_ms
        
        # 从fill提取成交信息
        if fill:
            record["px_fill"] = fill.price
            record["fill_qty"] = fill.qty
            record["fill_ts_ms"] = fill.ts_ms
            record["fee"] = fill.fee
            record["liquidity"] = fill.liquidity
            if fill.broker_order_id:
                record["exchange_order_id"] = fill.broker_order_id
        
        # 元数据
        if meta:
            record["meta"] = meta
        else:
            record["meta"] = {}
        
        # 添加模式标识
        record["meta"]["_writer"] = "exec_jsonl_outbox_v1"
        
        # 获取文件路径
        spool_file, ready_file = self._get_file_path(ts_ms, symbol)
        
        # 轮转文件（如果需要）
        self._rotate_file_if_needed(spool_file)
        
        # 写入spool文件
        serialized = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        self._current_file_handle.write(serialized + "\n")
        self._write_count += 1
        
        # 按批次fsync
        if self._write_count >= self.fsync_every_n:
            self._current_file_handle.flush()
            os.fsync(self._current_file_handle.fileno())
            self._write_count = 0
        else:
            self._current_file_handle.flush()
        
        # 如果文件大小达到阈值（例如10MB），提前发布
        try:
            if self._current_file and self._current_file.exists() and self._current_file.stat().st_size > 10 * 1024 * 1024:  # 10MB
                self._close_and_publish_file(spool_file)
                self._current_file = None
        except (OSError, AttributeError):
            # 文件可能不存在或无法访问，忽略
            pass
    
    def flush(self) -> None:
        """刷新并发布所有待发布文件"""
        # 关闭当前文件并发布
        if self._current_file:
            self._close_and_publish_file(self._current_file)
            self._current_file = None
        
        # 重试发布pending文件
        retry_files = self._pending_files.copy()
        self._pending_files.clear()
        
        for spool_file in retry_files:
            if spool_file.exists():
                self._close_and_publish_file(spool_file)
    
    def close(self) -> None:
        """关闭Sink，发布所有文件"""
        self.flush()
        
        if self._current_file_handle:
            self._current_file_handle.close()
            self._current_file_handle = None
        
        logger.info("[JsonlExecLogSinkOutbox] Closed")


def create_exec_log_sink_outbox(output_dir: Path, fsync_every_n: int = 100) -> JsonlExecLogSinkOutbox:
    """创建Outbox模式的执行日志Sink
    
    Args:
        output_dir: 输出目录
        fsync_every_n: 每N次写入执行一次fsync
        
    Returns:
        JsonlExecLogSinkOutbox实例
    """
    return JsonlExecLogSinkOutbox(output_dir, fsync_every_n)

