#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成详细的回测分析报告"""
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

def load_jsonl(file_path: Path):
    """加载JSONL文件"""
    data = []
    if not file_path.exists():
        return data
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    data.append(json.loads(line))
                except:
                    continue
    return data

def main():
    backtest_dir = Path("runtime/backtest/6pairs_24h_20251109_200401")
    result_dir = list(backtest_dir.glob("backtest_*"))[0]
    
    # 加载数据
    trades = load_jsonl(result_dir / "trades.jsonl")
    pnl_daily = load_jsonl(result_dir / "pnl_daily.jsonl")
    
    with open(result_dir / "metrics.json", "r", encoding="utf-8") as f:
        metrics = json.load(f)
    
    with open(result_dir / "run_manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    # 按交易对统计
    by_symbol = defaultdict(lambda: {"trades": [], "pnl": 0, "fee": 0, "slippage": 0, "wins": 0, "losses": 0})
    
    for trade in trades:
        symbol = trade.get("symbol", "UNKNOWN")
        by_symbol[symbol]["trades"].append(trade)
        by_symbol[symbol]["pnl"] += trade.get("pnl", 0)
        by_symbol[symbol]["fee"] += trade.get("fee", 0)
        by_symbol[symbol]["slippage"] += trade.get("slippage", 0)
        if trade.get("pnl", 0) > 0:
            by_symbol[symbol]["wins"] += 1
        elif trade.get("pnl", 0) < 0:
            by_symbol[symbol]["losses"] += 1
    
    # 生成报告
    report = []
    report.append("# 6交易对24小时回测详细分析报告")
    report.append("")
    report.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    
    # 回测参数
    report.append("## 1. 回测参数配置")
    report.append("")
    report.append("### 基本信息")
    report.append(f"- **回测日期**: 2025-11-09")
    report.append(f"- **交易对**: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT")
    report.append(f"- **回测时长**: 24小时")
    report.append(f"- **数据行数**: {manifest.get('reader_stats', {}).get('total_rows', 0):,}")
    report.append(f"- **去重后行数**: {manifest.get('reader_stats', {}).get('total_rows', 0) - manifest.get('reader_stats', {}).get('deduplicated_rows', 0):,}")
    report.append("")
    
    config = manifest.get("config", {})
    backtest_config = config.get("backtest", {})
    report.append("### 回测配置")
    report.append(f"- **费率模型**: {backtest_config.get('fee_model', 'N/A')}")
    report.append(f"- **滑点模型**: {backtest_config.get('slippage_model', 'N/A')}")
    report.append(f"- **Taker费率**: {backtest_config.get('taker_fee_bps', 0)} bps")
    report.append(f"- **滑点**: {backtest_config.get('slippage_bps', 0)} bps")
    report.append(f"- **每笔交易名义价值**: ${backtest_config.get('notional_per_trade', 0):.2f}")
    report.append(f"- **忽略闸门**: {backtest_config.get('ignore_gating_in_backtest', False)}")
    report.append(f"- **反向交易**: {backtest_config.get('reverse_on_signal', False)}")
    report.append(f"- **止盈**: {backtest_config.get('take_profit_bps', 'N/A')} bps")
    report.append(f"- **止损**: {backtest_config.get('stop_loss_bps', 'N/A')} bps")
    report.append("")
    
    strategy_config = config.get("strategy", {})
    report.append("### 策略配置")
    report.append(f"- **模式**: {strategy_config.get('mode', 'N/A')}")
    report.append(f"- **方向**: {strategy_config.get('direction', 'N/A')}")
    report.append(f"- **入场阈值**: {strategy_config.get('entry_threshold', 0)}")
    report.append(f"- **出场阈值**: {strategy_config.get('exit_threshold', 0)}")
    report.append("")
    
    components_config = config.get("components", {})
    fusion_config = components_config.get("fusion", {})
    report.append("### 信号融合配置")
    report.append(f"- **OFI权重**: {fusion_config.get('w_ofi', 0)}")
    report.append(f"- **CVD权重**: {fusion_config.get('w_cvd', 0)}")
    report.append("")
    
    # 总体表现
    report.append("## 2. 总体表现")
    report.append("")
    report.append(f"- **总交易数**: {metrics.get('total_trades', 0):,}")
    report.append(f"- **总PnL**: ${metrics.get('total_pnl', 0):.2f}")
    report.append(f"- **总费用**: ${metrics.get('total_fee', 0):.2f}")
    report.append(f"- **总滑点**: ${metrics.get('total_slippage', 0):.2f}")
    report.append(f"- **净PnL**: ${metrics.get('total_pnl', 0) - metrics.get('total_fee', 0) - metrics.get('total_slippage', 0):.2f}")
    report.append(f"- **总成交额**: ${metrics.get('total_turnover', 0):,.2f}")
    report.append(f"- **胜率**: {metrics.get('win_rate', 0)*100:.2f}%")
    report.append(f"- **盈亏比**: {metrics.get('risk_reward_ratio', 0):.4f}")
    report.append("")
    
    report.append("### 性能指标")
    report.append(f"- **Sharpe比率**: {metrics.get('sharpe_ratio', 0):.4f}")
    report.append(f"- **Sortino比率**: {metrics.get('sortino_ratio', 0):.4f}")
    report.append(f"- **最大回撤**: {metrics.get('max_drawdown', 0):.2f} bps")
    report.append(f"- **MAR比率**: {metrics.get('MAR', 0):.4f}")
    report.append(f"- **平均持有时长**: {metrics.get('avg_hold_sec', 0):.2f} 秒")
    report.append("")
    
    # 按交易对分析
    report.append("## 3. 按交易对详细分析")
    report.append("")
    report.append("| 交易对 | 交易数 | 总PnL | 费用 | 滑点 | 净PnL | 胜率 | 盈亏比 | 平均持有时长 |")
    report.append("|--------|--------|-------|------|------|-------|------|--------|--------------|")
    
    sorted_symbols = sorted(by_symbol.items(), key=lambda x: x[1]["pnl"], reverse=True)
    
    for symbol, stats in sorted_symbols:
        total_trades = len(stats["trades"])
        win_rate = stats["wins"] / total_trades if total_trades > 0 else 0
        net_pnl = stats["pnl"] - stats["fee"] - stats["slippage"]
        
        # 计算盈亏比
        wins_pnl = [t.get("pnl", 0) for t in stats["trades"] if t.get("pnl", 0) > 0]
        losses_pnl = [t.get("pnl", 0) for t in stats["trades"] if t.get("pnl", 0) < 0]
        avg_win = sum(wins_pnl) / len(wins_pnl) if wins_pnl else 0
        avg_loss = abs(sum(losses_pnl) / len(losses_pnl)) if losses_pnl else 0
        risk_reward = avg_win / avg_loss if avg_loss > 0 else 0
        
        # 平均持有时长
        hold_times = [t.get("hold_time_sec", 0) for t in stats["trades"] if t.get("hold_time_sec", 0) > 0]
        avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0
        
        report.append(
            f"| {symbol} | {total_trades} | ${stats['pnl']:.2f} | "
            f"${stats['fee']:.2f} | ${stats['slippage']:.2f} | ${net_pnl:.2f} | "
            f"{win_rate*100:.2f}% | {risk_reward:.4f} | {avg_hold:.2f}s |"
        )
    
    report.append("")
    
    # 场景分析
    report.append("## 4. 场景分析")
    report.append("")
    scenario_breakdown = metrics.get("scenario_breakdown", {})
    if scenario_breakdown:
        report.append("| 场景 | 交易数 | PnL | 胜率 | 平均PnL | 平均持有时长 |")
        report.append("|------|--------|-----|------|---------|--------------|")
        
        for scenario, stats in sorted(scenario_breakdown.items(), key=lambda x: x[1].get("pnl", 0), reverse=True):
            report.append(
                f"| {scenario} | {stats.get('trades', 0)} | ${stats.get('pnl', 0):.2f} | "
                f"{stats.get('win_rate', 0)*100:.2f}% | ${stats.get('avg_pnl', 0):.4f} | "
                f"{stats.get('avg_hold_sec', 0):.2f}s |"
            )
        report.append("")
    
    # 优化建议
    report.append("## 5. 交易优化建议")
    report.append("")
    
    total_pnl = metrics.get("total_pnl", 0)
    total_fee = metrics.get("total_fee", 0)
    total_slippage = metrics.get("total_slippage", 0)
    win_rate = metrics.get("win_rate", 0)
    sharpe = metrics.get("sharpe_ratio", 0)
    
    suggestions = []
    
    if total_pnl < 0:
        suggestions.append({
            "title": "总体亏损优化",
            "priority": "高",
            "problem": f"总体PnL为负（${total_pnl:.2f}），费用和滑点成本较高（${total_fee + total_slippage:.2f}）",
            "suggestions": [
                "提高信号阈值（buy/sell阈值），只交易高质量信号",
                "启用maker/taker费用模型，降低交易成本",
                "使用情境化滑点模型，根据市场条件调整滑点",
                "增加一致性检查，过滤低质量信号"
            ],
            "expected_impact": "可能减少交易频率，但提高单笔交易质量，降低总体亏损"
        })
    
    if win_rate < 0.5:
        suggestions.append({
            "title": "胜率优化",
            "priority": "高",
            "problem": f"胜率较低（{win_rate*100:.2f}%），需要提高信号质量",
            "suggestions": [
                "提高信号阈值：buy阈值从0.5提高到0.7，sell阈值从-0.5降低到-0.7",
                "增加一致性要求：consistency_min从0.15提高到0.25",
                "优化融合权重：尝试调整w_ofi和w_cvd的比例",
                "启用止盈止损：设置take_profit_bps和stop_loss_bps"
            ],
            "expected_impact": "可能提高胜率，但可能减少交易频率"
        })
    
    if sharpe < 0:
        suggestions.append({
            "title": "风险调整收益优化",
            "priority": "中",
            "problem": f"Sharpe比率为负（{sharpe:.4f}），风险调整后的收益不理想",
            "suggestions": [
                "优化仓位管理：降低notional_per_trade，控制单笔交易风险",
                "提高信号质量：只交易强信号（strong_buy/strong_sell）",
                "优化出场策略：及时止损，让盈利交易持有更久",
                "减少交易频率：提高入场阈值，减少无效交易"
            ],
            "expected_impact": "可能提高风险调整后的收益，改善Sharpe比率"
        })
    
    if total_fee + total_slippage > abs(total_pnl) * 0.3:
        suggestions.append({
            "title": "成本优化",
            "priority": "中",
            "problem": f"费用和滑点成本较高（费用${total_fee:.2f}，滑点${total_slippage:.2f}），占总PnL比例较高",
            "suggestions": [
                "启用maker/taker费用模型：在backtest.yaml中设置fee_model: maker_taker",
                "使用情境化滑点：设置slippage_model: piecewise",
                "减少交易频率：提高信号阈值，只交易高质量信号",
                "优化交易时机：避免在spread较大时交易"
            ],
            "expected_impact": "可能降低交易成本，提高净收益"
        })
    
    # 检查场景表现
    if scenario_breakdown:
        worst_scenario = min(scenario_breakdown.items(), key=lambda x: x[1].get("pnl", 0))
        if worst_scenario[1].get("pnl", 0) < 0:
            suggestions.append({
                "title": "场景过滤优化",
                "priority": "低",
                "problem": f"场景{worst_scenario[0]}表现较差（PnL: ${worst_scenario[1].get('pnl', 0):.2f}）",
                "suggestions": [
                    f"考虑在特定场景（{worst_scenario[0]}）下提高信号阈值",
                    "分析该场景的特征，优化策略参数",
                    "考虑排除该场景的交易"
                ],
                "expected_impact": "可能减少亏损交易，提高整体表现"
            })
    
    for i, suggestion in enumerate(suggestions, 1):
        report.append(f"### 建议 {i}: {suggestion['title']} (优先级: {suggestion['priority']})")
        report.append("")
        report.append(f"**问题**: {suggestion['problem']}")
        report.append("")
        report.append("**建议措施**:")
        for j, sug in enumerate(suggestion['suggestions'], 1):
            report.append(f"{j}. {sug}")
        report.append("")
        report.append(f"**预期影响**: {suggestion['expected_impact']}")
        report.append("")
    
    # 参数优化建议
    report.append("## 6. 参数优化建议")
    report.append("")
    report.append("### 推荐配置调整")
    report.append("")
    report.append("```yaml")
    report.append("# config/backtest.yaml 推荐调整")
    report.append("")
    report.append("backtest:")
    report.append("  # 启用maker/taker费用模型，降低交易成本")
    report.append("  fee_model: maker_taker")
    report.append("  # 使用情境化滑点")
    report.append("  slippage_model: piecewise")
    report.append("  # 设置止盈止损")
    report.append("  take_profit_bps: 50  # 50 bps止盈")
    report.append("  stop_loss_bps: 30    # 30 bps止损")
    report.append("")
    report.append("strategy:")
    report.append("  # 提高入场阈值，只交易高质量信号")
    report.append("  entry_threshold: 0.3")
    report.append("  # 设置出场阈值")
    report.append("  exit_threshold: 0.1")
    report.append("")
    report.append("signal:")
    report.append("  # 提高一致性要求")
    report.append("  consistency_min: 0.25")
    report.append("  # 提高弱信号阈值")
    report.append("  weak_signal_threshold: 0.3")
    report.append("```")
    report.append("")
    
    # 保存报告
    output_file = backtest_dir / "detailed_backtest_report.md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    
    print(f"详细报告已保存: {output_file}")
    return 0

if __name__ == "__main__":
    sys.exit(main())

