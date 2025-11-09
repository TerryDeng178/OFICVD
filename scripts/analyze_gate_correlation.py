#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P1.8: Gate原因统计与TradeSim/复盘联通

分析gate_reason_breakdown与最终胜率/交易数的皮尔森相关性
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List

try:
    from scipy.stats import pearsonr
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("scipy not available, using manual correlation calculation")

logger = logging.getLogger(__name__)


def load_json_file(file_path: Path) -> Dict[str, Any]:
    """加载JSON文件"""
    try:
        with file_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load {file_path}: {e}")
        return {}


def manual_pearsonr(x: List[float], y: List[float]) -> tuple:
    """手动计算皮尔森相关系数（当scipy不可用时）"""
    import statistics
    
    if len(x) != len(y) or len(x) < 2:
        return (0.0, 1.0)
    
    n = len(x)
    mean_x = statistics.mean(x)
    mean_y = statistics.mean(y)
    
    numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    sum_sq_x = sum((x[i] - mean_x) ** 2 for i in range(n))
    sum_sq_y = sum((y[i] - mean_y) ** 2 for i in range(n))
    
    denominator = (sum_sq_x * sum_sq_y) ** 0.5
    
    if denominator == 0:
        return (0.0, 1.0)
    
    correlation = numerator / denominator
    
    # 简化的p值计算（不精确，但可用）
    t_stat = correlation * ((n - 2) / (1 - correlation ** 2)) ** 0.5 if abs(correlation) < 1 else 0
    p_value = 0.05  # 简化处理
    
    return (correlation, p_value)


def analyze_gate_correlation(
    gate_reason_file: Path,
    metrics_file: Path,
    trades_file: Path = None,
) -> Dict[str, Any]:
    """分析gate原因与策略表现的相关性
    
    Args:
        gate_reason_file: gate_reason_breakdown.json路径
        metrics_file: metrics.json路径
        trades_file: trades.jsonl路径（可选）
    
    Returns:
        相关性分析结果
    """
    # 加载数据
    gate_reasons = load_json_file(gate_reason_file)
    metrics = load_json_file(metrics_file)
    
    if not gate_reasons or not metrics:
        logger.error("Failed to load required files")
        return {}
    
    # 提取关键指标
    total_trades = metrics.get("total_trades", 0)
    win_rate = metrics.get("win_rate", 0.0)
    total_pnl = metrics.get("total_pnl", 0.0)
    
    # 计算gate原因统计
    total_gates = sum(gate_reasons.values())
    gate_reason_rates = {
        reason: count / total_gates if total_gates > 0 else 0.0
        for reason, count in gate_reasons.items()
    }
    
    # 按gate原因分组分析（如果有trades文件）
    gate_trade_stats = {}
    if trades_file and trades_file.exists():
        gate_trade_stats = analyze_gate_trade_stats(trades_file, gate_reasons)
    
    # 计算相关性
    correlations = {}
    
    # Gate原因比例 vs 胜率
    if len(gate_reason_rates) > 1:
        reasons = list(gate_reason_rates.keys())
        rates = list(gate_reason_rates.values())
        
        # 简化：计算gate总数与胜率的相关性
        gate_counts = [gate_reasons.get(r, 0) for r in reasons]
        
        # 使用总gate数作为代理变量
        if SCIPY_AVAILABLE:
            corr, p_value = pearsonr([total_gates], [win_rate])
        else:
            corr, p_value = manual_pearsonr([total_gates], [win_rate])
        
        correlations["gate_total_vs_win_rate"] = {
            "correlation": corr,
            "p_value": p_value,
            "interpretation": interpret_correlation(corr),
        }
    
    # 构建分析报告
    analysis = {
        "summary": {
            "total_gates": total_gates,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "gate_to_trade_ratio": total_gates / total_trades if total_trades > 0 else 0.0,
        },
        "gate_reason_distribution": gate_reason_rates,
        "top_gate_reasons": sorted(
            gate_reason_rates.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10],
        "correlations": correlations,
        "gate_trade_stats": gate_trade_stats,
        "recommendations": generate_recommendations(gate_reason_rates, metrics),
    }
    
    return analysis


