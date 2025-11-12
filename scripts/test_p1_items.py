#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速验证P1项"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_p1_2():
    """测试P1-2: Maker/Taker参数化"""
    print("\n[测试] P1-2: Maker/Taker概率模型参数化")
    trade_sim_file = project_root / "src" / "alpha_core" / "backtest" / "trade_sim.py"
    config_file = project_root / "config" / "backtest.yaml"
    
    trade_content = trade_sim_file.read_text(encoding="utf-8")
    config_content = config_file.read_text(encoding="utf-8")
    
    checks = [
        "fee_maker_taker_config" in trade_content,
        "scenario_probs" in trade_content,
        "fee_maker_taker:" in config_content,
    ]
    
    if all(checks):
        print("  [PASS] P1-2: Maker/Taker参数化已实施")
        return True
    else:
        print(f"  [FAIL] P1-2: 检查失败 {checks}")
        return False

def test_p1_3():
    """测试P1-3: PnL切日回归测试"""
    print("\n[测试] P1-3: PnL切日跨DST/跨月回归")
    test_file = project_root / "tests" / "test_pnl_rollover_boundaries.py"
    content = test_file.read_text(encoding="utf-8")
    
    checks = [
        "test_dst_fallback_america_new_york" in content,
        "test_dst_cross_month_ny" in content,
        "test_cross_month_small_sample" in content,
        "test_dst_with_custom_rollover_hour" in content,
    ]
    
    if all(checks):
        print("  [PASS] P1-3: 回归测试用例已添加")
        return True
    else:
        print(f"  [FAIL] P1-3: 检查失败 {checks}")
        return False

def test_p1_4():
    """测试P1-4: Reader结构类型"""
    print("\n[测试] P1-4: Reader样例路径记录结构类型")
    reader_file = project_root / "src" / "alpha_core" / "backtest" / "reader.py"
    content = reader_file.read_text(encoding="utf-8")
    
    checks = [
        "_structure_type" in content,
        '"structure_type":' in content,
        'self._structure_type = "flat"' in content or '_structure_type = "flat"' in content,
        'self._structure_type = "partition"' in content or '_structure_type = "partition"' in content,
    ]
    
    if all(checks):
        print("  [PASS] P1-4: Reader结构类型记录已添加")
        return True
    else:
        print(f"  [FAIL] P1-4: 检查失败 {checks}")
        return False

def test_p1_5():
    """测试P1-5: 对齐指标阈值外置"""
    print("\n[测试] P1-5: 对齐指标的阈值再外置")
    config_file = project_root / "config" / "backtest.yaml"
    content = config_file.read_text(encoding="utf-8")
    
    checks = [
        "# P1-5:" in content or "P1-5:" in content,
        "lag_threshold_ms:" in content,
        "默认值:" in content or "默认" in content,
        "环境变量" in content,
    ]
    
    if all(checks):
        print("  [PASS] P1-5: 对齐指标阈值外置已完善")
        return True
    else:
        print(f"  [FAIL] P1-5: 检查失败 {checks}")
        return False

def main():
    print("=" * 80)
    print("v4.0.10 P1剩余项验证")
    print("=" * 80)
    
    results = {
        "P1-2": test_p1_2(),
        "P1-3": test_p1_3(),
        "P1-4": test_p1_4(),
        "P1-5": test_p1_5(),
    }
    
    print("\n" + "=" * 80)
    print("验证结果汇总")
    print("=" * 80)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for key, value in results.items():
        status = "[PASS]" if value else "[FAIL]"
        print(f"{status} {key}")
    
    print(f"\n总计: {passed}/{total} 项通过")
    
    if passed == total:
        print("\n[SUCCESS] 所有P1剩余项验证通过！")
        return 0
    else:
        print(f"\n[WARNING] {total - passed} 项验证失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())

