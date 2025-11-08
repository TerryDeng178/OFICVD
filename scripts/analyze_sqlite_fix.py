#!/usr/bin/env python3
"""分析SQLite修复效果"""
import sys
import json
import sqlite3
from pathlib import Path
import re

def main():
    print("=" * 80)
    print("SQLite修复效果分析")
    print("=" * 80)
    print()
    
    # 1. 检查日志
    print("1. 关键日志检查:")
    print()
    
    log_file = Path("logs/signal/signal_stderr.log")
    if log_file.exists():
        # 只读取最后1000行，避免内存问题
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                # 读取最后1000行
                lines = f.readlines()[-1000:]
            
            init_logs = [l for l in lines if "SqliteSink" in l and "初始化完成" in l]
            close_logs = [l for l in lines if "SqliteSink" in l and ("关闭" in l or "刷新" in l)]
            batch_logs = [l for l in lines if "SqliteSink" in l and "批量刷新" in l]
            emit_logs = [l for l in lines if "emit" in l.lower() and "signal" in l.lower()]
            
            if init_logs:
                latest_init = init_logs[-1].strip()
                print(f"  [x] 初始化日志: {latest_init}")
                if "来源: env" in latest_init:
                    print("     [x] 环境变量来源确认")
                    # 提取batch_n和flush_ms
                    batch_n_match = re.search(r'batch_n=(\d+)', latest_init)
                    flush_ms_match = re.search(r'flush_ms=(\d+)', latest_init)
                    if batch_n_match and flush_ms_match:
                        batch_n = int(batch_n_match.group(1))
                        flush_ms = int(flush_ms_match.group(1))
                        print(f"     batch_n={batch_n}, flush_ms={flush_ms}ms")
                        if batch_n == 1 and flush_ms == 50:
                            print("     [x] 参数正确（batch_n=1, flush_ms=50）")
                        else:
                            print(f"     [!] 参数异常（期望batch_n=1, flush_ms=50）")
            else:
                print("  [!] 未找到初始化日志")
            
            if close_logs:
                print(f"\n  [x] 找到 {len(close_logs)} 条关闭日志")
                for log in close_logs[-3:]:
                    print(f"     {log.strip()}")
                # 检查是否有刷新数据
                has_refresh = any("刷新" in log and "0条" not in log for log in close_logs)
                if has_refresh:
                    print("     [x] 关闭时刷新了数据")
                else:
                    print("     [!] 关闭时批量队列为空（可能数据已在运行时刷新）")
            else:
                print("  [!] 未找到关闭日志")
            
            if batch_logs:
                print(f"\n  [x] 找到 {len(batch_logs)} 条批量刷新日志")
                print(f"     说明批量刷新在运行时被触发")
            else:
                print(f"\n  [!] 未找到批量刷新日志（可能批量较小或未启用SQLITE_DEBUG）")
        except Exception as e:
            print(f"  [!] 读取日志失败: {e}")
    else:
        print("  [!] 日志文件不存在")
    print()
    
    # 2. 数据统计
    print("2. 数据统计:")
    print()
    
    jsonl_dir = Path("runtime/ready/signal")
    jsonl_files = sorted(jsonl_dir.rglob("*.jsonl"))
    jsonl_count = 0
    for jsonl_file in jsonl_files:
        try:
            with open(jsonl_file, "r", encoding="utf-8") as f:
                jsonl_count += sum(1 for line in f if line.strip())
        except Exception:
            continue
    
    db = Path("runtime/signals.db")
    sqlite_count = 0
    if db.exists():
        try:
            conn = sqlite3.connect(str(db))
            cursor = conn.cursor()
            sqlite_count = cursor.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
            conn.close()
        except Exception:
            pass
    
    print(f"  JSONL总数: {jsonl_count:,}")
    print(f"  SQLite总数: {sqlite_count:,}")
    if jsonl_count > 0:
        diff_pct = abs(jsonl_count - sqlite_count) / jsonl_count * 100
        print(f"  差异: {abs(jsonl_count - sqlite_count):,} ({diff_pct:.2f}%)")
        print(f"  完成度: {sqlite_count / jsonl_count * 100:.2f}%")
    print()
    
    # 3. 分析问题
    print("3. 问题分析:")
    print()
    
    if jsonl_count > 0 and sqlite_count / jsonl_count < 0.5:
        print("  [!] SQLite数据严重缺失")
        print("  可能原因:")
        print("    1. 批量刷新在运行时未正确触发")
        print("    2. 数据在批量队列中，但关闭时队列已空（数据丢失）")
        print("    3. 批量刷新逻辑存在问题（flush_ms=50可能不够短）")
        print()
        print("  建议:")
        print("    1. 检查批量刷新是否在运行时触发（启用SQLITE_DEBUG=1）")
        print("    2. 进一步缩短flush_ms（如10ms或5ms）")
        print("    3. 检查emit()方法是否被正确调用")
    elif jsonl_count > 0 and sqlite_count / jsonl_count >= 0.95:
        print("  [x] SQLite数据完整性良好（>= 95%）")
    else:
        print("  [!] 无法判断（数据量异常）")
    print()
    
    # 4. 验证修复
    print("4. 修复验证:")
    print()
    
    checks = {
        "环境变量生效": False,
        "初始化日志": False,
        "关闭日志": False,
        "数据完整性": False,
    }
    
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                checks["环境变量生效"] = "来源: env" in content
                checks["初始化日志"] = "SqliteSink" in content and "初始化完成" in content
                checks["关闭日志"] = "SqliteSink" in content and "关闭" in content
        except Exception:
            pass
    
    if jsonl_count > 0:
        checks["数据完整性"] = sqlite_count / jsonl_count >= 0.95
    
    for check_name, passed in checks.items():
        status = "[x]" if passed else "[!]"
        print(f"  {status} {check_name}: {'通过' if passed else '失败'}")
    print()
    
    return 0 if all(checks.values()) else 1

if __name__ == "__main__":
    sys.exit(main())

