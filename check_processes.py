#!/usr/bin/env python
import os
import time
import psutil
import signal

print('=== 检查实验进程 ===')

# 检查Python进程
found_processes = []
for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
    try:
        if 'python' in proc.info['name'].lower():
            cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
            if any(keyword in cmdline for keyword in ['param_search', 'backtest', 'f_stage1_experiment']):
                start_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(proc.info['create_time']))
                runtime_minutes = (time.time() - proc.info['create_time']) / 60
                print(f'发现实验进程:')
                print(f'  PID: {proc.info["pid"]}')
                print(f'  运行时间: {runtime_minutes:.1f}分钟')
                print(f'  启动时间: {start_time}')
                print(f'  命令: {cmdline[:150]}...')
                found_processes.append(proc.info['pid'])
    except Exception as e:
        print(f'检查进程时出错: {e}')
        continue

if not found_processes:
    print('没有发现正在运行的实验进程')
else:
    print(f'\\n发现 {len(found_processes)} 个实验进程')

    # 询问是否停止
    response = input('\\n是否停止这些进程? (y/N): ')
    if response.lower() in ['y', 'yes']:
        for pid in found_processes:
            try:
                os.kill(pid, signal.SIGTERM)
                print(f'已发送终止信号到进程 {pid}')
            except Exception as e:
                print(f'终止进程 {pid} 失败: {e}')
        print('等待进程完全停止...')
        time.sleep(2)
    else:
        print('保持进程运行')

print('\\n=== 检查实验文件状态 ===')
experiment_dirs = ['runtime/f_stage1_experiment/results_*']
for exp_pattern in experiment_dirs:
    import glob
    for exp_dir in glob.glob(exp_pattern):
        if os.path.exists(exp_dir):
            print(f'\\n检查实验目录: {exp_dir}')

            # 检查是否有trial_results.json
            results_file = os.path.join(exp_dir, 'trial_results.json')
            if os.path.exists(results_file):
                mtime = os.path.getmtime(results_file)
                age_minutes = (time.time() - mtime) / 60
                print(f'  结果文件存在，{age_minutes:.1f}分钟前更新')
            else:
                print('  结果文件不存在 - 实验可能未完成')

            # 检查trial数量
            import glob
            trial_dirs = glob.glob(os.path.join(exp_dir, 'trial_*'))
            print(f'  发现 {len(trial_dirs)} 个trial目录')

            # 检查是否有最近的活动
            recent_activity = False
            for trial_dir in trial_dirs[:5]:  # 只检查前5个
                output_dirs = glob.glob(os.path.join(trial_dir, 'output', 'bt_*'))
                for output_dir in output_dirs:
                    if os.path.exists(output_dir):
                        files = os.listdir(output_dir)
                        for file in files:
                            filepath = os.path.join(output_dir, file)
                            if os.path.isfile(filepath):
                                mtime = os.path.getmtime(filepath)
                                age_minutes = (time.time() - mtime) / 60
                                if age_minutes < 10:  # 10分钟内有活动
                                    recent_activity = True
                                    break
                        if recent_activity:
                            break
                if recent_activity:
                    break

            if recent_activity:
                print('  检测到最近活动 - 实验可能仍在运行')
            else:
                print('  没有检测到最近活动')
