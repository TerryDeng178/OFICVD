#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查SQLite中guard_reason字段的实际内容"""
import sqlite3
import json
import sys
from pathlib import Path
from collections import Counter

def check_guard_reasons(sqlite_db: Path, test_name: str) -> dict:
    """检查guard_reason字段的内容"""
    conn = sqlite3.connect(str(sqlite_db))
    cursor = conn.cursor()
    
    results = {
        "test_name": test_name,
        "total_signals": 0,
        "blocked_signals": 0,
        "guard_reason_samples": [],
        "guard_reason_distribution": {},
        "contains_lag": 0,
        "contains_consistency": 0,
        "contains_spread": 0,
        "contains_weak_signal": 0,
    }
    
    # 统计总数
    cursor.execute("SELECT COUNT(*) FROM signals")
    results["total_signals"] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM signals WHERE gating = 1")
    results["blocked_signals"] = cursor.fetchone()[0]
    
    # 获取被阻止信号的guard_reason样本
    cursor.execute("""
        SELECT guard_reason, COUNT(*) as cnt
        FROM signals
        WHERE gating = 1 AND guard_reason IS NOT NULL
        GROUP BY guard_reason
        ORDER BY cnt DESC
        LIMIT 20
    """)
    
    guard_reason_dist = {}
    for row in cursor.fetchall():
        guard_reason, count = row
        guard_reason_dist[guard_reason] = count
    
    results["guard_reason_distribution"] = guard_reason_dist
    
    # 获取前10个样本
    cursor.execute("""
        SELECT DISTINCT guard_reason
        FROM signals
        WHERE gating = 1 AND guard_reason IS NOT NULL
        LIMIT 10
    """)
    
    results["guard_reason_samples"] = [row[0] for row in cursor.fetchall()]
    
    # 检查是否包含特定关键词
    cursor.execute("""
        SELECT COUNT(*) FROM signals
        WHERE gating = 1 AND guard_reason IS NOT NULL
        AND guard_reason LIKE '%lag%'
    """)
    results["contains_lag"] = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM signals
        WHERE gating = 1 AND guard_reason IS NOT NULL
        AND (guard_reason LIKE '%consistency%' OR guard_reason LIKE '%low_consistency%')
    """)
    results["contains_consistency"] = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM signals
        WHERE gating = 1 AND guard_reason IS NOT NULL
        AND guard_reason LIKE '%spread%'
    """)
    results["contains_spread"] = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM signals
        WHERE gating = 1 AND guard_reason IS NOT NULL
        AND guard_reason LIKE '%weak_signal%'
    """)
    results["contains_weak_signal"] = cursor.fetchone()[0]
    
    conn.close()
    return results

def main():
    if len(sys.argv) < 2:
        print("Usage: python check_guard_reason_content.py <sqlite_db> [test_name]")
        sys.exit(1)
    
    sqlite_db = Path(sys.argv[1])
    test_name = sys.argv[2] if len(sys.argv) > 2 else sqlite_db.parent.name
    
    if not sqlite_db.exists():
        print(f"❌ SQLite数据库不存在: {sqlite_db}")
        sys.exit(1)
    
    results = check_guard_reasons(sqlite_db, test_name)
    
    print("\n" + "="*80)
    print(f"Guard Reason内容检查: {test_name}")
    print("="*80 + "\n")
    
    print(f"信号总数: {results['total_signals']}")
    print(f"被阻止信号: {results['blocked_signals']}")
    print()
    
    print("Guard Reason分布 (Top-20):")
    for reason, count in list(results["guard_reason_distribution"].items())[:20]:
        pct = (count / results["blocked_signals"] * 100) if results["blocked_signals"] > 0 else 0
        print(f"  {reason}: {count} ({pct:.2f}%)")
    print()
    
    print("Guard Reason样本 (前10个):")
    for i, sample in enumerate(results["guard_reason_samples"][:10], 1):
        print(f"  {i}. {repr(sample)}")
    print()
    
    print("关键词统计:")
    print(f"  包含'lag': {results['contains_lag']}")
    print(f"  包含'consistency'或'low_consistency': {results['contains_consistency']}")
    print(f"  包含'spread': {results['contains_spread']}")
    print(f"  包含'weak_signal': {results['contains_weak_signal']}")
    print()
    
    # 分析
    print("分析:")
    if results["contains_lag"] > 0:
        print(f"  ✅ 找到{results['contains_lag']}个包含'lag'的guard_reason")
    else:
        print(f"  ❌ 未找到包含'lag'的guard_reason")
    
    if results["contains_consistency"] > 0:
        print(f"  ✅ 找到{results['contains_consistency']}个包含'consistency'的guard_reason")
    else:
        print(f"  ❌ 未找到包含'consistency'的guard_reason")
    
    if results["contains_spread"] > 0:
        print(f"  ✅ 找到{results['contains_spread']}个包含'spread'的guard_reason")
    else:
        print(f"  ❌ 未找到包含'spread'的guard_reason")
    
    # 保存结果
    output_file = Path("./runtime/reports/guard_reason_content_check.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # 如果文件已存在，读取并追加
    if output_file.exists():
        existing_data = json.loads(output_file.read_text(encoding="utf-8"))
        if not isinstance(existing_data, list):
            existing_data = [existing_data]
        existing_data.append(results)
    else:
        existing_data = [results]
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n结果已保存到: {output_file}")

if __name__ == "__main__":
    main()

