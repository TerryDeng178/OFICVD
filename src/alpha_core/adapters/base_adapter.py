# -*- coding: utf-8 -*-
"""BaseAdapter Abstract Interface

BaseAdapter 统一适配层：错误码/重试/节流/数量规范化
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
import logging
import time
import os
import threading
from pathlib import Path

from ..utils.rate_limiter import RateLimiter
from ..utils.retry import RetryPolicy, retry_with_backoff
from ..utils.rules_cache import RulesCache
from .adapter_event_sink import build_adapter_event_sink, AdapterEventSink

logger = logging.getLogger(__name__)


class AdapterErrorCode(str, Enum):
    """统一错误码"""
    OK = "OK"
    E_PARAMS = "E.PARAMS"  # 参数不合法
    E_RULES_MISS = "E.RULES.MISS"  # 交易规则缺失/过期
    E_RATE_LIMIT = "E.RATE.LIMIT"  # 触发限频
    E_NETWORK = "E.NETWORK"  # 网络/超时
    E_BROKER_REJECT = "E.BROKER.REJECT"  # 交易所拒绝
    E_STATE_CONFLICT = "E.STATE.CONFLICT"  # 状态竞争/重复撤单
    E_UNKNOWN = "E.UNKNOWN"  # 未分类错误


@dataclass
class AdapterOrder:
    """适配器订单数据结构"""
    client_order_id: str
    symbol: str
    side: str  # buy|sell
    qty: float
    price: Optional[float] = None
    order_type: str = "market"  # market|limit
    tif: str = "GTC"  # GTC|IOC|FOK
    ts_ms: int = 0


@dataclass
class AdapterResp:
    """适配器响应数据结构"""
    ok: bool
    code: str  # 统一错误码（AdapterErrorCode）
    msg: str
    broker_order_id: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class BaseAdapter(ABC):
    """BaseAdapter 抽象接口
    
    统一固化执行落地的底层契约，消除 backtest/testnet/live 的分支差异
    """
    
    def __init__(self, config: Dict[str, Any]):
        """初始化适配器
        
        Args:
            config: 配置字典，包含 adapter 配置段
        """
        self.config = config
        adapter_cfg = config.get("adapter", {})
        
        # 节流配置
        rate_limit_cfg = adapter_cfg.get("rate_limit", {})
        place_cfg = rate_limit_cfg.get("place", {"rps": 8, "burst": 16})
        cancel_cfg = rate_limit_cfg.get("cancel", {"rps": 5, "burst": 10})
        query_cfg = rate_limit_cfg.get("query", {"rps": 10, "burst": 20})
        
        self.rate_limiter = RateLimiter(
            place_rps=place_cfg.get("rps", 8.0),
            place_burst=place_cfg.get("burst", 16),
            cancel_rps=cancel_cfg.get("rps", 5.0),
            cancel_burst=cancel_cfg.get("burst", 10),
            query_rps=query_cfg.get("rps", 10.0),
            query_burst=query_cfg.get("burst", 20),
        )
        
        # 并发控制（P1: 线程安全）
        self.max_inflight_orders = adapter_cfg.get("max_inflight_orders", 32)
        self._inflight_orders: set = set()
        self._inflight_lock = threading.Lock()
        
        # 规则缓存配置
        self.rules_ttl_sec = adapter_cfg.get("rules_ttl_sec", 300)
        self.rules_cache = RulesCache(ttl_sec=self.rules_ttl_sec)
        
        # 重试策略
        retry_cfg = adapter_cfg.get("retry", {})
        self.retry_policy = RetryPolicy(
            max_retries=retry_cfg.get("max_retries", 5),
            base_delay_ms=retry_cfg.get("base_delay_ms", 200),
            factor=retry_cfg.get("factor", 2.0),
            jitter_pct=retry_cfg.get("jitter_pct", 0.25),
        )
        
        # 幂等性配置（P1: 线程安全 + 容量上限）
        self.idempotency_ttl_sec = adapter_cfg.get("idempotency_ttl_sec", 600)
        self.idempotency_max_size = adapter_cfg.get("idempotency_max_size", 1000)
        self._idempotency_cache: Dict[str, tuple[float, AdapterResp]] = {}  # client_order_id -> (expire_time, resp)
        self._idempotency_lock = threading.Lock()
        
        # 订单大小配置
        self.order_size_usd = adapter_cfg.get("order_size_usd", 100)
        self.tif = adapter_cfg.get("tif", "GTC")
        self.order_type = adapter_cfg.get("order_type", "market")
        
        # 事件落地
        output_dir_str = adapter_cfg.get("output_dir") or config.get("sink", {}).get("output_dir", "./runtime")
        output_dir_str = os.getenv("V13_OUTPUT_DIR", output_dir_str)
        self.output_dir = Path(output_dir_str)
        
        sink_kind = adapter_cfg.get("sink") or config.get("sink", {}).get("kind", "jsonl")
        sink_kind = os.getenv("V13_SINK", sink_kind)
        db_name = config.get("sink", {}).get("db_name", "signals.db")
        
        self.event_sink = build_adapter_event_sink(kind=sink_kind, output_dir=self.output_dir, db_name=db_name)
        
        # P1: 追踪ID（run_id/session_id）
        import uuid
        self._run_id = str(uuid.uuid4())[:8]
        self._session_id = str(uuid.uuid4())[:8]
    
    @abstractmethod
    def kind(self) -> str:
        """适配器类型
        
        Returns:
            类型名称：backtest|testnet|live
        """
        pass
    
    def load_rules(self, symbol: str) -> Dict[str, Any]:
        """加载交易规则（带缓存）
        
        Args:
            symbol: 交易对
            
        Returns:
            交易规则字典，包含：
            - qty_step: 数量步长
            - qty_min: 最小数量
            - price_tick: 价格精度
            - min_notional: 最小名义价值
            - precision: {qty: int, price: int}
            - base: 基础资产
            - quote: 计价资产
        """
        # 先检查缓存
        cached_rules = self.rules_cache.get(symbol)
        if cached_rules:
            return cached_rules
        
        # 缓存未命中，加载规则
        try:
            rules = self._load_rules_impl(symbol)
            
            # 验证规则有效性
            if not rules or not isinstance(rules, dict):
                raise RuntimeError(f"Invalid rules returned for {symbol}")
            
            # 存入缓存
            self.rules_cache.put(symbol, rules)
            
            return rules
            
        except Exception as e:
            # P1: 规则加载失败，使缓存失效并抛出异常
            logger.error(f"[BaseAdapter] Failed to load rules for {symbol}: {e}")
            self.rules_cache.invalidate(symbol)
            raise RuntimeError(f"Rules loading failed for {symbol}: {e}") from e
    
    @abstractmethod
    def _load_rules_impl(self, symbol: str) -> Dict[str, Any]:
        """加载交易规则实现（子类实现）
        
        Args:
            symbol: 交易对
            
        Returns:
            交易规则字典
        """
        pass
    
    def normalize(self, symbol: str, qty: float, price: Optional[float] = None) -> Dict[str, float]:
        """数量/价格规范化（默认实现）
        
        Args:
            symbol: 交易对
            qty: 原始数量
            price: 原始价格（限价单）
            
        Returns:
            规范化后的数量/价格字典：
            - qty: 规范化后的数量
            - price: 规范化后的价格（如果提供）
            - notional: 名义价值
            
        Raises:
            ValueError: 如果规范化失败（数量小于最小值等）
        """
        # 加载交易规则
        rules = self.load_rules(symbol)
        
        # P2: 记录规则版本/hash（用于观测）
        rules_version = rules.get("version", "unknown")
        rules_hash = hash(str(sorted(rules.items())))  # 简单hash
        
        # P2: 使用 Decimal 避免浮点误差
        qty_step = Decimal(str(rules.get("qty_step", 0.0001)))
        qty_min = Decimal(str(rules.get("qty_min", 0.001)))
        price_tick = Decimal(str(rules.get("price_tick", 0.01)))
        min_notional = Decimal(str(rules.get("min_notional", 5.0)))
        precision_qty = rules.get("precision", {}).get("qty", 8)
        precision_price = rules.get("precision", {}).get("price", 8)
        
        # 转换为 Decimal
        qty_decimal = Decimal(str(qty))
        
        # 1. 规范化数量：floor(qty/qty_step)*qty_step（使用 Decimal 精确计算）
        normalized_qty_decimal = (qty_decimal / qty_step).quantize(Decimal('1'), rounding=ROUND_DOWN) * qty_step
        # 使用 quantize 进行精度控制
        normalized_qty_decimal = normalized_qty_decimal.quantize(Decimal('0.1') ** precision_qty, rounding=ROUND_HALF_UP)
        normalized_qty = float(normalized_qty_decimal)
        
        # 检查最小数量
        if normalized_qty_decimal < qty_min:
            raise ValueError(f"Quantity {normalized_qty} < min {float(qty_min)} for {symbol}")
        
        # 2. 规范化价格（限价单，使用 Decimal 精确计算）
        normalized_price = None
        if price is not None:
            price_decimal = Decimal(str(price))
            normalized_price_decimal = (price_decimal / price_tick).quantize(Decimal('1'), rounding=ROUND_DOWN) * price_tick
            normalized_price_decimal = normalized_price_decimal.quantize(Decimal('0.1') ** precision_price, rounding=ROUND_HALF_UP)
            normalized_price = float(normalized_price_decimal)
        
        # 3. 计算名义价值（使用 Decimal 精确计算）
        # 如果有限价，使用限价；否则需要从外部获取mark_price
        if normalized_price:
            mark_price_decimal = Decimal(str(normalized_price))
        else:
            # 市价单：优先使用 rules 中的 mark_price
            mark_price_raw = rules.get("mark_price")
            
            # 如果 rules 中没有 mark_price，尝试从配置获取 order_size_usd 回退
            if not mark_price_raw or mark_price_raw <= 0:
                order_size_usd = self.config.get("adapter", {}).get("order_size_usd", 100.0)
                # 如果 qty 是从 order_size_usd 计算出来的，可以用 qty 反推价格
                # 否则尝试从 ticker_provider 获取（如果可用）
                if hasattr(self, "_get_ticker_price"):
                    try:
                        ticker_price = self._get_ticker_price(symbol)
                        if ticker_price and ticker_price > 0:
                            mark_price_raw = ticker_price
                    except Exception as e:
                        logger.warning(f"[BaseAdapter] Failed to get ticker price for {symbol}: {e}")
                
                # 如果仍然没有价格，使用 order_size_usd / qty 反推（作为最后手段）
                if (not mark_price_raw or mark_price_raw <= 0) and normalized_qty > 0:
                    # P2: 使用 Decimal 精确计算
                    mark_price_raw = float(Decimal(str(order_size_usd)) / normalized_qty_decimal)
                    logger.debug(f"[BaseAdapter] Using fallback mark_price={mark_price_raw} for {symbol} (order_size_usd={order_size_usd}/qty={normalized_qty})")
            
            if not mark_price_raw or mark_price_raw <= 0:
                raise ValueError(f"Cannot determine mark_price for market order: {symbol}")
            
            mark_price_decimal = Decimal(str(mark_price_raw))
        
        # P2: 使用 Decimal 计算名义价值
        notional_decimal = normalized_qty_decimal * mark_price_decimal
        notional = float(notional_decimal)
        
        # 4. 检查最小名义价值（使用 Decimal 精确比较）
        if notional_decimal < min_notional:
            raise ValueError(f"Notional {notional} < min {float(min_notional)} for {symbol}")
        
        result = {
            "qty": normalized_qty,
            "notional": notional,
        }
        
        if normalized_price is not None:
            result["price"] = normalized_price
        
        return result
    
    def submit(self, order: AdapterOrder) -> AdapterResp:
        """提交订单（带节流/重试/幂等）
        
        Args:
            order: 订单对象
            
        Returns:
            适配器响应
        """
        # 1. 检查幂等性（P1: 线程安全）
        with self._idempotency_lock:
            if order.client_order_id in self._idempotency_cache:
                expire_time, cached_resp = self._idempotency_cache[order.client_order_id]
                if time.time() < expire_time:
                    logger.debug(f"[BaseAdapter] Idempotent request: {order.client_order_id}")
                    return cached_resp
                else:
                    # 过期，删除
                    del self._idempotency_cache[order.client_order_id]
        
        # 2. 检查并发限制（P1: 线程安全）
        with self._inflight_lock:
            if len(self._inflight_orders) >= self.max_inflight_orders:
                resp = AdapterResp(
                    ok=False,
                    code=AdapterErrorCode.E_RATE_LIMIT,
                    msg=f"Max inflight orders ({self.max_inflight_orders}) exceeded",
                )
                self._write_event(order, resp, {"event": "rate.limit"})
                return resp
        
        # 3. 节流检查
        if not self.rate_limiter.acquire_place(timeout=0.1):
            resp = AdapterResp(
                ok=False,
                code=AdapterErrorCode.E_RATE_LIMIT,
                msg="Rate limit exceeded",
            )
            self._write_event(order, resp, {"event": "rate.limit"})
            return resp
        
        # 4. 规范化数量/价格
        try:
            normalized = self.normalize(order.symbol, order.qty, order.price)
            order.qty = normalized["qty"]
            if "price" in normalized:
                order.price = normalized["price"]
        except RuntimeError as e:
            # P1: 规则加载失败，返回 E.RULES.MISS（可重试）
            if "Rules loading failed" in str(e) or "rules" in str(e).lower():
                resp = AdapterResp(
                    ok=False,
                    code=AdapterErrorCode.E_RULES_MISS,
                    msg=str(e),
                )
                self._write_event(order, resp, {"event": "rules.refresh"})
                return resp
            else:
                # 其他运行时错误
                resp = AdapterResp(
                    ok=False,
                    code=AdapterErrorCode.E_UNKNOWN,
                    msg=str(e),
                )
                self._write_event(order, resp, {"event": "submit"})
                return resp
        except ValueError as e:
            resp = AdapterResp(
                ok=False,
                code=AdapterErrorCode.E_PARAMS,
                msg=str(e),
            )
            self._write_event(order, resp, {"event": "submit"})
            return resp
        
        # 5. 记录到并发集合（P1: 线程安全）
        with self._inflight_lock:
            self._inflight_orders.add(order.client_order_id)
        
        try:
            # 6. 重试逻辑
            attempt = 0
            resp = None
            
            while attempt <= self.retry_policy.max_retries:
                resp = self._submit_impl(order)
                
                # 如果成功或不可重试，直接返回
                if resp.ok or not self.is_retriable(resp.code):
                    break
                
                # P2: 如果遇到 E.RATE.LIMIT，触发自适应退避
                if resp.code == AdapterErrorCode.E_RATE_LIMIT:
                    self.rate_limiter.trigger_adaptive_backoff(duration_sec=10.0)
                
                # 如果可重试但已达到最大重试次数，返回最后一次响应
                if attempt >= self.retry_policy.max_retries:
                    break
                
                # 计算延迟并等待
                delay_ms = self.retry_policy.get_delay_ms(attempt)
                logger.debug(f"[BaseAdapter] Retry attempt {attempt + 1}/{self.retry_policy.max_retries + 1} "
                           f"for {order.client_order_id}, code={resp.code}, delay={delay_ms}ms")
                time.sleep(delay_ms / 1000.0)
                attempt += 1
            
            # 记录重试次数（P2: 补充观测性信息）
            meta = {
                "event": "submit",
                "attempt": attempt + 1,
            }
            if attempt > 0:
                meta["retries"] = attempt
                # P2: 计算退避时间
                backoff_ms = self.retry_policy.get_delay_ms(attempt - 1) if attempt > 0 else 0
                meta["backoff_ms"] = backoff_ms
            self._write_event(order, resp, meta)
            
            # 7. 缓存响应（幂等性，P1: 线程安全 + 容量上限）
            expire_time = time.time() + self.idempotency_ttl_sec
            with self._idempotency_lock:
                # 如果超过容量上限，删除最旧的条目
                if len(self._idempotency_cache) >= self.idempotency_max_size:
                    # 删除最旧的条目（按过期时间）
                    oldest_key = min(
                        self._idempotency_cache.keys(),
                        key=lambda k: self._idempotency_cache[k][0]
                    )
                    del self._idempotency_cache[oldest_key]
                
                self._idempotency_cache[order.client_order_id] = (expire_time, resp)
            
            # 8. 清理过期缓存
            self._cleanup_idempotency_cache()
            
            return resp
            
        finally:
            # 9. 从并发集合移除（P1: 线程安全）
            with self._inflight_lock:
                self._inflight_orders.discard(order.client_order_id)
    
    @abstractmethod
    def _submit_impl(self, order: AdapterOrder) -> AdapterResp:
        """提交订单实现（子类实现）
        
        Args:
            order: 订单对象（已规范化）
            
        Returns:
            适配器响应
        """
        pass
    
    def cancel(self, symbol: str, broker_order_id: str) -> AdapterResp:
        """撤销订单（带节流/重试）
        
        Args:
            symbol: 交易对
            broker_order_id: 交易所订单ID
            
        Returns:
            适配器响应
        """
        # 1. 节流检查
        if not self.rate_limiter.acquire_cancel(timeout=0.1):
            resp = AdapterResp(
                ok=False,
                code=AdapterErrorCode.E_RATE_LIMIT,
                msg="Rate limit exceeded",
            )
            self._write_event(None, resp, {"event": "rate.limit", "symbol": symbol, "broker_order_id": broker_order_id})
            return resp
        
        # 2. 重试逻辑
        attempt = 0
        resp = None
        
        while attempt <= self.retry_policy.max_retries:
            resp = self._cancel_impl(symbol, broker_order_id)
            
            # 如果成功或不可重试，直接返回
            if resp.ok or not self.is_retriable(resp.code):
                break
            
            # 如果可重试但已达到最大重试次数，返回最后一次响应
            if attempt >= self.retry_policy.max_retries:
                break
            
            # 计算延迟并等待
            delay_ms = self.retry_policy.get_delay_ms(attempt)
            logger.debug(f"[BaseAdapter] Retry cancel attempt {attempt + 1}/{self.retry_policy.max_retries + 1} "
                       f"for {broker_order_id}, code={resp.code}, delay={delay_ms}ms")
            time.sleep(delay_ms / 1000.0)
            attempt += 1
        
        # 记录事件（P1: 确保 broker_order_id 在 meta 中，用于撤单事件主键）
        meta = {"event": "cancel", "symbol": symbol, "broker_order_id": broker_order_id}
        if attempt > 0:
            meta["retries"] = attempt
        self._write_event(None, resp, meta)
        
        return resp
    
    @abstractmethod
    def _cancel_impl(self, symbol: str, broker_order_id: str) -> AdapterResp:
        """撤销订单实现（子类实现）
        
        Args:
            symbol: 交易对
            broker_order_id: 交易所订单ID
            
        Returns:
            适配器响应
        """
        pass
    
    @abstractmethod
    def fetch_fills(self, symbol: str, since_ts_ms: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取成交记录
        
        Args:
            symbol: 交易对
            since_ts_ms: 起始时间戳（ms），None表示获取所有成交
            
        Returns:
            成交记录列表
        """
        pass
    
    def is_retriable(self, code: str) -> bool:
        """判断错误是否可重试
        
        Args:
            code: 错误码
            
        Returns:
            是否可重试
        """
        retriable_codes = {
            AdapterErrorCode.E_NETWORK,
            AdapterErrorCode.E_RATE_LIMIT,
            AdapterErrorCode.E_RULES_MISS,  # P1: E.RULES.MISS 现在真正可触发
        }
        return code in retriable_codes
    
    def _write_event(
        self,
        order: Optional[AdapterOrder],
        resp: Optional[AdapterResp],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """写入适配器事件（P2: 补充观测性信息，P1: 添加契约版本和追踪ID）
        
        Args:
            order: 订单对象
            resp: 响应对象
            meta: 元数据
        """
        ts_ms = order.ts_ms if order else int(time.time() * 1000)
        symbol = order.symbol if order else meta.get("symbol", "")
        event = meta.get("event", "submit") if meta else "submit"
        
        # P2: 补充观测性信息到 meta
        enhanced_meta = meta.copy() if meta else {}
        
        # P1: 添加契约版本
        if "contract_ver" not in enhanced_meta:
            enhanced_meta["contract_ver"] = "v1"
        
        # P1: 添加追踪ID（run_id/session_id）
        if "run_id" not in enhanced_meta:
            enhanced_meta["run_id"] = getattr(self, "_run_id", "unknown")
        if "session_id" not in enhanced_meta:
            enhanced_meta["session_id"] = getattr(self, "_session_id", "unknown")
        
        # 添加可用令牌数（如果未提供）
        if "available_tokens" not in enhanced_meta and event in ("submit", "rate.limit"):
            try:
                available_tokens = self.rate_limiter.get_available_tokens("place")
                enhanced_meta["available_tokens"] = available_tokens
            except Exception:
                pass
        
        # 添加规则版本/hash（如果可能）
        if order and "rules_version" not in enhanced_meta:
            try:
                rules = self.rules_cache.get(order.symbol)
                if rules:
                    enhanced_meta["rules_version"] = rules.get("version", "unknown")
                    enhanced_meta["rules_hash"] = hash(str(sorted(rules.items())))
            except Exception:
                pass
        
        self.event_sink.write_event(
            ts_ms=ts_ms,
            mode=self.kind(),
            symbol=symbol,
            event=event,
            order=order,
            resp=resp,
            meta=enhanced_meta,
        )
    
    def _cleanup_idempotency_cache(self) -> None:
        """清理过期的幂等性缓存（P1: 线程安全）"""
        now = time.time()
        with self._idempotency_lock:
            expired_keys = [
                key for key, (expire_time, _) in self._idempotency_cache.items()
                if now >= expire_time
            ]
            for key in expired_keys:
                del self._idempotency_cache[key]
    
    def close(self) -> None:
        """关闭适配器
        
        清理资源，刷新缓存
        """
        with self._inflight_lock:
            self._inflight_orders.clear()
        with self._idempotency_lock:
            self._idempotency_cache.clear()
        if self.event_sink:
            self.event_sink.close()

