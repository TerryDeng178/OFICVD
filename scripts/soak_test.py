#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TASK-07A: LIVE 60 分钟端到端实测（Soak Test）
执行脚本
"""

import os
import sys
import subprocess
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

def check_timeseries_preflight(timeseries_type: str, timeseries_url: str) -> bool:
    """时序库可达性预检"""
    print("执行时序库可达性预检...")
    try:
        import requests
        if timeseries_type == "prometheus":
            response = requests.get(timeseries_url, timeout=5)
            if response.status_code == 200:
                print(f"  [OK] Prometheus Pushgateway 可达 ({timeseries_url})")
                return True
        elif timeseries_type == "influxdb":
            health_url = f"{timeseries_url.rstrip('/')}/health"
            response = requests.get(health_url, timeout=5)
            if response.status_code == 200:
                print(f"  [OK] InfluxDB 可达 ({timeseries_url})")
                return True
    except ImportError:
        print("  [WARNING] requests 库未安装，跳过预检")
        return True  # 继续运行
    except Exception as e:
        print(f"  [WARNING] 时序库预检失败: {e}")
        print("  将继续运行，但时序库导出可能失败")
        return True  # 继续运行，不阻塞
    return False

def main():
    import argparse
    parser = argparse.ArgumentParser(description="TASK-07A: LIVE 60 分钟端到端实测（Soak Test）")
    parser.add_argument("--config", default="./config/defaults.yaml", help="配置文件路径")
    parser.add_argument("--minutes", type=int, default=60, help="运行时长（分钟）")
    parser.add_argument("--sink", default="jsonl", choices=["jsonl", "sqlite", "dual"], help="Sink 类型")
    parser.add_argument("--timeseries-type", default="prometheus", choices=["prometheus", "influxdb"], help="时序库类型")
    parser.add_argument("--timeseries-url", default="http://localhost:9091", help="时序库地址")
    parser.add_argument("--skip-preflight", action="store_true", help="跳过时序库预检")
    args = parser.parse_args()

    print("=== TASK-07A: LIVE 60 分钟端到端实测（Soak Test） ===")
    print()
    print("配置参数:")
    print(f"  配置文件: {args.config}")
    print(f"  Sink: {args.sink}")
    print(f"  运行时长: {args.minutes} 分钟")
    print(f"  时序库类型: {args.timeseries_type}")
    print(f"  时序库地址: {args.timeseries_url}")
    print(f"  时区: Asia/Tokyo")
    print(f"  模式: LIVE (V13_REPLAY_MODE=0)")
    print()

    # 时序库预检
    if not args.skip_preflight:
        check_timeseries_preflight(args.timeseries_type, args.timeseries_url)
        print()

    # 设置环境变量
    env = os.environ.copy()
    env["TIMESERIES_TYPE"] = args.timeseries_type
    env["TIMESERIES_URL"] = args.timeseries_url
    env["REPORT_TZ"] = "Asia/Tokyo"
    env["V13_REPLAY_MODE"] = "0"

    # 检查配置文件
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[ERROR] 配置文件不存在: {args.config}")
        sys.exit(1)

    print("启动 Orchestrator...")
    print(f"  注意: 这将运行 {args.minutes} 分钟，请确保有足够时间")
    print("  按 Ctrl+C 可提前终止（将执行优雅关闭）")
    print()

    # 记录启动时间
    start_time = datetime.now()
    print(f"启动时间: {start_time}")
    print()

    # 运行 Orchestrator
    try:
        cmd = [
            sys.executable, "-m", "orchestrator.run",
            "--config", str(config_path),
            "--enable", "harvest,signal,broker,report",
            "--sink", args.sink,
            "--minutes", str(args.minutes)
        ]
        
        result = subprocess.run(cmd, env=env, check=False)
        exit_code = result.returncode
    except KeyboardInterrupt:
        print("\n[INFO] 用户中断，执行优雅关闭...")
        exit_code = 0
    except Exception as e:
        print(f"\n[ERROR] Orchestrator 运行失败: {e}")
        sys.exit(1)

    end_time = datetime.now()
    duration = end_time - start_time

    print()
    print("=== Soak Test 完成 ===")
    print(f"  结束时间: {end_time}")
    print(f"  运行时长: {duration.total_seconds() / 60:.2f} 分钟")
    print(f"  退出码: {exit_code}")
    print()
    print("请检查以下产出物:")
    print("  - artifacts/run_logs/run_manifest_*.json")
    print("  - artifacts/source_manifest.json")
    if args.sink == "dual":
        print("  - artifacts/parity_diff.json")
    print("  - logs/report/summary_*.json|md")
    print("  - logs/orchestrator/orchestrator.log")

    if exit_code != 0:
        print()
        print("[WARNING] Orchestrator 非正常退出，请检查日志")
        sys.exit(exit_code)

if __name__ == "__main__":
    main()

