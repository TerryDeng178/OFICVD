#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查Gate分布统计（使用SQLite视图）"""
import sqlite3
import json
import sys
from pathlib import Path

def create_views(sqlite_db: Path):
    """创建Gate分布查询视图"""
    conn = sqlite3.connect(str(sqlite_db))
    cursor = conn.cursor()
    
    # 读取SQL脚本
    sql_file = Path(__file__).parent / "create_gate_distribution_view.sql"
    if sql_file.exists():
        sql_content = sql_file.read_text(encoding="utf-8")
        # 执行SQL脚本（按分号分割，但需要处理多行语句）
        statements = []
        current_statement = []
        for line in sql_content.split('\n'):
            line = line.strip()
            if not line or line.startswith('--'):
                continue
            current_statement.append(line)
            if line.endswith(';'):
                statements.append(' '.join(current_statement))
                current_statement = []
        
        # 执行所有语句
        for statement in statements:
            statement = statement.rstrip(';').strip()
            if statement:
                try:
                    cursor.execute(statement)
                except sqlite3.OperationalError as e:
                    # 视图可能已存在，忽略错误
                    error_msg = str(e).lower()
                    if "already exists" not in error_msg and "duplicate" not in error_msg:
                        print(f"警告: 创建视图时出错: {e}")
                        print(f"  语句: {statement[:100]}...")
        conn.commit()
    else:
        print(f"警告: SQL脚本文件不存在: {sql_file}")
    
    conn.close()

def check_distribution(sqlite_db: Path) -> dict:
    """检查Gate分布统计"""
    # 先创建视图
    create_views(sqlite_db)
    
    conn = sqlite3.connect(str(sqlite_db))
    cursor = conn.cursor()
    
    results = {}
    
    # 查询统计视图
    try:
        cursor.execute("SELECT * FROM v_gate_distribution_stats")
        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            results["stats"] = dict(zip(columns, row))
    except sqlite3.OperationalError as e:
        print(f"警告: 无法查询统计视图: {e}")
        results["stats"] = {}
    
    # 查询Top gate原因
    try:
        cursor.execute("""
            SELECT guard_reason, COUNT(*) as cnt
            FROM signals
            WHERE gating = 1 AND guard_reason IS NOT NULL
            GROUP BY guard_reason
            ORDER BY cnt DESC
            LIMIT 10
        """)
        results["top_reasons"] = [{"reason": r[0], "count": r[1]} for r in cursor.fetchall()]
    except sqlite3.OperationalError as e:
        print(f"警告: 无法查询Top原因: {e}")
        results["top_reasons"] = []
    
    conn.close()
    return results

def main():
    if len(sys.argv) < 2:
        print("Usage: python check_gate_distribution_sqlite.py <sqlite_db>")
        sys.exit(1)
    
    sqlite_db = Path(sys.argv[1])
    if not sqlite_db.exists():
        print(f"❌ SQLite数据库不存在: {sqlite_db}")
        sys.exit(1)
    
    results = check_distribution(sqlite_db)
    
    print("\n" + "="*80)
    print("Gate分布统计")
    print("="*80 + "\n")
    
    # 显示统计
    if "stats" in results and results["stats"]:
        stats = results["stats"]
        print("总体统计:")
        print(f"  信号总数: {stats.get('total_signals', 0)}")
        print(f"  被阻止信号: {stats.get('blocked_signals', 0)}")
        print()
        print("Gate原因分布:")
        print(f"  lag_exceeded: {stats.get('lag_exceeded_count', 0)} ({stats.get('lag_exceeded_pct', 0):.2f}%)")
        print(f"  spread_exceeded: {stats.get('spread_exceeded_count', 0)} ({stats.get('spread_exceeded_pct', 0):.2f}%)")
        print(f"  low_consistency: {stats.get('low_consistency_count', 0)} ({stats.get('low_consistency_pct', 0):.2f}%)")
        print(f"  weak_signal: {stats.get('weak_signal_count', 0)} ({stats.get('weak_signal_pct', 0):.2f}%)")
        print(f"  warmup: {stats.get('warmup_count', 0)} ({stats.get('warmup_pct', 0):.2f}%)")
        print()
    
    # 显示Top原因
    if "top_reasons" in results and results["top_reasons"]:
        print("Top Gate原因:")
        for i, item in enumerate(results["top_reasons"][:10], 1):
            print(f"  {i}. {item['reason']}: {item['count']}")
        print()
    
    # 计算Top-1占比
    if results.get("top_reasons") and results["top_reasons"]:
        top1 = results["top_reasons"][0]
        total_blocked = results.get("stats", {}).get("blocked_signals", 0)
        if total_blocked > 0:
            top1_pct = (top1["count"] / total_blocked) * 100
            print(f"Top-1占比: {top1_pct:.2f}%")
            print(f"状态: {'✅ 通过' if top1_pct < 60 else '❌ 未通过'} (阈值<60%)")
    
    # 保存结果
    output_file = Path("./runtime/reports/gate_distribution_stats.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n结果已保存到: {output_file}")

if __name__ == "__main__":
    main()

