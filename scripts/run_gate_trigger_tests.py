#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行Gate强触发测试"""
import subprocess
import json
import sys
from pathlib import Path
from datetime import datetime

def run_test(config_path: Path, test_name: str, minutes: int = 2) -> Path:
    """运行单个强触发测试"""
    output_dir = Path(f"./runtime/task09x_gate_trigger_{test_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    
    cmd = [
        "python", "scripts/replay_harness.py",
        "--input", "./deploy/data/ofi_cvd",
        "--date", "2025-11-09",
        "--symbols", "BTCUSDT",
        "--kinds", "features",
        "--config", str(config_path),
        "--output", str(output_dir),
        "--minutes", str(minutes),
        "--sink", "sqlite",
    ]
    
    print(f"\n{'='*80}")
    print(f"运行测试: {test_name}")
    print(f"配置: {config_path}")
    print(f"输出: {output_dir}")
    print(f"{'='*80}\n")
    
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    
    if result.returncode != 0:
        print(f"❌ 测试失败: {test_name}")
        print(result.stderr)
        return None
    
    # 查找backtest目录
    backtest_dirs = list(output_dir.glob("backtest_*"))
    if not backtest_dirs:
        print(f"❌ 未找到backtest目录: {output_dir}")
        return None
    
    return backtest_dirs[0]

def check_gate_reasons(backtest_dir: Path, expected_reason: str) -> dict:
    """检查gate原因统计"""
    gate_file = backtest_dir / "gate_reason_breakdown.json"
    
    if not gate_file.exists():
        return {"found": False, "error": "gate_reason_breakdown.json不存在"}
    
    data = json.loads(gate_file.read_text(encoding="utf-8"))
    
    if not data:
        return {"found": False, "error": "gate_reason_breakdown.json为空"}
    
    total = sum(data.values())
    expected_count = data.get(expected_reason, 0)
    expected_pct = (expected_count / total * 100) if total > 0 else 0
    
    # 检查Top-1
    reasons = sorted(data.items(), key=lambda x: x[1], reverse=True)
    top1_name, top1_count = reasons[0] if reasons else ("", 0)
    top1_pct = (top1_count / total * 100) if total > 0 else 0
    
    return {
        "found": expected_count > 0,
        "expected_reason": expected_reason,
        "expected_count": expected_count,
        "expected_pct": expected_pct,
        "total_reasons": len(data),
        "top1_name": top1_name,
        "top1_pct": top1_pct,
        "all_reasons": dict(data),
    }

def main():
    """运行所有强触发测试"""
    tests = [
        ("spread", "./config/stage1_consistency_spread_trigger.yaml", "spread_bps_exceeded"),
        ("lag", "./config/stage1_consistency_lag_trigger.yaml", "lag_sec_exceeded"),
        ("lag_inject", "./config/stage1_consistency_lag_inject.yaml", "lag_sec_exceeded"),  # P0修复: 注入lag测试
        ("consistency", "./config/stage1_consistency_consistency_trigger.yaml", "low_consistency"),
        ("consistency_inject", "./config/stage1_consistency_consistency_inject.yaml", "low_consistency"),  # P0修复: 注入consistency测试
    ]
    
    results = {}
    
    for test_name, config_path, expected_reason in tests:
        config_file = Path(config_path)
        if not config_file.exists():
            print(f"❌ 配置文件不存在: {config_path}")
            results[test_name] = {"error": "配置文件不存在"}
            continue
        
        backtest_dir = run_test(config_file, test_name, minutes=2)
        if not backtest_dir:
            results[test_name] = {"error": "测试运行失败"}
            continue
        
        check_result = check_gate_reasons(backtest_dir, expected_reason)
        results[test_name] = {
            "backtest_dir": str(backtest_dir),
            **check_result,
        }
        
        # 打印结果
        print(f"\n{'='*80}")
        print(f"测试结果: {test_name}")
        print(f"{'='*80}")
        if check_result.get("found"):
            print(f"✅ 找到期望的gate原因: {expected_reason}")
            print(f"   计数: {check_result['expected_count']}")
            print(f"   占比: {check_result['expected_pct']:.2f}%")
        else:
            print(f"❌ 未找到期望的gate原因: {expected_reason}")
            if "error" in check_result:
                print(f"   错误: {check_result['error']}")
        print(f"Top-1: {check_result['top1_name']} = {check_result['top1_pct']:.2f}%")
        print(f"所有原因: {check_result.get('all_reasons', {})}")
        print(f"{'='*80}\n")
    
    # 汇总报告
    print(f"\n{'='*80}")
    print("汇总报告")
    print(f"{'='*80}\n")
    
    all_passed = True
    for test_name, result in results.items():
        if result.get("found"):
            print(f"✅ {test_name}: 通过")
        else:
            print(f"❌ {test_name}: 失败")
            all_passed = False
    
    # 保存结果
    output_file = Path("./runtime/reports/gate_trigger_tests_results.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n结果已保存到: {output_file}")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())

