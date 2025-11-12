# -*- coding: utf-8 -*-
"""Risk Guards Module

护栏检查：spread、lag、activity等基础护栏
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GuardChecker:
    """护栏检查器"""
    
    def __init__(self, config: Dict):
        """初始化护栏检查器
        
        Args:
            config: 配置字典，包含guards配置段
        """
        guards_config = config.get("guards", {})
        self.spread_bps_max = guards_config.get("spread_bps_max", 8.0)
        self.lag_sec_cap = guards_config.get("lag_sec_cap", 1.5)
        self.activity_min_tpm = guards_config.get("activity_min_tpm", 10.0)
    
    def check_spread(self, spread_bps: float) -> Tuple[bool, Optional[str]]:
        """检查价差护栏
        
        Args:
            spread_bps: 价差（基点）
            
        Returns:
            (是否通过, 拒绝原因码)
        """
        if spread_bps > self.spread_bps_max:
            return False, "spread_too_wide"
        return True, None
    
    def check_lag(self, event_lag_sec: float) -> Tuple[bool, Optional[str]]:
        """检查延迟护栏
        
        Args:
            event_lag_sec: 事件延迟（秒）
            
        Returns:
            (是否通过, 拒绝原因码)
        """
        if event_lag_sec > self.lag_sec_cap:
            return False, "lag_exceeds_cap"
        return True, None
    
    def check_activity(self, activity_tpm: float) -> Tuple[bool, Optional[str]]:
        """检查市场活跃度护栏
        
        Args:
            activity_tpm: 每分钟交易数
            
        Returns:
            (是否通过, 拒绝原因码)
        """
        if activity_tpm < self.activity_min_tpm:
            return False, "market_inactive"
        return True, None
    
    def check_all(self, guards: Dict[str, float]) -> List[str]:
        """检查所有护栏
        
        Args:
            guards: 护栏字段字典
            
        Returns:
            拒绝原因码列表（空列表表示全部通过）
        """
        reasons = []
        
        spread_bps = guards.get("spread_bps", 0.0)
        passed, reason = self.check_spread(spread_bps)
        if not passed:
            reasons.append(reason)
        
        event_lag_sec = guards.get("event_lag_sec", 0.0)
        passed, reason = self.check_lag(event_lag_sec)
        if not passed:
            reasons.append(reason)
        
        activity_tpm = guards.get("activity_tpm", 0.0)
        passed, reason = self.check_activity(activity_tpm)
        if not passed:
            reasons.append(reason)
        
        return reasons

