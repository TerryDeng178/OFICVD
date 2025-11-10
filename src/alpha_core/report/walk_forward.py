# -*- coding: utf-8 -*-
"""Walk-forward验证模块"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class WalkForwardValidator:
    """Walk-forward验证器
    
    功能：
    - 将数据分为训练集和验证集
    - 在训练集上优化参数
    - 在验证集上评估泛化能力
    - 输出训练/验证指标对比
    """
    
    def __init__(
        self,
        dates: List[str],
        train_ratio: float = 0.5,
        step_size: int = 1,
        scoring_function: Optional[callable] = None,
        scoring_weights: Optional[Dict[str, float]] = None,
    ):
        """
        Args:
            dates: 可用日期列表（按时间顺序）
            train_ratio: 训练集比例（默认0.5，即训练:验证=1:1）
            step_size: 走步大小（每次前进的天数，默认1）
            scoring_function: 评分函数，接受(metrics, net_pnl, scoring_weights)参数
            scoring_weights: 评分权重（如果scoring_function支持）
        """
        self.dates = sorted(dates)
        self.train_ratio = train_ratio
        self.step_size = step_size
        self.scoring_function = scoring_function
        self.scoring_weights = scoring_weights
    
    def generate_folds(self) -> List[Tuple[List[str], List[str]]]:
        """生成walk-forward折叠
        
        Returns:
            [(train_dates, val_dates), ...] 列表
        """
        folds = []
        total_days = len(self.dates)
        train_days = int(total_days * self.train_ratio)
        
        for i in range(0, total_days - train_days + 1, self.step_size):
            train_dates = self.dates[i:i + train_days]
            val_start = i + train_days
            val_end = min(val_start + (total_days - train_days), total_days)
            val_dates = self.dates[val_start:val_end] if val_start < total_days else []
            
            if train_dates and val_dates:
                folds.append((train_dates, val_dates))
        
        return folds
    
    def evaluate_trial(
        self,
        trial_result: Dict[str, Any],
        train_dates: List[str],
        val_dates: List[str],
    ) -> Dict[str, Any]:
        """评估单个trial的训练/验证表现
        
        Args:
            trial_result: Trial结果（包含train和val的metrics，或直接包含train_score/val_score）
            train_dates: 训练日期列表
            val_dates: 验证日期列表
        
        Returns:
            包含train/val指标和generalization_gap的字典
        """
        # 如果trial_result已经包含train_score和val_score（由optimizer计算），直接使用
        if "train_score" in trial_result and "val_score" in trial_result:
            train_score = trial_result.get("train_score", 0)
            val_score = trial_result.get("val_score", 0)
            train_metrics = trial_result.get("metrics", {})
            val_metrics = trial_result.get("val_metrics", {})
        else:
            # 否则从metrics计算
            train_metrics = trial_result.get("train_metrics", trial_result.get("metrics", {}))
            val_metrics = trial_result.get("val_metrics", {})
            
            train_net_pnl = train_metrics.get("total_pnl", 0) - train_metrics.get("total_fee", 0) - train_metrics.get("total_slippage", 0)
            val_net_pnl = val_metrics.get("total_pnl", 0) - val_metrics.get("total_fee", 0) - val_metrics.get("total_slippage", 0)
            
            # 使用自定义评分函数或默认评分函数
            if self.scoring_function:
                train_score = self.scoring_function(train_metrics, train_net_pnl, self.scoring_weights)
                val_score = self.scoring_function(val_metrics, val_net_pnl, self.scoring_weights) if val_metrics else 0
            else:
                train_score = self._calculate_score(train_metrics, train_net_pnl)
                val_score = self._calculate_score(val_metrics, val_net_pnl) if val_metrics else 0
        
        train_net_pnl = train_metrics.get("total_pnl", 0) - train_metrics.get("total_fee", 0) - train_metrics.get("total_slippage", 0)
        train_win_rate = train_metrics.get("win_rate", 0)
        train_cost_ratio = self._calculate_cost_ratio(train_metrics)
        
        val_net_pnl = val_metrics.get("total_pnl", 0) - val_metrics.get("total_fee", 0) - val_metrics.get("total_slippage", 0) if val_metrics else 0
        val_win_rate = val_metrics.get("win_rate", 0) if val_metrics else 0
        val_cost_ratio = self._calculate_cost_ratio(val_metrics) if val_metrics else 0
        
        # 计算泛化差距
        generalization_gap = train_score - val_score
        
        return {
            "train_score": train_score,
            "train_net_pnl": train_net_pnl,
            "train_win_rate": train_win_rate,
            "train_cost_ratio": train_cost_ratio,
            "val_score": val_score,
            "val_net_pnl": val_net_pnl,
            "val_win_rate": val_win_rate,
            "val_cost_ratio": val_cost_ratio,
            "generalization_gap": generalization_gap,
        }
    
    def _calculate_score(self, metrics: Dict[str, Any], net_pnl: float) -> float:
        """计算综合评分（简化版，实际应使用optimizer的评分函数）
        
        Args:
            metrics: 指标字典
            net_pnl: 净收益
        """
        win_rate = metrics.get("win_rate", 0)
        cost_ratio = self._calculate_cost_ratio(metrics)
        
        # 简化评分：net_pnl + win_rate - cost_ratio
        return net_pnl + win_rate * 100 - cost_ratio * 100
    
    def _calculate_cost_ratio(self, metrics: Dict[str, Any]) -> float:
        """计算成本占比"""
        total_pnl = metrics.get("total_pnl", 0)
        total_fee = metrics.get("total_fee", 0)
        total_slippage = metrics.get("total_slippage", 0)
        
        if total_pnl == 0:
            return 0
        
        return (total_fee + total_slippage) / abs(total_pnl)

