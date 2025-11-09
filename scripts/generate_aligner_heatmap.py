#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P2.2: Aligner对齐完整度heatmap生成脚本

生成每分钟对齐完整度heatmap（0-60s命中率），快速扫盘数据空洞
"""
import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


def generate_heatmap_from_features(features: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从features数据生成对齐完整度heatmap
    
    Args:
        features: Feature记录列表
    
    Returns:
        Heatmap数据（按分钟分组，每秒钟命中率）
    """
    # 按分钟分组
    minute_data: Dict[str, Dict[int, bool]] = defaultdict(lambda: {i: False for i in range(60)})
    
    for feature in features:
        ts_ms = feature.get("ts_ms", 0)
        if ts_ms <= 0:
            continue
        
        # 转换为datetime
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        
        # 生成分钟键（YYYY-MM-DD HH:MM）
        minute_key = dt.strftime("%Y-%m-%d %H:%M")
        
        # 获取秒数（0-59）
        second = dt.second
        
        # 标记该秒有数据
        minute_data[minute_key][second] = True
    
    # 计算每分钟的完整度
    heatmap = {}
    for minute_key, seconds_data in minute_data.items():
        hit_count = sum(1 for hit in seconds_data.values() if hit)
        completeness = hit_count / 60.0  # 0-1之间
        
        heatmap[minute_key] = {
            "completeness": completeness,
            "hit_count": hit_count,
            "miss_count": 60 - hit_count,
            "seconds": seconds_data,  # 详细的秒级命中情况
        }
    
    return heatmap


def generate_heatmap_from_files(input_dir: Path, kind: str = "features") -> Dict[str, Any]:
    """从文件读取features并生成heatmap
    
    Args:
        input_dir: 输入目录
        kind: 数据类型（features）
    
    Returns:
        Heatmap数据
    """
    from alpha_core.backtest.reader import DataReader
    
    reader = DataReader(input_dir=input_dir, kinds=[kind])
    features = list(reader.read_features())
    
    return generate_heatmap_from_features(features)


def save_heatmap_csv(heatmap: Dict[str, Any], output_file: Path):
    """保存heatmap为CSV格式（Excel可打开）"""
    import csv
    
    with output_file.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig for Excel
        writer = csv.writer(f)
        
        # 表头
        writer.writerow(["Minute", "Completeness", "Hit_Count", "Miss_Count"] + [f"Second_{i}" for i in range(60)])
        
        # 数据行
        for minute_key in sorted(heatmap.keys()):
            data = heatmap[minute_key]
            row = [
                minute_key,
                f"{data['completeness']:.4f}",
                data["hit_count"],
                data["miss_count"],
            ]
            # 添加每秒钟的命中情况（1=hit, 0=miss）
            for i in range(60):
                row.append(1 if data["seconds"][i] else 0)
            writer.writerow(row)
    
    logger.info(f"Heatmap CSV saved to: {output_file}")


def save_heatmap_json(heatmap: Dict[str, Any], output_file: Path):
    """保存heatmap为JSON格式"""
    # 转换为可序列化格式
    serializable_heatmap = {}
    for minute_key, data in heatmap.items():
        serializable_heatmap[minute_key] = {
            "completeness": data["completeness"],
            "hit_count": data["hit_count"],
            "miss_count": data["miss_count"],
            "seconds": [1 if data["seconds"][i] else 0 for i in range(60)],
        }
    
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(serializable_heatmap, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Heatmap JSON saved to: {output_file}")


def generate_summary_stats(heatmap: Dict[str, Any]) -> Dict[str, Any]:
    """生成汇总统计"""
    if not heatmap:
        return {}
    
    completeness_values = [data["completeness"] for data in heatmap.values()]
    hit_counts = [data["hit_count"] for data in heatmap.values()]
    
    import statistics
    
    stats = {
        "total_minutes": len(heatmap),
        "avg_completeness": statistics.mean(completeness_values) if completeness_values else 0.0,
        "min_completeness": min(completeness_values) if completeness_values else 0.0,
        "max_completeness": max(completeness_values) if completeness_values else 0.0,
        "median_completeness": statistics.median(completeness_values) if completeness_values else 0.0,
        "avg_hit_count": statistics.mean(hit_counts) if hit_counts else 0.0,
        "total_missing_seconds": sum(60 - hc for hc in hit_counts),
    }
    
    # 找出完整度最低的分钟
    if heatmap:
        worst_minute = min(heatmap.items(), key=lambda x: x[1]["completeness"])
        stats["worst_minute"] = {
            "minute": worst_minute[0],
            "completeness": worst_minute[1]["completeness"],
            "miss_count": worst_minute[1]["miss_count"],
        }
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Generate alignment completeness heatmap (0-60s hit rate per minute)"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input data directory",
    )
    parser.add_argument(
        "--kind",
        default="features",
        help="Data kind (default: features)",
    )
    parser.add_argument(
        "--output-csv",
        help="Output CSV file (Excel-compatible)",
    )
    parser.add_argument(
        "--output-json",
        help="Output JSON file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    
    args = parser.parse_args()
    
    # 配置日志
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    
    # 生成heatmap
    logger.info(f"Reading features from: {args.input}")
    heatmap = generate_heatmap_from_files(Path(args.input), args.kind)
    
    if not heatmap:
        logger.warning("No heatmap data generated")
        sys.exit(1)
    
    # 生成汇总统计
    stats = generate_summary_stats(heatmap)
    
    # 打印摘要
    print("\n" + "=" * 80)
    print("Alignment Completeness Heatmap Summary")
    print("=" * 80)
    print(f"Total Minutes: {stats.get('total_minutes', 0)}")
    print(f"Average Completeness: {stats.get('avg_completeness', 0.0)*100:.2f}%")
    print(f"Min Completeness: {stats.get('min_completeness', 0.0)*100:.2f}%")
    print(f"Max Completeness: {stats.get('max_completeness', 0.0)*100:.2f}%")
    print(f"Median Completeness: {stats.get('median_completeness', 0.0)*100:.2f}%")
    print(f"Total Missing Seconds: {stats.get('total_missing_seconds', 0)}")
    
    worst = stats.get("worst_minute")
    if worst:
        print(f"\nWorst Minute: {worst['minute']}")
        print(f"  Completeness: {worst['completeness']*100:.2f}%")
        print(f"  Missing Seconds: {worst['miss_count']}")
    
    print("=" * 80)
    
    # 保存输出
    if args.output_csv:
        save_heatmap_csv(heatmap, Path(args.output_csv))
    
    if args.output_json:
        output_json_path = Path(args.output_json)
        # 保存heatmap和stats
        combined = {
            "heatmap": heatmap,
            "stats": stats,
        }
        save_heatmap_json(combined, output_json_path)
    
    sys.exit(0)


if __name__ == "__main__":
    main()

