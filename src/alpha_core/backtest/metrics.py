# -*- coding: utf-8 -*-
"""T08.5: Aggregator & Metrics - Compute performance metrics"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class MetricsAggregator:
    """Compute performance metrics from trades and PnL"""
    
    def __init__(self, output_dir: Path):
        """
        Args:
            output_dir: Output directory for metrics
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.metrics_file = self.output_dir / "metrics.json"
    
    def compute_metrics(
        self,
        trades: List[Dict[str, Any]],
        pnl_daily: List[Dict[str, Any]],
        trade_sim_stats: Optional[Dict[str, Any]] = None,
        initial_equity: Optional[float] = None,
        reader_stats: Optional[Dict[str, Any]] = None,
        feeder_stats: Optional[Dict[str, Any]] = None,
        aligner_stats: Optional[Dict[str, Any]] = None,  # P1-1: 新增aligner_stats参数
    ) -> Dict[str, Any]:
        """
        Compute aggregated metrics
        
        Args:
            trades: List of trade records
            pnl_daily: List of daily PnL records
            
        Returns:
            Metrics dictionary
        """
        # P1-4: 无交易时的Metrics行为 - 至少推送健康度与0值核心指标
        if not trades:
            logger.warning("[MetricsAggregator] No trades to compute metrics")
            # P1-4: 返回空指标但保留结构，便于在看板上识别"无交易"的回合
            empty_metrics = {
                "total_trades": 0,
                "total_pnl": 0.0,
                "total_fee": 0.0,
                "total_slippage": 0.0,
                "total_turnover": 0.0,
                "win_rate": 0.0,  # 日口径
                "win_rate_trades": 0.0,  # 交易口径
                "cost_bps_on_turnover": 0.0,  # 成本bps
                "risk_reward_ratio": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "max_drawdown": 0.0,
                "MAR": 0.0,
                "avg_hold_sec": 0.0,
                "avg_hold_long": 0.0,
                "avg_hold_short": 0.0,
                "scenario_breakdown": {},
                "invalid_scenario_rate": 0.0,
                "invalid_fee_tier_rate": 0.0,
                "turnover_maker": 0.0,
                "turnover_taker": 0.0,
                "fee_tier_distribution": {},
                "avg_ret1s_bps": 0.0,
                "by_symbol": {},  # 多品种公平权重：空交易时也包含by_symbol字段
            }
            # P1-4: 即使无交易也保存metrics并推送健康度指标
            self._save_metrics(empty_metrics, reader_stats=reader_stats, feeder_stats=feeder_stats, aligner_stats=aligner_stats)
            return empty_metrics
        
        # Extract PnL series
        pnl_series = []
        cumulative_pnl = 0.0
        for daily in sorted(pnl_daily, key=lambda x: (x["date"], x["symbol"])):
            cumulative_pnl += daily["net_pnl"]
            pnl_series.append(cumulative_pnl)
        
        # Basic statistics
        # P0修复: total_trades只统计出场类reason（避免翻倍）
        exit_reasons = ["exit", "reverse", "reverse_signal", "stop_loss", "take_profit", "timeout", "rollover_close"]
        total_trades = len([t for t in trades if t.get("reason") in exit_reasons])
        total_pnl = sum(d.get("net_pnl", 0) for d in pnl_daily)
        total_fee = sum(d.get("fee", 0) for d in pnl_daily)
        total_slippage = sum(d.get("slippage", 0) for d in pnl_daily)
        total_turnover = sum(d.get("turnover", 0) for d in pnl_daily)
        
        # Win rate - P0修复: 区分日口径和交易口径
        # 日口径（保留，用于兼容）
        wins_days = sum(1 for d in pnl_daily if d.get("net_pnl", 0) > 0)
        losses_days = sum(1 for d in pnl_daily if d.get("net_pnl", 0) < 0)
        win_rate_days = wins_days / (wins_days + losses_days) if (wins_days + losses_days) > 0 else 0.0
        
        # 交易口径（用于优化打分）- P0修复
        exit_reasons_for_winrate = ["exit", "reverse", "reverse_signal", "stop_loss", "take_profit", "timeout", "rollover_close"]
        exit_trades = [t for t in trades if t.get("reason") in exit_reasons_for_winrate]
        wins_trades = sum(1 for t in exit_trades if t.get("net_pnl", 0) > 0)
        losses_trades = sum(1 for t in exit_trades if t.get("net_pnl", 0) < 0)
        win_rate_trades = wins_trades / (wins_trades + losses_trades) if (wins_trades + losses_trades) > 0 else 0.0
        
        # Risk-reward ratio (使用日口径)
        avg_win = sum(d["net_pnl"] for d in pnl_daily if d.get("net_pnl", 0) > 0) / wins_days if wins_days > 0 else 0.0
        avg_loss = abs(sum(d["net_pnl"] for d in pnl_daily if d.get("net_pnl", 0) < 0) / losses_days) if losses_days > 0 else 0.0
        rr = avg_win / avg_loss if avg_loss > 0 else float("inf") if avg_win > 0 else 0.0
        
        # 代码.2: Sharpe/Sortino收益率归一（增加initial_equity）
        # 将pnl_series规范成日收益率，避免"单位不一"的偏差
        # 如果提供了initial_equity，将PnL转换为收益率；否则使用notional_per_trade作为基准
        equity_base = initial_equity
        if equity_base is None:
            # 从trade_sim_stats获取notional_per_trade作为基准
            if trade_sim_stats:
                equity_base = trade_sim_stats.get("notional_per_trade", 1000.0)
            else:
                equity_base = 1000.0  # 默认基准
        
        # 将PnL序列转换为收益率序列
        returns = []
        if len(pnl_series) > 1:
            for i in range(1, len(pnl_series)):
                daily_pnl = pnl_series[i] - pnl_series[i-1]
                # 转换为日收益率（基于equity_base）
                daily_return = daily_pnl / equity_base if equity_base > 0 else 0.0
                returns.append(daily_return)
        
        # P1: Metrics年化与归一口径一致化
        # pnl_series时间粒度：日（daily）
        # Sharpe/Sortino年化因子：√252（交易日）
        # MAR年化因子：252（交易日）
        
        # Sharpe ratio (annualized with √252)
        if returns:
            import statistics
            mean_return = statistics.mean(returns)
            std_return = statistics.stdev(returns) if len(returns) > 1 else 0.0
            # P1: 年化因子统一为√252（交易日）
            sharpe = (mean_return / std_return * (252 ** 0.5)) if std_return > 0 else 0.0
        else:
            sharpe = 0.0
        
        # Sortino ratio (downside deviation, annualized with √252)
        if returns:
            downside_returns = [r for r in returns if r < 0]
            if downside_returns:
                import statistics
                mean_return = statistics.mean(returns)
                downside_std = statistics.stdev(downside_returns) if len(downside_returns) > 1 else 0.0
                # P1: 年化因子统一为√252（交易日）
                sortino = (mean_return / downside_std * (252 ** 0.5)) if downside_std > 0 else 0.0
            else:
                mean_return = statistics.mean(returns)
                sortino = float("inf") if mean_return > 0 else 0.0
        else:
            sortino = 0.0
        
        # Maximum drawdown
        dd_max = 0.0
        peak = pnl_series[0] if pnl_series else 0.0
        for pnl in pnl_series:
            if pnl > peak:
                peak = pnl
            drawdown = peak - pnl
            if drawdown > dd_max:
                dd_max = drawdown
        
        # P0: 修正MAR公式判定
        # P1: Metrics年化与归一口径一致化
        # dd_max是正数（最大回撤幅度），应判断dd_max > 0而非< 0
        # MAR年化因子：252（交易日）
        if dd_max > 0:
            # 年化收益 / 最大回撤
            # P1: 年化因子统一为252（交易日），与Sharpe/Sortino一致
            annual_return = (total_pnl / max(1, len(pnl_daily))) * 252
            mar = annual_return / dd_max
        else:
            # 无回撤时，正收益为无穷大，负收益为0
            mar = float("inf") if total_pnl > 0 else 0.0
        
        # P1: Average hold time - optimized from O(N²) to O(N)
        # Use stack/map to track recent entry by symbol/side, match with exit directly
        # P1: 分多空分别统计（avg_hold_long/short）
        hold_times_long = []
        hold_times_short = []
        entry_map = {}  # (symbol, side) -> entry_trade
        
        for trade in trades:
            symbol = trade.get("symbol", "")
            side = trade.get("side", "")
            reason = trade.get("reason", "")
            ts_ms = trade.get("ts_ms", 0)
            
            if reason == "entry":
                # Record entry
                key = (symbol, side)
                entry_map[key] = trade
            elif reason in ["exit", "reverse", "reverse_signal", "stop_loss", "take_profit", "timeout", "rollover_close"]:
                # A组修复: 只统计已闭合的持仓对（忽略未闭合的持仓）
                # Find matching entry
                key = (symbol, side)
                if key in entry_map:
                    entry_trade = entry_map[key]
                    entry_ts = entry_trade.get("ts_ms", 0)
                    hold_time = (ts_ms - entry_ts) / 1000
                    
                    # P1: 分多空统计
                    entry_side = entry_trade.get("side", "")
                    if entry_side == "buy":
                        hold_times_long.append(hold_time)
                    elif entry_side == "sell":
                        hold_times_short.append(hold_time)
                    else:
                        # Fallback: 使用当前side
                        if side == "buy":
                            hold_times_long.append(hold_time)
                        else:
                            hold_times_short.append(hold_time)
                    
                    # Remove from map (position closed)
                    del entry_map[key]
        
        avg_hold_sec = sum(hold_times_long + hold_times_short) / len(hold_times_long + hold_times_short) if (hold_times_long + hold_times_short) else 0.0
        avg_hold_long = sum(hold_times_long) / len(hold_times_long) if hold_times_long else 0.0
        avg_hold_short = sum(hold_times_short) / len(hold_times_short) if hold_times_short else 0.0
        
        # P1.5/P1-3: Scenario breakdown（基于trade记录中的scenario_2x2和session）
        # P1-3: 补完持有时长/胜率/期望，使用entry_map匹配exit的做法
        scenario_breakdown = defaultdict(lambda: {
            "trades": 0,
            "pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "avg_hold_sec": 0.0,
        })
        
        # P1-3: 按场景和会话分组，匹配entry和exit计算持有时长
        scenario_entry_map = defaultdict(dict)  # key -> {(symbol, side): entry_trade}
        scenario_trades = defaultdict(list)
        scenario_pnl = defaultdict(float)
        scenario_wins = defaultdict(int)
        scenario_losses = defaultdict(int)
        scenario_hold_times = defaultdict(list)
        
        for trade in trades:
            scenario = trade.get("scenario_2x2") or "unknown"
            session = trade.get("session") or "unknown"
            key = f"{scenario}_{session}"
            
            reason = trade.get("reason", "")
            symbol = trade.get("symbol", "")
            side = trade.get("side", "")
            
            if reason == "entry":
                # P1-3: 记录entry trade（按场景分组）
                entry_key = (symbol, side)
                scenario_entry_map[key][entry_key] = trade
            elif reason in exit_reasons:
                scenario_trades[key].append(trade)
                net_pnl = trade.get("net_pnl", 0.0)
                scenario_pnl[key] += net_pnl
                
                if net_pnl > 0:
                    scenario_wins[key] += 1
                elif net_pnl < 0:
                    scenario_losses[key] += 1
                
                # P1-3: 匹配entry和exit计算持有时长
                entry_key = (symbol, side)
                if entry_key in scenario_entry_map[key]:
                    entry_trade = scenario_entry_map[key][entry_key]
                    entry_ts = entry_trade.get("ts_ms", 0)
                    exit_ts = trade.get("ts_ms", 0)
                    if entry_ts > 0 and exit_ts > 0:
                        hold_time = (exit_ts - entry_ts) / 1000  # 秒
                        scenario_hold_times[key].append(hold_time)
                    # 移除已匹配的entry
                    del scenario_entry_map[key][entry_key]
        
        # P1-3: 填充scenario_breakdown（包含持有时长）
        for key, trade_list in scenario_trades.items():
            scenario_breakdown[key]["trades"] = len(trade_list)
            scenario_breakdown[key]["pnl"] = scenario_pnl[key]
            scenario_breakdown[key]["wins"] = scenario_wins[key]
            scenario_breakdown[key]["losses"] = scenario_losses[key]
            
            total_trades_scenario = len(trade_list)
            if total_trades_scenario > 0:
                scenario_breakdown[key]["win_rate"] = scenario_wins[key] / total_trades_scenario
                scenario_breakdown[key]["avg_pnl"] = scenario_pnl[key] / total_trades_scenario
            
            # P1-3: 计算平均持有时长
            hold_times = scenario_hold_times[key]
            if hold_times:
                scenario_breakdown[key]["avg_hold_sec"] = sum(hold_times) / len(hold_times)
            else:
                scenario_breakdown[key]["avg_hold_sec"] = 0.0
        
        # P1.4: 计算非法场景/费率比例（从trade_sim_stats获取）
        invalid_scenario_rate = 0.0
        invalid_fee_tier_rate = 0.0
        if trade_sim_stats:
            total_signals = trade_sim_stats.get("total_signal_count", 0)
            if total_signals > 0:
                invalid_scenario_count = trade_sim_stats.get("invalid_scenario_count", 0)
                invalid_fee_tier_count = trade_sim_stats.get("invalid_fee_tier_count", 0)
                invalid_scenario_rate = invalid_scenario_count / total_signals
                invalid_fee_tier_rate = invalid_fee_tier_count / total_signals
        
        # P2.1: Turnover细化统计（从trade_sim_stats获取）
        turnover_maker = trade_sim_stats.get("turnover_maker", 0.0) if trade_sim_stats else 0.0
        turnover_taker = trade_sim_stats.get("turnover_taker", 0.0) if trade_sim_stats else 0.0
        fee_tier_distribution = trade_sim_stats.get("fee_tier_distribution", {}) if trade_sim_stats else {}
        
        # P1-4: 计算平均波动指标（avg_ret1s_bps）作为质量监控指标
        # 从trades中提取return_1s（如果有）或从feature_data中获取
        ret1s_values = []
        for trade in trades:
            # 尝试从trade的feature_data中获取return_1s
            feature_data = trade.get("_feature_data", {})
            ret1s = feature_data.get("return_1s")
            if ret1s is not None:
                ret1s_values.append(abs(float(ret1s)))
        avg_ret1s_bps = sum(ret1s_values) / len(ret1s_values) if ret1s_values else 0.0
        
        # 多品种公平权重：按symbol聚合生成by_symbol字段
        by_symbol = {}
        symbol_pnl_daily = defaultdict(list)
        
        # 按symbol分组pnl_daily
        for daily in pnl_daily:
            symbol = daily.get("symbol", "")
            if symbol:
                symbol_pnl_daily[symbol].append(daily)
        
        # 对每个symbol计算指标
        for symbol, symbol_daily_list in symbol_pnl_daily.items():
            symbol_total_pnl = sum(d.get("net_pnl", 0) for d in symbol_daily_list)
            symbol_gross_pnl = sum(d.get("gross_pnl", 0) for d in symbol_daily_list)
            symbol_fee = sum(d.get("fee", 0) for d in symbol_daily_list)
            symbol_slippage = sum(d.get("slippage", 0) for d in symbol_daily_list)
            symbol_turnover = sum(d.get("turnover", 0) for d in symbol_daily_list)
            symbol_trades = sum(d.get("trades", 0) for d in symbol_daily_list)
            symbol_wins = sum(d.get("wins", 0) for d in symbol_daily_list)
            symbol_losses = sum(d.get("losses", 0) for d in symbol_daily_list)
            
            # 计算胜率
            symbol_win_rate = symbol_wins / (symbol_wins + symbol_losses) if (symbol_wins + symbol_losses) > 0 else 0.0
            
            # 计算成本占比
            symbol_cost_ratio = (symbol_fee + symbol_slippage) / abs(symbol_gross_pnl) if symbol_gross_pnl != 0 else 0.0
            
            # 计算该symbol的PnL序列（用于计算回撤和Sharpe）
            symbol_pnl_series = []
            symbol_cumulative_pnl = 0.0
            for daily in sorted(symbol_daily_list, key=lambda x: x.get("date", "")):
                symbol_cumulative_pnl += daily.get("net_pnl", 0)
                symbol_pnl_series.append(symbol_cumulative_pnl)
            
            # 计算最大回撤
            symbol_dd_max = 0.0
            symbol_peak = symbol_pnl_series[0] if symbol_pnl_series else 0.0
            for pnl in symbol_pnl_series:
                if pnl > symbol_peak:
                    symbol_peak = pnl
                drawdown = symbol_peak - pnl
                if drawdown > symbol_dd_max:
                    symbol_dd_max = drawdown
            
            # 计算MAR（年化收益/最大回撤）
            if symbol_dd_max > 0:
                symbol_annual_return = (symbol_total_pnl / max(1, len(symbol_daily_list))) * 252
                symbol_mar = symbol_annual_return / symbol_dd_max
            else:
                symbol_mar = float("inf") if symbol_total_pnl > 0 else 0.0
            
            # 计算Sharpe ratio（简化版，使用日收益率）
            symbol_returns = []
            if len(symbol_pnl_series) > 1:
                equity_base = initial_equity if initial_equity else (trade_sim_stats.get("notional_per_trade", 1000.0) if trade_sim_stats else 1000.0)
                for i in range(1, len(symbol_pnl_series)):
                    daily_pnl = symbol_pnl_series[i] - symbol_pnl_series[i-1]
                    daily_return = daily_pnl / equity_base if equity_base > 0 else 0.0
                    symbol_returns.append(daily_return)
            
            if symbol_returns:
                import statistics
                symbol_mean_return = statistics.mean(symbol_returns)
                symbol_std_return = statistics.stdev(symbol_returns) if len(symbol_returns) > 1 else 0.0
                symbol_sharpe = (symbol_mean_return / symbol_std_return * (252 ** 0.5)) if symbol_std_return > 0 else 0.0
            else:
                symbol_sharpe = 0.0
            
            # 构建by_symbol条目
            by_symbol[symbol] = {
                "pnl_gross": symbol_gross_pnl,
                "pnl_net": symbol_total_pnl,
                "fee": symbol_fee,
                "slippage": symbol_slippage,
                "turnover": symbol_turnover,
                "count": symbol_trades,  # 交易数
                "wins": symbol_wins,
                "losses": symbol_losses,
                "win_rate": symbol_win_rate,
                "cost_ratio": symbol_cost_ratio,
                "max_drawdown": symbol_dd_max,
                "MAR": symbol_mar,
                "sharpe_ratio": symbol_sharpe,
            }
        
        # P0修复: 计算成本bps（稳定口径，避免除以接近0的毛利导致发散）
        cost_bps_on_turnover = ((total_fee + total_slippage) / total_turnover * 10000) if total_turnover > 0 else 0.0
        
        # Build metrics dict
        metrics = {
            "total_trades": total_trades,
            "total_pnl": total_pnl,
            "total_fee": total_fee,
            "total_slippage": total_slippage,
            "total_turnover": total_turnover,
            "win_rate": win_rate_days,  # 兼容保留（日口径）
            "win_rate_trades": win_rate_trades,  # P0修复: 新增交易口径胜率（优化打分建议用它）
            "cost_bps_on_turnover": cost_bps_on_turnover,  # P0修复: 新增成本bps口径
            "risk_reward_ratio": rr,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "max_drawdown": dd_max,
            "MAR": mar,
            "avg_hold_sec": avg_hold_sec,
            "avg_hold_long": avg_hold_long,  # P1: 分多空统计
            "avg_hold_short": avg_hold_short,  # P1: 分多空统计
            "scenario_breakdown": dict(scenario_breakdown),
            # P1.4: 非法场景/费率比例（用于质量监控）
            "invalid_scenario_rate": invalid_scenario_rate,
            "invalid_fee_tier_rate": invalid_fee_tier_rate,
            # P2.1: Turnover细化统计
            "turnover_maker": turnover_maker,
            "turnover_taker": turnover_taker,
            "fee_tier_distribution": dict(fee_tier_distribution),
            # P1-4: 统一波动字段命名（avg_ret1s_bps作为质量监控指标）
            "avg_ret1s_bps": avg_ret1s_bps,
            # 多品种公平权重：按symbol聚合的指标
            "by_symbol": dict(by_symbol),
        }
        
        # Save metrics
        # P0-2: 统一在_save_metrics中调用_export_to_pushgateway，避免重复推送
        self._save_metrics(metrics, reader_stats=reader_stats, feeder_stats=feeder_stats, aligner_stats=aligner_stats)
        
        return metrics
    
    def _save_metrics(self, metrics: Dict[str, Any], reader_stats: Optional[Dict[str, Any]] = None, feeder_stats: Optional[Dict[str, Any]] = None, aligner_stats: Optional[Dict[str, Any]] = None) -> None:
        """Save metrics to JSON file
        
        P0-2: 统一在这里调用_export_to_pushgateway，避免重复推送
        """
        try:
            with self.metrics_file.open("w", encoding="utf-8") as f:
                json.dump(metrics, f, ensure_ascii=False, indent=2)
            logger.info(f"[MetricsAggregator] Saved metrics to {self.metrics_file}")
        except Exception as e:
            logger.error(f"Error saving metrics: {e}")
        
        # P0-2: 统一在这里推送Pushgateway指标（包含健康度指标）
        self._export_to_pushgateway(metrics, reader_stats=reader_stats, feeder_stats=feeder_stats, aligner_stats=aligner_stats)
    
    def _export_to_pushgateway(self, metrics: Dict[str, Any], reader_stats: Optional[Dict[str, Any]] = None, feeder_stats: Optional[Dict[str, Any]] = None, aligner_stats: Optional[Dict[str, Any]] = None) -> None:
        """Export metrics to Prometheus Pushgateway (optional)
        
        P1-5: 同时导出Reader/Feeder健康度指标
        P1-1: 同时导出Aligner质量指标（质量→收益桥接）
        
        Args:
            metrics: Core backtest metrics
            reader_stats: Reader statistics (optional)
            feeder_stats: Feeder statistics (optional)
            aligner_stats: Aligner statistics (optional)
        """
        import os
        
        timeseries_enabled = os.getenv("TIMESERIES_ENABLED", "0") == "1"
        if not timeseries_enabled:
            return
        
        timeseries_type = os.getenv("TIMESERIES_TYPE", "prometheus").lower()
        if timeseries_type != "prometheus":
            return
        
        timeseries_url = os.getenv("TIMESERIES_URL", "")
        if not timeseries_url:
            return
        
        # Extract run_id and symbol from output_dir or use defaults
        run_id = os.getenv("RUN_ID", "unknown")
        symbol = os.getenv("BACKTEST_SYMBOL", "all")
        session = os.getenv("BACKTEST_SESSION", "all")
        
        try:
            import requests
            from datetime import datetime, timezone
            
            # 代码.1: Metrics推送规范化（秒时间戳 + instance标签）
            # Prometheus通常使用秒时间戳或无时间戳（由采集端打时标）
            # 改为秒时间戳，降低乱序/抖动风险
            timestamp_sec = int(datetime.now(timezone.utc).timestamp())
            
            # 获取instance标签（主机/IP），便于多机并行回测聚合
            instance = os.getenv("INSTANCE", "default")
            try:
                import socket
                hostname = socket.gethostname()
                instance = f"{hostname}_{instance}"
            except Exception:
                pass
            metrics_text = []
            
            # Core metrics
            if "total_pnl" in metrics:
                metrics_text.append(f"backtest_total_pnl{{run_id=\"{run_id}\",symbol=\"{symbol}\",session=\"{session}\",instance=\"{instance}\"}} {metrics['total_pnl']} {timestamp_sec}")
            
            if "sharpe_ratio" in metrics:
                metrics_text.append(f"backtest_sharpe{{run_id=\"{run_id}\",symbol=\"{symbol}\",session=\"{session}\",instance=\"{instance}\"}} {metrics['sharpe_ratio']} {timestamp_sec}")
            
            if "sortino_ratio" in metrics:
                metrics_text.append(f"backtest_sortino{{run_id=\"{run_id}\",symbol=\"{symbol}\",session=\"{session}\",instance=\"{instance}\"}} {metrics['sortino_ratio']} {timestamp_sec}")
            
            if "MAR" in metrics:
                mar_value = metrics['MAR'] if metrics['MAR'] != float('inf') else 0
                metrics_text.append(f"backtest_mar{{run_id=\"{run_id}\",symbol=\"{symbol}\",session=\"{session}\",instance=\"{instance}\"}} {mar_value} {timestamp_sec}")
            
            if "win_rate" in metrics:
                metrics_text.append(f"backtest_win_rate{{run_id=\"{run_id}\",symbol=\"{symbol}\",session=\"{session}\",instance=\"{instance}\"}} {metrics['win_rate']} {timestamp_sec}")
            
            if "risk_reward_ratio" in metrics:
                rr_value = metrics['risk_reward_ratio'] if metrics['risk_reward_ratio'] != float('inf') else 0
                metrics_text.append(f"backtest_rr{{run_id=\"{run_id}\",symbol=\"{symbol}\",session=\"{session}\",instance=\"{instance}\"}} {rr_value} {timestamp_sec}")
            
            if "avg_hold_sec" in metrics:
                metrics_text.append(f"backtest_avg_hold_sec{{run_id=\"{run_id}\",symbol=\"{symbol}\",session=\"{session}\",instance=\"{instance}\"}} {metrics['avg_hold_sec']} {timestamp_sec}")
            
            # Trade metrics
            if "total_trades" in metrics:
                metrics_text.append(f"backtest_trades_total{{run_id=\"{run_id}\",symbol=\"{symbol}\",session=\"{session}\",instance=\"{instance}\"}} {metrics['total_trades']} {timestamp_sec}")
            
            if "total_turnover" in metrics:
                metrics_text.append(f"backtest_turnover{{run_id=\"{run_id}\",symbol=\"{symbol}\",session=\"{session}\",instance=\"{instance}\"}} {metrics['total_turnover']} {timestamp_sec}")
            
            if "total_fee" in metrics:
                metrics_text.append(f"backtest_fee_total{{run_id=\"{run_id}\",symbol=\"{symbol}\",session=\"{session}\",instance=\"{instance}\"}} {metrics['total_fee']} {timestamp_sec}")
            
            if "total_slippage" in metrics:
                metrics_text.append(f"backtest_slippage_total{{run_id=\"{run_id}\",symbol=\"{symbol}\",session=\"{session}\",instance=\"{instance}\"}} {metrics['total_slippage']} {timestamp_sec}")
            
            # P1-5: Reader/Feeder健康度指标
            if reader_stats:
                dedup_rate = reader_stats.get("deduplication_rate_pct", 0.0)
                metrics_text.append(f"backtest_reader_dedup_rate{{run_id=\"{run_id}\",symbol=\"{symbol}\",instance=\"{instance}\"}} {dedup_rate} {timestamp_sec}")
                
                total_rows = reader_stats.get("total_rows", 0)
                metrics_text.append(f"backtest_reader_total_rows{{run_id=\"{run_id}\",symbol=\"{symbol}\",instance=\"{instance}\"}} {total_rows} {timestamp_sec}")
            
            if feeder_stats:
                sink_health = feeder_stats.get("sink_health", {})
                if sink_health:
                    sink_ok = 1 if sink_health.get("ok", False) else 0
                    metrics_text.append(f"backtest_sink_health{{run_id=\"{run_id}\",symbol=\"{symbol}\",instance=\"{instance}\"}} {sink_ok} {timestamp_sec}")
                
                # P0-4: 对齐Feeder指标字段名（支持emitted和signals_emitted别名）
                signal_count = feeder_stats.get("signals_emitted") or feeder_stats.get("emitted", 0)
                metrics_text.append(f"backtest_feeder_signals_emitted{{run_id=\"{run_id}\",symbol=\"{symbol}\",instance=\"{instance}\"}} {signal_count} {timestamp_sec}")
            
            # P1-1: Pushgateway指标再补两项"质量→收益"桥接
            if aligner_stats:
                gap_rate = aligner_stats.get("gap_seconds_rate", 0.0)
                lag_bad_price_rate = aligner_stats.get("lag_bad_price_rate", 0.0)
                lag_bad_orderbook_rate = aligner_stats.get("lag_bad_orderbook_rate", 0.0)
                lag_bad_rate = max(lag_bad_price_rate, lag_bad_orderbook_rate)  # max(price, orderbook)超阈值占比
                
                metrics_text.append(f"backtest_aligner_gap_rate{{run_id=\"{run_id}\",symbol=\"{symbol}\",instance=\"{instance}\"}} {gap_rate} {timestamp_sec}")
                metrics_text.append(f"backtest_lag_bad_rate{{run_id=\"{run_id}\",symbol=\"{symbol}\",instance=\"{instance}\"}} {lag_bad_rate} {timestamp_sec}")
            
            if not metrics_text:
                return
            
            # Push to Pushgateway
            metrics_payload = "\n".join(metrics_text) + "\n"
            # P1-1: Pushgateway分组键使用URL path带instance（避免多机/并行回测覆盖）
            # 与payload内的instance标签相匹配，避免分组冲突
            push_url = f"{timeseries_url}/metrics/job/{run_id}/instance/{instance}"
            
            # Retry with exponential backoff
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    delay = 0.5 * (2 ** attempt)
                    if attempt > 0:
                        import time
                        time.sleep(delay)
                    
                    response = requests.post(
                        push_url,
                        data=metrics_payload,
                        headers={"Content-Type": "text/plain; charset=utf-8"},
                        timeout=10
                    )
                    response.raise_for_status()
                    
                    logger.info(f"[MetricsAggregator] Exported {len(metrics_text)} metrics to Pushgateway (attempt {attempt + 1})")
                    return
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"[MetricsAggregator] Pushgateway export failed (attempt {attempt + 1}): {e}, retrying in {delay}s")
                    else:
                        logger.error(f"[MetricsAggregator] Pushgateway export failed after {max_retries} attempts: {e}")
        except ImportError:
            logger.warning("[MetricsAggregator] requests library not available, skipping Pushgateway export")
        except Exception as e:
            logger.warning(f"[MetricsAggregator] Pushgateway export error: {e}")

