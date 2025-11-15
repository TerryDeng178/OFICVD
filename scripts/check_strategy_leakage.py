#!/usr/bin/env python3
"""
策略泄漏检测脚本

扫描回测组件代码，检测是否有策略决策逻辑泄漏到环境壳中。
用于CI/CD自动化检查，确保策略层边界不被破坏。
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Tuple


class StrategyLeakageChecker:
    """策略泄漏检测器"""

    def __init__(self):
        # 要扫描的文件模式
        self.scan_patterns = [
            "src/backtest/app.py",
            "scripts/backtest_*.py",
            "src/alpha_core/executors/*.py",
            "orchestrator/*.py",
        ]

        # 危险模式：这些正则表达式表示真正的策略泄漏
        # 只检测最关键的违规：重新实现策略决策逻辑
        self.danger_patterns = [
            # 重新定义策略类/函数（排除导入语句）
            r'^(?!from|import).*(class StrategyEmulator|def is_tradeable|def should_trade|def decide_side)',
            r'^(?!from|import).*SOFT_GATING\s*=.*\{',
            r'^(?!from|import).*HARD_ALWAYS_BLOCK\s*=.*\{',

            # 在环境壳中重新实现策略决策逻辑（排除统计代码）
            r'(?!.*count.*|.*passed.*|.*total.*)if.*confirm.*and.*gating',  # 重新实现confirm+gating逻辑
            r'(?!.*count.*|.*passed.*|.*total.*)gating.*and.*confirm',      # gating和confirm的组合判断
            r'if.*score\s*[<>].*\s*and.*BUY|if.*score\s*[<>].*\s*and.*SELL',  # 复杂的方向判断

            # 直接基于质量字段做交易决策
            r'if.*quality_tier.*not.*allowed|if.*quality_flags.*not.*allowed',
        ]

        # 白名单：这些文件或代码段允许包含策略逻辑
        self.whitelist = [
            "src/alpha_core/strategy/",  # 策略模块本身
            "tests/test_strategy",       # 策略测试
        ]

    def is_whitelisted(self, file_path: str) -> bool:
        """检查文件是否在白名单中"""
        for allowed in self.whitelist:
            if file_path.startswith(allowed) or allowed in file_path:
                return True
        return False

    def scan_file(self, file_path: str) -> List[Tuple[int, str, str]]:
        """扫描单个文件，返回发现的违规"""
        violations = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                for pattern in self.danger_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        violations.append((line_num, line, pattern))
                        break  # 每行只报告一次

        except Exception as e:
            violations.append((0, f"Error reading file: {e}", "file_error"))

        return violations

    def scan_all_files(self) -> List[Tuple[str, int, str, str]]:
        """扫描所有相关文件"""
        all_violations = []

        for pattern in self.scan_patterns:
            # 展开通配符
            if '*' in pattern:
                import glob
                files = glob.glob(pattern)
            else:
                files = [pattern] if os.path.exists(pattern) else []

            for file_path in files:
                if self.is_whitelisted(file_path):
                    continue

                violations = self.scan_file(file_path)
                for line_num, line, pattern in violations:
                    all_violations.append((file_path, line_num, line, pattern))

        return all_violations

    def report_violations(self, violations: List[Tuple[str, int, str, str]]) -> None:
        """报告发现的违规"""
        if not violations:
            print("PASS: 策略泄漏检查通过，未发现策略决策逻辑泄漏到环境壳中")
            return

        print("FAIL: 发现策略泄漏违规！")
        print("=" * 50)

        for file_path, line_num, line, pattern in violations:
            print(f"File {file_path}:{line_num}")
            print(f"   Pattern: {pattern}")
            print(f"   Line: {line}")
            print()

        print("=" * 50)
        print(f"Total violations found: {len(violations)}")
        print()
        print("Suggestions:")
        print("1. Move strategy logic to alpha_core.strategy module")
        print("2. Use only StrategyEmulator interface in environment shell")
        print("3. Avoid direct parsing of signal['gating'] / signal['quality_tier']")

    def check(self) -> bool:
        """执行完整检查，返回是否通过"""
        print("Starting strategy leakage detection...")
        print(f"Scan patterns: {self.scan_patterns}")
        print(f"Danger patterns: {len(self.danger_patterns)}")
        print()

        violations = self.scan_all_files()
        self.report_violations(violations)

        return len(violations) == 0


def main():
    """主函数"""
    checker = StrategyLeakageChecker()
    success = checker.check()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
