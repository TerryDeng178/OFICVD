# -*- coding: utf-8 -*-
"""
Pytest 配置文件
设置测试环境的路径和配置
"""

import sys
from pathlib import Path

# 添加 src 目录到 Python 路径
# 测试文件位于: tests/test_*.py
# 项目结构: tests/ -> project_root/ -> src/
_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parent
_SRC_DIR = _PROJECT_ROOT / "src"

if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

