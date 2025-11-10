#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0修复: 从SQLite数据库检查活动度覆盖率（支持JSON字段提取）"""
import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M%S",
)
logger = logging.getLogger(__name__)


def check_activity_coverage(sqlite_db: Path, output_file: Path) -> Dict[str, Any]:
    """检查活动度覆盖率"""
    conn = sqlite3.connect(str(sqlite_db))
    cursor = conn.cursor()
    
    # 创建视图（如果不存在）
    try:
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS v_signals_activity AS
            SELECT 
                *,
                json_extract(_feature_data, '$.activity.trade_rate') AS trade_rate,
                json_extract(_feature_data, '$.activity.quote_rate') AS quote_rate,
                json_extract(_feature_data, '$.trades_per_min') AS trades_per_min,
                json_extract(_feature_data, '$.quote_updates_per_sec') AS quote_updates_per_sec
            FROM signals
        """)
        conn.commit()
    except Exception as e:
        logger.warning(f"创建视图失败（可能已存在）: {e}")
    
    # 检查覆盖率（根据是否有_feature_data列选择不同的查询）
    if has_feature_data:
        cursor.execute("""
            SELECT
                COUNT(*) AS total_signals,
                SUM(CASE WHEN trade_rate IS NOT NULL AND CAST(trade_rate AS REAL) > 0 THEN 1 ELSE 0 END) AS trade_rate_valid,
                SUM(CASE WHEN quote_rate IS NOT NULL AND CAST(quote_rate AS REAL) > 0 THEN 1 ELSE 0 END) AS quote_rate_valid,
                SUM(CASE WHEN trades_per_min IS NOT NULL AND CAST(trades_per_min AS REAL) > 0 THEN 1 ELSE 0 END) AS trades_per_min_valid,
                SUM(CASE WHEN quote_updates_per_sec IS NOT NULL AND CAST(quote_updates_per_sec AS REAL) > 0 THEN 1 ELSE 0 END) AS quote_updates_per_sec_valid
            FROM v_signals_activity
        """)
    else:
        # 如果没有_feature_data列，活动度数据可能不在signals表中
        # 返回空结果
        cursor.execute("SELECT COUNT(*) AS total_signals FROM signals")
        total = cursor.fetchone()[0]
        return {
            "total_records": total,
            "trade_rate": {"coverage_pct": 0.0, "zero_rate_pct": 0.0, "passed": False, "note": "活动度数据不在signals表中"},
            "quote_rate": {"coverage_pct": 0.0, "zero_rate_pct": 0.0, "passed": False, "note": "活动度数据不在signals表中"},
            "overall_passed": False
        }
    
    row = cursor.fetchone()
    total_signals = row[0]
    trade_rate_valid = row[1] or 0
    quote_rate_valid = row[2] or 0
    trades_per_min_valid = row[3] or 0
    quote_updates_per_sec_valid = row[4] or 0
    
    trade_rate_coverage = (trade_rate_valid / total_signals * 100) if total_signals > 0 else 0.0
    quote_rate_coverage = (quote_rate_valid / total_signals * 100) if total_signals > 0 else 0.0
    trades_per_min_coverage = (trades_per_min_valid / total_signals * 100) if total_signals > 0 else 0.0
    quote_updates_per_sec_coverage = (quote_updates_per_sec_valid / total_signals * 100) if total_signals > 0 else 0.0
    
    # 检查零值率
    cursor.execute("""
        SELECT
            SUM(CASE WHEN trade_rate IS NOT NULL AND CAST(trade_rate AS REAL) = 0 THEN 1 ELSE 0 END) AS trade_rate_zero,
            SUM(CASE WHEN quote_rate IS NOT NULL AND CAST(quote_rate AS REAL) = 0 THEN 1 ELSE 0 END) AS quote_rate_zero
        FROM v_signals_activity
    """)
    
    zero_row = cursor.fetchone()
    trade_rate_zero = zero_row[0] or 0
    quote_rate_zero = zero_row[1] or 0
    
    trade_rate_zero_rate = (trade_rate_zero / total_signals * 100) if total_signals > 0 else 0.0
    quote_rate_zero_rate = (quote_rate_zero / total_signals * 100) if total_signals > 0 else 0.0
    
    conn.close()
    
    result = {
        "total_signals": total_signals,
        "trade_rate": {
            "valid_count": trade_rate_valid,
            "coverage_pct": trade_rate_coverage,
            "zero_count": trade_rate_zero,
            "zero_rate_pct": trade_rate_zero_rate,
            "passed": trade_rate_coverage >= 95.0 and trade_rate_zero_rate < 5.0
        },
        "quote_rate": {
            "valid_count": quote_rate_valid,
            "coverage_pct": quote_rate_coverage,
            "zero_count": quote_rate_zero,
            "zero_rate_pct": quote_rate_zero_rate,
            "passed": quote_rate_coverage >= 95.0 and quote_rate_zero_rate < 5.0
        },
        "trades_per_min": {
            "valid_count": trades_per_min_valid,
            "coverage_pct": trades_per_min_coverage,
            "passed": trades_per_min_coverage >= 95.0
        },
        "quote_updates_per_sec": {
            "valid_count": quote_updates_per_sec_valid,
            "coverage_pct": quote_updates_per_sec_coverage,
            "passed": quote_updates_per_sec_coverage >= 95.0
        },
        "overall_passed": (trade_rate_coverage >= 95.0 and trade_rate_zero_rate < 5.0 and 
                          quote_rate_coverage >= 95.0 and quote_rate_zero_rate < 5.0)
    }
    
    # 生成Markdown报告
    md_content = f"""# 活动度覆盖率检查报告

