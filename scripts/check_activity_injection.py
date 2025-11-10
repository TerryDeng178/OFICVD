# -*- coding: utf-8 -*-
"""检查活动度字段注入情况"""
import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_jsonl(file_path: Path) -> List[Dict[str, Any]]:
    """加载JSONL文件"""
    records = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except Exception as e:
        logger.error(f"Error loading {file_path}: {e}")
    return records


def check_activity_fields(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """检查活动度字段"""
    activity_fields = ["trade_rate", "quote_rate", "trades_per_min", "quote_updates_per_sec"]
    
    stats = {
        "total_records": len(records),
        "field_stats": {},
        "coverage": {},
        "zero_rate": {},
        "distribution": {}
    }
    
    for field in activity_fields:
        valid_count = 0
        zero_count = 0
        values = []
        
        for rec in records:
            # 检查多种可能的字段名
            value = None
            if field in rec:
                value = rec[field]
            elif "activity" in rec and isinstance(rec["activity"], dict):
                if field in rec["activity"]:
                    value = rec["activity"][field]
            
            if value is not None:
                valid_count += 1
                if isinstance(value, (int, float)):
                    values.append(float(value))
                    if value == 0:
                        zero_count += 1
        
        stats["field_stats"][field] = {
            "valid_count": valid_count,
            "total": len(records),
            "coverage_rate": valid_count / len(records) if records else 0.0
        }
        
        stats["coverage"][field] = valid_count / len(records) if records else 0.0
        stats["zero_rate"][field] = zero_count / len(records) if records else 0.0
        
        if values:
            stats["distribution"][field] = {
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / len(values),
                "non_zero_count": len(values) - zero_count
            }
    
    return stats


def generate_activity_report(
    input_file: Path,
    output_file: Path
) -> None:
    """生成活动度注入报告"""
    logger.info(f"Loading records from {input_file}")
    records = load_jsonl(input_file)
    
    if not records:
        logger.warning("No records found")
        return
    
    logger.info(f"Loaded {len(records)} records")
    
    stats = check_activity_fields(records)
    
    # 生成Markdown报告
    md_content = f"""# 活动度字段注入复核报告

**输入文件**: `{input_file}`  
**记录数**: {len(records)}  
**生成时间**: {Path(__file__).stat().st_mtime}

## 字段覆盖率

"""
    
    for field, coverage in stats["coverage"].items():
        md_content += f"- **{field}**: {coverage:.2%}\n"
    
    md_content += "\n## 零值率\n\n"
    
    for field, zero_rate in stats["zero_rate"].items():
        md_content += f"- **{field}**: {zero_rate:.2%}\n"
    
    md_content += "\n## 字段分布\n\n"
    
    for field, dist in stats["distribution"].items():
        md_content += f"### {field}\n"
        md_content += f"- **最小值**: {dist['min']:.2f}\n"
        md_content += f"- **最大值**: {dist['max']:.2f}\n"
        md_content += f"- **平均值**: {dist['mean']:.2f}\n"
        md_content += f"- **非零值数**: {dist['non_zero_count']}\n\n"
    
    md_content += "## 验收标准\n\n"
    
    # 检查覆盖率是否≥95%
    all_coverage_ok = all(c >= 0.95 for c in stats["coverage"].values())
    all_zero_rate_ok = all(z < 0.05 for z in stats["zero_rate"].values())
    
    md_content += f"- **覆盖率≥95%**: {'✅ 通过' if all_coverage_ok else '❌ 未通过'}\n"
    md_content += f"- **零值率<5%**: {'✅ 通过' if all_zero_rate_ok else '❌ 未通过'}\n"
    
    if not all_coverage_ok:
        md_content += "\n⚠️ **问题**: 部分字段覆盖率 < 95%，需要检查注入逻辑\n"
    
    if not all_zero_rate_ok:
        md_content += "\n⚠️ **问题**: 部分字段零值率 ≥ 5%，需要检查计算逻辑\n"
    
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    logger.info(f"Activity injection report saved to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="检查活动度字段注入")
    parser.add_argument("--input", type=str, help="输入JSONL文件路径（features或signals）")
    parser.add_argument("--out", type=str, default="./runtime/reports/activity_injection.md", help="输出报告路径")
    
    args = parser.parse_args()
    
    if not args.input:
        # 尝试查找最新的features文件
        input_dir = Path("./deploy/data/ofi_cvd")
        if input_dir.exists():
            feature_files = list(input_dir.glob("**/features_*.jsonl"))
            if feature_files:
                args.input = str(max(feature_files, key=lambda p: p.stat().st_mtime))
                logger.info(f"Auto-detected input file: {args.input}")
            else:
                logger.error("No input file specified and no feature files found")
                return
        else:
            logger.error("No input file specified and input directory not found")
            return
    
    input_file = Path(args.input)
    output_file = Path(args.out)
    
    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        return
    
    generate_activity_report(input_file, output_file)


if __name__ == "__main__":
    main()

