#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TASK-09 STAGE-2优化：基于Trial 5基线，F2-F5联合优化"""
import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_core.report.optimizer import ParameterOptimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def check_dual_sink_parity_prerequisite(
    config_path: Path,
    input_dir: str,
    date: str,
    symbols: str,
    minutes: int = 2,
    threshold: float = 0.2,
) -> bool:
    """TASK-07B: 检查双Sink等价性前置条件"""
    logger.info("=" * 80)
    logger.info("TASK-07B: 双Sink等价性前置检查")
    logger.info("=" * 80)
    
    try:
        logger.info(f"运行双Sink测试（{minutes}分钟）...")
        
        # 运行JSONL sink
        cmd_jsonl = [
            sys.executable,
            "scripts/replay_harness.py",
            "--config",
            str(config_path),
            "--input", input_dir or "deploy/data/ofi_cvd",
            "--date", date or "2025-11-10",
            "--symbols", symbols or "BTCUSDT",
            "--kinds", "features",
            "--minutes",
            str(minutes),
            "--sink",
            "jsonl",
        ]
        
        result_jsonl = subprocess.run(
            cmd_jsonl,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=os.environ.copy(),
        )
        
        if result_jsonl.returncode != 0:
            logger.error(f"JSONL Sink测试失败，退出码: {result_jsonl.returncode}")
            logger.error(f"错误信息: {result_jsonl.stderr[:500]}")
            return False
        
        # 运行SQLite sink
        cmd_sqlite = [
            sys.executable,
            "scripts/replay_harness.py",
            "--config",
            str(config_path),
            "--input", input_dir or "deploy/data/ofi_cvd",
            "--date", date or "2025-11-10",
            "--symbols", symbols or "BTCUSDT",
            "--kinds", "features",
            "--minutes",
            str(minutes),
            "--sink",
            "sqlite",
        ]
        
        result_sqlite = subprocess.run(
            cmd_sqlite,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=os.environ.copy(),
        )
        
        if result_sqlite.returncode != 0:
            logger.error(f"SQLite Sink测试失败，退出码: {result_sqlite.returncode}")
            logger.error(f"错误信息: {result_sqlite.stderr[:500]}")
            return False
        
        result = result_sqlite
        
        # 获取RUN_ID
        run_id = os.getenv("RUN_ID", "")
        if not run_id:
            output_base = Path("runtime")
            if output_base.exists():
                backtest_dirs = sorted(output_base.glob("**/backtest_*"), key=lambda p: p.stat().st_mtime, reverse=True)
                for backtest_dir in backtest_dirs[:3]:
                    manifest_file = backtest_dir / "run_manifest.json"
                    if manifest_file.exists():
                        try:
                            with open(manifest_file, "r", encoding="utf-8") as f:
                                manifest = json.load(f)
                                run_id = manifest.get("run_id", "")
                                if run_id:
                                    logger.info(f"从 {manifest_file} 读取RUN_ID: {run_id}")
                                    break
                        except Exception:
                            pass
        
        if not run_id:
            logger.error("无法获取RUN_ID，无法完成双Sink等价性验证（Fail-Closed）")
            return False
        
        # 运行等价性验证
        logger.info(f"验证双Sink等价性（RUN_ID={run_id}，阈值={threshold}%，即{threshold*10}bp）...")
        verify_script = Path(__file__).parent / "verify_sink_parity.py"
        if not verify_script.exists():
            logger.error(f"验证脚本不存在: {verify_script}（Fail-Closed）")
            return False
        
        verify_result = subprocess.run(
            [
                sys.executable,
                str(verify_script),
                "--run-id",
                run_id,
                "--threshold",
                str(threshold),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        
        if verify_result.returncode != 0:
            logger.error("双Sink等价性前置检查失败")
            logger.error(f"验证输出: {verify_result.stdout}")
            logger.error(f"验证错误: {verify_result.stderr}")
            return False
        
        logger.info("双Sink等价性前置检查通过，可以开始参数优化")
        logger.info(f"验证结果: {verify_result.stdout[:500]}")
        return True
        
    except Exception as e:
        logger.error(f"双Sink前置检查异常: {e}", exc_info=True)
        return False


def main():
    """STAGE-2优化主函数"""
    parser = argparse.ArgumentParser(description="STAGE-2优化：基于Trial 5基线，F2-F5联合优化")
    parser.add_argument(
        "--config",
        type=str,
        default="runtime/optimizer/group_stage2_baseline_trial5.yaml",
        help="基础配置文件路径（Trial 5基线）",
    )
    parser.add_argument(
        "--search-space",
        type=str,
        required=True,
        help="搜索空间JSON/YAML文件路径",
    )
    parser.add_argument(
        "--input",
        type=str,
        default="deploy/data/ofi_cvd",
        help="输入数据目录",
    )
    parser.add_argument(
        "--date",
        type=str,
        required=True,
        help="回测日期（YYYY-MM-DD），支持逗号分隔多个日期",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTCUSDT,ETHUSDT,BNBUSDT",
        help="交易对（逗号分隔）",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=None,
        help="回测时长（分钟，默认24小时=1440分钟）",
    )
    parser.add_argument(
        "--method",
        type=str,
        choices=["grid", "random"],
        default="grid",
        help="搜索方法（grid/random）",
    )
    parser.add_argument(
        "--max-trials",
        type=int,
        default=None,
        help="最大试验次数",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出目录（默认：runtime/optimizer/stage2_YYYYMMDD_HHMMSS/）",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=6,
        help="并行worker数",
    )
    parser.add_argument(
        "--sink",
        type=str,
        choices=["sqlite", "jsonl", "null"],
        default="sqlite",
        help="信号Sink类型",
    )
    parser.add_argument(
        "--skip-dual-sink-check",
        action="store_true",
        help="跳过双Sink等价性前置检查",
    )
    
    args = parser.parse_args()
    
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"配置文件不存在: {config_path}")
        return 1
    
    search_space_file = Path(args.search_space)
    if not search_space_file.exists():
        logger.error(f"搜索空间文件不存在: {search_space_file}")
        return 1
    
    # 加载搜索空间（可能包含scoring_weights和hard_constraints）
    with open(search_space_file, "r", encoding="utf-8") as f:
        if search_space_file.suffix == ".yaml":
            import yaml
            search_space_data = yaml.safe_load(f)
        else:
            search_space_data = json.load(f)
    
    search_space = search_space_data.get("search_space", {})
    scoring_weights = search_space_data.get("scoring_weights", None)
    hard_constraints = search_space_data.get("hard_constraints", None)
    
    # 兼容：如果文件顶层没包 "search_space"，把整个文件当作 search_space
    if not search_space and search_space_data:
        logger.warning("未找到 'search_space' 键，尝试使用文件顶层作为搜索空间")
        search_space = search_space_data
    
    # 过滤掉非参数字段（note, description等）
    search_space = {k: v for k, v in search_space.items() if k not in ("note", "description", "target")}
    
    # 计算组合数
    def _combo_count(space: dict) -> int:
        import collections.abc as cab
        total = 1
        for k, v in space.items():
            if k in ("note", "description", "target"):
                continue
            if not isinstance(v, cab.Sequence) or isinstance(v, (str, bytes)):
                logger.warning(f"键 {k} 的值不是列表，按单一取值处理")
                v = [v]
            total *= len(v)
        return total
    
    combos = _combo_count(search_space)
    
    if combos == 1:
        logger.warning(f"搜索空间组合数=1（可能是固定配置），继续执行")
    elif combos < 1:
        logger.error("搜索空间组合数<1，配置错误")
        return 1
    
    logger.info("=" * 80)
    logger.info("STAGE-2优化：基于Trial 5基线")
    logger.info("=" * 80)
    logger.info(f"基础配置: {config_path}")
    logger.info(f"搜索空间: {search_space_file}")
    logger.info(f"组合数: {combos}")
    logger.info(f"评分权重: {scoring_weights}")
    logger.info(f"硬约束: {hard_constraints}")
    
    # 双Sink前置检查
    if not args.skip_dual_sink_check:
        if not check_dual_sink_parity_prerequisite(
            config_path=config_path,
            input_dir=args.input,
            date=args.date.split(",")[0] if "," in args.date else args.date,
            symbols=args.symbols.split(",")[0] if "," in args.symbols else args.symbols,
            minutes=2,
            threshold=0.2,
        ):
            logger.error("双Sink等价性前置检查失败，中断参数搜索")
            return 1
    else:
        logger.warning("跳过双Sink等价性前置检查（不推荐）")
    
    # 创建输出目录
    if args.output:
        output_dir = Path(args.output)
    else:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(f"runtime/optimizer/stage2_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 准备回测参数
    backtest_args = {
        "input": args.input,
        "date": args.date,
        "symbols": args.symbols.split(","),
        "minutes": args.minutes or 1440,  # 默认24小时
        "sink": args.sink,
    }
    
    # 创建优化器
    optimizer = ParameterOptimizer(
        base_config_path=config_path,
        search_space=search_space,
        output_dir=output_dir,
        runner="replay_harness",
        scoring_weights=scoring_weights,
        symbols=backtest_args["symbols"],
    )
    
    # 执行优化
    try:
        results = optimizer.optimize(
            backtest_args=backtest_args,
            method=args.method,
            max_trials=args.max_trials,
            max_workers=args.max_workers,
            resume=False,
        )
        
        logger.info(f"\nSTAGE-2优化完成，共运行 {len(results)} 个试验")
        logger.info(f"结果目录: {optimizer.output_dir}")
        logger.info(f"CSV对比表: {optimizer.output_dir / 'trial_results.csv'}")
        
        # 硬约束检查
        if hard_constraints:
            logger.info("\n硬约束检查:")
            successful = [r for r in results if r.get("success")]
            for constraint_name, constraint_value in hard_constraints.items():
                constraint_met = 0
                for result in successful:
                    metrics = result.get("metrics", {})
                    metric_value = metrics.get(constraint_name, None)
                    if metric_value is not None:
                        # 解析约束（如">= 0"）
                        if ">=" in constraint_value:
                            threshold = float(constraint_value.split(">=")[1].strip())
                            if metric_value >= threshold:
                                constraint_met += 1
                        elif "<=" in constraint_value:
                            threshold = float(constraint_value.split("<=")[1].strip())
                            if metric_value <= threshold:
                                constraint_met += 1
                logger.info(f"  {constraint_name} {constraint_value}: {constraint_met}/{len(successful)} ({constraint_met/len(successful)*100:.1f}%)")
        
        return 0
        
    except Exception as e:
        logger.error(f"优化过程异常: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
