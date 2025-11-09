#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行24小时回测"""
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

def find_latest_date():
    """查找最新的数据日期"""
    data_dir = Path("deploy/data/ofi_cvd/preview")
    if not data_dir.exists():
        return None
    
    dates = sorted([d.name.replace("date=", "") for d in data_dir.iterdir() if d.is_dir() and d.name.startswith("date=")], reverse=True)
    return dates[0] if dates else None

def main():
    """主函数"""
    # 查找最新日期
    latest_date = find_latest_date()
    if not latest_date:
        print("错误: 未找到数据")
        return 1
    
    print(f"使用日期: {latest_date}")
    
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
    
    print(f"执行命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        
        # 保存日志
        log_file = output_dir / "backtest.log"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(result.stdout)
            if result.stderr:
                f.write("\n--- STDERR ---\n")
                f.write(result.stderr)
        
        print(f"\n回测完成（退出码: {result.returncode}）")
        print(f"日志已保存到: {log_file}")
        
        if result.returncode != 0:
            print("\n错误输出:")
            print(result.stderr)
            return result.returncode
        
        # 显示结果
        print("\n" + "=" * 80)
        print("回测结果")
        print("=" * 80)
        
        # 运行结果展示脚本
        show_cmd = [sys.executable, "scripts/show_backtest_results.py", str(output_dir)]
        subprocess.run(show_cmd)
        
        return 0
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())


