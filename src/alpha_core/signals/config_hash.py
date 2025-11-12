# -*- coding: utf-8 -*-
"""Config Hash Calculator

计算 core.* 参数哈希，用于可回放审计
"""

import hashlib
import json
from typing import Dict, Any


def calculate_config_hash(core_config: Dict[str, Any]) -> str:
    """计算 core.* 参数哈希（稳定序列化 + SHA1）
    
    Args:
        core_config: core.* 配置字典
        
    Returns:
        SHA1 哈希值（16 进制字符串，前 8 位）
    """
    # 稳定序列化：排序键，去除空格
    serialized = json.dumps(core_config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    
    # SHA1 哈希
    hash_obj = hashlib.sha1(serialized.encode("utf-8"))
    hash_hex = hash_obj.hexdigest()
    
    # TASK-A4 修复4: 返回前 12 位（降低碰撞概率，尤其多 run/多环境）
    return hash_hex[:12]


def extract_core_config(full_config: Dict[str, Any]) -> Dict[str, Any]:
    """从完整配置中提取 core.* 部分
    
    Args:
        full_config: 完整配置字典
        
    Returns:
        core.* 配置字典
    """
    core_config = full_config.get("core", {})
    
    # 如果没有 core 键，尝试从顶层提取相关字段
    if not core_config:
        core_config = {
            "expiry_ms": full_config.get("expiry_ms"),
            "cooldown_ms": full_config.get("cooldown_ms"),
            "allow_quiet": full_config.get("allow_quiet"),
            "gating": full_config.get("gating", {}),
            "threshold": full_config.get("threshold", {}),
            "regime": full_config.get("regime", {}),
        }
    
    return core_config

