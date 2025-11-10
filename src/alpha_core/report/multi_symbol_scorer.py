# -*- coding: utf-8 -*-
"""多品种公平权重评分模块"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MultiSymbolScorer:
    """多品种公平权重评分器
    
    关键护栏：多品种公平权重
    - 对每个symbol先算各自指标
    - 再做等权聚合
    - 避免单一高波动品种"带飞"
    """
    
    def __init__(self, symbols: List[str]):
        """
        Args:
            symbols: 交易对列表
        """
        self.symbols = symbols
    
    def calculate_equal_weight_score(
        self,
        trial_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """计算等权多品种评分
        
        Args:
            trial_result: Trial结果（包含metrics和可能的by_symbol数据）
        
        Returns:
            包含等权评分和per-symbol指标的字典
        """
        metrics = trial_result.get("metrics", {})
        
        # 尝试从metrics中获取by_symbol数据
        by_symbol = metrics.get("by_symbol", {})
        
        # 如果没有by_symbol，尝试从报表文件读取
        if not by_symbol:
            output_dir = trial_result.get("output_dir")
            if output_dir:
                metrics_file = Path(output_dir) / "metrics.json"
                if metrics_file.exists():
                    try:
                        with open(metrics_file, "r", encoding="utf-8") as f:
                            metrics_data = json.load(f)
                        by_symbol = metrics_data.get("by_symbol", {})
                    except Exception as e:
                        logger.debug(f"读取metrics.json失败: {e}")
        
        # 如果没有by_symbol数据，回退到整体指标
        if not by_symbol:
            logger.warning("未找到by_symbol数据，使用整体指标")
            return {
                "equal_weight_score": self._calculate_overall_score(metrics),
                "per_symbol_metrics": {},
                "symbol_count": 0,
            }
        
        # 计算每个symbol的指标
        per_symbol_metrics = {}
        symbol_scores = []
        
        for symbol in self.symbols:
            if symbol not in by_symbol:
                continue
            
            symbol_stats = by_symbol[symbol]
            symbol_score = self._calculate_symbol_score(symbol_stats)
            
            per_symbol_metrics[symbol] = {
                "net_pnl": symbol_stats.get("pnl_net", 0),
                "win_rate": symbol_stats.get("win_rate", 0),
                "cost_ratio": self._calculate_symbol_cost_ratio(symbol_stats),
                "total_trades": symbol_stats.get("count", 0),
                "score": symbol_score,
            }
            
            symbol_scores.append(symbol_score)
        
        # 等权聚合（平均值）
        if symbol_scores:
            equal_weight_score = sum(symbol_scores) / len(symbol_scores)
        else:
            equal_weight_score = self._calculate_overall_score(metrics)
        
        return {
            "equal_weight_score": equal_weight_score,
            "per_symbol_metrics": per_symbol_metrics,
            "symbol_count": len(symbol_scores),
        }
    
    def _calculate_symbol_score(self, symbol_stats: Dict[str, Any]) -> float:
        """计算单个symbol的评分"""
        net_pnl = symbol_stats.get("pnl_net", 0)
        win_rate = symbol_stats.get("win_rate", 0)
        cost_ratio = self._calculate_symbol_cost_ratio(symbol_stats)
        total_trades = symbol_stats.get("count", 0)
        
        # 简化评分：net_pnl + win_rate权重 - cost_ratio权重
        score = net_pnl + win_rate * 100 - cost_ratio * 50
        
        # 惩罚低样本
        if total_trades < 10:
            score -= 50
        elif total_trades < 20:
            score -= 25
        
        return score
    
    def _calculate_symbol_cost_ratio(self, symbol_stats: Dict[str, Any]) -> float:
        """计算单个symbol的成本占比"""
        pnl_gross = symbol_stats.get("pnl_gross", 0)
        fee = symbol_stats.get("fee", 0)
        slippage = symbol_stats.get("slippage", 0)
        
        if pnl_gross == 0:
            return 0
        
        return (fee + slippage) / abs(pnl_gross)
    
    def _calculate_overall_score(self, metrics: Dict[str, Any]) -> float:
        """计算整体评分（回退方法）"""
        total_pnl = metrics.get("total_pnl", 0)
        total_fee = metrics.get("total_fee", 0)
        total_slippage = metrics.get("total_slippage", 0)
        net_pnl = total_pnl - total_fee - total_slippage
        win_rate = metrics.get("win_rate", 0)
        
        total_pnl_abs = abs(total_pnl) if total_pnl != 0 else 1
        cost_ratio = (total_fee + total_slippage) / total_pnl_abs
        
        score = net_pnl + win_rate * 100 - cost_ratio * 50
        
        total_trades = metrics.get("total_trades", 0)
        if total_trades < 10:
            score -= 50
        elif total_trades < 20:
            score -= 25
        
        return score

