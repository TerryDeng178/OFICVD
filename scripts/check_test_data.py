#!/usr/bin/env python3
"""检查测试数据"""
import sqlite3
from datetime import datetime

run_id = "task07a_live_20251108_230654"
conn = sqlite3.connect("runtime/signals.db")
cursor = conn.cursor()

# 总信号数
cursor.execute("SELECT COUNT(*) FROM signals WHERE run_id = ?", (run_id,))
total = cursor.fetchone()[0]

# 确认信号
cursor.execute("SELECT COUNT(*) FROM signals WHERE run_id = ? AND confirm = 1", (run_id,))
confirmed = cursor.fetchone()[0]

# 强信号
cursor.execute("SELECT COUNT(*) FROM signals WHERE run_id = ? AND signal_type IN ('strong_buy', 'strong_sell')", (run_id,))
strong = cursor.fetchone()[0]

# 时间范围
cursor.execute("SELECT MIN(ts_ms), MAX(ts_ms) FROM signals WHERE run_id = ?", (run_id,))
ts_min, ts_max = cursor.fetchone()

dt_min = datetime.fromtimestamp(ts_min / 1000) if ts_min else None
dt_max = datetime.fromtimestamp(ts_max / 1000) if ts_max else None
duration_min = (ts_max - ts_min) / 1000 / 60 if ts_min and ts_max else 0

print(f"RUN_ID: {run_id}")
print(f"总信号数: {total:,}")
print(f"确认信号: {confirmed:,}")
print(f"强信号: {strong:,}")
print(f"强信号占比: {strong/total*100:.2f}%" if total > 0 else "N/A")
print(f"数据时间范围: {dt_min.strftime('%Y-%m-%d %H:%M:%S') if dt_min else 'N/A'} - {dt_max.strftime('%Y-%m-%d %H:%M:%S') if dt_max else 'N/A'}")
print(f"时间跨度: {duration_min:.1f} 分钟")

conn.close()

