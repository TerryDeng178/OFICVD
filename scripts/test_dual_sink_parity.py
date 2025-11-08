#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双 Sink 等价性测试脚本
比较 JSONL 和 SQLite 的输出，生成 parity_diff.json
"""

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

def load_jsonl_signals(jsonl_dir: Path, start_time: str = None, end_time: str = None, run_id: str = None) -> Dict[int, Dict]:
    """从JSONL文件加载信号，按分钟聚合"""
    minute_stats = defaultdict(lambda: {
        "total": 0,
        "confirmed": 0,
        "strong": 0,
        "buy": 0,
        "sell": 0
    })
    
    # 如果提供了时间范围，计算时间戳范围
    start_ts_ms = None
    end_ts_ms = None
    if start_time and end_time:
        try:
            from datetime import datetime
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            start_ts_ms = int(start_dt.timestamp() * 1000)
            end_ts_ms = int(end_dt.timestamp() * 1000)
        except Exception:
            pass
    
    jsonl_files = sorted(jsonl_dir.rglob("*.jsonl"))
    
    for jsonl_file in jsonl_files:
        try:
            with jsonl_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        signal = json.loads(line)
                        ts_ms = signal.get("ts_ms", 0)
                        
                        # P0: 如果提供了run_id，只统计匹配的run_id
                        if run_id and signal.get("run_id") != run_id:
                            continue
                        
                        # 如果提供了时间范围，过滤信号
                        if start_ts_ms is not None and end_ts_ms is not None:
                            if ts_ms < start_ts_ms or ts_ms > end_ts_ms:
                                continue
                        
                        minute = ts_ms // 60000  # 转换为分钟
                        
                        minute_stats[minute]["total"] += 1
                        
                        if signal.get("confirm", 0) == 1:
                            minute_stats[minute]["confirmed"] += 1
                            
                            signal_type = signal.get("signal_type", "").lower()
                            if "strong" in signal_type:
                                minute_stats[minute]["strong"] += 1
                            
                            if "buy" in signal_type:
                                minute_stats[minute]["buy"] += 1
                            elif "sell" in signal_type:
                                minute_stats[minute]["sell"] += 1
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"[WARNING] 读取 {jsonl_file} 失败: {e}")
    
    return dict(minute_stats)

def load_sqlite_signals(sqlite_db: Path, start_time: str = None, end_time: str = None, run_id: str = None) -> Dict[int, Dict]:
    """从SQLite数据库加载信号，按分钟聚合"""
    minute_stats = defaultdict(lambda: {
        "total": 0,
        "confirmed": 0,
        "strong": 0,
        "buy": 0,
        "sell": 0
    })
    
    if not sqlite_db.exists():
        return {}
    
    try:
        conn = sqlite3.connect(str(sqlite_db), timeout=10.0)
        cursor = conn.cursor()
        
        # 构建查询条件
        where_clause = ""
        params = []
        # P0: 如果提供了run_id，只统计匹配的run_id
        if run_id:
            where_clause = "WHERE run_id = ?"
            params.append(run_id)
        if start_time and end_time:
            try:
                from datetime import datetime
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                start_ts_ms = int(start_dt.timestamp() * 1000)
                end_ts_ms = int(end_dt.timestamp() * 1000)
                where_clause = "WHERE ts_ms >= ? AND ts_ms <= ?"
                params = [start_ts_ms, end_ts_ms]
            except Exception:
                pass
        
        # 查询信号
        query = f"""
            SELECT 
                CAST(ts_ms / 60000 AS INTEGER) AS minute,
                confirm,
                signal_type
            FROM signals
            {where_clause}
        """
        cursor.execute(query, params)
        
        for minute, confirm, signal_type in cursor.fetchall():
            minute_stats[minute]["total"] += 1
            
            if confirm == 1:
                minute_stats[minute]["confirmed"] += 1
                
                signal_type_lower = (signal_type or "").lower()
                if "strong" in signal_type_lower:
                    minute_stats[minute]["strong"] += 1
                
                if "buy" in signal_type_lower:
                    minute_stats[minute]["buy"] += 1
                elif "sell" in signal_type_lower:
                    minute_stats[minute]["sell"] += 1
        
        conn.close()
    except Exception as e:
        print(f"[ERROR] 读取SQLite数据库失败: {e}")
        return {}
    
    return dict(minute_stats)

def calculate_parity_diff(jsonl_stats: Dict[int, Dict], sqlite_stats: Dict[int, Dict]) -> Dict:
    """计算等价性差异"""
    # 找到交集窗口（两个Sink都有的分钟）
    jsonl_minutes = set(jsonl_stats.keys())
    sqlite_minutes = set(sqlite_stats.keys())
    overlap_minutes = sorted(jsonl_minutes & sqlite_minutes)
    
    if not overlap_minutes:
        return {
            "overlap_minutes": 0,
            "jsonl_only_minutes": len(jsonl_minutes),
            "sqlite_only_minutes": len(sqlite_minutes),
            "error": "无交集窗口"
        }
    
    # 计算总体差异
    jsonl_total = sum(jsonl_stats[m]["total"] for m in overlap_minutes)
    sqlite_total = sum(sqlite_stats[m]["total"] for m in overlap_minutes)
    total_diff_pct = abs(jsonl_total - sqlite_total) / max(jsonl_total, sqlite_total, 1) * 100
    
    jsonl_confirmed = sum(jsonl_stats[m]["confirmed"] for m in overlap_minutes)
    sqlite_confirmed = sum(sqlite_stats[m]["confirmed"] for m in overlap_minutes)
    confirm_diff_pct = abs(jsonl_confirmed - sqlite_confirmed) / max(jsonl_confirmed, sqlite_confirmed, 1) * 100
    
    jsonl_strong = sum(jsonl_stats[m]["strong"] for m in overlap_minutes)
    sqlite_strong = sum(sqlite_stats[m]["strong"] for m in overlap_minutes)
    jsonl_strong_ratio = jsonl_strong / max(jsonl_confirmed, 1) * 100
    sqlite_strong_ratio = sqlite_strong / max(sqlite_confirmed, 1) * 100
    strong_ratio_diff_pct = abs(jsonl_strong_ratio - sqlite_strong_ratio)
    
    # 计算每分钟差异
    minute_diffs = []
    for minute in overlap_minutes:
        j = jsonl_stats[minute]
        s = sqlite_stats[minute]
        
        total_diff = abs(j["total"] - s["total"])
        confirm_diff = abs(j["confirmed"] - s["confirmed"])
        strong_diff = abs(j["strong"] - s["strong"])
        
        minute_diffs.append({
            "minute": minute,
            "minute_human": datetime.fromtimestamp(minute * 60).strftime("%Y-%m-%d %H:%M"),
            "jsonl": {
                "total": j["total"],
                "confirmed": j["confirmed"],
                "strong": j["strong"]
            },
            "sqlite": {
                "total": s["total"],
                "confirmed": s["confirmed"],
                "strong": s["strong"]
            },
            "diff": {
                "total": total_diff,
                "confirmed": confirm_diff,
                "strong": strong_diff
            }
        })
    
    # 按差异排序，找出Top-N差异分钟
    minute_diffs.sort(key=lambda x: x["diff"]["total"], reverse=True)
    
    return {
        "overlap_minutes": len(overlap_minutes),
        "jsonl_only_minutes": len(jsonl_minutes - sqlite_minutes),
        "sqlite_only_minutes": len(sqlite_minutes - jsonl_minutes),
        "overall": {
            "jsonl_total": jsonl_total,
            "sqlite_total": sqlite_total,
            "total_diff": abs(jsonl_total - sqlite_total),
            "total_diff_pct": total_diff_pct,
            "jsonl_confirmed": jsonl_confirmed,
            "sqlite_confirmed": sqlite_confirmed,
            "confirm_diff": abs(jsonl_confirmed - sqlite_confirmed),
            "confirm_diff_pct": confirm_diff_pct,
            "jsonl_strong_ratio": jsonl_strong_ratio,
            "sqlite_strong_ratio": sqlite_strong_ratio,
            "strong_ratio_diff_pct": strong_ratio_diff_pct
        },
        "top_diff_minutes": minute_diffs[:10],  # Top 10差异分钟
        "all_minute_diffs": minute_diffs
    }

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="双Sink等价性测试")
    parser.add_argument("--jsonl-dir", type=str, default="./runtime/ready/signal", help="JSONL信号目录")
    parser.add_argument("--sqlite-db", type=str, default="./runtime/signals.db", help="SQLite数据库路径")
    parser.add_argument("--output", type=str, default="./deploy/artifacts/ofi_cvd/parity_diff.json", help="输出文件路径")
    parser.add_argument("--manifest", type=str, default=None, help="run_manifest.json路径（用于获取时间范围）")
    parser.add_argument("--start-time", type=str, default=None, help="开始时间（ISO格式）")
    parser.add_argument("--end-time", type=str, default=None, help="结束时间（ISO格式）")
    parser.add_argument("--run-id", type=str, default=None, help="运行ID（用于按run_id对账）")
    
    args = parser.parse_args()
    
    jsonl_dir = Path(args.jsonl_dir)
    sqlite_db = Path(args.sqlite_db)
    output_path = Path(args.output)
    
    # 尝试从manifest获取时间范围
    start_time = args.start_time
    end_time = args.end_time
    
    if args.manifest:
        manifest_path = Path(args.manifest)
        if manifest_path.exists():
            try:
                with manifest_path.open("r", encoding="utf-8") as f:
                    manifest = json.load(f)
                start_time = manifest.get("started_at")
                end_time = manifest.get("ended_at")
                print(f"[INFO] 从manifest获取时间范围: {start_time} - {end_time}")
            except Exception as e:
                print(f"[WARNING] 读取manifest失败: {e}")
    
    # 如果没有指定manifest，尝试查找最新的
    if not start_time or not end_time:
        artifacts_dir = Path("deploy/artifacts/ofi_cvd/run_logs")
        manifests = sorted(artifacts_dir.glob("run_manifest_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if manifests:
            try:
                with manifests[0].open("r", encoding="utf-8") as f:
                    manifest = json.load(f)
                start_time = manifest.get("started_at")
                end_time = manifest.get("ended_at")
                print(f"[INFO] 从最新manifest获取时间范围: {start_time} - {end_time}")
            except Exception as e:
                print(f"[WARNING] 读取最新manifest失败: {e}")
    
    print("=" * 80)
    print("双 Sink 等价性测试")
    print("=" * 80)
    print()
    
    print(f"[INFO] JSONL目录: {jsonl_dir}")
    print(f"[INFO] SQLite数据库: {sqlite_db}")
    if start_time and end_time:
        print(f"[INFO] 时间范围: {start_time} - {end_time}")
    print()
    
    # P0: 获取run_id（用于按run_id对账）
    run_id = args.run_id or os.getenv("RUN_ID")
    if run_id:
        print(f"[INFO] 使用run_id过滤: {run_id}")
    
    # 加载数据
    print("[INFO] 加载JSONL信号...")
    jsonl_stats = load_jsonl_signals(jsonl_dir, start_time, end_time, run_id)
    print(f"  JSONL分钟数: {len(jsonl_stats)}")
    
    print("[INFO] 加载SQLite信号...")
    sqlite_stats = load_sqlite_signals(sqlite_db, start_time, end_time, run_id)
    print(f"  SQLite分钟数: {len(sqlite_stats)}")
    
    # 计算差异
    print("[INFO] 计算等价性差异...")
    parity_diff = calculate_parity_diff(jsonl_stats, sqlite_stats)
    
    # 输出结果
    print("\n=== 等价性差异分析 ===")
    print(f"交集窗口数: {parity_diff['overlap_minutes']}")
    print(f"JSONL独有分钟数: {parity_diff['jsonl_only_minutes']}")
    print(f"SQLite独有分钟数: {parity_diff['sqlite_only_minutes']}")
    
    if "error" in parity_diff:
        print(f"[ERROR] {parity_diff['error']}")
        return 1
    
    overall = parity_diff["overall"]
    print(f"\n总体差异:")
    print(f"  总量差异: {overall['total_diff']} ({overall['total_diff_pct']:.3f}%)")
    print(f"  确认量差异: {overall['confirm_diff']} ({overall['confirm_diff_pct']:.3f}%)")
    print(f"  强信号占比差异: {overall['strong_ratio_diff_pct']:.3f}%")
    
    # 判断是否通过
    passed = (
        overall['total_diff_pct'] < 0.5 and
        overall['confirm_diff_pct'] < 0.5 and
        overall['strong_ratio_diff_pct'] < 0.5
    )
    
    print(f"\n验收标准 (< 0.5%): {'[PASS]' if passed else '[FAIL]'}")
    
    # 保存结果
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(parity_diff, f, ensure_ascii=False, indent=2)
    print(f"\n[INFO] 差异分析已保存: {output_path}")
    
    return 0 if passed else 1

if __name__ == "__main__":
    exit(main())

