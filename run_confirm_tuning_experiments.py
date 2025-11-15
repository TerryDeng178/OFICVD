#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TASK_CONFIRM_PIPELINE_TUNING: Phase C - 参数搜索实验执行脚本

执行 confirm_tuning_profiles 中定义的所有参数组合实验
"""

import os
import sys
import json
import yaml
import shutil
from pathlib import Path
from datetime import datetime, timezone
import subprocess

def load_config(config_path):
    """加载YAML配置"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def create_profile_config(base_config, profile):
    """基于基础配置和profile创建具体的实验配置"""
    config = base_config.copy()

    # 移除不必要的 confirm_tuning_profiles 字段，避免配置文件混乱
    config.pop('confirm_tuning_profiles', None)

    # 更新信号配置中的参数
    if 'signal' not in config:
        config['signal'] = {}

    # 应用profile中的参数覆盖
    for key, value in profile.items():
        if key in ['weak_signal_threshold', 'consistency_min', 'strong_threshold']:
            config['signal'][key] = value
            # 同时设置顶层参数，确保 CoreAlgorithm 能读取到
            config[key] = value

    return config

def save_profile_config(config, profile_name, output_dir):
    """保存profile配置到文件"""
    config_path = output_dir / f"config_{profile_name}.yaml"
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return config_path

def run_backtest(config_path, profile_name, base_output_dir):
    """运行单个profile的backtest"""
    print(f"[PROGRESS] 开始运行 profile: {profile_name}")

    # 创建输出目录
    output_dir = base_output_dir / profile_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # 构建命令
    cmd = [
        sys.executable, "-m", "backtest.app",
        "--mode", "A",
        "--features-dir", "deploy/data/ofi_cvd",
        "--symbols", "BTCUSDT",
        "--start", "2025-11-15T15:59:00Z",
        "--end", "2025-11-15T15:59:30Z",
        "--config", str(config_path),
        "--out-dir", str(output_dir),
        "--run-id", f"confirm_tuning_{profile_name}",
        "--gating-mode", "strict",
        "--consistency-qa"
    ]

    print(f"[PROGRESS] 执行命令: {' '.join(cmd)}")

    # 执行命令
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        print(f"[PROGRESS] Profile {profile_name} 执行完成")

        # 保存执行结果
        result_file = output_dir / "execution_result.txt"
        with open(result_file, 'w', encoding='utf-8') as f:
            f.write(f"Return code: {result.returncode}\n\n")
            f.write("STDOUT:\n")
            f.write(result.stdout)
            f.write("\nSTDERR:\n")
            f.write(result.stderr)

        success = result.returncode == 0
        if success:
            print(f"[OK] Profile {profile_name} 成功完成")
        else:
            print(f"[FAIL] Profile {profile_name} 执行失败 (return code: {result.returncode})")

        return success, str(output_dir)

    except subprocess.TimeoutExpired:
        print(f"[ERROR] Profile {profile_name} 执行超时")
        return False, str(output_dir)
    except Exception as e:
        print(f"[ERROR] Profile {profile_name} 执行异常: {e}")
        return False, str(output_dir)

def collect_results(base_output_dir, profiles):
    """收集所有实验结果"""
    summary = {
        "experiment_timestamp": datetime.now(timezone.utc).isoformat(),
        "total_profiles": len(profiles),
        "successful_runs": 0,
        "failed_runs": 0,
        "results": {}
    }

    for profile in profiles:
        profile_name = profile['name']
        profile_dir = base_output_dir / profile_name
        run_manifest = profile_dir / "run_manifest.json"

        result = {
            "profile_name": profile_name,
            "profile_description": profile.get('description', ''),
            "output_dir": str(profile_dir),
            "success": False,
            "run_manifest": None,
            "funnel_stats": None,
            "quality_stats": None
        }

        # 检查运行结果
        execution_result = profile_dir / "execution_result.txt"
        if execution_result.exists():
            with open(execution_result, 'r', encoding='utf-8') as f:
                content = f.read()
                result["success"] = "Return code: 0" in content

        # 读取run_manifest
        if run_manifest.exists():
            try:
                with open(run_manifest, 'r', encoding='utf-8') as f:
                    result["run_manifest"] = json.load(f)
            except Exception as e:
                print(f"[WARN] 无法读取 {profile_name} 的 run_manifest: {e}")

        # 读取funnel_stats
        funnel_file = profile_dir / "confirm_funnel_stats.json"
        if funnel_file.exists():
            try:
                with open(funnel_file, 'r', encoding='utf-8') as f:
                    result["funnel_stats"] = json.load(f)
            except Exception as e:
                print(f"[WARN] 无法读取 {profile_name} 的 funnel_stats: {e}")

        summary["results"][profile_name] = result
        if result["success"]:
            summary["successful_runs"] += 1
        else:
            summary["failed_runs"] += 1

    return summary

def main():
    print("[START] TASK_CONFIRM_PIPELINE_TUNING: Phase C - 参数搜索实验")

    # 配置路径
    config_path = Path("config/confirm_tuning_profiles.yaml")
    if not config_path.exists():
        print(f"[ERROR] 配置文件不存在: {config_path}")
        return 1

    # 加载配置
    try:
        config = load_config(config_path)
        profiles = config.get('confirm_tuning_profiles', [])
        if not profiles:
            print("[ERROR] 配置中没有找到 confirm_tuning_profiles")
            return 1
    except Exception as e:
        print(f"[ERROR] 加载配置失败: {e}")
        return 1

    print(f"[INFO] 找到 {len(profiles)} 个调优配置: {[p['name'] for p in profiles]}")

    # 创建输出目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_output_dir = Path(f"runtime/confirm_tuning_experiments/{timestamp}")
    base_output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] 实验输出目录: {base_output_dir}")

    # 为每个profile创建配置并运行实验
    successful_profiles = []
    for profile in profiles:
        profile_name = profile['name']

        # 创建profile配置
        profile_config = create_profile_config(config, profile)
        config_file_path = save_profile_config(profile_config, profile_name, base_output_dir)

        # 运行backtest
        success, output_dir = run_backtest(config_file_path, profile_name, base_output_dir)

        if success:
            successful_profiles.append(profile_name)
        else:
            print(f"[WARN] Profile {profile_name} 运行失败，跳过结果收集")

    # 收集结果
    print(f"[PROGRESS] 收集实验结果...")
    summary = collect_results(base_output_dir, profiles)

    # 保存汇总报告
    summary_file = base_output_dir / "experiment_summary.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # 打印简要报告
    print(f"\n{'='*60}")
    print("实验执行总结:")
    print(f"总配置数: {summary['total_profiles']}")
    print(f"成功运行: {summary['successful_runs']}")
    print(f"失败运行: {summary['failed_runs']}")
    print(f"输出目录: {base_output_dir}")
    print(f"汇总报告: {summary_file}")

    # 打印各profile的confirm_true_rate
    print(f"\n各配置的confirm_true_rate:")
    for profile_name, result in summary['results'].items():
        if result['success'] and result['funnel_stats']:
            funnel = result['funnel_stats']
            confirm_rate = funnel.get('confirm_true_rate', 0)
            print(f"  {profile_name}: {confirm_rate:.1f}%")
        else:
            print(f"  {profile_name}: 执行失败")

    print(f"{'='*60}")

    if successful_profiles:
        print("[OK] 实验执行完成")
        return 0
    else:
        print("[ERROR] 所有实验都失败了")
        return 1

if __name__ == "__main__":
    sys.exit(main())
