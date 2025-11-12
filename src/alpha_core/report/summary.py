# -*- coding: utf-8 -*-
"""TASK-09: 复盘报表生成器"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import matplotlib
    matplotlib.use("Agg")  # 非交互式后端
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    plt = None
    mdates = None

logger = logging.getLogger(__name__)

# Fix 3: 统一PnL口径 - 原子口径使用gross_pnl
def _extract_gross_pnl(trade: Dict[str, Any]) -> float:
    """提取gross_pnl（不含费用和滑点）
    
    如果trade中有net_pnl，需要回推gross_pnl = net_pnl + fee + slippage_cost
    """
    gross_pnl = trade.get("gross_pnl")
    if gross_pnl is not None:
        return gross_pnl
    
    # 如果只有net_pnl，回推gross_pnl
    net_pnl = trade.get("net_pnl")
    if net_pnl is not None:
        fee = trade.get("fee", 0)
        slippage_bps = abs(trade.get("slippage_bps", 0))
        notional = trade.get("notional", 1000)
        slippage_cost = slippage_bps * notional / 10000
        return net_pnl + fee + slippage_cost
    
    return 0.0

def _extract_slippage_cost(trade: Dict[str, Any]) -> float:
    """提取滑点成本（正数）
    
    改进：智能回退名义本金
    1. 优先使用trade["notional"]
    2. 没有则用abs(qty) * px（或entry_px）
    3. 再不行才回退小额默认值，并标记为估算
    """
    slippage_bps = abs(trade.get("slippage_bps", 0.0))
    if slippage_bps == 0:
        return 0.0
    
    notional = trade.get("notional")
    if notional is None or notional == 0:
        # 尝试从qty和px计算
        qty = abs(trade.get("qty", 0.0))
        px = trade.get("px") or trade.get("price") or trade.get("entry_px", 0.0)
        if qty and px:
            notional = qty * px
        else:
            # 更保守的小额默认值
            notional = 200.0
            # 标记为估算（用于后续metrics标记）
            trade["_slip_notional_estimated"] = True
    
    return slippage_bps * notional / 10000.0

# Fix 5: 场景标准化 - 仅接受{A_H,A_L,Q_H,Q_L}，其他标为unknown
VALID_SCENARIOS = {"A_H", "A_L", "Q_H", "Q_L"}

def _normalize_scenario(scenario: Optional[str]) -> str:
    """标准化场景名称"""
    if not scenario:
        return "unknown"
    
    # 处理格式如"A_H_unknown"的情况
    if "_" in scenario:
        parts = scenario.split("_")
        if len(parts) >= 2:
            normalized = parts[0] + "_" + parts[1]
            if normalized in VALID_SCENARIOS:
                return normalized
    
    # 直接检查是否有效
    if scenario in VALID_SCENARIOS:
        return scenario
    
    return "unknown"

class ReportGenerator:
    """复盘报表生成器
    
    功能：
    - 按时段/场景/交易对分组统计
    - 成本分解（费用maker/taker、滑点bps→$）
    - 生成Markdown报告和图表
    - 输出metrics.json
    """
    
    def __init__(self, backtest_dir: Path, output_dir: Optional[Path] = None):
        """
        Args:
            backtest_dir: 回测结果目录（包含backtest_*子目录）
            output_dir: 报表输出目录（默认：reports/daily/YYYYMMDD/）
        """
        self.backtest_dir = Path(backtest_dir)
        
        # Fix 4: 选择最后修改时间最大的子目录（避免误选旧结果）
        subdirs = list(self.backtest_dir.glob("backtest_*"))
        if not subdirs:
            raise ValueError(f"未找到回测结果目录: {self.backtest_dir}")
        # 按修改时间排序，选择最新的
        subdirs = sorted(subdirs, key=lambda p: p.stat().st_mtime, reverse=True)
        self.result_dir = subdirs[0]
        
        # 设置输出目录
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            # 默认：reports/daily/YYYYMMDD/
            run_id = self.result_dir.name
            date_str = run_id.split("_")[1] if "_" in run_id else datetime.now().strftime("%Y%m%d")
            self.output_dir = Path(f"reports/daily/{date_str}")
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"[ReportGenerator] 回测目录: {self.result_dir}")
        logger.info(f"[ReportGenerator] 输出目录: {self.output_dir}")
    
    def load_data(self) -> Dict[str, Any]:
        """加载回测数据"""
        logger.info("[ReportGenerator] 加载回测数据...")
        
        data = {}
        
        # 加载trades.jsonl
        trades_file = self.result_dir / "trades.jsonl"
        if trades_file.exists():
            data["trades"] = self._load_jsonl(trades_file)
            logger.info(f"  加载交易数据: {len(data['trades'])} 笔")
        else:
            data["trades"] = []
            logger.warning("  未找到trades.jsonl")
        
        # 加载pnl_daily.jsonl
        pnl_daily_file = self.result_dir / "pnl_daily.jsonl"
        if pnl_daily_file.exists():
            data["pnl_daily"] = self._load_jsonl(pnl_daily_file)
            logger.info(f"  加载日频PnL: {len(data['pnl_daily'])} 条")
        else:
            data["pnl_daily"] = []
            logger.warning("  未找到pnl_daily.jsonl")
        
        # 加载metrics.json
        metrics_file = self.result_dir / "metrics.json"
        if metrics_file.exists():
            with open(metrics_file, "r", encoding="utf-8") as f:
                data["metrics"] = json.load(f)
            logger.info("  加载metrics.json")
        else:
            data["metrics"] = {}
            logger.warning("  未找到metrics.json")
        
        # 加载run_manifest.json
        manifest_file = self.result_dir / "run_manifest.json"
        if manifest_file.exists():
            with open(manifest_file, "r", encoding="utf-8") as f:
                data["manifest"] = json.load(f)
            logger.info("  加载run_manifest.json")
        else:
            data["manifest"] = {}
            logger.warning("  未找到run_manifest.json")
        
        return data
    
    def _load_jsonl(self, file_path: Path) -> List[Dict[str, Any]]:
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
    
    def analyze_by_hour(self, trades: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        """按时段（UTC小时）分析"""
        by_hour = defaultdict(lambda: {
            "trades": [],
            "pnl": 0.0,
            "fee": 0.0,
            "slippage": 0.0,
            "wins": 0,
            "losses": 0,
        })
        
        for trade in trades:
            ts_ms = trade.get("ts_ms", 0)
            if ts_ms:
                dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                hour = dt.hour
                
                by_hour[hour]["trades"].append(trade)
                # Fix 3: 统一使用gross_pnl进行统计
                gross_pnl = _extract_gross_pnl(trade)
                by_hour[hour]["pnl"] += gross_pnl
                by_hour[hour]["fee"] += trade.get("fee", 0)
                by_hour[hour]["slippage"] += _extract_slippage_cost(trade)
                
                # Fix 3: 使用gross_pnl判断盈亏
                if gross_pnl > 0:
                    by_hour[hour]["wins"] += 1
                elif gross_pnl < 0:
                    by_hour[hour]["losses"] += 1
        
        # 计算统计指标
        result = {}
        for hour in range(24):
            stats = by_hour[hour]
            total_trades = len(stats["trades"])
            win_rate = stats["wins"] / total_trades if total_trades > 0 else 0
            
            # 平均持有时长
            hold_times = [t.get("hold_time_sec", 0) for t in stats["trades"] if t.get("hold_time_sec", 0) > 0]
            avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0
            
            # Fix 3: 计算净PnL = 总gross_pnl - 费用 - 滑点
            pnl_gross = stats["pnl"]
            pnl_net = pnl_gross - stats["fee"] - stats["slippage"]
            
            # 计算每笔平均PnL
            avg_pnl_per_trade = pnl_net / total_trades if total_trades > 0 else 0
            
            result[hour] = {
                "count": total_trades,
                "pnl_gross": pnl_gross,
                "pnl_net": pnl_net,
                "fee": stats["fee"],
                "slippage": stats["slippage"],
                "win_rate": win_rate,
                "avg_hold_sec": avg_hold,
                "avg_pnl_per_trade": avg_pnl_per_trade,  # 新增：每笔平均PnL
            }
        
        return result
    
    def analyze_by_scenario(self, trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """按场景分析"""
        by_scenario = defaultdict(lambda: {
            "trades": [],
            "pnl": 0.0,
            "fee": 0.0,
            "slippage": 0.0,
            "wins": 0,
            "losses": 0,
        })
        
        for trade in trades:
            # Fix 5: 场景标准化
            scenario = _normalize_scenario(trade.get("scenario_2x2"))
            
            by_scenario[scenario]["trades"].append(trade)
            # Fix 3: 统一使用gross_pnl进行统计
            gross_pnl = _extract_gross_pnl(trade)
            by_scenario[scenario]["pnl"] += gross_pnl
            by_scenario[scenario]["fee"] += trade.get("fee", 0)
            by_scenario[scenario]["slippage"] += _extract_slippage_cost(trade)
            
            # Fix 3: 使用gross_pnl判断盈亏
            if gross_pnl > 0:
                by_scenario[scenario]["wins"] += 1
            elif gross_pnl < 0:
                by_scenario[scenario]["losses"] += 1
        
        # 计算统计指标
        result = {}
        for scenario, stats in by_scenario.items():
            total_trades = len(stats["trades"])
            win_rate = stats["wins"] / total_trades if total_trades > 0 else 0
            
            # Fix 3: 盈亏比基于gross_pnl计算
            wins_pnl = [_extract_gross_pnl(t) for t in stats["trades"] if _extract_gross_pnl(t) > 0]
            losses_pnl = [_extract_gross_pnl(t) for t in stats["trades"] if _extract_gross_pnl(t) < 0]
            avg_win = sum(wins_pnl) / len(wins_pnl) if wins_pnl else 0
            avg_loss = abs(sum(losses_pnl) / len(losses_pnl)) if losses_pnl else 0
            risk_reward = avg_win / avg_loss if avg_loss > 0 else 0
            
            # Fix 3: 计算净PnL
            pnl_gross = stats["pnl"]
            pnl_net = pnl_gross - stats["fee"] - stats["slippage"]
            
            result[scenario] = {
                "count": total_trades,
                "pnl_gross": pnl_gross,
                "pnl_net": pnl_net,
                "fee": stats["fee"],
                "slippage": stats["slippage"],
                "win_rate": win_rate,
                "risk_reward_ratio": risk_reward,
            }
        
        return result
    
    def analyze_by_symbol(self, trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """按交易对分析"""
        by_symbol = defaultdict(lambda: {
            "trades": [],
            "pnl": 0.0,
            "fee": 0.0,
            "slippage": 0.0,
            "wins": 0,
            "losses": 0,
        })
        
        for trade in trades:
            symbol = trade.get("symbol", "UNKNOWN")
            
            by_symbol[symbol]["trades"].append(trade)
            # Fix 3: 统一使用gross_pnl进行统计
            gross_pnl = _extract_gross_pnl(trade)
            by_symbol[symbol]["pnl"] += gross_pnl
            by_symbol[symbol]["fee"] += trade.get("fee", 0)
            by_symbol[symbol]["slippage"] += _extract_slippage_cost(trade)
            
            # Fix 3: 使用gross_pnl判断盈亏
            if gross_pnl > 0:
                by_symbol[symbol]["wins"] += 1
            elif gross_pnl < 0:
                by_symbol[symbol]["losses"] += 1
        
        # 计算统计指标
        result = {}
        for symbol, stats in by_symbol.items():
            total_trades = len(stats["trades"])
            win_rate = stats["wins"] / total_trades if total_trades > 0 else 0
            
            # Fix 3: 盈亏比基于gross_pnl计算
            wins_pnl = [_extract_gross_pnl(t) for t in stats["trades"] if _extract_gross_pnl(t) > 0]
            losses_pnl = [_extract_gross_pnl(t) for t in stats["trades"] if _extract_gross_pnl(t) < 0]
            avg_win = sum(wins_pnl) / len(wins_pnl) if wins_pnl else 0
            avg_loss = abs(sum(losses_pnl) / len(losses_pnl)) if losses_pnl else 0
            risk_reward = avg_win / avg_loss if avg_loss > 0 else 0
            
            # 平均持有时长
            hold_times = [t.get("hold_time_sec", 0) for t in stats["trades"] if t.get("hold_time_sec", 0) > 0]
            avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0
            
            # Fix 3: 计算净PnL
            pnl_gross = stats["pnl"]
            pnl_net = pnl_gross - stats["fee"] - stats["slippage"]
            
            result[symbol] = {
                "count": total_trades,
                "pnl_gross": pnl_gross,
                "pnl_net": pnl_net,
                "fee": stats["fee"],
                "slippage": stats["slippage"],
                "win_rate": win_rate,
                "risk_reward_ratio": risk_reward,
                "avg_hold_sec": avg_hold,
            }
        
        return result
    
    def analyze_cost_breakdown(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """成本分解分析
        
        A.1改进: 添加成交额口径的成本占比（并行口径）
        - cost_ratio: 基于gross_pnl（单位盈利的成本压力）
        - cost_ratio_notional: 基于成交额（更稳定，避免gross≈0时的抖动）
        """
        # Fix 3: 统一使用gross_pnl计算成本占比
        total_fee = sum(t.get("fee", 0) for t in trades)
        total_slippage = sum(_extract_slippage_cost(t) for t in trades)
        total_gross_pnl = sum(_extract_gross_pnl(t) for t in trades)
        total_net_pnl = total_gross_pnl - total_fee - total_slippage
        
        # A.1: 计算成交额（turnover）
        turnover = sum(
            max(1e-9, t.get("notional") or (abs(t.get("qty", 0)) * abs(t.get("px", 0) or t.get("entry_px", 0)) or 0.0))
            for t in trades
        )
        
        # Maker/Taker费用分解
        maker_turnover = sum(t.get("notional", 1000) for t in trades if t.get("fee_tier", "").upper() in ("MM", "MK"))
        taker_turnover = sum(t.get("notional", 1000) for t in trades if t.get("fee_tier", "").upper() in ("TM", "TT", "TK"))
        
        # Fix 3: 成本占比基于gross_pnl计算（单位盈利的成本压力）
        cost_ratio_pnl = (total_fee + total_slippage) / max(1e-9, abs(total_gross_pnl)) if total_gross_pnl != 0 else 0
        
        # A.1: 成本占比基于成交额计算（更稳定，避免gross≈0时的抖动）
        cost_ratio_notional = (total_fee + total_slippage) / max(1.0, turnover)
        
        return {
            "total_fee": total_fee,
            "total_slippage": total_slippage,
            "total_cost": total_fee + total_slippage,
            "total_gross_pnl": total_gross_pnl,
            "total_net_pnl": total_net_pnl,
            "turnover": turnover,  # A.1: 新增成交额
            "maker_turnover": maker_turnover,
            "taker_turnover": taker_turnover,
            "cost_ratio": cost_ratio_pnl,  # 基于PnL的口径
            "cost_ratio_notional": cost_ratio_notional,  # A.1: 基于成交额的口径（更稳定）
        }
    
    def get_top_trades(self, trades: List[Dict[str, Any]], n: int = 10, top: bool = True) -> List[Dict[str, Any]]:
        """获取TOP N交易（盈利或亏损）"""
        # Fix 3: 使用gross_pnl排序
        sorted_trades = sorted(
            trades,
            key=lambda t: _extract_gross_pnl(t),
            reverse=top
        )
        return sorted_trades[:n]
    
    def generate_report(self) -> Path:
        """生成复盘报表"""
        logger.info("[ReportGenerator] 生成复盘报表...")
        
        # 加载数据
        data = self.load_data()
        trades = data["trades"]
        metrics = data["metrics"]
        manifest = data["manifest"]
        
        if not trades:
            logger.warning("没有交易数据，无法生成报表")
            return None
        
        # 分析
        by_hour = self.analyze_by_hour(trades)
        by_scenario = self.analyze_by_scenario(trades)
        by_symbol = self.analyze_by_symbol(trades)
        cost_breakdown = self.analyze_cost_breakdown(trades)
        
        # 获取TOP交易
        top_wins = self.get_top_trades(trades, n=10, top=True)
        top_losses = self.get_top_trades(trades, n=10, top=False)
        
        # 生成Markdown报告
        run_id = self.result_dir.name
        report_file = self.output_dir / f"{run_id}_summary.md"
        self._generate_markdown(
            report_file,
            trades,
            metrics,
            manifest,
            by_hour,
            by_scenario,
            by_symbol,
            cost_breakdown,
            top_wins,
            top_losses,
        )
        
        # 生成metrics.json
        metrics_file = self.output_dir / f"{run_id}_metrics.json"
        self._generate_metrics_json(
            metrics_file,
            trades,
            metrics,
            by_hour,
            by_scenario,
            by_symbol,
            cost_breakdown,
        )
        
        # 生成图表（C.1/C.2改进：添加净值曲线、回撤曲线、热力图）
        if MATPLOTLIB_AVAILABLE:
            self._generate_charts(trades, by_hour, by_scenario, by_symbol)
        
        logger.info(f"[ReportGenerator] 报表已生成: {report_file}")
        return report_file
    
    def _generate_markdown(
        self,
        output_file: Path,
        trades: List[Dict[str, Any]],
        metrics: Dict[str, Any],
        manifest: Dict[str, Any],
        by_hour: Dict[int, Dict[str, Any]],
        by_scenario: Dict[str, Dict[str, Any]],
        by_symbol: Dict[str, Dict[str, Any]],
        cost_breakdown: Dict[str, Any],
        top_wins: List[Dict[str, Any]],
        top_losses: List[Dict[str, Any]],
    ):
        """生成Markdown报告"""
        run_id = self.result_dir.name
        config = manifest.get("config", {})
        
        md = []
        md.append("# 复盘报表")
        md.append("")
        md.append(f"**生成时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        md.append(f"**回测ID**: {run_id}")
        md.append("")
        
        # 回测参数
        md.append("## 1. 回测参数")
        md.append("")
        backtest_config = config.get("backtest", {})
        md.append("### 回测配置")
        md.append(f"- **费率模型**: {backtest_config.get('fee_model', 'N/A')}")
        md.append(f"- **滑点模型**: {backtest_config.get('slippage_model', 'N/A')}")
        md.append(f"- **Taker费率**: {backtest_config.get('taker_fee_bps', 0)} bps")
        md.append(f"- **滑点**: {backtest_config.get('slippage_bps', 0)} bps")
        md.append(f"- **每笔交易名义价值**: ${backtest_config.get('notional_per_trade', 0):.2f}")
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
        total_trades = len(trades)
        # Fix 3: 统一使用cost_breakdown中的gross/net PnL
        total_gross_pnl = cost_breakdown["total_gross_pnl"]
        total_net_pnl = cost_breakdown["total_net_pnl"]
        total_fee = cost_breakdown["total_fee"]
        total_slippage = cost_breakdown["total_slippage"]
        
        # Fix 3: 基于gross_pnl判断盈亏
        wins = [t for t in trades if _extract_gross_pnl(t) > 0]
        losses = [t for t in trades if _extract_gross_pnl(t) < 0]
        win_rate = len(wins) / total_trades if total_trades > 0 else 0
        
        md.append(f"- **总交易数**: {total_trades:,}")
        md.append(f"- **总PnL（毛）**: ${total_gross_pnl:.2f}")
        md.append(f"- **总费用**: ${total_fee:.2f}")
        md.append(f"- **总滑点**: ${total_slippage:.2f}")
        md.append(f"- **净PnL**: ${total_net_pnl:.2f}")
        md.append(f"- **胜率**: {win_rate*100:.2f}%")
        md.append(f"- **盈利交易**: {len(wins)}")
        md.append(f"- **亏损交易**: {len(losses)}")
        md.append(f"- **成本占比（PnL口径）**: {cost_breakdown['cost_ratio']*100:.2f}%")
        md.append(f"- **成本占比（成交额口径）**: {cost_breakdown.get('cost_ratio_notional', 0)*100:.2f}%")
        md.append(f"- **总成交额**: ${cost_breakdown.get('turnover', 0):,.2f}")
        md.append("")
        
        md.append("### 性能指标")
        md.append(f"- **Sharpe比率**: {metrics.get('sharpe_ratio', 0):.4f}")
        md.append(f"- **Sortino比率**: {metrics.get('sortino_ratio', 0):.4f}")
        md.append(f"- **最大回撤**: {metrics.get('max_drawdown', 0):.2f} bps")
        md.append(f"- **MAR比率**: {metrics.get('MAR', 0):.4f}")
        md.append(f"- **盈亏比**: {metrics.get('risk_reward_ratio', 0):.4f}")
        md.append(f"- **平均持有时长**: {metrics.get('avg_hold_sec', 0):.2f} 秒")
        md.append("")
        
        # 按时段分析
        md.append("## 3. 按时段分析（UTC小时）")
        md.append("")
        md.append("| 时段 | 交易数 | 净PnL | 费用 | 滑点 | 胜率 | 每笔平均PnL | 平均持有时长 |")
        md.append("|------|--------|-------|------|------|------|-------------|--------------|")
        
        for hour in range(24):
            stats = by_hour[hour]
            avg_pnl_per_trade = stats.get("avg_pnl_per_trade", 0)
            md.append(
                f"| {hour:02d}:00 | {stats['count']} | ${stats['pnl_net']:.2f} | "
                f"${stats['fee']:.2f} | ${stats['slippage']:.2f} | "
                f"{stats['win_rate']*100:.2f}% | ${avg_pnl_per_trade:.2f} | {stats['avg_hold_sec']:.2f}s |"
            )
        md.append("")
        
        # 按场景分析
        md.append("## 4. 按场景分析")
        md.append("")
        
        # 计算unknown占比（数据质量提示）
        unknown_count = by_scenario.get("unknown", {}).get("count", 0)
        unknown_ratio = unknown_count / total_trades if total_trades > 0 else 0
        if unknown_ratio > 0:
            md.append(f"WARNING: **数据质量提示**: unknown场景占比 {unknown_ratio*100:.2f}% ({unknown_count}/{total_trades})")
            md.append("")
        
        md.append("| 场景 | 交易数 | 净PnL | 费用 | 滑点 | 胜率 | 盈亏比 |")
        md.append("|------|--------|-------|------|------|------|--------|")
        
        for scenario in sorted(by_scenario.keys()):
            stats = by_scenario[scenario]
            md.append(
                f"| {scenario} | {stats['count']} | ${stats['pnl_net']:.2f} | "
                f"${stats['fee']:.2f} | ${stats['slippage']:.2f} | "
                f"{stats['win_rate']*100:.2f}% | {stats['risk_reward_ratio']:.4f} |"
            )
        md.append("")
        
        # 按交易对分析
        md.append("## 5. 按交易对分析")
        md.append("")
        md.append("| 交易对 | 交易数 | 净PnL | 费用 | 滑点 | 胜率 | 盈亏比 | 平均持有时长 |")
        md.append("|--------|--------|-------|------|------|------|--------|--------------|")
        
        for symbol in sorted(by_symbol.keys()):
            stats = by_symbol[symbol]
            md.append(
                f"| {symbol} | {stats['count']} | ${stats['pnl_net']:.2f} | "
                f"${stats['fee']:.2f} | ${stats['slippage']:.2f} | "
                f"{stats['win_rate']*100:.2f}% | {stats['risk_reward_ratio']:.4f} | "
                f"{stats['avg_hold_sec']:.2f}s |"
            )
        md.append("")
        
        # 成本分解
        md.append("## 6. 成本分解")
        md.append("")
        md.append(f"- **总费用**: ${cost_breakdown['total_fee']:.2f}")
        md.append(f"- **总滑点**: ${cost_breakdown['total_slippage']:.2f}")
        md.append(f"- **总成本**: ${cost_breakdown['total_cost']:.2f}")
        md.append(f"- **总成交额**: ${cost_breakdown.get('turnover', 0):,.2f}")
        md.append(f"- **Maker成交额**: ${cost_breakdown['maker_turnover']:,.2f}")
        md.append(f"- **Taker成交额**: ${cost_breakdown['taker_turnover']:,.2f}")
        md.append(f"- **成本占比（PnL口径）**: {cost_breakdown['cost_ratio']*100:.2f}%")
        md.append(f"- **成本占比（成交额口径）**: {cost_breakdown.get('cost_ratio_notional', 0)*100:.2f}%")
        md.append("")
        
        # TOP交易
        md.append("## 7. TOP交易分析")
        md.append("")
        md.append("### TOP 10 盈利交易")
        md.append("")
        md.append("| 排名 | 时间 | 交易对 | 方向 | 价格 | PnL | 场景 |")
        md.append("|------|------|--------|------|------|-----|------|")
        
        for i, trade in enumerate(top_wins[:10], 1):
            ts_ms = trade.get("ts_ms", 0)
            dt_str = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%H:%M:%S") if ts_ms else "N/A"
            # Fix 3: 显示gross_pnl
            pnl = _extract_gross_pnl(trade)
            scenario = _normalize_scenario(trade.get("scenario_2x2"))
            md.append(
                f"| {i} | {dt_str} | {trade.get('symbol', 'N/A')} | {trade.get('side', 'N/A')} | "
                f"${trade.get('px', 0):.2f} | ${pnl:.2f} | {scenario} |"
            )
        md.append("")
        
        md.append("### TOP 10 亏损交易")
        md.append("")
        md.append("| 排名 | 时间 | 交易对 | 方向 | 价格 | PnL | 场景 |")
        md.append("|------|------|--------|------|------|-----|------|")
        
        for i, trade in enumerate(top_losses[:10], 1):
            ts_ms = trade.get("ts_ms", 0)
            dt_str = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%H:%M:%S") if ts_ms else "N/A"
            # Fix 3: 显示gross_pnl
            pnl = _extract_gross_pnl(trade)
            scenario = _normalize_scenario(trade.get("scenario_2x2"))
            md.append(
                f"| {i} | {dt_str} | {trade.get('symbol', 'N/A')} | {trade.get('side', 'N/A')} | "
                f"${trade.get('px', 0):.2f} | ${pnl:.2f} | {scenario} |"
            )
        md.append("")
        
        # 保存
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(md))
    
    def _generate_metrics_json(
        self,
        output_file: Path,
        trades: List[Dict[str, Any]],
        metrics: Dict[str, Any],
        by_hour: Dict[int, Dict[str, Any]],
        by_scenario: Dict[str, Dict[str, Any]],
        by_symbol: Dict[str, Dict[str, Any]],
        cost_breakdown: Dict[str, Any],
    ):
        """生成metrics.json"""
        # Fix 7: 统一派生overall指标
        total_trades = len(trades)
        wins = [t for t in trades if _extract_gross_pnl(t) > 0]
        losses = [t for t in trades if _extract_gross_pnl(t) < 0]
        win_rate = len(wins) / total_trades if total_trades > 0 else 0
        
        # 计算盈亏比
        wins_pnl = [_extract_gross_pnl(t) for t in wins]
        losses_pnl = [_extract_gross_pnl(t) for t in losses]
        avg_win = sum(wins_pnl) / len(wins_pnl) if wins_pnl else 0
        avg_loss = abs(sum(losses_pnl) / len(losses_pnl)) if losses_pnl else 0
        risk_reward = avg_win / avg_loss if avg_loss > 0 else 0
        
        overall_computed = {
            "total_trades": total_trades,
            "total_gross_pnl": cost_breakdown["total_gross_pnl"],
            "total_net_pnl": cost_breakdown["total_net_pnl"],
            "total_fee": cost_breakdown["total_fee"],
            "total_slippage": cost_breakdown["total_slippage"],
            "total_cost": cost_breakdown["total_cost"],
            "turnover": cost_breakdown.get("turnover", 0),  # A.1: 成交额
            "win_rate": win_rate,
            "risk_reward_ratio": risk_reward,
            "cost_ratio": cost_breakdown["cost_ratio"],  # PnL口径
            "cost_ratio_notional": cost_breakdown.get("cost_ratio_notional", 0),  # A.1: 成交额口径
            "wins": len(wins),
            "losses": len(losses),
        }
        
        result = {
            "overall_computed": overall_computed,  # Fix 7: 统一派生
            "overall_from_engine": metrics,  # Fix 7: 保留原始指标以便对比
            "by_hour": {str(k): v for k, v in by_hour.items()},
            "by_scenario": by_scenario,
            "by_symbol": by_symbol,
            "cost_breakdown": cost_breakdown,
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    
    def _generate_charts(
        self,
        trades: List[Dict[str, Any]],
        by_hour: Dict[int, Dict[str, Any]],
        by_scenario: Dict[str, Dict[str, Any]],
        by_symbol: Dict[str, Dict[str, Any]],
    ):
        """生成图表
        
        C.1改进: 添加净值曲线和回撤曲线
        C.2改进: 添加时段×场景胜率热力图
        """
        if not MATPLOTLIB_AVAILABLE:
            logger.warning("matplotlib不可用，跳过图表生成")
            return
        
        # 图表1: 按时段PnL
        fig, ax = plt.subplots(figsize=(12, 6))
        hours = list(range(24))
        pnls = [by_hour[h]["pnl_net"] for h in hours]
        counts = [by_hour[h]["count"] for h in hours]
        ax.bar(hours, pnls)
        ax.set_xlabel("UTC Hour")
        ax.set_ylabel("Net PnL ($)")
        ax.set_title(f"Net PnL by Hour (Total: {sum(counts)} trades)")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.output_dir / "fig_pnl_by_hour.png", dpi=150)
        plt.close()
        
        # 图表2: 按场景PnL
        fig, ax = plt.subplots(figsize=(10, 6))
        scenarios = sorted(by_scenario.keys())
        pnls = [by_scenario[s]["pnl_net"] for s in scenarios]
        ax.barh(scenarios, pnls)
        ax.set_xlabel("Net PnL ($)")
        ax.set_title("Net PnL by Scenario")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.output_dir / "fig_pnl_by_scenario.png", dpi=150)
        plt.close()
        
        # 图表3: 按交易对PnL
        fig, ax = plt.subplots(figsize=(10, 6))
        symbols = sorted(by_symbol.keys())
        pnls = [by_symbol[s]["pnl_net"] for s in symbols]
        ax.barh(symbols, pnls)
        ax.set_xlabel("Net PnL ($)")
        ax.set_title("Net PnL by Symbol")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.output_dir / "fig_pnl_by_symbol.png", dpi=150)
        plt.close()
        
        # C.1: 图表4: 净值曲线（累计净PnL）
        if trades:
            sorted_trades = sorted(trades, key=lambda t: t.get("ts_ms", 0))
            time_index = []
            pnl_net_series = []
            cum_pnl = 0.0
            
            for trade in sorted_trades:
                ts_ms = trade.get("ts_ms", 0)
                if ts_ms:
                    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                    time_index.append(dt)
                    gross_pnl = _extract_gross_pnl(trade)
                    fee = trade.get("fee", 0)
                    slippage = _extract_slippage_cost(trade)
                    net_pnl = gross_pnl - fee - slippage
                    cum_pnl += net_pnl
                    pnl_net_series.append(cum_pnl)
            
            if time_index and pnl_net_series:
                fig, ax = plt.subplots(figsize=(12, 4))
                ax.plot(time_index, pnl_net_series, linewidth=1.5)
                ax.set_xlabel("Time")
                ax.set_ylabel("Cumulative Net PnL ($)")
                ax.set_title("Cumulative Net PnL")
                ax.grid(True, alpha=0.3)
                plt.xticks(rotation=45)
                plt.tight_layout()
                plt.savefig(self.output_dir / "fig_cum_net_pnl.png", dpi=150)
                plt.close()
                
                # C.1: 图表5: 回撤曲线
                cum_max = []
                max_so_far = -1e9
                for pnl in pnl_net_series:
                    max_so_far = max(max_so_far, pnl)
                    cum_max.append(max_so_far)
                
                drawdown = [pnl - max_val for pnl, max_val in zip(pnl_net_series, cum_max)]
                
                fig, ax = plt.subplots(figsize=(12, 4))
                ax.fill_between(time_index, drawdown, 0, alpha=0.3, color="red")
                ax.plot(time_index, drawdown, linewidth=1.5, color="red")
                ax.set_xlabel("Time")
                ax.set_ylabel("Drawdown ($)")
                ax.set_title("Drawdown")
                ax.grid(True, alpha=0.3)
                plt.xticks(rotation=45)
                plt.tight_layout()
                plt.savefig(self.output_dir / "fig_drawdown.png", dpi=150)
                plt.close()
        
        # C.2: 图表6: 时段×场景胜率热力图
        scenarios_list = sorted([s for s in by_scenario.keys() if s != "unknown"])
        hours_list = list(range(24))
        
        # 构建热力图数据
        heatmap_data = []
        for hour in hours_list:
            row = []
            for scenario in scenarios_list:
                # 从trades中筛选该时段和场景的交易
                hour_trades = [t for t in trades 
                              if t.get("ts_ms") and 
                              datetime.fromtimestamp(t["ts_ms"] / 1000.0, tz=timezone.utc).hour == hour]
                scenario_trades = [t for t in hour_trades 
                                 if _normalize_scenario(t.get("scenario_2x2")) == scenario]
                
                if scenario_trades:
                    wins = sum(1 for t in scenario_trades if _extract_gross_pnl(t) > 0)
                    win_rate = wins / len(scenario_trades) if scenario_trades else 0
                else:
                    win_rate = 0
                row.append(win_rate)
            heatmap_data.append(row)
        
        if heatmap_data and scenarios_list:
            fig, ax = plt.subplots(figsize=(10, 8))
            im = ax.imshow(heatmap_data, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1)
            ax.set_xticks(range(len(scenarios_list)))
            ax.set_xticklabels(scenarios_list)
            ax.set_yticks(range(24))
            ax.set_yticklabels([f"{h:02d}:00" for h in range(24)])
            ax.set_xlabel("Scenario")
            ax.set_ylabel("UTC Hour")
            ax.set_title("Win Rate Heatmap (Hour × Scenario)")
            plt.colorbar(im, ax=ax, label="Win Rate")
            plt.tight_layout()
            plt.savefig(self.output_dir / "fig_winrate_heatmap.png", dpi=150)
            plt.close()
        
        logger.info(f"[ReportGenerator] 图表已生成: {self.output_dir}")

