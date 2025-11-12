# -*- coding: utf-8 -*-
"""验收E组实验（四个验收标准）"""
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
        print("请先运行: python scripts/run_e_experiments.py")
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


def validate_experiment(exp_key: str, exp_data: Dict[str, Any], minutes: int) -> Tuple[bool, Dict[str, Any]]:
    """验收单个实验"""
    metrics = exp_data["metrics"]
    symbol_metrics = exp_data.get("symbol_metrics", {})
    
    # 计算各交易对的指标
    symbol_trades_per_hour = []
    symbol_cost_bps = []
    symbol_pnl_per_trade = []
    symbol_net_pnl = []
    
    for symbol, sym_metrics in symbol_metrics.items():
        sym_hours = minutes / 60.0
        sym_trades = sym_metrics.get("total_trades", 0)
        sym_trades_per_hour = sym_trades / sym_hours if sym_hours > 0 else 0
        sym_cost_bps = sym_metrics.get("cost_bps_on_turnover", 0)
        sym_net_pnl_val = sym_metrics.get("total_pnl", 0) - sym_metrics.get("total_fee", 0) - sym_metrics.get("total_slippage", 0)
        sym_pnl_per_trade_val = sym_net_pnl_val / sym_trades if sym_trades > 0 else 0
        
        symbol_trades_per_hour.append(sym_trades_per_hour)
        symbol_cost_bps.append(sym_cost_bps)
        symbol_pnl_per_trade.append(sym_pnl_per_trade_val)
        symbol_net_pnl.append(sym_net_pnl_val)
    
    # 如果没有交易对级别的数据，使用总体数据
    if not symbol_trades_per_hour:
        symbol_trades_per_hour = [metrics["trades_per_hour"]]
        symbol_cost_bps = [metrics["cost_bps_on_turnover"]]
        symbol_pnl_per_trade = [metrics["pnl_per_trade"]]
        symbol_net_pnl = [metrics["net_pnl"]]
    
    # 计算P25分位值
    p25_trades_per_hour = calculate_p25(symbol_trades_per_hour)
    p25_cost_bps = calculate_p25(symbol_cost_bps)
    p25_pnl_per_trade = calculate_p25(symbol_pnl_per_trade)
    
    # 验收标准
    criteria = {
        "trades_per_hour": {
            "target": 20.0,
            "op": "<=",
            "desc": "交易频率 ≤20笔/小时（P25分位）",
            "value": p25_trades_per_hour,
            "symbol_values": symbol_trades_per_hour,
        },
        "cost_bps": {
            "target": 1.75,
            "op": "<=",
            "desc": "成本bps ≤1.75bps（Top-3方案中位数）",
            "value": p25_cost_bps,
            "symbol_values": symbol_cost_bps,
        },
        "pnl_per_trade": {
            "target": 0.0,
            "op": ">=",
            "desc": "单笔收益 ≥0（三对均值P25）",
            "value": p25_pnl_per_trade,
            "symbol_values": symbol_pnl_per_trade,
        },
        "ethusdt_robustness": {
            "target": 0.0,
            "op": ">=",
            "desc": "ETHUSDT稳健性（ETH净PnL不为显著负值）",
            "value": symbol_net_pnl[list(symbol_metrics.keys()).index("ETHUSDT")] if "ETHUSDT" in symbol_metrics else 0.0,
            "symbol_values": symbol_net_pnl,
        },
    }
    
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
        else:
            passed = False
        
        if not passed:
            all_passed = False
        
        results[criterion_key] = {
            "passed": passed,
            "value": value,
            "target": target,
            "description": criterion["desc"],
            "symbol_values": criterion.get("symbol_values", []),
        }
    
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
    
    # 假设所有实验使用相同的minutes（从命令行或默认值）
    minutes = 60  # 默认60分钟
    
    print("="*80)
    print("E组实验验收报告")
    print("="*80 + "\n")
    
    # 验收每个实验
    validation_results = {}
    for exp_key, exp_data in experiments.items():
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
            if result.get("symbol_values"):
                print(f"    各交易对: {result['symbol_values']}")
        
        print(f"\n总体状态: {'[PASS]' if passed else '[FAIL]'}")
    
    # 汇总
    print("\n" + "="*80)
    print("验收汇总")
    print("="*80 + "\n")
    
    all_experiments_passed = all(v["passed"] for v in validation_results.values())
    
    for exp_key, validation in validation_results.items():
        status = "[PASS]" if validation["passed"] else "[FAIL]"
        print(f"{status} {exp_key}: {experiments[exp_key]['name']}")
    
    print(f"\n总体验收: {'[PASS]' if all_experiments_passed else '[FAIL]'}")
    
    # 保存验收结果
    output_file = project_root / "runtime" / "optimizer" / "e_experiments_validation.json"
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

