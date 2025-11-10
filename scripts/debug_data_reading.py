#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调试数据读取问题"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_core.backtest import DataReader

def main():
    print("=" * 80)
    print("调试数据读取")
    print("=" * 80)
    
    # 检查数据目录
    data_dir = Path("deploy/data/ofi_cvd")
    print(f"\n1. 数据目录检查:")
    print(f"   数据目录存在: {data_dir.exists()}")
    
    ready_dir = data_dir / "ready"
    preview_dir = data_dir / "preview"
    print(f"   ready目录存在: {ready_dir.exists()}")
    print(f"   preview目录存在: {preview_dir.exists()}")
    
    # 查找可用日期
    if ready_dir.exists():
        dates = sorted([d.name.replace("date=", "") for d in ready_dir.iterdir() 
                       if d.is_dir() and d.name.startswith("date=")], reverse=True)
        print(f"   ready可用日期: {dates[:5]}")
    
    if preview_dir.exists():
        dates = sorted([d.name.replace("date=", "") for d in preview_dir.iterdir() 
                       if d.name.startswith("date=")], reverse=True)
        print(f"   preview可用日期: {dates[:5]}")
    
    # 测试不同的读取方式
    print(f"\n2. 测试数据读取:")
    
    # 方式1: 不指定date，不包含preview
    print(f"\n   方式1: 不指定date，不包含preview")
    reader1 = DataReader(
        input_dir=data_dir,
        symbols=["BTCUSDT"],
        kinds=["features"],
        minutes=5,
        include_preview=False,
    )
    files1 = reader1._find_files("features")
    print(f"   找到文件数: {len(files1)}")
    if files1:
        print(f"   示例文件: {files1[0]}")
    
    # 方式2: 指定date，不包含preview
    print(f"\n   方式2: 指定date=2025-11-09，不包含preview")
    reader2 = DataReader(
        input_dir=data_dir,
        date="2025-11-09",
        symbols=["BTCUSDT"],
        kinds=["features"],
        minutes=5,
        include_preview=False,
    )
    files2 = reader2._find_files("features")
    print(f"   找到文件数: {len(files2)}")
    if files2:
        print(f"   示例文件: {files2[0]}")
    
    # 方式3: 指定date，包含preview
    print(f"\n   方式3: 指定date=2025-11-09，包含preview")
    reader3 = DataReader(
        input_dir=data_dir,
        date="2025-11-09",
        symbols=["BTCUSDT"],
        kinds=["features"],
        minutes=5,
        include_preview=True,
        source_priority=["ready", "preview"],
    )
    files3 = reader3._find_files("features")
    print(f"   找到文件数: {len(files3)}")
    if files3:
        print(f"   示例文件: {files3[0]}")
    
    # 方式4: 使用source参数
    print(f"\n   方式4: 指定date=2025-11-09，source=both")
    reader4 = DataReader(
        input_dir=data_dir,
        date="2025-11-09",
        symbols=["BTCUSDT"],
        kinds=["features"],
        minutes=5,
        include_preview=True,
        source_priority=["ready", "preview"],
    )
    files4 = reader4._find_files("features")
    print(f"   找到文件数: {len(files4)}")
    if files4:
        print(f"   示例文件: {files4[0]}")
    
    # 实际读取数据
    print(f"\n3. 实际读取数据（使用方式3）:")
    count = 0
    for row in reader3.read_features():
        count += 1
        if count == 1:
            print(f"   第一条数据字段: {list(row.keys())[:10]}")
        if count >= 10:
            break
    
    print(f"   读取到数据行数: {count}")
    
    print("\n" + "=" * 80)
    return 0

if __name__ == "__main__":
    sys.exit(main())

