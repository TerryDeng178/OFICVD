#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TASK-09 阶段1优化：稳胜率 + 控回撤"""
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
    """TASK-07B: 检查双Sink等价性前置条件
    
    Args:
        config_path: 配置文件路径
        input_dir: 输入数据目录
        date: 回测日期
        symbols: 交易对（逗号分隔）
        minutes: 测试时长（分钟，默认2分钟）
        threshold: 差异阈值（单位：百分比数值，0.2表示0.2%，即20bp）
    
    Returns:
        True表示通过，False表示失败（Fail-Closed策略）
    """
    logger.info("=" * 80)
    logger.info("TASK-07B: 双Sink等价性前置检查")
    logger.info("=" * 80)
    
    try:
        # 运行一个短时间的双Sink测试
        # F系列实验修复: replay_harness不支持dual sink，需要分别运行jsonl和sqlite
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
        
        # 使用SQLite的RUN_ID（两个sink应该使用相同的RUN_ID）
        result = result_sqlite
        
        # 获取RUN_ID（优先从输出目录读取run_manifest.json，其次环境变量，最后日志）
        run_id = os.getenv("RUN_ID", "")
        if not run_id:
            # P1修复: 尝试从输出目录读取run_manifest.json（更健壮）
            # 查找最新的backtest目录
            output_base = Path("runtime")
            if output_base.exists():
                backtest_dirs = sorted(output_base.glob("**/backtest_*"), key=lambda p: p.stat().st_mtime, reverse=True)
                for backtest_dir in backtest_dirs[:3]:  # 只检查最新的3个
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
            # 最后尝试从日志中提取RUN_ID
            for line in result.stdout.split("\n"):
                if "RUN_ID" in line or "run_id" in line:
                    # 简单提取，可能需要更复杂的解析
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if "run_id" in part.lower() and i + 1 < len(parts):
                            run_id = parts[i + 1].strip("'\"")
                            break
                    if run_id:
                        break
        
        if not run_id:
            logger.error("无法获取RUN_ID，无法完成双Sink等价性验证（Fail-Closed）")
            return False  # P1修复: fail-closed，无法验证等价性则拒绝继续
        
        # 运行等价性验证
        logger.info(f"验证双Sink等价性（RUN_ID={run_id}，阈值={threshold}%，即{threshold*10}bp）...")
        verify_script = Path(__file__).parent / "verify_sink_parity.py"
        if not verify_script.exists():
            logger.error(f"验证脚本不存在: {verify_script}（Fail-Closed）")
            return False  # P1修复: fail-closed，验证脚本不存在则拒绝继续
        
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
            logger.error("双Sink等价性检查失败，中断参数搜索")
            logger.error(f"验证输出: {verify_result.stdout}")
            logger.error(f"验证错误: {verify_result.stderr}")
            return False
        
        # 解析验证结果
        logger.info("双Sink等价性前置检查通过，可以开始参数优化")
        logger.info(f"验证输出: {verify_result.stdout[:500]}")
        return True
        
    except Exception as e:
        logger.error(f"双Sink前置检查异常: {e}", exc_info=True)
        return False


