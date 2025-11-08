#!/usr/bin/env python3
"""验证parity_diff.json格式"""
import json
import sys
from pathlib import Path

def verify_parity_format(file_path: Path) -> bool:
    """验证parity_diff.json格式"""
    if not file_path.exists():
        print(f"[FAIL] 文件不存在: {file_path}")
        return False
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[FAIL] 读取JSON失败: {e}")
        return False
    
    # 检查必需字段
    required_fields = {
        "jsonl_stats": dict,
        "sqlite_stats": dict,
        "differences": dict,
        "threshold": (int, float),
        "passed": bool,
        "window_alignment": dict,  # P1新增
        "top_minute_diffs": list,  # P1新增
        "threshold_exceeded_minutes": list  # P1新增
    }
    
    print("=" * 80)
    print("parity_diff.json格式验证")
    print("=" * 80)
    
    all_passed = True
    for field, expected_type in required_fields.items():
        if field not in data:
            print(f"[FAIL] 缺少字段: {field}")
            all_passed = False
            continue
        
        value = data[field]
        if isinstance(expected_type, tuple):
            if not isinstance(value, expected_type):
                print(f"[FAIL] {field}类型错误: 期望{expected_type}, 实际{type(value)}")
                all_passed = False
                continue
        elif not isinstance(value, expected_type):
            print(f"[FAIL] {field}类型错误: 期望{expected_type}, 实际{type(value)}")
            all_passed = False
            continue
        
        print(f"[OK] {field}: {type(value).__name__}")
    
    # 检查window_alignment子字段
    if "window_alignment" in data:
        wa = data["window_alignment"]
        wa_fields = ["status", "first_minute", "last_minute", "overlap_minutes"]
        print("\nwindow_alignment子字段:")
        for field in wa_fields:
            if field in wa:
                print(f"  [OK] {field}: {wa[field]}")
            else:
                print(f"  [FAIL] 缺少字段: {field}")
                all_passed = False
    
    # 检查top_minute_diffs格式
    if "top_minute_diffs" in data:
        tmd = data["top_minute_diffs"]
        if isinstance(tmd, list) and len(tmd) > 0:
            first_item = tmd[0]
            tmd_fields = ["minute", "jsonl_count", "sqlite_count", "diff", "diff_pct"]
            print("\ntop_minute_diffs格式:")
            for field in tmd_fields:
                if field in first_item:
                    print(f"  [OK] {field}: {type(first_item[field]).__name__}")
                else:
                    print(f"  [FAIL] 缺少字段: {field}")
                    all_passed = False
    
    # 检查threshold_exceeded_minutes格式
    if "threshold_exceeded_minutes" in data:
        tem = data["threshold_exceeded_minutes"]
        if isinstance(tem, list) and len(tem) > 0:
            first_item = tem[0]
            tem_fields = ["minute", "jsonl_count", "sqlite_count", "diff", "diff_pct"]
            print("\nthreshold_exceeded_minutes格式:")
            for field in tem_fields:
                if field in first_item:
                    print(f"  [OK] {field}: {type(first_item[field]).__name__}")
                else:
                    print(f"  [FAIL] 缺少字段: {field}")
                    all_passed = False
    
    print("=" * 80)
    if all_passed:
        print("[OK] 所有格式验证通过！")
    else:
        print("[FAIL] 部分格式验证失败")
    
    return all_passed

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python verify_parity_format.py <parity_diff.json>")
        sys.exit(1)
    
    file_path = Path(sys.argv[1])
    success = verify_parity_format(file_path)
    sys.exit(0 if success else 1)

