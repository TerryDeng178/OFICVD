#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行24小时回测（修复版）"""
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

def find_latest_date():
    """查找最新的数据日期"""
    data_dir = Path("deploy/data/ofi_cvd/preview")
    if not data_dir.exists():
        print(f"数据目录不存在: {data_dir}")
        return None
    
    dates = sorted([d.name.replace("date=", "") for d in data_dir.iterdir() if d.is_dir() and d.name.startswith("date=")], reverse=True)
    if not dates:
        print("未找到日期目录")
        return None
    
    print(f"找到日期: {dates[:5]}")
    return dates[0]

def check_data_availability(date_str):
    """检查数据可用性"""
    data_dir = Path(f"deploy/data/ofi_cvd/preview/date={date_str}")
    if not data_dir.exists():
        print(f"日期目录不存在: {data_dir}")
        return False
    
    # 检查features数据
    features_files = list(data_dir.rglob("kind=features/*.parquet"))
    print(f"找到 {len(features_files)} 个features文件")
    
    if features_files:
        # 检查第一个文件的时间范围
        import pyarrow.parquet as pq
        try:
            table = pq.read_table(features_files[0])
            if len(table) > 0:
                print(f"示例文件包含 {len(table)} 行数据")
                return True
        except Exception as e:
            print(f"读取文件错误: {e}")
    
    return False

def main():
    """主函数"""
    # 查找最新日期
    latest_date = find_latest_date()
    if not latest_date:
        return 1
    
    print(f"\n使用日期: {latest_date}")
    
    # 检查数据可用性
    if not check_data_availability(latest_date):
        print("警告: 数据可能不完整")
    
    # 生成Run ID
    run_id = f"backtest_24h_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    output_dir = Path(f"runtime/backtest/{run_id}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Run ID: {run_id}")
    print(f"输出目录: {output_dir}")
    print("\n开始24小时回测...")
    
    # 运行回测
    cmd = [
        sys.executable,
        "scripts/replay_harness.py",
        "--input", "deploy/data/ofi_cvd",
        "--date", latest_date,
        "--symbols", "BTCUSDT",
        "--kinds", "features",
        "--minutes", "1440",  # 24小时 = 1440分钟
        "--output", str(output_dir),
        "--config", "config/backtest.yaml",
    ]
    
    print(f"\n执行命令:")
    print(" ".join(cmd))
    print()
    
    try:
        # 直接输出到控制台，不使用capture_output
        result = subprocess.run(cmd)
        
        if result.returncode != 0:
            print(f"\n回测失败（退出码: {result.returncode}）")
            return result.returncode
        
        print("\n回测完成")
        
        # 查找实际输出目录（可能在output_dir下有子目录）
        actual_output = None
        for subdir in output_dir.rglob("backtest_*"):
            if (subdir / "run_manifest.json").exists():
                actual_output = subdir
                break
        
        if not actual_output:
            actual_output = output_dir
        
        # 显示结果
        print("\n" + "=" * 80)
        print("回测结果")
        print("=" * 80)
        
        # 运行结果展示脚本
        show_cmd = [sys.executable, "scripts/show_backtest_results.py", str(actual_output)]
        subprocess.run(show_cmd)
        
        return 0
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())


