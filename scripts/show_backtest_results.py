#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""显示回测结果"""
import json
import sys
from pathlib import Path

def load_jsonl(file_path: Path):
    """加载JSONL文件"""
    results = []
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return results

def format_number(value, decimals=2):
    """格式化数字"""
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:,.{decimals}f}"
    return str(value)

def show_trades(trades_file: Path, limit=20):
    """显示交易记录"""
    trades = load_jsonl(trades_file)
    if not trades:
        print("  无交易记录")
        return
    
    print(f"\n  交易记录（共 {len(trades)} 笔，显示前 {min(limit, len(trades))} 笔）:")
    print("  " + "=" * 120)
    print(f"  {'时间':<20} {'交易对':<12} {'方向':<6} {'价格':<12} {'数量':<12} {'费用':<10} {'滑点(bps)':<12} {'原因':<20}")
    print("  " + "-" * 120)
    
    for trade in trades[:limit]:
        ts_ms = trade.get("ts_ms", 0)
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        
        symbol = trade.get("symbol", "")
        side = trade.get("side", "")
        px = format_number(trade.get("px", 0), 2)
        qty = format_number(trade.get("qty", 0), 6)
        fee = format_number(trade.get("fee", 0), 4)
        slippage_bps = format_number(trade.get("slippage_bps", 0), 2)
        reason = trade.get("reason", "")
        
        print(f"  {time_str:<20} {symbol:<12} {side:<6} {px:<12} {qty:<12} {fee:<10} {slippage_bps:<12} {reason:<20}")
    
    if len(trades) > limit:
        print(f"  ... (还有 {len(trades) - limit} 笔交易)")

def show_pnl_daily(pnl_file: Path):
    """显示每日PnL"""
    pnl_daily = load_jsonl(pnl_file)
    if not pnl_daily:
        print("  无每日PnL记录")
        return
    
    print(f"\n  每日PnL（共 {len(pnl_daily)} 天）:")
    print("  " + "=" * 100)
    print(f"  {'日期':<12} {'交易对':<12} {'总收益':<12} {'费用':<10} {'滑点':<10} {'净收益':<12} {'交易数':<8} {'胜率':<8}")
    print("  " + "-" * 100)
    
    total_gross = 0.0
    total_fee = 0.0
    total_slippage = 0.0
    total_net = 0.0
    total_trades = 0
    
    for daily in pnl_daily:
        date = daily.get("date", "")
        symbol = daily.get("symbol", "")
        gross_pnl = daily.get("gross_pnl", 0.0)
        fee = daily.get("fee", 0.0)
        slippage = daily.get("slippage", 0.0)
        net_pnl = daily.get("net_pnl", 0.0)
        trades = daily.get("trades", 0)
        win_rate = daily.get("win_rate", 0.0) * 100
        
        total_gross += gross_pnl
        total_fee += fee
        total_slippage += slippage
        total_net += net_pnl
        total_trades += trades
        
        print(f"  {date:<12} {symbol:<12} {format_number(gross_pnl):<12} {format_number(fee):<10} {format_number(slippage):<10} {format_number(net_pnl):<12} {trades:<8} {format_number(win_rate, 1):<8}%")
    
    print("  " + "-" * 100)
    print(f"  {'总计':<12} {'':<12} {format_number(total_gross):<12} {format_number(total_fee):<10} {format_number(total_slippage):<10} {format_number(total_net):<12} {total_trades:<8}")

def show_metrics(metrics_file: Path):
    """显示指标"""
    if not metrics_file.exists():
        print("  指标文件不存在")
        return
    
    with open(metrics_file, "r", encoding="utf-8") as f:
        metrics = json.load(f)
    
    print("\n  性能指标:")
    print("  " + "=" * 60)
    print(f"  {'指标':<30} {'值':<30}")
    print("  " + "-" * 60)
    
    key_metrics = [
        ("总收益 (Total PnL)", "total_pnl"),
        ("Sharpe比率 (年化)", "sharpe_ratio"),
        ("Sortino比率 (年化)", "sortino_ratio"),
        ("最大回撤", "max_drawdown"),
        ("MAR (年化)", "MAR"),
        ("命中率", "hit_ratio"),
        ("盈亏比", "profit_loss_ratio"),
        ("平均持有时间 (秒)", "avg_hold_time_sec"),
        ("总交易数", "total_trades"),
        ("胜率", "win_rate"),
    ]
    
    for label, key in key_metrics:
        value = metrics.get(key)
        if value is not None:
            if isinstance(value, float):
                if abs(value) < 0.01:
                    value_str = f"{value:.6f}"
                else:
                    value_str = f"{value:.2f}"
            else:
                value_str = str(value)
            print(f"  {label:<30} {value_str:<30}")

def main():
    """主函数"""
    if len(sys.argv) < 2:
        # 查找最新的回测结果
        backtest_dir = Path("runtime/backtest")
        if not backtest_dir.exists():
            print("错误: runtime/backtest 目录不存在")
            return 1
        
        runs = sorted(backtest_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if not runs:
            print("错误: 未找到回测结果")
            return 1
        
        output_dir = runs[0]
        print(f"使用最新回测结果: {output_dir.name}")
    else:
        output_dir = Path(sys.argv[1])
    
    if not output_dir.exists():
        print(f"错误: 目录不存在: {output_dir}")
        return 1
    
    print("\n" + "=" * 120)
    print(f"回测结果: {output_dir.name}")
    print("=" * 120)
    
    # 显示运行清单
    manifest_file = output_dir / "run_manifest.json"
    if manifest_file.exists():
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        
        print("\n运行信息:")
        print(f"  Run ID: {manifest.get('run_id', 'N/A')}")
        print(f"  开始时间: {manifest.get('started_at', 'N/A')}")
        
        reader_stats = manifest.get("reader_stats", {})
        if reader_stats:
            print(f"\n  数据统计:")
            print(f"    总行数: {reader_stats.get('total_rows', 0):,}")
            print(f"    去重行数: {reader_stats.get('deduplicated_rows', 0):,}")
            print(f"    去重率: {reader_stats.get('deduplication_rate', 0):.2f}%")
        
        feeder_stats = manifest.get("feeder_stats", {})
        if feeder_stats:
            print(f"\n  信号统计:")
            print(f"    处理行数: {feeder_stats.get('processed', 0):,}")
            print(f"    生成信号: {feeder_stats.get('emitted', 0):,}")
            print(f"    抑制信号: {feeder_stats.get('suppressed', 0):,}")
        
        trade_stats = manifest.get("trade_stats", {})
        if trade_stats:
            print(f"\n  交易统计:")
            print(f"    总交易数: {trade_stats.get('total_trades', 0):,}")
            print(f"    持仓数: {trade_stats.get('open_positions', 0):,}")
    
    # 显示交易记录
    trades_file = output_dir / "trades.jsonl"
    if trades_file.exists():
        show_trades(trades_file)
    
    # 显示每日PnL
    pnl_file = output_dir / "pnl_daily.jsonl"
    if pnl_file.exists():
        show_pnl_daily(pnl_file)
    
    # 显示指标
    metrics_file = output_dir / "metrics.json"
    if metrics_file.exists():
        show_metrics(metrics_file)
    
    print("\n" + "=" * 120)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())


