#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证SQLite视图是否正确创建"""
import sqlite3
import sys
from pathlib import Path

def verify_views(sqlite_db: Path) -> dict:
    """验证视图是否正确创建"""
    conn = sqlite3.connect(str(sqlite_db))
    cursor = conn.cursor()
    
    results = {
        "views_exist": [],
        "views_missing": [],
        "view_queries_work": {}
    }
    
    # 检查视图是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='view'")
    existing_views = [row[0] for row in cursor.fetchall()]
    
    expected_views = ["v_signals_gate_distribution", "v_gate_distribution_stats"]
    
    for view_name in expected_views:
        if view_name in existing_views:
            results["views_exist"].append(view_name)
            # 测试查询
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {view_name}")
                count = cursor.fetchone()[0]
                results["view_queries_work"][view_name] = {
                    "exists": True,
                    "query_works": True,
                    "row_count": count
                }
            except Exception as e:
                results["view_queries_work"][view_name] = {
                    "exists": True,
                    "query_works": False,
                    "error": str(e)
                }
        else:
            results["views_missing"].append(view_name)
            results["view_queries_work"][view_name] = {
                "exists": False,
                "query_works": False
            }
    
    conn.close()
    return results

def main():
    if len(sys.argv) < 2:
        print("Usage: python verify_sqlite_views.py <sqlite_db>")
        sys.exit(1)
    
    sqlite_db = Path(sys.argv[1])
    if not sqlite_db.exists():
        print(f"❌ SQLite数据库不存在: {sqlite_db}")
        sys.exit(1)
    
    results = verify_views(sqlite_db)
    
    print("\n" + "="*80)
    print("SQLite视图验证")
    print("="*80 + "\n")
    
    print("视图存在情况:")
    for view_name in results["views_exist"]:
        print(f"  ✅ {view_name}")
    for view_name in results["views_missing"]:
        print(f"  ❌ {view_name} (缺失)")
    print()
    
    print("视图查询测试:")
    for view_name, status in results["view_queries_work"].items():
        if status.get("exists"):
            if status.get("query_works"):
                print(f"  ✅ {view_name}: 查询成功 (行数: {status.get('row_count', 0)})")
            else:
                print(f"  ❌ {view_name}: 查询失败 - {status.get('error', 'Unknown error')}")
        else:
            print(f"  ❌ {view_name}: 视图不存在")
    print()
    
    # 总体状态
    all_exist = len(results["views_missing"]) == 0
    all_work = all(
        status.get("query_works", False) 
        for status in results["view_queries_work"].values() 
        if status.get("exists")
    )
    
    if all_exist and all_work:
        print("✅ 所有视图创建成功且查询正常")
        return 0
    else:
        print("❌ 部分视图存在问题")
        return 1

if __name__ == "__main__":
    sys.exit(main())

