"""
OFI+CVD融合指标模块

实现订单流不平衡(OFI)和累积成交量差值(CVD)的融合信号生成，
包含时间对齐、降级机制、去噪三件套等核心功能。

Author: V13 OFI+CVD AI Trading System
Date: 2025-10-19
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Union
import math
import time
import logging
from enum import Enum
from pathlib import Path


class SignalType(Enum):
    """信号类型枚举"""
    NEUTRAL = "neutral"
    BUY = "buy"
    STRONG_BUY = "strong_buy"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class OFICVDFusionConfig:
    """OFI+CVD融合配置"""
    # 权重配置
    w_ofi: float = 0.6
    w_cvd: float = 0.4
    
    # 信号阈值 - 包B+配置（激进调整，目标 6-9%）
    fuse_buy: float = 0.95         # 1.0 → 0.95 (包B: 温和降低买入门槛)
    fuse_strong_buy: float = 1.70  # 1.8 → 1.70 (包B: 温和降低强买入门槛)
    fuse_sell: float = -0.95       # -1.0 → -0.95 (包B: 温和降低卖出门槛)
    fuse_strong_sell: float = -1.70 # -1.8 → -1.70 (包B: 温和降低强卖出门槛)
    
    # 一致性阈值 - 包B+配置（更激进降低一致性要求）
    min_consistency: float = 0.12  # 0.15 → 0.12 (包B: 温和降低一致性要求)
    strong_min_consistency: float = 0.45  # 0.5 → 0.45 (包B: 温和降低强一致性要求)
    
    # 数据处理 - 包B配置
    z_clip: float = 4.0            # 5.0 → 4.0 (放宽Z-score裁剪)
    max_lag: float = 0.25         # 0.800 → 0.25 (收紧时间对齐要求)
    
    # 去噪参数 - 包B+配置（继续减少冷却时间）
    hysteresis_exit: float = 0.6  # 0.8 → 0.6 (进一步减小迟滞)
    cooldown_secs: float = 0.3    # 保持 0.3 (propsB+ 冷却时间)
    min_consecutive: int = 1      # 保持1 (最低持续门槛)
    
    # 暖启动 - 包B+配置
    min_warmup_samples: int = 10   # 保持 10 (包B+ 暖启动样本数)
    
    # 高级机制配置（突破冷却限制）
    rearm_on_flip: bool = True  # 方向翻转即重臂
    flip_rearm_margin: float = 0.05  # 重臂余量δ=5%
    
    adaptive_cooldown_enabled: bool = True  # 自适应冷却
    adaptive_cooldown_k: float = 0.6  # 收缩系数
    adaptive_cooldown_min_secs: float = 0.12  # 最小冷却时间
    
    burst_coalesce_ms: float = 120.0  # 微型突发合并窗口（毫秒）


class OFI_CVD_Fusion:
    """
    OFI+CVD融合信号生成器
    
    核心功能:
    1. 权重融合: w_ofi * z_ofi + w_cvd * z_cvd
    2. 时间对齐: 处理OFI/CVD不同步问题
    3. 降级机制: 数据缺失时降级为单因子
    4. 去噪三件套: 迟滞/冷却/最小持续
    5. 暖启动保护: 数据不足时返回neutral
    """
    
    def __init__(self, cfg: OFICVDFusionConfig = None, config_loader=None, verbose: bool = False,
                 runtime_cfg: Optional[Dict[str, Any]] = None):
        """
        初始化融合器
        
        Args:
            cfg: 融合配置，默认使用标准配置
            config_loader: 配置加载器实例（兼容旧接口，库式调用时不应使用）
            verbose: 是否启用详细日志输出
            runtime_cfg: 运行时配置字典，库式调用时使用（优先于config_loader）
        """
        self._config_loader = config_loader  # 保存配置来源，便于可观测
        self._verbose = verbose  # 日志开关
        self._logger = logging.getLogger(__name__)  # 模块级logger
        
        # 优先使用运行时配置字典（库式调用）
        if runtime_cfg is not None:
            fusion_cfg = runtime_cfg.get('fusion', {}) if isinstance(runtime_cfg, dict) else {}
            # 从运行时配置构建OFICVDFusionConfig对象
            weights = fusion_cfg.get('weights', {})
            thresholds = fusion_cfg.get('thresholds', {})
            consistency = fusion_cfg.get('consistency', {})
            data_processing = fusion_cfg.get('data_processing', {})
            denoising = fusion_cfg.get('denoising', {})
            
            default = OFICVDFusionConfig()
            self.cfg = OFICVDFusionConfig(
                w_ofi=weights.get('w_ofi', default.w_ofi),
                w_cvd=weights.get('w_cvd', default.w_cvd),
                fuse_buy=thresholds.get('fuse_buy', default.fuse_buy),
                fuse_strong_buy=thresholds.get('fuse_strong_buy', default.fuse_strong_buy),
                fuse_sell=thresholds.get('fuse_sell', default.fuse_sell),
                fuse_strong_sell=thresholds.get('fuse_strong_sell', default.fuse_strong_sell),
                min_consistency=consistency.get('min_consistency', default.min_consistency),
                strong_min_consistency=consistency.get('strong_min_consistency', default.strong_min_consistency),
                z_clip=data_processing.get('z_clip', default.z_clip) if data_processing else default.z_clip,
                max_lag=data_processing.get('max_lag', default.max_lag) if data_processing else default.max_lag,
                min_warmup_samples=data_processing.get('warmup_samples', default.min_warmup_samples) if data_processing else default.min_warmup_samples,
                hysteresis_exit=denoising.get('hysteresis_exit', default.hysteresis_exit) if denoising else default.hysteresis_exit,
                cooldown_secs=denoising.get('cooldown_secs', default.cooldown_secs) if denoising else default.cooldown_secs,
                min_consecutive=denoising.get('min_duration', default.min_consecutive) if denoising else default.min_consecutive
            )
        elif config_loader:
            # 从统一配置系统加载参数（兼容旧接口）
            self.cfg = self._load_from_config_loader(config_loader)
        else:
            self.cfg = cfg or OFICVDFusionConfig()
        
        # 权重归一化
        total_weight = self.cfg.w_ofi + self.cfg.w_cvd
        if total_weight <= 0:
            raise ValueError("权重和必须大于0")
        self.w_ofi = self.cfg.w_ofi / total_weight
        self.w_cvd = self.cfg.w_cvd / total_weight
        
        # 状态管理
        self._last_signal = SignalType.NEUTRAL
        self._last_emit_ts: Optional[float] = None
        self._streak = 0
        self._prev_raw_signal: Optional[SignalType] = None  # 记录"原始判定"用于连击门槛
        self._warmup_count = 0
        self._is_warmup = True
        # default regime for consistency thresholds
        self._current_regime = 'normal'
        
        # 运行时场景一致性配置缓存
        self._regime_consistency = None
        
        # 高级机制状态（突破冷却限制）
        self._last_signal_direction = 0  # 1=buy, -1=sell, 0=neutral
        self._burst_window_candidates = []  # 突发合并候选池
        self._burst_window_start = None  # 突发窗口开始时间
        
        # 统计信息
        self._stats = {
            'total_updates': 0,
            'downgrades': 0,
            'warmup_returns': 0,
            'invalid_inputs': 0,
            'lag_exceeded': 0,
            'cooldown_blocks': 0,
            'min_duration_blocks': 0,
            'flip_rearm': 0,
            'adaptive_cooldown_used': 0,
            'burst_coalesced': 0
        }
    
    def _load_from_config_loader(self, config_loader) -> OFICVDFusionConfig:
        """
        从统一配置系统加载融合指标参数
        
        Args:
            config_loader: 配置加载器实例
            
        Returns:
            融合指标配置对象
        """
        try:
            # 获取融合指标配置
            fusion_config = config_loader.get('fusion_metrics', {})
            
            # 提取权重配置
            weights = fusion_config.get('weights', {})
            w_ofi = weights.get('w_ofi', 0.6)
            w_cvd = weights.get('w_cvd', 0.4)
            
            # 提取阈值配置
            thresholds = fusion_config.get('thresholds', {})
            fuse_buy = thresholds.get('fuse_buy', 1.5)
            fuse_strong_buy = thresholds.get('fuse_strong_buy', 2.5)
            fuse_sell = thresholds.get('fuse_sell', -1.5)
            fuse_strong_sell = thresholds.get('fuse_strong_sell', -2.5)
            
            # 提取一致性配置（支持分场景）
            consistency = fusion_config.get('consistency', {})
            regime_consistency = consistency.get('regime_consistency', {})
            
            # 获取当前regime（从核心算法传递）
            current_regime = getattr(self, '_current_regime', 'normal')
            regime_config = regime_consistency.get(current_regime, {})
            
            if regime_config:
                # 使用分场景一致性阈值
                min_consistency = regime_config.get('min_consistency', consistency.get('min_consistency', 0.15))
                strong_min_consistency = regime_config.get('strong_min_consistency', consistency.get('strong_min_consistency', 0.4))
            else:
                # 使用基础一致性阈值
                min_consistency = consistency.get('min_consistency', 0.15)
                strong_min_consistency = consistency.get('strong_min_consistency', 0.4)
            
            # 提取数据处理配置
            data_processing = fusion_config.get('data_processing', {})
            z_clip = data_processing.get('z_clip', 5.0)
            max_lag = data_processing.get('max_lag', 0.25)  # 统一为进攻版默认值
            warmup_samples = data_processing.get('warmup_samples', 30)
            
            # 提取去噪配置
            denoising = fusion_config.get('denoising', {})
            hysteresis_exit = denoising.get('hysteresis_exit', 1.2)
            cooldown_secs = denoising.get('cooldown_secs', 1.0)
            min_duration = denoising.get('min_duration', 2)
            
            # 创建配置对象
            return OFICVDFusionConfig(
                w_ofi=w_ofi,
                w_cvd=w_cvd,
                fuse_buy=fuse_buy,
                fuse_strong_buy=fuse_strong_buy,
                fuse_sell=fuse_sell,
                fuse_strong_sell=fuse_strong_sell,
                min_consistency=min_consistency,
                strong_min_consistency=strong_min_consistency,
                z_clip=z_clip,
                max_lag=max_lag,
                hysteresis_exit=hysteresis_exit,
                cooldown_secs=cooldown_secs,
                min_consecutive=min_duration,
                min_warmup_samples=warmup_samples
            )
            
        except Exception as e:
            # 如果配置加载失败，使用默认配置并记录警告
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to load fusion metrics config from config_loader: {e}. Using default config.")
            return OFICVDFusionConfig()
    
    def _consistency(self, z_ofi: float, z_cvd: float) -> float:
        """
        计算信号一致性
        
        Args:
            z_ofi: OFI Z-score
            z_cvd: CVD Z-score
            
        Returns:
            一致性得分 (0-1之间，更高=更一致)
        """
        # 使用极小epsilon避免浮点/裁剪造成的0被误判
        eps = 1e-9
        if abs(z_ofi) < eps or abs(z_cvd) < eps:
            return 0.0
        
        # 方向一致性检查
        if math.copysign(1, z_ofi) != math.copysign(1, z_cvd):
            return 0.0
        
        # 强度一致性 (较小值/较大值)
        abs_ofi, abs_cvd = abs(z_ofi), abs(z_cvd)
        return min(abs_ofi, abs_cvd) / max(abs_ofi, abs_cvd)
    
    def _clip_z_score(self, z: float) -> float:
        """裁剪Z-score到合理范围"""
        return max(-self.cfg.z_clip, min(self.cfg.z_clip, z))
    
    def _check_warmup(self) -> bool:
        """检查是否还在暖启动期"""
        if self._warmup_count < self.cfg.min_warmup_samples:
            self._warmup_count += 1
            return True
        self._is_warmup = False
        return False
    
    def _apply_denoising(self, signal: SignalType, fusion_score: float, 
                        ts: float, consistency: float = 0.0) -> tuple[SignalType, list]:
        """
        应用去噪三件套 + 高级机制（方向翻转重臂、自适应冷却、突发合并）
        
        Args:
            signal: 原始信号
            fusion_score: 融合得分
            ts: 时间戳
            consistency: 一致性得分
            
        Returns:
            (去噪后的信号, 去噪原因列表)
        """
        denoising_reasons = []
        original_signal = signal
        
        # 获取信号方向
        current_direction = 0  # 1=buy, -1=sell, 0=neutral
        if signal in [SignalType.BUY, SignalType.STRONG_BUY]:
            current_direction = 1
        elif signal in [SignalType.SELL, SignalType.STRONG_SELL]:
            current_direction = -1
        
        # 连击计数：基于"原始判定信号"，而非上次已发出的信号
        if original_signal is not SignalType.NEUTRAL:
            if self._prev_raw_signal == original_signal:
                self._streak += 1
            else:
                self._streak = 1
        else:
            self._streak = 0
        self._prev_raw_signal = original_signal
        
        # 1. 冷却时间检查 + 高级机制
        cooldown_passed = True
        effective_cooldown = self.cfg.cooldown_secs
        
        if self._last_emit_ts:
            elapsed = ts - self._last_emit_ts
            
            # 机制1: 自适应冷却 - 根据信号强度动态调整
            if self.cfg.adaptive_cooldown_enabled and elapsed < self.cfg.cooldown_secs:
                # 计算超阈强度
                strength = 0.0
                if abs(fusion_score) >= abs(self.cfg.fuse_buy):
                    strength = min(1.0, (abs(fusion_score) - abs(self.cfg.fuse_buy)) / 
                                  (abs(self.cfg.fuse_strong_buy) - abs(self.cfg.fuse_buy)))
                
                # 有效冷却 = max(最小冷却, 基础冷却 * (1 - k * 强度))
                effective_cooldown = max(
                    self.cfg.adaptive_cooldown_min_secs,
                    self.cfg.cooldown_secs * (1 - self.cfg.adaptive_cooldown_k * strength)
                )
                if effective_cooldown < self.cfg.cooldown_secs:
                    self._stats['adaptive_cooldown_used'] += 1
            
            # 机制2: 方向翻转即重臂 - 方向反转时提前解锁
            rearm = False
            if self.cfg.rearm_on_flip and current_direction != 0:
                if self._last_signal_direction != 0 and current_direction != self._last_signal_direction:
                    # 方向翻转，检查是否超阈足够
                    threshold = abs(self.cfg.fuse_buy) * (1 + self.cfg.flip_rearm_margin)
                    if abs(fusion_score) >= threshold:
                        rearm = True
                        denoising_reasons.append("flip_rearm")
                        self._stats['flip_rearm'] += 1
            
            # 判断是否通过冷却
            if not rearm and elapsed < effective_cooldown:
                cooldown_passed = False
            
            # 冷却检查结果
            if not cooldown_passed and signal != SignalType.NEUTRAL:
                denoising_reasons.append("cooldown")
                self._stats['cooldown_blocks'] += 1
                # 记录到突发合并候选池（如果启用）
                if self.cfg.burst_coalesce_ms > 0:
                    if (self._burst_window_start is None or 
                        (ts - self._burst_window_start) > self.cfg.burst_coalesce_ms / 1000.0):
                        # 新窗口，清空候选池
                        self._burst_window_candidates = []
                        self._burst_window_start = ts
                    
                    # 添加到候选池
                    self._burst_window_candidates.append({
                        'signal': signal,
                        'score': abs(fusion_score),
                        'ts': ts
                    })
                return SignalType.NEUTRAL, denoising_reasons
        
        # 更新方向记录
        if signal != SignalType.NEUTRAL:
            self._last_signal_direction = current_direction
        
        # 2. 一致性加权迟滞处理 - 增强版
        consistency_bonus = max(0.0, consistency - 0.3) * 0.5  # 一致性加分
        adjusted_hysteresis = self.cfg.hysteresis_exit + consistency_bonus
        
        if (self._last_signal == SignalType.STRONG_BUY and 
            signal == SignalType.BUY and 
            fusion_score > adjusted_hysteresis):
            # 从强买入降级到买入时，如果得分仍然很高，保持强买入
            denoising_reasons.append("hysteresis_hold")
            signal = SignalType.STRONG_BUY
        elif (self._last_signal == SignalType.STRONG_SELL and 
              signal == SignalType.SELL and 
              fusion_score < -adjusted_hysteresis):
            # 从强卖出降级到卖出时，如果得分仍然很低，保持强卖出
            denoising_reasons.append("hysteresis_hold")
            signal = SignalType.STRONG_SELL
        elif (self._last_signal in [SignalType.BUY, SignalType.STRONG_BUY] and 
              signal == SignalType.NEUTRAL and 
              fusion_score > adjusted_hysteresis):
            # 从买入信号变为中性时，如果得分仍然较高，保持买入
            denoising_reasons.append("hysteresis_hold")
            signal = self._last_signal
        elif (self._last_signal in [SignalType.SELL, SignalType.STRONG_SELL] and 
              signal == SignalType.NEUTRAL and 
              fusion_score < -adjusted_hysteresis):
            # 从卖出信号变为中性时，如果得分仍然较低，保持卖出
            denoising_reasons.append("hysteresis_hold")
            signal = self._last_signal
        
        # 3. 一致性驱动的信号强度调整
        if consistency > 0.7:  # 高一致性时放宽阈值
            # 允许将 NEUTRAL 升级为 BUY/SELL（接近阈值时）
            if signal == SignalType.NEUTRAL:
                if fusion_score > self.cfg.fuse_buy * 0.8:
                    signal = SignalType.BUY
                    denoising_reasons.append("consistency_boost")
                elif fusion_score < self.cfg.fuse_sell * 0.8:
                    signal = SignalType.SELL
                    denoising_reasons.append("consistency_boost")
        elif consistency < 0.3:  # 低一致性时严格节流
            if signal in [SignalType.BUY, SignalType.STRONG_BUY, SignalType.SELL, SignalType.STRONG_SELL]:
                signal = SignalType.NEUTRAL
                denoising_reasons.append("low_consistency_throttle")
        
        # 4. 最小持续检查：一致性提升（consistency_boost）允许放行首帧
        bypass = ("consistency_boost" in denoising_reasons)
        if signal != SignalType.NEUTRAL and self._streak < self.cfg.min_consecutive and not bypass:
            signal = SignalType.NEUTRAL
            denoising_reasons.append("min_duration")
            self._stats['min_duration_blocks'] += 1
        
        return signal, denoising_reasons
    
    def update(self, z_ofi: float, z_cvd: float, ts: float,
               price: Optional[float] = None, lag_sec: float = 0.0) -> Dict[str, Any]:
        """
        更新融合信号
        
        Args:
            z_ofi: OFI Z-score
            z_cvd: CVD Z-score
            ts: 事件时间戳
            price: 可选价格信息
            lag_sec: OFI/CVD时间差(秒)
            
        Returns:
            融合结果字典
        """
        self._stats['total_updates'] += 1
        reason_codes = []
        
        # 1. 输入验证
        if any(x is None or math.isinf(x) or math.isnan(x) 
               for x in [z_ofi, z_cvd]):
            self._stats['invalid_inputs'] += 1
            return {
                "fusion_score": 0.0,
                "signal": SignalType.NEUTRAL.value,
                "consistency": 0.0,
                "ofi_weight": self.w_ofi,  # 修复：使用实际权重而非0
                "cvd_weight": self.w_cvd,  # 修复：使用实际权重而非0
                "reason_codes": ["invalid_input"],
                "components": {"ofi": 0.0, "cvd": 0.0},
                "warmup": self._is_warmup,  # 修复：使用真实暖启动状态
                "stats": self._stats.copy()  # 修复：添加stats字段
            }
        
        # 2. 暖启动检查
        if self._check_warmup():
            self._stats['warmup_returns'] += 1
            return {
                "fusion_score": 0.0,
                "signal": SignalType.NEUTRAL.value,
                "consistency": 0.0,
                "ofi_weight": self.w_ofi,
                "cvd_weight": self.w_cvd,
                "reason_codes": ["warmup"],
                "components": {"ofi": 0.0, "cvd": 0.0},
                "warmup": True,
                "stats": self._stats.copy()  # 修复：添加stats字段
            }
        
        # 3. 数据裁剪
        z_ofi_clipped = self._clip_z_score(z_ofi)
        z_cvd_clipped = self._clip_z_score(z_cvd)
        
        # 4. 时间对齐检查与单因子降级
        w_ofi, w_cvd = self.w_ofi, self.w_cvd
        degraded = False
        if lag_sec > self.cfg.max_lag:
            self._stats['lag_exceeded'] += 1
            self._stats['downgrades'] += 1  # 添加降级统计
            reason_codes.append("lag_exceeded")
            # 实现单因子降级：保留更"强"的一侧
            if abs(z_ofi_clipped) >= abs(z_cvd_clipped):
                w_ofi, w_cvd = 1.0, 0.0
                reason_codes.append("degraded_ofi_only")
            else:
                w_ofi, w_cvd = 0.0, 1.0
                reason_codes.append("degraded_cvd_only")
            degraded = True
        
        # 5. 融合计算
        raw_fusion = w_ofi * z_ofi_clipped + w_cvd * z_cvd_clipped
        consistency = self._consistency(z_ofi_clipped, z_cvd_clipped)
        if degraded:
            # 单因子时一致性按 1.0 处理，避免"降级=不可信"的误判
            consistency = 1.0
        
        # 融合分数诊断日志（每10秒汇总一次）
        current_time = time.time()
        if not hasattr(self, '_last_fusion_log'):
            self._last_fusion_log = current_time
            self._fusion_samples = []
        
        # 收集样本用于统计
        self._fusion_samples.append({
            'z_ofi': z_ofi_clipped,
            'z_cvd': z_cvd_clipped,
            'w_ofi': w_ofi,
            'w_cvd': w_cvd,
            'raw_fusion': raw_fusion,
            'consistency': consistency,
            'ts': current_time
        })
        
        # 每10秒打印一次融合分数统计（带numpy try/except保护）
        if current_time - self._last_fusion_log >= 10:
            if self._fusion_samples:
                try:
                    import numpy as np
                    raw_fusions = [s['raw_fusion'] for s in self._fusion_samples]
                    consistencies = [s['consistency'] for s in self._fusion_samples]
                    
                    self._logger.info(f"[FUSION_DIAG] n={len(self._fusion_samples)} samples")
                    self._logger.info(f"[FUSION_DIAG] Raw fusion stats: p50={np.percentile(raw_fusions, 50):.3f}, "
                          f"p95={np.percentile(raw_fusions, 95):.3f}, p99={np.percentile(raw_fusions, 99):.3f}, max={np.max(raw_fusions):.3f}")
                    self._logger.info(f"[FUSION_DIAG] Consistency stats: p50={np.percentile(consistencies, 50):.3f}, "
                          f"p95={np.percentile(consistencies, 95):.3f}")
                    self._logger.info(f"[FUSION_DIAG] Sample: z_ofi={z_ofi_clipped:.3f}, z_cvd={z_cvd_clipped:.3f}, "
                          f"w_ofi={w_ofi:.2f}, w_cvd={w_cvd:.2f}, raw_fusion={raw_fusion:.3f}, consistency={consistency:.3f}")
                    
                    # 检查是否需要校准策略A
                    if np.percentile(raw_fusions, 95) < 0.3:
                        self._logger.warning(f"[FUSION_DIAG] Raw fusion p95 < 0.3, may need calibration strategy A")
                except ImportError:
                    self._logger.warning("[FUSION_DIAG] numpy not available, skipping statistics")
            else:
                self._logger.debug("[FUSION_DIAG] No samples collected in 10s window")
            
            self._last_fusion_log = current_time
            self._fusion_samples = []
        
        fusion_score = raw_fusion
        
        # 6. 信号生成
        signal = SignalType.NEUTRAL
        if (fusion_score > self.cfg.fuse_strong_buy and 
            consistency > self.cfg.strong_min_consistency):
            signal = SignalType.STRONG_BUY
        elif (fusion_score > self.cfg.fuse_buy and 
              consistency > self.cfg.min_consistency):
            signal = SignalType.BUY
        elif (fusion_score < self.cfg.fuse_strong_sell and 
              consistency > self.cfg.strong_min_consistency):
            signal = SignalType.STRONG_SELL
        elif (fusion_score < self.cfg.fuse_sell and 
              consistency > self.cfg.min_consistency):
            signal = SignalType.SELL
        
        # 7. 去噪处理 - 传递一致性参数
        signal, denoising_reasons = self._apply_denoising(signal, fusion_score, ts, consistency)
        reason_codes.extend(denoising_reasons)
        
        # 8. 状态更新
        if signal != SignalType.NEUTRAL:
            self._last_emit_ts = ts
        self._last_signal = signal if signal != SignalType.NEUTRAL else self._last_signal
        
        # 添加融合器可观测性护栏（受verbose控制）
        if self._verbose:
            self._logger.debug(f"[FUSION_OBSERVABILITY] Input: z_ofi={z_ofi_clipped:.6f}, z_cvd={z_cvd_clipped:.6f}")
            self._logger.debug(f"[FUSION_OBSERVABILITY] Weights: w_ofi={w_ofi:.3f}, w_cvd={w_cvd:.3f}")
            self._logger.debug(f"[FUSION_OBSERVABILITY] Raw fusion: {raw_fusion:.6f}, consistency={consistency:.3f}")
            self._logger.debug(f"[FUSION_OBSERVABILITY] Regime: {self._current_regime}, thresholds: fuse_buy={self.cfg.fuse_buy}, fuse_sell={self.cfg.fuse_sell}")
            self._logger.debug(f"[FUSION_OBSERVABILITY] Consistency thresholds: min={self.cfg.min_consistency:.3f}, strong={self.cfg.strong_min_consistency:.3f}")
            self._logger.debug(f"[FUSION_OBSERVABILITY] Config source: unified_config={self._config_loader is not None}")
        
        # 当融合分数接近0时，记录详细原因
        if abs(raw_fusion) < 1e-6:
            reason_code = "due_to_warmup" if "warmup" in reason_codes else "zero_inputs" if (abs(z_ofi_clipped) < 1e-6 and abs(z_cvd_clipped) < 1e-6) else "consistency_fail"
            self._logger.debug(f"[FUSION_ZERO] Raw fusion={raw_fusion:.6f}, reason_code={reason_code}, reason_codes={reason_codes}")
        
        self._logger.debug(f"[FUSION_INTERNAL] Signal: {signal.value}, reason_codes: {reason_codes}")
        
        return {
            "fusion_score": fusion_score,
            "signal": signal.value,
            "consistency": consistency,
            "ofi_weight": w_ofi,
            "cvd_weight": w_cvd,
            "reason_codes": reason_codes,
            "components": {
                "ofi": w_ofi * z_ofi_clipped, 
                "cvd": w_cvd * z_cvd_clipped
            },
            "warmup": False,
            "stats": self._stats.copy(),
            "last_signal": self._last_signal.value,  # 上一次发射的非中性信号
            "streak": self._streak  # 当前连击计数
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._stats.copy()
    
    def reset(self):
        """重置状态"""
        self._last_signal = SignalType.NEUTRAL
        self._last_emit_ts = None
        self._streak = 0
        self._prev_raw_signal = None  # 重置原始判定信号
        self._warmup_count = 0
        self._is_warmup = True
        # default regime for consistency thresholds
        self._current_regime = 'normal'
        
        # 高级机制状态重置
        self._last_signal_direction = 0
        self._burst_window_candidates = []
        self._burst_window_start = None
        
        self._stats = {
            'total_updates': 0,
            'downgrades': 0,
            'warmup_returns': 0,
            'invalid_inputs': 0,
            'lag_exceeded': 0,
            'cooldown_blocks': 0,
            'min_duration_blocks': 0,
            'flip_rearm': 0,
            'adaptive_cooldown_used': 0,
            'burst_coalesced': 0
        }
    
    # -------- 运行时更新（移入类内，修正缩进/作用域） --------
    def set_thresholds(self, **kwargs):
        """Update fusion thresholds and consistency safely at runtime.
        Accepts keys: fuse_buy, fuse_strong_buy, fuse_sell, fuse_strong_sell,
        min_consistency, strong_min_consistency, regime_consistency (dict),
        w_ofi, w_cvd.
        """
        updated = {}
        # update weights
        for k in ("w_ofi", "w_cvd"):
            if k in kwargs:
                try:
                    setattr(self.cfg, k, float(kwargs[k]))
                    updated[k] = float(kwargs[k])
                except Exception as e:
                    self._logger.warning(f"Failed to set {k}: {e}")
        # renormalize weights
        try:
            total = self.cfg.w_ofi + self.cfg.w_cvd
            if total > 0:
                self.w_ofi = self.cfg.w_ofi / total
                self.w_cvd = self.cfg.w_cvd / total
        except Exception as e:
            self._logger.warning(f"Weight renormalization failed: {e}")
        # thresholds
        for k in ("fuse_buy", "fuse_strong_buy", "fuse_sell", "fuse_strong_sell",
                  "min_consistency", "strong_min_consistency"):
            if k in kwargs:
                try:
                    setattr(self.cfg, k, float(kwargs[k]))
                    updated[k] = float(kwargs[k])
                except Exception as e:
                    self._logger.warning(f"Failed to set {k}: {e}")
        # regime consistency
        rc = kwargs.get("regime_consistency")
        if isinstance(rc, dict):
            try:
                self._regime_consistency = rc  # store for runtime switching
                updated["regime_consistency"] = True
            except Exception as e:
                self._logger.warning(f"Failed to set regime_consistency: {e}")
        if updated:
            self._logger.info(f"Fusion thresholds updated: {updated}")
        return updated

    def set_regime(self, regime: str):
        """外部可更新当前场景标签（供统一配置使用）"""
        old_regime = self._current_regime
        self._current_regime = regime
        
        # 如果配置了场景一致性阈值，应用当前regime的阈值
        if self._regime_consistency and isinstance(self._regime_consistency, dict):
            regime_config = self._regime_consistency.get(regime, {})
            if regime_config:
                try:
                    # 更新当前regime对应的阈值
                    if 'min_consistency' in regime_config:
                        self.cfg.min_consistency = float(regime_config['min_consistency'])
                        self._logger.debug(f"Updated min_consistency for regime {regime}: {self.cfg.min_consistency}")
                    if 'strong_min_consistency' in regime_config:
                        self.cfg.strong_min_consistency = float(regime_config['strong_min_consistency'])
                        self._logger.debug(f"Updated strong_min_consistency for regime {regime}: {self.cfg.strong_min_consistency}")
                except Exception as e:
                    self._logger.warning(f"Failed to apply regime thresholds for {regime}: {e}")
        
        if old_regime != regime:
            self._logger.info(f"Regime switched from {old_regime} to {regime}")
        
        return self._current_regime


def create_fusion_config(**kwargs) -> OFICVDFusionConfig:
    """
    创建融合配置的便捷函数
    
    Args:
        **kwargs: 配置参数
        
    Returns:
        配置对象
    """
    return OFICVDFusionConfig(**kwargs)


# 默认配置层级

DEFAULT_CONFIG = OFICVDFusionConfig()
