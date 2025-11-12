#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Signal v2 测试网验证脚本

TASK-A4: 测试网验证 - 执行链路完整性/健康探针/基线对比
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


def load_sqlite_signals(db_path: Path) -> List[Dict[str, Any]]:
    """加载 SQLite 信号"""
    signals = []
    
    if not db_path.exists():
        logger.warning(f"SQLite database not found: {db_path}")
        return signals
    
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        
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


def find_latest_backtest_dir(baseline_dir: Path) -> Optional[Path]:
    """查找最新的回测目录"""
    if not baseline_dir.exists():
        return None
    
    backtest_dirs = [
        d for d in baseline_dir.iterdir() 
        if d.is_dir() and d.name.startswith("backtest_")
    ]
    
    if not backtest_dirs:
        return None
    
    # 按修改时间排序，最新的在前
    backtest_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return backtest_dirs[0]


def load_baseline_metrics(baseline_dir: Path) -> Optional[Dict[str, Any]]:
    """加载回测基线指标"""
    # 首先尝试直接从 baseline_dir 加载报告
    report_file = baseline_dir / "report.json"
    if report_file.exists():
        try:
            with report_file.open("r", encoding="utf-8") as f:
                report = json.load(f)
            
            # 提取 JSONL 统计信息作为基线（兼容不同的字段名）
            baseline_stats = None
            if "jsonl_stats" in report:
                baseline_stats = report["jsonl_stats"]
            elif "jsonl_statistics" in report:
                baseline_stats = report["jsonl_statistics"]
            
            if baseline_stats:
                # 统一字段名（decision_code_dist vs decision_code_distribution）
                if "decision_code_distribution" in baseline_stats:
                    baseline_stats["decision_code_dist"] = baseline_stats.pop("decision_code_distribution")
                logger.info(f"[testnet_verify] Loaded baseline from {report_file}")
                return baseline_stats
        except Exception as e:
            logger.warning(f"Failed to load baseline report from {report_file}: {e}")
    
    # 如果直接路径不存在，尝试查找最新的回测目录
    backtest_dir = find_latest_backtest_dir(baseline_dir)
    if backtest_dir:
        # 回测目录的报告可能在 backtest_dir 的父目录
        parent_report = baseline_dir / "report.json"
        if parent_report.exists():
            try:
                with parent_report.open("r", encoding="utf-8") as f:
                    report = json.load(f)
                
                baseline_stats = None
                if "jsonl_stats" in report:
                    baseline_stats = report["jsonl_stats"]
                elif "jsonl_statistics" in report:
                    baseline_stats = report["jsonl_statistics"]
                
                if baseline_stats:
                    # 统一字段名（decision_code_dist vs decision_code_distribution）
                    if "decision_code_distribution" in baseline_stats:
                        baseline_stats["decision_code_dist"] = baseline_stats.pop("decision_code_distribution")
                    logger.info(f"[testnet_verify] Loaded baseline from {parent_report}")
                    return baseline_stats
            except Exception as e:
                logger.warning(f"Failed to load baseline report from {parent_report}: {e}")
    
    logger.warning(f"[testnet_verify] Baseline report not found in {baseline_dir}")
    return None


def compare_with_baseline(
    testnet_stats: Dict[str, Any],
    baseline_stats: Optional[Dict[str, Any]],
    threshold_pct: float = 10.0
) -> Dict[str, Any]:
    """对比测试网结果与回测基线"""
    if not baseline_stats:
        return {
            "baseline_found": False,
            "status": "SKIP",
            "alerts": [],
        }
    
    alerts = []
    status = "PASS"
    
    # 对比 confirm rate
    testnet_confirm_rate = testnet_stats.get("confirm_rate", 0.0)
    baseline_confirm_rate = baseline_stats.get("confirm_rate", 0.0)
    
    # 如果两者都很小（<0.1%），认为是一致的
    if baseline_confirm_rate < 0.001 and testnet_confirm_rate < 0.001:
        # 两者都很小，认为一致
        pass
    elif baseline_confirm_rate > 0:
        confirm_rate_diff_pct = abs(testnet_confirm_rate - baseline_confirm_rate) / baseline_confirm_rate * 100
        if confirm_rate_diff_pct > threshold_pct:
            alerts.append(
                f"Confirm rate deviation: {confirm_rate_diff_pct:.2f}% "
                f"(testnet={testnet_confirm_rate:.6%}, baseline={baseline_confirm_rate:.6%})"
            )
            status = "ALERT"
    else:
        # 如果基线 confirm rate 为 0，但测试网有确认信号，且确认率 > 0.1%，才报警
        if testnet_confirm_rate > 0.001:
            alerts.append(
                f"Testnet has confirm signals ({testnet_confirm_rate:.6%}) but baseline had none"
            )
            status = "ALERT"
    
    # 对比 decision code 分布（按比例对比，而不是绝对数量）
    testnet_dist = testnet_stats.get("decision_code_dist", {})
    baseline_dist = baseline_stats.get("decision_code_dist", {})
    
    testnet_total = testnet_stats.get("total", 1)
    baseline_total = baseline_stats.get("total", 1)
    
    for code in set(list(testnet_dist.keys()) + list(baseline_dist.keys())):
        testnet_count = testnet_dist.get(code, 0)
        baseline_count = baseline_dist.get(code, 0)
        
        # 计算比例
        testnet_ratio = testnet_count / testnet_total if testnet_total > 0 else 0.0
        baseline_ratio = baseline_count / baseline_total if baseline_total > 0 else 0.0
        
        # 如果基线比例 > 0.1%，才进行对比
        if baseline_ratio > 0.001:
            ratio_diff_pct = abs(testnet_ratio - baseline_ratio) / baseline_ratio * 100
            if ratio_diff_pct > threshold_pct * 2:  # Decision code 分布允许更大的偏差
                alerts.append(
                    f"Decision code {code} ratio deviation: {ratio_diff_pct:.2f}% "
                    f"(testnet={testnet_ratio:.4%}, baseline={baseline_ratio:.4%})"
                )
                status = "ALERT"
    
    if alerts:
        status = "ALERT"
    
    return {
        "baseline_found": True,
        "status": status,
        "confirm_rate_diff": testnet_confirm_rate - baseline_confirm_rate,
        "confirm_rate_diff_pct": abs(testnet_confirm_rate - baseline_confirm_rate) / baseline_confirm_rate * 100 if baseline_confirm_rate > 0 else 0.0,
        "alerts": alerts,
    }


