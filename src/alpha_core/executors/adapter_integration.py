# -*- coding: utf-8 -*-
"""Adapter Integration Utilities

适配器集成工具：错误码映射、状态机转换
"""

import logging
from typing import Dict, Any, Optional

from ..adapters import BaseAdapter, AdapterErrorCode, AdapterOrder, AdapterResp
from ..adapters.adapter_factory import create_adapter
from .base_executor import Order, OrderState, ExecResult, ExecResultStatus

logger = logging.getLogger(__name__)


def make_adapter(config: Dict[str, Any]) -> BaseAdapter:
    """创建适配器实例（根据 executor.mode 选择 adapter.impl）
    
    Args:
        config: 配置字典，包含 executor 和 adapter 配置段
        
    Returns:
        适配器实例
        
    注意：
        - executor.mode 为单一权威
        - adapter.impl 默认跟随 executor.mode
        - 如果强行覆盖，会进行一致性校验并告警
    """
    executor_cfg = config.get("executor", {})
    adapter_cfg = config.get("adapter", {})
    
    executor_mode = executor_cfg.get("mode", "backtest")
    adapter_impl = adapter_cfg.get("impl")
    
    # 如果未配置 adapter.impl，默认跟随 executor.mode
    if not adapter_impl:
        adapter_impl = executor_mode
        logger.info(f"[AdapterIntegration] adapter.impl not set, using executor.mode: {adapter_impl}")
    else:
        # P2: 一致性校验 + 强校验
        if adapter_impl != executor_mode:
            logger.warning(
                f"[AdapterIntegration] WARNING: adapter.impl ({adapter_impl}) != executor.mode ({executor_mode}), "
                f"using adapter.impl={adapter_impl}"
            )
            # P2: 落地 adapter_event 记录配置不一致
            # 注意：此时 adapter 还未创建，需要延迟记录
    
    # 创建适配器
    adapter = create_adapter(config)
    logger.info(f"[AdapterIntegration] Created adapter: {adapter.kind()}")
    
    # P1: 记录配置决策快照（无论是否一致，便于审计）
    try:
        from ..adapters.adapter_event_sink import build_adapter_event_sink
        from pathlib import Path
        import os
        
        # P0: 统一从 sink.kind 读取，与 BaseAdapter 保持一致
        sink_cfg = config.get("sink", {})
        sink_kind = sink_cfg.get("kind", os.getenv("V13_SINK", "jsonl"))
        output_dir = Path(os.getenv("V13_OUTPUT_DIR", sink_cfg.get("output_dir", executor_cfg.get("output_dir", "./runtime"))))
        event_sink = build_adapter_event_sink(sink_kind, output_dir)
        
        import time
        # P1: 记录配置决策快照（impl.confirm 或 impl.mismatch）
        event_type = "impl.mismatch" if adapter_impl != executor_mode else "impl.confirm"
        event_sink.write_event(
            ts_ms=int(time.time() * 1000),
            mode=adapter.kind(),
            symbol="SYSTEM",
            event=event_type,
            meta={
                "executor_mode": executor_mode,
                "adapter_impl": adapter_impl,
                "sink_kind": sink_kind,
                "output_dir": str(output_dir),
                "impl_decision": {
                    "executor_mode": executor_mode,
                    "adapter_impl": adapter_impl,
                    "sink_kind": sink_kind,
                    "output_dir": str(output_dir),
                },
                "warning": f"adapter.impl ({adapter_impl}) != executor.mode ({executor_mode})" if adapter_impl != executor_mode else None,
                "contract_ver": "v1",  # P1: 契约版本
            },
        )
        event_sink.close()
    except Exception as e:
        logger.debug(f"[AdapterIntegration] Failed to log impl decision event: {e}")
    
    return adapter