**数据库**: {sqlite_db}  
**检查时间**: {Path(__file__).stat().st_mtime}

## 总体统计

- **信号总数**: {total_signals}

## 覆盖率统计

### trade_rate
- **有效值数量**: {trade_rate_valid}
- **覆盖率**: {trade_rate_coverage:.2f}% {'✅ 达标（≥95%）' if trade_rate_coverage >= 95.0 else '❌ 未达标（<95%）'}
- **零值数量**: {trade_rate_zero}
- **零值率**: {trade_rate_zero_rate:.2f}% {'✅ 达标（<5%）' if trade_rate_zero_rate < 5.0 else '❌ 未达标（≥5%）'}

### quote_rate
- **有效值数量**: {quote_rate_valid}
- **覆盖率**: {quote_rate_coverage:.2f}% {'✅ 达标（≥95%）' if quote_rate_coverage >= 95.0 else '❌ 未达标（<95%）'}
- **零值数量**: {quote_rate_zero}
- **零值率**: {quote_rate_zero_rate:.2f}% {'✅ 达标（<5%）' if quote_rate_zero_rate < 5.0 else '❌ 未达标（≥5%）'}

### trades_per_min
- **有效值数量**: {trades_per_min_valid}
- **覆盖率**: {trades_per_min_coverage:.2f}% {'✅ 达标（≥95%）' if trades_per_min_coverage >= 95.0 else '❌ 未达标（<95%）'}

### quote_updates_per_sec
- **有效值数量**: {quote_updates_per_sec_valid}
- **覆盖率**: {quote_updates_per_sec_coverage:.2f}% {'✅ 达标（≥95%）' if quote_updates_per_sec_coverage >= 95.0 else '❌ 未达标（<95%）'}

## 验收结果

**总体状态**: {'✅ 通过' if result['overall_passed'] else '❌ 未通过'}

**验收标准**:
- trade_rate覆盖率 ≥ 95%: {'✅' if trade_rate_coverage >= 95.0 else '❌'}
- trade_rate零值率 < 5%: {'✅' if trade_rate_zero_rate < 5.0 else '❌'}
- quote_rate覆盖率 ≥ 95%: {'✅' if quote_rate_coverage >= 95.0 else '❌'}
- quote_rate零值率 < 5%: {'✅' if quote_rate_zero_rate < 5.0 else '❌'}
"""
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    logger.info(f"活动度覆盖率报告已保存: {output_file}")
    
    return result


def main():
    parser = argparse.ArgumentParser(description="检查SQLite数据库中的活动度覆盖率")
    parser.add_argument("--sqlite-db", type=str, required=True, help="SQLite数据库路径")
    parser.add_argument("--out", type=str, required=True, help="输出Markdown报告路径")
    
    args = parser.parse_args()
    
    sqlite_db = Path(args.sqlite_db)
    if not sqlite_db.exists():
        logger.error(f"SQLite数据库不存在: {sqlite_db}")
        return 1
    
    output_file = Path(args.out)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    result = check_activity_coverage(sqlite_db, output_file)
    
    # 保存JSON结果
    json_file = output_file.with_suffix(".json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    if result["overall_passed"]:
        logger.info("✅ 活动度覆盖率检查通过")
        return 0
    else:
        logger.warning("❌ 活动度覆盖率检查未通过")
        return 1


if __name__ == "__main__":
    sys.exit(main())

