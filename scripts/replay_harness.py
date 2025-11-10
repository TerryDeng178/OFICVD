#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T08.6: CLI for replay harness - Backtest trading strategies"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from alpha_core.backtest import DataReader, DataAligner, ReplayFeeder, TradeSimulator, MetricsAggregator
from alpha_core.backtest.config_schema import load_backtest_config
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(config_path: Path) -> Dict:
    """Load YAML configuration file
    
    P2.3: 使用Pydantic Schema验证配置
    """
    try:
        # P2.3: 使用config_schema验证配置
        backtest_config = load_backtest_config(config_path)
        return {"backtest": backtest_config}
    except Exception as e:
        logger.warning(f"Config validation failed, using raw config: {e}")
        # Fallback to original method
        try:
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except ImportError:
            logger.warning("PyYAML not installed, using empty config")
            return {}
        except Exception as e2:
            logger.error(f"Error loading config: {e2}")
            return {}


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="T08: Replay + Backtest Harness")
    
    # Input
    parser.add_argument("--input", type=str, required=True, help="Input data directory")
    parser.add_argument("--date", type=str, help="Date filter (YYYY-MM-DD)")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols (e.g., BTCUSDT,ETHUSDT)")
    parser.add_argument("--kinds", type=str, required=True, help="Comma-separated data kinds (e.g., features,prices,orderbook)")
    
    # Time filters
    parser.add_argument("--start-ms", type=int, help="Start timestamp (Unix ms)")
    parser.add_argument("--end-ms", type=int, help="End timestamp (Unix ms)")
    parser.add_argument("--minutes", type=int, help="Number of minutes to process")
    parser.add_argument("--session", type=str, help="Session filter (NY, AS, EU)")
    
    # Configuration
    parser.add_argument("--config", type=str, default="./config/backtest.yaml", help="Config file path")
    parser.add_argument("--output", type=str, help="Output directory (overrides config)")
    parser.add_argument("--sink", type=str, choices=["jsonl", "sqlite", "null"], help="Signal sink type")
    
    # Backtest parameters
    parser.add_argument("--taker-fee-bps", type=float, help="Taker fee (basis points)")
    parser.add_argument("--slippage-bps", type=float, help="Slippage (basis points)")
    
    # P0: Reader参数
    parser.add_argument("--include-preview", action="store_true", help="Include preview directory (default: False)")
    parser.add_argument("--source-priority", type=str, help="Source priority (e.g., ready,preview)")
    
    # P1: 统一入口参数
    parser.add_argument("--source", type=str, choices=["ready", "preview", "both"], 
                       help="Data source selection: ready (default), preview, or both")
    
    # P0-3: TradeSim参数 - 支持忽略/尊重gating
    parser.add_argument("--ignore-gating", action="store_true", help="Ignore gating in backtest (for pure strategy evaluation)")
    parser.add_argument("--respect-gating", action="store_true", help="Respect gating in backtest (override config default)")
    
    return parser.parse_args()


def generate_run_id() -> str:
    """Generate run ID"""
    return f"backtest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


def load_config(config_path: Path) -> Dict[str, Any]:
    """P0-1: 加载配置（保留YAML其它分区，避免被Pydantic覆盖）
    
    只校验backtest小节，其它小节（paths/signal/aligner等）原样保留
    """
    raw = {}
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    
    # 只校验backtest小节，其它小节原样保留
    validated_backtest = load_backtest_config(config_path=config_path)
    
    # 合并：保留原始YAML的所有顶层键，仅把backtest小节替换为校验后的字典
    return {**raw, "backtest": validated_backtest}


