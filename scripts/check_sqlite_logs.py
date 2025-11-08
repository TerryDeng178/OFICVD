#!/usr/bin/env python3
"""检查SQLite关键日志"""
import sys
from pathlib import Path
import re

def main():
    log_file = Path("logs/signal_stderr.log")
    if not log_file.exists():
        print("[!] 日志文件不存在")
        return 1
    
    content = log_file.read_text(encoding="utf-8", errors="ignore")
    lines = content.split("\n")
    
    print("=" * 80)
    print("SQLite关键日志检查")
    print("=" * 80)
    print()
    
    # 查找关键日志
    init_logs = [l for l in lines if "SqliteSink" in l and "初始化完成" in l]
    close_logs = [l for l in lines if "SqliteSink" in l and ("关闭" in l or "刷新剩余批次" in l)]
    wal_logs = [l for l in lines if "SqliteSink" in l and "WAL" in l]
    batch_logs = [l for l in lines if "SqliteSink" in l and "批量刷新" in l]
    
    print("1. 初始化日志:")
    if init_logs:
        for log in init_logs[-3:]:
            print(f"   {log}")
        # 检查环境变量来源
        if any("来源: env" in log for log in init_logs):
            print("   [x] 环境变量来源确认: env")
        else:
            print("   [!] 未找到env来源标记")
    else:
        print("   [!] 未找到初始化日志")
    print()
    
    print("2. 关闭日志:")
    if close_logs:
        for log in close_logs[-5:]:
            print(f"   {log}")
        if any("关闭时刷新剩余批次" in log for log in close_logs):
            print("   [x] 找到'关闭时刷新剩余批次'日志")
        elif any("关闭时批量队列为空" in log for log in close_logs):
            print("   [x] 找到'关闭时批量队列为空'日志")
        else:
            print("   [!] 未找到关闭刷新日志")
    else:
        print("   [!] 未找到关闭日志")
    print()
    
    print("3. WAL检查点日志:")
    if wal_logs:
        for log in wal_logs[-3:]:
            print(f"   {log}")
        print("   [x] WAL检查点日志存在")
    else:
        print("   [!] 未找到WAL检查点日志")
    print()
    
    print("4. 批量刷新日志:")
    if batch_logs:
        print(f"   找到 {len(batch_logs)} 条批量刷新日志")
        for log in batch_logs[-3:]:
            print(f"   {log}")
    else:
        print("   [!] 未找到批量刷新日志（可能批量较小或未启用SQLITE_DEBUG）")
    print()
    
    # 总结
    print("=" * 80)
    print("检查总结:")
    print("=" * 80)
    
    checks = {
        "初始化日志": len(init_logs) > 0,
        "环境变量来源": any("来源: env" in log for log in init_logs) if init_logs else False,
        "关闭日志": len(close_logs) > 0,
        "关闭刷新日志": any("关闭时刷新剩余批次" in log or "关闭时批量队列为空" in log for log in close_logs) if close_logs else False,
        "WAL检查点": len(wal_logs) > 0,
    }
    
    for check_name, passed in checks.items():
        status = "[x]" if passed else "[!]"
        print(f"  {status} {check_name}: {'通过' if passed else '失败'}")
    
    all_passed = all(checks.values())
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())

