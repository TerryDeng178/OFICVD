#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""等待阶段1完成并运行阶段2"""
import json
import subprocess
import sys
import time
from pathlib import Path

def find_latest_stage1_dir():
    """找到最新的阶段1目录"""
    optimizer_dir = Path("runtime/optimizer")
    if not optimizer_dir.exists():
        return None
    
    stage1_dirs = [d for d in optimizer_dir.iterdir() if d.is_dir() and d.name.startswith("stage1_")]
    if not stage1_dirs:
        return None
    
    return max(stage1_dirs, key=lambda p: p.stat().st_mtime)

def check_stage1_complete(stage1_dir: Path, expected_trials: int = 30):
    """检查阶段1是否完成"""
    results_file = stage1_dir / "trial_results.json"
    if not results_file.exists():
        return False
    
    try:
        with open(results_file, "r", encoding="utf-8") as f:
            results = json.load(f)
        
        # 检查是否有足够的trial
        if len(results) < expected_trials:
            return False
        
        # 检查是否所有trial都完成（成功或失败）
        completed = sum(1 for r in results if r.get("success") is not None)
        return completed >= expected_trials
    except Exception:
        return False

def get_best_config(stage1_dir: Path) -> Path:
    """获取阶段1的最佳配置"""
    recommended_config = stage1_dir / "recommended_config.yaml"
    if recommended_config.exists():
        return recommended_config
    
    # 如果没有推荐配置，使用基础配置
    return Path("config/backtest.yaml")

def main():
    """主函数"""
    print("=" * 80)
    print("等待阶段1完成并运行阶段2")
    print("=" * 80)
    
    # 找到最新的阶段1目录
    stage1_dir = find_latest_stage1_dir()
    if not stage1_dir:
        print("未找到阶段1目录，请先运行阶段1优化")
        return 1
    
    print(f"找到阶段1目录: {stage1_dir}")
    
    # 等待阶段1完成
    max_wait_time = 3600  # 最多等待1小时
    check_interval = 30  # 每30秒检查一次
    waited = 0
    
    print(f"等待阶段1完成（最多等待{max_wait_time}秒）...")
    while waited < max_wait_time:
        if check_stage1_complete(stage1_dir, expected_trials=30):
            print(f"\n阶段1完成！")
            break
        
        print(f"等待中... ({waited}/{max_wait_time}秒)")
        time.sleep(check_interval)
        waited += check_interval
    else:
        print("\n等待超时，但继续运行阶段2...")
    
    # 获取最佳配置
    best_config = get_best_config(stage1_dir)
    print(f"\n使用配置: {best_config}")
    
    # 运行阶段2
    print("\n" + "=" * 80)
    print("运行阶段2优化")
    print("=" * 80)
    
    cmd = [
        sys.executable,
        "scripts/run_stage2_optimization.py",
        "--config", str(best_config),
        "--search-space", "tasks/TASK-09/search_space_stage2.json",
        "--date", "2025-11-09",
        "--symbols", "BTCUSDT",
        "--method", "random",
        "--max-trials", "20",
        "--max-workers", "2",
        "--early-stop-rounds", "10",
    ]
    
    print(f"执行命令: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())

