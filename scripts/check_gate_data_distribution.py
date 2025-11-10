#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查Gate数据分布，验证是否应该触发其他gate原因"""
import sqlite3
import json
import sys
from pathlib import Path

def check_distribution(sqlite_db: Path) -> dict:
    """检查数据分布"""
    conn = sqlite3.connect(str(sqlite_db))
    cursor = conn.cursor()
    
    results = {}
    
    # 检查spread分布（从signals表的spread_bps列读取）
    cursor.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN spread_bps > 8.0 THEN 1 ELSE 0 END) AS spread_over_8bps,
            AVG(spread_bps) AS avg_spread_bps,
            MAX(spread_bps) AS max_spread_bps
        FROM signals
        WHERE spread_bps IS NOT NULL
    """)
    row = cursor.fetchone()
    if row:
        total, spread_over_8bps, avg_spread, max_spread = row
        results["spread"] = {
            "total": total,
            "over_8bps_count": spread_over_8bps or 0,
            "over_8bps_pct": (spread_over_8bps / total * 100) if total > 0 else 0,
            "avg_spread_bps": avg_spread,
            "max_spread_bps": max_spread,
        }
    
    # 检查lag分布（从signals表的lag_sec列读取）
    cursor.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN lag_sec > 0.3 THEN 1 ELSE 0 END) AS lag_over_0_3s,
            AVG(lag_sec) AS avg_lag_sec,
            MAX(lag_sec) AS max_lag_sec
        FROM signals
        WHERE lag_sec IS NOT NULL
    """)
    row = cursor.fetchone()
    if row:
        total, lag_over_0_3s, avg_lag, max_lag = row
        results["lag"] = {
            "total": total,
            "over_0_3s_count": lag_over_0_3s or 0,
            "over_0_3s_pct": (lag_over_0_3s / total * 100) if total > 0 else 0,
            "avg_lag_sec": avg_lag,
            "max_lag_sec": max_lag,
        }
    
    # 检查consistency分布（从signals表的consistency列读取）
    cursor.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN consistency < 0.3 THEN 1 ELSE 0 END) AS cons_below_0_3,
            AVG(consistency) AS avg_consistency,
            MIN(consistency) AS min_consistency
        FROM signals
        WHERE consistency IS NOT NULL
    """)
    row = cursor.fetchone()
    if row:
        total, cons_below_0_3, avg_cons, min_cons = row
        results["consistency"] = {
            "total": total,
            "below_0_3_count": cons_below_0_3 or 0,
            "below_0_3_pct": (cons_below_0_3 / total * 100) if total > 0 else 0,
            "avg_consistency": avg_cons,
            "min_consistency": min_cons,
        }
    
    # 检查reason_codes分布
    cursor.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN json_extract(_feature_data,'$.reason_codes') IS NOT NULL 
                     AND json_array_length(json_extract(_feature_data,'$.reason_codes')) > 0 THEN 1 ELSE 0 END) AS has_reason_codes,
            SUM(CASE WHEN json_extract(_feature_data,'$.reason_codes') LIKE '%lag_exceeded%' THEN 1 ELSE 0 END) AS has_lag_exceeded,
            SUM(CASE WHEN json_extract(_feature_data,'$.reason_codes') LIKE '%low_consistency_throttle%' THEN 1 ELSE 0 END) AS has_low_consistency_throttle
        FROM signals
        WHERE _feature_data IS NOT NULL
    """)
    row = cursor.fetchone()
    if row:
        total, has_reason_codes, has_lag_exceeded, has_low_consistency_throttle = row
        results["reason_codes"] = {
            "total": total,
            "has_reason_codes_count": has_reason_codes or 0,
            "has_reason_codes_pct": (has_reason_codes / total * 100) if total > 0 else 0,
            "has_lag_exceeded_count": has_lag_exceeded or 0,
            "has_low_consistency_throttle_count": has_low_consistency_throttle or 0,
        }
    
    conn.close()
    return results

def main():
    if len(sys.argv) < 2:
        print("Usage: python check_gate_data_distribution.py <sqlite_db>")
        sys.exit(1)
    
    sqlite_db = Path(sys.argv[1])
    if not sqlite_db.exists():
        print(f"❌ SQLite数据库不存在: {sqlite_db}")
        sys.exit(1)
    
    results = check_distribution(sqlite_db)
    
    print("\n" + "="*80)
    print("Gate数据分布检查")
    print("="*80 + "\n")
    
    # Spread分布
    if "spread" in results:
        spread = results["spread"]
        print(f"Spread分布:")
        print(f"  总数: {spread['total']}")
        print(f"  >8bps数量: {spread['over_8bps_count']} ({spread['over_8bps_pct']:.2f}%)")
        print(f"  平均spread: {spread['avg_spread_bps']:.4f} bps")
        print(f"  最大spread: {spread['max_spread_bps']:.4f} bps")
        print()
    
    # Lag分布
    if "lag" in results:
        lag = results["lag"]
        print(f"Lag分布:")
        print(f"  总数: {lag['total']}")
        print(f"  >0.3s数量: {lag['over_0_3s_count']} ({lag['over_0_3s_pct']:.2f}%)")
        print(f"  平均lag: {lag['avg_lag_sec']:.4f} s")
        print(f"  最大lag: {lag['max_lag_sec']:.4f} s")
        print()
    
    # Consistency分布
    if "consistency" in results:
        cons = results["consistency"]
        print(f"Consistency分布:")
        print(f"  总数: {cons['total']}")
        print(f"  <0.3数量: {cons['below_0_3_count']} ({cons['below_0_3_pct']:.2f}%)")
        print(f"  平均consistency: {cons['avg_consistency']:.4f}")
        print(f"  最小consistency: {cons['min_consistency']:.4f}")
        print()
    
    # Reason codes分布
    if "reason_codes" in results:
        rc = results["reason_codes"]
        print(f"Reason codes分布:")
        print(f"  总数: {rc['total']}")
        print(f"  有reason_codes数量: {rc['has_reason_codes_count']} ({rc['has_reason_codes_pct']:.2f}%)")
        print(f"  包含lag_exceeded: {rc['has_lag_exceeded_count']}")
        print(f"  包含low_consistency_throttle: {rc['has_low_consistency_throttle_count']}")
        print()
    
    # 保存结果
    output_file = Path("./runtime/reports/gate_data_distribution.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"结果已保存到: {output_file}")

if __name__ == "__main__":
    main()

