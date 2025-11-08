#!/usr/bin/env python3
"""检查日志中的参数提示功能"""
from pathlib import Path
import re

def check_reporter_config():
    """检查Reporter启动配置快照"""
    log_file = Path("logs/orchestrator/orchestrator.log")
    if not log_file.exists():
        print("[FAIL] orchestrator.log不存在")
        return False
    
    content = log_file.read_text(encoding="utf-8", errors="ignore")
    lines = content.split("\n")
    
    # 查找最近的启动配置快照（从最新开始查找）
    recent_config = []
    in_config = False
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if "启动配置快照" in line:
            in_config = True
            recent_config = [line]
        elif in_config:
            recent_config.append(line)
            if "====" in line and len(recent_config) > 5:
                break
    
    if not recent_config:
        print("[FAIL] 未找到启动配置快照")
        return False
    
    recent_config.reverse()
    print("[OK] Reporter启动配置快照:")
    for line in recent_config[:20]:
        if line.strip():
            print(f"  {line}")
    
    # 检查新增字段
    config_text = "\n".join(recent_config)
    checks = {
        "REPORT_TZ": "REPORT_TZ" in config_text,
        "V13_REPLAY_MODE": "V13_REPLAY_MODE" in config_text,
        "V13_INPUT_MODE": "V13_INPUT_MODE" in config_text,
    }
    
    print("\n新增字段检查:")
    for field, found in checks.items():
        status = "[OK]" if found else "[FAIL]"
        print(f"  {status} {field}: {'已包含' if found else '未找到'}")
    
    return all(checks.values())

def check_sink_params():
    """检查Sink参数打印"""
    log_file = Path("logs/signal/signal_stdout.log")
    if not log_file.exists():
        print("[FAIL] signal_stdout.log不存在")
        return False
    
    content = log_file.read_text(encoding="utf-8", errors="ignore")
    lines = content.split("\n")
    
    # 查找最近的参数打印
    jsonl_fsync = [l for l in lines if "fsync策略" in l]
    sqlite_batch = [l for l in lines if "批量参数" in l]
    
    print("\n[OK] JsonlSink fsync策略:")
    if jsonl_fsync:
        print(f"  {jsonl_fsync[-1]}")
    else:
        print("  [FAIL] 未找到")
    
    print("\n[OK] SqliteSink批量参数:")
    if sqlite_batch:
        print(f"  {sqlite_batch[-1]}")
    else:
        print("  [FAIL] 未找到")
    
    return len(jsonl_fsync) > 0 and len(sqlite_batch) > 0

def check_timeseries_health():
    """检查时序库健康检查提示"""
    log_file = Path("logs/orchestrator/orchestrator.log")
    if not log_file.exists():
        print("[FAIL] orchestrator.log不存在")
        return False
    
    content = log_file.read_text(encoding="utf-8", errors="ignore")
    lines = content.split("\n")
    
    # 查找最近的健康检查提示
    health_hints = [l for l in lines if "提示:" in l and "timeseries" in l.lower()]
    
    print("\n[OK] 时序库健康检查提示:")
    if health_hints:
        for line in health_hints[-5:]:
            print(f"  {line[:120]}")
        return True
    else:
        print("  [FAIL] 未找到提示")
        return False

if __name__ == "__main__":
    print("=" * 80)
    print("P1参数提示功能验证")
    print("=" * 80)
    
    results = []
    
    print("\n1. Reporter启动配置快照")
    results.append(("启动配置快照", check_reporter_config()))
    
    print("\n2. Sink参数打印")
    results.append(("Sink参数打印", check_sink_params()))
    
    print("\n3. 时序库健康检查提示")
    results.append(("健康检查提示", check_timeseries_health()))
    
    print("\n" + "=" * 80)
    print("验证结果汇总:")
    all_passed = True
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {name}")
        if not passed:
            all_passed = False
    
    print("=" * 80)
    if all_passed:
        print("[OK] 所有功能验证通过！")
        exit(0)
    else:
        print("[FAIL] 部分功能验证失败")
        exit(1)

