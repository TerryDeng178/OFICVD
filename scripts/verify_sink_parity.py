#!/usr/bin/env python3
"""P2: 小型"对账器"脚本，固化到CI"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

def load_jsonl_signals(jsonl_dir: Path, run_id: Optional[str] = None) -> Dict[tuple, Dict]:
    """加载JSONL信号，使用(run_id, ts_ms, symbol)作为key"""
    signals = {}
    jsonl_files = sorted(jsonl_dir.rglob("*.jsonl"))
    for jsonl_file in jsonl_files:
        try:
            with jsonl_file.open("r", encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        signal = json.loads(line)
                        # P0: 如果提供了run_id，只统计匹配的run_id
                        signal_run_id = signal.get("run_id", "")
                        if run_id and signal_run_id != run_id:
                            continue
                        ts_ms = int(signal.get("ts_ms", 0))
                        symbol = signal.get("symbol", "")
                        if ts_ms > 0 and symbol:
                            # 使用(run_id, ts_ms, symbol)作为key，避免同一ts_ms不同symbol的记录被覆盖
                            key = (signal_run_id, ts_ms, symbol)
                            signals[key] = signal
                    except (json.JSONDecodeError, ValueError, KeyError):
                        continue
        except Exception as e:
            print(f"[WARN] 读取JSONL文件失败 {jsonl_file}: {e}", file=sys.stderr)
            continue
    return signals

def load_sqlite_signals(sqlite_db: Path, run_id: Optional[str] = None) -> Dict[tuple, Dict]:
    """加载SQLite信号，使用(run_id, ts_ms, symbol)作为key"""
    import sqlite3
    signals = {}
    try:
        conn = sqlite3.connect(str(sqlite_db))
        cursor = conn.cursor()
        
        # P0: 如果提供了run_id，只统计匹配的run_id
        if run_id:
            cursor.execute("""
                SELECT ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, 
                       signal_type, confirm, gating, guard_reason, run_id
                FROM signals
                WHERE run_id = ?
            """, (run_id,))
        else:
            cursor.execute("""
                SELECT ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, 
                       signal_type, confirm, gating, guard_reason, run_id
                FROM signals
            """)
        
        for row in cursor.fetchall():
            ts_ms, symbol, score, z_ofi, z_cvd, regime, div_type, signal_type, confirm, gating, guard_reason, run_id_val = row
            if ts_ms > 0 and symbol:
                # 使用(run_id, ts_ms, symbol)作为key，避免同一ts_ms不同symbol的记录被覆盖
                key = (run_id_val or "", ts_ms, symbol)
                signals[key] = {
                    "ts_ms": ts_ms,
                    "symbol": symbol,
                    "score": score,
                    "z_ofi": z_ofi,
                    "z_cvd": z_cvd,
                    "regime": regime,
                    "div_type": div_type,
                    "signal_type": signal_type,
                    "confirm": bool(confirm),
                    "gating": bool(gating),
                    "guard_reason": guard_reason,
                    "run_id": run_id_val
                }
        conn.close()
    except Exception as e:
        print(f"[ERROR] 读取SQLite数据库失败: {e}", file=sys.stderr)
        return signals
    return signals

def calculate_stats(signals: Dict[tuple, Dict]) -> Dict:
    """计算统计信息"""
    total = len(signals)
    confirmed = sum(1 for s in signals.values() if s.get("confirm"))
    strong = sum(1 for s in signals.values() if s.get("signal_type") in ("strong_buy", "strong_sell"))
    return {
        "total": total,
        "confirmed": confirmed,
        "strong": strong,
        "strong_ratio": strong / total if total > 0 else 0.0
    }

def calculate_per_minute_stats(signals: Dict[tuple, Dict]) -> Dict[str, Dict]:
    """P1: 按分钟统计信号数量"""
    from datetime import datetime, timezone
    
    per_minute: Dict[str, Dict] = defaultdict(lambda: {"jsonl": 0, "sqlite": 0})
    
    for signal in signals.values():
        ts_ms = signal.get("ts_ms", 0)
        if ts_ms > 0:
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            minute = dt.strftime("%Y%m%d_%H%M")
            # 这里只统计总量，实际调用时会分别传入jsonl和sqlite的signals
            per_minute[minute]["total"] = per_minute[minute].get("total", 0) + 1
    
    return per_minute

def calculate_window_alignment(jsonl_signals: Dict[tuple, Dict], sqlite_signals: Dict[tuple, Dict]) -> Dict:
    """P1: 计算窗口对齐信息"""
    from datetime import datetime, timezone
    
    # 提取所有分钟
    jsonl_minutes = set()
    sqlite_minutes = set()
    
    for signal in jsonl_signals.values():
        ts_ms = signal.get("ts_ms", 0)
        if ts_ms > 0:
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            minute = dt.strftime("%Y%m%d_%H%M")
            jsonl_minutes.add(minute)
    
    for signal in sqlite_signals.values():
        ts_ms = signal.get("ts_ms", 0)
        if ts_ms > 0:
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            minute = dt.strftime("%Y%m%d_%H%M")
            sqlite_minutes.add(minute)
    
    # 计算交集和重叠
    overlap_minutes = sorted(jsonl_minutes & sqlite_minutes)
    jsonl_only = sorted(jsonl_minutes - sqlite_minutes)
    sqlite_only = sorted(sqlite_minutes - jsonl_minutes)
    
    # 确定状态
    if len(jsonl_minutes) == 0 and len(sqlite_minutes) == 0:
        status = "empty"
    elif len(overlap_minutes) == 0:
        status = "no_overlap"
    elif len(jsonl_only) > 0 or len(sqlite_only) > 0:
        status = "partial_overlap"
    else:
        status = "full_overlap"
    
    # P1: 收敛报告限流，避免artifact过大（只保留汇总计数，移除大数组）
    return {
        "status": status,
        "first_minute": overlap_minutes[0] if overlap_minutes else None,
        "last_minute": overlap_minutes[-1] if overlap_minutes else None,
        "overlap_minutes": len(overlap_minutes),
        "jsonl_only_minutes": len(jsonl_only),
        "sqlite_only_minutes": len(sqlite_only),
        "jsonl_total_minutes": len(jsonl_minutes),  # 只保留计数，不保留完整数组
        "sqlite_total_minutes": len(sqlite_minutes)  # 只保留计数，不保留完整数组
    }

def calculate_top_minute_diffs(jsonl_signals: Dict[tuple, Dict], sqlite_signals: Dict[tuple, Dict], top_n: int = 10) -> List[Dict]:
    """P1: 计算逐分钟差异Top-N"""
    from datetime import datetime, timezone
    from collections import defaultdict
    
    # 按分钟统计
    jsonl_per_minute: Dict[str, int] = defaultdict(int)
    sqlite_per_minute: Dict[str, int] = defaultdict(int)
    
    for signal in jsonl_signals.values():
        ts_ms = signal.get("ts_ms", 0)
        if ts_ms > 0:
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            minute = dt.strftime("%Y%m%d_%H%M")
            jsonl_per_minute[minute] += 1
    
    for signal in sqlite_signals.values():
        ts_ms = signal.get("ts_ms", 0)
        if ts_ms > 0:
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            minute = dt.strftime("%Y%m%d_%H%M")
            sqlite_per_minute[minute] += 1
    
    # 计算所有分钟的交集
    all_minutes = set(jsonl_per_minute.keys()) | set(sqlite_per_minute.keys())
    
    # 计算差异
    minute_diffs = []
    for minute in all_minutes:
        jsonl_count = jsonl_per_minute.get(minute, 0)
        sqlite_count = sqlite_per_minute.get(minute, 0)
        diff = abs(jsonl_count - sqlite_count)
        avg_count = (jsonl_count + sqlite_count) / 2.0
        diff_pct = (diff / max(avg_count, 1)) * 100 if avg_count > 0 else 0.0
        
        minute_diffs.append({
            "minute": minute,
            "jsonl_count": jsonl_count,
            "sqlite_count": sqlite_count,
            "diff": diff,
            "diff_pct": diff_pct
        })
    
    # 按差异百分比排序，取Top-N
    minute_diffs.sort(key=lambda x: x["diff_pct"], reverse=True)
    return minute_diffs[:top_n]

def calculate_threshold_exceeded_minutes(jsonl_signals: Dict[tuple, Dict], sqlite_signals: Dict[tuple, Dict], threshold_pct: float) -> List[Dict]:
    """P1: 计算超过阈值的分钟清单"""
    from datetime import datetime, timezone
    from collections import defaultdict
    
    # 按分钟统计
    jsonl_per_minute: Dict[str, int] = defaultdict(int)
    sqlite_per_minute: Dict[str, int] = defaultdict(int)
    
    for signal in jsonl_signals.values():
        ts_ms = signal.get("ts_ms", 0)
        if ts_ms > 0:
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            minute = dt.strftime("%Y%m%d_%H%M")
            jsonl_per_minute[minute] += 1
    
    for signal in sqlite_signals.values():
        ts_ms = signal.get("ts_ms", 0)
        if ts_ms > 0:
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            minute = dt.strftime("%Y%m%d_%H%M")
            sqlite_per_minute[minute] += 1
    
    # 计算所有分钟的交集
    all_minutes = set(jsonl_per_minute.keys()) | set(sqlite_per_minute.keys())
    
    # 找出超过阈值的分钟
    exceeded_minutes = []
    for minute in sorted(all_minutes):
        jsonl_count = jsonl_per_minute.get(minute, 0)
        sqlite_count = sqlite_per_minute.get(minute, 0)
        diff = abs(jsonl_count - sqlite_count)
        avg_count = (jsonl_count + sqlite_count) / 2.0
        diff_pct = (diff / max(avg_count, 1)) * 100 if avg_count > 0 else 0.0
        
        if diff_pct > threshold_pct:
            exceeded_minutes.append({
                "minute": minute,
                "jsonl_count": jsonl_count,
                "sqlite_count": sqlite_count,
                "diff": diff,
                "diff_pct": diff_pct
            })
    
    return exceeded_minutes

def main():
    parser = argparse.ArgumentParser(description="P2: 小型对账器脚本（CI固化）")
    parser.add_argument("--jsonl-dir", type=str, default="./runtime/ready/signal", help="JSONL信号目录")
    parser.add_argument("--sqlite-db", type=str, default="./runtime/signals.db", help="SQLite数据库路径")
    parser.add_argument("--run-id", type=str, default=None, help="运行ID（用于按run_id对账）")
    parser.add_argument("--threshold", type=float, default=0.25, help="偏差阈值（百分比，默认0.25%，P1收紧）")
    parser.add_argument("--output", type=str, default=None, help="输出JSON文件路径（可选）")
    parser.add_argument("--top-n", type=int, default=10, help="Top-N分钟差异（默认10）")
    
    args = parser.parse_args()
    
    jsonl_dir = Path(args.jsonl_dir)
    sqlite_db = Path(args.sqlite_db)
    
    if not jsonl_dir.exists():
        print(f"[ERROR] JSONL目录不存在: {jsonl_dir}", file=sys.stderr)
        return 1
    
    if not sqlite_db.exists():
        print(f"[ERROR] SQLite数据库不存在: {sqlite_db}", file=sys.stderr)
        return 1
    
    print(f"[INFO] 加载JSONL信号（run_id={args.run_id or 'ALL'}）...")
    jsonl_signals = load_jsonl_signals(jsonl_dir, args.run_id)
    jsonl_stats = calculate_stats(jsonl_signals)
    
    print(f"[INFO] 加载SQLite信号（run_id={args.run_id or 'ALL'}）...")
    sqlite_signals = load_sqlite_signals(sqlite_db, args.run_id)
    sqlite_stats = calculate_stats(sqlite_signals)
    
    # 计算差异
    total_diff_pct = abs(jsonl_stats["total"] - sqlite_stats["total"]) / max(jsonl_stats["total"], 1) * 100
    confirm_diff_pct = abs(jsonl_stats["confirmed"] - sqlite_stats["confirmed"]) / max(jsonl_stats["confirmed"], 1) * 100 if jsonl_stats["confirmed"] > 0 else 0.0
    strong_ratio_diff_pct = abs(jsonl_stats["strong_ratio"] - sqlite_stats["strong_ratio"]) * 100
    
    # P1: 计算窗口对齐
    window_alignment = calculate_window_alignment(jsonl_signals, sqlite_signals)
    
    # P1: 计算Top-N分钟差异
    top_minute_diffs = calculate_top_minute_diffs(jsonl_signals, sqlite_signals, args.top_n)
    
    # P1: 计算超过阈值的分钟
    threshold_exceeded_minutes = calculate_threshold_exceeded_minutes(jsonl_signals, sqlite_signals, args.threshold)
    
    # 输出结果
    result = {
        "jsonl_stats": jsonl_stats,
        "sqlite_stats": sqlite_stats,
        "differences": {
            "total_diff_pct": total_diff_pct,
            "confirm_diff_pct": confirm_diff_pct,
            "strong_ratio_diff_pct": strong_ratio_diff_pct
        },
        "threshold": args.threshold,
        "passed": (
            total_diff_pct < args.threshold and
            confirm_diff_pct < args.threshold and
            strong_ratio_diff_pct < args.threshold
        ),
        # P1: 新增字段
        "window_alignment": window_alignment,
        "top_minute_diffs": top_minute_diffs,
        "threshold_exceeded_minutes": threshold_exceeded_minutes
    }
    
    # 打印结果
    print()
    print("=" * 80)
    print("对账结果")
    print("=" * 80)
    print(f"JSONL - 总量: {jsonl_stats['total']}, 确认: {jsonl_stats['confirmed']}, 强信号: {jsonl_stats['strong']}, 强信号占比: {jsonl_stats['strong_ratio']:.2%}")
    print(f"SQLite - 总量: {sqlite_stats['total']}, 确认: {sqlite_stats['confirmed']}, 强信号: {sqlite_stats['strong']}, 强信号占比: {sqlite_stats['strong_ratio']:.2%}")
    print()
    print(f"差异统计:")
    print(f"  总量差异: {total_diff_pct:.4f}% {'[PASS]' if total_diff_pct < args.threshold else '[FAIL]'}")
    print(f"  确认量差异: {confirm_diff_pct:.4f}% {'[PASS]' if confirm_diff_pct < args.threshold else '[FAIL]'}")
    print(f"  强信号占比差异: {strong_ratio_diff_pct:.4f}% {'[PASS]' if strong_ratio_diff_pct < args.threshold else '[FAIL]'}")
    print()
    print(f"窗口对齐:")
    print(f"  状态: {window_alignment['status']}")
    print(f"  重叠分钟数: {window_alignment['overlap_minutes']}")
    print(f"  第一个分钟: {window_alignment['first_minute']}")
    print(f"  最后一个分钟: {window_alignment['last_minute']}")
    print(f"  JSONL独有分钟数: {window_alignment['jsonl_only_minutes']}")
    print(f"  SQLite独有分钟数: {window_alignment['sqlite_only_minutes']}")
    print()
    if top_minute_diffs:
        print(f"Top-{args.top_n}分钟差异:")
        for i, diff in enumerate(top_minute_diffs[:5], 1):  # 只显示前5个
            print(f"  {i}. {diff['minute']}: JSONL={diff['jsonl_count']}, SQLite={diff['sqlite_count']}, 差异={diff['diff_pct']:.4f}%")
    print()
    if threshold_exceeded_minutes:
        print(f"超过阈值({args.threshold}%)的分钟数: {len(threshold_exceeded_minutes)}")
        for diff in threshold_exceeded_minutes[:5]:  # 只显示前5个
            print(f"  {diff['minute']}: JSONL={diff['jsonl_count']}, SQLite={diff['sqlite_count']}, 差异={diff['diff_pct']:.4f}%")
    print()
    print(f"阈值: {args.threshold}%")
    print(f"结果: {'[PASS]' if result['passed'] else '[FAIL]'}")
    print("=" * 80)
    
    # 保存结果
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {output_path}")
    
    return 0 if result['passed'] else 1

if __name__ == "__main__":
    sys.exit(main())
