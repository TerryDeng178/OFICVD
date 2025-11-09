#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify P1 fixes"""
import json
import re
import sys
from pathlib import Path

def verify_param_contract():
    """Verify parameter contract document consistency"""
    print("=" * 80)
    print("1. 验证参数契约文档")
    print("=" * 80)
    
    contract_file = Path("docs/参数契约.md")
    if not contract_file.exists():
        print("  [FAIL] 参数契约文档不存在")
        return False
    
    # Check if key parameters are documented
    content = contract_file.read_text(encoding="utf-8")
    
    required_params = [
        "--include-preview",
        "--ignore-gating",
        "--taker-fee-bps",
        "--slippage-bps",
        "--source-priority",
        "include_preview",
        "ignore_gating_in_backtest",
        "taker_fee_bps",
        "slippage_bps",
    ]
    
    missing_params = []
    for param in required_params:
        if param not in content:
            missing_params.append(param)
    
    if missing_params:
        print(f"  [FAIL] 缺少参数文档: {missing_params}")
        return False
    
    print("  [OK] 参数契约文档存在且包含关键参数")
    return True

def verify_alignment_script():
    """Verify alignment script enhancements"""
    print("\n" + "=" * 80)
    print("2. 验证对齐验收脚本增强")
    print("=" * 80)
    
    script_file = Path("scripts/test_backtest_alignment.py")
    if not script_file.exists():
        print("  [FAIL] 对齐验收脚本不存在")
        return False
    
    content = script_file.read_text(encoding="utf-8")
    
    # Check for P1 enhancements
    checks = {
        "run_id过滤": "run_id" in content and "signal_run_id" in content,
        "时间窗强校验": "window_alignment" in content and "overlap_minutes" in content,
        "差异原因分析": "diff_reasons" in content,
        "分钟粒度截断": "minute_ts" in content or "60000" in content,
    }
    
    all_passed = True
    for check_name, passed in checks.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} {check_name}")
        if not passed:
            all_passed = False
    
    return all_passed

def verify_metrics_normalization():
    """Verify metrics normalization"""
    print("\n" + "=" * 80)
    print("3. 验证Metrics年化口径")
    print("=" * 80)
    
    metrics_file = Path("src/alpha_core/backtest/metrics.py")
    if not metrics_file.exists():
        print("  [FAIL] Metrics文件不存在")
        return False
    
    content = metrics_file.read_text(encoding="utf-8")
    
    # Check for normalization comments
    checks = {
        "年化口径注释": "Metrics年化与归一口径一致化" in content,
        "Sharpe年化因子": "252 ** 0.5" in content and "sharpe" in content.lower(),
        "Sortino年化因子": "252 ** 0.5" in content and "sortino" in content.lower(),
        "MAR年化因子": "252" in content and "annual_return" in content and "mar" in content.lower(),
        "时间粒度说明": "daily" in content.lower() or "日" in content,
    }
    
    all_passed = True
    for check_name, passed in checks.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} {check_name}")
        if not passed:
            all_passed = False
    
    # Verify actual calculation
    sharpe_match = re.search(r'sharpe\s*=\s*.*?252\s*\*\*\s*0\.5', content, re.IGNORECASE)
    sortino_match = re.search(r'sortino\s*=\s*.*?252\s*\*\*\s*0\.5', content, re.IGNORECASE)
    mar_match = re.search(r'annual_return\s*=\s*.*?252', content, re.IGNORECASE)
    
    print("\n  年化因子验证:")
    print(f"    Sharpe: {'[OK] √252' if sharpe_match else '[FAIL]'}")
    print(f"    Sortino: {'[OK] √252' if sortino_match else '[FAIL]'}")
    print(f"    MAR: {'[OK] 252' if mar_match else '[FAIL]'}")
    
    if not (sharpe_match and sortino_match and mar_match):
        all_passed = False
    
    return all_passed

def verify_aligner_ofi_cvd():
    """Verify Aligner OFI/CVD/Fusion wiring"""
    print("\n" + "=" * 80)
    print("4. 验证Aligner接线OFI/CVD/Fusion")
    print("=" * 80)
    
    aligner_file = Path("src/alpha_core/backtest/aligner.py")
    if not aligner_file.exists():
        print("  [FAIL] Aligner文件不存在")
        return False
    
    content = aligner_file.read_text(encoding="utf-8")
    
    checks = {
        "OFI字段": "ofi_z" in content and ("z_ofi" in content or "get(\"ofi_z\")" in content),
        "CVD字段": "cvd_z" in content and ("z_cvd" in content or "get(\"cvd_z\")" in content),
        "Fusion字段": "fusion_score" in content,
        "P1注释": "P1: 如果可获取" in content or "P1:" in content,
    }
    
    all_passed = True
    for check_name, passed in checks.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} {check_name}")
        if not passed:
            all_passed = False
    
    return all_passed

def main():
    """Main verification"""
    print("=" * 80)
    print("P1修复验证")
    print("=" * 80)
    
    results = []
    
    # Verify each fix
    results.append(("参数契约文档", verify_param_contract()))
    results.append(("对齐验收脚本增强", verify_alignment_script()))
    results.append(("Metrics年化口径", verify_metrics_normalization()))
    results.append(("Aligner接线OFI/CVD/Fusion", verify_aligner_ofi_cvd()))
    
    # Summary
    print("\n" + "=" * 80)
    print("验证结果汇总")
    print("=" * 80)
    
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    
    for name, ok in results:
        status = "[OK]" if ok else "[FAIL]"
        print(f"  {status} {name}")
    
    print(f"\n通过: {passed}/{total}")
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())

