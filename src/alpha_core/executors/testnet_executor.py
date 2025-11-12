# -*- coding: utf-8 -*-
"""TestnetExecutor Implementation

测试网执行器：使用交易所Testnet API（dry-run模式）
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from .base_executor import IExecutor, Order, OrderCtx, Fill, ExecResult, ExecResultStatus, Side, OrderState
from .exec_log_sink import build_exec_log_sink, ExecLogSink
from .executor_precheck import ExecutorPrecheck, AdaptiveThrottler
from .broker_gateway_client import BrokerGatewayClient
from .adapter_integration import (
    make_adapter,
    convert_order_to_adapter_order,
    apply_adapter_resp_to_exec_result,
    map_adapter_error_to_state,
    map_adapter_error_to_reject_reason,
)
from ..adapters import BaseAdapter
import time

logger = logging.getLogger(__name__)


class TestnetExecutor(IExecutor):
    """测试网执行器
    
    使用交易所Testnet API，支持dry-run模式
    """
    
    def __init__(self):
        """初始化测试网执行器"""
        self.config: Optional[Dict[str, Any]] = None
        self.output_dir: Optional[Path] = None
        self.sink_kind: str = "jsonl"
        self.exec_log_sink: Optional[ExecLogSink] = None
        self.dry_run: bool = True  # 默认dry-run模式
        self.positions: Dict[str, float] = {}  # symbol -> position qty
        self.order_map: Dict[str, Order] = {}  # client_order_id -> Order
        self.fill_map: Dict[str, List[Fill]] = {}  # client_order_id -> List[Fill]
        self.broker_order_map: Dict[str, str] = {}  # client_order_id -> broker_order_id
        self._order_seq = 0
        
        # 执行前置检查和节流器（测试网模式默认启用）
        self.precheck: Optional[ExecutorPrecheck] = None
        self.throttler: Optional[AdaptiveThrottler] = None
        
        # BaseAdapter（组合/依赖注入）
        self.adapter: Optional[BaseAdapter] = None
    
    def prepare(self, cfg: Dict[str, Any]) -> None:
        """初始化执行器
        
        Args:
            cfg: 配置字典，包含executor和broker配置段
        """
        self.config = cfg
        executor_cfg = cfg.get("executor", {})
        broker_cfg = cfg.get("broker", {})
        
        # 获取输出目录
        output_dir_str = executor_cfg.get("output_dir", "./runtime")
        self.output_dir = Path(output_dir_str)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 获取Sink类型
        self.sink_kind = executor_cfg.get("sink", cfg.get("sink", {}).get("kind", "jsonl"))
        
        # 初始化执行日志Sink（支持Outbox模式）
        use_outbox = executor_cfg.get("use_outbox", True)  # 测试网模式默认启用Outbox
        self.exec_log_sink = build_exec_log_sink(
            kind=self.sink_kind,
            output_dir=self.output_dir,
            db_name=cfg.get("sink", {}).get("db_name", "signals.db"),
            use_outbox=use_outbox,
        )
        
        # 获取dry-run模式（默认True）
        self.dry_run = broker_cfg.get("dry_run", True)
        
        # 初始化执行前置检查和节流器（测试网模式默认启用）
        enable_precheck = executor_cfg.get("enable_precheck", True)
        if enable_precheck:
            self.precheck = ExecutorPrecheck(executor_cfg.get("precheck", {}))
            self.throttler = AdaptiveThrottler(executor_cfg.get("throttler", {}))
        
        # 初始化BaseAdapter（组合/依赖注入）
        self.adapter = make_adapter(cfg)
        
        # 初始化Broker Gateway MCP客户端（保留用于向后兼容，但优先使用Adapter）
        broker_cfg_with_mock = broker_cfg.copy()
        # Testnet模式：如果dry_run=True则使用Mock，否则使用真实API
        broker_cfg_with_mock["mock_enabled"] = broker_cfg.get("dry_run", True) or broker_cfg.get("mock_enabled", True)
        broker_cfg_with_mock["mock_output_path"] = str(self.output_dir / "mock_orders.jsonl")
        # 传递 backtest 配置以便 BrokerGatewayClient 在 mock 模式下使用相同的滑点和费用参数
        if "backtest" in cfg:
            broker_cfg_with_mock["backtest"] = cfg["backtest"]
        self.broker_client = BrokerGatewayClient(broker_cfg_with_mock)
        
        logger.info(
            f"[TestnetExecutor] Initialized: output_dir={self.output_dir}, "
            f"sink={self.sink_kind}, dry_run={self.dry_run}, "
            f"precheck={enable_precheck}, outbox={use_outbox}, adapter={self.adapter.kind()}"
        )
    
    def submit(self, order: Order) -> str:
        """提交订单（委托给BaseAdapter）
        
        Args:
            order: 订单对象
            
        Returns:
            broker_order_id: 交易所订单ID
        """
        if not self.adapter:
            raise RuntimeError("TestnetExecutor not prepared")
        
        # 生成client_order_id（如果未提供）
        if not order.client_order_id:
            self._order_seq += 1
            order.client_order_id = f"testnet-{order.ts_ms}-{self._order_seq}"
        
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
            meta={"mode": "testnet", "dry_run": self.dry_run},
        )
        
        # 委托给BaseAdapter：规范化 + 节流 + 重试 + 提交
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
                meta={"mode": "testnet", "dry_run": self.dry_run, "adapter_code": adapter_resp.code, "adapter_msg": adapter_resp.msg},
            )
            return order.client_order_id
        
        # 成功提交，记录ACK
        broker_order_id = adapter_resp.broker_order_id or order.client_order_id
        self.broker_order_map[order.client_order_id] = broker_order_id
        
        ack_ts_ms = int(time.time() * 1000)
        latency_ms = ack_ts_ms - sent_ts_ms
        
        self.exec_log_sink.write_event(
            ts_ms=ack_ts_ms,
            symbol=order.symbol,
            event="ack",
            order=order,
            state=OrderState.ACK,
            meta={"mode": "testnet", "dry_run": self.dry_run, "latency_ms": latency_ms},
        )
        
        # 注意：实际成交需要从Broker API轮询获取
        # 这里不立即获取成交，等待轮询
        
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
            raise RuntimeError("TestnetExecutor not prepared")
        
        # 查找client_order_id
        client_order_id = None
        if order_id in self.order_map:
            client_order_id = order_id
        else:
            # 反向查找broker_order_id
            for cid, bid in self.broker_order_map.items():
                if bid == order_id:
                    client_order_id = cid
                    break
        
        if not client_order_id or client_order_id not in self.order_map:
            return False
        
        order = self.order_map[client_order_id]
        
        # 检查是否已成交
        if client_order_id in self.fill_map and len(self.fill_map[client_order_id]) > 0:
            logger.warning(f"[TestnetExecutor] Cannot cancel filled order: {client_order_id}")
            return False
        
        # 委托给BaseAdapter撤销
        broker_order_id = self.broker_order_map.get(client_order_id, order_id)
        adapter_resp = self.adapter.cancel(order.symbol, broker_order_id)
        
        if adapter_resp.ok:
            # 写入CANCELED事件
            self.exec_log_sink.write_event(
                ts_ms=int(time.time() * 1000),
                symbol=order.symbol,
                event="canceled",
                order=order,
                state=OrderState.CANCELED,
                meta={"mode": "testnet", "dry_run": self.dry_run},
            )
            return True
        else:
            logger.warning(f"[TestnetExecutor] Cancel failed: {adapter_resp.msg}")
            return False
    
    def fetch_fills(self, since_ts_ms: Optional[int] = None) -> List[Fill]:
        """获取成交记录（委托给BaseAdapter + 本地缓存）
        
        Args:
            since_ts_ms: 起始时间戳（ms），None表示获取所有成交
            
        Returns:
            成交记录列表
        """
        # 从适配器获取成交（按symbol）
        all_fills = []
        symbols = set(order.symbol for order in self.order_map.values()) if self.order_map else set()
        for symbol in symbols:
            adapter_fills = self.adapter.fetch_fills(symbol, since_ts_ms) if self.adapter else []
            # 转换适配器成交格式到Fill对象（简化处理）
            for af in adapter_fills:
                if isinstance(af, dict):
                    side_raw = af.get("side")
                    side = None
                    if isinstance(side_raw, str):
                        s = side_raw.lower()
                        if s in ("buy", "b", "long"):
                            side = Side.BUY
                        elif s in ("sell", "s", "short"):
                            side = Side.SELL

                    fill = Fill(
                        ts_ms=af.get("ts_ms", 0),
                        symbol=af.get("symbol", symbol),
                        client_order_id=af.get("client_order_id", ""),
                        broker_order_id=af.get("broker_order_id"),
                        price=af.get("price", 0.0),
                        qty=af.get("qty", 0.0),
                        fee=af.get("fee", 0.0),
                        liquidity=af.get("liquidity", "unknown"),
                        side=side,  # <- 关键修复：恢复 side 字段
                    )
                    all_fills.append(fill)
        
        # 合并本地缓存
        for fills in self.fill_map.values():
            for fill in fills:
                if since_ts_ms is None or fill.ts_ms >= since_ts_ms:
                    # 避免重复
                    if fill not in all_fills:
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
        # 从Broker Gateway客户端获取持仓
        broker_position = self.broker_client.get_position(symbol)
        
        # 合并本地缓存
        local_position = self.positions.get(symbol, 0.0)
        
        # 返回两者之和（Broker Gateway可能包含其他来源的持仓）
        return broker_position + local_position
    
    def close(self) -> None:
        """关闭执行器"""
        if self.exec_log_sink and hasattr(self.exec_log_sink, "close"):
            self.exec_log_sink.close()
        if self.adapter:
            self.adapter.close()
        logger.info("[TestnetExecutor] Closed")
    
    @property
    def mode(self) -> str:
        """执行模式"""
        return "testnet"

