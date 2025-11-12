#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T3 Live Small Flow 验证脚本

TASK-A4: 验证交易执行链路完整性、系统稳定性、失败批次补偿
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


def load_jsonl_signals(jsonl_dir: Path) -> List[Dict[str, Any]]:
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
                        signals.append(signal)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON line in {jsonl_file}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Failed to read {jsonl_file}: {e}")
            continue
    
    return signals


def load_execution_logs(output_dir: Path) -> List[Dict[str, Any]]:
    """加载执行日志"""
    exec_logs = []
    exec_log_dir = output_dir / "ready" / "execlog"
    
    if not exec_log_dir.exists():
        logger.warning(f"Execution log directory not found: {exec_log_dir}")
        return exec_logs
    
    jsonl_files = list(exec_log_dir.rglob("*.jsonl"))
    
    for jsonl_file in jsonl_files:
        try:
            with jsonl_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        log_entry = json.loads(line)
                        exec_logs.append(log_entry)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON line in {jsonl_file}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Failed to read {jsonl_file}: {e}")
            continue
    
    return exec_logs


def calculate_signal_statistics(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """计算信号统计信息"""
    if not signals:
        return {
            "total": 0,
            "confirm_count": 0,
            "confirm_rate": 0.0,
            "decision_code_dist": {},
        }
    
    confirm_count = sum(1 for s in signals if s.get("confirm") is True)
    decision_codes = Counter(s.get("decision_code", "UNKNOWN") for s in signals)
    
    return {
        "total": len(signals),
        "confirm_count": confirm_count,
        "confirm_rate": confirm_count / len(signals) if signals else 0.0,
        "decision_code_dist": dict(decision_codes),
    }


def calculate_trading_statistics(exec_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """计算交易统计信息"""
    if not exec_logs:
        return {
            "total_orders": 0,
            "filled_orders": 0,
            "rejected_orders": 0,
            "fill_rate": 0.0,
        }
    
    total_orders = len(exec_logs)
    filled_orders = sum(1 for log in exec_logs if log.get("status") == "FILLED")
    rejected_orders = sum(1 for log in exec_logs if log.get("status") == "REJECTED")
    
    return {
        "total_orders": total_orders,
        "filled_orders": filled_orders,
        "rejected_orders": rejected_orders,
        "fill_rate": filled_orders / total_orders if total_orders > 0 else 0.0,
    }


def check_system_stability(
    jsonl_dir: Path,
    db_path: Path,
    exec_logs: List[Dict[str, Any]],
    run_id: Optional[str] = None,
    minutes: Optional[int] = None
) -> Dict[str, Any]:
    """检查系统稳定性
    
    Args:
        jsonl_dir: JSONL信号目录
        db_path: SQLite数据库路径
        exec_logs: 执行日志列表
        run_id: 可选的run_id过滤（只统计本次运行的数据）
        minutes: 可选的时间窗口过滤（只统计最近N分钟的数据）
    """
    # 检查双 Sink 一致性
    jsonl_exists = jsonl_dir.exists() and any(jsonl_dir.rglob("*.jsonl"))
    sqlite_exists = db_path.exists()
    
    dual_sink_consistent = False
    jsonl_count = 0
    sqlite_count = 0
    
    if jsonl_exists and sqlite_exists:
        jsonl_signals = load_jsonl_signals(jsonl_dir)
        
        # TASK-A4优化: 按run_id或时间窗口过滤，避免历史数据干扰
        if run_id and run_id != "unknown":
            jsonl_signals = [s for s in jsonl_signals if s.get("run_id") == run_id]
            logger.info(f"[t3_verify] Filtered JSONL signals by run_id={run_id}: {len(jsonl_signals)} signals")
        
        if minutes:
            import time
            cutoff_ts_ms = int((time.time() - minutes * 60) * 1000)
            jsonl_signals = [s for s in jsonl_signals if s.get("ts_ms", 0) >= cutoff_ts_ms]
            logger.info(f"[t3_verify] Filtered JSONL signals by time window (last {minutes}min): {len(jsonl_signals)} signals")
        
        jsonl_count = len(jsonl_signals)
        
        try:
            conn = sqlite3.connect(str(db_path))
            # TASK-A4优化: 按run_id或时间窗口过滤SQLite数据
            query = "SELECT COUNT(*) FROM signals"
            conditions = []
            params = []
            
            if run_id and run_id != "unknown":
                conditions.append("run_id = ?")
                params.append(run_id)
            
            if minutes:
                import time
                cutoff_ts_ms = int((time.time() - minutes * 60) * 1000)
                conditions.append("ts_ms >= ?")
                params.append(cutoff_ts_ms)
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            cursor = conn.execute(query, params)
            sqlite_count = cursor.fetchone()[0]
            conn.close()
            
            if run_id and run_id != "unknown":
                logger.info(f"[t3_verify] Filtered SQLite signals by run_id={run_id}: {sqlite_count} signals")
            if minutes:
                logger.info(f"[t3_verify] Filtered SQLite signals by time window (last {minutes}min): {sqlite_count} signals")
        except Exception as e:
            logger.warning(f"Failed to count SQLite signals: {e}")
        
        if jsonl_count > 0:
            diff_pct = abs(jsonl_count - sqlite_count) / jsonl_count * 100
            dual_sink_consistent = diff_pct < 5.0
            logger.info(f"[t3_verify] Dual sink consistency: JSONL={jsonl_count}, SQLite={sqlite_count}, diff={diff_pct:.2f}%")
    
    # 检查 SQLite busy_timeout 问题（通过执行日志中的错误）
    sqlite_busy_timeout_issues = sum(
        1 for log in exec_logs
        if "busy" in str(log.get("error", "")).lower() or
        "timeout" in str(log.get("error", "")).lower()
    )
    
    # 计算写放大比率（简化：SQLite 大小 / JSONL 大小）
    write_amplification_ratio = 1.0
    if sqlite_exists and jsonl_exists:
        try:
            db_size = db_path.stat().st_size
            jsonl_total_size = sum(f.stat().st_size for f in jsonl_dir.rglob("*.jsonl"))
            if jsonl_total_size > 0:
                write_amplification_ratio = db_size / jsonl_total_size
        except Exception as e:
            logger.warning(f"Failed to calculate write amplification: {e}")
    
    # 检查 fsync 轮转稳定性（简化：检查文件数量是否合理）
    fsync_rotation_stable = True
    if jsonl_exists:
        jsonl_files = list(jsonl_dir.rglob("*.jsonl"))
        # 如果文件数量过多或过少，可能有问题
        if len(jsonl_files) > 1000 or len(jsonl_files) == 0:
            fsync_rotation_stable = False
    
    return {
        "dual_sink_consistent": dual_sink_consistent,
        "jsonl_count": jsonl_count,
        "sqlite_count": sqlite_count,
        "sqlite_busy_timeout_issues": sqlite_busy_timeout_issues,
        "write_amplification_ratio": write_amplification_ratio,
        "fsync_rotation_stable": fsync_rotation_stable,
    }


def load_baseline_metrics(baseline_dir: Path) -> Optional[Dict[str, Any]]:
    """加载 T2 测试网基线指标"""
    report_file = baseline_dir / "testnet_report.json"
    if report_file.exists():
        try:
            with report_file.open("r", encoding="utf-8") as f:
                report = json.load(f)
            
            if "signal_stats" in report:
                logger.info(f"[t3_verify] Loaded baseline from {report_file}")
                return report["signal_stats"]
        except Exception as e:
            logger.warning(f"Failed to load baseline report: {e}")
    
    logger.warning(f"[t3_verify] Baseline report not found in {baseline_dir}")
    return None


def compare_with_baseline(
    t3_stats: Dict[str, Any],
    baseline_stats: Optional[Dict[str, Any]],
    threshold_pct: float = 10.0
) -> Dict[str, Any]:
    """对比 T3 结果与 T2 基线"""
    if not baseline_stats:
        return {
            "baseline_found": False,
            "status": "SKIP",
            "alerts": [],
        }
    
    alerts = []
    status = "PASS"
    
    # 对比 confirm rate
    t3_confirm_rate = t3_stats.get("confirm_rate", 0.0)
    baseline_confirm_rate = baseline_stats.get("confirm_rate", 0.0)
    
    if baseline_confirm_rate < 0.001 and t3_confirm_rate < 0.001:
        pass  # 两者都很小，认为一致
    elif baseline_confirm_rate > 0:
        confirm_rate_diff_pct = abs(t3_confirm_rate - baseline_confirm_rate) / baseline_confirm_rate * 100
        if confirm_rate_diff_pct > threshold_pct:
            alerts.append(
                f"Confirm rate deviation: {confirm_rate_diff_pct:.2f}% "
                f"(t3={t3_confirm_rate:.6%}, baseline={baseline_confirm_rate:.6%})"
            )
            status = "ALERT"
    
    if alerts:
        status = "ALERT"
    
    return {
        "baseline_found": True,
        "status": status,
        "confirm_rate_diff": t3_confirm_rate - baseline_confirm_rate,
        "alerts": alerts,
    }


def main():
    parser = argparse.ArgumentParser(description="T3 Live Small Flow 验证")
    parser.add_argument("--output-dir", type=str, required=True, help="输出目录")
    parser.add_argument("--baseline-dir", type=str, help="T2 测试网基线目录")
    parser.add_argument("--symbols", type=str, default="BTCUSDT", help="交易对（逗号分隔）")
    parser.add_argument("--minutes", type=int, default=60, help="运行时长（分钟）")
    parser.add_argument("--run-id", type=str, help="Run ID（用于过滤本次运行的数据，如果不提供则从环境变量或信号中提取）")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 设置环境变量
    os.environ["V13_SIGNAL_V2"] = "1"
    os.environ["V13_SINK"] = "dual"
    
    logger.info(f"[t3_verify] Starting verification")
    logger.info(f"[t3_verify] Output dir: {output_dir}")
    logger.info(f"[t3_verify] Baseline dir: {args.baseline_dir}")
    logger.info(f"[t3_verify] Symbols: {args.symbols}")
    logger.info(f"[t3_verify] Minutes: {args.minutes}")
    
    # 查找信号文件
    jsonl_dir = output_dir / "ready" / "signal"
    db_path = output_dir / "signals_v2.db"
    
    logger.info(f"[t3_verify] JSONL directory: {jsonl_dir}")
    logger.info(f"[t3_verify] SQLite database: {db_path}")
    
    # 获取run_id（用于过滤本次运行的数据）
    # TASK-A4优化: 优先使用命令行参数，然后环境变量，最后从信号中提取
    run_id = args.run_id or os.getenv("RUN_ID")
    
    # 如果还没有run_id，尝试从信号中提取最新的run_id
    if not run_id or run_id == "unknown":
        jsonl_files = list(jsonl_dir.rglob("*.jsonl")) if jsonl_dir.exists() else []
        if jsonl_files:
            try:
                # 读取最新的JSONL文件，提取run_id
                latest_file = max(jsonl_files, key=lambda p: p.stat().st_mtime)
                with latest_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            signal = json.loads(line)
                            if "run_id" in signal:
                                run_id = signal["run_id"]
                                logger.info(f"[t3_verify] Extracted run_id from signals: {run_id}")
                                break
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.warning(f"[t3_verify] Failed to extract run_id from signals: {e}")
    
    if not run_id:
        run_id = "unknown"
        logger.warning(f"[t3_verify] Run ID not found, will not filter by run_id (may include historical data)")
    else:
        logger.info(f"[t3_verify] Run ID: {run_id}")
    
    # 加载信号
    logger.info("[t3_verify] Loading JSONL signals...")
    jsonl_signals = load_jsonl_signals(jsonl_dir)
    logger.info(f"[t3_verify] Loaded {len(jsonl_signals)} JSONL signals (total)")
    
    # TASK-A4优化: 按run_id过滤信号（只统计本次运行的数据）
    if run_id != "unknown":
        jsonl_signals_filtered = [s for s in jsonl_signals if s.get("run_id") == run_id]
        logger.info(f"[t3_verify] Filtered by run_id={run_id}: {len(jsonl_signals_filtered)} signals")
        jsonl_signals = jsonl_signals_filtered
    
    # 计算信号统计
    signal_stats = calculate_signal_statistics(jsonl_signals)
    
    # 加载执行日志
    logger.info("[t3_verify] Loading execution logs...")
    exec_logs = load_execution_logs(output_dir)
    logger.info(f"[t3_verify] Loaded {len(exec_logs)} execution log entries")
    
    # 计算交易统计
    trading_stats = calculate_trading_statistics(exec_logs)
    
    # 检查系统稳定性（传入run_id和minutes用于过滤）
    system_stability = check_system_stability(jsonl_dir, db_path, exec_logs, run_id=run_id, minutes=args.minutes)
    
    # 加载基线并对比
    baseline_comparison = {}
    if args.baseline_dir:
        baseline_dir = Path(args.baseline_dir)
        baseline_stats = load_baseline_metrics(baseline_dir)
        baseline_comparison = compare_with_baseline(signal_stats, baseline_stats)
    else:
        baseline_comparison = {"baseline_found": False, "status": "SKIP"}
    
    # 生成报告
    report = {
        "t3_run_id": os.getenv("RUN_ID", "unknown"),
        "symbols": args.symbols.split(","),
        "minutes": args.minutes,
        "signal_stats": signal_stats,
        "trading_stats": trading_stats,
        "system_stability": system_stability,
        "baseline_comparison": baseline_comparison,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # 保存报告
    report_file = output_dir / "t3_report.json"
    with report_file.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    logger.info(f"[t3_verify] Report saved to {report_file}")
    
    # 检查验证结果
    if baseline_comparison.get("status") == "ALERT":
        logger.warning("[t3_verify] Baseline comparison alerts detected")
        return 1
    
    if not system_stability.get("dual_sink_consistent", False):
        logger.warning("[t3_verify] Dual sink consistency check failed")
        return 1
    
    if system_stability.get("sqlite_busy_timeout_issues", 0) > 10:
        logger.warning(f"[t3_verify] SQLite busy_timeout issues detected: {system_stability['sqlite_busy_timeout_issues']}")
        return 1
    
    logger.info("[t3_verify] Verification passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())


