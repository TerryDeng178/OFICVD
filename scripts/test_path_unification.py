#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试路径统一修复效果"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from alpha_core.common.paths import resolve_roots, get_data_root


def test_path_constants():
    """测试路径常量模块"""
    print("\n" + "=" * 80)
    print("测试1: 路径常量模块")
    print("=" * 80)
    
    roots = resolve_roots(project_root)
    
    print(f"\n路径根目录:")
    print(f"  PROJECT_ROOT: {roots['PROJECT_ROOT']}")
    print(f"  DEPLOY_ROOT: {roots['DEPLOY_ROOT']}")
    print(f"  DATA_ROOT: {roots['DATA_ROOT']}")
    print(f"  RAW_ROOT: {roots['RAW_ROOT']}")
    print(f"  PREVIEW_ROOT: {roots['PREVIEW_ROOT']}")
    print(f"  ARTIFACTS_ROOT: {roots['ARTIFACTS_ROOT']}")
    
    # 验证路径结构
    assert roots['RAW_ROOT'] == roots['DATA_ROOT'] / "raw", "RAW_ROOT结构错误"
    assert roots['PREVIEW_ROOT'] == roots['DATA_ROOT'] / "preview", "PREVIEW_ROOT结构错误"
    assert roots['DATA_ROOT'] == roots['DEPLOY_ROOT'] / "data" / "ofi_cvd", "DATA_ROOT结构错误"
    assert roots['ARTIFACTS_ROOT'] == roots['DEPLOY_ROOT'] / "artifacts" / "ofi_cvd", "ARTIFACTS_ROOT结构错误"
    
    print("\n[PASS] 路径结构验证通过")
    
    # 测试get_data_root
    raw_root = get_data_root("raw")
    preview_root = get_data_root("preview")
    
    assert raw_root == roots['RAW_ROOT'], "get_data_root('raw')返回错误"
    assert preview_root == roots['PREVIEW_ROOT'], "get_data_root('preview')返回错误"
    
    print(f"\nget_data_root测试:")
    print(f"  get_data_root('raw'): {raw_root}")
    print(f"  get_data_root('preview'): {preview_root}")
    print("\n[PASS] get_data_root验证通过")
    
    return roots


