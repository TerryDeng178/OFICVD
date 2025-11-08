#!/usr/bin/env python3
"""TASK-07B 3分钟双Sink冒烟测试脚本"""
import os
import sys
import subprocess
import json
import time
from pathlib import Path
from datetime import datetime

def main():
    print("=" * 80)
    print("TASK-07B 3分钟双Sink冒烟测试")
    print("=" * 80)
    print()
    
    minutes = 3
    
    # 步骤1: 设置环境变量（短跑调参）
    print("步骤1: 设置环境变量（短跑调参）")
    print()
    os.environ["V13_REPLAY_MODE"] = "1"
    os.environ["V13_INPUT_MODE"] = "preview"
    os.environ["TIMESERIES_ENABLED"] = "0"
    # P0: 强一致测试开关
    os.environ["V13_SINK"] = "dual"
    os.environ["SQLITE_BATCH_N"] = "1"
    os.environ["SQLITE_FLUSH_MS"] = "10"  # P0: 短跑参数一刀切到"秒落盘"（从50ms再降一档）
    os.environ["FSYNC_EVERY_N"] = "1"  # JSONL每次都fsync
    os.environ["RUN_ID"] = f"task07b_smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}"  # 生成唯一run_id
    os.environ["SQLITE_DEBUG"] = "1"  # 启用调试日志
    
    print("  环境变量配置:")
    print(f"    V13_REPLAY_MODE = {os.environ['V13_REPLAY_MODE']}")
    print(f"    V13_INPUT_MODE = {os.environ['V13_INPUT_MODE']}")
    print(f"    V13_SINK = {os.environ.get('V13_SINK', 'dual')}")
    print(f"    SQLITE_BATCH_N = {os.environ['SQLITE_BATCH_N']}")
    print(f"    SQLITE_FLUSH_MS = {os.environ['SQLITE_FLUSH_MS']} (立即刷新)")
    print(f"    FSYNC_EVERY_N = {os.environ['FSYNC_EVERY_N']} (每次都fsync)")
    print(f"    RUN_ID = {os.environ['RUN_ID']} (用于按run_id对账)")
    print(f"    SQLITE_DEBUG = {os.environ.get('SQLITE_DEBUG', '0')} (调试日志)")
    print()
    
    # 步骤2: 运行双Sink测试
    print(f"步骤2: 运行{minutes}分钟双Sink测试")
    print()
    start_time = datetime.now()
    print(f"测试开始时间: {start_time}")
    print()
    
    log_file = Path(f"logs/task07b_smoke_3min_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        sys.executable, "-m", "orchestrator.run",
        "--config", "./config/defaults.yaml",
        "--enable", "harvest,signal,broker,report",
        "--sink", "dual",
        "--minutes", str(minutes)
    ]
    
    print(f"执行命令: {' '.join(cmd)}")
    print()
    
    with open(log_file, "w", encoding="utf-8") as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() / 60
    print()
    print(f"测试结束时间: {end_time}")
    print(f"测试时长: {duration:.1f} 分钟")
    print(f"退出码: {result.returncode}")
    print()
    
    if result.returncode != 0:
        print(f"[!] Orchestrator运行失败 (退出码: {result.returncode})")
        print(f"    请查看日志: {log_file}")
        return 1
    
    # 步骤3: 检查补偿文件
    print("步骤3: 检查补偿文件")
    print()
    
    failed_batches_file = Path("runtime/failed_batches.jsonl")
    if failed_batches_file.exists():
        failed_count = sum(1 for _ in failed_batches_file.open("r", encoding="utf-8"))
        if failed_count > 0:
            print(f"[!] 发现补偿文件: {failed_batches_file} ({failed_count}条)")
            print("    这表示SQLite批量写入失败，数据已保存到补偿文件")
            return 1
        else:
            print("[x] 补偿文件为空（正常）")
    else:
        print("[x] 无补偿文件（正常）")
    
    # 步骤4: 运行等价性测试
    print()
    print("步骤4: 运行双Sink等价性测试")
    print()
    
    parity_output = Path(f"deploy/artifacts/ofi_cvd/parity_diff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    parity_output.parent.mkdir(parents=True, exist_ok=True)
    
    # 查找最新的run_manifest.json以获取时间范围
    manifest_dir = Path("deploy/artifacts/ofi_cvd/run_logs")
    manifest_files = sorted(manifest_dir.glob("run_manifest_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    # P0: 传递run_id给等价性测试脚本
    run_id = os.environ.get("RUN_ID", "")
    parity_cmd = [
        sys.executable, "scripts/test_dual_sink_parity.py",
        "--jsonl-dir", "./runtime/ready/signal",
        "--sqlite-db", "./runtime/signals.db",
        "--output", str(parity_output)
    ]
    if run_id:
        parity_cmd.extend(["--run-id", run_id])
    
    # 如果找到manifest，使用它来指定时间范围
    if manifest_files:
        parity_cmd.extend(["--manifest", str(manifest_files[0])])
    
    print(f"执行命令: {' '.join(parity_cmd)}")
    print()
    
    parity_result = subprocess.run(parity_cmd, capture_output=True, text=True, encoding="utf-8")
    
    if parity_result.returncode == 0:
        print("[x] 等价性测试完成")
        print(f"    结果文件: {parity_output}")
    else:
        print(f"[!] 等价性测试失败 (退出码: {parity_result.returncode})")
        if parity_result.stderr:
            print(f"    错误: {parity_result.stderr}")
        return 1
    
    # 步骤5: 检查结果
    print()
    print("步骤5: 检查测试结果")
    print()
    
    if parity_output.exists():
        print("[x] 等价性测试结果文件存在")
        with open(parity_output, "r", encoding="utf-8") as f:
            parity_data = json.load(f)
        
        print()
        print("差异统计:")
        total_diff = parity_data.get("differences", {}).get("total_diff_pct", 0)
        confirm_diff = parity_data.get("differences", {}).get("confirm_diff_pct", 0)
        strong_diff = parity_data.get("differences", {}).get("strong_ratio_diff_pct", 0)
        
        print(f"  总量差异: {total_diff}%", end="")
        print(" [PASS]" if total_diff < 0.2 else " [FAIL]")
        
        print(f"  确认量差异: {confirm_diff}%", end="")
        print(" [PASS]" if confirm_diff < 0.2 else " [FAIL]")
        
        print(f"  强信号占比差异: {strong_diff}%", end="")
        print(" [PASS]" if strong_diff < 0.2 else " [FAIL]")
        
        print()
        print("窗口对齐:")
        alignment = parity_data.get("window_alignment", {})
        status = alignment.get("status", "unknown")
        overlap = alignment.get("overlap_minutes", 0)
        print(f"  状态: {status}", end="")
        print(" [PASS]" if status == "aligned" else " [FAIL]")
        print(f"  交集分钟数: {overlap}")
        
        print()
        print("数据统计:")
        jsonl_stats = parity_data.get("jsonl_stats", {})
        sqlite_stats = parity_data.get("sqlite_stats", {})
        print(f"  JSONL - 总量: {jsonl_stats.get('total', 0)}, 确认: {jsonl_stats.get('confirmed', 0)}, 强信号: {jsonl_stats.get('strong', 0)}")
        print(f"  SQLite - 总量: {sqlite_stats.get('total', 0)}, 确认: {sqlite_stats.get('confirmed', 0)}, 强信号: {sqlite_stats.get('strong', 0)}")
        
        # 检查是否通过
        all_pass = (
            total_diff < 0.2 and
            confirm_diff < 0.2 and
            strong_diff < 0.2 and
            status == "aligned" and
            overlap > 0
        )
        
        print()
        if all_pass:
            print("[x] 所有检查项通过！")
            return 0
        else:
            print("[!] 部分检查项未通过")
            return 1
    else:
        print("[!] 等价性测试结果文件不存在")
        return 1

if __name__ == "__main__":
    sys.exit(main())

