#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析回测结果并生成详细报告"""
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

def load_jsonl(file_path: Path) -> List[Dict[str, Any]]:
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
                except json.JSONDecodeError:
                    continue
    return data

def analyze_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """分析交易数据"""
    if not trades:
        return {}
    
    # 按交易对分组
    trades_by_symbol = defaultdict(list)
    for trade in trades:
        symbol = trade.get("symbol", "UNKNOWN")
        trades_by_symbol[symbol].append(trade)
    
    # 统计每个交易对
    symbol_stats = {}
    for symbol, symbol_trades in trades_by_symbol.items():
        total_pnl = sum(t.get("pnl", 0) for t in symbol_trades)
        total_fee = sum(t.get("fee", 0) for t in symbol_trades)
        total_slippage = sum(t.get("slippage", 0) for t in symbol_trades)
        
        wins = [t for t in symbol_trades if t.get("pnl", 0) > 0]
        losses = [t for t in symbol_trades if t.get("pnl", 0) < 0]
        
        win_rate = len(wins) / len(symbol_trades) if symbol_trades else 0
        
        avg_pnl = total_pnl / len(symbol_trades) if symbol_trades else 0
        avg_win = sum(t.get("pnl", 0) for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.get("pnl", 0) for t in losses) / len(losses) if losses else 0
        
        risk_reward = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        # 持有时长统计
        hold_times = [t.get("hold_time_sec", 0) for t in symbol_trades if t.get("hold_time_sec")]
        avg_hold_time = sum(hold_times) / len(hold_times) if hold_times else 0
        
        symbol_stats[symbol] = {
            "total_trades": len(symbol_trades),
            "total_pnl": total_pnl,
            "total_fee": total_fee,
            "total_slippage": total_slippage,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "risk_reward_ratio": risk_reward,
            "avg_hold_time_sec": avg_hold_time,
        }
    
    # 总体统计
    total_trades = len(trades)
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    total_fee = sum(t.get("fee", 0) for t in trades)
    total_slippage = sum(t.get("slippage", 0) for t in trades)
    
    all_wins = [t for t in trades if t.get("pnl", 0) > 0]
    all_losses = [t for t in trades if t.get("pnl", 0) < 0]
    
    overall_win_rate = len(all_wins) / total_trades if total_trades else 0
    
    return {
        "overall": {
            "total_trades": total_trades,
            "total_pnl": total_pnl,
            "total_fee": total_fee,
            "total_slippage": total_slippage,
            "net_pnl": total_pnl - total_fee - total_slippage,
            "wins": len(all_wins),
            "losses": len(all_losses),
            "win_rate": overall_win_rate,
        },
        "by_symbol": symbol_stats,
    }

def analyze_daily_pnl(pnl_daily: List[Dict[str, Any]]) -> Dict[str, Any]:
    """分析日频PnL"""
    if not pnl_daily:
        return {}
    
    daily_pnls = [p.get("pnl", 0) for p in pnl_daily]
    cumulative_pnl = []
    cumsum = 0
    for pnl in daily_pnls:
        cumsum += pnl
        cumulative_pnl.append(cumsum)
    
    # 计算最大回撤
    max_drawdown = 0
    peak = 0
    for cum_pnl in cumulative_pnl:
        if cum_pnl > peak:
            peak = cum_pnl
        drawdown = peak - cum_pnl
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    return {
        "daily_pnl": daily_pnls,
        "cumulative_pnl": cumulative_pnl,
        "max_drawdown": max_drawdown,
        "total_days": len(pnl_daily),
    }

