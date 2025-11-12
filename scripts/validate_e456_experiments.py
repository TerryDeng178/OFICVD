# -*- coding: utf-8 -*-
"""验收E4/E5/E6实验（四条验收标准）"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def load_comparison_results() -> Dict[str, Any]:
    """加载E组实验对比结果"""
    comparison_file = project_root / "runtime" / "optimizer" / "e_experiments_comparison.json"
    
    if not comparison_file.exists():
        print(f"[ERROR] 未找到对比结果文件: {comparison_file}")
        print("请先运行: python scripts/run_e_experiments.py --groups E4,E5,E6")
        return None
    
    with open(comparison_file, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_p25(values: List[float]) -> float:
    """计算P25分位值"""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = max(0, len(sorted_vals) // 4 - 1)
    return sorted_vals[idx]


def calculate_median(values: List[float]) -> float:
    """计算中位数"""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    mid = len(sorted_vals) // 2
    if len(sorted_vals) % 2 == 0:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
    return sorted_vals[mid]


def validate_experiment(exp_key: str, exp_data: Dict[str, Any], minutes: int) -> Tuple[bool, Dict[str, Any]]:
    """验收单个实验"""
    metrics = exp_data["metrics"]
    symbol_metrics = exp_data.get("symbol_metrics", {})
    
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
        symbol_win_rate = [metrics.get("win_rate_trades", 0)]
    
    # 根据实验组设置不同的验收标准
    if exp_key == "E4":
        # E4: trades_per_hour ≤ 25 且 cost_bps ≤ 1.85
        trades_per_hour_median = calculate_median(symbol_trades_per_hour)
        cost_bps_median = calculate_median(symbol_cost_bps)
        p25_pnl_per_trade = calculate_p25(symbol_pnl_per_trade)
        
        criteria = {
            "trades_per_hour": {
                "target": 25.0,
                "op": "<=",
                "desc": "交易频率 ≤25笔/小时（中位数）",
                "value": trades_per_hour_median,
            },
            "cost_bps": {
                "target": 1.85,
                "op": "<=",
                "desc": "成本bps ≤1.85bps（中位数）",
                "value": cost_bps_median,
            },
            "maker_ratio": {
                "target": 0.0,
                "op": ">",
                "desc": "Maker比例显著提升（maker_ratio_actual > 0）",
                "value": metrics.get("maker_ratio_actual", 0.0),
            },
        }
    elif exp_key == "E5":
        # E5: avg_pnl_per_trade ≥ 0（P25），胜率≥30%
        p25_pnl_per_trade = calculate_p25(symbol_pnl_per_trade)
        median_win_rate = calculate_median(symbol_win_rate)
        
        criteria = {
            "pnl_per_trade": {
                "target": 0.0,
                "op": ">=",
                "desc": "单笔收益 ≥0（P25分位）",
                "value": p25_pnl_per_trade,
            },
            "win_rate": {
                "target": 0.30,
                "op": ">=",
                "desc": "胜率 ≥30%",
                "value": median_win_rate,
            },
        }
    elif exp_key == "E6":
        # E6: trades_per_hour ≤ 20（中位数），胜率≥25%
        trades_per_hour_median = calculate_median(symbol_trades_per_hour)
        median_win_rate = calculate_median(symbol_win_rate)
        
        criteria = {
            "trades_per_hour": {
                "target": 20.0,
                "op": "<=",
                "desc": "交易频率 ≤20笔/小时（中位数）",
                "value": trades_per_hour_median,
            },
            "win_rate": {
                "target": 0.25,
                "op": ">=",
                "desc": "胜率 ≥25%",
                "value": median_win_rate,
            },
        }
    else:
        criteria = {}
    
    # 检查每个标准
    all_passed = True
    results = {}
    
    for criterion_key, criterion in criteria.items():
        value = criterion["value"]
        target = criterion["target"]
        op = criterion["op"]
        
        if op == "<=":
            passed = value <= target
        elif op == ">=":
            passed = value >= target
        elif op == ">":
            passed = value > target
        else:
            passed = False
        
        if not passed:
            all_passed = False
        
        results[criterion_key] = {
            "passed": passed,
            "value": value,
            "target": target,
            "description": criterion["desc"],
        }
    
    # 通用稳健性检查（ETHUSDT）
    ethusdt_net_pnl = 0.0
    if "ETHUSDT" in symbol_metrics:
        eth_metrics = symbol_metrics["ETHUSDT"]
        ethusdt_net_pnl = eth_metrics.get("total_pnl", 0) - eth_metrics.get("total_fee", 0) - eth_metrics.get("total_slippage", 0)
    
    results["ethusdt_robustness"] = {
        "passed": ethusdt_net_pnl >= -10.0,  # ETH净PnL不为显著负值（允许小幅亏损）
        "value": ethusdt_net_pnl,
        "target": -10.0,
        "description": "ETHUSDT稳健性（ETH净PnL不为显著负值）",
    }
    
    if not results["ethusdt_robustness"]["passed"]:
        all_passed = False
    
    return all_passed, results


def main():
    """主函数"""
    comparison_data = load_comparison_results()
    if not comparison_data:
        sys.exit(1)
    
    experiments = comparison_data.get("experiments", {})
    if not experiments:
        print("[ERROR] 对比结果中没有实验数据")
        sys.exit(1)
    
    # 只验收E4/E5/E6
    e456_experiments = {k: v for k, v in experiments.items() if k in ["E4", "E5", "E6"]}
    if not e456_experiments:
        print("[ERROR] 未找到E4/E5/E6实验数据")
        print(f"可用实验: {list(experiments.keys())}")
        sys.exit(1)
    
    minutes = 60  # 默认60分钟
    
    print("="*80)
    print("E4/E5/E6实验验收报告")
    print("="*80 + "\n")
    
    # 验收每个实验
    validation_results = {}
    for exp_key, exp_data in e456_experiments.items():
        print(f"\n实验 {exp_key}: {exp_data['name']}")
        print("-" * 80)
        
        passed, results = validate_experiment(exp_key, exp_data, minutes)
        
        validation_results[exp_key] = {
            "passed": passed,
            "results": results,
        }
        
        # 打印验收结果
        for criterion_key, result in results.items():
            status = "[OK]" if result["passed"] else "[FAIL]"
            print(f"{status} {result['description']}")
            print(f"    值: {result['value']:.4f} vs 目标: {result['target']:.4f}")
        
        print(f"\n总体状态: {'[PASS]' if passed else '[FAIL]'}")
    
    # 汇总
    print("\n" + "="*80)
    print("验收汇总")
    print("="*80 + "\n")
    
    all_experiments_passed = all(v["passed"] for v in validation_results.values())
    
    for exp_key, validation in validation_results.items():
        status = "[PASS]" if validation["passed"] else "[FAIL]"
        exp_name = e456_experiments[exp_key]["name"]
        print(f"{status} {exp_key}: {exp_name}")
    
    print(f"\n总体验收: {'[PASS]' if all_experiments_passed else '[FAIL]'}")
    
    # 保存验收结果
    output_file = project_root / "runtime" / "optimizer" / "e456_experiments_validation.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "validation_time": str(Path(__file__).stat().st_mtime),
            "experiments": validation_results,
        }, f, indent=2, ensure_ascii=False)
    
    print(f"\n[OK] 验收结果已保存到: {output_file}")
    
    # 返回退出码
    sys.exit(0 if all_experiments_passed else 1)


if __name__ == "__main__":
    main()

