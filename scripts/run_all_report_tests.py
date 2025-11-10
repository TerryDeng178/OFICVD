#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行所有TASK-09报表相关测试"""
import subprocess
import sys
from pathlib import Path

def main():
    """运行所有测试"""
    test_files = [
        "tests/test_report_summary_fixes.py",
        "tests/test_report_optimizer_fixes.py",
        "tests/test_report_integration.py",
        "tests/test_report_regression.py",
    ]
    
    results = {}
    
    for test_file in test_files:
        print("=" * 80)
        print(f"运行测试: {test_file}")
        print("=" * 80)
        
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-v"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        
        results[test_file] = {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        
        if result.returncode == 0:
            print(f"[PASS] {test_file}")
        else:
            print(f"[FAIL] {test_file}")
        print()
    
    # 汇总
    print("=" * 80)
    print("测试汇总")
    print("=" * 80)
    
    total = len(test_files)
    passed = sum(1 for r in results.values() if r["returncode"] == 0)
    failed = total - passed
    
    print(f"总测试文件数: {total}")
    print(f"通过: {passed}")
    print(f"失败: {failed}")
    
    if failed > 0:
        print("\n失败的测试:")
        for test_file, result in results.items():
            if result["returncode"] != 0:
                print(f"  - {test_file}")
    
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())

