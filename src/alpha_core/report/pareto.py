# -*- coding: utf-8 -*-
"""Pareto前沿分析模块"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class ParetoAnalyzer:
    """Pareto前沿分析器
    
    功能：
    - 计算多维Pareto前沿
    - 输出Pareto前沿的trial列表
    - 生成Pareto视图（CSV/JSON）
    """
    
    def __init__(self, objectives: List[str]):
        """
        Args:
            objectives: 目标指标列表，如["win_rate", "net_pnl", "cost_ratio"]
        """
        self.objectives = objectives
    
    def find_pareto_front(
        self,
        trial_results: List[Dict[str, Any]],
        maximize: Dict[str, bool] = None,
    ) -> List[Dict[str, Any]]:
        """找到Pareto前沿
        
        Args:
            trial_results: Trial结果列表
            maximize: 每个目标是否最大化，如{"win_rate": True, "net_pnl": True, "cost_ratio": False}
        
        Returns:
            Pareto前沿的trial列表
        """
        if maximize is None:
            # 默认：win_rate和net_pnl最大化，cost_ratio最小化
            maximize = {
                "win_rate": True,
                "net_pnl": True,
                "cost_ratio": False,
                "max_drawdown": False,
            }
        
        pareto_front = []
        
        for trial in trial_results:
            if not trial.get("success"):
                continue
            
            metrics = trial.get("metrics", {})
            trial_values = {}
            
            # 提取目标值
            for obj in self.objectives:
                if obj == "net_pnl":
                    total_pnl = metrics.get("total_pnl", 0)
                    total_fee = metrics.get("total_fee", 0)
                    total_slippage = metrics.get("total_slippage", 0)
                    trial_values[obj] = total_pnl - total_fee - total_slippage
                elif obj == "cost_ratio":
                    total_pnl = metrics.get("total_pnl", 0)
                    total_fee = metrics.get("total_fee", 0)
                    total_slippage = metrics.get("total_slippage", 0)
                    trial_values[obj] = (total_fee + total_slippage) / abs(total_pnl) if total_pnl != 0 else 0
                elif obj == "cost_ratio_notional":
                    turnover = metrics.get("turnover", 0)
                    total_fee = metrics.get("total_fee", 0)
                    total_slippage = metrics.get("total_slippage", 0)
                    trial_values[obj] = (total_fee + total_slippage) / max(1.0, turnover) if turnover > 0 else 0
                else:
                    trial_values[obj] = metrics.get(obj, 0)
            
            # 检查是否被其他trial支配
            is_dominated = False
            for other_trial in trial_results:
                if not other_trial.get("success") or other_trial == trial:
                    continue
                
                other_metrics = other_trial.get("metrics", {})
                other_values = {}
                
                for obj in self.objectives:
                    if obj == "net_pnl":
                        tp = other_metrics.get("total_pnl", 0)
                        tf = other_metrics.get("total_fee", 0)
                        ts = other_metrics.get("total_slippage", 0)
                        other_values[obj] = tp - tf - ts
                    elif obj == "cost_ratio":
                        tp = other_metrics.get("total_pnl", 0)
                        tf = other_metrics.get("total_fee", 0)
                        ts = other_metrics.get("total_slippage", 0)
                        other_values[obj] = (tf + ts) / abs(tp) if tp != 0 else 0
                    elif obj == "cost_ratio_notional":
                        turnover = other_metrics.get("turnover", 0)
                        tf = other_metrics.get("total_fee", 0)
                        ts = other_metrics.get("total_slippage", 0)
                        other_values[obj] = (tf + ts) / max(1.0, turnover) if turnover > 0 else 0
                    else:
                        other_values[obj] = other_metrics.get(obj, 0)
                
                # 检查是否被支配
                dominates = True
                for obj in self.objectives:
                    if maximize.get(obj, True):
                        # 最大化目标：other必须>=trial
                        if other_values[obj] < trial_values[obj]:
                            dominates = False
                            break
                    else:
                        # 最小化目标：other必须<=trial
                        if other_values[obj] > trial_values[obj]:
                            dominates = False
                            break
                
                if dominates:
                    # 检查是否严格支配（至少一个目标更优）
                    strictly_better = False
                    for obj in self.objectives:
                        if maximize.get(obj, True):
                            if other_values[obj] > trial_values[obj]:
                                strictly_better = True
                                break
                        else:
                            if other_values[obj] < trial_values[obj]:
                                strictly_better = True
                                break
                    
                    if strictly_better:
                        is_dominated = True
                        break
            
            if not is_dominated:
                pareto_front.append(trial)
        
        return pareto_front
    
    def save_pareto_front(
        self,
        pareto_front: List[Dict[str, Any]],
        output_file: Path,
    ):
        """保存Pareto前沿到文件"""
        pareto_data = []
        
        for trial in pareto_front:
            metrics = trial.get("metrics", {})
            total_pnl = metrics.get("total_pnl", 0)
            total_fee = metrics.get("total_fee", 0)
            total_slippage = metrics.get("total_slippage", 0)
            net_pnl = total_pnl - total_fee - total_slippage
            
            pareto_data.append({
                "trial_id": trial.get("trial_id"),
                "score": trial.get("score"),
                "net_pnl": net_pnl,
                "win_rate": metrics.get("win_rate", 0),
                "cost_ratio": (total_fee + total_slippage) / abs(total_pnl) if total_pnl != 0 else 0,
                "cost_ratio_notional": self._calculate_cost_ratio_notional(metrics),
                "max_drawdown": metrics.get("max_drawdown", 0),
                "total_trades": metrics.get("total_trades", 0),
                "params": trial.get("params", {}),
            })
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(pareto_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[ParetoAnalyzer] Pareto前沿已保存: {output_file}")
    
    def _calculate_cost_ratio_notional(self, metrics: Dict[str, Any]) -> float:
        """计算成交额口径成本占比"""
        turnover = metrics.get("turnover", 0)
        total_fee = metrics.get("total_fee", 0)
        total_slippage = metrics.get("total_slippage", 0)
        
        if turnover == 0:
            return 0
        
        return (total_fee + total_slippage) / turnover

