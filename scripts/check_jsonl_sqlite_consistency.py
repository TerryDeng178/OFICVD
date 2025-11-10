# -*- coding: utf-8 -*-
"""检查JSONL和SQLite sink的记录数一致性"""
import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def count_jsonl_records(jsonl_file: Path) -> int:
    """统计JSONL文件记录数"""
    count = 0
    try:
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    count += 1
    except Exception as e:
        logger.error(f"Error counting JSONL records: {e}")
    return count


def count_sqlite_records(db_file: Path, table: str = "signals") -> int:
    """统计SQLite表记录数"""
    try:
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.error(f"Error counting SQLite records: {e}")
        return 0


def check_consistency(
    jsonl_dir: Path,
    sqlite_dir: Optional[Path] = None,
    table: str = "signals"
) -> Dict[str, Any]:
    """检查JSONL和SQLite的一致性"""
    result = {
        "jsonl_files": [],
        "sqlite_files": [],
        "comparisons": [],
        "summary": {}
    }
    
    # 查找JSONL文件
    jsonl_files = list(jsonl_dir.glob("**/*.jsonl"))
    result["jsonl_files"] = [str(f) for f in jsonl_files]
    
    # 查找SQLite文件
    if sqlite_dir and sqlite_dir.exists():
        sqlite_files = list(sqlite_dir.glob("**/*.db"))
        result["sqlite_files"] = [str(f) for f in sqlite_files]
    else:
        # 尝试在同一目录查找
        sqlite_files = list(jsonl_dir.glob("**/*.db"))
        result["sqlite_files"] = [str(f) for f in sqlite_files]
    
    # 对比记录数
    jsonl_total = 0
    sqlite_total = 0
    
    for jsonl_file in jsonl_files:
        jsonl_count = count_jsonl_records(jsonl_file)
        jsonl_total += jsonl_count
        
        # 尝试找到对应的SQLite文件
        sqlite_file = None
        for sf in sqlite_files:
            # 简单的文件名匹配（可以根据实际情况调整）
            if jsonl_file.stem in sf.stem or sf.stem in jsonl_file.stem:
                sqlite_file = sf
                break
        
        if sqlite_file:
            sqlite_count = count_sqlite_records(sqlite_file, table)
            sqlite_total += sqlite_count
            
            diff = abs(jsonl_count - sqlite_count)
            diff_pct = (diff / jsonl_count * 100) if jsonl_count > 0 else 0.0
            
            result["comparisons"].append({
                "jsonl_file": str(jsonl_file),
                "sqlite_file": str(sqlite_file),
                "jsonl_count": jsonl_count,
                "sqlite_count": sqlite_count,
                "difference": diff,
                "difference_pct": diff_pct,
                "within_threshold": diff_pct < 5.0
            })
        else:
            result["comparisons"].append({
                "jsonl_file": str(jsonl_file),
                "sqlite_file": None,
                "jsonl_count": jsonl_count,
                "sqlite_count": 0,
                "difference": jsonl_count,
                "difference_pct": 100.0,
                "within_threshold": False
            })
    
    # 汇总
    total_diff = abs(jsonl_total - sqlite_total)
    total_diff_pct = (total_diff / jsonl_total * 100) if jsonl_total > 0 else 0.0
    
    result["summary"] = {
        "jsonl_total": jsonl_total,
        "sqlite_total": sqlite_total,
        "total_difference": total_diff,
        "total_difference_pct": total_diff_pct,
        "within_threshold": total_diff_pct < 5.0,
        "jsonl_file_count": len(jsonl_files),
        "sqlite_file_count": len(sqlite_files)
    }
    
    return result


def generate_report(consistency_result: Dict[str, Any], output_file: Path) -> None:
    """生成一致性报告"""
    md_content = f"""# JSONL vs SQLite 窗口一致性报告

**生成时间**: {Path(__file__).stat().st_mtime}

## 汇总统计

- **JSONL总记录数**: {consistency_result['summary']['jsonl_total']}
- **SQLite总记录数**: {consistency_result['summary']['sqlite_total']}
- **总差异**: {consistency_result['summary']['total_difference']} ({consistency_result['summary']['total_difference_pct']:.2f}%)
- **是否达标**: {'✅ 达标（差异<5%）' if consistency_result['summary']['within_threshold'] else '❌ 未达标（差异≥5%）'}
- **JSONL文件数**: {consistency_result['summary']['jsonl_file_count']}
- **SQLite文件数**: {consistency_result['summary']['sqlite_file_count']}

## 详细对比

"""
    
    if consistency_result["comparisons"]:
        md_content += "| JSONL文件 | SQLite文件 | JSONL记录数 | SQLite记录数 | 差异 | 差异% | 状态 |\n"
        md_content += "|-----------|------------|-------------|--------------|------|-------|------|\n"
        
        for comp in consistency_result["comparisons"]:
            jsonl_name = Path(comp["jsonl_file"]).name
            sqlite_name = Path(comp["sqlite_file"]).name if comp["sqlite_file"] else "N/A"
            status = "✅ 达标" if comp["within_threshold"] else "❌ 未达标"
            
            md_content += f"| {jsonl_name} | {sqlite_name} | {comp['jsonl_count']} | {comp['sqlite_count']} | {comp['difference']} | {comp['difference_pct']:.2f}% | {status} |\n"
    else:
        md_content += "⚠️ **无对比数据**: 未找到对应的SQLite文件\n"
    
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    logger.info(f"Consistency report saved to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="检查JSONL和SQLite一致性")
    parser.add_argument("--jsonl-dir", type=str, required=True, help="JSONL文件目录")
    parser.add_argument("--sqlite-dir", type=str, help="SQLite文件目录（可选，默认与JSONL目录相同）")
    parser.add_argument("--table", type=str, default="signals", help="SQLite表名")
    parser.add_argument("--out", type=str, default="./runtime/reports/jsonl_sqlite_consistency.md", help="输出报告路径")
    
    args = parser.parse_args()
    
    jsonl_dir = Path(args.jsonl_dir)
    sqlite_dir = Path(args.sqlite_dir) if args.sqlite_dir else None
    
    if not jsonl_dir.exists():
        logger.error(f"JSONL directory not found: {jsonl_dir}")
        return 1
    
    consistency_result = check_consistency(jsonl_dir, sqlite_dir, args.table)
    generate_report(consistency_result, Path(args.out))
    
    return 0


if __name__ == "__main__":
    exit(main())

