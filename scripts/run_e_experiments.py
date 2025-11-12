# -*- coding: utf-8 -*-
"""运行E1/E2/E3三个实验（基于D组）"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# E组实验定义
E_GROUPS = {
    "E1": {
        "name": "入口节流+去重加严",
        "config": "runtime/optimizer/group_e1_entry_throttle.yaml",
        "output_prefix": "group_e1",
        "description": "降频：weak_signal_threshold=0.78, consistency_min=0.48, dedupe_ms=6000"
    },
    "E2": {
        "name": "Maker概率&费率专项",
        "config": "runtime/optimizer/group_e2_maker_cost.yaml",
        "output_prefix": "group_e2",
        "description": "降成本：maker_fee_ratio=0.35, Q_L=0.90, A_L=0.80"
    },
    "E3": {
        "name": "TP/SL + 死区组合",
        "config": "runtime/optimizer/group_e3_tp_sl.yaml",
        "output_prefix": "group_e3",
        "description": "抬单笔收益：take_profit_bps=18, stop_loss_bps=6, deadband_bps=3"
    },
    "E4": {
        "name": "E1入口节流+E2 Maker策略合并",
        "config": "runtime/optimizer/group_e4_combined.yaml",
        "output_prefix": "group_e4",
        "description": "降频+降成本：E1阈值/去重 + E2 Maker参数，trades_per_hour≤25且cost_bps≤1.85"
    },
    "E5": {
        "name": "TP/SL+死区回调",
        "config": "runtime/optimizer/group_e5_optimized_tp_sl.yaml",
        "output_prefix": "group_e5",
        "description": "抬单笔收益：take_profit_bps=15, stop_loss_bps=8, deadband_bps=1.5"
    },
    "E6": {
        "name": "极限降频闸",
        "config": "runtime/optimizer/group_e6_ultra_low_tps.yaml",
        "output_prefix": "group_e6",
        "description": "极限降频：weak_signal_threshold=0.80, consistency_min=0.50, dedupe_ms=8000, min_consecutive=4"
    }
}

# D组基线（多交易对优化结果）
D_BASELINE = {
    "trades_per_hour": 71.0,
    "cost_bps_on_turnover": 1.93,
    "pnl_per_trade": -0.64,
    "win_rate_trades": 0.1681,
    "net_pnl": -64.0,
}


def run_backtest(group_key: str, group_info: Dict[str, Any], 
                 input_dir: str, date: str, symbols: str, minutes: int) -> Path:
    """运行单个组的回测"""
    config_path = project_root / group_info["config"]
    output_dir = project_root / "runtime" / "optimizer" / f"{group_info['output_prefix']}_validation"
    
    print(f"\n{'='*60}")
    print(f"运行实验 {group_key}: {group_info['name']}")
    print(f"描述: {group_info['description']}")
    print(f"配置: {config_path}")
    print(f"输出: {output_dir}")
    print(f"{'='*60}\n")
    
    # 构建命令
    cmd = [
        sys.executable,
        str(project_root / "scripts" / "replay_harness.py"),
        "--input", input_dir,
        "--date", date,
        "--symbols", symbols,
        "--kinds", "prices,orderbook",  # 修复：使用full path确保spread_bps非0
        "--minutes", str(minutes),
        "--config", str(config_path),
        "--output", str(output_dir),
    ]
    
    # 运行回测
    print(f"执行命令: {' '.join(cmd)}\n")
    result = subprocess.run(
        cmd, 
        cwd=project_root, 
        capture_output=True, 
        text=True, 
        encoding="utf-8",
        errors="replace"
    )
    
    if result.returncode != 0:
        print(f"[ERROR] 实验 {group_key} 运行失败:")
        print(result.stderr)
        return None
    
    # 查找结果目录
    backtest_dirs = list(output_dir.glob("backtest_*"))
    if not backtest_dirs:
        print(f"[WARN] 实验 {group_key} 未找到结果目录")
        return None
    
    result_dir = backtest_dirs[0]
    print(f"[OK] 实验 {group_key} 完成，结果目录: {result_dir}")
    return result_dir


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
    }


def compare_results(results: Dict[str, Dict[str, Any]], minutes: int) -> None:
    """对比结果并生成报告"""
    print("\n" + "="*80)
    print("E组实验对比报告")
    print("="*80 + "\n")
    
    # 表头
    print(f"{'实验':<6} {'名称':<25} {'trades/h':<10} {'cost_bps':<10} {'pnl/trade':<12} {'win_rate':<10}")
    print("-" * 80)
    
    # D组基线
    print(f"{'D基线':<6} {'D组组合（多交易对）':<25} "
          f"{D_BASELINE['trades_per_hour']:>9.1f} "
          f"{D_BASELINE['cost_bps_on_turnover']:>9.2f}bps "
          f"${D_BASELINE['pnl_per_trade']:>10.2f} "
          f"{D_BASELINE['win_rate_trades']:>9.2%}")
    
    # 各组结果
    for group_key, group_info in E_GROUPS.items():
        if group_key not in results:
            print(f"{group_key:<6} {group_info['name']:<25} {'N/A':<10} {'N/A':<10} {'N/A':<12} {'N/A':<10}")
            continue
        
        metrics = results[group_key]["metrics"]
        print(f"{group_key:<6} {group_info['name']:<25} "
              f"{metrics['trades_per_hour']:>9.1f} "
              f"{metrics['cost_bps_on_turnover']:>9.2f}bps "
              f"${metrics['pnl_per_trade']:>10.2f} "
              f"{metrics['win_rate_trades']:>9.2%}")
    
    print("\n" + "="*80)
    print("验收标准检查（P25分位）")
    print("="*80 + "\n")
    
    # 验收标准
    acceptance_criteria = {
        "trades_per_hour": {"target": 20.0, "op": "<=", "desc": "交易频率 ≤20笔/小时"},
        "cost_bps_on_turnover": {"target": 1.75, "op": "<=", "desc": "成本bps ≤1.75bps"},
        "pnl_per_trade": {"target": 0.0, "op": ">=", "desc": "单笔收益 ≥0"},
    }
    
    for group_key, group_info in E_GROUPS.items():
        if group_key not in results:
            continue
        
        metrics = results[group_key]["metrics"]
        symbol_metrics = results[group_key].get("symbol_metrics", {})
        
        print(f"\n实验 {group_key}: {group_info['name']}")
        
        # 计算各交易对的指标
        symbol_trades_per_hour = []
        symbol_cost_bps = []
        symbol_pnl_per_trade = []
        
        for symbol, sym_metrics in symbol_metrics.items():
            sym_hours = minutes / 60.0
            sym_trades_per_hour = sym_metrics.get("total_trades", 0) / sym_hours if sym_hours > 0 else 0
            sym_cost_bps = sym_metrics.get("cost_bps_on_turnover", 0)
            sym_net_pnl = sym_metrics.get("total_pnl", 0) - sym_metrics.get("total_fee", 0) - sym_metrics.get("total_slippage", 0)
            sym_pnl_per_trade = sym_net_pnl / sym_metrics.get("total_trades", 1) if sym_metrics.get("total_trades", 0) > 0 else 0
            
            symbol_trades_per_hour.append(sym_trades_per_hour)
            symbol_cost_bps.append(sym_cost_bps)
            symbol_pnl_per_trade.append(sym_pnl_per_trade)
        
        # 计算P25分位（简单排序取第一个四分位）
        def p25(values):
            if not values:
                return 0
            sorted_vals = sorted(values)
            idx = max(0, len(sorted_vals) // 4 - 1)
            return sorted_vals[idx]
        
        p25_trades_per_hour = p25(symbol_trades_per_hour) if symbol_trades_per_hour else metrics["trades_per_hour"]
        p25_cost_bps = p25(symbol_cost_bps) if symbol_cost_bps else metrics["cost_bps_on_turnover"]
        p25_pnl_per_trade = p25(symbol_pnl_per_trade) if symbol_pnl_per_trade else metrics["pnl_per_trade"]
        
        # 检查验收标准
        for metric_key, criteria in acceptance_criteria.items():
            if metric_key == "trades_per_hour":
                value = p25_trades_per_hour
            elif metric_key == "cost_bps_on_turnover":
                value = p25_cost_bps
            elif metric_key == "pnl_per_trade":
                value = p25_pnl_per_trade
            else:
                value = metrics.get(metric_key, 0)
            
            target = criteria["target"]
            op = criteria["op"]
            
            if op == "<=":
                passed = value <= target
            elif op == ">=":
                passed = value >= target
            else:
                passed = False
            
            status = "[OK]" if passed else "[FAIL]"
            print(f"  {status} {criteria['desc']}: {value:.2f} vs {target:.2f} ({'通过' if passed else '未达标'})")
            if metric_key in ["trades_per_hour", "cost_bps_on_turnover", "pnl_per_trade"]:
                print(f"      (P25分位值，各交易对: {symbol_trades_per_hour if metric_key == 'trades_per_hour' else symbol_cost_bps if metric_key == 'cost_bps_on_turnover' else symbol_pnl_per_trade})")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="运行E1/E2/E3三个实验（基于D组）")
    parser.add_argument("--input", type=str, default="./deploy/data/ofi_cvd", help="输入数据目录")
    parser.add_argument("--date", type=str, default="2025-11-09", help="日期 (YYYY-MM-DD)")
    parser.add_argument("--symbols", type=str, default="BTCUSDT,ETHUSDT,BNBUSDT", help="交易对（逗号分隔）")
    parser.add_argument("--minutes", type=int, default=60, help="回测时长（分钟）")
    parser.add_argument("--groups", type=str, default="E1,E2,E3", help="要运行的实验（逗号分隔，如E1,E2,E3）")
    
    args = parser.parse_args()
    
    # 解析要运行的组
    groups_to_run = [g.strip().upper() for g in args.groups.split(",")]
    
    # 运行各组回测
    results = {}
    for group_key in groups_to_run:
        if group_key not in E_GROUPS:
            print(f"[WARN] 未知实验: {group_key}，跳过")
            continue
        
        group_info = E_GROUPS[group_key]
        result_dir = run_backtest(group_key, group_info, args.input, args.date, args.symbols, args.minutes)
        
        if result_dir:
            metrics = load_metrics(result_dir)
            symbol_metrics = load_symbol_metrics(result_dir)
            
            if metrics:
                key_metrics = calculate_key_metrics(metrics, args.minutes)
                results[group_key] = {
                    "result_dir": result_dir,
                    "metrics": key_metrics,
                    "full_metrics": metrics,
                    "symbol_metrics": symbol_metrics,
                }
    
    # 对比结果
    if results:
        compare_results(results, args.minutes)
        
        # 保存结果到JSON
        output_file = project_root / "runtime" / "optimizer" / "e_experiments_comparison.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        comparison_data = {
            "baseline": D_BASELINE,
            "experiments": {}
        }
        
        for group_key, result in results.items():
            comparison_data["experiments"][group_key] = {
                "name": E_GROUPS[group_key]["name"],
                "description": E_GROUPS[group_key]["description"],
                "result_dir": str(result["result_dir"]),
                "metrics": result["metrics"],
                "symbol_metrics": result.get("symbol_metrics", {}),
            }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(comparison_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n[OK] 对比结果已保存到: {output_file}")
    else:
        print("\n[ERROR] 没有成功运行任何实验")


if __name__ == "__main__":
    main()

