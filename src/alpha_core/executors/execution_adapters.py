# -*- coding: utf-8 -*-
"""执行适配器模块

定义执行层适配器接口，实现 DryRun 和 Live 执行模式
"""
import asyncio
import time
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass

from ..executors.base_executor import ExecResult, ExecResultStatus

logger = logging.getLogger(__name__)


@dataclass
class ExecutionRequest:
    """执行请求"""

    symbol: str
    side: str  # long | short | flat | skip
    quantity: float
    price: Optional[float]
    client_order_id: str
    signal_id: str


class ExecutionAdapter(ABC):
    """执行适配器抽象基类"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    async def send_order(self, request: ExecutionRequest) -> ExecResult:
        """发送执行请求

        Args:
            request: 执行请求

        Returns:
            执行结果
        """
        pass

    async def health_check(self) -> bool:
        """健康检查

        Returns:
            是否健康
        """
        return True


class DryRunExecutionAdapter(ExecutionAdapter):
    """DryRun 执行适配器

    不实际执行订单，仅返回模拟结果，用于测试和验证业务逻辑
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.logger.info("初始化 DryRun 执行适配器")

    async def send_order(self, request: ExecutionRequest) -> ExecResult:
        """模拟执行订单

        Args:
            request: 执行请求

        Returns:
            模拟的执行结果
        """
        # 模拟网络延迟
        await asyncio.sleep(0.01)

        # 记录请求
        self.logger.debug(f"[DryRun] 执行请求: {request.symbol} {request.side} {request.quantity}")

        # 如果是 skip，直接返回成功（不执行任何操作）
        if request.side == "skip":
            return ExecResult(
                status=ExecResultStatus.ACCEPTED,
                client_order_id=request.client_order_id,
                sent_ts_ms=int(time.time() * 1000),
                latency_ms=10,
                meta={"dry_run": True, "reason": "skip_signal"}
            )

        # 简单的验证逻辑
        if request.quantity <= 0:
            return ExecResult(
                status=ExecResultStatus.REJECTED,
                client_order_id=request.client_order_id,
                reject_reason="invalid_quantity",
                sent_ts_ms=int(time.time() * 1000),
                latency_ms=10,
                meta={"dry_run": True, "error": "quantity_must_be_positive"}
            )

        if request.side not in ["long", "short", "flat"]:
            return ExecResult(
                status=ExecResultStatus.REJECTED,
                client_order_id=request.client_order_id,
                reject_reason="invalid_side",
                sent_ts_ms=int(time.time() * 1000),
                latency_ms=10,
                meta={"dry_run": True, "error": "invalid_side_value"}
            )

        # 模拟成功执行
        exec_price = request.price if request.price else 50000.0  # 模拟价格

        return ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id=request.client_order_id,
            exchange_order_id=f"dryrun_{request.client_order_id}_{int(time.time())}",
            sent_ts_ms=int(time.time() * 1000),
            ack_ts_ms=int(time.time() * 1000) + 5,
            latency_ms=15,
            slippage_bps=0.0,  # DryRun 没有滑点
            meta={
                "dry_run": True,
                "simulated_price": exec_price,
                "execution_mode": "dry_run"
            }
        )


class LiveExecutionAdapter(ExecutionAdapter):
    """真实执行适配器

    实际连接交易所执行订单
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.logger.info("初始化 Live 执行适配器")

        # TODO: 初始化真实的交易所连接
        # 这里需要集成现有的 BaseAdapter 或直接调用 Binance API

    async def send_order(self, request: ExecutionRequest) -> ExecResult:
        """真实执行订单

        Args:
            request: 执行请求

        Returns:
            实际的执行结果
        """
        # TODO: 实现真实的下单逻辑
        # 需要：
        # 1. 将 ExecutionRequest 转换为 AdapterOrder
        # 2. 调用现有的 BaseAdapter.submit() 方法
        # 3. 处理响应并转换为 ExecResult

        raise NotImplementedError("Live execution adapter not implemented yet")


def create_execution_adapter(mode: str, config: Optional[Dict[str, Any]] = None) -> ExecutionAdapter:
    """创建执行适配器的工厂函数

    Args:
        mode: 执行模式 ("dry_run" | "live")
        config: 适配器配置

    Returns:
        执行适配器实例
    """
    if mode == "dry_run":
        return DryRunExecutionAdapter(config)
    elif mode == "live":
        return LiveExecutionAdapter(config)
    else:
        raise ValueError(f"不支持的执行模式: {mode}")
