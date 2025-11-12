#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试atexit在Windows上是否正常工作"""

import atexit
import sys
import time

cleanup_called = False

def cleanup():
    global cleanup_called
    cleanup_called = True
    print("[atexit] 清理函数被调用", file=sys.stderr)
    sys.stderr.flush()

# 注册atexit
atexit.register(cleanup)

print("[test] 进程启动，atexit已注册")
sys.stdout.flush()
sys.stderr.flush()

# 模拟工作
time.sleep(2)

print("[test] 进程即将退出")
sys.stdout.flush()
sys.stderr.flush()

# 正常退出
sys.exit(0)