def map_adapter_error_to_state(adapter_resp: AdapterResp) -> OrderState:
    """将适配器错误码映射到订单状态
    
    Args:
        adapter_resp: 适配器响应
        
    Returns:
        订单状态
        
    映射规则：
        - OK: ACK（后续可能变为 PARTIAL/FILLED）
        - E.PARAMS / E.BROKER.REJECT / E.STATE.CONFLICT: REJECTED
        - E.RATE.LIMIT / E.NETWORK / E.RULES.MISS: REJECTED（适配器已重试，超出上限）
        - E.UNKNOWN: REJECTED
    """
    if adapter_resp.ok:
        return OrderState.ACK
    
    code = adapter_resp.code
    
    # 不可重试错误 → REJECTED
    if code in (AdapterErrorCode.E_PARAMS, AdapterErrorCode.E_BROKER_REJECT, AdapterErrorCode.E_STATE_CONFLICT):
        return OrderState.REJECTED
    
    # 可重试错误（适配器已重试，超出上限）→ REJECTED
    if code in (AdapterErrorCode.E_RATE_LIMIT, AdapterErrorCode.E_NETWORK, AdapterErrorCode.E_RULES_MISS):
        return OrderState.REJECTED
    
    # 未知错误 → REJECTED
    return OrderState.REJECTED


def map_adapter_error_to_reject_reason(adapter_resp: AdapterResp) -> str:
    """将适配器错误码映射到拒绝原因
    
    Args:
        adapter_resp: 适配器响应
        
    Returns:
        拒绝原因字符串
    """
    code = adapter_resp.code
    
    reason_map = {
        AdapterErrorCode.E_PARAMS: "invalid_params",
        AdapterErrorCode.E_BROKER_REJECT: "broker_reject",
        AdapterErrorCode.E_STATE_CONFLICT: "state_conflict",
        AdapterErrorCode.E_RATE_LIMIT: "rate_limit",
        AdapterErrorCode.E_NETWORK: "network_error",
        AdapterErrorCode.E_RULES_MISS: "rules_miss",
        AdapterErrorCode.E_UNKNOWN: "unknown_error",
    }
    
    return reason_map.get(code, "unknown_error")


def convert_order_to_adapter_order(order: Order) -> AdapterOrder:
    """将 IExecutor Order 转换为 AdapterOrder
    
    Args:
        order: IExecutor 订单对象
        
    Returns:
        适配器订单对象
    """
    return AdapterOrder(
        client_order_id=order.client_order_id,
        symbol=order.symbol,
        side=order.side.value,
        qty=order.qty,
        price=order.price,
        order_type=order.order_type.value,
        tif=order.tif.value,
        ts_ms=order.ts_ms,
    )


def apply_adapter_resp_to_exec_result(
    order: Order,
    adapter_resp: AdapterResp,
    sent_ts_ms: int,
    ack_ts_ms: Optional[int] = None,
) -> ExecResult:
    """将适配器响应转换为执行结果
    
    Args:
        order: 订单对象
        adapter_resp: 适配器响应
        sent_ts_ms: 发送时间戳（ms）
        ack_ts_ms: ACK时间戳（ms），None表示未ACK
        
    Returns:
        执行结果
    """
    state = map_adapter_error_to_state(adapter_resp)
    
    if adapter_resp.ok:
        status = ExecResultStatus.ACCEPTED
        reject_reason = None
    else:
        status = ExecResultStatus.REJECTED
        reject_reason = map_adapter_error_to_reject_reason(adapter_resp)
    
    latency_ms = None
    if ack_ts_ms:
        latency_ms = ack_ts_ms - sent_ts_ms
    
    return ExecResult(
        status=status,
        client_order_id=order.client_order_id,
        exchange_order_id=adapter_resp.broker_order_id,
        reject_reason=reject_reason,
        latency_ms=latency_ms,
        sent_ts_ms=sent_ts_ms,
        ack_ts_ms=ack_ts_ms,
        meta={
            "adapter_code": adapter_resp.code,
            "adapter_msg": adapter_resp.msg,
        },
    )