def check_health(jsonl_dir: Path, db_path: Path) -> Dict[str, Any]:
    """检查健康状态"""
    jsonl_exists = jsonl_dir.exists() and any(jsonl_dir.rglob("*.jsonl"))
    sqlite_exists = db_path.exists()
    
    # 检查双 Sink 一致性
    dual_sink_consistent = False
    if jsonl_exists and sqlite_exists:
        jsonl_signals = load_jsonl_signals(jsonl_dir)
        sqlite_signals = load_sqlite_signals(db_path)
        
        jsonl_count = len(jsonl_signals)
        sqlite_count = len(sqlite_signals)
        
        # 允许 5% 的差异（由于批处理队列刷新时机）
        if jsonl_count > 0:
            diff_pct = abs(jsonl_count - sqlite_count) / jsonl_count * 100
            dual_sink_consistent = diff_pct < 5.0
        else:
            dual_sink_consistent = jsonl_count == sqlite_count
    
    return {
        "jsonl_exists": jsonl_exists,
        "sqlite_exists": sqlite_exists,
        "dual_sink_consistent": dual_sink_consistent,
    }


def main():
    parser = argparse.ArgumentParser(description="Signal v2 测试网验证")
    parser.add_argument("--output-dir", type=str, required=True, help="输出目录")
    parser.add_argument("--baseline-dir", type=str, help="回测基线目录")
    parser.add_argument("--symbols", type=str, default="BTCUSDT,ETHUSDT", help="交易对（逗号分隔）")
    parser.add_argument("--minutes", type=int, default=45, help="运行时长（分钟）")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 设置环境变量
    os.environ["V13_SIGNAL_V2"] = "1"
    os.environ["V13_SINK"] = "dual"
    
    logger.info(f"[testnet_verify] Starting verification")
    logger.info(f"[testnet_verify] Output dir: {output_dir}")
    logger.info(f"[testnet_verify] Baseline dir: {args.baseline_dir}")
    logger.info(f"[testnet_verify] Symbols: {args.symbols}")
    logger.info(f"[testnet_verify] Minutes: {args.minutes}")
    
    # 查找信号文件（orchestrator 输出到 output_dir/ready/signal/）
    jsonl_dir = output_dir / "ready" / "signal"
    db_path = output_dir / "signals_v2.db"
    
    logger.info(f"[testnet_verify] JSONL directory: {jsonl_dir}")
    logger.info(f"[testnet_verify] SQLite database: {db_path}")
    
    # 加载信号
    logger.info("[testnet_verify] Loading JSONL signals...")
    jsonl_signals = load_jsonl_signals(jsonl_dir)
    logger.info(f"[testnet_verify] Loaded {len(jsonl_signals)} JSONL signals")
    
    logger.info("[testnet_verify] Loading SQLite signals...")
    sqlite_signals = load_sqlite_signals(db_path)
    logger.info(f"[testnet_verify] Loaded {len(sqlite_signals)} SQLite signals")
    
    if not jsonl_signals and not sqlite_signals:
        logger.error("[testnet_verify] No signals found!")
        return 1
    
    # 计算统计信息（使用 JSONL，因为它更完整）
    signal_stats = calculate_statistics(jsonl_signals)
    
    # 加载基线并对比
    baseline_comparison = {}
    if args.baseline_dir:
        baseline_dir = Path(args.baseline_dir)
        baseline_stats = load_baseline_metrics(baseline_dir)
        baseline_comparison = compare_with_baseline(signal_stats, baseline_stats)
    else:
        baseline_comparison = {"baseline_found": False, "status": "SKIP"}
    
    # 健康检查
    health_checks = check_health(jsonl_dir, db_path)
    
    # 生成报告
    report = {
        "testnet_run_id": os.getenv("RUN_ID", "unknown"),
        "symbols": args.symbols.split(","),
        "minutes": args.minutes,
        "signal_stats": signal_stats,
        "baseline_comparison": baseline_comparison,
        "health_checks": health_checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # 保存报告
    report_file = output_dir / "testnet_report.json"
    with report_file.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    logger.info(f"[testnet_verify] Report saved to {report_file}")
    
    # 检查验证结果
    if baseline_comparison.get("status") == "ALERT":
        logger.warning("[testnet_verify] Baseline comparison alerts detected")
        return 1
    
    if not health_checks.get("dual_sink_consistent", False):
        logger.warning("[testnet_verify] Dual sink consistency check failed")
        return 1
    
    logger.info("[testnet_verify] Verification passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())

