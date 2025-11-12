# -*- coding: utf-8 -*-
"""IExecutor Abstract Interface

执行层抽象接口：统一回测/测试网/实盘执行接口
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any


class Side(str, Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(str, Enum):
    """订单有效期"""
    GTC = "GTC"  # Good Till Cancel
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill


class OrderState(str, Enum):
    """订单状态"""
    NEW = "new"
    ACK = "ack"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


class ExecResultStatus(str, Enum):
    """执行结果状态"""
    ACCEPTED = "accepted"  # 已接受
    REJECTED = "rejected"  # 已拒绝


@dataclass
class ExecResult:
    """执行结果
    
    单一事实来源：字段定义以docs/api_contracts.md executor_contract/v1为准
    """
    status: ExecResultStatus  # 执行状态
    client_order_id: str  # 客户端订单ID
    exchange_order_id: Optional[str] = None  # 交易所订单ID
    reject_reason: Optional[str] = None  # 拒绝原因（如果被拒绝）
    latency_ms: Optional[int] = None  # 延迟（ms，从提交到ACK）
    slippage_bps: Optional[float] = None  # 滑点（基点）
    rounding_applied: Optional[Dict[str, float]] = None  # 价格/数量对齐调整（price_diff, qty_diff）
    sent_ts_ms: Optional[int] = None  # 发送时间戳（ms）
    ack_ts_ms: Optional[int] = None  # ACK时间戳（ms）
    meta: Dict[str, Any] = field(default_factory=dict)  # 其他元数据


@dataclass
class CancelResult:
    """撤销结果
    
    单一事实来源：字段定义以docs/api_contracts.md executor_contract/v1为准
    """
    success: bool  # 是否成功
    client_order_id: str  # 客户端订单ID
    exchange_order_id: Optional[str] = None  # 交易所订单ID
    reason: Optional[str] = None  # 失败原因（如果失败）
    latency_ms: Optional[int] = None  # 延迟（ms）
    cancel_ts_ms: Optional[int] = None  # 撤销时间戳（ms）
    meta: Dict[str, Any] = field(default_factory=dict)  # 其他元数据


@dataclass
class AmendResult:
    """修改结果（预留，当前未实现）
    
    单一事实来源：字段定义以docs/api_contracts.md executor_contract/v1为准
    """
    success: bool  # 是否成功
    client_order_id: str  # 客户端订单ID
    exchange_order_id: Optional[str] = None  # 交易所订单ID
    reason: Optional[str] = None  # 失败原因（如果失败）
    latency_ms: Optional[int] = None  # 延迟（ms）
    amend_ts_ms: Optional[int] = None  # 修改时间戳（ms）
    meta: Dict[str, Any] = field(default_factory=dict)  # 其他元数据


@dataclass
class Order:
    """订单数据结构（基础版本）
    
    单一事实来源：字段定义以docs/api_contracts.md为准
    注意：推荐使用OrderCtx（包含上游状态字段）进行执行决策
    """
    client_order_id: str  # 客户端订单ID（幂等键）
    symbol: str  # 交易对，如 BTCUSDT（大写，统一）
    side: Side  # 方向：buy/sell
    qty: float  # 数量（与交易所精度、步长对齐）
    # 以下字段有默认值，必须放在最后
    order_type: OrderType = OrderType.MARKET  # 订单类型
    price: Optional[float] = None  # 限价单价格
    tif: TimeInForce = TimeInForce.GTC  # 订单有效期
    ts_ms: int = 0  # 本地决定时间戳（ms）
    metadata: Dict[str, Any] = field(default_factory=dict)  # 上下文信息（可选）


@dataclass
class OrderCtx:
    """订单上下文（扩展版本，包含上游状态字段）
    
    用于执行决策，包含来自信号层的状态信息
    单一事实来源：字段定义以docs/api_contracts.md executor_contract/v1为准
    """
    # 基础订单字段
    client_order_id: str  # 客户端订单ID（幂等键：hash(signal_row_id|ts_ms|side|qty|px)）
    symbol: str  # 交易对，如 BTCUSDT（大写，统一）
    side: Side  # 方向：buy/sell
    qty: float  # 数量（与交易所精度、步长对齐）
    order_type: OrderType = OrderType.MARKET  # 订单类型
    price: Optional[float] = None  # 限价单价格
    tif: TimeInForce = TimeInForce.GTC  # 订单有效期
    
    # 时间戳字段
    ts_ms: int = 0  # 本地决定时间戳（ms）
    event_ts_ms: Optional[int] = None  # 事件时间戳（ms，来自上游信号）
    
    # 上游状态字段（来自信号层）
    signal_row_id: Optional[str] = None  # 信号行ID（用于追溯）
    regime: Optional[str] = None  # 市场状态：active/quiet
    scenario: Optional[str] = None  # 场景标识（2x2场景：HH/HL/LH/LL）
    warmup: bool = False  # 是否在暖启动阶段
    guard_reason: Optional[str] = None  # 护栏原因（逗号分隔，如"warmup,low_consistency"）
    consistency: Optional[float] = None  # 一致性分数（0.0-1.0）
    weak_signal_throttle: bool = False  # 是否因弱信号被节流
    
    # 交易所约束字段
    tick_size: Optional[float] = None  # 价格精度（最小变动单位）
    step_size: Optional[float] = None  # 数量精度（最小变动单位）
    min_notional: Optional[float] = None  # 最小名义价值
    
    # 成本字段
    costs_bps: Optional[float] = None  # 预期成本（基点）
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)  # 其他上下文信息
    
    def to_order(self) -> Order:
        """转换为基础Order对象（向后兼容）"""
        return Order(
            client_order_id=self.client_order_id,
            symbol=self.symbol,
            side=self.side,
            qty=self.qty,
            order_type=self.order_type,
            price=self.price,
            tif=self.tif,
            ts_ms=self.ts_ms,
            metadata=self.metadata.copy()
        )


@dataclass
class Fill:
    """成交数据结构
    
    单一事实来源：字段定义以docs/api_contracts.md为准
    """
    ts_ms: int  # 成交时间戳（ms）
    symbol: str  # 交易对
    client_order_id: str  # 客户端订单ID
    price: float  # 成交价格
    qty: float  # 成交数量
    # 以下字段有默认值，必须放在最后
    broker_order_id: Optional[str] = None  # 交易所订单ID
    fee: float = 0.0  # 手续费
    liquidity: str = "unknown"  # 流动性类型：maker/taker/unknown
    side: Optional[Side] = None  # 方向（冗余字段，便于查询）


class IExecutor(ABC):
    """执行器抽象接口
    
    统一回测/测试网/实盘执行接口，隔离执行差异
    """
    
    @abstractmethod
    def prepare(self, cfg: Dict[str, Any]) -> None:
        """初始化执行器
        
        Args:
            cfg: 配置字典，包含executor配置段
        """
        pass
    
    @abstractmethod
    def submit(self, order: Order) -> str:
        """提交订单（基础接口，向后兼容）
        
        Args:
            order: 订单对象
            
        Returns:
            broker_order_id: 交易所订单ID（回测模式下返回client_order_id）
        """
        pass
    
    def submit_with_ctx(self, order_ctx: OrderCtx) -> ExecResult:
        """提交订单（扩展接口，包含上游状态）
        
        Args:
            order_ctx: 订单上下文（包含上游状态字段）
            
        Returns:
            ExecResult: 执行结果
            
        注意：默认实现调用submit()，子类可重写以利用上游状态
        """
        # 默认实现：转换为基础Order并调用submit()
        # 子类应重写此方法以实现前置检查逻辑
        order = order_ctx.to_order()
        broker_order_id = self.submit(order)
        
        # 构建ExecResult
        import time
        ack_ts_ms = int(time.time() * 1000)
        latency_ms = ack_ts_ms - (order_ctx.ts_ms or ack_ts_ms)
        
        return ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id=order_ctx.client_order_id,
            exchange_order_id=broker_order_id,
            sent_ts_ms=order_ctx.ts_ms,
            ack_ts_ms=ack_ts_ms,
            latency_ms=latency_ms if latency_ms > 0 else None,
        )
    
    @abstractmethod
    def cancel(self, order_id: str) -> bool:
        """撤销订单（基础接口，向后兼容）
        
        Args:
            order_id: 订单ID（client_order_id或broker_order_id）
            
        Returns:
            是否撤销成功
        """
        pass
    
    def cancel_with_result(self, order_id: str) -> CancelResult:
        """撤销订单（扩展接口，返回详细结果）
        
        Args:
            order_id: 订单ID（client_order_id或broker_order_id）
            
        Returns:
            CancelResult: 撤销结果
            
        注意：默认实现调用cancel()，子类可重写以返回详细信息
        """
        import time
        cancel_ts_ms = int(time.time() * 1000)
        success = self.cancel(order_id)
        
        return CancelResult(
            success=success,
            client_order_id=order_id,
            cancel_ts_ms=cancel_ts_ms,
            reason=None if success else "cancel_failed",
        )
    
    def flush(self) -> None:
        """刷新缓存
        
        确保所有待写入的事件都已落盘
        默认实现为空，子类可重写
        """
        pass
    
    @abstractmethod
    def fetch_fills(self, since_ts_ms: Optional[int] = None) -> List[Fill]:
        """获取成交记录
        
        Args:
            since_ts_ms: 起始时间戳（ms），None表示获取所有成交
            
        Returns:
            成交记录列表
        """
        pass
    
    @abstractmethod
    def get_position(self, symbol: str) -> float:
        """获取持仓
        
        Args:
            symbol: 交易对
            
        Returns:
            持仓数量（正数=多头，负数=空头）
        """
        pass
    
    @abstractmethod
    def close(self) -> None:
        """关闭执行器
        
        清理资源，刷新缓存，关闭连接
        """
        pass
    
    @property
    @abstractmethod
    def mode(self) -> str:
        """执行模式
        
        Returns:
            模式名称：backtest/testnet/live
        """
        pass

