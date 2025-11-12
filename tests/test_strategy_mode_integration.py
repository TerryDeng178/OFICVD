# -*- coding: utf-8 -*-
"""测试策略模式集成模块

验证从StrategyModeManager读取模式参数、统一时区配置
"""
import pytest
from unittest.mock import Mock, MagicMock
from datetime import timezone, timedelta

from src.alpha_core.executors.strategy_mode_integration import (
    StrategyModeIntegration,
    ExecutorConfigProvider,
)
from src.alpha_core.risk.strategy_mode import StrategyModeManager, StrategyMode


class TestStrategyModeIntegration:
    """测试StrategyModeIntegration"""
    
    def test_init_without_manager(self):
        """测试无StrategyModeManager初始化"""
        integration = StrategyModeIntegration()
        
        assert integration.strategy_mode_manager is None
        assert integration.get_current_mode() is None
        assert integration.get_scenario_params() == {}
    
    def test_init_with_manager(self):
        """测试有StrategyModeManager初始化"""
        mock_manager = Mock(spec=StrategyModeManager)
        mock_mode = StrategyMode.ACTIVE
        mock_manager.get_current_mode.return_value = mock_mode
        mock_manager.current_params = {"cost_bps": 2.0}
        
        integration = StrategyModeIntegration(strategy_mode_manager=mock_manager)
        
        assert integration.strategy_mode_manager == mock_manager
        assert integration.get_current_mode() == mock_mode
    
    def test_get_scenario_params(self):
        """测试获取场景参数"""
        mock_manager = Mock(spec=StrategyModeManager)
        mock_manager.get_current_mode.return_value = StrategyMode.ACTIVE
        mock_manager.current_params = {
            "cost_bps": 2.0,
            "take_profit_bps": 50.0,
            "stop_loss_bps": 30.0,
        }
        
        integration = StrategyModeIntegration(strategy_mode_manager=mock_manager)
        
        params = integration.get_scenario_params()
        assert params["cost_bps"] == 2.0
        assert params["take_profit_bps"] == 50.0
        assert params["stop_loss_bps"] == 30.0
    
    def test_get_cost_bps(self):
        """测试获取成本"""
        mock_manager = Mock(spec=StrategyModeManager)
        mock_manager.get_current_mode.return_value = StrategyMode.ACTIVE
        mock_manager.current_params = {"cost_bps": 2.5}
        
        integration = StrategyModeIntegration(strategy_mode_manager=mock_manager)
        
        assert integration.get_cost_bps() == 2.5
    
    def test_get_cost_bps_default(self):
        """测试获取成本（默认值）"""
        integration = StrategyModeIntegration()
        
        assert integration.get_cost_bps() == 1.93  # 默认值
    
    def test_get_take_profit_bps(self):
        """测试获取止盈"""
        mock_manager = Mock(spec=StrategyModeManager)
        mock_manager.get_current_mode.return_value = StrategyMode.ACTIVE
        mock_manager.current_params = {"take_profit_bps": 50.0}
        
        integration = StrategyModeIntegration(strategy_mode_manager=mock_manager)
        
        assert integration.get_take_profit_bps() == 50.0
    
    def test_get_stop_loss_bps(self):
        """测试获取止损"""
        mock_manager = Mock(spec=StrategyModeManager)
        mock_manager.get_current_mode.return_value = StrategyMode.ACTIVE
        mock_manager.current_params = {"stop_loss_bps": 30.0}
        
        integration = StrategyModeIntegration(strategy_mode_manager=mock_manager)
        
        assert integration.get_stop_loss_bps() == 30.0
    
    def test_get_market_activity(self):
        """测试获取市场活跃度"""
        mock_manager = Mock(spec=StrategyModeManager)
        mock_mode = StrategyMode.ACTIVE
        mock_manager.get_current_mode.return_value = mock_mode
        mock_manager.current_params = {}
        
        integration = StrategyModeIntegration(strategy_mode_manager=mock_manager)
        
        assert integration.get_market_activity() == "active"
    
    def test_set_timezone(self):
        """测试设置时区"""
        integration = StrategyModeIntegration()
        
        tz = timezone(timedelta(hours=8))  # UTC+8
        integration.set_timezone(tz)
        
        assert integration.get_timezone() == tz
    
    def test_wrap_midnight(self):
        """测试跨午夜窗口处理"""
        integration = StrategyModeIntegration()
        
        # 测试时间戳（假设是UTC时间）
        ts_ms = 1609459200000  # 2021-01-01 00:00:00 UTC
        
        # wrap_midnight应该返回相同或调整后的时间戳
        result = integration.wrap_midnight(ts_ms)
        
        assert isinstance(result, int)
        assert result > 0
    
    def test_is_mode_active(self):
        """测试判断是否为活跃模式"""
        mock_manager = Mock(spec=StrategyModeManager)
        mock_mode = StrategyMode.ACTIVE
        mock_manager.get_current_mode.return_value = mock_mode
        mock_manager.current_params = {}
        
        integration = StrategyModeIntegration(strategy_mode_manager=mock_manager)
        
        assert integration.is_mode_active() is True
        
        # 测试非活跃模式
        mock_mode_quiet = StrategyMode.QUIET
        mock_manager.get_current_mode.return_value = mock_mode_quiet
        
        assert integration.is_mode_active() is False


class TestExecutorConfigProvider:
    """测试ExecutorConfigProvider"""
    
    def test_get_execution_config(self):
        """测试获取执行配置"""
        mock_manager = Mock(spec=StrategyModeManager)
        mock_mode = StrategyMode.ACTIVE
        mock_manager.get_current_mode.return_value = mock_mode
        mock_manager.current_params = {
            "cost_bps": 2.0,
            "rate_limit": 10.0,
        }
        
        integration = StrategyModeIntegration(strategy_mode_manager=mock_manager)
        provider = ExecutorConfigProvider(integration)
        
        config = provider.get_execution_config()
        
        assert config["cost_bps"] == 2.0
        assert config["rate_limit"] == 10.0
        assert config["max_parallel_orders"] == 4  # 活跃市场
        assert config["order_size_usd"] == 100
    
    def test_get_execution_config_quiet_market(self):
        """测试安静市场的执行配置"""
        mock_manager = Mock(spec=StrategyModeManager)
        mock_mode = StrategyMode.QUIET
        mock_manager.get_current_mode.return_value = mock_mode
        mock_manager.current_params = {"cost_bps": 1.5}
        
        integration = StrategyModeIntegration(strategy_mode_manager=mock_manager)
        provider = ExecutorConfigProvider(integration)
        
        config = provider.get_execution_config()
        
        assert config["cost_bps"] == 1.5
        assert config["max_parallel_orders"] == 2  # 安静市场
        assert config["order_size_usd"] == 50
    
    def test_get_risk_config(self):
        """测试获取风控配置"""
        mock_manager = Mock(spec=StrategyModeManager)
        mock_mode = StrategyMode.ACTIVE
        mock_manager.get_current_mode.return_value = mock_mode
        mock_manager.current_params = {
            "take_profit_bps": 50.0,
            "stop_loss_bps": 30.0,
        }
        
        integration = StrategyModeIntegration(strategy_mode_manager=mock_manager)
        provider = ExecutorConfigProvider(integration)
        
        config = provider.get_risk_config()
        
        assert config["take_profit_bps"] == 50.0
        assert config["stop_loss_bps"] == 30.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

