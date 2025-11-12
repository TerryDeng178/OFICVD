# -*- coding: utf-8 -*-
"""运行三组优化配置并对比结果"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 配置组定义
GROUPS = {
    "A": {
        "name": "严门控+去重提速",
        "config": "runtime/optimizer/group_a_strict_gating.yaml",
        "output_prefix": "group_a",
        "description": "主打降频：弱信号阈值0.7，去重窗口5000ms，持仓180s"
    },
    "B": {
        "name": "冷却+反向防抖",
        "config": "runtime/optimizer/group_b_cooldown_anti_flip.yaml",
        "output_prefix": "group_b",
        "description": "主打少反手：flip_rearm_margin=0.45，adaptive_cooldown_k=0.7"
    },
    "C": {
        "name": "Maker-first成本压降",
        "config": "runtime/optimizer/group_c_maker_first.yaml",
        "output_prefix": "group_c",
        "description": "主打降成本：maker_fee_ratio=0.4，安静期maker概率0.85"
    },
    "D": {
        "name": "A+B+C组合",
        "config": "runtime/optimizer/group_d_combined.yaml",
        "output_prefix": "group_d",
        "description": "一把到位的过线配置：weak_signal_threshold=0.70，flip_rearm_margin=0.45，min_hold_time_sec=240"
    }
}

# 基线数据（深层修复验证结果）
BASELINE = {
    "trades_per_hour": 934.0,
    "avg_hold_sec": 164.0,
    "cost_bps_on_turnover": 1.93,
    "pnl_per_trade": -0.82,
    "win_rate_trades": 0.1681,
    "total_trades": 934,
}


def run_backtest(group_key: str, group_info: Dict[str, Any], 
                 input_dir: str, date: str, symbols: str, minutes: int) -> Path:
    """运行单个组的回测"""
    config_path = project_root / group_info["config"]
    output_dir = project_root / "runtime" / "optimizer" / f"{group_info['output_prefix']}_validation"
    
    print(f"\n{'='*60}")
    print(f"运行组 {group_key}: {group_info['name']}")
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
        "--kinds", "features",
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
        print(f"[ERROR] 组 {group_key} 运行失败:")
        print(result.stderr)
        return None
    
    # 查找结果目录
    backtest_dirs = list(output_dir.glob("backtest_*"))
    if not backtest_dirs:
        print(f"[WARN] 组 {group_key} 未找到结果目录")
        return None
    
    result_dir = backtest_dirs[0]
    print(f"[OK] 组 {group_key} 完成，结果目录: {result_dir}")
    return result_dir


def load_metrics(result_dir: Path) -> Dict[str, Any]:
    """加载metrics.json"""
    metrics_file = result_dir / "metrics.json"
    if not metrics_file.exists():
        return None
    
    with open(metrics_file, "r", encoding="utf-8") as f:
        return json.load(f)


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


def compare_results(results: Dict[str, Dict[str, Any]]) -> None:
    """对比结果并生成报告"""
    print("\n" + "="*80)
    print("优化组对比报告")
    print("="*80 + "\n")
    
    # 表头
    print(f"{'组':<6} {'名称':<20} {'trades/h':<10} {'hold_sec':<10} {'cost_bps':<10} {'pnl/trade':<12} {'win_rate':<10}")
    print("-" * 80)
    
    # 基线
    print(f"{'基线':<6} {'深层修复验证':<20} "
          f"{BASELINE['trades_per_hour']:>9.1f} "
          f"{BASELINE['avg_hold_sec']:>9.1f}s "
          f"{BASELINE['cost_bps_on_turnover']:>9.2f}bps "
          f"${BASELINE['pnl_per_trade']:>10.2f} "
          f"{BASELINE['win_rate_trades']:>9.2%}")
    
    # 各组结果
    for group_key, group_info in GROUPS.items():
        if group_key not in results:
            print(f"{group_key:<6} {group_info['name']:<20} {'N/A':<10} {'N/A':<10} {'N/A':<10} {'N/A':<12} {'N/A':<10}")
            continue
        
        metrics = results[group_key]["metrics"]
        print(f"{group_key:<6} {group_info['name']:<20} "
              f"{metrics['trades_per_hour']:>9.1f} "
              f"{metrics['avg_hold_sec']:>9.1f}s "
              f"{metrics['cost_bps_on_turnover']:>9.2f}bps "
              f"${metrics['pnl_per_trade']:>10.2f} "
              f"{metrics['win_rate_trades']:>9.2%}")
    
    print("\n" + "="*80)
    print("验收标准检查")
    print("="*80 + "\n")
    
    # 验收标准
    acceptance_criteria = {
        "trades_per_hour": {"target": 20.0, "op": "<=", "desc": "交易频率 ≤20笔/小时"},
        "avg_hold_sec": {"target": 180.0, "op": ">=", "desc": "平均持仓 ≥180秒"},
        "cost_bps_on_turnover": {"target": 1.75, "op": "<=", "desc": "成本bps ≤1.75bps"},
    }
    
    for group_key, group_info in GROUPS.items():
        if group_key not in results:
            continue
        
        metrics = results[group_key]["metrics"]
        print(f"\n组 {group_key}: {group_info['name']}")
        
        for metric_key, criteria in acceptance_criteria.items():
            value = metrics[metric_key]
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
    
    # 改善对比
    print("\n" + "="*80)
    print("相对基线改善")
    print("="*80 + "\n")
    
    for group_key, group_info in GROUPS.items():
        if group_key not in results:
            continue
        
        metrics = results[group_key]["metrics"]
        print(f"\n组 {group_key}: {group_info['name']}")
        
        improvements = []
        for metric_key in ["trades_per_hour", "avg_hold_sec", "cost_bps_on_turnover", "win_rate_trades"]:
            baseline_value = BASELINE[metric_key]
            current_value = metrics[metric_key]
            
            if metric_key == "trades_per_hour" or metric_key == "cost_bps_on_turnover":
                # 越低越好
                change_pct = (baseline_value - current_value) / baseline_value * 100
                if change_pct > 0:
                    improvements.append(f"{metric_key}: DOWN {change_pct:.1f}%")
            else:
                # 越高越好
                change_pct = (current_value - baseline_value) / baseline_value * 100
                if change_pct > 0:
                    improvements.append(f"{metric_key}: UP {change_pct:.1f}%")
        
        if improvements:
            for imp in improvements:
                print(f"  {imp}")
        else:
            print("  [WARN] 未发现明显改善")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="运行三组优化配置并对比结果")
    parser.add_argument("--input", type=str, default="./deploy/data/ofi_cvd", help="输入数据目录")
    parser.add_argument("--date", type=str, default="2025-11-09", help="日期 (YYYY-MM-DD)")
    parser.add_argument("--symbols", type=str, default="BTCUSDT,ETHUSDT", help="交易对（逗号分隔）")
    parser.add_argument("--minutes", type=int, default=60, help="回测时长（分钟）")
    parser.add_argument("--groups", type=str, default="A,B,C,D", help="要运行的组（逗号分隔，如A,B,C,D）")
    
    args = parser.parse_args()
    
    # 解析要运行的组
    groups_to_run = [g.strip().upper() for g in args.groups.split(",")]
    
    # 运行各组回测
    results = {}
    for group_key in groups_to_run:
        if group_key not in GROUPS:
            print(f"[WARN] 未知组: {group_key}，跳过")
            continue
        
        group_info = GROUPS[group_key]
        result_dir = run_backtest(group_key, group_info, args.input, args.date, args.symbols, args.minutes)
        
        if result_dir:
            metrics = load_metrics(result_dir)
            if metrics:
                key_metrics = calculate_key_metrics(metrics, args.minutes)
                results[group_key] = {
                    "result_dir": result_dir,
                    "metrics": key_metrics,
                    "full_metrics": metrics,
                }
    
    # 对比结果
    if results:
        compare_results(results)
        
        # 保存结果到JSON
        output_file = project_root / "runtime" / "optimizer" / "optimization_groups_comparison.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        comparison_data = {
            "baseline": BASELINE,
            "groups": {}
        }
        
        for group_key, result in results.items():
            comparison_data["groups"][group_key] = {
                "name": GROUPS[group_key]["name"],
                "description": GROUPS[group_key]["description"],
                "result_dir": str(result["result_dir"]),
                "metrics": result["metrics"],
            }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(comparison_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n[OK] 对比结果已保存到: {output_file}")
    else:
        print("\n[ERROR] 没有成功运行任何组")


if __name__ == "__main__":
    main()

