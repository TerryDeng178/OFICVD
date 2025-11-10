# -*- coding: utf-8 -*-
"""A/B组对比脚本：对比A组（shadow）和B组（当前配置）"""
import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_metrics(metrics_file: Path) -> Dict[str, Any]:
    """加载metrics.json"""
    try:
        with open(metrics_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {metrics_file}: {e}")
        return {}


def load_gate_breakdown(breakdown_file: Path) -> Dict[str, int]:
    """加载gate_reason_breakdown.json"""
    try:
        with open(breakdown_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Error loading {breakdown_file}: {e}")
        return {}


def compare_ab_groups(
    group_a_dir: Path,
    group_b_dir: Path,
    output_report: Path
) -> None:
    """对比A组和B组"""
    # 查找最新的backtest目录
    a_backtest_dirs = list(group_a_dir.glob("backtest_*"))
    b_backtest_dirs = list(group_b_dir.glob("backtest_*"))
    
    if not a_backtest_dirs:
        logger.error(f"No backtest directories found in {group_a_dir}")
        return
    
    if not b_backtest_dirs:
        logger.error(f"No backtest directories found in {group_b_dir}")
        return
    
    a_backtest_dir = max(a_backtest_dirs, key=lambda p: p.stat().st_mtime)
    b_backtest_dir = max(b_backtest_dirs, key=lambda p: p.stat().st_mtime)
    
    logger.info(f"A组目录: {a_backtest_dir}")
    logger.info(f"B组目录: {b_backtest_dir}")
    
    # 加载metrics
    a_metrics = load_metrics(a_backtest_dir / "metrics.json")
    b_metrics = load_metrics(b_backtest_dir / "metrics.json")
    
    # 加载gate breakdown
    a_gate_breakdown = load_gate_breakdown(a_backtest_dir / "gate_reason_breakdown.json")
    b_gate_breakdown = load_gate_breakdown(b_backtest_dir / "gate_reason_breakdown.json")
    
    # 计算关键指标
    a_total_trades = a_metrics.get("total_trades", 0)
    b_total_trades = b_metrics.get("total_trades", 0)
    
    a_total_pnl = a_metrics.get("total_pnl", 0)
    b_total_pnl = b_metrics.get("total_pnl", 0)
    
    a_total_fee = a_metrics.get("total_fee", 0)
    b_total_fee = b_metrics.get("total_fee", 0)
    
    a_total_slippage = a_metrics.get("total_slippage", 0)
    b_total_slippage = b_metrics.get("total_slippage", 0)
    
    a_net_pnl = a_total_pnl - a_total_fee - a_total_slippage
    b_net_pnl = b_total_pnl - b_total_fee - b_total_slippage
    
    a_pnl_per_trade = a_net_pnl / a_total_trades if a_total_trades > 0 else 0
    b_pnl_per_trade = b_net_pnl / b_total_trades if b_total_trades > 0 else 0
    
    a_win_rate = a_metrics.get("win_rate_trades", 0)
    b_win_rate = b_metrics.get("win_rate_trades", 0)
    
    a_avg_hold_sec = a_metrics.get("avg_hold_sec", 0)
    b_avg_hold_sec = b_metrics.get("avg_hold_sec", 0)
    
    a_trades_per_hour = a_total_trades / 0.25  # 15分钟 = 0.25小时
    b_trades_per_hour = b_total_trades / 0.25
    
    a_cost_bps = a_metrics.get("cost_bps_on_turnover", 0)
    b_cost_bps = b_metrics.get("cost_bps_on_turnover", 0)
    
    # 生成对比报告
    md_content = f"""# A/B组对比报告

**生成时间**: {Path(__file__).stat().st_mtime}  
**A组目录**: {a_backtest_dir}  
**B组目录**: {b_backtest_dir}

## 关键指标对比

| 指标 | A组（Shadow） | B组（当前配置） | 差异 | 状态 |
|------|---------------|-----------------|------|------|
| **总交易数** | {a_total_trades} | {b_total_trades} | {a_total_trades - b_total_trades:+d} | {'✅ A组更多' if a_total_trades > b_total_trades else '✅ B组更多' if b_total_trades > a_total_trades else '➡️ 相同'} |
| **交易频率** | {a_trades_per_hour:.1f}笔/小时 | {b_trades_per_hour:.1f}笔/小时 | {a_trades_per_hour - b_trades_per_hour:+.1f} | - |
| **平均持仓** | {a_avg_hold_sec:.1f}秒 | {b_avg_hold_sec:.1f}秒 | {a_avg_hold_sec - b_avg_hold_sec:+.1f} | - |
| **单笔收益** | ${a_pnl_per_trade:.2f} | ${b_pnl_per_trade:.2f} | ${a_pnl_per_trade - b_pnl_per_trade:+.2f} | {'✅ A组更好' if a_pnl_per_trade > b_pnl_per_trade else '✅ B组更好' if b_pnl_per_trade > a_pnl_per_trade else '➡️ 相同'} |
| **胜率** | {a_win_rate:.2%} | {b_win_rate:.2%} | {a_win_rate - b_win_rate:+.2%} | {'✅ A组更高' if a_win_rate > b_win_rate else '✅ B组更高' if b_win_rate > a_win_rate else '➡️ 相同'} |
| **成本bps** | {a_cost_bps:.2f}bps | {b_cost_bps:.2f}bps | {a_cost_bps - b_cost_bps:+.2f} | {'✅ A组更低' if a_cost_bps < b_cost_bps else '✅ B组更低' if b_cost_bps < a_cost_bps else '➡️ 相同'} |
| **净收益** | ${a_net_pnl:.2f} | ${b_net_pnl:.2f} | ${a_net_pnl - b_net_pnl:+.2f} | {'✅ A组更好' if a_net_pnl > b_net_pnl else '✅ B组更好' if b_net_pnl > a_net_pnl else '➡️ 相同'} |

## Gate原因对比

### A组（Shadow）Top-5原因

"""
    
    if a_gate_breakdown:
        sorted_a_reasons = sorted(a_gate_breakdown.items(), key=lambda x: x[1], reverse=True)
        total_a_blocked = sum(a_gate_breakdown.values())
        
        for i, (reason, count) in enumerate(sorted_a_reasons[:5], 1):
            percentage = count / total_a_blocked * 100 if total_a_blocked > 0 else 0
            md_content += f"{i}. **{reason}**: {count}次 ({percentage:.2f}%)\n"
    else:
        md_content += "无数据\n"
    
    md_content += "\n### B组（当前配置）Top-5原因\n\n"
    
    if b_gate_breakdown:
        sorted_b_reasons = sorted(b_gate_breakdown.items(), key=lambda x: x[1], reverse=True)
        total_b_blocked = sum(b_gate_breakdown.values())
        
        for i, (reason, count) in enumerate(sorted_b_reasons[:5], 1):
            percentage = count / total_b_blocked * 100 if total_b_blocked > 0 else 0
            md_content += f"{i}. **{reason}**: {count}次 ({percentage:.2f}%)\n"
    else:
        md_content += "无数据\n"
    
    md_content += "\n## 主因门检查\n\n"
    
    if a_gate_breakdown and b_gate_breakdown:
        a_top_reason = max(a_gate_breakdown.items(), key=lambda x: x[1])
        b_top_reason = max(b_gate_breakdown.items(), key=lambda x: x[1])
        
        total_a_blocked = sum(a_gate_breakdown.values())
        total_b_blocked = sum(b_gate_breakdown.values())
        
        a_top_percentage = a_top_reason[1] / total_a_blocked * 100 if total_a_blocked > 0 else 0
        b_top_percentage = b_top_reason[1] / total_b_blocked * 100 if total_b_blocked > 0 else 0
        
        md_content += f"### A组\n"
        md_content += f"- **Top-1原因**: {a_top_reason[0]}\n"
        md_content += f"- **占比**: {a_top_percentage:.2f}%\n"
        if a_top_percentage >= 60:
            md_content += f"- **状态**: ⚠️ 警告（≥60%）\n"
        else:
            md_content += f"- **状态**: ✅ 通过（<60%）\n"
        
        md_content += f"\n### B组\n"
        md_content += f"- **Top-1原因**: {b_top_reason[0]}\n"
        md_content += f"- **占比**: {b_top_percentage:.2f}%\n"
        if b_top_percentage >= 60:
            md_content += f"- **状态**: ⚠️ 警告（≥60%）\n"
        else:
            md_content += f"- **状态**: ✅ 通过（<60%）\n"
    
    md_content += "\n## 结论\n\n"
    
    # 判断是否有显著差异
    if abs(a_total_trades - b_total_trades) / max(a_total_trades, b_total_trades, 1) > 0.1:
        md_content += "- ✅ **交易频率有显著差异**：A组和B组的交易频率差异 > 10%\n"
    else:
        md_content += "- ➡️ **交易频率差异较小**：A组和B组的交易频率差异 < 10%\n"
    
    if abs(a_pnl_per_trade - b_pnl_per_trade) > 0.1:
        md_content += "- ✅ **单笔收益有显著差异**：A组和B组的单笔收益差异 > $0.10\n"
    else:
        md_content += "- ➡️ **单笔收益差异较小**：A组和B组的单笔收益差异 < $0.10\n"
    
    if abs(a_win_rate - b_win_rate) > 0.05:
        md_content += "- ✅ **胜率有显著差异**：A组和B组的胜率差异 > 5%\n"
    else:
        md_content += "- ➡️ **胜率差异较小**：A组和B组的胜率差异 < 5%\n"
    
    output_report.parent.mkdir(parents=True, exist_ok=True)
    with open(output_report, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    logger.info(f"AB comparison report saved to {output_report}")


def main():
    parser = argparse.ArgumentParser(description="A/B组对比脚本")
    parser.add_argument("--group-a", type=str, required=True, help="A组结果目录")
    parser.add_argument("--group-b", type=str, required=True, help="B组结果目录")
    parser.add_argument("--out", type=str, default="./runtime/reports/ab_summary.md", help="输出报告路径")
    
    args = parser.parse_args()
    
    group_a_dir = Path(args.group_a)
    group_b_dir = Path(args.group_b)
    
    if not group_a_dir.exists():
        logger.error(f"Group A directory not found: {group_a_dir}")
        return 1
    
    if not group_b_dir.exists():
        logger.error(f"Group B directory not found: {group_b_dir}")
        return 1
    
    compare_ab_groups(group_a_dir, group_b_dir, Path(args.out))
    
    return 0


if __name__ == "__main__":
    exit(main())