def generate_report(backtest_dir: Path, output_file: Path):
    """生成分析报告"""
    # 查找实际结果目录
    subdirs = list(backtest_dir.glob("backtest_*"))
    if not subdirs:
        logger.error("未找到回测结果目录")
        return
    
    result_dir = subdirs[0]
    
    # 加载数据
    logger.info(f"加载回测结果: {result_dir}")
    
    trades = load_jsonl(result_dir / "trades.jsonl")
    pnl_daily = load_jsonl(result_dir / "pnl_daily.jsonl")
    
    with open(result_dir / "metrics.json", "r", encoding="utf-8") as f:
        metrics = json.load(f)
    
    with open(result_dir / "run_manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    # 加载回测信息
    backtest_info_file = backtest_dir / "backtest_info.json"
    backtest_info = {}
    if backtest_info_file.exists():
        with open(backtest_info_file, "r", encoding="utf-8") as f:
            backtest_info = json.load(f)
    
    # 分析交易
    trade_analysis = analyze_trades(trades)
    pnl_analysis = analyze_daily_pnl(pnl_daily)
    
    # 生成报告
    report = {
        "backtest_info": backtest_info,
        "config": manifest.get("config", {}),
        "metrics": metrics,
        "trade_analysis": trade_analysis,
        "pnl_analysis": pnl_analysis,
        "timestamp": datetime.now().isoformat(),
    }
    
    # 保存JSON报告
    json_file = output_file.with_suffix(".json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    logger.info(f"JSON报告已保存: {json_file}")
    
    # 生成Markdown报告
    md_content = generate_markdown_report(report)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    logger.info(f"Markdown报告已保存: {output_file}")
    
    return report

def generate_markdown_report(report: Dict[str, Any]) -> str:
    """生成Markdown格式的报告"""
    backtest_info = report.get("backtest_info", {})
    config = report.get("config", {})
    metrics = report.get("metrics", {})
    trade_analysis = report.get("trade_analysis", {})
    pnl_analysis = report.get("pnl_analysis", {})
    
    md = []
    md.append("# 6交易对24小时回测分析报告")
    md.append("")
    md.append(f"**生成时间**: {report.get('timestamp', 'N/A')}")
    md.append("")
    
    # 回测参数
    md.append("## 1. 回测参数")
    md.append("")
    md.append("### 基本信息")
    md.append(f"- **回测日期**: {backtest_info.get('date', 'N/A')}")
    md.append(f"- **交易对**: {', '.join(backtest_info.get('symbols', []))}")
    md.append(f"- **回测时长**: {backtest_info.get('duration_hours', 24)} 小时")
    md.append("")
    
    # 配置参数
    md.append("### 配置参数")
    backtest_config = config.get("backtest", {})
    md.append(f"- **费率模型**: {backtest_config.get('fee_model', 'N/A')}")
    md.append(f"- **滑点模型**: {backtest_config.get('slippage_model', 'N/A')}")
    md.append(f"- **Taker费率**: {backtest_config.get('taker_fee_bps', 0)} bps")
    md.append(f"- **滑点**: {backtest_config.get('slippage_bps', 0)} bps")
    md.append(f"- **每笔交易名义价值**: ${backtest_config.get('notional_per_trade', 0):.2f}")
    md.append(f"- **忽略闸门**: {backtest_config.get('ignore_gating_in_backtest', False)}")
    md.append("")
    
    signal_config = config.get("signal", {})
    md.append("### 信号配置")
    md.append(f"- **信号输出**: {signal_config.get('sink', 'N/A')}")
    md.append(f"- **回放模式**: {signal_config.get('replay_mode', 'N/A')}")
    md.append("")
    
    strategy_config = config.get("strategy", {})
    md.append("### 策略配置")
    md.append(f"- **模式**: {strategy_config.get('mode', 'N/A')}")
    md.append(f"- **方向**: {strategy_config.get('direction', 'N/A')}")
    md.append(f"- **入场阈值**: {strategy_config.get('entry_threshold', 0)}")
    md.append(f"- **出场阈值**: {strategy_config.get('exit_threshold', 0)}")
    md.append("")
    
    # 总体表现
    md.append("## 2. 总体表现")
    md.append("")
    overall = trade_analysis.get("overall", {})
    md.append(f"- **总交易数**: {overall.get('total_trades', 0)}")
    md.append(f"- **总PnL**: ${overall.get('total_pnl', 0):.2f}")
    md.append(f"- **总费用**: ${overall.get('total_fee', 0):.2f}")
    md.append(f"- **总滑点**: ${overall.get('total_slippage', 0):.2f}")
    md.append(f"- **净PnL**: ${overall.get('net_pnl', 0):.2f}")
    md.append(f"- **胜率**: {overall.get('win_rate', 0)*100:.2f}%")
    md.append(f"- **盈利交易**: {overall.get('wins', 0)}")
    md.append(f"- **亏损交易**: {overall.get('losses', 0)}")
    md.append("")
    
    # 性能指标
    md.append("### 性能指标")
    md.append(f"- **Sharpe比率**: {metrics.get('sharpe_ratio', 0):.4f}")
    md.append(f"- **Sortino比率**: {metrics.get('sortino_ratio', 0):.4f}")
    md.append(f"- **最大回撤**: {metrics.get('max_drawdown', 0):.2f} bps")
    md.append(f"- **MAR比率**: {metrics.get('MAR', 0):.4f}")
    md.append(f"- **盈亏比**: {metrics.get('risk_reward_ratio', 0):.4f}")
    md.append(f"- **平均持有时长**: {metrics.get('avg_hold_sec', 0):.2f} 秒")
    md.append("")
    
    # 按交易对分析
    md.append("## 3. 按交易对分析")
    md.append("")
    by_symbol = trade_analysis.get("by_symbol", {})
    
    # 按PnL排序
    sorted_symbols = sorted(by_symbol.items(), key=lambda x: x[1].get("total_pnl", 0), reverse=True)
    
    md.append("| 交易对 | 交易数 | 总PnL | 费用 | 滑点 | 胜率 | 盈亏比 | 平均持有时长 |")
    md.append("|--------|--------|-------|------|------|------|--------|--------------|")
    
    for symbol, stats in sorted_symbols:
        md.append(
            f"| {symbol} | {stats.get('total_trades', 0)} | "
            f"${stats.get('total_pnl', 0):.2f} | ${stats.get('total_fee', 0):.2f} | "
            f"${stats.get('total_slippage', 0):.2f} | {stats.get('win_rate', 0)*100:.2f}% | "
            f"{stats.get('risk_reward_ratio', 0):.4f} | {stats.get('avg_hold_time_sec', 0):.2f}s |"
        )
    
    md.append("")
    
    # 回撤分析
    md.append("## 4. 回撤分析")
    md.append("")
    if pnl_analysis:
        md.append(f"- **最大回撤**: ${pnl_analysis.get('max_drawdown', 0):.2f}")
        md.append(f"- **回测天数**: {pnl_analysis.get('total_days', 0)}")
        md.append("")
    
    # 优化建议
    md.append("## 5. 交易优化建议")
    md.append("")
    
    suggestions = generate_optimization_suggestions(report)
    for i, suggestion in enumerate(suggestions, 1):
        md.append(f"### 建议 {i}: {suggestion['title']}")
        md.append("")
        md.append(f"**问题**: {suggestion['problem']}")
        md.append("")
        md.append(f"**建议**: {suggestion['suggestion']}")
        md.append("")
        if suggestion.get('impact'):
            md.append(f"**预期影响**: {suggestion['impact']}")
            md.append("")
    
    return "\n".join(md)

def generate_optimization_suggestions(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """生成优化建议"""
    suggestions = []
    
    overall = report.get("trade_analysis", {}).get("overall", {})
    metrics = report.get("metrics", {})
    by_symbol = report.get("trade_analysis", {}).get("by_symbol", {})
    
    # 检查总体PnL
    total_pnl = overall.get("total_pnl", 0)
    if total_pnl < 0:
        suggestions.append({
            "title": "总体亏损优化",
            "problem": f"总体PnL为负（${total_pnl:.2f}），需要优化策略或参数",
            "suggestion": "1. 检查信号阈值是否过高，导致错过盈利机会\n2. 考虑调整费率模型或滑点模型\n3. 分析亏损交易的特征，优化入场/出场条件",
            "impact": "可能提升整体盈利能力"
        })
    
    # 检查胜率
    win_rate = overall.get("win_rate", 0)
    if win_rate < 0.5:
        suggestions.append({
            "title": "胜率优化",
            "problem": f"胜率较低（{win_rate*100:.2f}%），需要提高信号质量",
            "suggestion": "1. 提高信号阈值，只交易高质量信号\n2. 增加一致性检查，过滤低质量信号\n3. 优化融合权重（w_ofi, w_cvd）",
            "impact": "可能提高胜率，但可能减少交易频率"
        })
    
    # 检查盈亏比
    risk_reward = metrics.get("risk_reward_ratio", 0)
    if risk_reward < 1.0:
        suggestions.append({
            "title": "盈亏比优化",
            "problem": f"盈亏比小于1（{risk_reward:.4f}），平均亏损大于平均盈利",
            "suggestion": "1. 优化止盈/止损策略\n2. 提高出场阈值，让盈利交易持有更久\n3. 降低入场阈值，但提高一致性要求",
            "impact": "可能提高盈亏比，改善整体收益"
        })
    
    # 检查费用和滑点
    total_fee = overall.get("total_fee", 0)
    total_slippage = overall.get("total_slippage", 0)
    if total_fee + total_slippage > abs(total_pnl) * 0.3:
        suggestions.append({
            "title": "成本优化",
            "problem": f"费用和滑点占总PnL比例较高（费用${total_fee:.2f}，滑点${total_slippage:.2f}）",
            "suggestion": "1. 考虑使用maker/taker费用模型，降低费用\n2. 优化滑点模型，使用情境化滑点\n3. 减少交易频率，只交易高质量信号",
            "impact": "可能降低交易成本，提高净收益"
        })
    
    # 检查交易对表现差异
    if len(by_symbol) > 1:
        pnls = [stats.get("total_pnl", 0) for stats in by_symbol.values()]
        if max(pnls) - min(pnls) > abs(sum(pnls)) * 0.5:
            suggestions.append({
                "title": "交易对选择优化",
                "problem": "不同交易对表现差异较大，部分交易对可能不适合当前策略",
                "suggestion": "1. 分析表现差的交易对特征，考虑排除\n2. 为不同交易对设置不同的参数\n3. 增加交易对特定的信号阈值",
                "impact": "可能提高整体表现，减少亏损交易对的影响"
            })
    
    # 检查Sharpe比率
    sharpe = metrics.get("sharpe_ratio", 0)
    if sharpe < 1.0:
        suggestions.append({
            "title": "风险调整收益优化",
            "problem": f"Sharpe比率较低（{sharpe:.4f}），风险调整后的收益不理想",
            "suggestion": "1. 优化仓位管理，控制单笔交易风险\n2. 提高信号质量，减少无效交易\n3. 优化出场策略，及时止损",
            "impact": "可能提高风险调整后的收益"
        })
    
    return suggestions

def main():
    """主函数"""
    if len(sys.argv) < 2:
        logger.error("用法: python analyze_backtest_results.py <backtest_dir>")
        return 1
    
    backtest_dir = Path(sys.argv[1])
    if not backtest_dir.exists():
        logger.error(f"回测目录不存在: {backtest_dir}")
        return 1
    
    output_file = backtest_dir / "backtest_analysis_report.md"
    
    logger.info(f"分析回测结果: {backtest_dir}")
    logger.info(f"输出报告: {output_file}")
    
    report = generate_report(backtest_dir, output_file)
    
    if report:
        logger.info("分析完成")
        return 0
    else:
        logger.error("分析失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())

