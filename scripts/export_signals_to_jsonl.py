#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从SQLite导出signals到JSONL，用于对齐审计"""
import sqlite3
import json
import sys
from pathlib import Path

def export_signals(sqlite_db: Path, output_file: Path):
    """从SQLite导出signals到JSONL"""
    conn = sqlite3.connect(str(sqlite_db))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM signals")
    rows = cursor.fetchall()
    
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        for row in rows:
            record = dict(row)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    conn.close()
    print(f"✅ 导出 {len(rows)} 条记录到 {output_file}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python export_signals_to_jsonl.py <sqlite_db> <output_jsonl>")
        sys.exit(1)
    
    sqlite_db = Path(sys.argv[1])
    output_file = Path(sys.argv[2])
    
    export_signals(sqlite_db, output_file)

