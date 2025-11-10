#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Walk-forward验证功能测试脚本"""
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_core.report.optimizer import ParameterOptimizer
from alpha_core.report.walk_forward import WalkForwardValidator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def find_available_dates(input_dir: Path) -> list:
    """查找可用日期"""
    dates = []
    
    # 查找preview/date=目录
    preview_dir = input_dir / "preview"
    if preview_dir.exists():
        for date_dir in preview_dir.glob("date=*"):
            date_str = date_dir.name.replace("date=", "")
            dates.append(date_str)
    
    # 查找ready/date=目录
    ready_dir = input_dir / "ready"
    if ready_dir.exists():
        for date_dir in ready_dir.glob("date=*"):
            date_str = date_dir.name.replace("date=", "")
            if date_str not in dates:
                dates.append(date_str)
    
    return sorted(dates)


def create_test_search_space() -> dict:
    """创建测试用的简化搜索空间"""
    return {
        "search_space": {
            "signal.thresholds.active.buy": [0.8, 0.85],
            "signal.thresholds.active.sell": [-0.85, -0.8],
            "backtest.min_hold_time_sec": [90, 120],
        },
        "scoring_weights": None,
    }


def main():
    """主函数"""
    logger.info("=" * 80)
    logger.info("Walk-forward验证功能测试")
    logger.info("=" * 80)
    
    # 查找可用日期
    input_dir = Path("deploy/data/ofi_cvd")
    available_dates = find_available_dates(input_dir)
    
    logger.info(f"找到 {len(available_dates)} 个可用日期: {available_dates}")
    
    if len(available_dates) < 2:
        logger.error(f"可用日期不足（需要至少2天）: {available_dates}")
        return 1
    
    # 创建测试搜索空间
    search_space_data = create_test_search_space()
    search_space = search_space_data["search_space"]
    scoring_weights = search_space_data["scoring_weights"]
    
    logger.info(f"测试搜索空间: {list(search_space.keys())}")
    
    # 创建Walk-forward验证器
    validator = WalkForwardValidator(
        dates=available_dates,
        train_ratio=0.5,
        step_size=1,
    )
    
    folds = validator.generate_folds()
    logger.info(f"生成 {len(folds)} 个walk-forward折叠")
    
    for fold_idx, (train_dates, val_dates) in enumerate(folds, 1):
        logger.info(f"\nFold {fold_idx}:")
        logger.info(f"  训练日期: {train_dates}")
        logger.info(f"  验证日期: {val_dates}")
    
    # 创建输出目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(f"runtime/optimizer/test_walkforward_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"\n输出目录: {output_dir}")
    
    # 创建optimizer
    # 解析symbols列表（测试脚本使用默认值）
    symbols_list = ["BTCUSDT"]
    
    optimizer = ParameterOptimizer(
        base_config_path=Path("config/backtest.yaml"),
        search_space=search_space,
        output_dir=output_dir,
        runner="replay_harness",
        scoring_weights=scoring_weights,
        symbols=symbols_list,  # 多品种公平权重：传递symbols列表
    )
    
    # 运行优化（使用第一个fold进行测试）
    if folds:
        train_dates, val_dates = folds[0]
        logger.info(f"\n使用第一个fold进行测试:")
        logger.info(f"  训练日期: {train_dates}")
        logger.info(f"  验证日期: {val_dates}")
        
        backtest_args = {
            "input": str(input_dir),
            "date": train_dates[0],  # 使用第一个训练日期
            "symbols": ["BTCUSDT"],
        }
        
        logger.info("\n开始运行优化（启用walk-forward验证）...")
        logger.info(f"  方法: random")
        logger.info(f"  最大trial数: 3")
        logger.info(f"  并行worker数: 1")
        
        try:
            results = optimizer.optimize(
                backtest_args=backtest_args,
                method="random",
                max_trials=3,  # 只运行3个trial进行快速测试
                max_workers=1,  # 串行运行以便观察日志
                resume=False,
                walk_forward_dates=train_dates + val_dates,
                train_ratio=0.5,
            )
            
            logger.info(f"\n优化完成，共 {len(results)} 个trial")
            
            # 检查walk-forward指标
            successful_results = [r for r in results if r.get("success")]
            logger.info(f"成功trial数: {len(successful_results)}")
            
            if successful_results:
                logger.info("\nWalk-forward指标检查:")
                for result in successful_results:
                    trial_id = result.get("trial_id")
                    train_score = result.get("train_score")
                    val_score = result.get("val_score")
                    generalization_gap = result.get("generalization_gap")
                    
                    logger.info(f"\nTrial {trial_id}:")
                    logger.info(f"  训练分数: {train_score}")
                    logger.info(f"  验证分数: {val_score}")
                    logger.info(f"  泛化差距: {generalization_gap}")
                    
                    if train_score is not None and val_score is not None:
                        logger.info(f"  [OK] Walk-forward指标存在")
                    else:
                        logger.warning(f"  [WARN] Walk-forward指标缺失")
                
                # 检查CSV文件
                csv_file = output_dir / "trial_results.csv"
                if csv_file.exists():
                    logger.info(f"\n[OK] CSV文件已生成: {csv_file}")
                    logger.info("  检查CSV是否包含walk-forward列...")
                    with open(csv_file, "r", encoding="utf-8") as f:
                        header = f.readline().strip()
                        if "train_score" in header and "val_score" in header and "generalization_gap" in header:
                            logger.info("  [OK] CSV包含walk-forward列")
                        else:
                            logger.warning(f"  [WARN] CSV缺少walk-forward列")
                            logger.warning(f"  表头: {header}")
                else:
                    logger.warning(f"[WARN] CSV文件不存在: {csv_file}")
                
                logger.info(f"\n[OK] Walk-forward验证测试完成")
                logger.info(f"结果目录: {output_dir}")
                return 0
            else:
                logger.error("[ERROR] 没有成功的trial")
                return 1
        
        except Exception as e:
            logger.error(f"[ERROR] 优化失败: {e}", exc_info=True)
            return 1
    else:
        logger.error("[ERROR] 没有可用的fold")
        return 1


if __name__ == "__main__":
    sys.exit(main())

