#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据连续性检查脚本

检查采集数据是否存在空档，并评估对回测的影响
"""

import argparse
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def analyze_data_gaps(data_dir: Path, symbol: str, max_gap_minutes: int = 10) -> Dict[str, Any]:
    """分析数据空档

    Args:
        data_dir: 数据目录
        symbol: 交易对
        max_gap_minutes: 最大允许空档分钟数

    Returns:
        空档分析结果
    """
    gaps = []
    total_files = 0
    total_rows = 0
    time_ranges = []

    # 查找所有数据文件
    for parquet_file in data_dir.rglob(f"**/symbol={symbol}/**/*.parquet"):
        total_files += 1

        try:
            # 解析文件名获取时间范围
            # 格式: part-{start_ms}-{end_ms}-{rows}-{writerid}.parquet
            filename = parquet_file.name
            if not filename.startswith("part-"):
                continue

            parts = filename.split("-")
            if len(parts) < 4:
                continue

            start_ms = int(parts[1])
            end_ms = int(parts[2])

            time_ranges.append((start_ms, end_ms, parquet_file))

        except (ValueError, IndexError) as e:
            logger.warning(f"无法解析文件时间: {parquet_file} - {e}")
            continue

    # 按时间排序
    time_ranges.sort(key=lambda x: x[0])

    # 检测空档
    prev_end_ms = None
    max_gap_ms = max_gap_minutes * 60 * 1000

    for start_ms, end_ms, file_path in time_ranges:
        total_rows += (end_ms - start_ms) // 1000  # 估算行数（每秒一行）

        if prev_end_ms is not None:
            gap_ms = start_ms - prev_end_ms
            if gap_ms > max_gap_ms:
                gaps.append({
                    'start_time': datetime.fromtimestamp(prev_end_ms / 1000).isoformat(),
                    'end_time': datetime.fromtimestamp(start_ms / 1000).isoformat(),
                    'gap_minutes': gap_ms / (60 * 1000),
                    'gap_ms': gap_ms,
                    'prev_file': str(prev_file_path),
                    'next_file': str(file_path)
                })

        prev_end_ms = end_ms
        prev_file_path = file_path

    # 计算覆盖率
    if time_ranges:
        total_start = min(r[0] for r in time_ranges)
        total_end = max(r[1] for r in time_ranges)
        total_duration_ms = total_end - total_start
        covered_duration_ms = sum(r[1] - r[0] for r in time_ranges)
        coverage_ratio = covered_duration_ms / total_duration_ms if total_duration_ms > 0 else 0
    else:
        coverage_ratio = 0
        total_duration_ms = 0

    return {
        'symbol': symbol,
        'total_files': total_files,
        'total_rows': total_rows,
        'gaps_count': len(gaps),
        'gaps': gaps,
        'coverage_ratio': coverage_ratio,
        'total_duration_hours': total_duration_ms / (1000 * 60 * 60),
        'critical_gaps': [g for g in gaps if g['gap_minutes'] > 30],  # 超过30分钟的严重空档
        'assessment': {
            'data_quality': 'GOOD' if len(gaps) == 0 else ('FAIR' if len(gaps) <= 5 else 'POOR'),
            'backtest_risk': 'LOW' if len([g for g in gaps if g['gap_minutes'] > 5]) == 0 else 'HIGH',
            'recommendations': []
        }
    }


def generate_report(results: List[Dict[str, Any]], output_file: Path):
    """生成分析报告"""

    report = {
        'analysis_timestamp': datetime.now().isoformat(),
        'summary': {
            'total_symbols': len(results),
            'total_gaps': sum(r['gaps_count'] for r in results),
            'critical_gaps': sum(len(r['critical_gaps']) for r in results),
            'average_coverage': sum(r['coverage_ratio'] for r in results) / len(results) if results else 0
        },
        'symbol_details': results,
        'risk_assessment': {
            'overall_risk': 'LOW',
            'issues': [],
            'recommendations': []
        }
    }

    # 风险评估
    high_risk_symbols = [r for r in results if r['assessment']['backtest_risk'] == 'HIGH']
    poor_quality_symbols = [r for r in results if r['assessment']['data_quality'] == 'POOR']

    if high_risk_symbols:
        report['risk_assessment']['overall_risk'] = 'HIGH'
        report['risk_assessment']['issues'].append(f"{len(high_risk_symbols)}个交易对存在严重数据空档")

    if poor_quality_symbols:
        report['risk_assessment']['overall_risk'] = 'MEDIUM' if report['risk_assessment']['overall_risk'] == 'LOW' else 'HIGH'
        report['risk_assessment']['issues'].append(f"{len(poor_quality_symbols)}个交易对数据质量较差")

    # 生成建议
    if report['risk_assessment']['overall_risk'] != 'LOW':
        report['risk_assessment']['recommendations'].extend([
            "建议在回测前修复数据空档或使用数据质量更好的时间段",
            "考虑实施数据连续性监控，在采集过程中检测并报警空档",
            "对于关键交易对，可以考虑多采集器并行采集以提高可靠性"
        ])
    else:
        report['risk_assessment']['recommendations'].append("数据连续性良好，可以正常进行回测")

    # 保存报告
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


def main():
    parser = argparse.ArgumentParser(description='数据连续性检查')
    parser.add_argument('--data-dir', type=str, default='./deploy/data/ofi_cvd/raw',
                       help='数据目录路径')
    parser.add_argument('--symbols', type=str, nargs='+',
                       help='要检查的交易对，不指定则检查所有')
    parser.add_argument('--max-gap-minutes', type=int, default=10,
                       help='最大允许空档分钟数')
    parser.add_argument('--output', type=str, default='./data_continuity_report.json',
                       help='输出报告文件路径')

    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        logger.error(f"数据目录不存在: {data_dir}")
        sys.exit(1)

    # 发现所有交易对
    symbols = set()
    for parquet_file in data_dir.rglob("*.parquet"):
        for part in parquet_file.parts:
            if part.startswith("symbol="):
                symbols.add(part.split("=")[1])

    if args.symbols:
        symbols = set(args.symbols) & symbols

    if not symbols:
        logger.error("未找到任何交易对数据")
        sys.exit(1)

    logger.info(f"开始检查 {len(symbols)} 个交易对的数据连续性...")
    logger.info(f"交易对: {sorted(symbols)}")

    results = []
    for symbol in sorted(symbols):
        logger.info(f"分析 {symbol}...")
        result = analyze_data_gaps(data_dir, symbol, args.max_gap_minutes)
        results.append(result)

        # 打印摘要
        print(f"\n{symbol} 数据连续性分析:")
        print(f"  文件数: {result['total_files']}")
        print(".1f")
        print(f"  空档数: {result['gaps_count']}")
        print(".1f")
        print(f"  数据质量: {result['assessment']['data_quality']}")
        print(f"  回测风险: {result['assessment']['backtest_risk']}")

        if result['critical_gaps']:
            print(f"  ⚠️ 严重空档: {len(result['critical_gaps'])}个")
            for gap in result['critical_gaps'][:3]:  # 只显示前3个
                print(".1f")

    # 生成报告
    output_file = Path(args.output)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    report = generate_report(results, output_file)
    logger.info(f"分析报告已保存到: {output_file}")

    print("\n=== 整体风险评估 ===")
    print(f"风险等级: {report['risk_assessment']['overall_risk']}")

    if report['risk_assessment']['issues']:
        print("发现的问题:")
        for issue in report['risk_assessment']['issues']:
            print(f"  - {issue}")

    print("建议:")
    for rec in report['risk_assessment']['recommendations']:
        print(f"  - {rec}")


if __name__ == "__main__":
    main()