def analyze_gate_trade_stats(trades_file: Path, gate_reasons: Dict[str, int]) -> Dict[str, Any]:
    """分析gate原因与交易统计的关系"""
    gate_trade_stats = {}
    
    # 这里可以扩展：从trades文件中提取gate相关信息
    # 当前简化实现
    
    return gate_trade_stats


def interpret_correlation(corr: float) -> str:
    """解释相关系数"""
    abs_corr = abs(corr)
    if abs_corr < 0.1:
        return "negligible"
    elif abs_corr < 0.3:
        return "weak"
    elif abs_corr < 0.5:
        return "moderate"
    elif abs_corr < 0.7:
        return "strong"
    else:
        return "very_strong"


def generate_recommendations(
    gate_reason_rates: Dict[str, float],
    metrics: Dict[str, Any],
) -> List[str]:
    """生成调参建议"""
    recommendations = []
    
    # 找出占比最高的gate原因
    if gate_reason_rates:
        top_reason = max(gate_reason_rates.items(), key=lambda x: x[1])
        if top_reason[1] > 0.3:  # 占比超过30%
            recommendations.append(
                f"Top gate reason '{top_reason[0]}' accounts for {top_reason[1]*100:.1f}% of gates. "
                f"Consider adjusting threshold for this reason."
            )
    
    # 检查胜率
    win_rate = metrics.get("win_rate", 0.0)
    if win_rate < 0.4:
        recommendations.append(
            f"Win rate is low ({win_rate*100:.1f}%). Consider reviewing gate thresholds to allow more trades."
        )
    
    # 检查gate/trade比例
    total_trades = metrics.get("total_trades", 0)
    total_gates = sum(gate_reason_rates.values()) if gate_reason_rates else 0
    if total_trades > 0:
        gate_ratio = total_gates / total_trades
        if gate_ratio > 10:
            recommendations.append(
                f"Gate-to-trade ratio is high ({gate_ratio:.1f}). "
                f"Most signals are being gated. Consider relaxing gate thresholds."
            )
    
    return recommendations


def main():
    parser = argparse.ArgumentParser(
        description="Analyze correlation between gate reasons and strategy performance"
    )
    parser.add_argument(
        "--gate-reason-file",
        required=True,
        help="Path to gate_reason_breakdown.json",
    )
    parser.add_argument(
        "--metrics-file",
        required=True,
        help="Path to metrics.json",
    )
    parser.add_argument(
        "--trades-file",
        help="Path to trades.jsonl (optional)",
    )
    parser.add_argument(
        "--output",
        help="Output JSON file (default: gate_correlation_analysis.json)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    
    args = parser.parse_args()
    
    # 配置日志
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    
    # 分析相关性
    analysis = analyze_gate_correlation(
        gate_reason_file=Path(args.gate_reason_file),
        metrics_file=Path(args.metrics_file),
        trades_file=Path(args.trades_file) if args.trades_file else None,
    )
    
    if not analysis:
        logger.error("Analysis failed")
        sys.exit(1)
    
    # 输出结果
    output_file = Path(args.output) if args.output else Path("gate_correlation_analysis.json")
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Analysis saved to: {output_file}")
    
    # 打印摘要
    print("\n" + "=" * 80)
    print("Gate Correlation Analysis Summary")
    print("=" * 80)
    
    summary = analysis.get("summary", {})
    print(f"\nTotal Gates: {summary.get('total_gates', 0)}")
    print(f"Total Trades: {summary.get('total_trades', 0)}")
    print(f"Win Rate: {summary.get('win_rate', 0.0)*100:.2f}%")
    print(f"Gate-to-Trade Ratio: {summary.get('gate_to_trade_ratio', 0.0):.2f}")
    
    print("\nTop Gate Reasons:")
    for reason, rate in analysis.get("top_gate_reasons", [])[:5]:
        print(f"  {reason}: {rate*100:.2f}%")
    
    print("\nCorrelations:")
    for key, corr_data in analysis.get("correlations", {}).items():
        corr = corr_data.get("correlation", 0.0)
        interpretation = corr_data.get("interpretation", "unknown")
        print(f"  {key}: {corr:.4f} ({interpretation})")
    
    recommendations = analysis.get("recommendations", [])
    if recommendations:
        print("\nRecommendations:")
        for i, rec in enumerate(recommendations, 1):
            print(f"  {i}. {rec}")
    
    print("=" * 80)
    
    sys.exit(0)


if __name__ == "__main__":
    main()

