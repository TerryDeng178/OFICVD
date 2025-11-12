# -*- coding: utf-8 -*-
"""
Pytest 配置文件
设置测试环境的路径和配置
"""

import sys
import pytest
from pathlib import Path

# 添加项目根目录和 src 目录到 Python 路径
# 测试文件位于: tests/test_*.py
# 项目结构: tests/ -> project_root/ -> src/ 和 mcp/
_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parent
_SRC_DIR = _PROJECT_ROOT / "src"

# 添加项目根目录（用于导入 mcp 模块）
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 添加 src 目录（用于导入 alpha_core 模块）
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


# 清理 Prometheus metrics（避免测试间重复注册）
@pytest.fixture(autouse=True, scope="function")
def cleanup_prometheus_metrics():
    """每个测试前后清理 Prometheus metrics"""
    # 测试前清理
    try:
        import prometheus_client
        import src.alpha_core.executors.executor_metrics as em
        
        # 重置全局实例
        if em._metrics_instance is not None:
            em._metrics_instance = None
        
        # 清理 REGISTRY 中所有 executor 相关的 metrics
        collectors_to_remove = []
        for collector in list(prometheus_client.REGISTRY._collector_to_names.keys()):
            try:
                collector_name = None
                if hasattr(collector, "_name"):
                    collector_name = collector._name
                elif hasattr(collector, "name"):
                    collector_name = collector.name
                
                if collector_name and "executor" in collector_name.lower():
                    collectors_to_remove.append(collector)
            except Exception:
                pass
        
        for collector in collectors_to_remove:
            try:
                prometheus_client.REGISTRY.unregister(collector)
            except Exception:
                pass
    except Exception:
        pass
    
    yield
    
    # 测试后清理
    try:
        import prometheus_client
        import src.alpha_core.executors.executor_metrics as em
        
        # 重置全局实例
        if em._metrics_instance is not None:
            em._metrics_instance = None
        
        # 清理 REGISTRY 中所有 executor 相关的 metrics
        collectors_to_remove = []
        for collector in list(prometheus_client.REGISTRY._collector_to_names.keys()):
            try:
                collector_name = None
                if hasattr(collector, "_name"):
                    collector_name = collector._name
                elif hasattr(collector, "name"):
                    collector_name = collector.name
                
                if collector_name and "executor" in collector_name.lower():
                    collectors_to_remove.append(collector)
            except Exception:
                pass
        
        for collector in collectors_to_remove:
            try:
                prometheus_client.REGISTRY.unregister(collector)
            except Exception:
                pass
    except Exception:
        pass


# P0: pytest_sessionfinish 钩子，确保测试结束后清理全局注册表
def pytest_sessionfinish(session, exitstatus):
    """测试会话结束时清理 Prometheus metrics"""
    try:
        import prometheus_client
        import src.alpha_core.executors.executor_metrics as em
        
        # 重置全局实例
        if em._metrics_instance is not None:
            em._metrics_instance = None
        
        # 清理所有 executor 相关的 metrics
        collectors_to_remove = []
        for collector in list(prometheus_client.REGISTRY._collector_to_names.keys()):
            try:
                collector_name = None
                if hasattr(collector, "_name"):
                    collector_name = collector._name
                elif hasattr(collector, "name"):
                    collector_name = collector.name
                
                if collector_name and "executor" in collector_name.lower():
                    collectors_to_remove.append(collector)
            except Exception:
                pass
        
        for collector in collectors_to_remove:
            try:
                prometheus_client.REGISTRY.unregister(collector)
            except Exception:
                pass
    except Exception:
        pass
