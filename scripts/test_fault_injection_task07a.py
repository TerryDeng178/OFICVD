#!/usr/bin/env python3
"""TASK-07A 故障注入测试脚本

在运行中的orchestrator上执行故障注入测试：
1. 启动orchestrator（60分钟测试）
2. 等待30秒让进程稳定
3. kill signal进程
4. 观察重启行为（12秒内恢复）
5. 记录重启耗时、健康探针恢复时间、事件顺序
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from orchestrator.run import Supervisor, build_process_specs


async def test_fault_injection():
    """执行故障注入测试"""
    print("=" * 80)
    print("TASK-07A 故障注入测试")
    print("=" * 80)
    
    # 设置环境变量
    os.environ["V13_REPLAY_MODE"] = "0"
    os.environ["V13_SINK"] = "dual"
    os.environ["REPORT_TZ"] = "Asia/Tokyo"
    os.environ["TIMESERIES_ENABLED"] = "0"  # 先不启用时序库，专注故障注入
    
    # 生成RUN_ID
    run_id = f"fault_injection_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.environ["RUN_ID"] = run_id
    
    print(f"\n[1] 启动Orchestrator (RUN_ID: {run_id})...")
    
    # 构建进程规格
    config_path = project_root / "config" / "defaults.yaml"
    enabled_modules = {"harvest", "signal", "broker", "report"}
    sink_kind = "dual"
    output_dir = project_root / "runtime"
    
    specs = build_process_specs(
        project_root=project_root,
        config_path=config_path,
        sink_kind=sink_kind,
        output_dir=output_dir,
        symbols=None
    )
    
    # 创建Supervisor（需要log_dir和artifacts_dir）
    log_dir = project_root / "logs"
    artifacts_dir = project_root / "deploy" / "artifacts" / "ofi_cvd"
    
    supervisor = Supervisor(
        project_root=project_root,
        log_dir=log_dir,
        artifacts_dir=artifacts_dir
    )
    
    # 注册进程
    for spec in specs:
        if spec.name in enabled_modules:
            supervisor.register_process(spec)
    
    # 启动所有进程（start_all是同步方法）
    supervisor.start_all(enabled_modules)
    
    # 启动健康检查循环（异步任务）
    health_task = asyncio.create_task(supervisor.tick_health(interval_secs=10))
    
    # 等待进程就绪（wait_ready是async方法，只需要timeout_secs参数）
    print("[1.1] 等待进程就绪...")
    ready = await supervisor.wait_ready(timeout_secs=30)
    if not ready:
        print("[WARN] 部分进程未在30秒内就绪，继续测试...")
    else:
        print("[1.2] 所有进程已就绪")
    
    print("[2] 等待进程稳定（30秒）...")
    await asyncio.sleep(30)
    
    # 检查signal进程状态
    signal_state = supervisor.processes.get("signal")
    if not signal_state or not signal_state.process:
        print("[ERROR] signal进程未找到")
        await supervisor.graceful_shutdown()
        return
    
    signal_pid = signal_state.process.pid
    print(f"[3] 找到signal进程 (PID: {signal_pid})")
    print(f"[4] 准备kill signal进程...")
    
    # 记录kill前的时间
    kill_time = time.time()
    kill_timestamp = datetime.now().isoformat()
    
    # Kill signal进程
    try:
        signal_state.process.terminate()  # 先发送SIGTERM
        await asyncio.sleep(2)  # 等待2秒
        if signal_state.process.poll() is None:
            signal_state.process.kill()  # 如果还在运行，强制kill
        print(f"[5] signal进程已kill (PID: {signal_pid})")
    except Exception as e:
        print(f"[ERROR] kill signal进程失败: {e}")
        await supervisor.graceful_shutdown()
        return
    
    # 观察重启行为
    print("[6] 观察重启行为（最多等待30秒）...")
    restart_detected = False
    health_recovered = False
    restart_time = None
    health_recovery_time = None
    
    for i in range(30):  # 最多等待30秒
        await asyncio.sleep(1)
        
        # 检查是否有新的signal进程
        current_signal_state = supervisor.processes.get("signal")
        if current_signal_state and current_signal_state.process:
            current_pid = current_signal_state.process.pid
            if current_pid != signal_pid:
                if not restart_detected:
                    restart_time = time.time()
                    restart_detected = True
                    restart_duration = restart_time - kill_time
                    print(f"[7] 检测到signal进程重启 (新PID: {current_pid}, 耗时: {restart_duration:.2f}秒)")
            
            # 检查健康状态
            if current_signal_state.health_status == "healthy":
                if not health_recovered:
                    health_recovery_time = time.time()
                    health_recovered = True
                    health_recovery_duration = health_recovery_time - kill_time
                    print(f"[8] 健康状态恢复为healthy (耗时: {health_recovery_duration:.2f}秒)")
                    break
        
        if i % 5 == 0:
            print(f"    等待中... ({i+1}/30秒)")
    
    # 收集结果
    print("\n[9] 收集测试结果...")
    
    # 获取最终状态
    final_signal_state = supervisor.processes.get("signal")
    restart_count = final_signal_state.restart_count if final_signal_state else 0
    
    # 生成测试报告
    test_results = {
        "run_id": run_id,
        "test_type": "fault_injection",
        "kill_timestamp": kill_timestamp,
        "signal_pid_before": signal_pid,
        "signal_pid_after": final_signal_state.process.pid if final_signal_state and final_signal_state.process else None,
        "restart_detected": restart_detected,
        "restart_duration_seconds": (restart_time - kill_time) if restart_time else None,
        "health_recovered": health_recovered,
        "health_recovery_duration_seconds": (health_recovery_time - kill_time) if health_recovery_time else None,
        "restart_count": restart_count,
        "final_health_status": final_signal_state.health_status if final_signal_state else None,
        "test_passed": restart_detected and health_recovered and (restart_time - kill_time) <= 12.0 if restart_time else False
    }
    
    # 保存测试报告
    report_path = project_root / "reports" / f"v4.0.6-TASK-07A-故障注入测试报告-{run_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    import json
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(test_results, f, ensure_ascii=False, indent=2)
    
    print(f"\n[10] 测试结果:")
    print(f"  - 重启检测: {'[OK]' if restart_detected else '[FAIL]'}")
    restart_duration = test_results.get('restart_duration_seconds')
    print(f"  - 重启耗时: {restart_duration:.2f}秒" if restart_duration else "N/A")
    print(f"  - 健康恢复: {'[OK]' if health_recovered else '[FAIL]'}")
    health_recovery_duration = test_results.get('health_recovery_duration_seconds')
    print(f"  - 健康恢复耗时: {health_recovery_duration:.2f}秒" if health_recovery_duration else "N/A")
    print(f"  - 重启计数: {restart_count}")
    print(f"  - 测试通过: {'[OK]' if test_results['test_passed'] else '[FAIL]'}")
    print(f"\n测试报告已保存: {report_path}")
    
    # 继续运行一段时间，观察稳定性
    print("\n[11] 继续运行30秒，观察稳定性...")
    await asyncio.sleep(30)
    
    # 停止健康检查循环
    supervisor.running = False
    supervisor.shutdown_event.set()
    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass
    
    # 优雅关闭
    print("\n[12] 执行优雅关闭...")
    await supervisor.graceful_shutdown()
    
    # 读取run_manifest验证重启记录
    manifest_path = project_root / "deploy" / "artifacts" / "ofi_cvd" / "run_logs" / f"run_manifest_{run_id}.json"
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
            signal_status = manifest.get("status", {}).get("processes", {}).get("signal", {})
            print(f"\n[13] run_manifest中的重启记录:")
            print(f"  - restart_count: {signal_status.get('restart_count', 0)}")
            print(f"  - health_status: {signal_status.get('health_status', 'unknown')}")
    
    print("\n" + "=" * 80)
    print("故障注入测试完成")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_fault_injection())

