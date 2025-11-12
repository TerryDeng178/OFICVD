# -*- coding: utf-8 -*-
"""检查E组实验运行状态"""
import json
import sys
from pathlib import Path
from datetime import datetime

# 项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

E_GROUPS = {
    "E1": {
        "name": "入口节流+去重加严",
        "output_prefix": "group_e1",
    },
    "E2": {
        "name": "Maker概率&费率专项",
        "output_prefix": "group_e2",
    },
    "E3": {
        "name": "TP/SL + 死区组合",
        "output_prefix": "group_e3",
    }
}


def check_experiment_status(group_key: str, group_info: dict) -> dict:
    """检查单个实验的状态"""
    output_dir = project_root / "runtime" / "optimizer" / f"{group_info['output_prefix']}_validation"
    
    status = {
        "group": group_key,
        "name": group_info["name"],
        "status": "not_started",
        "result_dir": None,
        "has_metrics": False,
        "metrics": None,
    }
    
    if not output_dir.exists():
        return status
    
    # 查找最新的回测目录
    backtest_dirs = list(output_dir.glob("backtest_*"))
    if not backtest_dirs:
        status["status"] = "running"
        return status
    
    # 按修改时间排序，取最新的
    backtest_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    result_dir = backtest_dirs[0]
    
    status["result_dir"] = str(result_dir)
    status["status"] = "completed"
    
    # 检查是否有metrics.json
    metrics_file = result_dir / "metrics.json"
    if metrics_file.exists():
        status["has_metrics"] = True
        try:
            with open(metrics_file, "r", encoding="utf-8") as f:
                status["metrics"] = json.load(f)
        except Exception as e:
            status["error"] = str(e)
    
    return status


def main():
    """主函数"""
    print("="*80)
    print("E组实验运行状态")
    print("="*80 + "\n")
    
    all_status = {}
    for group_key, group_info in E_GROUPS.items():
        status = check_experiment_status(group_key, group_info)
        all_status[group_key] = status
        
        # 打印状态
        status_icon = {
            "not_started": "[WAIT]",
            "running": "[RUN]",
            "completed": "[OK]",
        }.get(status["status"], "[?]")
        
        print(f"{status_icon} {group_key}: {status['name']}")
        print(f"    状态: {status['status']}")
        
        if status["result_dir"]:
            print(f"    结果目录: {status['result_dir']}")
        
        if status["has_metrics"]:
            metrics = status["metrics"]
            total_trades = metrics.get("total_trades", 0)
            net_pnl = metrics.get("total_pnl", 0) - metrics.get("total_fee", 0) - metrics.get("total_slippage", 0)
            cost_bps = metrics.get("cost_bps_on_turnover", 0)
            print(f"    交易次数: {total_trades}")
            print(f"    净PnL: ${net_pnl:.2f}")
            print(f"    成本bps: {cost_bps:.2f}")
        
        print()
    
    # 检查是否全部完成
    all_completed = all(s["status"] == "completed" for s in all_status.values())
    all_have_metrics = all(s["has_metrics"] for s in all_status.values())
    
    if all_completed and all_have_metrics:
        print("[OK] 所有实验已完成，可以运行验收脚本:")
        print("  python scripts/validate_e_experiments.py")
    elif all_completed:
        print("[WARN] 所有实验已完成，但部分实验缺少metrics.json")
    else:
        print("[INFO] 实验仍在运行中，请稍后再次检查")
    
    return all_status


if __name__ == "__main__":
    main()

