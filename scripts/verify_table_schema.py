#!/usr/bin/env python3
"""验证表结构"""
import sys
import sqlite3
from pathlib import Path

def main():
    db = Path("runtime/signals.db")
    if not db.exists():
        print("[!] 数据库不存在")
        return 1
    
    conn = sqlite3.connect(str(db))
    cursor = conn.cursor()
    
    # 检查表结构
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='signals'")
    result = cursor.fetchone()
    ddl = result[0] if result else ""
    
    print("=" * 80)
    print("表结构检查")
    print("=" * 80)
    print()
    print("DDL:")
    print(ddl)
    print()
    
    # 检查列
    cursor.execute("PRAGMA table_info(signals)")
    columns = cursor.fetchall()
    print("列信息:")
    for col in columns:
        print(f"  {col[1]} ({col[2]}) - PK: {col[5]}")
    print()
    
    # 检查主键
    has_id_pk = any(col[1] == "id" and col[5] == 1 for col in columns)
    has_ts_symbol_pk = "PRIMARY KEY" in ddl.upper() and "TS_MS" in ddl.upper() and "SYMBOL" in ddl.upper() and "AUTOINCREMENT" not in ddl.upper()
    
    print("主键检查:")
    print(f"  有id主键: {has_id_pk}")
    print(f"  有(ts_ms,symbol)主键: {has_ts_symbol_pk}")
    print()
    
    # 数据统计
    count = cursor.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    print(f"数据总数: {count:,}")
    
    conn.close()
    
    if has_id_pk and not has_ts_symbol_pk:
        print()
        print("[x] 表结构正确：使用行级主键(id AUTOINCREMENT)")
        return 0
    else:
        print()
        print("[!] 表结构异常：需要迁移")
        return 1

if __name__ == "__main__":
    sys.exit(main())

