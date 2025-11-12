# -*- coding: utf-8 -*-
"""BacktestExecutor Implementation

回测执行器：使用TradeSimulator进行回测
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from .base_executor import IExecutor, Order, OrderCtx, Fill, ExecResult, ExecResultStatus, Side, OrderType, OrderState
from .exec_log_sink import build_exec_log_sink, ExecLogSink
from .executor_precheck import ExecutorPrecheck, AdaptiveThrottler
from .exec_log_sink_outbox import JsonlExecLogSinkOutbox
from .adapter_integration import (
    make_adapter,
    convert_order_to_adapter_order,
    apply_adapter_resp_to_exec_result,
    map_adapter_error_to_state,
    map_adapter_error_to_reject_reason,
)
from ..adapters import BaseAdapter
from ..backtest.trade_sim import TradeSimulator
import time

logger = logging.getLogger(__name__)


class BacktestExecutor(IExecutor):
    """回测执行器
    
    从signals表/JSONL读取信号，使用TradeSimulator进行回测
    """
    
    def __init__(self):
        """初始化回测执行器"""
        self.config: Optional[Dict[str, Any]] = None
        self.output_dir: Optional[Path] = None
        self.sink_kind: str = "jsonl"
        self.exec_log_sink: Optional[ExecLogSink] = None
        self.trade_sim: Optional[TradeSimulator] = None
        self.positions: Dict[str, float] = {}  # symbol -> position qty
        self.order_map: Dict[str, Order] = {}  # client_order_id -> Order
        self.fill_map: Dict[str, List[Fill]] = {}  # client_order_id -> List[Fill]
        self._order_seq = 0  # 订单序号（用于生成client_order_id）
        
        # 执行前置检查和节流器（可选，回测模式下可以禁用）
        self.precheck: Optional[ExecutorPrecheck] = None
        self.throttler: Optional[AdaptiveThrottler] = None
        
        # BaseAdapter（组合/依赖注入）
        self.adapter: Optional[BaseAdapter] = None
    
    def prepare(self, cfg: Dict[str, Any]) -> None:
        """初始化执行器
        
        Args:
            cfg: 配置字典，包含executor配置段
        """
        self.config = cfg
        executor_cfg = cfg.get("executor", {})
        
        # 获取输出目录
        output_dir_str = executor_cfg.get("output_dir", "./runtime")
        self.output_dir = Path(output_dir_str)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 获取Sink类型（与全局V13_SINK对齐）
        self.sink_kind = executor_cfg.get("sink", cfg.get("sink", {}).get("kind", "jsonl"))
        
        # 初始化执行日志Sink（支持Outbox模式）
        use_outbox = executor_cfg.get("use_outbox", False)
        self.exec_log_sink = build_exec_log_sink(
            kind=self.sink_kind,
            output_dir=self.output_dir,
            db_name=cfg.get("sink", {}).get("db_name", "signals.db"),
            use_outbox=use_outbox,
        )
        
        # 初始化执行前置检查和节流器（可选）
        enable_precheck = executor_cfg.get("enable_precheck", False)  # 回测模式默认禁用
        if enable_precheck:
            self.precheck = ExecutorPrecheck(executor_cfg.get("precheck", {}))
            self.throttler = AdaptiveThrottler(executor_cfg.get("throttler", {}))
        
        # 初始化BaseAdapter（组合/依赖注入）
        self.adapter = make_adapter(cfg)
        
        # 初始化TradeSimulator
        backtest_cfg = cfg.get("backtest", {})
        self.trade_sim = TradeSimulator(
            config=backtest_cfg,
            output_dir=self.output_dir,
            ignore_gating_in_backtest=backtest_cfg.get("ignore_gating", False),
        )
        
        logger.info(
            f"[BacktestExecutor] Initialized: output_dir={self.output_dir}, sink={self.sink_kind}, "
            f"precheck={enable_precheck}, outbox={use_outbox}, adapter={self.adapter.kind()}"
        )
    
    def submit(self, order: Order) -> str:
        """提交订单（委托给BaseAdapter）
        
        Args:
            order: 订单对象
            
        Returns:
            broker_order_id: 回测模式下返回client_order_id
        """
        if not self.adapter or not self.trade_sim:
            raise RuntimeError("BacktestExecutor not prepared")
        
        # 生成client_order_id（如果未提供）
        if not order.client_order_id:
            self._order_seq += 1
            order.client_order_id = f"backtest-{order.ts_ms}-{self._order_seq}"
        
        # 记录订单
        self.order_map[order.client_order_id] = order
        
        # 写入submit事件
        sent_ts_ms = order.ts_ms or int(time.time() * 1000)
        self.exec_log_sink.write_event(
            ts_ms=sent_ts_ms,
            symbol=order.symbol,
            event="submit",
            order=order,
            state=OrderState.NEW,
            meta={"mode": "backtest"},
        )
        
        # 委托给BaseAdapter：规范化 + 提交
        adapter_order = convert_order_to_adapter_order(order)
        adapter_resp = self.adapter.submit(adapter_order)
        
        # 映射错误码到状态机
        state = map_adapter_error_to_state(adapter_resp)
        
        # 如果被拒绝，记录并返回
        if not adapter_resp.ok:
            reject_reason = map_adapter_error_to_reject_reason(adapter_resp)
            self.exec_log_sink.write_event(
                ts_ms=sent_ts_ms,
                symbol=order.symbol,
                event="rejected",
                order=order,
                state=state,
                reason=reject_reason,
                meta={"mode": "backtest", "adapter_code": adapter_resp.code, "adapter_msg": adapter_resp.msg},
            )
            return order.client_order_id
        
        # 成功提交，记录ACK
        broker_order_id = adapter_resp.broker_order_id or order.client_order_id
        ack_ts_ms = int(time.time() * 1000)
        
        self.exec_log_sink.write_event(
            ts_ms=ack_ts_ms,
            symbol=order.symbol,
            event="ack",
            order=order,
            state=OrderState.ACK,
            meta={"mode": "backtest", "latency_ms": ack_ts_ms - sent_ts_ms},
        )
        
        # 回测模式下立即成交（模拟）
        mid_price = order.metadata.get("mid_price", 0.0)
        if mid_price:
            # 计算成交价格（考虑滑点）
            slippage_bps = self.config.get("backtest", {}).get("slippage_bps", 1.0)
            if order.side == Side.BUY:
                fill_price = mid_price * (1 + slippage_bps / 10000)
            else:
                fill_price = mid_price * (1 - slippage_bps / 10000)
            
            # 计算手续费
            fee_bps = self.config.get("backtest", {}).get("fee_bps", 1.93)
            notional = fill_price * order.qty
            fee = notional * (fee_bps / 10000)
            
            # 创建成交记录
            fill = Fill(
                ts_ms=ack_ts_ms,
                symbol=order.symbol,
                client_order_id=order.client_order_id,
                broker_order_id=broker_order_id,
                price=fill_price,
                qty=order.qty,
                fee=fee,
                liquidity="taker",
                side=order.side,
            )
            
            # 记录成交
            if order.client_order_id not in self.fill_map:
                self.fill_map[order.client_order_id] = []
            self.fill_map[order.client_order_id].append(fill)
            
            # 更新持仓
            if order.symbol not in self.positions:
                self.positions[order.symbol] = 0.0
            if order.side == Side.BUY:
                self.positions[order.symbol] += order.qty
            else:
                self.positions[order.symbol] -= order.qty
            
            # 写入FILLED事件
            self.exec_log_sink.write_event(
                ts_ms=ack_ts_ms,
                symbol=order.symbol,
                event="filled",
                order=order,
                fill=fill,
                state=OrderState.FILLED,
                meta={"mode": "backtest"},
            )
        
        return broker_order_id
    
    def submit_with_ctx(self, order_ctx: OrderCtx) -> ExecResult:
        """提交订单（扩展接口，包含上游状态）
        
        Args:
            order_ctx: 订单上下文（包含上游状态字段）
            
        Returns:
            ExecResult: 执行结果
        """
        import time as time_module
        
        # 1. 执行前置检查（如果启用）
        if self.precheck:
            exec_result = self.precheck.check(order_ctx)
            if exec_result.status == ExecResultStatus.REJECTED:
                # 被拒绝，记录日志并返回
                self.exec_log_sink.write_event(
                    ts_ms=order_ctx.ts_ms or int(time_module.time() * 1000),
                    symbol=order_ctx.symbol,
                    event="rejected",
                    order_ctx=order_ctx,
                    exec_result=exec_result,
                )
                return exec_result
        
        # 2. 检查节流（如果启用）
        if self.throttler:
            gate_reason_stats = {}  # 可以从上游获取
            market_activity = order_ctx.regime or "active"
            if self.throttler.should_throttle(gate_reason_stats=gate_reason_stats, market_activity=market_activity):
                # 被节流，返回拒绝结果
                sent_ts_ms = order_ctx.ts_ms or int(time_module.time() * 1000)
                return ExecResult(
                    status=ExecResultStatus.REJECTED,
                    client_order_id=order_ctx.client_order_id,
                    reject_reason="rate_limit",
                    sent_ts_ms=sent_ts_ms,
                )
        
        # 3. 转换为基础Order并提交
        order = order_ctx.to_order()
        broker_order_id = self.submit(order)
        
        # 4. 构建ExecResult
        ack_ts_ms = int(time_module.time() * 1000)
        latency_ms = ack_ts_ms - (order_ctx.ts_ms or ack_ts_ms)
        
        return ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id=order_ctx.client_order_id,
            exchange_order_id=broker_order_id,
            sent_ts_ms=order_ctx.ts_ms,
            ack_ts_ms=ack_ts_ms,
            latency_ms=latency_ms if latency_ms > 0 else None,
        )
    
    def cancel(self, order_id: str) -> bool:
        """撤销订单（委托给BaseAdapter）
        
        Args:
            order_id: 订单ID（client_order_id或broker_order_id）
            
        Returns:
            是否撤销成功
        """
        if not self.adapter:
            raise RuntimeError("BacktestExecutor not prepared")
        
        # 查找订单
        if order_id not in self.order_map:
            return False
        
        order = self.order_map[order_id]
        
        # 检查是否已成交
        if order_id in self.fill_map and len(self.fill_map[order_id]) > 0:
            logger.warning(f"[BacktestExecutor] Cannot cancel filled order: {order_id}")
            return False
        
        # 委托给BaseAdapter撤销
        broker_order_id = order_id  # 回测模式下相同
        adapter_resp = self.adapter.cancel(order.symbol, broker_order_id)
        
        if adapter_resp.ok:
            # 写入CANCELED事件
            self.exec_log_sink.write_event(
                ts_ms=int(time.time() * 1000),
                symbol=order.symbol,
                event="canceled",
                order=order,
                state=OrderState.CANCELED,
                meta={"mode": "backtest"},
            )
            return True
        else:
            logger.warning(f"[BacktestExecutor] Cancel failed: {adapter_resp.msg}")
            return False
    
    def fetch_fills(self, since_ts_ms: Optional[int] = None) -> List[Fill]:
        """获取成交记录（委托给BaseAdapter + 本地缓存）
        
        Args:
            since_ts_ms: 起始时间戳（ms），None表示获取所有成交
            
        Returns:
            成交记录列表
        """
        # 从适配器获取成交（回测模式下可能为空）
        adapter_fills = self.adapter.fetch_fills("", since_ts_ms) if self.adapter else []
        
        # 合并本地缓存
        all_fills = []
        for fills in self.fill_map.values():
            for fill in fills:
                if since_ts_ms is None or fill.ts_ms >= since_ts_ms:
                    all_fills.append(fill)
        
        # 按时间戳排序
        all_fills.sort(key=lambda f: f.ts_ms)
        return all_fills
    
    def get_position(self, symbol: str) -> float:
        """获取持仓
        
        Args:
            symbol: 交易对
            
        Returns:
            持仓数量（正数=多头，负数=空头）
        """
        return self.positions.get(symbol, 0.0)
    
    def close(self) -> None:
        """关闭执行器"""
        if self.exec_log_sink and hasattr(self.exec_log_sink, "close"):
            self.exec_log_sink.close()
        if self.adapter:
            self.adapter.close()
        logger.info("[BacktestExecutor] Closed")
    
    @property
    def mode(self) -> str:
        """执行模式"""
        return "backtest"

