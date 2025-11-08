#!/usr/bin/env python3
"""TASK-07A 时序库导出验证脚本

验证时序库导出功能：
1. 配置时序库连接（Prometheus Pushgateway）
2. 运行短时间测试（5分钟）
3. 验证export_count >= 5，error_count = 0
"""
import os
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime

def main():
    """执行时序库导出验证"""
    print("=" * 80)
    print("TASK-07A 时序库导出验证")
    print("=" * 80)
    
    # 步骤1: 设置环境变量
    print("\n[1] 设置环境变量（时序库导出）")
    
    os.environ["V13_REPLAY_MODE"] = "0"  # LIVE模式
    os.environ["V13_SINK"] = "dual"  # 双Sink模式
    os.environ["REPORT_TZ"] = "Asia/Tokyo"
    os.environ["TIMESERIES_ENABLED"] = "1"  # 启用时序库导出
    os.environ["TIMESERIES_TYPE"] = "prometheus"
    os.environ["TIMESERIES_URL"] = "http://localhost:9091"
    
    # 生成RUN_ID
    run_id = f"timeseries_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.environ["RUN_ID"] = run_id
    
    print(f"  环境变量配置:")
    print(f"    TIMESERIES_TYPE = {os.getenv('TIMESERIES_TYPE')}")
    print(f"    TIMESERIES_URL = {os.getenv('TIMESERIES_URL')}")
    print(f"    RUN_ID = {run_id}")
    
    # 步骤2: 时序库可达性预检
    print("\n[2] 时序库可达性预检")
    timeseries_url = os.getenv("TIMESERIES_URL", "")
    
    if timeseries_url:
        print(f"  检查 Pushgateway 连接: {timeseries_url}")
        try:
            import requests
            # Pushgateway健康检查
            response = requests.get(f"{timeseries_url}/metrics", timeout=5)
            if response.status_code == 200:
                print(f"  [OK] Pushgateway可达")
            else:
                print(f"  [WARN] Pushgateway返回状态码: {response.status_code}")
                print(f"  [INFO] 将继续运行，但导出可能失败（代码会记录警告）")
        except ImportError:
            print(f"  [WARN] requests库未安装，跳过预检")
        except Exception as e:
            print(f"  [WARN] Pushgateway预检失败: {e}")
            print(f"  [INFO] 将继续运行，但导出可能失败（代码会记录警告）")
    else:
        print(f"  [WARN] 未设置TIMESERIES_URL，跳过预检")
    
    # 步骤3: 运行5分钟测试（短时间验证）
    print("\n[3] 运行5分钟测试（验证时序库导出）")
    print(f"测试开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    cmd = [
        sys.executable, "-m", "orchestrator.run",
        "--config", "./config/defaults.yaml",
        "--enable", "harvest,signal,broker,report",
        "--sink", "dual",
        "--minutes", "5"  # 短时间测试
    ]
    
    print(f"执行命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            cwd=Path(__file__).parent.parent,
            env=os.environ.copy(),
            encoding="utf-8",
            errors="replace",
            capture_output=False  # 实时输出
        )
        
        test_end_time = datetime.now()
        print(f"\n测试结束时间: {test_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if result.returncode != 0:
            print(f"\n[WARN] 测试退出码: {result.returncode}")
    except KeyboardInterrupt:
        print("\n[INFO] 测试被用户中断")
    except Exception as e:
        print(f"\n[ERROR] 测试执行失败: {e}")
        return 1
    
    # 步骤4: 验证时序库导出统计
    print("\n[4] 验证时序库导出统计")
    
    # 查找run_manifest
    manifest_dir = Path(__file__).parent.parent / "deploy" / "artifacts" / "ofi_cvd" / "run_logs"
    manifest_files = sorted(manifest_dir.glob(f"run_manifest_{run_id}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    if not manifest_files:
        print(f"  [ERROR] 未找到run_manifest文件（RUN_ID: {run_id}）")
        return 1
    
    manifest_path = manifest_files[0]
    print(f"  找到run_manifest: {manifest_path.name}")
    
    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
        
        timeseries_export = manifest.get("timeseries_export", {})
        export_count = timeseries_export.get("export_count", 0)
        error_count = timeseries_export.get("error_count", 0)
        
        print(f"\n  时序库导出统计:")
        print(f"    export_count: {export_count} (应 >= 5)")
        print(f"    error_count: {error_count} (应 = 0)")
        
        # 验证结果
        export_ok = export_count >= 5
        error_ok = error_count == 0
        
        print(f"\n  验证结果:")
        print(f"    export_count >= 5: {'[OK]' if export_ok else '[FAIL]'}")
        print(f"    error_count = 0: {'[OK]' if error_ok else '[FAIL]'}")
        
        test_passed = export_ok and error_ok
        
        # 生成验证报告
        verification_report = {
            "run_id": run_id,
            "test_type": "timeseries_export",
            "test_timestamp": datetime.now().isoformat(),
            "manifest_path": str(manifest_path),
            "timeseries_export": timeseries_export,
            "verification": {
                "export_count_ok": export_ok,
                "error_count_ok": error_ok,
                "test_passed": test_passed
            }
        }
        
        report_path = Path(__file__).parent.parent / "reports" / f"v4.0.6-TASK-07A-时序库导出验证报告-{run_id}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(verification_report, f, ensure_ascii=False, indent=2)
        
        print(f"\n验证报告已保存: {report_path}")
        
        if test_passed:
            print(f"\n[OK] 时序库导出验证通过")
            return 0
        else:
            print(f"\n[FAIL] 时序库导出验证失败")
            if not export_ok:
                print(f"  - export_count ({export_count}) < 5，可能原因：")
                print(f"    1. Pushgateway未运行或不可达")
                print(f"    2. 网络连接问题")
                print(f"    3. 代码逻辑问题")
            if not error_ok:
                print(f"  - error_count ({error_count}) > 0，请检查日志")
            return 1
            
    except Exception as e:
        print(f"  [ERROR] 读取或验证run_manifest失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())


