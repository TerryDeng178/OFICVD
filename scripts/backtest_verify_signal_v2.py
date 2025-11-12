#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Signal v2 回测验证脚本

TASK-A4: 回测验证 - confirm率/decision_code分布/契约一致性
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_jsonl_signals(jsonl_dir: Path, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """加载 JSONL 信号"""
    signals = []
    jsonl_files = list(jsonl_dir.rglob("*.jsonl"))
    
    for jsonl_file in jsonl_files:
        try:
            with jsonl_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        signal = json.loads(line)
                        # 如果指定了 run_id，只加载匹配的信号
                        if run_id is None or signal.get("run_id") == run_id:
                            signals.append(signal)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON line in {jsonl_file}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Failed to read {jsonl_file}: {e}")
            continue
    
    return signals


def load_sqlite_signals(db_path: Path, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """加载 SQLite 信号"""
    signals = []
    
    if not db_path.exists():
        logger.warning(f"SQLite database not found: {db_path}")
        return signals
    
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        
        if run_id:
            cursor = conn.execute(
                "SELECT * FROM signals WHERE run_id = ?",
                (run_id,)
            )
        else:
            cursor = conn.execute("SELECT * FROM signals")
        
        for row in cursor:
            signal = dict(row)
            # 解析 meta JSON 字符串
            if signal.get("meta") and isinstance(signal["meta"], str):
                try:
                    signal["meta"] = json.loads(signal["meta"])
                except json.JSONDecodeError:
                    pass
            signals.append(signal)
        
        conn.close()
    except Exception as e:
        logger.error(f"Failed to read SQLite database: {e}")
    
    return signals


def calculate_statistics(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """计算统计信息"""
    if not signals:
        return {
            "total": 0,
            "confirm_count": 0,
            "confirm_rate": 0.0,
            "decision_code_distribution": {},
            "regime_distribution": {},
            "gating_distribution": {},
            "symbol_distribution": {},
        }
    
    total = len(signals)
    confirm_count = sum(1 for s in signals if s.get("confirm") is True)
    confirm_rate = (confirm_count / total * 100) if total > 0 else 0.0
    
    decision_code_dist = Counter(s.get("decision_code", "UNKNOWN") for s in signals)
    regime_dist = Counter(s.get("regime", "UNKNOWN") for s in signals)
    gating_dist = Counter(s.get("gating", 0) for s in signals)
    symbol_dist = Counter(s.get("symbol", "UNKNOWN") for s in signals)
    
    return {
        "total": total,
        "confirm_count": confirm_count,
        "confirm_rate": round(confirm_rate, 2),
        "decision_code_distribution": dict(decision_code_dist),
        "regime_distribution": dict(regime_dist),
        "gating_distribution": dict(gating_dist),
        "symbol_distribution": dict(symbol_dist),
    }


def verify_contract_consistency(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """验证契约一致性
    
    检查：
    1. confirm=true ⇒ gating=1 && decision_code=OK
    2. 所有信号都有必需的字段
    3. config_hash 一致性
    """
    errors = []
    warnings = []
    
    # 检查必需的字段
    required_fields = [
        "schema_version", "ts_ms", "symbol", "signal_id",
        "score", "side_hint", "regime", "gating", "confirm",
        "cooldown_ms", "expiry_ms", "decision_code",
        "config_hash", "run_id"
    ]
    
    config_hashes = set()
    run_ids = set()
    
    for i, signal in enumerate(signals):
        # 检查必需字段
        missing_fields = [f for f in required_fields if f not in signal]
        if missing_fields:
            errors.append(f"Signal {i}: Missing required fields: {missing_fields}")
        
        # 检查 confirm 约束
        if signal.get("confirm") is True:
            if signal.get("gating") != 1:
                errors.append(
                    f"Signal {i} (signal_id={signal.get('signal_id')}): "
                    f"confirm=true but gating={signal.get('gating')} (expected 1)"
                )
            if signal.get("decision_code") != "OK":
                errors.append(
                    f"Signal {i} (signal_id={signal.get('signal_id')}): "
                    f"confirm=true but decision_code={signal.get('decision_code')} (expected OK)"
                )
        
        # 收集 config_hash 和 run_id
        config_hash = signal.get("config_hash")
        if config_hash:
            config_hashes.add(config_hash)
        
        run_id = signal.get("run_id")
        if run_id:
            run_ids.add(run_id)
    
    # 检查 config_hash 一致性
    if len(config_hashes) > 1:
        warnings.append(f"Multiple config_hashes found: {config_hashes}")
    
    # 检查 run_id 一致性
    if len(run_ids) > 1:
        warnings.append(f"Multiple run_ids found: {run_ids}")
    
    return {
        "errors": errors,
        "warnings": warnings,
        "config_hash_count": len(config_hashes),
        "run_id_count": len(run_ids),
        "config_hashes": list(config_hashes),
        "run_ids": list(run_ids),
    }


def verify_dual_sink_consistency(
    jsonl_signals: List[Dict[str, Any]],
    sqlite_signals: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """验证双 Sink 一致性（JSONL vs SQLite）"""
    errors = []
    warnings = []
    
    # 按 signal_id 索引
    jsonl_by_id = {s.get("signal_id"): s for s in jsonl_signals if s.get("signal_id")}
    sqlite_by_id = {s.get("signal_id"): s for s in sqlite_signals if s.get("signal_id")}
    
    # 检查数量一致性
    jsonl_count = len(jsonl_by_id)
    sqlite_count = len(sqlite_by_id)
    
    if jsonl_count != sqlite_count:
        errors.append(
            f"Count mismatch: JSONL={jsonl_count}, SQLite={sqlite_count}"
        )
    
    # 检查每个信号的一致性
    common_ids = set(jsonl_by_id.keys()) & set(sqlite_by_id.keys())
    jsonl_only = set(jsonl_by_id.keys()) - set(sqlite_by_id.keys())
    sqlite_only = set(sqlite_by_id.keys()) - set(jsonl_by_id.keys())
    
    if jsonl_only:
        warnings.append(f"Signals only in JSONL: {len(jsonl_only)}")
    
    if sqlite_only:
        warnings.append(f"Signals only in SQLite: {len(sqlite_only)}")
    
    # 检查字段一致性
    field_errors = []
    for signal_id in common_ids:
        jsonl_sig = jsonl_by_id[signal_id]
        sqlite_sig = sqlite_by_id[signal_id]
        
        # 检查关键字段
        key_fields = ["symbol", "ts_ms", "confirm", "gating", "decision_code", "score"]
        for field in key_fields:
            jsonl_val = jsonl_sig.get(field)
            sqlite_val = sqlite_sig.get(field)
            
            # 处理布尔值转换（SQLite 可能存储为 0/1）
            if field == "confirm" or field == "gating":
                jsonl_val = bool(jsonl_val) if jsonl_val is not None else None
                sqlite_val = bool(sqlite_val) if sqlite_val is not None else None
            
            if jsonl_val != sqlite_val:
                field_errors.append(
                    f"Signal {signal_id}: {field} mismatch "
                    f"(JSONL={jsonl_val}, SQLite={sqlite_val})"
                )
    
    if field_errors:
        errors.extend(field_errors[:10])  # 只报告前10个错误
    
    return {
        "jsonl_count": jsonl_count,
        "sqlite_count": sqlite_count,
        "common_count": len(common_ids),
        "jsonl_only_count": len(jsonl_only),
        "sqlite_only_count": len(sqlite_only),
        "errors": errors,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(description="Signal v2 回测验证")
    parser.add_argument("--data-dir", type=str, required=True, help="数据目录")
    parser.add_argument("--output-dir", type=str, required=True, help="输出目录")
    parser.add_argument("--run-id", type=str, help="运行ID（用于过滤信号）")
    parser.add_argument("--symbols", type=str, default="BTCUSDT,ETHUSDT", help="交易对（逗号分隔）")
    parser.add_argument("--minutes", type=int, default=120, help="处理分钟数（默认120分钟）")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 设置环境变量
    os.environ["V13_SIGNAL_V2"] = "1"
    os.environ["V13_SINK"] = "dual"
    os.environ["V13_OUTPUT_DIR"] = str(output_dir)
    if args.run_id:
        os.environ["RUN_ID"] = args.run_id
    
    logger.info(f"[backtest_verify] Starting verification")
    logger.info(f"[backtest_verify] Data dir: {args.data_dir}")
    logger.info(f"[backtest_verify] Output dir: {output_dir}")
    logger.info(f"[backtest_verify] Run ID: {args.run_id}")
    logger.info(f"[backtest_verify] Symbols: {args.symbols}")
    logger.info(f"[backtest_verify] Minutes: {args.minutes}")
    
    # 注意：此脚本假设信号已经通过 replay_harness 或 orchestrator 生成
    # 如果信号尚未生成，请先运行回测脚本（如 scripts/run_t1_backtest_signal_v2.ps1）
    
    # 查找信号文件（replay_harness 输出到 output_dir/run_id/signals/）
    # 优先查找包含 run_id 的子目录，否则查找最新的回测输出目录
    jsonl_dir = None
    db_path = None
    
    # 查找包含 run_id 的子目录
    if args.run_id:
        run_id_dirs = list(output_dir.glob(f"*{args.run_id}*"))
        if run_id_dirs:
            for run_dir in run_id_dirs:
                signals_dir = run_dir / "signals" / "ready" / "signal"
                if signals_dir.exists():
                    jsonl_dir = signals_dir
                    db_path = run_dir / "signals" / "signals_v2.db"
                    break
    
    # 如果没有找到，查找最新的回测输出目录（以 backtest_ 开头，按修改时间排序）
    if jsonl_dir is None:
        backtest_dirs = [
            d for d in output_dir.iterdir() 
            if d.is_dir() and d.name.startswith("backtest_")
        ]
        if backtest_dirs:
            # 按修改时间排序，最新的在前
            backtest_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            for run_dir in backtest_dirs:
                signals_dir = run_dir / "signals" / "ready" / "signal"
                if signals_dir.exists():
                    jsonl_dir = signals_dir
                    db_path = run_dir / "signals" / "signals_v2.db"
                    logger.info(f"[backtest_verify] Using latest backtest directory: {run_dir.name}")
                    break
    
    # 如果还是没找到，尝试查找任何包含 signals 的子目录（按修改时间排序）
    if jsonl_dir is None:
        subdirs = [d for d in output_dir.iterdir() if d.is_dir()]
        subdirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        for subdir in subdirs:
            signals_dir = subdir / "signals" / "ready" / "signal"
            if signals_dir.exists():
                jsonl_dir = signals_dir
                db_path = subdir / "signals" / "signals_v2.db"
                break
    
    # 如果还是没找到，使用默认路径
    if jsonl_dir is None:
        jsonl_dir = output_dir / "ready" / "signal"
        db_path = output_dir / "signals_v2.db"
    
    logger.info(f"[backtest_verify] JSONL directory: {jsonl_dir}")
    logger.info(f"[backtest_verify] SQLite database: {db_path}")
    
    logger.info("[backtest_verify] Loading JSONL signals...")
    # 如果指定了 run_id，但找不到匹配的目录，尝试不传 run_id 让脚本自动从信号中提取
    jsonl_signals = load_jsonl_signals(jsonl_dir, None)  # 先加载所有信号
    logger.info(f"[backtest_verify] Loaded {len(jsonl_signals)} JSONL signals (before filtering)")
    
    # 如果指定了 run_id，过滤信号
    if args.run_id:
        jsonl_signals = [s for s in jsonl_signals if s.get("run_id") == args.run_id]
        logger.info(f"[backtest_verify] Filtered to {len(jsonl_signals)} signals matching run_id={args.run_id}")
    
    logger.info("[backtest_verify] Loading SQLite signals...")
    # 同样，先加载所有信号，再过滤
    sqlite_signals = load_sqlite_signals(db_path, None)
    logger.info(f"[backtest_verify] Loaded {len(sqlite_signals)} SQLite signals (before filtering)")
    
    # 如果指定了 run_id，过滤信号
    if args.run_id:
        sqlite_signals = [s for s in sqlite_signals if s.get("run_id") == args.run_id]
        logger.info(f"[backtest_verify] Filtered to {len(sqlite_signals)} signals matching run_id={args.run_id}")
    
    if not jsonl_signals and not sqlite_signals:
        logger.error("[backtest_verify] No signals found! Please run backtest first.")
        return 1
    
    # 计算统计信息
    logger.info("[backtest_verify] Calculating statistics...")
    jsonl_stats = calculate_statistics(jsonl_signals)
    sqlite_stats = calculate_statistics(sqlite_signals)
    
    # 验证契约一致性
    logger.info("[backtest_verify] Verifying contract consistency...")
    jsonl_contract = verify_contract_consistency(jsonl_signals)
    sqlite_contract = verify_contract_consistency(sqlite_signals)
    
    # 验证双 Sink 一致性
    logger.info("[backtest_verify] Verifying dual sink consistency...")
    dual_sink_consistency = verify_dual_sink_consistency(jsonl_signals, sqlite_signals)
    
    # 生成报告
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": args.run_id,
        "symbols": args.symbols.split(","),
        "minutes": args.minutes,
        "jsonl_statistics": jsonl_stats,
        "sqlite_statistics": sqlite_stats,
        "jsonl_contract_verification": jsonl_contract,
        "sqlite_contract_verification": sqlite_contract,
        "dual_sink_consistency": dual_sink_consistency,
    }
    
    # 保存报告
    report_path = output_dir / "report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    logger.info(f"[backtest_verify] Report saved to {report_path}")
    
    # 打印摘要
    print("\n" + "=" * 80)
    print("回测验证摘要")
    print("=" * 80)
    print(f"\nJSONL 统计:")
    print(f"  总信号数: {jsonl_stats['total']}")
    print(f"  确认信号数: {jsonl_stats['confirm_count']}")
    print(f"  确认率: {jsonl_stats['confirm_rate']}%")
    print(f"\n  Decision Code 分布:")
    for code, count in jsonl_stats['decision_code_distribution'].items():
        print(f"    {code}: {count}")
    
    print(f"\nSQLite 统计:")
    print(f"  总信号数: {sqlite_stats['total']}")
    print(f"  确认信号数: {sqlite_stats['confirm_count']}")
    print(f"  确认率: {sqlite_stats['confirm_rate']}%")
    
    print(f"\n契约一致性验证:")
    print(f"  JSONL 错误数: {len(jsonl_contract['errors'])}")
    print(f"  SQLite 错误数: {len(sqlite_contract['errors'])}")
    if jsonl_contract['errors']:
        print(f"  JSONL 错误示例:")
        for error in jsonl_contract['errors'][:5]:
            print(f"    - {error}")
    if sqlite_contract['errors']:
        print(f"  SQLite 错误示例:")
        for error in sqlite_contract['errors'][:5]:
            print(f"    - {error}")
    
    print(f"\n双 Sink 一致性:")
    print(f"  JSONL 数量: {dual_sink_consistency['jsonl_count']}")
    print(f"  SQLite 数量: {dual_sink_consistency['sqlite_count']}")
    print(f"  共同数量: {dual_sink_consistency['common_count']}")
    print(f"  错误数: {len(dual_sink_consistency['errors'])}")
    if dual_sink_consistency['errors']:
        print(f"  错误示例:")
        for error in dual_sink_consistency['errors'][:5]:
            print(f"    - {error}")
    
    print("\n" + "=" * 80)
    
    # 返回状态码
    total_errors = (
        len(jsonl_contract['errors']) +
        len(sqlite_contract['errors']) +
        len(dual_sink_consistency['errors'])
    )
    
    if total_errors > 0:
        logger.error(f"[backtest_verify] Verification failed with {total_errors} errors")
        return 1
    else:
        logger.info("[backtest_verify] Verification passed!")
        return 0


if __name__ == "__main__":
    sys.exit(main())

