# -*- coding: utf-8 -*-
"""ETHUSDT专项定位分析"""
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def run_ethusdt_backtest(config_path: Path, input_dir: str, date: str, minutes: int) -> Path:
    """运行ETHUSDT单独回测"""
    output_dir = project_root / "runtime" / "optimizer" / "ethusdt_analysis"
    
    print(f"\n{'='*60}")
    print(f"运行ETHUSDT专项分析")
    print(f"配置: {config_path}")
    print(f"输出: {output_dir}")
    print(f"{'='*60}\n")
    
    # 构建命令
    cmd = [
        sys.executable,
        str(project_root / "scripts" / "replay_harness.py"),
        "--input", input_dir,
        "--date", date,
        "--symbols", "ETHUSDT",
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
        print(f"[ERROR] ETHUSDT回测失败:")
        print(result.stderr)
        return None
    
    # 查找结果目录
    backtest_dirs = list(output_dir.glob("backtest_*"))
    if not backtest_dirs:
        print(f"[WARN] 未找到结果目录")
        return None
    
    result_dir = backtest_dirs[0]
    print(f"[OK] ETHUSDT回测完成，结果目录: {result_dir}")
    return result_dir


def load_metrics(result_dir: Path) -> Dict[str, Any]:
    """加载metrics.json"""
    metrics_file = result_dir / "metrics.json"
    if not metrics_file.exists():
        return None
    
    with open(metrics_file, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_cost_profile(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """分析成本剖面"""
    total_fee = metrics.get("total_fee", 0)
    total_slippage = metrics.get("total_slippage", 0)
    total_cost = total_fee + total_slippage
    total_turnover = metrics.get("total_turnover", 0)
    
    cost_bps = (total_cost / total_turnover * 10000) if total_turnover > 0 else 0
    fee_bps = (total_fee / total_turnover * 10000) if total_turnover > 0 else 0
    slippage_bps = (total_slippage / total_turnover * 10000) if total_turnover > 0 else 0
    
    # 计算Maker/Taker比例（如果有数据）
    maker_fee = metrics.get("maker_fee", 0)
    taker_fee = metrics.get("taker_fee", 0)
    total_fee_for_ratio = maker_fee + taker_fee
    maker_ratio = maker_fee / total_fee_for_ratio if total_fee_for_ratio > 0 else 0
    taker_ratio = taker_fee / total_fee_for_ratio if total_fee_for_ratio > 0 else 0
    
    return {
        "cost_bps": cost_bps,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "maker_ratio": maker_ratio,
        "taker_ratio": taker_ratio,
        "total_cost": total_cost,
        "total_fee": total_fee,
        "total_slippage": total_slippage,
    }


def compare_with_other_symbols(ethusdt_metrics: Dict[str, Any], 
                               btcusdt_metrics: Dict[str, Any],
                               bnbusdt_metrics: Dict[str, Any]) -> None:
    """对比ETHUSDT与其他交易对"""
    print("\n" + "="*80)
    print("ETHUSDT vs BTCUSDT vs BNBUSDT 对比")
    print("="*80 + "\n")
    
    symbols = {
        "ETHUSDT": ethusdt_metrics,
        "BTCUSDT": btcusdt_metrics,
        "BNBUSDT": bnbusdt_metrics,
    }
    
    # 对比关键指标
    print(f"{'指标':<20} {'ETHUSDT':<15} {'BTCUSDT':<15} {'BNBUSDT':<15}")
    print("-" * 80)
    
    # 成本bps
    for symbol, metrics in symbols.items():
        cost_profile = analyze_cost_profile(metrics)
        print(f"{'成本bps':<20} {cost_profile['cost_bps']:>14.2f} ", end="")
    print()
    
    # Maker比例
    for symbol, metrics in symbols.items():
        cost_profile = analyze_cost_profile(metrics)
        print(f"{'Maker比例':<20} {cost_profile['maker_ratio']:>14.2%} ", end="")
    print()
    
    # 滑点bps
    for symbol, metrics in symbols.items():
        cost_profile = analyze_cost_profile(metrics)
        print(f"{'滑点bps':<20} {cost_profile['slippage_bps']:>14.2f} ", end="")
    print()
    
    # 净PnL
    for symbol, metrics in symbols.items():
        net_pnl = metrics.get("total_pnl", 0) - metrics.get("total_fee", 0) - metrics.get("total_slippage", 0)
        print(f"{'净PnL':<20} ${net_pnl:>13.2f} ", end="")
    print()
    
    # 交易次数
    for symbol, metrics in symbols.items():
        total_trades = metrics.get("total_trades", 0)
        print(f"{'交易次数':<20} {total_trades:>14} ", end="")
    print()


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="ETHUSDT专项定位分析")
    parser.add_argument("--input", type=str, default="./deploy/data/ofi_cvd", help="输入数据目录")
    parser.add_argument("--date", type=str, default="2025-11-09", help="日期 (YYYY-MM-DD)")
    parser.add_argument("--minutes", type=int, default=60, help="回测时长（分钟）")
    parser.add_argument("--config", type=str, default="runtime/optimizer/group_d_combined.yaml", help="配置文件路径")
    
    args = parser.parse_args()
    
    config_path = project_root / args.config
    if not config_path.exists():
        print(f"[ERROR] 配置文件不存在: {config_path}")
        sys.exit(1)
    
    # 运行ETHUSDT回测
    result_dir = run_ethusdt_backtest(config_path, args.input, args.date, args.minutes)
    if not result_dir:
        sys.exit(1)
    
    # 加载ETHUSDT metrics
    ethusdt_metrics = load_metrics(result_dir)
    if not ethusdt_metrics:
        print("[ERROR] 无法加载ETHUSDT metrics")
        sys.exit(1)
    
    # 分析成本剖面
    print("\n" + "="*80)
    print("ETHUSDT 成本剖面分析")
    print("="*80 + "\n")
    
    cost_profile = analyze_cost_profile(ethusdt_metrics)
    print(f"成本bps: {cost_profile['cost_bps']:.2f}")
    print(f"  手续费bps: {cost_profile['fee_bps']:.2f}")
    print(f"  滑点bps: {cost_profile['slippage_bps']:.2f}")
    print(f"Maker比例: {cost_profile['maker_ratio']:.2%}")
    print(f"Taker比例: {cost_profile['taker_ratio']:.2%}")
    
    # 如果有其他交易对的数据，进行对比
    # （这里需要从之前的回测结果中加载）
    print("\n[INFO] 如需对比BTCUSDT和BNBUSDT，请运行完整的多交易对回测")
    
    # 保存分析结果
    output_file = project_root / "runtime" / "optimizer" / "ethusdt_analysis_result.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    analysis_result = {
        "config": str(config_path),
        "result_dir": str(result_dir),
        "metrics": ethusdt_metrics,
        "cost_profile": cost_profile,
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(analysis_result, f, indent=2, ensure_ascii=False)
    
    print(f"\n[OK] 分析结果已保存到: {output_file}")


if __name__ == "__main__":
    main()

