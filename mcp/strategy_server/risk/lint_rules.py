# -*- coding: utf-8 -*-
"""Risk Module Lint Rules

契约冻结与枚举约束：将risk_contract/v1设为SSoT，reason_codes落成枚举（防高基数）
"""

import ast
import logging
from typing import List, Set

logger = logging.getLogger(__name__)


class RiskContractLinter(ast.NodeVisitor):
    """Risk契约Lint检查器"""
    
    def __init__(self):
        """初始化Lint检查器"""
        self.errors: List[str] = []
        self.valid_reason_codes = {
            # Schema校验
            "schema_validation_failed",
            "invalid_symbol",
            "invalid_side",
            "invalid_order_type",
            "invalid_qty",
            "invalid_price",
            "invalid_account_mode",
            "invalid_max_slippage_bps",
            "invalid_ts_ms",
            "invalid_regime",
            "invalid_guards",
            "invalid_context",
            # Guards
            "spread_too_wide",
            "lag_exceeds_cap",
            "market_inactive",
            # Position
            "notional_exceeds_limit",
            "symbol_qty_exceeds_limit",
            "notional_below_min",
            "qty_not_aligned_to_step_size",
            "price_not_aligned_to_tick_size",
            # Other
            "unknown_error",
        }
    
    def visit_Str(self, node):
        """检查字符串字面量（reason_codes）"""
        # 检查是否是reason_code相关的字符串
        if hasattr(node, "s") and isinstance(node.s, str):
            # 检查父节点是否是reason_codes相关的赋值或列表
            parent = getattr(node, "parent", None)
            if parent:
                # 如果是在reason_codes列表或赋值中
                if isinstance(parent, ast.List) or isinstance(parent, ast.Assign):
                    if node.s not in self.valid_reason_codes:
                        self.errors.append(
                            f"Line {node.lineno}: Invalid reason_code '{node.s}'. "
                            f"Must be one of: {sorted(self.valid_reason_codes)}"
                        )
        self.generic_visit(node)
    
    def check_file(self, file_path: str) -> List[str]:
        """检查文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            错误列表
        """
        self.errors = []
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=file_path)
            
            self.visit(tree)
        except Exception as e:
            self.errors.append(f"Failed to parse {file_path}: {e}")
        
        return self.errors


def lint_risk_module():
    """Lint整个risk模块"""
    import os
    from pathlib import Path
    
    risk_module_path = Path(__file__).parent
    linter = RiskContractLinter()
    
    all_errors = []
    
    # 检查所有Python文件
    for py_file in risk_module_path.rglob("*.py"):
        if py_file.name == "__init__.py" or py_file.name == "lint_rules.py":
            continue
        
        errors = linter.check_file(str(py_file))
        if errors:
            all_errors.extend([f"{py_file}: {e}" for e in errors])
    
    return all_errors


if __name__ == "__main__":
    """命令行入口"""
    import sys
    
    errors = lint_risk_module()
    
    if errors:
        print("Lint errors found:")
        for error in errors:
            print(f"  {error}")
        sys.exit(1)
    else:
        print("No lint errors found.")
        sys.exit(0)

