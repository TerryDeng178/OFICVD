#!/usr/bin/env python3
"""P1: 对账找差工具（定位confirm差异样本）"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Set, Tuple, List

def load_jsonl_keys(jsonl_dir: Path, run_id: str = None) -> Set[Tuple]:
    """加载JSONL信号的对账键集合"""
    keys = set()
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
                        if run_id and signal.get("run_id") != run_id:
                            continue
                        # 对账键：(run_id, ts_ms, symbol, signal_type, confirm)
                        key = (
                            signal.get("run_id", ""),
                            int(signal.get("ts_ms", 0)),
                            signal.get("symbol", ""),
                            signal.get("signal_type", ""),
                            bool(signal.get("confirm", False))
                        )
                        if key[1] > 0:  # ts_ms > 0
                            keys.add(key)
                    except (json.JSONDecodeError, ValueError, KeyError):
                        continue
        except Exception as e:
            print(f"[WARN] 读取JSONL文件失败 {jsonl_file}: {e}", file=sys.stderr)
            continue
    return keys

def load_sqlite_keys(sqlite_db: Path, run_id: str = None) -> Set[Tuple]:
    """加载SQLite信号的对账键集合"""
    keys = set()
    try:
        conn = sqlite3.connect(str(sqlite_db))
        cursor = conn.cursor()
        
        # P0: 如果提供了run_id，只统计匹配的run_id
        if run_id:
            cursor.execute("""
                SELECT run_id, ts_ms, symbol, signal_type, confirm
                FROM signals
                WHERE run_id = ?
            """, (run_id,))
        else:
            cursor.execute("""
                SELECT run_id, ts_ms, symbol, signal_type, confirm
                FROM signals
            """)
        
        for row in cursor.fetchall():
            run_id_val, ts_ms, symbol, signal_type, confirm = row
            if ts_ms > 0:
                key = (
                    run_id_val or "",
                    int(ts_ms),
                    symbol or "",
                    signal_type or "",
                    bool(confirm)
                )
                keys.add(key)
        conn.close()
    except Exception as e:
        print(f"[ERROR] 读取SQLite数据库失败: {e}", file=sys.stderr)
        return keys
    return keys

def find_diff_samples(jsonl_keys: Set[Tuple], sqlite_keys: Set[Tuple], max_samples: int = 100) -> Dict:
    """找出差异样本"""
    jsonl_only = jsonl_keys - sqlite_keys
    sqlite_only = sqlite_keys - jsonl_keys
    
    # 按confirm分组统计
    jsonl_only_by_confirm = {
        True: [k for k in jsonl_only if k[4]],
        False: [k for k in jsonl_only if not k[4]]
    }
    sqlite_only_by_confirm = {
        True: [k for k in sqlite_only if k[4]],
        False: [k for k in sqlite_only if not k[4]]
    }
    
    return {
        "jsonl_only_count": len(jsonl_only),
        "sqlite_only_count": len(sqlite_only),
        "jsonl_only_samples": {
            "confirmed": jsonl_only_by_confirm[True][:max_samples],
            "unconfirmed": jsonl_only_by_confirm[False][:max_samples]
        },
        "sqlite_only_samples": {
            "confirmed": sqlite_only_by_confirm[True][:max_samples],
            "unconfirmed": sqlite_only_by_confirm[False][:max_samples]
        },
        "common_count": len(jsonl_keys & sqlite_keys)
    }

def main():
    parser = argparse.ArgumentParser(description="P1: 对账找差工具（定位confirm差异样本）")
    parser.add_argument("--jsonl-dir", type=str, default="./runtime/ready/signal", help="JSONL信号目录")
    parser.add_argument("--sqlite-db", type=str, default="./runtime/signals.db", help="SQLite数据库路径")
    parser.add_argument("--run-id", type=str, default=None, help="运行ID（用于按run_id对账）")
    parser.add_argument("--output", type=str, default=None, help="输出JSON文件路径（可选）")
    parser.add_argument("--max-samples", type=int, default=100, help="每种差异类型的最大样本数")
    
    args = parser.parse_args()
    
    jsonl_dir = Path(args.jsonl_dir)
    sqlite_db = Path(args.sqlite_db)
    
    if not jsonl_dir.exists():
        print(f"[ERROR] JSONL目录不存在: {jsonl_dir}", file=sys.stderr)
        return 1
    
    if not sqlite_db.exists():
        print(f"[ERROR] SQLite数据库不存在: {sqlite_db}", file=sys.stderr)
        return 1
    
    print(f"[INFO] 加载JSONL对账键（run_id={args.run_id or 'ALL'}）...")
    jsonl_keys = load_jsonl_keys(jsonl_dir, args.run_id)
    print(f"  JSONL键数量: {len(jsonl_keys)}")
    
    print(f"[INFO] 加载SQLite对账键（run_id={args.run_id or 'ALL'}）...")
    sqlite_keys = load_sqlite_keys(sqlite_db, args.run_id)
    print(f"  SQLite键数量: {len(sqlite_keys)}")
    
    print(f"[INFO] 计算差异...")
    diff_result = find_diff_samples(jsonl_keys, sqlite_keys, args.max_samples)
    
    # 输出结果
    print()
    print("=" * 80)
    print("对账差异分析")
    print("=" * 80)
    print(f"JSONL独有: {diff_result['jsonl_only_count']}条")
    print(f"  - 已确认: {len(diff_result['jsonl_only_samples']['confirmed'])}条")
    print(f"  - 未确认: {len(diff_result['jsonl_only_samples']['unconfirmed'])}条")
    print(f"SQLite独有: {diff_result['sqlite_only_count']}条")
    print(f"  - 已确认: {len(diff_result['sqlite_only_samples']['confirmed'])}条")
    print(f"  - 未确认: {len(diff_result['sqlite_only_samples']['unconfirmed'])}条")
    print(f"共同键: {diff_result['common_count']}条")
    print()
    
    if diff_result['jsonl_only_samples']['confirmed']:
        print("JSONL独有（已确认）样本（前10条）:")
        for i, key in enumerate(diff_result['jsonl_only_samples']['confirmed'][:10], 1):
            print(f"  {i}. run_id={key[0]}, ts_ms={key[1]}, symbol={key[2]}, signal_type={key[3]}, confirm={key[4]}")
        print()
    
    if diff_result['sqlite_only_samples']['confirmed']:
        print("SQLite独有（已确认）样本（前10条）:")
        for i, key in enumerate(diff_result['sqlite_only_samples']['confirmed'][:10], 1):
            print(f"  {i}. run_id={key[0]}, ts_ms={key[1]}, symbol={key[2]}, signal_type={key[3]}, confirm={key[4]}")
        print()
    
    # 保存结果
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(diff_result, f, ensure_ascii=False, indent=2)
        print(f"结果已保存到: {output_path}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

