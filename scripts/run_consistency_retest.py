#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行TASK09X一致性复测"""
import subprocess
import json
import sys
from pathlib import Path
from datetime import datetime

def run_consistency_retest():
    """运行一致性复测"""
    output_dir = Path(f"./runtime/task09x_consistency_retest_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    
    print("\n" + "="*80)
    print("TASK09X 一致性复测")
    print("="*80 + "\n")
    
    # 步骤1: 运行一致性基线回放
    print("步骤1: 运行一致性基线回放（15分钟）...")
    cmd = [
        "python", "scripts/replay_harness.py",
        "--input", "./deploy/data/ofi_cvd",
        "--date", "2025-11-09",
        "--symbols", "BTCUSDT",
        "--kinds", "features",
        "--config", "./config/stage1_consistency.yaml",
        "--output", str(output_dir),
        "--minutes", "15",
        "--sink", "sqlite",
    ]
    
    import os
    os.environ["V13_REPLAY_MODE"] = "1"
    os.environ["V13_OUTPUT_DIR"] = "./runtime"
    
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    
    if result.returncode != 0:
        print(f"❌ 回放失败")
        print(result.stderr)
        return None
    
    # 查找backtest目录
    backtest_dirs = list(output_dir.glob("backtest_*"))
    if not backtest_dirs:
        print(f"❌ 未找到backtest目录: {output_dir}")
        return None
    
    backtest_dir = backtest_dirs[0]
    print(f"✅ 回放完成: {backtest_dir}\n")
    
    # 步骤2: 收集Gate统计
    print("步骤2: 收集Gate统计...")
    gate_stats_file = Path("./runtime/artifacts/gate_stats_retest.jsonl")
    gate_stats_file.parent.mkdir(parents=True, exist_ok=True)
    gate_report_file = Path("./runtime/reports/gate_stats_retest.md")
    
    cmd = [
        "python", "scripts/collect_gate_stats.py",
        "--in", str(backtest_dir),
        "--out", str(gate_stats_file),
        "--report", str(gate_report_file),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode == 0:
        print(f"✅ Gate统计完成: {gate_report_file}\n")
    else:
        print(f"⚠️ Gate统计警告: {result.stderr}\n")
    
    # 步骤3: 检查Gate分布
    print("步骤3: 检查Gate分布...")
    sqlite_db = backtest_dir / "signals" / "signals.db"
    if sqlite_db.exists():
        cmd = [
            "python", "scripts/check_gate_distribution_sqlite.py",
            str(sqlite_db),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode == 0:
            print(f"✅ Gate分布检查完成\n")
            print(result.stdout)
        else:
            print(f"⚠️ Gate分布检查警告: {result.stderr}\n")
    
    # 步骤4: 检查活动度覆盖率
    print("步骤4: 检查活动度覆盖率...")
    activity_report_file = Path("./runtime/reports/activity_coverage_retest.md")
    if sqlite_db.exists():
        cmd = [
            "python", "scripts/check_activity_coverage_sqlite.py",
            "--sqlite-db", str(sqlite_db),
            "--out", str(activity_report_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode == 0:
            print(f"✅ 活动度覆盖率检查完成: {activity_report_file}\n")
        else:
            print(f"⚠️ 活动度覆盖率检查警告: {result.stderr}\n")
    
    # 步骤5: 读取对齐审计脚本（如果存在）
    print("步骤5: 检查对齐审计脚本...")
    audit_script = Path("./scripts/audit_alignment.py")
    if audit_script.exists():
        print(f"✅ 对齐审计脚本存在: {audit_script}\n")
    else:
        print(f"⚠️ 对齐审计脚本不存在: {audit_script}\n")
    
    return backtest_dir

if __name__ == "__main__":
    backtest_dir = run_consistency_retest()
    if backtest_dir:
        print("\n" + "="*80)
        print("一致性复测完成")
        print("="*80)
        print(f"\n回放目录: {backtest_dir}")
        print(f"Gate统计报告: runtime/reports/gate_stats_retest.md")
        print(f"活动度覆盖率报告: runtime/reports/activity_coverage_retest.md")
        print(f"\n下一步: 查看报告并检查DoD验收标准")
    else:
        print("\n❌ 一致性复测失败")
        sys.exit(1)