def run_dual_sink_regression_check(
    run_id: str,
    threshold: float = 0.2,
) -> bool:
    """TASK-07B: 批次结束后的双Sink等价性回归检查
    
    Args:
        run_id: 优化批次的RUN_ID
        threshold: 差异阈值（单位：百分比数值，0.2表示0.2%，即20bp）
    
    Returns:
        True表示通过，False表示失败
    """
    logger.info("=" * 80)
    logger.info("TASK-07B: 双Sink等价性回归检查")
    logger.info("=" * 80)
    logger.info(f"RUN_ID: {run_id}")
    
    try:
        verify_script = Path(__file__).parent / "verify_sink_parity.py"
        if not verify_script.exists():
            logger.warning(f"验证脚本不存在: {verify_script}，跳过回归检查")
            return True
        
        logger.info(f"运行双Sink等价性回归检查（阈值={threshold}%，即{threshold*10}bp）...")
        verify_result = subprocess.run(
            [
                sys.executable,
                str(verify_script),
                "--run-id",
                run_id,
                "--threshold",
                str(threshold),
                "--output",
                f"runtime/artifacts/parity_regression_{run_id}.json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        
        if verify_result.returncode != 0:
            logger.error("双Sink等价性回归检查失败")
            logger.error(f"验证输出: {verify_result.stdout}")
            logger.error(f"验证错误: {verify_result.stderr}")
            return False
        
        logger.info("双Sink等价性回归检查通过")
        logger.info(f"验证输出: {verify_result.stdout[:500]}")
        return True
        
    except Exception as e:
        logger.error(f"双Sink回归检查异常: {e}", exc_info=True)
        return False


def main():
    """阶段1优化主函数"""
    parser = argparse.ArgumentParser(description="阶段1优化：稳胜率 + 控回撤")
    parser.add_argument(
        "--config",
        type=str,
        default="config/backtest.yaml",
        help="基础配置文件路径",
    )
    parser.add_argument(
        "--search-space",
        type=str,
        default="tasks/TASK-09/search_space_stage1.json",
        help="阶段1搜索空间JSON文件路径",
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
        help="回测日期（YYYY-MM-DD）",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTCUSDT",
        help="交易对（逗号分隔）",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=None,
        help="回测时长（分钟，用于快速测试）",
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
        help="最大试验次数（grid模式：随机选择前N个组合；random模式：限制随机搜索次数）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出目录（默认：runtime/optimizer/stage1/）",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="并行worker数（默认1，串行）",
    )
    parser.add_argument(
        "--early-stop-rounds",
        type=int,
        default=None,
        help="早停轮数（随机搜索时，N轮无提升则停止）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="允许复用历史结果（默认关闭，避免误复用）",
    )
    parser.add_argument(
        "--sink",
        type=str,
        choices=["sqlite", "jsonl", "null"],
        default="sqlite",
        help="信号Sink类型（TASK-07B: 优化期必须固定，默认sqlite）",
    )
    parser.add_argument(
        "--skip-dual-sink-check",
        action="store_true",
        help="跳过双Sink等价性前置检查（不推荐，仅用于调试）",
    )
    parser.add_argument(
        "--skip-regression-check",
        action="store_true",
        help="跳过批次结束后的双Sink等价性回归检查（不推荐）",
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
    
    # 加载搜索空间（可能包含scoring_weights）
    with open(search_space_file, "r", encoding="utf-8") as f:
        search_space_data = json.load(f)
    
    search_space = search_space_data.get("search_space", {})
    scoring_weights = search_space_data.get("scoring_weights", None)
    
    # 兼容：如果文件顶层没包 "search_space"，把整个文件当作 search_space
    if not search_space and search_space_data:
        logger.warning("未找到 'search_space' 键，尝试使用文件顶层作为搜索空间")
        search_space = search_space_data
    
    # 计算组合数并做健全性检查
    def _combo_count(space: dict) -> int:
        import collections.abc as cab
        total = 1
        for k, v in space.items():
            if not isinstance(v, cab.Sequence) or isinstance(v, (str, bytes)):
                logger.warning(f"键 {k} 的值不是列表，按单一取值处理")
                v = [v]
            total *= len(v)
        return total
    
    combos = _combo_count(search_space)
    
    # F系列实验修复: 允许单组合（如F4只有1个固定配置）
    if combos == 1:
        logger.warning(f"搜索空间组合数=1（可能是固定配置，如F4），继续执行")
    elif combos < 1:
        logger.error("搜索空间组合数<1，配置错误")
        return 1
    
    # P0修复: 预览前三个候选组合（仅打印键值），用于人工核对
    try:
        from itertools import product, islice
        keys = list(search_space.keys())
        values = [v if isinstance(v, list) else [v] for v in search_space.values()]
        previews = list(islice(product(*values), 3))
        preview_dicts = [dict(zip(keys, p)) for p in previews]
        logger.info(f"候选组合预览(前三): {preview_dicts}")
    except Exception as e:
        logger.warning(f"无法生成组合预览: {e}")
    
    logger.info("=" * 80)
    logger.info("阶段1优化：稳胜率 + 控回撤")
    logger.info("=" * 80)
    logger.info(f"目标: {search_space_data.get('target', 'N/A')}")
    logger.info(f"基础配置: {config_path}")
    logger.info(f"搜索空间键数={len(search_space)}，组合数={combos}")
    logger.info(f"搜索方法: {args.method}")
    logger.info(f"Sink类型: {args.sink} (TASK-07B: 优化期固定)")
    if scoring_weights:
        logger.info(f"评分权重: {scoring_weights}")
    
    # TASK-07B: 双Sink等价性前置检查
    if not args.skip_dual_sink_check:
        if not check_dual_sink_parity_prerequisite(
            config_path=config_path,
            input_dir=args.input,
            date=args.date,
            symbols=args.symbols,
            minutes=2,  # 短时间测试
            threshold=0.2,
        ):
            logger.error("双Sink等价性前置检查失败，中断参数搜索")
            return 1
    else:
        logger.warning("跳过双Sink等价性前置检查（不推荐）")
    
    if combos <= 1:
        # F系列实验修复: 允许单组合（如F4只有1个固定配置）
        logger.warning("搜索空间组合数=1（可能是固定配置，如F4），继续执行")
    
    # 创建输出目录
    if args.output:
        output_dir = Path(args.output)
    else:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(f"runtime/optimizer/stage1_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建优化器（使用阶段1权重）
    # 解析symbols列表
    symbols_list = args.symbols.split(",") if args.symbols else []
    
    optimizer = ParameterOptimizer(
        base_config_path=config_path,
        search_space=search_space,
        output_dir=output_dir,
        runner="replay_harness",
        scoring_weights=scoring_weights,
        symbols=symbols_list,  # 多品种公平权重：传递symbols列表
    )
    
    # 准备回测参数
    backtest_args = {
        "input": args.input,
        "date": args.date,
        "symbols": args.symbols.split(","),
        "minutes": args.minutes,
        "sink": args.sink,  # TASK-07B: 固定Sink类型
    }
    
    # 执行优化
    try:
        results = optimizer.optimize(
            backtest_args=backtest_args,
            method=args.method,
            max_trials=args.max_trials,
            max_workers=args.max_workers,
            early_stop_rounds=args.early_stop_rounds,
            resume=args.resume,  # P0修复: 使用命令行参数，默认False
        )
        
        logger.info(f"\n阶段1优化完成，共运行 {len(results)} 个试验")
        logger.info(f"结果目录: {optimizer.output_dir}")
        logger.info(f"CSV对比表: {optimizer.output_dir / 'trial_results.csv'}")
        logger.info(f"推荐配置: {optimizer.output_dir / 'recommended_config.yaml'}")
        
        # TASK-07B: 批次结束后的双Sink等价性回归检查
        if not args.skip_regression_check:
            # 尝试从输出目录或环境变量获取RUN_ID
            run_id = os.getenv("RUN_ID", "")
            if not run_id:
                # 尝试从最新的trial结果中提取RUN_ID
                trial_dirs = sorted(optimizer.output_dir.glob("trial_*"))
                if trial_dirs:
                    latest_trial = trial_dirs[-1]
                    backtest_dirs = list(latest_trial.glob("backtest_*"))
                    if backtest_dirs:
                        manifest_file = backtest_dirs[0] / "run_manifest.json"
                        if manifest_file.exists():
                            try:
                                with open(manifest_file, "r", encoding="utf-8") as f:
                                    manifest = json.load(f)
                                    run_id = manifest.get("run_id", "")
                            except Exception:
                                pass
            
            if run_id:
                logger.info(f"\n运行双Sink等价性回归检查（RUN_ID={run_id}）...")
                if not run_dual_sink_regression_check(run_id, threshold=0.2):
                    logger.warning("双Sink等价性回归检查失败，请检查结果")
                    logger.warning("建议：分析差异原因，确认无回归后再合入优化结果")
                else:
                    logger.info("双Sink等价性回归检查通过")
            else:
                logger.warning("无法获取RUN_ID，跳过双Sink等价性回归检查")
        else:
            logger.warning("跳过双Sink等价性回归检查（不推荐）")
        
        return 0
    except Exception as e:
        logger.error(f"优化失败: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

