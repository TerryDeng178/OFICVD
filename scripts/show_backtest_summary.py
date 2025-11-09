#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""显示回测结果摘要"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

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

def main():
    """主函数"""
    # 查找最新的回测结果
    backtest_dir = Path("runtime/backtest")
    if not backtest_dir.exists():
        print("错误: runtime/backtest 目录不存在")
        return 1
    
    runs = sorted(backtest_dir.glob("backtest_24h_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        print("错误: 未找到24小时回测结果")
        return 1
    
    latest_run = runs[0]
    print(f"最新回测: {latest_run.name}")
    
    # 查找实际输出目录
    subdirs = list(latest_run.glob("backtest_*"))
    actual_dir = subdirs[0] if subdirs else latest_run
    
    print(f"结果目录: {actual_dir}")
    print("=" * 80)
    
    # 读取运行清单
    manifest_file = actual_dir / "run_manifest.json"
    if manifest_file.exists():
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        
        print("\n运行信息:")
        print(f"  Run ID: {manifest.get('run_id', 'N/A')}")
        print(f"  开始时间: {manifest.get('started_at', 'N/A')}")
        
        reader_stats = manifest.get("reader_stats", {})
        print(f"\n数据统计:")
        print(f"  总行数: {reader_stats.get('total_rows', 0):,}")
        print(f"  去重行数: {reader_stats.get('deduplicated_rows', 0):,}")
        print(f"  去重率: {reader_stats.get('deduplication_rate_pct', 0):.2f}%")
        
        feeder_stats = manifest.get("feeder_stats", {})
        print(f"\n信号统计:")
        print(f"  处理行数: {feeder_stats.get('processed', 0):,}")
        print(f"  生成信号: {feeder_stats.get('emitted', 0):,}")
        print(f"  抑制信号: {feeder_stats.get('suppressed', 0):,}")
        
        trade_stats = manifest.get("trade_stats", {})
        print(f"\n交易统计:")
        print(f"  总交易数: {trade_stats.get('total_trades', 0):,}")
        print(f"  持仓数: {trade_stats.get('open_positions', 0):,}")
    
    # 读取交易记录
    trades_file = actual_dir / "trades.jsonl"
    trades = load_jsonl(trades_file)
    if trades:
        print(f"\n交易记录（共 {len(trades)} 笔）:")
        print("  前10笔交易:")
        for i, trade in enumerate(trades[:10], 1):
            ts_ms = trade.get("ts_ms", 0)
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            symbol = trade.get("symbol", "")
            side = trade.get("side", "")
            px = trade.get("px", 0)
            qty = trade.get("qty", 0)
            fee = trade.get("fee", 0)
            print(f"    {i}. {time_str} {symbol} {side} 价格={px:.2f} 数量={qty:.6f} 费用={fee:.4f}")
    else:
        print("\n交易记录: 无交易")
    
    # 读取每日PnL
    pnl_file = actual_dir / "pnl_daily.jsonl"
    pnl_daily = load_jsonl(pnl_file)
    if pnl_daily:
        print(f"\n每日PnL（共 {len(pnl_daily)} 天）:")
        total_net = sum(d.get("net_pnl", 0) for d in pnl_daily)
        total_trades = sum(d.get("trades", 0) for d in pnl_daily)
        print(f"  总净收益: {total_net:.2f}")
        print(f"  总交易数: {total_trades}")
        for daily in pnl_daily[:5]:
            date = daily.get("date", "")
            net_pnl = daily.get("net_pnl", 0)
            trades = daily.get("trades", 0)
            print(f"    {date}: 净收益={net_pnl:.2f} 交易数={trades}")
    else:
        print("\n每日PnL: 无记录")
    
    # 读取指标
    metrics_file = actual_dir / "metrics.json"
    if metrics_file.exists():
        with open(metrics_file, "r", encoding="utf-8") as f:
            metrics = json.load(f)
        
        print("\n性能指标:")
        print(f"  总收益: {metrics.get('total_pnl', 0):.2f}")
        print(f"  Sharpe比率: {metrics.get('sharpe_ratio', 0):.2f}")
        print(f"  Sortino比率: {metrics.get('sortino_ratio', 0):.2f}")
        print(f"  最大回撤: {metrics.get('max_drawdown', 0):.2f}")
        print(f"  MAR: {metrics.get('MAR', 0):.2f}")
        print(f"  命中率: {metrics.get('hit_ratio', 0):.2%}")
        print(f"  盈亏比: {metrics.get('profit_loss_ratio', 0):.2f}")
        print(f"  总交易数: {metrics.get('total_trades', 0)}")
    else:
        print("\n性能指标: 无数据")
    
    print("\n" + "=" * 80)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())


