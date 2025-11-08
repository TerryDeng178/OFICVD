#!/usr/bin/env python3
"""清理数据并运行测试"""
import os
import sys
import subprocess
import shutil
from pathlib import Path

def main():
    print("=" * 80)
    print("清理数据并运行测试")
    print("=" * 80)
    print()
    
    # 1. 停止所有Python进程（除了当前进程）
    print("步骤1: 停止所有Python进程...")
    try:
        import psutil
        current_pid = os.getpid()
        killed_count = 0
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] and 'python' in proc.info['name'].lower():
                    if proc.info['pid'] != current_pid:
                        # 检查是否是orchestrator/harvest/signal/broker相关进程
                        cmdline = ' '.join(proc.info['cmdline'] or [])
                        if any(keyword in cmdline for keyword in ['orchestrator', 'harvest', 'signal', 'broker', 'mcp.']):
                            print(f"  停止进程 PID {proc.info['pid']}: {cmdline[:100]}")
                            proc.terminate()
                            killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if killed_count > 0:
            import time
            time.sleep(2)  # 等待进程退出
            print(f"  已停止 {killed_count} 个进程")
        else:
            print("  未找到需要停止的进程")
    except ImportError:
        print("  [!] psutil未安装，跳过进程清理")
    except Exception as e:
        print(f"  [!] 进程清理失败: {e}")
    print()
    
    # 2. 清理数据目录
    print("步骤2: 清理数据目录...")
    runtime_dir = Path("runtime")
    if runtime_dir.exists():
        # 清理signals.db
        db_file = runtime_dir / "signals.db"
        if db_file.exists():
            try:
                db_file.unlink()
                print(f"  已删除: {db_file}")
            except Exception as e:
                print(f"  [!] 删除数据库失败: {e}")
        
        # 清理JSONL文件
        jsonl_dir = runtime_dir / "ready" / "signal"
        if jsonl_dir.exists():
            try:
                jsonl_files = list(jsonl_dir.rglob("*.jsonl"))
                for f in jsonl_files:
                    f.unlink()
                print(f"  已删除 {len(jsonl_files)} 个JSONL文件")
            except Exception as e:
                print(f"  [!] 删除JSONL文件失败: {e}")
    else:
        print("  runtime目录不存在，跳过清理")
    print()
    
    # 3. 运行测试
    print("步骤3: 运行3分钟测试...")
    print()
    result = subprocess.run(
        [sys.executable, "scripts/run_task07b_smoke_3min.py"],
        cwd=Path.cwd(),
        encoding="utf-8",
        errors="replace"
    )
    
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())

