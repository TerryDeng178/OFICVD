# -*- coding: utf-8 -*-
"""Risk Contract Schemas (v1)

订单上下文和风控决策的数据契约定义
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class OrderSide(str, Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"


class AccountMode(str, Enum):
    """账户模式"""
    ISOLATED = "isolated"
    CROSS = "cross"


@dataclass
class OrderCtx:
    """订单上下文 (v1)
    
    单一事实来源：字段定义以docs/api_contracts.md为准
    """
    symbol: str  # 交易对，如 BTCUSDT（大写，统一）
    side: str  # 方向：buy/sell
    order_type: str  # market/limit
    qty: float  # 张/币数量（与交易所精度、步长对齐）
    price: Optional[float] = None  # 限价单必填
    account_mode: str = "isolated"  # isolated/cross
    max_slippage_bps: float = 10.0  # 允许滑点上限 bps
    ts_ms: int = 0  # 本地决定时间戳（ms）
    regime: str = "normal"  # 来自策略层的场景标签（normal/quiet/turbulent/...）
    
    # Guards（护栏字段，与策略层一致性对齐）
    guards: Dict[str, float] = field(default_factory=lambda: {
        "spread_bps": 0.0,
        "event_lag_sec": 0.0,
        "activity_tpm": 0.0,  # trades per min
    })
    
    # Context（上下文信息）
    context: Dict[str, float] = field(default_factory=lambda: {
        "fees_bps": 0.0,
        "maker_ratio_target": 0.0,
        "recent_pnl": 0.0,
    })


@dataclass
class RiskDecision:
    """风控决策 (v1)
    
    单一事实来源：字段定义以docs/api_contracts.md为准
    """
    passed: bool  # 是否通过风控检查
    reason_codes: List[str] = field(default_factory=list)  # 拒绝原因码，如 ["spread_too_wide","lag_exceeds_cap"]
    
    # Adjustments（调整建议）
    adjustments: Dict[str, Optional[float]] = field(default_factory=lambda: {
        "max_qty": None,
        "price_cap": None,  # 限价上限（根据滑点护栏计算）
    })
    
    # Metrics（性能指标）
    metrics: Dict[str, float] = field(default_factory=lambda: {
        "check_latency_ms": 0.0,
    })
    
    # Shadow Compare（影子对比，用于与legacy风控比对）
    shadow_compare: Dict[str, bool] = field(default_factory=lambda: {
        "legacy_passed": False,
        "parity": False,  # 与legacy判定是否一致
    })

