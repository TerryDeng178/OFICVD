#!/usr/bin/env python3
"""验证Harvester进程是否已停止"""
import psutil

def main():
    print("=== 验证Harvester进程状态 ===\n")
    
    # 检查指定的PID
    target_pids = [2692, 18684]
    print("检查指定PID:")
    for pid in target_pids:
        exists = psutil.pid_exists(pid)
        status = "存在" if exists else "不存在"
        print(f"  PID {pid}: {status}")
    
    print("\n查找所有Harvester进程:")
    harvester_processes = []
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if not cmdline:
                continue
            cmdline_str = ' '.join(cmdline).lower()
            if 'python' in cmdline_str and 'harvest' in cmdline_str:
                # 排除检查脚本本身
                if 'kill_harvester' not in cmdline_str and 'check_harvester' not in cmdline_str and 'verify_kill' not in cmdline_str:
                    harvester_processes.append({
                        'pid': proc.info['pid'],
                        'cmdline': ' '.join(cmdline)
                    })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    if harvester_processes:
        print(f"  找到 {len(harvester_processes)} 个Harvester进程:")
        for p in harvester_processes:
            print(f"    PID: {p['pid']}")
            print(f"    命令: {p['cmdline'][:80]}...")
        print("\n  [!] 仍有Harvester进程在运行")
        return 1
    else:
        print("  [x] 未找到Harvester进程")
        print("\n  [x] 所有Harvester进程已停止")
        return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())