def main():
    """Main entry point"""
    # P1-2: 记录开始时间（用于manifest的started_at）
    started_at = datetime.now(timezone.utc)
    
    args = parse_args()
    
    # Load configuration
    config_path = Path(args.config)
    config = load_config(config_path) if config_path.exists() else {}
    
    # Generate run ID
    run_id = generate_run_id()
    os.environ["RUN_ID"] = run_id
    
    # P1: 使用集中式路径常量（如果输入目录是默认路径）
    from alpha_core.common.paths import resolve_roots, get_data_root
    roots = resolve_roots(Path(__file__).parent.parent)
    
    # 如果输入目录是默认路径，使用集中式常量
    input_dir = Path(args.input)
    if str(input_dir) in (str(roots["DATA_ROOT"]), str(roots["RAW_ROOT"]), str(roots["PREVIEW_ROOT"])):
        logger.info(f"[replay_harness] 使用集中式路径常量: {input_dir}")
    
    # Determine output directory
    output_base = Path(args.output or config.get("paths", {}).get("output_dir", "./runtime/backtest"))
    output_dir = output_base / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"[replay_harness] Starting backtest run_id={run_id}")
    logger.info(f"[replay_harness] Input: {args.input}, Kinds: {args.kinds}")
    logger.info(f"[replay_harness] Output: {output_dir}")
    
    # P1: 启动期路径自检
    if input_dir.exists():
        parquet_files = list(input_dir.rglob("*.parquet"))[:3]
        jsonl_files = list(input_dir.rglob("*.jsonl"))[:3]
        if parquet_files or jsonl_files:
            logger.info(f"[replay_harness] 路径自检: 找到 {len(list(input_dir.rglob('*.parquet')))} 个Parquet文件, {len(list(input_dir.rglob('*.jsonl')))} 个JSONL文件")
            if parquet_files:
                logger.info(f"[replay_harness] 示例文件: {parquet_files[0].relative_to(input_dir)}")
        else:
            logger.warning(f"[replay_harness] 路径为空: {input_dir}")
    else:
        logger.warning(f"[replay_harness] 路径不存在: {input_dir}")
    
    # Parse symbols and kinds
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
    kinds = [k.strip() for k in args.kinds.split(",")]
    
    # Determine path: features (fast) or raw (full)
    is_fast_path = "features" in kinds
    
    # P1: 统一入口参数（--source ready|preview|both）
    # 映射到include_preview和source_priority
    if args.source:
        if args.source == "ready":
            include_preview = False
            source_priority = ["ready"]
        elif args.source == "preview":
            include_preview = True
            source_priority = ["preview"]
        elif args.source == "both":
            include_preview = True
            source_priority = ["ready", "preview"]
    else:
        # P0: Reader参数 - 默认不扫preview，避免时间窗对不齐
        # 但如果指定了date且数据在preview目录，需要扫描preview
        source_priority = None
        if args.source_priority:
            source_priority = [s.strip() for s in args.source_priority.split(",")]
        
        # 如果指定了date，检查数据是否在preview目录
        include_preview = args.include_preview
        if args.date and not include_preview:
            preview_date_dir = Path(args.input) / "preview" / f"date={args.date}"
            if preview_date_dir.exists():
                # 数据在preview目录，需要扫描
                include_preview = True
                logger.info(f"[replay_harness] 检测到数据在preview目录，启用preview扫描")
                # P0-2: 固定ready优先顺序（确保ready覆盖preview的语义）
                if not source_priority:
                    source_priority = ["ready", "preview"]  # 确保ready优先
    
    # P1: 数据源预检 + 明确告警
    logger.info("=" * 80)
    logger.info("[replay_harness] 数据源预检")
    logger.info("=" * 80)
    
    input_path = Path(args.input)
    ready_dir = input_path / "ready"
    preview_dir = input_path / "preview"
    
    logger.info(f"输入目录: {input_path}")
    logger.info(f"  ready目录存在: {ready_dir.exists()}")
    logger.info(f"  preview目录存在: {preview_dir.exists()}")
    logger.info(f"包含preview: {include_preview}")
    logger.info(f"来源优先级: {source_priority}")
    
    # 检查时间窗重叠警告
    if include_preview and source_priority and len(source_priority) > 1:
        logger.warning(f"[replay_harness] 警告: include_preview=true且source_priority包含多个来源，"
                      f"将以{source_priority}优先顺序覆盖（时间窗可能重叠）")
    
    logger.info(f"数据源配置:")
    logger.info(f"  日期: {args.date}")
    logger.info(f"  交易对: {symbols}")
    logger.info(f"  数据种类: {kinds}")
    logger.info("=" * 80)
    
    # Initialize components
    reader = DataReader(
        input_dir=Path(args.input),
        date=args.date,
        symbols=symbols,
        kinds=kinds,
        start_ms=args.start_ms,
        end_ms=args.end_ms,
        minutes=args.minutes,
        session=args.session,
        include_preview=include_preview,
        source_priority=source_priority,
    )
    
    # Signal output directory
    signal_output_dir = output_dir / "signals"
    signal_output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get signal config
    signal_config = config.get("signal", {})
    if args.sink:
        signal_config["sink"] = {"kind": args.sink}
    
    # P0: 传递components配置段（包含fusion参数）给ReplayFeeder
    # 这样components.fusion参数（如flip_rearm_margin、adaptive_cooldown_k）才能正确传递到CoreAlgorithm
    if "components" in config:
        signal_config["components"] = config["components"]
    
    # Handle sink config (can be string or dict)
    sink_config = signal_config.get("sink", "jsonl")
    if isinstance(sink_config, str):
        sink_kind = sink_config
    else:
        sink_kind = sink_config.get("kind", "jsonl")
    
    # Initialize feeder
    feeder = ReplayFeeder(
        config=signal_config,
        output_dir=signal_output_dir,
        sink_kind=sink_kind,
    )
    
    # Initialize trade simulator
    backtest_config = config.get("backtest", {})
    if args.taker_fee_bps:
        backtest_config["taker_fee_bps"] = args.taker_fee_bps
    if args.slippage_bps:
        backtest_config["slippage_bps"] = args.slippage_bps
    
    # P0-3: TradeSim参数 - 支持忽略/尊重gating（用于纯策略收益评估）
    # 优先级：CLI参数 > YAML配置 > 默认值
    # 如果指定了--respect-gating，则尊重gating（ignore_gating=False）
    # 如果指定了--ignore-gating，则忽略gating（ignore_gating=True）
    # 如果都没指定，使用YAML配置的ignore_gating_in_backtest（默认True）
    if args.respect_gating:
        ignore_gating = False
    elif args.ignore_gating:
        ignore_gating = True
    else:
        # 从YAML配置读取（默认True）
        ignore_gating = backtest_config.get("ignore_gating_in_backtest", True)
    trade_sim = TradeSimulator(
        config=backtest_config,
        output_dir=output_dir,
        ignore_gating_in_backtest=ignore_gating,
    )
    
    # Process data
    if is_fast_path:
        # Fast path: features → signals → pnl
        logger.info("[replay_harness] Using fast path: features → signals → pnl")
        features = reader.read_features()
        
        # Track prices for trade simulation
        current_prices: Dict[str, float] = {}
        
        # 代码.5: 跟踪最后一条市场数据的ts_ms（用于收盘清仓时间戳）
        last_data_ts_ms: Optional[int] = None
        
        signal_count = 0
        for feature_row in features:
            # Update current price
            symbol = feature_row.get("symbol", "")
            mid = feature_row.get("mid", 0)
            if symbol and mid:
                current_prices[symbol] = mid
            
            # 代码.5: 更新最后一条市场数据的ts_ms
            ts_ms = feature_row.get("ts_ms", 0)
            if ts_ms > 0:
                last_data_ts_ms = ts_ms
            
            # 字段名标准化：将ofi_z/cvd_z映射到z_ofi/z_cvd（兼容不同数据格式）
            normalized_row = dict(feature_row)
            if "ofi_z" in normalized_row and "z_ofi" not in normalized_row:
                normalized_row["z_ofi"] = normalized_row["ofi_z"]
            if "cvd_z" in normalized_row and "z_cvd" not in normalized_row:
                normalized_row["z_cvd"] = normalized_row["cvd_z"]
            
            # 补充缺失字段的默认值（避免CoreAlgo警告和信号被阻止）
            if "lag_sec" not in normalized_row or normalized_row.get("lag_sec") is None:
                normalized_row["lag_sec"] = 0.0  # 默认无延迟
            if "consistency" not in normalized_row or normalized_row.get("consistency") is None:
                normalized_row["consistency"] = 1.0  # 默认完全一致
            if "warmup" not in normalized_row or normalized_row.get("warmup") is None:
                normalized_row["warmup"] = False  # False表示已完成warmup，可以交易（True表示正在warmup，会阻止信号）
            if "spread_bps" not in normalized_row or normalized_row.get("spread_bps") is None:
                normalized_row["spread_bps"] = 2.0  # 默认2.0 bps（合理值，避免spread检查失败）
            
            # P0修复: 注入固定lag_sec（用于强制触发lag检查）
            signal_config = config.get("signal", {})
            if signal_config.get("inject_lag_sec") is not None:
                inject_lag = signal_config.get("inject_lag_sec")
                normalized_row["lag_sec"] = inject_lag
                logger.debug(f"[replay_harness] Injected lag_sec={inject_lag} for lag trigger test")
            
            # P0修复: 注入低consistency（用于强制触发consistency检查）
            if signal_config.get("inject_low_consistency", False):
                inject_consistency = signal_config.get("inject_consistency_value", 0.1)
                normalized_row["consistency"] = inject_consistency
                logger.debug(f"[replay_harness] Injected consistency={inject_consistency} for consistency trigger test")
            
            # Feed to CORE_ALGO
            signal = feeder.algo.process_feature_row(normalized_row)
            if signal:
                # P0-1: fast path也需要附加_feature_data（包含return_1s），确保情境化滑点/费用生效
                if "_feature_data" not in signal:
                    signal["_feature_data"] = {
                        "lag_bad_price": feature_row.get("lag_bad_price", 0),
                        "lag_bad_orderbook": feature_row.get("lag_bad_orderbook", 0),
                        "is_gap_second": feature_row.get("is_gap_second", 0),
                        # P0-1/P1-2: 补充场景上下文（包含return_1s）
                        "spread_bps": feature_row.get("spread_bps"),
                        "vol_bps": feature_row.get("vol_bps"),
                        "scenario_2x2": feature_row.get("scenario_2x2"),
                        "fee_tier": feature_row.get("fee_tier"),
                        "session": feature_row.get("session"),
                        "return_1s": feature_row.get("return_1s"),  # P1-2: 显式包含return_1s
                    }
                signal_count += 1
                # Process signal for trading
                trade = trade_sim.process_signal(signal, mid)
                if trade:
                    logger.debug(f"Trade executed: {trade}")
        
        logger.info(f"[replay_harness] Generated {signal_count} signals")
    else:
        # Full path: raw → features → signals → pnl
        logger.info("[replay_harness] Using full path: raw → features → signals → pnl")
        
        # Initialize aligner
        # 代码.4: 传递配置给DataAligner（支持门限外置）
        # P1-3: aligner_config变量已移除（直接使用config）
        aligner = DataAligner(max_lag_ms=5000, config=config)
        
        # Read raw data
        logger.info("[replay_harness] Reading raw data: prices and orderbook")
        prices = reader.read_raw("prices")
        orderbook = reader.read_raw("orderbook")
        
        # Align raw data and compute features
        logger.info("[replay_harness] Aligning raw data and computing features")
        features = aligner.align_to_seconds(prices, orderbook)
        
        # Track prices for trade simulation
        current_prices: Dict[str, float] = {}
        
        # 代码.5: 跟踪最后一条市场数据的ts_ms（用于收盘清仓时间戳）
        last_data_ts_ms: Optional[int] = None
        
        signal_count = 0
        for feature_row in features:
            # Update current price
            symbol = feature_row.get("symbol", "")
            mid = feature_row.get("mid", 0)
            if symbol and mid:
                current_prices[symbol] = mid
            
            # 代码.5: 更新最后一条市场数据的ts_ms
            ts_ms = feature_row.get("ts_ms", 0)
            if ts_ms > 0:
                last_data_ts_ms = ts_ms
            
            # 字段名标准化：将ofi_z/cvd_z映射到z_ofi/z_cvd（兼容不同数据格式）
            normalized_row = dict(feature_row)
            if "ofi_z" in normalized_row and "z_ofi" not in normalized_row:
                normalized_row["z_ofi"] = normalized_row["ofi_z"]
            if "cvd_z" in normalized_row and "z_cvd" not in normalized_row:
                normalized_row["z_cvd"] = normalized_row["cvd_z"]
            
            # 补充缺失字段的默认值（避免CoreAlgo警告和信号被阻止）
            if "lag_sec" not in normalized_row or normalized_row.get("lag_sec") is None:
                normalized_row["lag_sec"] = 0.0  # 默认无延迟
            if "consistency" not in normalized_row or normalized_row.get("consistency") is None:
                normalized_row["consistency"] = 1.0  # 默认完全一致
            if "warmup" not in normalized_row or normalized_row.get("warmup") is None:
                normalized_row["warmup"] = False  # False表示已完成warmup，可以交易（True表示正在warmup，会阻止信号）
            if "spread_bps" not in normalized_row or normalized_row.get("spread_bps") is None:
                normalized_row["spread_bps"] = 2.0  # 默认2.0 bps（合理值，避免spread检查失败）
            
            # P0修复: 注入固定lag_sec（用于强制触发lag检查）
            signal_config = config.get("signal", {})
            if signal_config.get("inject_lag_sec") is not None:
                inject_lag = signal_config.get("inject_lag_sec")
                normalized_row["lag_sec"] = inject_lag
                logger.debug(f"[replay_harness] Injected lag_sec={inject_lag} for lag trigger test")
            
            # P0修复: 注入低consistency（用于强制触发consistency检查）
            if signal_config.get("inject_low_consistency", False):
                inject_consistency = signal_config.get("inject_consistency_value", 0.1)
                normalized_row["consistency"] = inject_consistency
                logger.debug(f"[replay_harness] Injected consistency={inject_consistency} for consistency trigger test")
            
            # Feed to CORE_ALGO
            signal = feeder.algo.process_feature_row(normalized_row)
            if signal:
                # P0-1: 将完整的场景上下文附加到signal（与Feeder保持一致）
                # 确保情境化滑点/费用在全路径回放时生效
                if "_feature_data" not in signal:
                    signal["_feature_data"] = {
                        "lag_bad_price": feature_row.get("lag_bad_price", 0),
                        "lag_bad_orderbook": feature_row.get("lag_bad_orderbook", 0),
                        "is_gap_second": feature_row.get("is_gap_second", 0),
                        # P0-1/P1-2: 补充场景上下文（包含return_1s）
                        "spread_bps": feature_row.get("spread_bps"),
                        "vol_bps": feature_row.get("vol_bps"),
                        "scenario_2x2": feature_row.get("scenario_2x2"),
                        "fee_tier": feature_row.get("fee_tier"),
                        "session": feature_row.get("session"),
                        "return_1s": feature_row.get("return_1s"),  # P1-2: 显式包含return_1s
                    }
                signal_count += 1
                # Process signal for trading
                trade = trade_sim.process_signal(signal, mid)
                if trade:
                    logger.debug(f"Trade executed: {trade}")
        
        logger.info(f"[replay_harness] Generated {signal_count} signals")
        logger.info(f"[replay_harness] Aligner stats: {aligner.get_stats()}")
    
    # Close all positions
    # 代码.5: 传递最后一条市场数据的ts_ms
    trade_sim.close_all_positions(current_prices, last_data_ts_ms=last_data_ts_ms)
    
    # P1: 期末平仓统计（未平仓数与技术性平仓盈亏）
    rollover_close_trades = [t for t in trade_sim.trades if t.get("reason") == "rollover_close"]
    rollover_close_pnl = sum(t.get("net_pnl", 0) for t in rollover_close_trades)
    
    # Save daily PnL
    trade_sim.save_pnl_daily()
    
    # P1: Set environment variables for Pushgateway export
    os.environ["RUN_ID"] = run_id
    if symbols:
        os.environ["BACKTEST_SYMBOL"] = symbols[0] if len(symbols) == 1 else "all"
    if args.session:
        os.environ["BACKTEST_SESSION"] = args.session
    else:
        os.environ["BACKTEST_SESSION"] = "all"
    
    # Compute metrics
    metrics_agg = MetricsAggregator(output_dir)
    pnl_daily_list = list(trade_sim.pnl_daily.values())
    # P1.4: 传递trade_sim统计信息（用于计算非法场景/费率比例）
    # P2.1: 传递turnover细化统计
    # 代码.2: 传递notional_per_trade用于Sharpe/Sortino收益率归一
    trade_sim_stats = {
        "total_signal_count": trade_sim.total_signal_count,
        "invalid_scenario_count": trade_sim.invalid_scenario_count,
        "invalid_fee_tier_count": trade_sim.invalid_fee_tier_count,
        "turnover_maker": trade_sim.turnover_maker,
        "turnover_taker": trade_sim.turnover_taker,
        "fee_tier_distribution": dict(trade_sim.fee_tier_distribution),
        "notional_per_trade": trade_sim.notional_per_trade,  # 代码.2: 用于收益率归一
    }
    # 代码.2: 传递initial_equity（如果配置中有）
    initial_equity = config.get("backtest", {}).get("initial_equity")
    
    # P1-5: 先获取Reader/Feeder/Aligner统计（用于Pushgateway导出）
    feeder_stats = feeder.get_stats()
    reader_stats = reader.get_stats()
    # P1-1: 获取Aligner统计（用于质量→收益桥接指标）
    aligner_stats = aligner.get_stats() if not is_fast_path else None
    
    # Close feeder
    feeder.close()
    
    # P0-2: 计算metrics并统一导出（传递reader_stats和feeder_stats，避免重复推送）
    # 注意：Pushgateway推送已在_save_metrics中统一处理，无需二次调用
    metrics = metrics_agg.compute_metrics(
        trade_sim.trades,
        pnl_daily_list,
        trade_sim_stats,
        initial_equity=initial_equity,
        reader_stats=reader_stats,
        feeder_stats=feeder_stats,
        aligner_stats=aligner_stats,  # P1-1: 传递aligner_stats
    )
    
    # P1: 获取sink健康度指标（用于manifest）
    sink_health = feeder_stats.get("sink_health", {})
    
    # P2-3: 获取git commit和data fingerprint（用于可复现性）
    git_commit = "unknown"
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
            timeout=5,
        )
        if result.returncode == 0:
            git_commit = result.stdout.strip()
    except Exception:
        pass
    
    # P2-3: 数据指纹（path, size, mtime）
    data_fingerprint = {}
    if args.input:
        input_path = Path(args.input)
        if input_path.exists():
            try:
                # 计算目录大小（简化：仅记录存在性）
                data_fingerprint = {
                    "path": str(input_path.absolute()),
                    "exists": True,
                }
                # 如果是指定日期的目录，记录mtime
                if args.date:
                    date_dir = input_path / "ready" / f"date={args.date}"
                    if date_dir.exists():
                        stat = date_dir.stat()
                        data_fingerprint["date_dir_mtime"] = stat.st_mtime
                        data_fingerprint["date_dir_size"] = sum(
                            f.stat().st_size for f in date_dir.rglob("*") if f.is_file()
                        )
            except Exception:
                pass
    
    # P1-2: 记录结束时间（用于manifest的finished_at）
    finished_at = datetime.now(timezone.utc)
    
    # Generate run manifest
    manifest = {
        "run_id": run_id,
        "started_at": started_at.isoformat(),  # P1-2: 使用进程开始时间
        "finished_at": finished_at.isoformat(),  # P1-2: 新增finished_at字段
        "git_commit": git_commit,  # P2-3: Git commit用于可复现性
        "data_fingerprint": data_fingerprint,  # P2-3: 数据指纹（path, size, mtime）
        "config": config,
        "args": vars(args),
        "reader_stats": reader_stats,  # P1: 包含reader_dedup_rate, missing_field_counts等（P2: 包含sample_files）
        "feeder_stats": feeder_stats,
        # P2修复: 记录ReplayFeeder的生效参数快照
        "effective_params": feeder.effective_params if hasattr(feeder, "effective_params") else {},
        # P2修复: 记录Aligner质量指标（用于质量→收益串联）
        "aligner_stats": aligner_stats,
        "trade_stats": {
            "total_trades": len(trade_sim.trades),
            "open_positions": len(trade_sim.positions),
            # P1: 期末平仓统计
            "rollover_close_count": len(rollover_close_trades),
            "rollover_close_pnl": rollover_close_pnl,
        },
        "metrics": metrics,
        "sink_health": sink_health,  # P1: 添加sink健康度指标
        # P1: 数据源预检信息
        "data_source_info": {
            "input_dir": str(args.input),
            "include_preview": include_preview,
            "source_priority": source_priority,
            "date": args.date,
            "symbols": symbols,
            "kinds": kinds,
        },
    }
    
    manifest_path = output_dir / "run_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    
    logger.info(f"[replay_harness] Backtest completed. Run ID: {run_id}")
    logger.info(f"[replay_harness] Metrics: {json.dumps(metrics, indent=2)}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

