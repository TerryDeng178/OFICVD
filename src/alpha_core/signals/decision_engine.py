# -*- coding: utf-8 -*-
"""Decision Engine for CoreAlgorithm

单点判定逻辑：expiry/cooldown/gating/regime/threshold
参考 TASK-A4 的 5.1 判定顺序
"""

import time
from typing import Dict, Any, Optional, Tuple
from enum import Enum

from .signal_schema import Regime, DecisionCode, SideHint


class DecisionEngine:
    """单点判定引擎
    
    实现 TASK-A4 的判定顺序：
    1. 有效期计算（expiry_ms）
    2. 冷却检查（cooldown_ms）
    3. 门控 Gating（z_ofi/z_cvd 阈值）
    4. Regime 判定（trend/revert/quiet）
    5. 打分与入场阈值（按 regime 差异化）
    """
    
    def __init__(self, core_config: Dict[str, Any]):
        """初始化判定引擎
        
        Args:
            core_config: core.* 配置字典
        """
        self.config = core_config
        
        # 从配置中提取参数（支持环境变量覆盖）
        import os
        expiry_ms_val = os.getenv("CORE_EXPIRY_MS") or core_config.get("expiry_ms") or 60000
        cooldown_ms_val = os.getenv("CORE_COOLDOWN_MS") or core_config.get("cooldown_ms") or 30000
        self.expiry_ms = int(expiry_ms_val)
        self.cooldown_ms = int(cooldown_ms_val)
        self.allow_quiet = core_config.get("allow_quiet", False)
        
        # 门控配置（支持 ENV 覆盖）
        gating_cfg = core_config.get("gating", {})
        self.gating_ofi_z = float(os.getenv("CORE_GATING_Z_OFI", gating_cfg.get("ofi_z", 1.5)))
        self.gating_cvd_z = float(os.getenv("CORE_GATING_Z_CVD", gating_cfg.get("cvd_z", 1.2)))
        self.enable_divergence_alt = gating_cfg.get("enable_divergence_alt", True)
        
        # Regime 配置
        regime_cfg = core_config.get("regime", {})
        self.z_t = regime_cfg.get("z_t", 1.2)
        self.z_r = regime_cfg.get("z_r", 1.0)
        
        # 阈值配置（支持 ENV 覆盖）
        threshold_cfg = core_config.get("threshold", {})
        entry_cfg = threshold_cfg.get("entry", {})
        self.entry_trend = float(os.getenv("CORE_ENTRY_TREND", entry_cfg.get("trend", 1.8)))
        self.entry_revert = float(os.getenv("CORE_ENTRY_REVERT", entry_cfg.get("revert", 2.2)))
        self.entry_quiet = float(os.getenv("CORE_ENTRY_QUIET", entry_cfg.get("quiet", 2.8)))
        
        # 冷却状态跟踪（symbol -> (side, cooldown_end_ts_ms)）
        self._cooldown_state: Dict[str, Dict[str, int]] = {}  # symbol -> {"buy": ts_ms, "sell": ts_ms}
    
    def get_effective_config(self) -> Dict[str, Any]:
        """获取生效后的配置（包含 ENV 覆盖）
        
        TASK-A4 修复4: 返回包含 ENV 覆盖后的配置，用于计算 config_hash
        
        Returns:
            生效后的配置字典
        """
        import os
        effective_config = {
            "expiry_ms": self.expiry_ms,
            "cooldown_ms": self.cooldown_ms,
            "allow_quiet": self.allow_quiet,
            "gating": {
                "ofi_z": self.gating_ofi_z,
                "cvd_z": self.gating_cvd_z,
                "enable_divergence_alt": self.enable_divergence_alt,
            },
            "regime": {
                "z_t": self.z_t,
                "z_r": self.z_r,
            },
            "threshold": {
                "entry": {
                    "trend": self.entry_trend,
                    "revert": self.entry_revert,
                    "quiet": self.entry_quiet,
                },
            },
        }
        return effective_config
    
    def decide(
        self,
        ts_ms: int,
        symbol: str,
        score: float,
        z_ofi: Optional[float],
        z_cvd: Optional[float],
        div_type: Optional[str],
        now_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """执行单点判定
        
        Args:
            ts_ms: 信号时间戳（ms）
            symbol: 交易对
            score: 归一化打分
            z_ofi: OFI z-score
            z_cvd: CVD z-score
            div_type: 背离类型（none/bull/bear）
            now_ms: 当前时间戳（ms），如果为 None 则使用 time.time() * 1000
        
        Returns:
            判定结果字典，包含：
            - regime: Regime 枚举
            - gating: int (0/1)
            - confirm: bool
            - cooldown_ms: int
            - expiry_ms: int
            - decision_code: DecisionCode 枚举
            - decision_reason: str
            - side_hint: SideHint 枚举
        """
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        
        # 1. 有效期计算
        elapsed_ms = now_ms - ts_ms
        if elapsed_ms > self.expiry_ms:
            return {
                "regime": Regime.UNKNOWN,
                "gating": 0,
                "confirm": False,
                "cooldown_ms": 0,
                "expiry_ms": self.expiry_ms,
                "decision_code": DecisionCode.EXPIRE,
                "decision_reason": f"expired({elapsed_ms}ms>{self.expiry_ms}ms)",
                "side_hint": SideHint.FLAT,
            }
        
        # 2. 冷却检查
        side_hint = SideHint.BUY if score > 0 else (SideHint.SELL if score < 0 else SideHint.FLAT)
        cooldown_ms = self._check_cooldown(symbol, side_hint.value, now_ms)
        if cooldown_ms > 0:
            return {
                "regime": Regime.UNKNOWN,
                "gating": 0,
                "confirm": False,
                "cooldown_ms": cooldown_ms,
                "expiry_ms": self.expiry_ms,
                "decision_code": DecisionCode.COOLDOWN,
                "decision_reason": f"cooldown({cooldown_ms}ms remaining)",
                "side_hint": side_hint,
            }
        
        # 3. 门控 Gating
        gating_result = self._check_gating(z_ofi, z_cvd, div_type)
        if not gating_result["passed"]:
            return {
                "regime": Regime.UNKNOWN,
                "gating": 0,
                "confirm": False,
                "cooldown_ms": 0,
                "expiry_ms": self.expiry_ms,
                "decision_code": DecisionCode.FAIL_GATING,
                "decision_reason": gating_result["reason"],
                "side_hint": side_hint,
            }
        
        # 4. Regime 判定
        regime = self._infer_regime(z_ofi, z_cvd)
        
        # 5. Regime 检查（quiet 且不允许）
        if regime == Regime.QUIET and not self.allow_quiet:
            return {
                "regime": regime,
                "gating": 1,
                "confirm": False,
                "cooldown_ms": 0,
                "expiry_ms": self.expiry_ms,
                "decision_code": DecisionCode.BAD_REGIME,
                "decision_reason": "quiet regime not allowed",
                "side_hint": side_hint,
            }
        
        # 6. 打分与入场阈值
        entry_threshold = self._get_entry_threshold(regime)
        if abs(score) < entry_threshold:
            return {
                "regime": regime,
                "gating": 1,
                "confirm": False,
                "cooldown_ms": 0,
                "expiry_ms": self.expiry_ms,
                "decision_code": DecisionCode.LOW_SCORE,
                "decision_reason": f"score({abs(score):.2f})<entry({entry_threshold:.2f})",
                "side_hint": side_hint,
            }
        
        # 7. 通过所有检查，确认信号
        # 更新冷却状态
        self._update_cooldown(symbol, side_hint.value, now_ms)
        
        return {
            "regime": regime,
            "gating": 1,
            "confirm": True,
            "cooldown_ms": 0,
            "expiry_ms": self.expiry_ms,
            "decision_code": DecisionCode.OK,
            "decision_reason": f"score({abs(score):.2f})>={entry_threshold:.2f} & {regime.value}",
            "side_hint": side_hint,
        }
    
    def _check_cooldown(self, symbol: str, side: str, now_ms: int) -> int:
        """检查冷却状态
        
        Returns:
            剩余冷却时长（ms），0 表示不受限
        """
        if symbol not in self._cooldown_state:
            return 0
        
        side_cooldown = self._cooldown_state[symbol].get(side)
        if side_cooldown is None:
            return 0
        
        remaining_ms = side_cooldown - now_ms
        return max(0, remaining_ms)
    
    def _update_cooldown(self, symbol: str, side: str, now_ms: int) -> None:
        """更新冷却状态"""
        if symbol not in self._cooldown_state:
            self._cooldown_state[symbol] = {}
        
        self._cooldown_state[symbol][side] = now_ms + self.cooldown_ms
    
    def _check_gating(self, z_ofi: Optional[float], z_cvd: Optional[float], div_type: Optional[str]) -> Dict[str, Any]:
        """检查门控
        
        Returns:
            {"passed": bool, "reason": str}
        """
        # 强信号路径：|z_ofi|>=ofi_z && |z_cvd|>=cvd_z
        if z_ofi is not None and z_cvd is not None:
            if abs(z_ofi) >= self.gating_ofi_z and abs(z_cvd) >= self.gating_cvd_z:
                return {"passed": True, "reason": "strong signal"}
        
        # 备选路径：背离替代
        if self.enable_divergence_alt and div_type and div_type in ["bull", "bear"]:
            return {"passed": True, "reason": f"divergence({div_type})"}
        
        # 门控失败
        reason_parts = []
        if z_ofi is None or abs(z_ofi) < self.gating_ofi_z:
            reason_parts.append(f"ofi_z({z_ofi or 'None'})<{self.gating_ofi_z}")
        if z_cvd is None or abs(z_cvd) < self.gating_cvd_z:
            reason_parts.append(f"cvd_z({z_cvd or 'None'})<{self.gating_cvd_z}")
        if not (self.enable_divergence_alt and div_type and div_type in ["bull", "bear"]):
            reason_parts.append("no divergence")
        
        return {"passed": False, "reason": " & ".join(reason_parts)}
    
    def _infer_regime(self, z_ofi: Optional[float], z_cvd: Optional[float]) -> Regime:
        """推断 Regime
        
        规则：
        - trend: |z_ofi|>=z_t && 同向 z_cvd
        - revert: |z_ofi|>=z_r && 反向 z_cvd
        - quiet: 其余
        """
        if z_ofi is None or z_cvd is None:
            return Regime.UNKNOWN
        
        abs_ofi = abs(z_ofi)
        ofi_sign = 1 if z_ofi > 0 else -1
        cvd_sign = 1 if z_cvd > 0 else -1
        
        # trend: |z_ofi|>=z_t && 同向 z_cvd
        if abs_ofi >= self.z_t and ofi_sign == cvd_sign:
            return Regime.TREND
        
        # revert: |z_ofi|>=z_r && 反向 z_cvd
        if abs_ofi >= self.z_r and ofi_sign != cvd_sign:
            return Regime.REVERT
        
        # quiet: 其余
        return Regime.QUIET
    
    def _get_entry_threshold(self, regime: Regime) -> float:
        """获取入场阈值（按 regime 差异化）"""
        if regime == Regime.TREND:
            return self.entry_trend
        elif regime == Regime.REVERT:
            return self.entry_revert
        elif regime == Regime.QUIET:
            return self.entry_quiet
        else:
            return self.entry_trend  # 默认使用 trend 阈值

