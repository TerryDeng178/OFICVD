#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gating Breakdown Normalizer

Report的gating_breakdown标准化：key归一化（小写、下划线、去空格），
并导出 risk_gate_breakdown_total{gate=*} 计数器
"""

import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def normalize_key(key: str) -> str:
    """归一化key（小写、下划线、去空格）
    
    Args:
        key: 原始key
        
    Returns:
        归一化后的key
    """
    # 转换为小写
    key = key.lower()
    
    # 替换空格为下划线
    key = key.replace(" ", "_")
    
    # 替换多个连续下划线为单个下划线
    key = re.sub(r"_+", "_", key)
    
    # 移除首尾下划线
    key = key.strip("_")
    
    return key


def normalize_gating_breakdown(breakdown: Dict) -> Dict:
    """归一化gating_breakdown字典
    
    Args:
        breakdown: 原始gating_breakdown字典
        
    Returns:
        归一化后的字典
    """
    normalized = {}
    
    for key, value in breakdown.items():
        normalized_key = normalize_key(key)
        normalized[normalized_key] = value
    
    return normalized


def extract_gate_breakdown_from_report(report_path: Path) -> Dict:
    """从报表文件中提取gating_breakdown
    
    Args:
        report_path: 报表文件路径
        
    Returns:
        gating_breakdown字典
    """
    if not report_path.exists():
        logger.warning(f"Report file not found: {report_path}")
        return {}
    
    try:
        with report_path.open("r", encoding="utf-8") as f:
            if report_path.suffix == ".json":
                data = json.load(f)
            elif report_path.suffix == ".jsonl":
                # JSONL格式：读取所有行并合并
                data = {}
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    data.update(item)
            else:
                logger.warning(f"Unsupported file format: {report_path.suffix}")
                return {}
        
        # 提取gating_breakdown
        if "gating_breakdown" in data:
            return data["gating_breakdown"]
        elif "timeseries_data" in data and "gating_breakdown" in data["timeseries_data"]:
            return data["timeseries_data"]["gating_breakdown"]
        else:
            logger.warning("gating_breakdown not found in report")
            return {}
            
    except Exception as e:
        logger.error(f"Failed to extract gating_breakdown: {e}")
        return {}


def generate_prometheus_metrics(breakdown: Dict) -> str:
    """生成Prometheus格式的risk_gate_breakdown_total指标
    
    Args:
        breakdown: 归一化后的gating_breakdown字典
        
    Returns:
        Prometheus格式的指标字符串
    """
    lines = []
    
    for gate, count in breakdown.items():
        # 确保gate名称符合Prometheus标签规范
        safe_gate = gate.replace("-", "_").replace(".", "_")
        lines.append(f'risk_gate_breakdown_total{{gate="{safe_gate}"}} {count}')
    
    return "\n".join(lines)


def process_report_file(report_path: Path, output_path: Path = None):
    """处理报表文件
    
    Args:
        report_path: 报表文件路径
        output_path: 输出文件路径（可选，如果提供则写入文件）
    """
    logger.info(f"Processing report: {report_path}")
    
    # 提取gating_breakdown
    breakdown = extract_gate_breakdown_from_report(report_path)
    
    if not breakdown:
        logger.warning("No gating_breakdown found, skipping")
        return
    
    # 归一化
    normalized_breakdown = normalize_gating_breakdown(breakdown)
    
    logger.info(f"Normalized breakdown: {normalized_breakdown}")
    
    # 生成Prometheus指标
    prometheus_output = generate_prometheus_metrics(normalized_breakdown)
    
    if output_path:
        with output_path.open("w", encoding="utf-8") as f:
            f.write(prometheus_output)
        logger.info(f"Prometheus metrics written to: {output_path}")
    else:
        print("\n=== Prometheus Metrics ===")
        print(prometheus_output)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gating Breakdown Normalizer")
    parser.add_argument(
        "report_file",
        type=str,
        help="Report file path (JSON or JSONL)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (optional, if not provided, print to stdout)",
    )
    
    args = parser.parse_args()
    
    report_path = Path(args.report_file)
    output_path = Path(args.output) if args.output else None
    
    process_report_file(report_path, output_path)


if __name__ == "__main__":
    main()

