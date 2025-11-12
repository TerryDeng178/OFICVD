# -*- coding: utf-8 -*-
"""策略模式集成模块

IExecutor初始化时读取StrategyModeManager的当前模式与场景参数
统一时区配置，跨午夜窗口遵循上游wrap_midnight语义
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from ..risk.strategy_mode import StrategyModeManager, StrategyMode

logger = logging.getLogger(__name__)


class StrategyModeIntegration:
    """策略模式集成器
    
    从StrategyModeManager读取模式参数，为执行层提供统一的配置接口
    """
    
    def __init__(self, strategy_mode_manager: Optional[StrategyModeManager] = None):
        """初始化策略模式集成器
        
        Args:
            strategy_mode_manager: StrategyModeManager实例（可选）
        """
        self.strategy_mode_manager = strategy_mode_manager
        self._current_mode: Optional[StrategyMode] = None
        self._current_scenario_params: Dict[str, Any] = {}
        self._timezone = timezone.utc  # 默认UTC时区
        
        if self.strategy_mode_manager:
            self._refresh_mode()
            logger.info(f"[StrategyModeIntegration] Initialized with mode={self._current_mode}")
        else:
            logger.info("[StrategyModeIntegration] Initialized without StrategyModeManager")
    
    def _refresh_mode(self) -> None:
        """刷新当前模式和场景参数"""
        if not self.strategy_mode_manager:
            return
        
        try:
            # 获取当前模式
            self._current_mode = self.strategy_mode_manager.get_current_mode()
            
            # 获取场景参数（从current_params或current_params_by_scenario）
            if self._current_mode:
                # 尝试从current_params获取
                if hasattr(self.strategy_mode_manager, 'current_params') and self.strategy_mode_manager.current_params:
                    self._current_scenario_params = self.strategy_mode_manager.current_params.copy()
                else:
                    # 如果没有current_params，尝试从current_params_by_scenario获取第一个场景的参数
                    if hasattr(self.strategy_mode_manager, 'current_params_by_scenario'):
                        scenarios = self.strategy_mode_manager.current_params_by_scenario
                        if scenarios:
                            # 取第一个场景的参数作为默认
                            self._current_scenario_params = list(scenarios.values())[0].copy()
                        else:
                            self._current_scenario_params = {}
                    else:
                        self._current_scenario_params = {}
            else:
                self._current_scenario_params = {}
            
            logger.debug(
                f"[StrategyModeIntegration] Mode refreshed: {self._current_mode}, "
                f"scenario_params={self._current_scenario_params}"
            )
        except Exception as e:
            logger.error(f"[StrategyModeIntegration] Failed to refresh mode: {e}")
    
    def get_current_mode(self) -> Optional[StrategyMode]:
        """获取当前策略模式
        
        Returns:
            当前策略模式（如果可用）
        """
        self._refresh_mode()
        return self._current_mode
    
    def get_scenario_params(self, scenario: Optional[str] = None) -> Dict[str, Any]:
        """获取当前场景参数
        
        Args:
            scenario: 场景标识（如"A_H"），如果为None则返回当前模式的通用参数
            
        Returns:
            场景参数字典（包含Z/TP/SL/cost_bps等）
        """
        self._refresh_mode()
        
        # 如果有StrategyModeManager且指定了scenario，使用get_params_for_scenario
        if self.strategy_mode_manager and scenario:
            try:
                return self.strategy_mode_manager.get_params_for_scenario(scenario)
            except Exception as e:
                logger.warning(f"[StrategyModeIntegration] Failed to get params for scenario {scenario}: {e}")
        
        # 否则返回缓存的通用参数
        return self._current_scenario_params.copy()
    
    def get_cost_bps(self) -> float:
        """获取当前成本（基点）
        
        Returns:
            成本（基点）
        """
        params = self.get_scenario_params()
        return params.get("cost_bps", 1.93)  # 默认成本
    
    def get_take_profit_bps(self) -> Optional[float]:
        """获取止盈（基点）
        
        Returns:
            止盈（基点），如果未设置则返回None
        """
        params = self.get_scenario_params()
        return params.get("take_profit_bps")
    
    def get_stop_loss_bps(self) -> Optional[float]:
        """获取止损（基点）
        
        Returns:
            止损（基点），如果未设置则返回None
        """
        params = self.get_scenario_params()
        return params.get("stop_loss_bps")
    
    def get_z_threshold(self) -> Optional[float]:
        """获取Z阈值
        
        Returns:
            Z阈值，如果未设置则返回None
        """
        params = self.get_scenario_params()
        return params.get("z_threshold")
    
    def get_rate_limit(self) -> Optional[float]:
        """获取速率限制（每秒请求数）
        
        Returns:
            速率限制，如果未设置则返回None
        """
        params = self.get_scenario_params()
        return params.get("rate_limit")
    
    def get_market_activity(self) -> Optional[str]:
        """获取市场活跃度
        
        Returns:
            市场活跃度（active/quiet），如果未设置则返回None
        """
        mode = self.get_current_mode()
        if mode:
            return mode.value  # StrategyMode是Enum，使用value获取字符串值
        return None
    
    def set_timezone(self, tz: timezone) -> None:
        """设置时区
        
        Args:
            tz: 时区对象
        """
        self._timezone = tz
        logger.info(f"[StrategyModeIntegration] Timezone set to {tz}")
    
    def get_timezone(self) -> timezone:
        """获取时区
        
        Returns:
            时区对象
        """
        return self._timezone
    
    def wrap_midnight(self, ts_ms: int) -> int:
        """跨午夜窗口处理（遵循上游wrap_midnight语义）
        
        Args:
            ts_ms: 时间戳（毫秒）
            
        Returns:
            调整后的时间戳（毫秒）
        """
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=self._timezone)
        
        # 如果时间在午夜附近（例如00:00-08:00），可能需要特殊处理
        # 这里简化处理，实际应根据上游wrap_midnight逻辑实现
        hour = dt.hour
        
        # 示例：如果时间在00:00-08:00，可能需要调整
        # 实际实现应根据上游逻辑
        if hour < 8:
            # 可以调整到前一天的某个时间点，或保持原样
            # 这里简化处理，保持原样
            pass
        
        return ts_ms
    
    def is_mode_active(self) -> bool:
        """判断当前模式是否为活跃模式
        
        Returns:
            是否为活跃模式
        """
        mode = self.get_current_mode()
        if mode:
            return mode == StrategyMode.ACTIVE
        return False
    
    def get_mode_switch_events(self) -> list:
        """获取模式切换事件（审计日志）
        
        Returns:
            模式切换事件列表
        """
        # 这里应该从StrategyModeManager获取切换事件
        # 简化实现，返回空列表
        if self.strategy_mode_manager:
            # 实际应该从StrategyModeManager获取事件历史
            return []
        return []


class ExecutorConfigProvider:
    """执行器配置提供器
    
    基于策略模式提供执行器配置
    """
    
    def __init__(self, strategy_mode_integration: StrategyModeIntegration):
        """初始化执行器配置提供器
        
        Args:
            strategy_mode_integration: 策略模式集成器
        """
        self.strategy_mode_integration = strategy_mode_integration
    
    def get_execution_config(self) -> Dict[str, Any]:
        """获取执行配置
        
        Returns:
            执行配置字典
        """
        config = {}
        
        # 从策略模式获取参数
        cost_bps = self.strategy_mode_integration.get_cost_bps()
        rate_limit = self.strategy_mode_integration.get_rate_limit()
        market_activity = self.strategy_mode_integration.get_market_activity()
        
        config["cost_bps"] = cost_bps
        if rate_limit:
            config["rate_limit"] = rate_limit
        
        # 根据市场活跃度调整配置
        if market_activity == "active":
            config["max_parallel_orders"] = 4  # 活跃市场允许更多并行订单
            config["order_size_usd"] = 100
        elif market_activity == "quiet":
            config["max_parallel_orders"] = 2  # 安静市场减少并行订单
            config["order_size_usd"] = 50
        
        return config
    
    def get_risk_config(self) -> Dict[str, Any]:
        """获取风控配置
        
        Returns:
            风控配置字典
        """
        config = {}
        
        # 从策略模式获取止盈止损
        take_profit_bps = self.strategy_mode_integration.get_take_profit_bps()
        stop_loss_bps = self.strategy_mode_integration.get_stop_loss_bps()
        
        if take_profit_bps:
            config["take_profit_bps"] = take_profit_bps
        if stop_loss_bps:
            config["stop_loss_bps"] = stop_loss_bps
        
        return config

