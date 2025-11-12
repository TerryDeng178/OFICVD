# -*- coding: utf-8 -*-
"""StrategyMode Integration Module

StrategyMode参数注入：将新模式的risk子树（guards/position/stop_rules）热注入到内联风控
"""

import time
import logging
import copy
from typing import Dict, Optional, Tuple
from threading import Lock

from .precheck import RiskManager, _risk_manager
from .metrics import get_metrics

logger = logging.getLogger(__name__)


class StrategyModeRiskInjector:
    """StrategyMode风险参数注入器
    
    线程安全的快照切换（Copy-on-Write），将场景参数（如quiet/active）同源管理，
    避免"策略触发阈值在A、风控阈值在B"的双口径问题。
    """
    
    def __init__(self, base_config: Dict):
        """初始化注入器
        
        Args:
            base_config: 基础配置字典
        """
        self.base_config = base_config
        self._lock = Lock()
        self._current_mode = None
        self._current_config_snapshot = None
    
    def apply_strategy_mode_params(self, mode: str, mode_params: Dict) -> Tuple[bool, float]:
        """应用StrategyMode参数到内联风控
        
        Args:
            mode: 策略模式（active/quiet）
            mode_params: 模式参数（包含risk子树）
            
        Returns:
            (success, duration_seconds)
        """
        start_time = time.perf_counter()
        
        try:
            with self._lock:
                # Copy-on-Write：创建新配置快照
                new_config = copy.deepcopy(self.base_config)
                
                # 提取risk子树
                risk_params = mode_params.get("risk", {})
                if not risk_params:
                    logger.warning(f"[RISK] No risk params found for mode={mode}")
                    return False, time.perf_counter() - start_time
                
                # 合并guards配置
                if "guards" in risk_params:
                    if "risk" not in new_config:
                        new_config["risk"] = {}
                    if "guards" not in new_config["risk"]:
                        new_config["risk"]["guards"] = {}
                    new_config["risk"]["guards"].update(risk_params["guards"])
                    logger.debug(f"[RISK] Updated guards for mode={mode}: {risk_params['guards']}")
                
                # 合并position配置
                if "position" in risk_params:
                    if "risk" not in new_config:
                        new_config["risk"] = {}
                    if "position" not in new_config["risk"]:
                        new_config["risk"]["position"] = {}
                    new_config["risk"]["position"].update(risk_params["position"])
                    logger.debug(f"[RISK] Updated position for mode={mode}: {risk_params['position']}")
                
                # 合并stop_rules配置
                if "stop_rules" in risk_params:
                    if "risk" not in new_config:
                        new_config["risk"] = {}
                    if "stop_rules" not in new_config["risk"]:
                        new_config["risk"]["stop_rules"] = {}
                    new_config["risk"]["stop_rules"].update(risk_params["stop_rules"])
                    logger.debug(f"[RISK] Updated stop_rules for mode={mode}: {risk_params['stop_rules']}")
                
                # 原子切换：重新初始化RiskManager（Copy-on-Write）
                # 直接调用precheck模块的initialize_risk_manager函数来更新全局实例
                from .precheck import initialize_risk_manager as init_risk_manager
                init_risk_manager(new_config)
                
                # 保存快照
                self._current_mode = mode
                self._current_config_snapshot = new_config
                
                duration_seconds = time.perf_counter() - start_time
                
                logger.info(
                    f"[RISK] StrategyMode params applied: mode={mode}, "
                    f"duration={duration_seconds*1000:.2f}ms"
                )
                
                # 记录指标
                metrics = get_metrics()
                # TODO: 添加 strategy_params_update_duration_seconds Histogram
                # metrics.record_params_update_duration(duration_seconds)
                
                return True, duration_seconds
                
        except Exception as e:
            duration_seconds = time.perf_counter() - start_time
            logger.error(
                f"[RISK] Failed to apply StrategyMode params: mode={mode}, "
                f"error={e}, duration={duration_seconds*1000:.2f}ms"
            )
            # TODO: 记录失败指标
            # metrics.record_params_update_failure("risk")
            return False, duration_seconds
    
    def get_current_mode(self) -> Optional[str]:
        """获取当前模式
        
        Returns:
            当前模式（active/quiet）或None
        """
        with self._lock:
            return self._current_mode


# 全局注入器实例
_injector: Optional[StrategyModeRiskInjector] = None


def initialize_strategy_mode_injector(base_config: Dict):
    """初始化全局StrategyMode注入器
    
    Args:
        base_config: 基础配置字典
    """
    global _injector
    _injector = StrategyModeRiskInjector(base_config)


def apply_strategy_mode_params(mode: str, mode_params: Dict) -> Tuple[bool, float]:
    """应用StrategyMode参数到内联风控（全局函数接口）
    
    Args:
        mode: 策略模式（active/quiet）
        mode_params: 模式参数（包含risk子树）
        
    Returns:
        (success, duration_seconds)
    """
    global _injector
    if _injector is None:
        raise RuntimeError("StrategyModeRiskInjector not initialized. Call initialize_strategy_mode_injector() first.")
    
    return _injector.apply_strategy_mode_params(mode, mode_params)

