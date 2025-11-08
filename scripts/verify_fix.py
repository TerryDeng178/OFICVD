#!/usr/bin/env python3
"""验证SQLite修复效果"""
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime

def main():
    print("=" * 80)
    print("SQLite修复验证")
    print("=" * 80)
    print()
    
    # 1. 检查数据量
    print("1. 数据量对比:")
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
        if diff_pct < 0.2:
            print("  状态: [x] PASS (差异 < 0.2%)")
        elif diff_pct < 1.0:
            print("  状态: [!] 部分通过 (差异 < 1.0%)")
        else:
            print("  状态: [x] FAIL (差异 >= 1.0%)")
    print()
    
    # 2. 检查日志
    print("2. 关键日志检查:")
    print()
    
    log_file = Path("logs/signal_stderr.log")
    if log_file.exists():
        try:
            content = log_file.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")
            
            init_logs = [l for l in lines if "SqliteSink" in l and "初始化完成" in l]
            close_logs = [l for l in lines if "SqliteSink" in l and ("关闭" in l or "刷新剩余批次" in l)]
            wal_logs = [l for l in lines if "SqliteSink" in l and "WAL" in l]
            
            if init_logs:
                print(f"  [x] 找到 {len(init_logs)} 条初始化日志")
                latest_init = init_logs[-1]
                print(f"     最新: {latest_init[:100]}...")
                if "来源: env" in latest_init:
                    print("     [x] 环境变量来源确认")
                else:
                    print("     [!] 未找到env来源标记")
            else:
                print("  [!] 未找到初始化日志")
            
            if close_logs:
                print(f"  [x] 找到 {len(close_logs)} 条关闭日志")
                for log in close_logs[-3:]:
                    print(f"     {log[:100]}...")
                if any("关闭时刷新剩余批次" in log for log in close_logs):
                    print("     [x] 找到'关闭时刷新剩余批次'日志")
                elif any("关闭时批量队列为空" in log for log in close_logs):
                    print("     [x] 找到'关闭时批量队列为空'日志")
                else:
                    print("     [!] 未找到关闭刷新相关日志")
            else:
                print("  [!] 未找到关闭日志")
            
            if wal_logs:
                print(f"  [x] 找到 {len(wal_logs)} 条WAL检查点日志")
            else:
                print("  [!] 未找到WAL检查点日志")
        except Exception as e:
            print(f"  [!] 读取日志失败: {e}")
    else:
        print("  [!] 日志文件不存在")
    print()
    
    # 3. 检查等价性测试结果
    print("3. 等价性测试结果:")
    print()
    
    parity_file = Path("deploy/artifacts/ofi_cvd/parity_diff_verify.json")
    if parity_file.exists():
        try:
            with open(parity_file, "r", encoding="utf-8") as f:
                parity_data = json.load(f)
            
            overall = parity_data.get("overall", {})
            total_diff = overall.get("total_diff_pct", 0)
            confirm_diff = overall.get("confirm_diff_pct", 0)
            strong_diff = overall.get("strong_ratio_diff_pct", 0)
            
            print(f"  总量差异: {total_diff:.2f}%", end="")
            print(" [PASS]" if total_diff < 0.2 else " [FAIL]")
            
            print(f"  确认量差异: {confirm_diff:.2f}%", end="")
            print(" [PASS]" if confirm_diff < 0.2 else " [FAIL]")
            
            print(f"  强信号占比差异: {strong_diff:.2f}%", end="")
            print(" [PASS]" if strong_diff < 0.2 else " [FAIL]")
            
            alignment = parity_data.get("window_alignment", {})
            status = alignment.get("status", "unknown")
            overlap = alignment.get("overlap_minutes", 0)
            print(f"  窗口对齐: {status}, 交集分钟数: {overlap}")
        except Exception as e:
            print(f"  [!] 读取等价性测试结果失败: {e}")
    else:
        print("  [!] 等价性测试结果文件不存在")
    print()
    
    # 4. 总结
    print("=" * 80)
    print("验证总结:")
    print("=" * 80)
    
    if jsonl_count > 0:
        diff_pct = abs(jsonl_count - sqlite_count) / jsonl_count * 100
        if diff_pct < 0.2:
            print("  [x] 数据完整性: PASS (差异 < 0.2%)")
            return 0
        else:
            print(f"  [!] 数据完整性: FAIL (差异 {diff_pct:.2f}%)")
            print("  建议: 检查日志确认关闭流程是否正确执行")
            return 1
    else:
        print("  [!] 无法验证（无JSONL数据）")
        return 1

if __name__ == "__main__":
    sys.exit(main())