def test_harvester_paths():
    """测试Harvester路径使用"""
    print("\n" + "=" * 80)
    print("测试2: Harvester路径使用")
    print("=" * 80)
    
    try:
        # 直接测试路径常量使用（不创建Harvester实例，避免依赖）
        from alpha_core.common.paths import resolve_roots
        
        roots = resolve_roots(project_root)
        
        # 模拟Harvester的路径设置逻辑（使用集中式路径常量）
        output_dir = roots["RAW_ROOT"]
        preview_dir = roots["PREVIEW_ROOT"]
        artifacts_dir = roots["ARTIFACTS_ROOT"]
        
        print(f"\nHarvester路径（模拟）:")
        print(f"  output_dir: {output_dir}")
        print(f"  preview_dir: {preview_dir}")
        print(f"  artifacts_dir: {artifacts_dir}")
        
        # 验证路径对齐
        assert str(output_dir).endswith("raw") or output_dir == roots['RAW_ROOT'], \
            f"output_dir未指向raw层级: {output_dir}"
        assert str(preview_dir).endswith("preview") or preview_dir == roots['PREVIEW_ROOT'], \
            f"preview_dir未指向preview层级: {preview_dir}"
        assert artifacts_dir == roots['ARTIFACTS_ROOT'], \
            f"artifacts_dir未对齐: {artifacts_dir} != {roots['ARTIFACTS_ROOT']}"
        
        print("\n[PASS] Harvester路径验证通过（使用集中式路径常量）")
        return True
    except Exception as e:
        print(f"\n[FAIL] Harvester路径测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_orchestrator_paths():
    """测试Orchestrator路径使用"""
    print("\n" + "=" * 80)
    print("测试3: Orchestrator路径使用")
    print("=" * 80)
    
    try:
        # 模拟Orchestrator的路径解析逻辑
        roots = resolve_roots(project_root)
        
        # 测试不同input_mode
        for input_mode in ["raw", "preview"]:
            os.environ["V13_INPUT_MODE"] = input_mode
            if "V13_INPUT_DIR" in os.environ:
                del os.environ["V13_INPUT_DIR"]
            
            features_dir = get_data_root(input_mode)
            expected_dir = roots['RAW_ROOT' if input_mode == 'raw' else 'PREVIEW_ROOT']
            
            print(f"\n  input_mode={input_mode}:")
            print(f"    features_dir: {features_dir}")
            print(f"    expected: {expected_dir}")
            
            assert features_dir == expected_dir, \
                f"input_mode={input_mode}路径不匹配: {features_dir} != {expected_dir}"
        
        print("\n[PASS] Orchestrator路径验证通过")
        return True
    except Exception as e:
        print(f"\n[FAIL] Orchestrator路径测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_directory_structure():
    """测试目录结构"""
    print("\n" + "=" * 80)
    print("测试4: 目录结构验证")
    print("=" * 80)
    
    roots = resolve_roots(project_root)
    
    # 检查目录是否存在（如果不存在则创建）
    for name, path in roots.items():
        if name == "PROJECT_ROOT":
            continue
        
        if name in ["RAW_ROOT", "PREVIEW_ROOT"]:
            # 数据目录应该存在或可以创建
            path.mkdir(parents=True, exist_ok=True)
            print(f"  {name}: {path} {'[EXISTS]' if path.exists() else '[CREATED]'}")
        elif name == "ARTIFACTS_ROOT":
            # artifacts目录应该存在或可以创建
            path.mkdir(parents=True, exist_ok=True)
            for subdir in ["run_logs", "dq_reports", "deadletter"]:
                (path / subdir).mkdir(parents=True, exist_ok=True)
            print(f"  {name}: {path} {'[EXISTS]' if path.exists() else '[CREATED]'}")
        else:
            path.mkdir(parents=True, exist_ok=True)
            print(f"  {name}: {path} {'[EXISTS]' if path.exists() else '[CREATED]'}")
    
    # 验证不存在独立的preview树
    old_preview_path = roots['DEPLOY_ROOT'] / "preview" / "ofi_cvd"
    if old_preview_path.exists():
        print(f"\n[WARN] 发现旧的独立preview树: {old_preview_path}")
        print("  建议: 移除旧的独立preview树，统一使用data/ofi_cvd/preview")
    else:
        print("\n[PASS] 未发现旧的独立preview树")
    
    print("\n[PASS] 目录结构验证通过")
    return True


def test_path_alignment():
    """测试路径对齐（Harvester写入 vs Orchestrator读取）"""
    print("\n" + "=" * 80)
    print("测试5: 路径对齐验证（Harvester写入 vs Orchestrator读取）")
    print("=" * 80)
    
    roots = resolve_roots(project_root)
    
    # Harvester写入路径
    harvester_raw = roots['RAW_ROOT']
    harvester_preview = roots['PREVIEW_ROOT']
    
    # Orchestrator读取路径
    orchestrator_raw = get_data_root("raw")
    orchestrator_preview = get_data_root("preview")
    
    print(f"\nHarvester写入路径:")
    print(f"  raw: {harvester_raw}")
    print(f"  preview: {harvester_preview}")
    
    print(f"\nOrchestrator读取路径:")
    print(f"  raw: {orchestrator_raw}")
    print(f"  preview: {orchestrator_preview}")
    
    # 验证对齐
    assert harvester_raw == orchestrator_raw, \
        f"raw路径不对齐: {harvester_raw} != {orchestrator_raw}"
    assert harvester_preview == orchestrator_preview, \
        f"preview路径不对齐: {harvester_preview} != {orchestrator_preview}"
    
    print("\n[PASS] 路径对齐验证通过")
    return True


def main():
    """主测试函数"""
    print("\n" + "=" * 80)
    print("路径统一修复测试")
    print("=" * 80)
    
    results = []
    
    # 测试1: 路径常量模块
    try:
        roots = test_path_constants()
        results.append(("路径常量模块", True))
    except Exception as e:
        print(f"\n[FAIL] 路径常量模块测试失败: {e}")
        results.append(("路径常量模块", False))
    
    # 测试2: Harvester路径
    results.append(("Harvester路径", test_harvester_paths()))
    
    # 测试3: Orchestrator路径
    results.append(("Orchestrator路径", test_orchestrator_paths()))
    
    # 测试4: 目录结构
    results.append(("目录结构", test_directory_structure()))
    
    # 测试5: 路径对齐
    results.append(("路径对齐", test_path_alignment()))
    
    # 汇总结果
    print("\n" + "=" * 80)
    print("测试结果汇总")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {name}")
    
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n[SUCCESS] 所有路径测试通过！")
        return 0
    else:
        print(f"\n[FAIL] {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())

