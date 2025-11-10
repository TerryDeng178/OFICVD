# -*- coding: utf-8 -*-
"""T08.4: TradeSim - Trade simulator with fees and slippage"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta, time
from pathlib import Path
from typing import Any, Dict, List, Optional
import os

logger = logging.getLogger(__name__)

class TradeSimulator:
    """Simulate trades based on signals with fees and slippage"""
    
    def __init__(
        self,
        config: Dict,
        output_dir: Path,
        ignore_gating_in_backtest: bool = False,
    ):
        """
        Args:
            config: Backtest configuration (backtest section)
            output_dir: Output directory for trades and PnL
        """
        self.config = config
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # P0: 回测信号入口门控可选绕过（用于纯策略收益评估）
        self.ignore_gating_in_backtest = ignore_gating_in_backtest
        
        # P1: PnL日切口径（UTC vs 本地）
        # P1增强: 支持自定义rollover_hour（如08:00切日）
        self.rollover_timezone = config.get("rollover_timezone", os.getenv("ROLLOVER_TZ", "UTC"))
        self.rollover_hour = int(config.get("rollover_hour", os.getenv("ROLLOVER_HOUR", "0")))
        try:
            if self.rollover_timezone != "UTC":
                import pytz
                self.tz = pytz.timezone(self.rollover_timezone)
            else:
                self.tz = timezone.utc
        except Exception:
            logger.warning(f"[TradeSim] Invalid timezone {self.rollover_timezone}, using UTC")
            self.tz = timezone.utc
        
        logger.info(f"[TradeSim] Rollover timezone: {self.rollover_timezone}, rollover_hour: {self.rollover_hour}")
        
        # P0修复: Scenario标准化方法
        def _normalize_scenario(s: str) -> str:
            """标准化scenario格式: A_H_unknown -> A_H"""
            if not s:
                return "unknown"
            parts = s.split("_")
            if len(parts) >= 2:
                return f"{parts[0]}_{parts[1]}"  # A_H_unknown -> A_H
            return s
        
        self._normalize_scenario = _normalize_scenario
        
        # Trade parameters
        self.taker_fee_bps = config.get("taker_fee_bps", 2.0)
        self.slippage_bps = config.get("slippage_bps", 1.0)
        self.notional_per_trade = config.get("notional_per_trade", 1000)
        self.reverse_on_signal = config.get("reverse_on_signal", False)
        self.take_profit_bps = config.get("take_profit_bps")
        self.stop_loss_bps = config.get("stop_loss_bps")
        self.min_hold_time_sec = config.get("min_hold_time_sec")
        # P0修复: 添加超时强平选项，让min_hold_time_sec真正有影响
        self.force_timeout_exit = bool(config.get("force_timeout_exit", False))
        # A组修复: 添加最大持仓时长保护（默认3600s，防止极端长尾）
        self.max_hold_time_sec = config.get("max_hold_time_sec", 3600)
        # B组优化: 死区带（只有价格相对开仓跨出死区才评估反向/TP）
        self.deadband_bps = config.get("deadband_bps", 0)
        
        # P1.3增强: 滑点/费用情境化模型
        self.slippage_model = config.get("slippage_model", os.getenv("SLIPPAGE_MODEL", "static"))
        self.fee_model = config.get("fee_model", os.getenv("FEE_MODEL", "taker_static"))
        
        # P1.3: 加载情境化配置
        self.slippage_piecewise_config = config.get("slippage_piecewise", {})
        self.fee_tiered_config = config.get("fee_tiered", {})
        
        # P1-2: Maker/Taker概率模型参数化配置
        self.fee_maker_taker_config = config.get("fee_maker_taker", {})
        # 默认概率配置
        default_scenario_probs = {
            "Q_H": 0.2,  # 宽&动 - 高taker概率（80% taker）
            "A_L": 0.8,  # 紧&静 - 高maker概率（80% maker）
            "A_H": 0.4,  # 紧&动 - 中等taker概率（60% taker）
            "Q_L": 0.6,  # 宽&静 - 中等maker概率（60% maker）
        }
        self.scenario_probs = self.fee_maker_taker_config.get("scenario_probs", default_scenario_probs)
        self.spread_slope = self.fee_maker_taker_config.get("spread_slope", 0.7)  # spread调整系数
        self.spread_threshold_wide = self.fee_maker_taker_config.get("spread_threshold_wide", 5.0)  # 宽spread阈值
        self.spread_threshold_narrow = self.fee_maker_taker_config.get("spread_threshold_narrow", 1.0)  # 窄spread阈值
        default_side_bias = {
            "buy": 1.2,   # 买入更容易maker
            "sell": 0.8,  # 卖出更容易taker
        }
        self.side_bias = self.fee_maker_taker_config.get("side_bias", default_side_bias)
        self.maker_fee_ratio = self.fee_maker_taker_config.get("maker_fee_ratio", 0.5)  # Maker费率相对taker的比率
        
        logger.info(f"[TradeSim] Slippage model: {self.slippage_model}, Fee model: {self.fee_model}")
        if self.slippage_model == "piecewise":
            logger.info(f"[TradeSim] Slippage piecewise config: {self.slippage_piecewise_config}")
        if self.fee_model == "tiered":
            logger.info(f"[TradeSim] Fee tiered config: {self.fee_tiered_config}")
        if self.fee_model == "maker_taker":
            logger.info(f"[TradeSim] Maker/Taker config: scenario_probs={self.scenario_probs}, spread_slope={self.spread_slope}, side_bias={self.side_bias}")
        
        # State tracking
        self.positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position info
        self.trades: List[Dict[str, Any]] = []
        # A组修复: 跟踪最后一条信号（用于期末强制平仓时提供完整的feature_data）
        self._last_signal_per_symbol: Dict[str, Dict[str, Any]] = {}  # symbol -> last signal
        self.pnl_daily: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "date": "",
            "symbol": "",
            "gross_pnl": 0.0,
            "fee": 0.0,
            "slippage": 0.0,
            "net_pnl": 0.0,
            "turnover": 0.0,
            "trades": 0,
            "wins": 0,
            "losses": 0,
        })
        
        # P1: Gate原因分布统计（用于诊断）
        self.gate_reason_breakdown: Dict[str, int] = defaultdict(int)
        
        # P1.4: 非法场景/费率统计（用于质量监控）
        self.invalid_scenario_count = 0
        self.invalid_fee_tier_count = 0
        self.total_signal_count = 0
        
        # P2.1: Turnover细化统计（maker/taker分项 + 费率等级分布）
        self.turnover_maker = 0.0
        self.turnover_taker = 0.0
        self.fee_tier_distribution: Dict[str, float] = defaultdict(float)  # tier -> turnover
        
        # Output files
        self.trades_file = self.output_dir / "trades.jsonl"
        # 初始化时创建空文件（即使没有交易也创建文件，保持一致性）
        self.trades_file.touch()
        self.pnl_file = self.output_dir / "pnl_daily.jsonl"
        self.gate_reason_file = self.output_dir / "gate_reason_breakdown.json"
        # P2修复: 时间线探针（trace）- 输出每笔entry/exit的详细信息
        self.trace_file = self.output_dir / "trace.csv"
        self._init_trace_file()
        
        logger.info(
            f"[TradeSim] Initialized: fee={self.taker_fee_bps}bps, "
            f"slippage={self.slippage_bps}bps, notional={self.notional_per_trade}"
        )
    
    def _init_trace_file(self) -> None:
        """P2修复: 初始化trace文件（时间线探针）"""
        import csv
        
        if not self.trace_file.exists():
            with open(self.trace_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ts_ms", "symbol", "side", "action", "confirm", "gating_blocked", "gate_reason",
                    "hold_time_s", "pnl_bps", "spread_bps", "vol_bps", "scenario", "exit_reason",
                    "signal_score", "signal_type"
                ])
    
    def _record_trace(self, ts_ms: int, symbol: str, side: str, action: str, signal: Optional[Dict[str, Any]] = None,
                     position: Optional[Dict[str, Any]] = None, exit_reason: Optional[str] = None) -> None:
        """P2修复: 记录trace信息（时间线探针）"""
        import csv
        
        feature_data = signal.get("_feature_data", {}) if signal else {}
        gating_blocked = signal.get("gating_blocked", signal.get("gating", False)) if signal else False
        
        # 计算持仓时长和PnL
        hold_time_s = None
        pnl_bps = None
        if position and action == "exit":
            entry_ts_ms = position.get("entry_ts_ms", 0)
            entry_px = position.get("entry_px", 0)
            pos_side = position.get("side", "")
            if entry_ts_ms and ts_ms:
                hold_time_s = (ts_ms - entry_ts_ms) / 1000.0
            if entry_px:
                # 从signal或position获取mid_price（_check_exit传入的mid_price）
                mid_price = signal.get("mid_price", 0) if signal else 0
                if not mid_price and position:
                    # 如果没有mid_price，使用entry_px作为近似
                    mid_price = entry_px
                if mid_price and entry_px:
                    if pos_side == "buy":
                        pnl_bps = ((mid_price - entry_px) / entry_px) * 10000
                    else:
                        pnl_bps = ((entry_px - mid_price) / entry_px) * 10000
        
        with open(self.trace_file, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                ts_ms,
                symbol,
                side or "",
                action,
                signal.get("confirm", False) if signal else False,
                gating_blocked,
                signal.get("gate_reason", "") if signal else "",
                hold_time_s or "",
                pnl_bps or "",
                feature_data.get("spread_bps", ""),
                feature_data.get("vol_bps", ""),
                feature_data.get("scenario_2x2", ""),
                exit_reason or "",
                signal.get("signal_score", "") if signal else "",
                signal.get("signal_type", "") if signal else "",
            ])
    
    def _biz_date(self, ts_ms: int) -> str:
        """Calculate business date with timezone and custom rollover hour
        
        P1增强: 支持自定义rollover_hour（如08:00切日）
        """
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=self.tz)
        
        # 若需要自定义RTH切分（如每日08:00切日）
        if self.rollover_hour != 0:
            # 先左移rollover_hour小时，取date，再右移回来
            shift = timedelta(hours=self.rollover_hour)
            dt_shifted = dt - shift
            date_part = dt_shifted.date()
            # 组合回带时区的datetime
            dt_combined = datetime.combine(date_part, time(0, 0), tzinfo=self.tz) + shift
            return dt_combined.strftime("%Y-%m-%d")
        
        return dt.strftime("%Y-%m-%d")
    
    def _compute_slippage_bps(self, signal: Optional[Dict[str, Any]], mid_px: float, side: str) -> float:
        """Compute slippage bps based on model
        
        P1增强: 支持情境化滑点模型（static/linear/piecewise）
        """
        if self.slippage_model == "static":
            return self.slippage_bps
        
        # 获取市场上下文
        fd = signal.get("_feature_data", {}) if signal else {}
        spread = float(fd.get("spread_bps") or 0.0)
        vol = float(fd.get("vol_bps") or 0.0)
        scenario = fd.get("scenario_2x2", "")
        
        if self.slippage_model == "linear":
            # P1增强: 线性模型: spread + volatility
            # P0-3: vol_bps兜底（如果缺失，使用abs(return_1s)）
            vol_bps = fd.get("vol_bps")
            if vol_bps is None:
                return_1s = fd.get("return_1s", 0.0)
                vol_bps = abs(float(return_1s))
            else:
                vol_bps = float(vol_bps)
            return max(self.slippage_bps, 0.5 * spread + 0.3 * vol_bps)
        
        if self.slippage_model == "piecewise":
            # P1.3: 分段模型: 基于spread和scenario（支持YAML配置的场景倍数）
            base = max(spread, 1.0)
            
            # P0修复: 场景名校验（A_H/A_L/Q_H/Q_L）
            # P1.4: 统计非法场景出现次数
            valid_scenarios = ("A_H", "A_L", "Q_H", "Q_L")
            if scenario not in valid_scenarios:
                self.invalid_scenario_count += 1
                logger.warning(f"[TradeSim] Unknown scenario '{scenario}', using default slippage")
                return self.slippage_bps
            
            # P1.3: 从配置中获取场景倍数（如果存在）
            slippage_config = getattr(self, "slippage_piecewise_config", {})
            scenario_multipliers = slippage_config.get("scenario_multipliers", {})
            spread_base_multiplier = slippage_config.get("spread_base_multiplier", 1.0)
            
            # 应用spread基数倍数
            base = spread * spread_base_multiplier
            
            # 应用场景倍数
            scenario_multiplier = scenario_multipliers.get(scenario, 1.0)
            base *= scenario_multiplier
            
            # 确保不低于基础滑点
            return max(base, self.slippage_bps)
        
        # 默认返回静态值
        return self.slippage_bps
    
    def _compute_fee_bps(self, signal: Optional[Dict[str, Any]], side: str, qty: float, notional: float, return_prob: bool = False):
        """Compute fee bps based on model
        
        P0-3: 同时返回maker_probability用于turnover统计
        P1增强: 支持情境化费用模型（taker_static/tiered/maker_taker）
        
        Args:
            signal: Signal dict with _feature_data
            side: Trade side (buy/sell)
            qty: Trade quantity
            notional: Trade notional
            return_prob: If True, return (fee_bps, maker_probability); else return fee_bps only
        
        Returns:
            fee_bps if return_prob=False, else (fee_bps, maker_probability)
        """
        if self.fee_model == "taker_static":
            if return_prob:
                return self.taker_fee_bps, 0.0  # taker_static模式下maker概率为0
            return self.taker_fee_bps
        
        # 获取市场上下文
        fd = signal.get("_feature_data", {}) if signal else {}
        tier = (fd.get("fee_tier") or "TM").upper()
        
        if self.fee_model == "tiered":
            # P1.3: 分档模型: 根据fee_tier调整费率（支持YAML配置的费率表）
            # P0修复: 场景名校验（TM/MM等）
            # P1.4: 统计非法费率层级出现次数
            valid_tiers = ("TM", "MM", "TT", "MT", "TK", "MK")  # 扩展支持TK/MK
            if tier not in valid_tiers:
                self.invalid_fee_tier_count += 1
                logger.warning(f"[TradeSim] Unknown fee_tier '{tier}', using default fee")
                return self.taker_fee_bps
            
            # P1.3: 从配置中获取费率表（如果存在）
            fee_config = getattr(self, "fee_tiered_config", {})
            tier_mapping = fee_config.get("tier_mapping", {})
            
            # 如果配置中有该tier，使用配置值；否则使用默认映射
            if tier in tier_mapping:
                fee_bps = tier_mapping[tier]
            else:
                # 默认映射（向后兼容）
                default_mapping = {
                    "TM": self.taker_fee_bps,  # Taker Maker
                    "MM": self.taker_fee_bps * 0.5,  # Maker Maker (假设maker费率更低)
                    "TT": self.taker_fee_bps,  # Taker Taker
                    "MT": self.taker_fee_bps * 0.5,  # Maker Taker
                    "TK": self.taker_fee_bps,  # Taker Taker (别名)
                    "MK": self.taker_fee_bps * 0.5,  # Maker Taker (别名)
                }
                fee_bps = default_mapping.get(tier, self.taker_fee_bps)
            
            # P0-3: tiered模式下，根据tier推断maker概率（简化：MM/MK=1.0, TM/TT=0.0, MT/TK=0.5）
            maker_prob = 0.0
            if tier in ("MM", "MK"):
                maker_prob = 1.0
            elif tier in ("MT", "TK"):
                maker_prob = 0.5
            
            if return_prob:
                return fee_bps, maker_prob
            return fee_bps
        
        if self.fee_model == "maker_taker":
            # P0-3/P1-2: Maker/Taker费用模型（基于spread_bps/scenario_2x2决定成交落点概率）
            # P1-2: 概率规则已参数化，从配置读取
            # 获取市场上下文
            fd = signal.get("_feature_data", {}) if signal else {}
            spread_bps = float(fd.get("spread_bps") or 0.0)
            raw_scenario = fd.get("scenario_2x2", "") or (signal.get("scenario", "") if signal else "")
            
            # P0修复: 标准化scenario格式（A_H_unknown -> A_H）
            scenario = self._normalize_scenario(raw_scenario)
            
            # P1-2: 基于scenario决定maker/taker概率（从配置读取，带兜底）
            maker_probability = self.scenario_probs.get(scenario, self.scenario_probs.get("default", 0.5))
            
            # P1-2: 基于spread调整（从配置读取阈值和系数）
            if spread_bps > self.spread_threshold_wide:  # 宽spread
                maker_probability *= self.spread_slope  # 降低maker概率
            elif spread_bps < self.spread_threshold_narrow:  # 窄spread
                maker_probability *= (1.0 / self.spread_slope)  # 提高maker概率（但不能超过1.0）
                maker_probability = min(maker_probability, 1.0)
            
            # P1-2: 根据side决定（从配置读取bias）
            side_bias_value = self.side_bias.get(side, 1.0)
            maker_probability *= side_bias_value
            
            maker_probability = max(0.0, min(1.0, maker_probability))  # 限制在[0, 1]
            
            # P1-2: 根据概率决定费率（从配置读取maker费率比率）
            maker_fee = self.taker_fee_bps * self.maker_fee_ratio
            taker_fee = self.taker_fee_bps
            
            # 返回期望费率
            expected_fee = maker_probability * maker_fee + (1 - maker_probability) * taker_fee
            
            # P0-3: 如果return_prob=True，同时返回maker_probability
            if return_prob:
                return expected_fee, maker_probability
            return expected_fee
        
        # 默认返回静态值
        return self.taker_fee_bps
    
    def process_signal(self, signal: Dict[str, Any], mid_price: float) -> Optional[Dict[str, Any]]:
        """
        Process a signal and generate trade if applicable
        
        Args:
            signal: Signal dict from CORE_ALGO
            mid_price: Current mid price
            
        Returns:
            Trade dict if trade executed, None otherwise
        """
        symbol = signal.get("symbol", "")
        ts_ms = signal.get("ts_ms", 0)
        confirm = signal.get("confirm", False)
        # 修复A: 门控语义 - gating=True表示"被门控阻止"，优先读取gating_blocked（兼容gating）
        gating_blocked = signal.get("gating_blocked", signal.get("gating", False))
        signal_type = signal.get("signal_type", "neutral")
        
        # P0修复: 统计所有信号的gate原因（包括未确认和被阻止的）
        # 先统计gate原因，再判断是否处理
        if gating_blocked:
            gate_reason = signal.get("gate_reason", "unknown")
            # P0修复: 拆分逗号分隔的gate原因，分别统计
            self._record_gate_reasons(gate_reason)
        
        # 修复A: 仅处理已确认信号
        if not confirm:
            return None
        
        # 修复A: 执行门控 - 若不是"忽略门控回测"，则gating_blocked=True直接拦截
        if not self.ignore_gating_in_backtest and gating_blocked:
            # gate_reason已在上面统计，这里直接返回
            logger.debug(f"[TradeSim] Signal blocked by gate: {gate_reason}, symbol={symbol}, ts_ms={ts_ms}")
            return None
        
        # P1.4: 统计总信号数（用于计算非法场景/费率比例）
        self.total_signal_count += 1
        
        # A组修复: 跟踪最后一条信号（用于期末强制平仓时提供完整的feature_data）
        self._last_signal_per_symbol[symbol] = signal.copy()
        
        # P1: 统计gate原因分布（即使忽略gating也记录，用于诊断）
        # P1: 同时汇总Aligner质量位（lag_bad, is_gap_second）到gate_reason_breakdown
        # 注意：gate原因已在上面统计，这里不再重复统计
        
        # P1: 汇总Aligner质量位到gate_reason_breakdown（用于诊断）
        # 注意：这些字段来自feature_row，需要通过signal传递
        feature_data = signal.get("_feature_data", {})  # 可选：从signal中获取feature数据
        if feature_data.get("lag_bad_price", 0) == 1:
            self.gate_reason_breakdown["lag_bad_price"] += 1
        if feature_data.get("lag_bad_orderbook", 0) == 1:
            self.gate_reason_breakdown["lag_bad_orderbook"] += 1
        if feature_data.get("is_gap_second", 0) == 1:
            self.gate_reason_breakdown["is_gap_second"] += 1
        
        # Determine direction
        side = None
        if signal_type in ("buy", "strong_buy"):
            side = "buy"
        elif signal_type in ("sell", "strong_sell"):
            side = "sell"
        
        if not side:
            return None
        
        # Check if we should enter/exit/reverse
        position = self.positions.get(symbol)
        
        if position is None:
            # Enter new position
            trade = self._enter_position(symbol, side, ts_ms, mid_price, signal)
            # P2修复: 记录entry trace
            if trade:
                self._record_trace(ts_ms, symbol, side, "entry", signal)
            return trade
        else:
            # Check exit conditions
            exit_trade = self._check_exit(position, signal, ts_ms, mid_price)
            if exit_trade:
                # P2修复: 记录exit trace
                exit_reason = exit_trade.get("reason", "unknown")
                self._record_trace(ts_ms, symbol, position["side"], "exit", signal, position, exit_reason)
                return exit_trade
            
            # Check reverse condition
            if self.reverse_on_signal:
                current_side = position["side"]
                if (side == "buy" and current_side == "sell") or (side == "sell" and current_side == "buy"):
                    # Close current and open reverse
                    # P0-1: _exit_position()内部已调用_record_trade()，无需重复写入
                    exit_trade = self._exit_position(position, ts_ms, mid_price, "reverse", signal)
                    if exit_trade:
                        return self._enter_position(symbol, side, ts_ms, mid_price, signal)
        
        return None
    
    def _enter_position(self, symbol: str, side: str, ts_ms: int, mid_price: float, signal: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Enter a new position
        
        P1增强: 支持情境化滑点和费用
        """
        # P1增强: 计算情境化滑点
        slippage_bps = self._compute_slippage_bps(signal, mid_price, side)
        slippage_multiplier = 1.0 + (1 if side == "buy" else -1) * (slippage_bps / 10000)
        exec_px = mid_price * slippage_multiplier
        
        # Calculate quantity
        qty = self.notional_per_trade / exec_px
        
        # P1增强: 计算情境化费用
        notional = exec_px * qty
        # P0-3: 获取maker_probability用于turnover统计
        fee_result = self._compute_fee_bps(signal, side, qty, notional, return_prob=True)
        if isinstance(fee_result, tuple):
            fee_bps, maker_prob = fee_result
        else:
            fee_bps = fee_result
            maker_prob = 0.0  # 默认taker
        
        fee = notional * (fee_bps / 10000)
        
        # P1.5/P2.1: 获取feature_data（用于场景标签和费率层级）
        feature_data = signal.get("_feature_data", {}) if signal else {}
        
        # P0-3: 使用概率期望判断maker/taker（而非简单的side判定）
        is_maker = maker_prob > 0.5  # 概率>50%视为maker
        
        # Record position
        # P0修复: 保存entry_notional用于turnover计算
        entry_notional = exec_px * qty
        self.positions[symbol] = {
            "symbol": symbol,
            "side": side,
            "entry_ts_ms": ts_ms,
            "entry_px": exec_px,
            "qty": qty,
            "entry_fee": fee,
            "entry_notional": entry_notional,  # P0修复: 保存entry_notional
            "is_maker": is_maker,  # P2.1: 记录maker/taker（向后兼容）
            "maker_probability": maker_prob,  # P0-3: 记录maker概率（用于turnover统计）
            "fee_tier": feature_data.get("fee_tier", "TM"),  # P2.1: 记录费率层级
        }
        
        # Create trade record
        # P1.5: 添加scenario_2x2和session到trade记录（用于Metrics维度拆分）
        trade = {
            "ts_ms": ts_ms,
            "symbol": symbol,
            "side": side,
            "px": exec_px,
            "qty": qty,
            "fee": fee,
            "slippage_bps": slippage_bps if side == "buy" else -slippage_bps,
            "reason": "entry",
            "pos_after": 1 if side == "buy" else -1,
            # P1.5: 添加场景和会话标签
            "scenario_2x2": feature_data.get("scenario_2x2"),
            "session": feature_data.get("session"),
        }
        
        self._record_trade(trade)
        return trade
    
    def _check_exit(self, position: Dict[str, Any], signal: Dict[str, Any], ts_ms: int, mid_price: float) -> Optional[Dict[str, Any]]:
        """Check if position should be exited
        
        修复B: 重排退出判定顺序，保证min_hold_time_sec优先生效
        - 止损例外：安全优先，任何时刻都可触发
        - 未达最小持仓 → 禁止TP/反向退出
        - 达到最小持仓 → 按TP/反向正常评估
        """
        symbol = position["symbol"]
        entry_ts_ms = position["entry_ts_ms"]
        entry_px = position["entry_px"]
        side = position["side"]
        
        # P2修复: 将mid_price添加到signal中，供trace记录使用
        if signal:
            signal["mid_price"] = mid_price
        
        # 修复C: 确保退出只由已确认信号触发
        confirm = signal.get("confirm", False)
        if not confirm:
            return None
        
        # 修复B: 0) 计算持仓时长
        hold_time_sec = (ts_ms - entry_ts_ms) / 1000 if entry_ts_ms else 0
        
        # A组修复: 最大持仓时长保护（防止极端长尾）
        if self.max_hold_time_sec and hold_time_sec >= self.max_hold_time_sec:
            logger.warning(
                f"[TradeSim] Max hold time exceeded: symbol={symbol}, "
                f"hold_time_sec={hold_time_sec:.1f} >= {self.max_hold_time_sec}s, forcing timeout exit"
            )
            exit_trade = self._exit_position(position, ts_ms, mid_price, "timeout", signal)
            if exit_trade:
                self._record_trace(ts_ms, symbol, side, "exit", signal, position, "timeout")
            return exit_trade
        
        # 计算PnL（用于TP/SL判断）
        if side == "buy":
            pnl_bps = ((mid_price - entry_px) / entry_px) * 10000
        else:
            pnl_bps = ((entry_px - mid_price) / entry_px) * 10000
        
        # 修复B: 1) 止损例外：安全优先，任何时刻都可触发
        if self.stop_loss_bps and pnl_bps <= -self.stop_loss_bps:
            # 验证不变量4: 记录止损时的市场状态
            feature_data = signal.get("_feature_data", {})
            logger.debug(
                f"[TradeSim] Stop loss triggered: symbol={symbol}, "
                f"pnl_bps={pnl_bps:.2f}, spread_bps={feature_data.get('spread_bps', 'N/A')}, "
                f"scenario={feature_data.get('scenario_2x2', 'N/A')}"
            )
            exit_trade = self._exit_position(position, ts_ms, mid_price, "stop_loss", signal)
            if exit_trade:
                # P2修复: 记录exit trace
                self._record_trace(ts_ms, symbol, side, "exit", signal, position, "stop_loss")
            return exit_trade
        
        # 修复B: 2) 未达最小持仓 → 禁止TP/反向退出（可通过配置开例外）
        if self.min_hold_time_sec and hold_time_sec < self.min_hold_time_sec:
            # 验证不变量2: hold_time_sec < min_hold_time_sec期间，不允许触发reverse_signal与take_profit
            return None
        
        # 修复B: 3) 达到最小持仓 → 按TP/反向正常评估
        signal_type = signal.get("signal_type", "neutral")
        
        # B组优化: 死区带检查（只有价格相对开仓跨出死区才评估反向/TP）
        if self.deadband_bps > 0:
            if abs(pnl_bps) < self.deadband_bps:
                # 价格在死区内，不评估反向/TP
                return None
        
        # 检查止盈
        if self.take_profit_bps and pnl_bps >= self.take_profit_bps:
            exit_trade = self._exit_position(position, ts_ms, mid_price, "take_profit", signal)
            if exit_trade:
                self._record_trace(ts_ms, symbol, side, "exit", signal, position, "take_profit")
            return exit_trade
        
        # 检查反向信号
        if side == "buy" and signal_type in ("sell", "strong_sell"):
            # 验证不变量3: 退出必须来自已确认信号
            logger.debug(
                f"[TradeSim] Reverse exit: symbol={symbol}, signal_type={signal_type}, "
                f"confirm={confirm}, signal_score={signal.get('signal_score', 'N/A')}, "
                f"gate_reason={signal.get('gate_reason', 'N/A')}"
            )
            exit_trade = self._exit_position(position, ts_ms, mid_price, "reverse_signal", signal)
            if exit_trade:
                self._record_trace(ts_ms, symbol, side, "exit", signal, position, "reverse_signal")
            return exit_trade
        if side == "sell" and signal_type in ("buy", "strong_buy"):
            logger.debug(
                f"[TradeSim] Reverse exit: symbol={symbol}, signal_type={signal_type}, "
                f"confirm={confirm}, signal_score={signal.get('signal_score', 'N/A')}, "
                f"gate_reason={signal.get('gate_reason', 'N/A')}"
            )
            exit_trade = self._exit_position(position, ts_ms, mid_price, "reverse_signal", signal)
            if exit_trade:
                self._record_trace(ts_ms, symbol, side, "exit", signal, position, "reverse_signal")
            return exit_trade
        
        # 修复B: 4) 超时离场（保留现逻辑）
        if self.min_hold_time_sec and hold_time_sec >= self.min_hold_time_sec:
            if self.force_timeout_exit:
                # P0修复: 强制超时平仓（无需反向信号）
                exit_trade = self._exit_position(position, ts_ms, mid_price, "timeout", signal)
                if exit_trade:
                    self._record_trace(ts_ms, symbol, side, "exit", signal, position, "timeout")
                return exit_trade
        
        return None
    
    def _exit_position(self, position: Dict[str, Any], ts_ms: int, mid_price: float, reason: str, signal: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Exit a position
        
        P1增强: 支持情境化滑点和费用
        """
        symbol = position["symbol"]
        side = position["side"]
        entry_px = position["entry_px"]
        qty = position["qty"]
        entry_fee = position["entry_fee"]
        
        # P1增强: 计算情境化滑点（出场方向）
        exit_side = "sell" if side == "buy" else "buy"
        slippage_bps = self._compute_slippage_bps(signal, mid_price, exit_side)
        slippage_multiplier = 1.0 + (1 if exit_side == "buy" else -1) * (slippage_bps / 10000)
        exec_px = mid_price * slippage_multiplier
        
        # Calculate PnL
        if side == "buy":
            gross_pnl = (exec_px - entry_px) * qty
        else:
            gross_pnl = (entry_px - exec_px) * qty
        
        # P1增强: 计算情境化费用
        notional = exec_px * qty
        # P0-3: 获取maker_probability（在turnover统计中使用）
        exit_fee_result = self._compute_fee_bps(signal, exit_side, qty, notional, return_prob=True)
        if isinstance(exit_fee_result, tuple):
            fee_bps, exit_maker_prob = exit_fee_result
        else:
            fee_bps = exit_fee_result
            exit_maker_prob = 0.0  # 默认taker
        exit_fee = notional * (fee_bps / 10000)
        
        # P0: 修正滑点双计问题
        # exec_px已经包含滑点修正，不再单独扣除slippage_cost
        # 但保留slippage_cost作为监控指标（不参与净值计算）
        slippage_cost = abs(mid_price - exec_px) * qty
        
        # Net PnL (仅扣除费用，滑点已体现在exec_px中)
        net_pnl = gross_pnl - entry_fee - exit_fee
        
        # Create trade record
        # P1.5: 添加scenario_2x2和session到trade记录（用于Metrics维度拆分）
        feature_data = signal.get("_feature_data", {}) if signal else {}
        trade = {
            "ts_ms": ts_ms,
            "symbol": symbol,
            "side": exit_side,
            "px": exec_px,
            "qty": qty,
            "fee": exit_fee,
            "slippage_bps": slippage_bps if exit_side == "buy" else -slippage_bps,
            "reason": reason,
            "pos_after": 0,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            # P1.5: 添加场景和会话标签
            "scenario_2x2": feature_data.get("scenario_2x2"),
            "session": feature_data.get("session"),
        }
        
        # P1增强: Update daily PnL with timezone-aware date rollover (using _biz_date)
        date_str = self._biz_date(ts_ms)
        daily = self.pnl_daily[f"{date_str}_{symbol}"]
        daily["date"] = date_str
        daily["symbol"] = symbol
        daily["gross_pnl"] += gross_pnl
        daily["fee"] += entry_fee + exit_fee
        daily["slippage"] += slippage_cost
        daily["net_pnl"] += net_pnl
        # P0修复: 成交额计算（使用entry_notional + exit_notional）
        entry_notional = position.get("entry_notional", entry_px * qty)
        daily["turnover"] += entry_notional + notional  # Entry + exit
        
        # P0-3: Turnover细化统计（使用maker_probability期望口径，而非side判定）
        # 获取entry和exit的maker概率
        entry_maker_prob = position.get("maker_probability", 0.0)  # 从position记录中获取
        
        # P0-3: 使用概率期望计入turnover_maker/taker
        self.turnover_maker += entry_notional * entry_maker_prob
        self.turnover_taker += entry_notional * (1 - entry_maker_prob)
        self.turnover_maker += notional * exit_maker_prob
        self.turnover_taker += notional * (1 - exit_maker_prob)
        
        # P2.1: 费率等级分布统计
        entry_fee_tier = position.get("fee_tier", "TM")
        exit_fee_tier = feature_data.get("fee_tier", "TM")
        self.fee_tier_distribution[entry_fee_tier] += entry_notional
        self.fee_tier_distribution[exit_fee_tier] += notional
        
        daily["trades"] += 1
        if net_pnl > 0:
            daily["wins"] += 1
        elif net_pnl < 0:
            daily["losses"] += 1
        
        # Remove position
        del self.positions[symbol]
        
        self._record_trade(trade)
        return trade
    
    def _record_trade(self, trade: Dict[str, Any]) -> None:
        """Record trade to JSONL file"""
        self.trades.append(trade)
        try:
            with self.trades_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(trade, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Error writing trade: {e}")
    
    def close_all_positions(self, current_prices: Dict[str, float], last_data_ts_ms: Optional[int] = None) -> None:
        """P1: Close all open positions at current prices (technical close at end of backtest)
        
        代码.5: 使用最后一条市场数据ts作为"日末平仓"时间，而非now()
        
        P0修复: 如果force_timeout_exit启用，优先使用timeout退出（满足min_hold_time_sec要求）
        
        Args:
            current_prices: Current mid prices for each symbol
            last_data_ts_ms: Timestamp of the last market data (代码.5)
        """
        if not self.positions:
            logger.info("[TradeSim] No open positions to close")
            return
        
        # 代码.5: 使用最后一条市场数据ts，避免切日PnL被当前机器时间影响
        if last_data_ts_ms is None:
            # Fallback: 如果没有提供，使用当前时间（向后兼容）
            last_data_ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            logger.warning("[TradeSim] No last_data_ts_ms provided, using current time (may affect PnL rollover)")
        else:
            logger.info(f"[TradeSim] Using last market data timestamp: {last_data_ts_ms} for position close")
        
        logger.info(f"[TradeSim] Closing {len(self.positions)} open positions (technical close)")
        
        for symbol, position in list(self.positions.items()):
            mid_price = current_prices.get(symbol, position["entry_px"])
            
            # A组修复: 使用最后一条信号（包含完整的feature_data）进行期末强制平仓
            last_signal = self._last_signal_per_symbol.get(symbol, {})
            # 如果没有最后一条信号，创建一个最小信号字典
            if not last_signal:
                last_signal = {
                    "symbol": symbol,
                    "ts_ms": last_data_ts_ms,
                    "confirm": True,
                    "_feature_data": {},
                }
            
            # P0修复: 如果force_timeout_exit启用，检查是否满足min_hold_time_sec
            # 如果满足，使用timeout退出（符合force_timeout_exit语义）
            # 如果不满足或未启用，使用rollover_close（技术性平仓）
            exit_reason = "rollover_close"
            if self.force_timeout_exit and self.min_hold_time_sec:
                entry_ts_ms = position.get("entry_ts_ms", 0)
                hold_time_sec = (last_data_ts_ms - entry_ts_ms) / 1000.0
                if hold_time_sec >= self.min_hold_time_sec:
                    exit_reason = "timeout"
                    logger.debug(f"[TradeSim] Position {symbol} held for {hold_time_sec:.1f}s >= {self.min_hold_time_sec}s, using timeout exit")
                else:
                    logger.debug(f"[TradeSim] Position {symbol} held for {hold_time_sec:.1f}s < {self.min_hold_time_sec}s, using rollover_close")
            
            # A组修复: 使用最后一条信号（包含完整的feature_data）进行期末强制平仓
            # 确保trace记录完整
            exit_trade = self._exit_position(position, last_data_ts_ms, mid_price, exit_reason, last_signal)
            if exit_trade:
                self._record_trace(last_data_ts_ms, symbol, position["side"], "exit", last_signal, position, exit_reason)
        
        logger.info(f"[TradeSim] Closed {len(self.positions)} positions (all positions should be closed now)")
    
    def save_pnl_daily(self) -> None:
        """Save daily PnL to JSONL file
        
        P0修复: 每日RR公式改为基于出场记录聚合（赢单均值/亏单均值）
        """
        try:
            # P0修复: 基于出场记录聚合RR（只统计exit/reverse/stop/take_profit等）
            exit_reasons = ["exit", "reverse", "reverse_signal", "stop_loss", "take_profit", "timeout", "rollover_close"]
            exit_trades = [t for t in self.trades if t.get("reason") in exit_reasons]
            
            # 按日期和symbol分组出场记录
            exit_by_date_symbol: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for trade in exit_trades:
                ts_ms = trade.get("ts_ms", 0)
                symbol = trade.get("symbol", "")
                date_str = self._biz_date(ts_ms)
                key = f"{date_str}_{symbol}"
                exit_by_date_symbol[key].append(trade)
            
            with self.pnl_file.open("w", encoding="utf-8") as f:
                for daily in sorted(self.pnl_daily.values(), key=lambda x: (x["date"], x["symbol"])):
                    # Calculate win rate
                    if daily["trades"] > 0:
                        daily["win_rate"] = daily["wins"] / daily["trades"]
                    else:
                        daily["win_rate"] = 0.0
                    
                    # P0修复: RR改为基于出场记录（赢单均值/亏单均值）
                    key = f"{daily['date']}_{daily['symbol']}"
                    daily_exits = exit_by_date_symbol.get(key, [])
                    if daily_exits:
                        win_exits = [t for t in daily_exits if t.get("net_pnl", 0) > 0]
                        loss_exits = [t for t in daily_exits if t.get("net_pnl", 0) < 0]
                        
                        avg_win = sum(t.get("net_pnl", 0) for t in win_exits) / len(win_exits) if win_exits else 0.0
                        avg_loss = abs(sum(t.get("net_pnl", 0) for t in loss_exits) / len(loss_exits)) if loss_exits else 0.0
                        
                        if avg_loss > 0:
                            daily["rr"] = avg_win / avg_loss
                        else:
                            daily["rr"] = float("inf") if avg_win > 0 else 0.0
                    else:
                        # 如果没有出场记录，使用旧公式（向后兼容）
                        if daily["losses"] > 0:
                            daily["rr"] = abs(daily["wins"] * daily["net_pnl"] / daily["trades"] / daily["losses"]) if daily["trades"] > 0 else 0.0
                        else:
                            daily["rr"] = float("inf") if daily["wins"] > 0 else 0.0
                    
                    f.write(json.dumps(daily, ensure_ascii=False) + "\n")
            logger.info(f"[TradeSim] Saved {len(self.pnl_daily)} daily PnL records")
        except Exception as e:
            logger.error(f"Error saving daily PnL: {e}")
        
        # P1: Save gate_reason_breakdown
        self._save_gate_reason_breakdown()
    
    def _record_gate_reasons(self, gate_reason: Optional[str]) -> None:
        """P0修复: 拆分逗号分隔的gate原因，分别统计，并映射融合理由到Gate原因
        
        Args:
            gate_reason: 逗号分隔的gate原因字符串，如 "weak_signal,spread_bps>8.0,reason:low_consistency_throttle"
        """
        if not gate_reason:
            self.gate_reason_breakdown["unknown"] += 1
            return
        
        # 拆分逗号分隔的原因
        reasons = [r.strip() for r in gate_reason.split(",") if r.strip()]
        if not reasons:
            self.gate_reason_breakdown["unknown"] += 1
            return
        
        # P0修复: 融合理由到Gate原因的映射表
        fusion_reason_mapping = {
            "low_consistency_throttle": "low_consistency",
            "lag_exceeded": "lag_sec_exceeded",
            "warmup": "component_warmup",  # fusion组件的warmup
            "degraded_ofi_only": "degraded_ofi_only",
            "degraded_cvd_only": "degraded_cvd_only",
        }
        
        # 分别统计每个原因
        for reason in reasons:
            # 处理spread_bps>阈值格式
            if reason.startswith("spread_bps>"):
                self.gate_reason_breakdown["spread_bps_exceeded"] += 1
            # 处理lag_sec>阈值格式
            elif reason.startswith("lag_sec>"):
                self.gate_reason_breakdown["lag_sec_exceeded"] += 1
            # 处理reason:code格式（融合理由）
            elif reason.startswith("reason:"):
                code = reason.replace("reason:", "").strip()
                # 映射融合理由到Gate原因
                mapped_reason = fusion_reason_mapping.get(code, f"reason_{code}")
                self.gate_reason_breakdown[mapped_reason] += 1
            # 直接原因
            elif reason == "weak_signal":
                self.gate_reason_breakdown["weak_signal"] += 1
            elif reason == "low_consistency":
                self.gate_reason_breakdown["low_consistency"] += 1
            elif reason == "warmup":
                self.gate_reason_breakdown["warmup"] += 1
            elif reason.startswith("reverse_cooldown"):
                self.gate_reason_breakdown["reverse_cooldown"] += 1
            else:
                # 其他未知原因直接记录
                self.gate_reason_breakdown[reason] += 1
    
    def _save_gate_reason_breakdown(self) -> None:
        """P1: Save gate reason breakdown to JSON file"""
        try:
            with self.gate_reason_file.open("w", encoding="utf-8") as f:
                json.dump(dict(self.gate_reason_breakdown), f, ensure_ascii=False, indent=2)
            logger.info(f"[TradeSim] Saved gate_reason_breakdown to {self.gate_reason_file}")
        except Exception as e:
            logger.error(f"Error saving gate_reason_breakdown: {e}")

