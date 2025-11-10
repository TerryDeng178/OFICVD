# -*- coding: utf-8 -*-
"""对齐审计脚本：检查时间戳、盘口、活动度的一致性"""
import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict
import statistics

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


def check_timestamp_monotonicity(records: List[Dict[str, Any]], ts_field: str = "ts_ms") -> Dict[str, Any]:
    """检查时间戳单调性"""
    timestamps = []
    violations = []
    
    for i, rec in enumerate(records):
        ts = rec.get(ts_field)
        if ts is not None:
            timestamps.append(ts)
            if i > 0 and ts < timestamps[-2]:
                violations.append({
                    "index": i,
                    "ts": ts,
                    "prev_ts": timestamps[-2],
                    "diff_ms": ts - timestamps[-2]
                })
    
    return {
        "total_records": len(records),
        "valid_timestamps": len(timestamps),
        "violations": len(violations),
        "violation_rate": len(violations) / len(timestamps) if timestamps else 0.0,
        "sample_violations": violations[:10] if violations else []
    }


def check_missing_rate(records: List[Dict[str, Any]], fields: List[str]) -> Dict[str, float]:
    """检查字段缺失率"""
    missing_counts = defaultdict(int)
    total = len(records)
    
    for rec in records:
        for field in fields:
            if field not in rec or rec[field] is None:
                missing_counts[field] += 1
    
    return {field: missing_counts[field] / total if total > 0 else 0.0 for field in fields}


