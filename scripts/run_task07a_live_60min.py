#!/usr/bin/env python3
"""TASK-07A LIVE模式60分钟Soak Test脚本"""
import os
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime

def main():
    """执行LIVE模式60分钟测试"""
    print("=" * 80)
    print("TASK-07A LIVE模式60分钟端到端实测（Soak Test）")
    print("=" * 80)
    print()
    
    # 步骤1: 设置环境变量
    print("步骤1: 设置环境变量（LIVE模式 + 时序库导出）")
    print()
    
    # LIVE模式配置
    os.environ["V13_REPLAY_MODE"] = "0"  # LIVE模式
    os.environ["V13_SINK"] = "dual"  # 双Sink模式
    os.environ["REPORT_TZ"] = "Asia/Tokyo"  # 报表时区
    
    # 时序库导出配置（如果未设置，使用默认值）
    if not os.getenv("TIMESERIES_TYPE"):
        os.environ["TIMESERIES_TYPE"] = "prometheus"  # 或 "influxdb"
    if not os.getenv("TIMESERIES_URL"):
        # 默认Pushgateway地址（如果未设置，代码会记录警告但不中断）
        os.environ["TIMESERIES_URL"] = "http://localhost:9091"
    
    # 生成RUN_ID
    run_id = f"task07a_live_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.environ["RUN_ID"] = run_id
    
    print(f"  环境变量配置:")
    print(f"    V13_REPLAY_MODE = {os.getenv('V13_REPLAY_MODE')}")
    print(f"    V13_SINK = {os.getenv('V13_SINK')}")
    print(f"    REPORT_TZ = {os.getenv('REPORT_TZ')}")
    print(f"    TIMESERIES_TYPE = {os.getenv('TIMESERIES_TYPE')}")
    print(f"    TIMESERIES_URL = {os.getenv('TIMESERIES_URL')}")
    print(f"    RUN_ID = {run_id}")
    print()
    
    # 步骤2: 时序库可达性预检（可选）
    print("步骤2: 时序库可达性预检（可选）")
    timeseries_type = os.getenv("TIMESERIES_TYPE", "prometheus")
    timeseries_url = os.getenv("TIMESERIES_URL", "")
    
    if timeseries_url:
        print(f"  检查 {timeseries_type} 连接: {timeseries_url}")
        try:
            import requests
            if timeseries_type == "prometheus":
                # Pushgateway健康检查
                response = requests.get(f"{timeseries_url}/metrics", timeout=5)
                if response.status_code == 200:
                    print(f"  [OK] Pushgateway可达")
                else:
                    print(f"  [WARN] Pushgateway返回状态码: {response.status_code}")
            elif timeseries_type == "influxdb":
                # InfluxDB健康检查
                response = requests.get(f"{timeseries_url}/health", timeout=5)
                if response.status_code == 200:
                    print(f"  [OK] InfluxDB可达")
                else:
                    print(f"  [WARN] InfluxDB返回状态码: {response.status_code}")
        except ImportError:
            print(f"  [WARN] requests库未安装，跳过预检")
        except Exception as e:
            print(f"  [WARN] 时序库预检失败: {e}（将记录警告但不中断运行）")
    else:
        print(f"  [INFO] 未设置TIMESERIES_URL，跳过预检")
    print()
    
    # 步骤3: 运行60分钟测试
    print("步骤3: 运行60分钟LIVE模式测试")
    print()
    
    test_start_time = datetime.now()
    print(f"测试开始时间: {test_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    cmd = [
        sys.executable, "-m", "orchestrator.run",
        "--config", "./config/defaults.yaml",
        "--enable", "harvest,signal,broker,report",
        "--sink", "dual",
        "--minutes", "60"
    ]
    
    print(f"执行命令: {' '.join(cmd)}")
    print()
    
    try:
        result = subprocess.run(
            cmd,
            cwd=Path(__file__).parent.parent,
            env=os.environ.copy(),
            encoding="utf-8",
            errors="replace"
        )
        
        test_end_time = datetime.now()
        test_duration = (test_end_time - test_start_time).total_seconds() / 60
        
        print()
        print(f"测试结束时间: {test_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"测试时长: {test_duration:.1f} 分钟")
        print(f"退出码: {result.returncode}")
        print()
        
        if result.returncode != 0:
            print("[!] 测试失败 (退出码: {})".format(result.returncode))
            return 1
        
    except KeyboardInterrupt:
        print()
        print("[!] 测试被用户中断")
        return 1
    except Exception as e:
        print()
        print(f"[!] 测试执行失败: {e}")
        return 1
    
    # 步骤4: 验证证据包
    print("步骤4: 验证证据包完整性")
    print()
    
    project_root = Path(__file__).parent.parent
    artifacts_dir = project_root / "deploy" / "artifacts" / "ofi_cvd"
    run_logs_dir = artifacts_dir / "run_logs"
    
    # 查找最新的run_manifest
    run_manifest_files = sorted(run_logs_dir.glob(f"run_manifest_{run_id}*.json"), reverse=True)
    if not run_manifest_files:
        # 如果没有找到精确匹配，查找最新的
        run_manifest_files = sorted(run_logs_dir.glob("run_manifest_*.json"), reverse=True)
    
    if run_manifest_files:
        run_manifest_path = run_manifest_files[0]
        print(f"  [OK] run_manifest.json: {run_manifest_path.name}")
        
        # 检查run_manifest字段
        try:
            with open(run_manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            checks = {
                "timeseries_export": "timeseries_export" in manifest,
                "alerts": "alerts" in manifest,
                "resource_usage": "resource_usage" in manifest,
                "shutdown_order": "shutdown_order" in manifest,
                "harvester_metrics": "harvester_metrics" in manifest,
            }
            
            for field, exists in checks.items():
                status = "[OK]" if exists else "[MISSING]"
                print(f"    {status} {field}: {exists}")
            
            # 检查timeseries_export统计
            if "timeseries_export" in manifest:
                ts_export = manifest["timeseries_export"]
                export_count = ts_export.get("export_count", 0)
                error_count = ts_export.get("error_count", 0)
                print(f"    timeseries_export.export_count: {export_count} (应 ≥ 60)")
                print(f"    timeseries_export.error_count: {error_count} (应 = 0)")
            
        except Exception as e:
            print(f"  [ERROR] 读取run_manifest失败: {e}")
    else:
        print(f"  [MISSING] run_manifest.json 未找到")
    
    # 查找source_manifest
    source_manifest_files = sorted(artifacts_dir.glob(f"source_manifest_{run_id}*.json"), reverse=True)
    if not source_manifest_files:
        source_manifest_files = sorted(artifacts_dir.glob("source_manifest_*.json"), reverse=True)
    
    if source_manifest_files:
        print(f"  [OK] source_manifest.json: {source_manifest_files[0].name}")
    else:
        print(f"  [MISSING] source_manifest.json 未找到")
    
    print()
    
    # 步骤5: 运行双Sink等价性测试
    print("步骤5: 运行双Sink等价性测试")
    print()
    
    parity_output = artifacts_dir / f"parity_diff_{run_id}.json"
    
    parity_cmd = [
        sys.executable, "scripts/verify_sink_parity.py",
        "--jsonl-dir", "./runtime/ready/signal",
        "--sqlite-db", "./runtime/signals.db",
        "--run-id", run_id,
        "--threshold", "0.5",
        "--output", str(parity_output)
    ]
    
    print(f"执行命令: {' '.join(parity_cmd)}")
    print()
    
    try:
        parity_result = subprocess.run(
            parity_cmd,
            cwd=project_root,
            encoding="utf-8",
            errors="replace"
        )
        
        if parity_result.returncode == 0:
            print(f"  [OK] 等价性测试通过")
            if parity_output.exists():
                print(f"  [OK] parity_diff.json: {parity_output.name}")
        else:
            print(f"  [!] 等价性测试失败 (退出码: {parity_result.returncode})")
    except Exception as e:
        print(f"  [ERROR] 等价性测试执行失败: {e}")
    
    print()
    print("=" * 80)
    print("测试完成")
    print("=" * 80)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

