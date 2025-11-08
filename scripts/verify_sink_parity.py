#!/usr/bin/env python3
"""P2: 小型"对账器"脚本，固化到CI"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Optional

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

def main():
    parser = argparse.ArgumentParser(description="P2: 小型对账器脚本（CI固化）")
    parser.add_argument("--jsonl-dir", type=str, default="./runtime/ready/signal", help="JSONL信号目录")
    parser.add_argument("--sqlite-db", type=str, default="./runtime/signals.db", help="SQLite数据库路径")
    parser.add_argument("--run-id", type=str, default=None, help="运行ID（用于按run_id对账）")
    parser.add_argument("--threshold", type=float, default=0.2, help="偏差阈值（百分比，默认0.2%）")
    parser.add_argument("--output", type=str, default=None, help="输出JSON文件路径（可选）")
    
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
        )
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

