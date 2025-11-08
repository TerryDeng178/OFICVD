#!/usr/bin/env python3
"""TASK-07A LIVE模式60分钟测试监控脚本"""
import json
import sys
import time
from pathlib import Path
from datetime import datetime

def monitor_test(run_id: str = None):
    """监控测试进度"""
    project_root = Path(__file__).parent.parent
    artifacts_dir = project_root / "deploy" / "artifacts" / "ofi_cvd"
    run_logs_dir = artifacts_dir / "run_logs"
    log_dir = project_root / "logs" / "orchestrator"
    
    print("=" * 80)
    print("TASK-07A LIVE模式60分钟测试监控")
    print("=" * 80)
    print()
    
    # 查找最新的run_manifest
    if run_id:
        manifest_files = sorted(run_logs_dir.glob(f"run_manifest_{run_id}*.json"), reverse=True)
    else:
        manifest_files = sorted(run_logs_dir.glob("run_manifest_*.json"), reverse=True)
    
    if manifest_files:
        manifest_path = manifest_files[0]
        print(f"找到run_manifest: {manifest_path.name}")
        
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            # 显示基本信息
            print()
            print("运行信息:")
            print(f"  RUN_ID: {manifest.get('run_id', 'N/A')}")
            print(f"  开始时间: {manifest.get('started_at', 'N/A')}")
            print(f"  结束时间: {manifest.get('ended_at', 'N/A')}")
            
            duration_s = manifest.get('duration_s', 0)
            if duration_s:
                duration_min = duration_s / 60
                print(f"  运行时长: {duration_min:.1f} 分钟")
            
            # 显示进程状态
            print()
            print("进程状态:")
            status = manifest.get('status', {})
            processes = status.get('processes', {})
            for name, proc_status in processes.items():
                running = proc_status.get('running', False)
                health = proc_status.get('health_status', 'unknown')
                restart_count = proc_status.get('restart_count', 0)
                status_icon = "[OK]" if running and health == "healthy" else "[WARN]"
                print(f"  {status_icon} {name}: running={running}, health={health}, restarts={restart_count}")
            
            # 显示报告统计
            print()
            print("报告统计:")
            report = manifest.get('report', {})
            print(f"  总信号数: {report.get('total', 0):,}")
            print(f"  确认信号: {report.get('buy_count', 0) + report.get('sell_count', 0):,}")
            print(f"  强信号: {report.get('strong_buy_count', 0) + report.get('strong_sell_count', 0):,}")
            print(f"  强信号占比: {report.get('strong_ratio', 0) * 100:.2f}%")
            
            # 显示TASK-07A必须项
            print()
            print("TASK-07A必须项检查:")
            
            # 1. 时序库导出统计
            ts_export = manifest.get('timeseries_export', {})
            export_count = ts_export.get('export_count', 0)
            error_count = ts_export.get('error_count', 0)
            ts_status = "[OK]" if export_count >= 60 and error_count == 0 else "[WARN]"
            print(f"  {ts_status} 时序库导出: export_count={export_count} (应≥60), error_count={error_count} (应=0)")
            
            # 2. 告警记录
            alerts = manifest.get('alerts', [])
            alerts_status = "[OK]" if isinstance(alerts, list) else "[WARN]"
            print(f"  {alerts_status} 告警记录: {len(alerts)} 条")
            
            # 3. Harvester SLO指标
            harvester_metrics = manifest.get('harvester_metrics', {})
            queue_dropped = harvester_metrics.get('queue_dropped', -1)
            reconnect_count = harvester_metrics.get('reconnect_count', -1)
            timeout_detected = harvester_metrics.get('substream_timeout_detected', None)
            harvester_status = "[OK]" if queue_dropped == 0 and (reconnect_count <= 3 or reconnect_count == -1) and (timeout_detected == False or timeout_detected is None) else "[WARN]"
            print(f"  {harvester_status} Harvester SLO: queue_dropped={queue_dropped}, reconnect_count={reconnect_count}, timeout={timeout_detected}")
            
            # 4. 资源使用
            resource_usage = manifest.get('resource_usage', {})
            max_rss = resource_usage.get('max_rss_mb', 0)
            max_files = resource_usage.get('max_open_files', 0)
            resource_status = "[OK]" if max_rss < 600 and max_files < 256 else "[WARN]"
            print(f"  {resource_status} 资源使用: max_rss={max_rss:.1f}MB (应<600), max_files={max_files} (应<256)")
            
            # 5. 关闭顺序
            shutdown_order = manifest.get('shutdown_order', [])
            shutdown_status = "[OK]" if shutdown_order else "[WARN]"
            print(f"  {shutdown_status} 关闭顺序: {shutdown_order}")
            
            # 6. source_manifest
            source_manifest_files = sorted(artifacts_dir.glob(f"source_manifest_{manifest.get('run_id', '')}*.json"), reverse=True)
            if not source_manifest_files:
                source_manifest_files = sorted(artifacts_dir.glob("source_manifest_*.json"), reverse=True)
            source_status = "[OK]" if source_manifest_files else "[WARN]"
            print(f"  {source_status} source_manifest.json: {'已生成' if source_manifest_files else '未找到'}")
            
        except Exception as e:
            print(f"[ERROR] 读取manifest失败: {e}")
    else:
        print("未找到run_manifest文件（测试可能还在运行中）")
        print()
        print("检查orchestrator日志:")
        orchestrator_log = log_dir / "orchestrator.log"
        if orchestrator_log.exists():
            print(f"  日志文件: {orchestrator_log}")
            # 显示最后几行
            try:
                with open(orchestrator_log, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    print(f"  最后5行:")
                    for line in lines[-5:]:
                        print(f"    {line.strip()}")
            except Exception as e:
                print(f"  读取日志失败: {e}")
    
    print()
    print("=" * 80)

if __name__ == "__main__":
    run_id = sys.argv[1] if len(sys.argv) > 1 else None
    monitor_test(run_id)

