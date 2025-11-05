#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查 HARVEST 运行3分钟后的数据生成情况
"""

import pandas as pd
from pathlib import Path
import json

print("=" * 60)
print("HARVEST 3分钟运行检查报告")
print("=" * 60)

# 1. 检查 Manifest 文件
manifest_file = Path("deploy/artifacts/ofi_cvd/run_logs/run_manifest_20251105_200540.json")
if manifest_file.exists():
    with open(manifest_file, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    print("\n[1] Manifest 文件检查:")
    print(f"  - 运行ID: {manifest['run_id']}")
    print(f"  - 开始时间: {manifest['start_time']}")
    print(f"  - 符号数量: {len(manifest['config']['symbols'])}")
    print(f"  - DQ汇总: {len(manifest.get('dq_summary', {}))} 种类型")
    if manifest.get('dq_summary'):
        for kind, stats in manifest['dq_summary'].items():
            print(f"    - {kind}: ok={stats['ok_rows']}, bad={stats['bad_rows']}, ratio={stats['bad_ratio']}%")
    else:
        print("    - 无坏数据（正常）")
else:
    print("\n[1] Manifest 文件: 未找到")

# 2. 检查 RAW 数据（prices）
raw_prices_file = Path("deploy/data/ofi_cvd/date=2025-11-05/hour=20/symbol=btcusdt/kind=prices/part-1762373260138606500-59109b.parquet")
if raw_prices_file.exists():
    df = pd.read_parquet(raw_prices_file)
    print("\n[2] RAW Prices 数据检查:")
    print(f"  - 文件: {raw_prices_file.name}")
    print(f"  - 行数: {len(df)}")
    print(f"  - 列数: {len(df.columns)}")
    print(f"  - 列名: {list(df.columns)[:10]}...")
    if 'schema_version' in df.columns:
        print(f"  - schema_version: {df['schema_version'].iloc[0]}")
    else:
        print("  - schema_version: 未找到（问题！）")
else:
    print("\n[2] RAW Prices 数据: 未找到")

# 3. 检查 Preview 数据（ofi）
preview_ofi_file = Path("deploy/preview/ofi_cvd/date=2025-11-05/hour=20/symbol=btcusdt/kind=ofi/part-1762373260254053500-299a7b.parquet")
if preview_ofi_file.exists():
    df = pd.read_parquet(preview_ofi_file)
    print("\n[3] Preview OFI 数据检查:")
    print(f"  - 文件: {preview_ofi_file.name}")
    print(f"  - 行数: {len(df)}")
    print(f"  - 列数: {len(df.columns)}")
    print(f"  - 列名: {list(df.columns)}")
    if 'schema_version' in df.columns:
        print(f"  - schema_version: {df['schema_version'].iloc[0]}")
    else:
        print("  - schema_version: 未找到（问题！）")
    
    # 检查是否包含大字段（应该被裁剪掉）
    large_fields = ['bids', 'asks', 'bids_json', 'asks_json']
    found_large = [f for f in large_fields if f in df.columns]
    if found_large:
        print(f"  - 警告: 发现大字段（应该被裁剪）: {found_large}")
    else:
        print("  - 列裁剪: 正常（大字段已移除）")
else:
    print("\n[3] Preview OFI 数据: 未找到")

# 4. 检查 DQ 报告目录
dq_reports_dir = Path("deploy/artifacts/ofi_cvd/dq_reports")
dq_files = list(dq_reports_dir.rglob("dq-*.json"))
print("\n[4] DQ 报告检查:")
print(f"  - DQ报告数量: {len(dq_files)}")
if dq_files:
    for dq_file in dq_files[:3]:  # 只显示前3个
        with open(dq_file, 'r', encoding='utf-8') as f:
            dq = json.load(f)
        print(f"  - {dq_file.name}: kind={dq['kind']}, ok={dq['ok_rows']}, bad={dq['bad_rows']}")
else:
    print("  - 无坏数据（正常，说明数据质量良好）")

# 5. 检查 sidecar 文件
sidecar_files = list(Path("deploy").rglob("*.sidecar.json"))
print("\n[5] Sidecar 文件检查:")
print(f"  - Sidecar文件数量: {len(sidecar_files)}")
if sidecar_files:
    with open(sidecar_files[0], 'r', encoding='utf-8') as f:
        sidecar = json.load(f)
    print(f"  - 示例: {sidecar_files[0].name}")
    print(f"    - schema_version: {sidecar.get('schema_version')}")
    print(f"    - rows: {sidecar.get('rows')}")
else:
    print("  - 未找到 sidecar 文件（可能需要检查代码）")

# 6. 检查目录结构
print("\n[6] 目录结构检查:")
data_root = Path("deploy/data/ofi_cvd")
preview_root = Path("deploy/preview/ofi_cvd")
artifacts_root = Path("deploy/artifacts/ofi_cvd")

print(f"  - RAW数据目录: {data_root.exists()}")
print(f"  - Preview数据目录: {preview_root.exists()}")
print(f"  - Artifacts目录: {artifacts_root.exists()}")

# 统计文件数量
raw_files = list(data_root.rglob("*.parquet"))
preview_files = list(preview_root.rglob("*.parquet"))
print(f"  - RAW Parquet文件: {len(raw_files)}")
print(f"  - Preview Parquet文件: {len(preview_files)}")

print("\n" + "=" * 60)
print("检查完成")
print("=" * 60)

