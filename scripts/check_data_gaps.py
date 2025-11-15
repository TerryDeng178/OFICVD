#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据时间空档检查脚本

检查JSONL/CSV文件中时间戳的连续性，评估数据完整性
"""

import sys
import json
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
import argparse

def load_timestamps_from_jsonl(path: str, ts_field: str = "ts_ms") -> List[int]:
    """从JSONL文件加载时间戳"""
    ts_list = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    ts = obj.get(ts_field) or obj.get("event_time_ms") or obj.get("event_ts_ms")
                    if ts is None:
                        continue
                    ts_list.append(int(ts))
                except json.JSONDecodeError as e:
                    print(f"  警告: 第{line_num}行JSON解析错误: {e}")
                    continue
    except FileNotFoundError:
        print(f"[ERROR] 文件不存在: {path}")
        return []
    except Exception as e:
        print(f"[ERROR] 读取文件失败: {e}")
        return []

    return ts_list

def load_timestamps_from_csv(path: str, ts_column: str = "ts_ms") -> List[int]:
    """从CSV文件加载时间戳"""
    ts_list = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = row.get(ts_column)
                if ts is None:
                    continue
                try:
                    ts_list.append(int(ts))
                except ValueError:
                    continue
    except Exception as e:
        print(f"[ERROR] 读取CSV失败: {e}")
        return []

    return ts_list

def analyze_gaps(ts_list: List[int], max_allowed_gap_sec: int = 60) -> dict:
    """分析时间戳空档"""
    if not ts_list:
        return {
            'status': 'NO_DATA',
            'message': '无有效时间戳数据'
        }

    ts_list.sort()
    min_ts, max_ts = ts_list[0], ts_list[-1]
    total_span_sec = (max_ts - min_ts) / 1000

    gaps = []
    for a, b in zip(ts_list, ts_list[1:]):
        gap_sec = (b - a) / 1000
        gaps.append(gap_sec)

    max_gap_sec = max(gaps) if gaps else 0

    # 计算覆盖率：把每个间隔cap到max_allowed_gap_sec再累加
    covered_sec = sum(min(g, max_allowed_gap_sec) for g in gaps)
    coverage_ratio = covered_sec / total_span_sec if total_span_sec > 0 else 1.0

    # 分析结果
    is_good = max_gap_sec <= max_allowed_gap_sec and coverage_ratio >= 0.95

    return {
        'status': 'OK' if is_good else 'RISK',
        'min_ts': min_ts,
        'max_ts': max_ts,
        'total_span_sec': total_span_sec,
        'max_gap_sec': max_gap_sec,
        'coverage_ratio': coverage_ratio,
        'record_count': len(ts_list),
        'gap_count': len([g for g in gaps if g > max_allowed_gap_sec]),
        'assessment': 'GO' if is_good else 'REVIEW'
    }

def check_file_gaps(path: str, ts_field: str = "ts_ms", max_allowed_gap_sec: int = 60):
    """检查单个文件的时间空档"""
    file_path = Path(path)

    if not file_path.exists():
        print(f"[ERROR] 文件不存在: {path}")
        return

    print(f"[CHECK] 检查文件: {path}")

    # 根据文件扩展名选择加载方式
    if path.endswith('.jsonl') or path.endswith('.json'):
        ts_list = load_timestamps_from_jsonl(path, ts_field)
    elif path.endswith('.csv'):
        ts_list = load_timestamps_from_csv(path, ts_field)
    else:
        print(f"[ERROR] 不支持的文件格式: {path}")
        return

    if not ts_list:
        print(f"  无有效时间戳数据")
        return

    result = analyze_gaps(ts_list, max_allowed_gap_sec)

    if result['status'] == 'NO_DATA':
        print(f"  {result['message']}")
        return

    # 输出结果
    min_time = datetime.utcfromtimestamp(result['min_ts'] / 1000)
    max_time = datetime.utcfromtimestamp(result['max_ts'] / 1000)

    print(f"  记录数量: {result['record_count']:,}")
    print(f"  时间范围: {min_time} ~ {max_time}")
    print(f"  时间跨度: {result['total_span_sec']:.1f} 秒")
    print(f"  最大空档: {result['max_gap_sec']:.2f} 秒")
    print(f"  覆盖率: {result['coverage_ratio']*100:.1f}%")
    print(f"  大空档数量: {result['gap_count']} 个")

    if result['assessment'] == 'GO':
        print("  => 数据完整性: [GO] 可用于正式回测评估")
    else:
        print("  => 数据完整性: [REVIEW] 建议检查，可能存在较大空档")

def batch_check_data_quality(data_root: str, symbols: List[str] = None,
                           max_gap_sec: int = 60, ts_field: str = "ts_ms"):
    """批量检查数据质量"""
    data_path = Path(data_root)
    if not data_path.exists():
        print(f"[ERROR] 数据目录不存在: {data_root}")
        return

    print(f"[BATCH] 批量检查数据质量: {data_root}")
    print(f"  最大允许空档: {max_gap_sec}秒")
    print(f"  时间戳字段: {ts_field}")
    print("-" * 80)

    results = []

    # 查找所有数据文件
    for file_path in data_path.rglob("*.jsonl"):
        # 检查是否是目标交易对
        if symbols:
            symbol_found = False
            for symbol in symbols:
                if symbol.lower() in file_path.name.lower():
                    symbol_found = True
                    break
            if not symbol_found:
                continue

        try:
            check_file_gaps(str(file_path), ts_field, max_gap_sec)
            print()
        except Exception as e:
            print(f"[ERROR] 检查文件失败 {file_path}: {e}")
            print()

def main():
    parser = argparse.ArgumentParser(description='数据时间空档检查')
    parser.add_argument('path', help='要检查的文件路径')
    parser.add_argument('--ts-field', default='ts_ms',
                       help='时间戳字段名 (默认: ts_ms)')
    parser.add_argument('--max-gap-sec', type=int, default=60,
                       help='最大允许空档秒数 (默认: 60)')
    parser.add_argument('--batch', action='store_true',
                       help='批量检查模式')
    parser.add_argument('--symbols', nargs='+',
                       help='指定交易对列表 (批量模式)')

    args = parser.parse_args()

    if args.batch:
        batch_check_data_quality(
            args.path,
            symbols=args.symbols,
            max_gap_sec=args.max_gap_sec,
            ts_field=args.ts_field
        )
    else:
        check_file_gaps(
            args.path,
            ts_field=args.ts_field,
            max_gap_sec=args.max_gap_sec
        )

if __name__ == "__main__":
    main()
