# -*- coding: utf-8 -*-
"""分析E4/E5/E6实验结果"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Any

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def load_metrics(result_dir: Path) -> Dict[str, Any]:
    """加载metrics.json"""
    metrics_file = result_dir / "metrics.json"
    if not metrics_file.exists():
        return None
    
    with open(metrics_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_symbol_metrics(result_dir: Path) -> Dict[str, Dict[str, Any]]:
    """加载各交易对的metrics"""
    symbol_metrics = {}
    
    # 查找各交易对的metrics文件
    for metrics_file in result_dir.glob("metrics_*.json"):
        symbol = metrics_file.stem.replace("metrics_", "")
        with open(metrics_file, "r", encoding="utf-8") as f:
            symbol_metrics[symbol] = json.load(f)
    
    return symbol_metrics


def calculate_key_metrics(metrics: Dict[str, Any], minutes: int) -> Dict[str, float]:
    """计算关键指标"""
    total_trades = metrics.get("total_trades", 0)
    total_pnl = metrics.get("total_pnl", 0)
    total_fee = metrics.get("total_fee", 0)
    total_slippage = metrics.get("total_slippage", 0)
    net_pnl = total_pnl - total_fee - total_slippage
    
    hours = minutes / 60.0
    trades_per_hour = total_trades / hours if hours > 0 else 0
    avg_hold_sec = metrics.get("avg_hold_sec", 0)
    cost_bps_on_turnover = metrics.get("cost_bps_on_turnover", 0)
    pnl_per_trade = net_pnl / total_trades if total_trades > 0 else 0
    win_rate_trades = metrics.get("win_rate_trades", 0)
    
    return {
        "trades_per_hour": trades_per_hour,
        "avg_hold_sec": avg_hold_sec,
        "cost_bps_on_turnover": cost_bps_on_turnover,
        "pnl_per_trade": pnl_per_trade,
        "win_rate_trades": win_rate_trades,
        "total_trades": total_trades,
        "net_pnl": net_pnl,
        "maker_ratio_actual": metrics.get("maker_ratio_actual", 0.0),
        "taker_ratio_actual": metrics.get("taker_ratio_actual", 0.0),
        "effective_spread_bps_p50": metrics.get("effective_spread_bps_p50", 0.0),
        "effective_spread_bps_p95": metrics.get("effective_spread_bps_p95", 0.0),
    }


def calculate_median(values: List[float]) -> float:
    """计算中位数"""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    mid = len(sorted_vals) // 2
    if len(sorted_vals) % 2 == 0:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
    return sorted_vals[mid]


def calculate_p25(values: List[float]) -> float:
    """计算P25分位值"""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = max(0, len(sorted_vals) // 4 - 1)
    return sorted_vals[idx]


def main():
    """主函数"""
    # D组基线
    D_BASELINE = {
        "trades_per_hour": 71.0,
        "cost_bps_on_turnover": 1.93,
        "pnl_per_trade": -0.64,
        "win_rate_trades": 0.1681,
        "net_pnl": -64.0,
    }
    
    # E4/E5/E6结果目录
    experiments = {
        "E4": {
            "name": "E1入口节流+E2 Maker策略合并",
            "result_dir": project_root / "runtime/optimizer/group_e4_validation/backtest_20251110_224256",
        },
        "E5": {
            "name": "TP/SL+死区回调",
            "result_dir": project_root / "runtime/optimizer/group_e5_validation/backtest_20251110_224622",
        },
        "E6": {
            "name": "极限降频闸",
            "result_dir": project_root / "runtime/optimizer/group_e6_validation/backtest_20251110_225001",
        },
    }
    
    minutes = 60
    
    print("="*80)
    print("E4/E5/E6实验结果统计")
    print("="*80 + "\n")
    
    # 表头
    print(f"{'实验组':<6} {'名称':<30} {'trades/h':<10} {'cost_bps':<10} {'pnl/trade':<12} {'win_rate':<10} {'maker_ratio':<12}")
    print("-" * 80)
    
    # D组基线
    print(f"{'D基线':<6} {'D组组合（多交易对）':<30} "
          f"{D_BASELINE['trades_per_hour']:>9.1f} "
          f"{D_BASELINE['cost_bps_on_turnover']:>9.2f}bps "
          f"${D_BASELINE['pnl_per_trade']:>10.2f} "
          f"{D_BASELINE['win_rate_trades']:>9.2%} "
          f"{'N/A':>11}")
    
    results = {}
    
    # 各组结果
    for exp_key, exp_info in experiments.items():
        result_dir = exp_info["result_dir"]
        
        if not result_dir.exists():
            print(f"{exp_key:<6} {exp_info['name']:<30} {'N/A':<10} {'N/A':<10} {'N/A':<12} {'N/A':<10} {'N/A':<12}")
            continue
        
        metrics = load_metrics(result_dir)
        symbol_metrics = load_symbol_metrics(result_dir)
        
        if not metrics:
            print(f"{exp_key:<6} {exp_info['name']:<30} {'N/A':<10} {'N/A':<10} {'N/A':<12} {'N/A':<10} {'N/A':<12}")
            continue
        
        key_metrics = calculate_key_metrics(metrics, minutes)
        results[exp_key] = {
            "result_dir": result_dir,
            "metrics": key_metrics,
            "full_metrics": metrics,
            "symbol_metrics": symbol_metrics,
        }
        
        print(f"{exp_key:<6} {exp_info['name']:<30} "
              f"{key_metrics['trades_per_hour']:>9.1f} "
              f"{key_metrics['cost_bps_on_turnover']:>9.2f}bps "
              f"${key_metrics['pnl_per_trade']:>10.2f} "
              f"{key_metrics['win_rate_trades']:>9.2%} "
              f"{key_metrics['maker_ratio_actual']:>10.2%}")
    
    # 验收标准检查
    print("\n" + "="*80)
    print("验收标准检查")
    print("="*80 + "\n")
    
    for exp_key, result in results.items():
        metrics = result["metrics"]
        symbol_metrics = result["symbol_metrics"]
        
        print(f"\n{exp_key}组: {experiments[exp_key]['name']}")
        print("-" * 80)
        
        # 计算各交易对的指标
        symbol_trades_per_hour = []
        symbol_cost_bps = []
        symbol_pnl_per_trade = []
        symbol_net_pnl = []
        symbol_win_rate = []
        
        for symbol, sym_metrics in symbol_metrics.items():
            sym_hours = minutes / 60.0
            sym_trades = sym_metrics.get("total_trades", 0)
            sym_trades_per_hour = sym_trades / sym_hours if sym_hours > 0 else 0
            sym_cost_bps = sym_metrics.get("cost_bps_on_turnover", 0)
            sym_net_pnl_val = sym_metrics.get("total_pnl", 0) - sym_metrics.get("total_fee", 0) - sym_metrics.get("total_slippage", 0)
            sym_pnl_per_trade_val = sym_net_pnl_val / sym_trades if sym_trades > 0 else 0
            sym_win_rate = sym_metrics.get("win_rate_trades", 0)
            
            symbol_trades_per_hour.append(sym_trades_per_hour)
            symbol_cost_bps.append(sym_cost_bps)
            symbol_pnl_per_trade.append(sym_pnl_per_trade_val)
            symbol_net_pnl.append(sym_net_pnl_val)
            symbol_win_rate.append(sym_win_rate)
        
        # 如果没有交易对级别的数据，使用总体数据
        if not symbol_trades_per_hour:
            symbol_trades_per_hour = [metrics["trades_per_hour"]]
            symbol_cost_bps = [metrics["cost_bps_on_turnover"]]
            symbol_pnl_per_trade = [metrics["pnl_per_trade"]]
            symbol_net_pnl = [metrics["net_pnl"]]
            symbol_win_rate = [metrics["win_rate_trades"]]
        
        # 根据实验组设置不同的验收标准
        if exp_key == "E4":
            # E4: trades_per_hour ≤ 25 且 cost_bps ≤ 1.85
            trades_per_hour_median = calculate_median(symbol_trades_per_hour)
            cost_bps_median = calculate_median(symbol_cost_bps)
            p25_pnl_per_trade = calculate_p25(symbol_pnl_per_trade)
            
            print(f"  验收标准1: 交易频率 ≤25笔/小时（中位数）")
            status1 = "[OK]" if trades_per_hour_median <= 25.0 else "[FAIL]"
            print(f"    {status1} 值: {trades_per_hour_median:.2f} vs 目标: 25.0")
            print(f"      各交易对: {symbol_trades_per_hour}")
            
            print(f"  验收标准2: 成本bps ≤1.85bps（中位数）")
            status2 = "[OK]" if cost_bps_median <= 1.85 else "[FAIL]"
            print(f"    {status2} 值: {cost_bps_median:.2f} vs 目标: 1.85")
            print(f"      各交易对: {symbol_cost_bps}")
            
            print(f"  验收标准3: Maker比例显著提升")
            maker_ratio = metrics["maker_ratio_actual"]
            status3 = "[OK]" if maker_ratio > 0.0 else "[FAIL]"
            print(f"    {status3} 值: {maker_ratio:.2%}")
            
        elif exp_key == "E5":
            # E5: avg_pnl_per_trade ≥ 0（P25），胜率≥30%
            p25_pnl_per_trade = calculate_p25(symbol_pnl_per_trade)
            median_win_rate = calculate_median(symbol_win_rate)
            
            print(f"  验收标准1: 单笔收益 ≥0（P25分位）")
            status1 = "[OK]" if p25_pnl_per_trade >= 0.0 else "[FAIL]"
            print(f"    {status1} 值: {p25_pnl_per_trade:.4f} vs 目标: 0.0")
            print(f"      各交易对: {symbol_pnl_per_trade}")
            
            print(f"  验收标准2: 胜率 ≥30%")
            status2 = "[OK]" if median_win_rate >= 0.30 else "[FAIL]"
            print(f"    {status2} 值: {median_win_rate:.2%} vs 目标: 30%")
            print(f"      各交易对: {[f'{w:.2%}' for w in symbol_win_rate]}")
            
        elif exp_key == "E6":
            # E6: trades_per_hour ≤ 20（中位数），胜率≥25%
            trades_per_hour_median = calculate_median(symbol_trades_per_hour)
            median_win_rate = calculate_median(symbol_win_rate)
            
            print(f"  验收标准1: 交易频率 ≤20笔/小时（中位数）")
            status1 = "[OK]" if trades_per_hour_median <= 20.0 else "[FAIL]"
            print(f"    {status1} 值: {trades_per_hour_median:.2f} vs 目标: 20.0")
            print(f"      各交易对: {symbol_trades_per_hour}")
            
            print(f"  验收标准2: 胜率 ≥25%")
            status2 = "[OK]" if median_win_rate >= 0.25 else "[FAIL]"
            print(f"    {status2} 值: {median_win_rate:.2%} vs 目标: 25%")
            print(f"      各交易对: {[f'{w:.2%}' for w in symbol_win_rate]}")
        
        # 通用稳健性检查（ETHUSDT）
        ethusdt_net_pnl = 0.0
        if "ETHUSDT" in symbol_metrics:
            eth_metrics = symbol_metrics["ETHUSDT"]
            ethusdt_net_pnl = eth_metrics.get("total_pnl", 0) - eth_metrics.get("total_fee", 0) - eth_metrics.get("total_slippage", 0)
        
        print(f"  验收标准3: ETHUSDT稳健性（ETH净PnL不为显著负值）")
        status3 = "[OK]" if ethusdt_net_pnl >= -10.0 else "[FAIL]"
        print(f"    {status3} 值: ${ethusdt_net_pnl:.2f} vs 目标: ≥-$10.0")
    
    # 成本观测指标分析
    print("\n" + "="*80)
    print("成本观测指标分析")
    print("="*80 + "\n")
    
    for exp_key, result in results.items():
        metrics = result["metrics"]
        print(f"{exp_key}组:")
        print(f"  Maker实际比例: {metrics['maker_ratio_actual']:.2%}")
        print(f"  Taker实际比例: {metrics['taker_ratio_actual']:.2%}")
        print(f"  有效价差P50: {metrics['effective_spread_bps_p50']:.2f}bps")
        print(f"  有效价差P95: {metrics['effective_spread_bps_p95']:.2f}bps")
        print(f"  成本bps: {metrics['cost_bps_on_turnover']:.2f}bps")
        print()
    
    # 保存结果
    output_file = project_root / "runtime/optimizer" / "e456_results_analysis.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    analysis_data = {
        "baseline": D_BASELINE,
        "experiments": {}
    }
    
    for exp_key, result in results.items():
        analysis_data["experiments"][exp_key] = {
            "name": experiments[exp_key]["name"],
            "result_dir": str(result["result_dir"]),
            "metrics": result["metrics"],
        }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(analysis_data, f, indent=2, ensure_ascii=False)
    
    print(f"[OK] 分析结果已保存到: {output_file}")


if __name__ == "__main__":
    main()