def check_activity_coverage(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """检查活动度字段覆盖率"""
    activity_fields = ["trades_per_min", "quote_updates_per_sec"]
    coverage = {}
    
    for field in activity_fields:
        valid_count = 0
        zero_count = 0
        total = len(records)
        
        for rec in records:
            value = rec.get(field)
            if value is not None:
                valid_count += 1
                if value == 0:
                    zero_count += 1
        
        coverage[field] = {
            "coverage_rate": valid_count / total if total > 0 else 0.0,
            "zero_rate": zero_count / total if total > 0 else 0.0,
            "valid_count": valid_count,
            "zero_count": zero_count,
            "total": total
        }
    
    return coverage


def check_lag_distribution(records: List[Dict[str, Any]], lag_field: str = "lag_sec") -> Dict[str, Any]:
    """检查延迟分布"""
    lags = []
    lag_ms_list = []
    
    for rec in records:
        # 尝试多种lag字段名
        lag_sec = rec.get(lag_field) or rec.get("lag_sec")
        lag_ms = rec.get("lag_ms") or rec.get("lag_ms_price") or rec.get("lag_ms_orderbook")
        
        if lag_sec is not None and isinstance(lag_sec, (int, float)):
            lags.append(float(lag_sec))
        if lag_ms is not None and isinstance(lag_ms, (int, float)):
            lag_ms_list.append(float(lag_ms))
    
    if not lags and not lag_ms_list:
        return {"error": "No lag data found"}
    
    # 使用lag_ms优先，如果没有则使用lag_sec * 1000
    if lag_ms_list:
        lag_data = lag_ms_list
        unit = "ms"
    else:
        lag_data = [l * 1000 for l in lags]
        unit = "ms"
    
    if not lag_data:
        return {"error": "No valid lag data"}
    
    sorted_lags = sorted(lag_data)
    n = len(sorted_lags)
    
    p50 = sorted_lags[n // 2] if n > 0 else None
    p95 = sorted_lags[int(n * 0.95)] if n > 0 else None
    p99 = sorted_lags[int(n * 0.99)] if n > 0 else None
    
    return {
        "count": n,
        "unit": unit,
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "max": sorted_lags[-1] if sorted_lags else None,
        "mean": statistics.mean(sorted_lags) if sorted_lags else None,
        "median": statistics.median(sorted_lags) if sorted_lags else None,
        "p95_target_met": p95 < 1500 if p95 is not None else None  # P95目标 < 1500ms
    }


def check_spread_distribution(records: List[Dict[str, Any]], spread_field: str = "spread_bps") -> Dict[str, Any]:
    """检查价差分布"""
    spreads = []
    
    for rec in records:
        spread = rec.get(spread_field)
        if spread is not None and isinstance(spread, (int, float)):
            spreads.append(float(spread))
    
    if not spreads:
        return {"error": "No spread data found"}
    
    sorted_spreads = sorted(spreads)
    n = len(sorted_spreads)
    
    # 99.9分位裁剪
    p999_index = int(n * 0.999)
    clipped_spreads = sorted_spreads[:p999_index] if p999_index < n else sorted_spreads
    
    return {
        "count": n,
        "p50": sorted_spreads[n // 2] if n > 0 else None,
        "p95": sorted_spreads[int(n * 0.95)] if n > 0 else None,
        "p99": sorted_spreads[int(n * 0.99)] if n > 0 else None,
        "p999": sorted_spreads[p999_index] if p999_index < n else sorted_spreads[-1] if sorted_spreads else None,
        "max": sorted_spreads[-1] if sorted_spreads else None,
        "mean": statistics.mean(clipped_spreads) if clipped_spreads else None,
        "median": statistics.median(clipped_spreads) if clipped_spreads else None,
        "clipped_count": len(clipped_spreads),
        "outliers_count": n - len(clipped_spreads)
    }


def generate_audit_report(
    input_file: Path,
    output_file: Path,
    fast_mode: bool = False
) -> None:
    """生成对齐审计报告"""
    logger.info(f"Loading records from {input_file}")
    records = load_jsonl(input_file)
    
    if not records:
        logger.warning("No records found")
        return
    
    logger.info(f"Loaded {len(records)} records")
    
    report = {
        "input_file": str(input_file),
        "total_records": len(records),
        "checks": {}
    }
    
    # 1. 时间戳单调性检查
    logger.info("Checking timestamp monotonicity...")
    report["checks"]["timestamp_monotonicity"] = check_timestamp_monotonicity(records)
    
    # 2. 字段缺失率检查
    logger.info("Checking missing rates...")
    key_fields = ["ts_ms", "symbol", "spread_bps", "lag_sec", "trades_per_min", "quote_updates_per_sec"]
    report["checks"]["missing_rates"] = check_missing_rate(records, key_fields)
    
    # 3. 活动度覆盖率检查
    logger.info("Checking activity coverage...")
    report["checks"]["activity_coverage"] = check_activity_coverage(records)
    
    # 4. 延迟分布检查
    logger.info("Checking lag distribution...")
    report["checks"]["lag_distribution"] = check_lag_distribution(records)
    
    # 5. 价差分布检查
    logger.info("Checking spread distribution...")
    report["checks"]["spread_distribution"] = check_spread_distribution(records)
    
    # 生成Markdown报告
    md_content = f"""# 对齐审计报告

**输入文件**: `{input_file}`  
**记录数**: {len(records)}  
**生成时间**: {Path(__file__).stat().st_mtime}

## 1. 时间戳单调性

- **总记录数**: {report['checks']['timestamp_monotonicity']['total_records']}
- **有效时间戳**: {report['checks']['timestamp_monotonicity']['valid_timestamps']}
- **违反次数**: {report['checks']['timestamp_monotonicity']['violations']}
- **违反率**: {report['checks']['timestamp_monotonicity']['violation_rate']:.2%}

## 2. 字段缺失率

"""
    
    for field, rate in report["checks"]["missing_rates"].items():
        md_content += f"- **{field}**: {rate:.2%}\n"
    
    md_content += "\n## 3. 活动度覆盖率\n\n"
    
    for field, stats in report["checks"]["activity_coverage"].items():
        md_content += f"### {field}\n"
        md_content += f"- **覆盖率**: {stats['coverage_rate']:.2%}\n"
        md_content += f"- **零值率**: {stats['zero_rate']:.2%}\n"
        md_content += f"- **有效数**: {stats['valid_count']}\n"
        md_content += f"- **零值数**: {stats['zero_count']}\n\n"
    
    md_content += "## 4. 延迟分布\n\n"
    
    lag_dist = report["checks"]["lag_distribution"]
    if "error" not in lag_dist:
        unit = lag_dist.get('unit', 'ms')
        p50 = lag_dist.get('p50', 0)
        p95 = lag_dist.get('p95', 0)
        p99 = lag_dist.get('p99', 0)
        max_val = lag_dist.get('max', 0)
        mean_val = lag_dist.get('mean', 0)
        p95_target_met = lag_dist.get('p95_target_met')
        
        md_content += f"- **单位**: {unit}\n"
        md_content += f"- **P50**: {p50:.2f} {unit}\n"
        md_content += f"- **P95**: {p95:.2f} {unit}"
        if p95_target_met is not None:
            md_content += f" {'✅ 达标' if p95_target_met else '❌ 未达标（目标<1500ms）'}\n"
        else:
            md_content += "\n"
        md_content += f"- **P99**: {p99:.2f} {unit}\n"
        md_content += f"- **最大值**: {max_val:.2f} {unit}\n"
        md_content += f"- **平均值**: {mean_val:.2f} {unit}\n"
    else:
        md_content += f"- **错误**: {lag_dist['error']}\n"
    
    md_content += "\n## 5. 价差分布\n\n"
    
    spread_dist = report["checks"]["spread_distribution"]
    if "error" not in spread_dist:
        p50 = spread_dist.get('p50', 0)
        p95 = spread_dist.get('p95', 0)
        p99 = spread_dist.get('p99', 0)
        p999 = spread_dist.get('p999', 0)
        max_val = spread_dist.get('max', 0)
        mean_val = spread_dist.get('mean', 0)
        outliers = spread_dist.get('outliers_count', 0)
        
        md_content += f"- **P50**: {p50:.2f} bps\n"
        md_content += f"- **P95**: {p95:.2f} bps\n"
        md_content += f"- **P99**: {p99:.2f} bps\n"
        md_content += f"- **P99.9**: {p999:.2f} bps\n"
        md_content += f"- **最大值**: {max_val:.2f} bps\n"
        md_content += f"- **平均值（99.9%裁剪后）**: {mean_val:.2f} bps\n"
        md_content += f"- **异常值数（>P99.9）**: {outliers}\n"
    else:
        md_content += f"- **错误**: {spread_dist['error']}\n"
    
    md_content += "\n## 6. JSONL vs SQLite 窗口一致性\n\n"
    md_content += "⚠️ **待实现**: 需要对比JSONL和SQLite sink的记录数差异\n"
    md_content += "- 目标：记录数差异 < 5%\n"
    
    # 保存JSON报告
    json_output = output_file.with_suffix(".json")
    with open(json_output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    # 保存Markdown报告
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    logger.info(f"Audit report saved to {output_file}")
    logger.info(f"JSON report saved to {json_output}")


def main():
    parser = argparse.ArgumentParser(description="对齐审计脚本")
    parser.add_argument("--input", type=str, help="输入JSONL文件路径")
    parser.add_argument("--out", type=str, default="./runtime/reports/alignment_audit.md", help="输出报告路径")
    parser.add_argument("--fast", action="store_true", help="快速模式（跳过部分检查）")
    
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
    
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    generate_audit_report(input_file, output_file, fast_mode=args.fast)


if __name__ == "__main__":
    main()

