# -*- coding: utf-8 -*-
"""
Ingestion - 数据采集层模块
"""

from .harvester import SuccessOFICVDHarvester, stable_row_id, _env, ALLOWED_ENV
from .dq_gate import dq_gate_df, save_dq_report, save_bad_data_to_deadletter, PREVIEW_COLUMNS, REQUIRED_FIELDS
from .path_utils import PathBuilder, KIND_RAW, KIND_PREVIEW, norm_symbol

__all__ = [
    'SuccessOFICVDHarvester', 'Harvester', 'stable_row_id', '_env', 'ALLOWED_ENV', 'run_ws_harvest',
    'dq_gate_df', 'save_dq_report', 'save_bad_data_to_deadletter', 'PREVIEW_COLUMNS', 'REQUIRED_FIELDS',
    'PathBuilder', 'KIND_RAW', 'KIND_PREVIEW', 'norm_symbol'
]

# 别名兼容
Harvester = SuccessOFICVDHarvester

# 便捷入口函数
async def run_ws_harvest(config: dict = None, **kwargs):
    """
    运行 WebSocket 采集器（便捷入口）
    
    Args:
        config: 配置字典（来自运行时包）
        **kwargs: 向后兼容参数（symbols, run_hours, output_dir等）
    
    Returns:
        Harvester 实例
    """
    harvester = SuccessOFICVDHarvester(cfg=config, **kwargs)
    await harvester.run()
    return harvester

