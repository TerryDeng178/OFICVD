# -*- coding: utf-8 -*-
"""价格对齐模块

统一tick_size/step_size对齐策略，确保价格和数量符合交易所精度要求
"""
import logging
import math
from typing import Optional, Dict, Tuple

from .base_executor import OrderCtx, Order

logger = logging.getLogger(__name__)


class PriceAligner:
    """价格对齐器
    
    将价格和数量对齐到交易所精度（tick_size/step_size）
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """初始化价格对齐器
        
        Args:
            config: 配置字典（可选）
        """
        self.config = config or {}
        logger.info("[PriceAligner] Initialized")
    
    def align_price(self, price: float, tick_size: Optional[float] = None) -> Tuple[float, float]:
        """对齐价格到tick_size
        
        Args:
            price: 原始价格
            tick_size: 价格精度（最小变动单位），如果为None则不对齐
            
        Returns:
            (对齐后的价格, 调整差额)
        """
        if tick_size is None or tick_size <= 0:
            return price, 0.0
        
        # 计算对齐后的价格（四舍五入到最近的tick）
        # 使用decimal避免浮点精度问题
        import decimal
        d_price = decimal.Decimal(str(price))
        d_tick = decimal.Decimal(str(tick_size))
        d_aligned = (d_price / d_tick).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * d_tick
        aligned_price = float(d_aligned)
        
        # 计算调整差额
        price_diff = aligned_price - price
        
        return aligned_price, price_diff
    
    def align_quantity(self, qty: float, step_size: Optional[float] = None) -> Tuple[float, float]:
        """对齐数量到step_size
        
        Args:
            qty: 原始数量
            step_size: 数量精度（最小变动单位），如果为None则不对齐
            
        Returns:
            (对齐后的数量, 调整差额)
        """
        if step_size is None or step_size <= 0:
            return qty, 0.0
        
        # 计算对齐后的数量（向下取整到最近的step）
        # 注意：数量通常向下取整，避免超过账户余额
        aligned_qty = math.floor(qty / step_size) * step_size
        
        # 如果向下取整后为0，则使用最小step_size
        if aligned_qty == 0.0 and qty > 0:
            aligned_qty = step_size
        
        # 计算调整差额
        qty_diff = aligned_qty - qty
        
        return aligned_qty, qty_diff
    
    def align_order_ctx(self, order_ctx: OrderCtx) -> Tuple[OrderCtx, Dict[str, float]]:
        """对齐OrderCtx的价格和数量
        
        Args:
            order_ctx: 订单上下文
            
        Returns:
            (对齐后的OrderCtx, 调整差额字典)
        """
        rounding_diff = {}
        aligned_ctx = OrderCtx(
            client_order_id=order_ctx.client_order_id,
            symbol=order_ctx.symbol,
            side=order_ctx.side,
            qty=order_ctx.qty,
            order_type=order_ctx.order_type,
            price=order_ctx.price,
            tif=order_ctx.tif,
            ts_ms=order_ctx.ts_ms,
            event_ts_ms=order_ctx.event_ts_ms,
            signal_row_id=order_ctx.signal_row_id,
            regime=order_ctx.regime,
            scenario=order_ctx.scenario,
            warmup=order_ctx.warmup,
            guard_reason=order_ctx.guard_reason,
            consistency=order_ctx.consistency,
            weak_signal_throttle=order_ctx.weak_signal_throttle,
            tick_size=order_ctx.tick_size,
            step_size=order_ctx.step_size,
            min_notional=order_ctx.min_notional,
            costs_bps=order_ctx.costs_bps,
            metadata=order_ctx.metadata.copy(),
        )
        
        # 对齐数量
        if order_ctx.step_size:
            aligned_qty, qty_diff = self.align_quantity(order_ctx.qty, order_ctx.step_size)
            aligned_ctx.qty = aligned_qty
            rounding_diff["qty_diff"] = qty_diff
        
        # 对齐价格（限价单）
        if order_ctx.order_type.value == "limit" and order_ctx.price is not None:
            if order_ctx.tick_size:
                aligned_price, price_diff = self.align_price(order_ctx.price, order_ctx.tick_size)
                aligned_ctx.price = aligned_price
                rounding_diff["price_diff"] = price_diff
        
        return aligned_ctx, rounding_diff
    
    def align_order(self, order: Order, tick_size: Optional[float] = None, step_size: Optional[float] = None) -> Tuple[Order, Dict[str, float]]:
        """对齐Order的价格和数量（向后兼容）
        
        Args:
            order: 订单对象
            tick_size: 价格精度（可选）
            step_size: 数量精度（可选）
            
        Returns:
            (对齐后的Order, 调整差额字典)
        """
        rounding_diff = {}
        aligned_order = Order(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            order_type=order.order_type,
            price=order.price,
            tif=order.tif,
            ts_ms=order.ts_ms,
            metadata=order.metadata.copy(),
        )
        
        # 对齐数量
        if step_size:
            aligned_qty, qty_diff = self.align_quantity(order.qty, step_size)
            aligned_order.qty = aligned_qty
            rounding_diff["qty_diff"] = qty_diff
        
        # 对齐价格（限价单）
        if order.order_type.value == "limit" and order.price is not None:
            if tick_size:
                aligned_price, price_diff = self.align_price(order.price, tick_size)
                aligned_order.price = aligned_price
                rounding_diff["price_diff"] = price_diff
        
        return aligned_order, rounding_diff
    
    def validate_notional(self, qty: float, price: float, min_notional: Optional[float] = None) -> Tuple[bool, Optional[str], Optional[float]]:
        """验证名义价值是否满足最小要求
        
        Args:
            qty: 数量
            price: 价格
            min_notional: 最小名义价值
            
        Returns:
            (是否通过, 失败原因, 建议的最大数量)
        """
        if min_notional is None or min_notional <= 0:
            return True, None, None
        
        notional = qty * price
        
        if notional < min_notional:
            # 计算建议的最大数量
            suggested_qty = min_notional / price if price > 0 else None
            return False, "notional_below_minimum", suggested_qty
        
        return True, None, None


class SlippageModel:
    """滑点模型抽象接口"""
    
    def calculate_slippage_bps(self, order_ctx: OrderCtx, market_data: Dict) -> float:
        """计算滑点（基点）
        
        Args:
            order_ctx: 订单上下文
            market_data: 市场数据（包含spread_bps, vol_bps等）
            
        Returns:
            滑点（基点）
        """
        raise NotImplementedError


class StaticSlippageModel(SlippageModel):
    """静态滑点模型"""
    
    def __init__(self, slippage_bps: float = 1.0):
        """初始化静态滑点模型
        
        Args:
            slippage_bps: 固定滑点（基点）
        """
        self.slippage_bps = slippage_bps
    
    def calculate_slippage_bps(self, order_ctx: OrderCtx, market_data: Dict) -> float:
        """计算滑点（固定值）"""
        return self.slippage_bps


class LinearSlippageModel(SlippageModel):
    """线性滑点模型
    
    滑点 = base_slippage + spread_coeff * spread_bps + vol_coeff * vol_bps
    然后取 max(base_slippage, 计算结果)
    """
    
    def __init__(self, base_slippage_bps: float = 1.0, spread_coeff: float = 0.5, vol_coeff: float = 0.3):
        """初始化线性滑点模型
        
        Args:
            base_slippage_bps: 基础滑点（基点）
            spread_coeff: 价差系数
            vol_coeff: 波动率系数
        """
        self.base_slippage_bps = base_slippage_bps
        self.spread_coeff = spread_coeff
        self.vol_coeff = vol_coeff
    
    def calculate_slippage_bps(self, order_ctx: OrderCtx, market_data: Dict) -> float:
        """计算滑点（线性模型）"""
        spread_bps = float(market_data.get("spread_bps", 0.0))
        vol_bps = float(market_data.get("vol_bps", 0.0))
        
        # 线性组合：base + spread_coeff * spread + vol_coeff * vol
        linear_slippage = self.base_slippage_bps + self.spread_coeff * spread_bps + self.vol_coeff * vol_bps
        
        # 取最大值（确保不低于base_slippage）
        slippage = max(self.base_slippage_bps, linear_slippage)
        
        return slippage


class MakerTakerSlippageModel(SlippageModel):
    """Maker/Taker滑点模型
    
    根据订单类型（maker/taker）和流动性计算滑点
    """
    
    def __init__(self, maker_slippage_bps: float = 0.1, taker_slippage_bps: float = 1.0):
        """初始化Maker/Taker滑点模型
        
        Args:
            maker_slippage_bps: Maker订单滑点（基点）
            taker_slippage_bps: Taker订单滑点（基点）
        """
        self.maker_slippage_bps = maker_slippage_bps
        self.taker_slippage_bps = taker_slippage_bps
    
    def calculate_slippage_bps(self, order_ctx: OrderCtx, market_data: Dict) -> float:
        """计算滑点（Maker/Taker模型）"""
        # 判断订单类型（简化处理：限价单=maker，市价单=taker）
        if order_ctx.order_type.value == "limit":
            return self.maker_slippage_bps
        else:
            return self.taker_slippage_bps


def create_slippage_model(model_type: str, config: Optional[Dict] = None) -> SlippageModel:
    """创建滑点模型
    
    Args:
        model_type: 模型类型（static/linear/maker_taker）
        config: 配置字典
        
    Returns:
        SlippageModel实例
    """
    config = config or {}
    
    if model_type == "static":
        slippage_bps = config.get("slippage_bps", 1.0)
        return StaticSlippageModel(slippage_bps)
    elif model_type == "linear":
        base_slippage = config.get("base_slippage_bps", 1.0)
        spread_coeff = config.get("spread_coeff", 0.5)
        vol_coeff = config.get("vol_coeff", 0.3)
        return LinearSlippageModel(base_slippage, spread_coeff, vol_coeff)
    elif model_type == "maker_taker":
        maker_slippage = config.get("maker_slippage_bps", 0.1)
        taker_slippage = config.get("taker_slippage_bps", 1.0)
        return MakerTakerSlippageModel(maker_slippage, taker_slippage)
    else:
        logger.warning(f"[SlippageModel] Unknown model type: {model_type}, using static")
        return StaticSlippageModel()

