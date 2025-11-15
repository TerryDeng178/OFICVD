# -*- coding: utf-8 -*-
"""
Strategy Policy Layer

统一的策略决策逻辑，支持：
- 回测环境
- 测试网环境
- 实盘环境

确保三套环境使用相同的策略决策逻辑，避免行为漂移。
"""

from typing import Dict, Any, Optional

# 软/硬护栏分类常量
SOFT_GATING = {"weak_signal", "low_consistency"}
HARD_ALWAYS_BLOCK = {"fallback", "price_cache_failed", "no_price", "spread_bps_exceeded", "lag_sec_exceeded", "kill_switch", "guarded"}


def is_tradeable(signal: Dict[str, Any], gating_mode: str = "strict") -> tuple[bool, Optional[str]]:
    """判断信号是否可以交易

    Args:
        signal: 信号字典
        gating_mode: gating策略模式
            - strict: 生产严格模式，任何gating都阻塞
            - ignore_soft: 忽略软护栏（weak_signal/low_consistency等）
            - ignore_all: 完全忽略gating，只看confirm

    Returns:
        (can_trade, reason): can_trade为True表示可以交易，reason为不可交易的原因
    """
    gating = list(signal.get("gating") or [])
    confirm = bool(signal.get("confirm", False))

    # 1) 硬护栏永远阻塞（即使在ignore模式下）
    original_gating = list(gating or [])
    hard_blocks = [g for g in original_gating if g in HARD_ALWAYS_BLOCK]
    if hard_blocks:
        return False, f"gating_hard_{','.join(hard_blocks)}"

    # 2) 根据模式调整gating视图
    if gating_mode == "ignore_soft":
        gating = [g for g in gating if g not in SOFT_GATING]
    elif gating_mode == "ignore_all":
        gating = []

    # 3) 剩余gating一律视为阻塞
    if gating:
        return False, f"gating_{','.join(gating)}"

    # 4) confirm检查照旧
    if not confirm:
        return False, "confirm_false"

    # 5) 通过所有检查，可以交易
    return True, None


class StrategyEmulator:
    """策略仿真器：统一处理信号的策略决策逻辑

    负责将信号转换为交易决策，包括：
    - 判断信号是否可交易 (gating/confirm检查)
    - 确定交易方向 (signal_type/side_hint/score决策)
    - 策略相关的其他决策逻辑

    这个类确保回测和实盘使用相同的决策逻辑，避免drift。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, gating_mode: str = "strict",
                 legacy_backtest_mode: bool = False, quality_mode: str = "all"):
        """初始化策略仿真器

        Args:
            config: 配置字典，包含min_abs_score_for_side等参数
            gating_mode: gating策略模式，strict/ignore_soft/ignore_all
            legacy_backtest_mode: 遗留回测模式，完全忽略confirm和gating
            quality_mode: 质量档位模式，conservative/balanced/aggressive/all
        """
        self.config = config or {}
        self.gating_mode = gating_mode
        self.legacy_backtest_mode = legacy_backtest_mode
        self.quality_mode = quality_mode

    def decide_side(self, signal: Dict[str, Any]) -> Optional[str]:
        """根据信号决定交易方向

        决策顺序：
        1. signal_type (buy/strong_buy/sell/strong_sell)
        2. side_hint (BUY/LONG/BULLISH/SELL/SHORT/BEARISH)
        3. score 正负号（如果绝对值超过阈值）

        Args:
            signal: 信号字典

        Returns:
            "BUY", "SELL" 或 None
        """
        # 从配置读取阈值，默认0.1
        min_abs_score = (
            self.config
            .get("signal", {})
            .get("min_abs_score_for_side", 0.1)
        )

        # 1. 优先检查signal_type
        st = (signal.get("signal_type") or "").lower()
        if st in ("buy", "strong_buy"):
            return "BUY"
        elif st in ("sell", "strong_sell"):
            return "SELL"

        # 2. 检查side_hint
        side_hint = (signal.get("side_hint") or "").upper()
        if side_hint in ("BUY", "LONG", "BULLISH"):
            return "BUY"
        elif side_hint in ("SELL", "SHORT", "BEARISH"):
            return "SELL"

        # 3. 检查score
        score = signal.get("score")
        if isinstance(score, (int, float)) and abs(score) > min_abs_score:
            return "BUY" if score > 0 else "SELL"

        # 无法判定方向
        return None

    def should_trade(self, signal: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """判断信号是否应该交易

        Args:
            signal: 信号字典

        Returns:
            (should_trade, reason): should_trade为True表示应该交易，reason为不交易的原因
        """
        # TASK-CORE-CONFIRM: Legacy backtest mode - 完全忽略confirm和gating，只基于direction/score
        if self.legacy_backtest_mode:
            # 在legacy模式下，只要有方向信号就交易，完全忽略confirm和gating
            score = signal.get("score", 0.0)
            min_abs_score = (
                self.config
                .get("signal", {})
                .get("min_abs_score_for_side", 0.1)
            )
            if abs(score) >= min_abs_score:
                return True, None
            else:
                return False, "score_too_low_for_legacy_mode"

        # 正常模式：使用统一的is_tradeable函数
        can_trade, reason = is_tradeable(signal, gating_mode=self.gating_mode)
        if not can_trade:
            return False, reason

        # Phase C: 质量档位过滤
        if self.quality_mode != "all":
            quality_tier = signal.get("quality_tier")
            quality_flags = signal.get("quality_flags", [])

            if self.quality_mode == "conservative":
                # 只允许 strong 档位
                if quality_tier != "strong":
                    return False, f"quality_tier_{quality_tier}_not_allowed_in_conservative_mode"
            elif self.quality_mode == "balanced":
                # 允许 strong + normal（但normal不能有low_consistency）
                if quality_tier == "strong":
                    pass  # 允许
                elif quality_tier == "normal":
                    if "low_consistency" in quality_flags:
                        return False, "low_consistency_not_allowed_in_balanced_mode"
                else:  # weak
                    return False, f"quality_tier_{quality_tier}_not_allowed_in_balanced_mode"
            elif self.quality_mode == "aggressive":
                # 所有confirm=True的信号都允许（已在is_tradeable中检查过confirm）
                pass  # 允许所有已通过confirm检查的信号
            else:
                return False, f"unknown_quality_mode_{self.quality_mode}"

        return True, None
