#!/usr/bin/env python3
"""检查signals表结构"""
import sqlite3
from pathlib import Path

def check_signals_table(db_path: Path):
    """检查signals表结构"""
    if not db_path.exists():
        print(f"[FAIL] 数据库不存在: {db_path}")
        return False
    
    try:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        
        # 检查表定义
        table_sql = cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='signals'").fetchone()
        if not table_sql:
            print("[FAIL] signals表不存在")
            con.close()
            return False
        
        table_ddl = table_sql[0]
        print("=" * 80)
        print("signals表结构检查")
        print("=" * 80)
        print("\nTable DDL:")
        print(table_ddl)
        
        # 检查主键
        ddl_upper = table_ddl.upper()
        has_composite_pk = (
            "PRIMARY KEY" in ddl_upper and 
            "RUN_ID" in ddl_upper and 
            "TS_MS" in ddl_upper and 
            "SYMBOL" in ddl_upper
        )
        has_old_pk = (
            "PRIMARY KEY" in ddl_upper and 
            "TS_MS" in ddl_upper and 
            "SYMBOL" in ddl_upper and
            "RUN_ID" not in ddl_upper.split("PRIMARY KEY")[1].split(")")[0] if "PRIMARY KEY" in ddl_upper else False
        )
        
        print("\n主键检查:")
        if has_composite_pk:
            print("  [OK] 复合主键 (run_id, ts_ms, symbol) 已存在")
        else:
            print("  [FAIL] 未找到复合主键 (run_id, ts_ms, symbol)")
        
        if has_old_pk:
            print("  [WARN] 检测到旧版主键 (ts_ms, symbol)")
        else:
            print("  [OK] 未发现旧版主键")
        
        # 检查索引
        indexes = cur.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='signals'").fetchall()
        print("\n索引:")
        if indexes:
            for name, sql in indexes:
                print(f"  {name}: {sql}")
        else:
            print("  无索引")
        
        con.close()
        return has_composite_pk and not has_old_pk
    except Exception as e:
        print(f"[FAIL] 检查失败: {e}")
        return False

if __name__ == "__main__":
    import sys
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./deploy/data/ofi_cvd/signals.db")
    success = check_signals_table(db_path)
    sys.exit(0 if success else 1)

