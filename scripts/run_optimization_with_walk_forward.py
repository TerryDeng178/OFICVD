#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""带Walk-forward验证的优化执行脚本"""
import argparse
import json
import logging
import sys
from pathlib import Path

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


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="带Walk-forward验证的优化")
    parser.add_argument(
        "--config",
        type=str,
        default="config/backtest.yaml",
        help="基础配置文件路径",
    )
    parser.add_argument(
        "--search-space",
        type=str,
        required=True,
        help="搜索空间JSON文件路径",
    )
    parser.add_argument(
        "--input",
        type=str,
        default="deploy/data/ofi_cvd",
        help="输入数据目录",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTCUSDT",
        help="交易对（逗号分隔）",
    )
    parser.add_argument(
        "--method",
        type=str,
        choices=["grid", "random"],
        default="random",
        help="搜索方法",
    )
    parser.add_argument(
        "--max-trials",
        type=int,
        default=30,
        help="最大试验次数",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=2,
        help="并行worker数",
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.5,
        help="训练集比例（默认0.5，即训练:验证=1:1）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出目录",
    )
    
    args = parser.parse_args()
    
    # 查找可用日期
    input_dir = Path(args.input)
    available_dates = find_available_dates(input_dir)
    
    if len(available_dates) < 2:
        logger.error(f"可用日期不足（需要至少2天）: {available_dates}")
        return 1
    
    logger.info(f"找到 {len(available_dates)} 个可用日期: {available_dates[:5]}...")
    
    # 创建Walk-forward验证器
    validator = WalkForwardValidator(
        dates=available_dates,
        train_ratio=args.train_ratio,
        step_size=1,
    )
    
    folds = validator.generate_folds()
    logger.info(f"生成 {len(folds)} 个walk-forward折叠")
    
    # 加载搜索空间
    search_space_file = Path(args.search_space)
    with open(search_space_file, "r", encoding="utf-8") as f:
        search_space_data = json.load(f)
    
    search_space = search_space_data.get("search_space", {})
    scoring_weights = search_space_data.get("scoring_weights", None)
    
    # 创建输出目录
    if args.output:
        output_dir = Path(args.output)
    else:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(f"runtime/optimizer/walkforward_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 对每个fold运行优化
    fold_results = []
    
    for fold_idx, (train_dates, val_dates) in enumerate(folds, 1):
        logger.info(f"\n{'='*80}")
        logger.info(f"Fold {fold_idx}/{len(folds)}")
        logger.info(f"训练日期: {train_dates}")
        logger.info(f"验证日期: {val_dates}")
        logger.info(f"{'='*80}")
        
        # 使用训练日期运行优化
        fold_output_dir = output_dir / f"fold_{fold_idx}"
        
        # 解析symbols列表
        symbols_list = args.symbols.split(",") if args.symbols else []
        
        optimizer = ParameterOptimizer(
            base_config_path=Path(args.config),
            search_space=search_space,
            output_dir=fold_output_dir,
            runner="replay_harness",
            scoring_weights=scoring_weights,
            symbols=symbols_list,  # 多品种公平权重：传递symbols列表
        )
        
        # 运行优化（使用训练日期，并传递walk-forward日期列表）
        # 注意：replay_harness只支持单个日期，所以使用第一个训练日期
        # optimizer会在内部处理多日期合并（通过_run_validation_trial）
        backtest_args = {
            "input": args.input,
            "date": train_dates[0],  # 使用第一个训练日期作为主训练日期
            "symbols": args.symbols.split(","),
        }
        
        try:
            # 运行优化，optimizer会自动在验证日期上运行验证回测
            results = optimizer.optimize(
                backtest_args=backtest_args,
                method=args.method,
                max_trials=args.max_trials,
                max_workers=args.max_workers,
                resume=True,
                walk_forward_dates=train_dates + val_dates,  # 传递所有日期（训练+验证）
                train_ratio=args.train_ratio,
            )
            
            # 找到最佳trial（基于训练分数）
            successful_results = [r for r in results if r.get("success")]
            if successful_results:
                # 优先使用train_score，如果没有则使用score
                best_result = max(
                    successful_results,
                    key=lambda x: x.get("train_score", x.get("score", -999))
                )
                
                # 提取walk-forward指标（包含多品种公平权重指标）
                train_metrics = best_result.get("metrics", {})
                val_metrics = best_result.get("val_metrics", {})
                
                fold_results.append({
                    "fold": fold_idx,
                    "train_dates": train_dates,
                    "val_dates": val_dates,
                    "best_trial_id": best_result.get("trial_id"),
                    "train_score": best_result.get("train_score", best_result.get("score")),
                    "val_score": best_result.get("val_score"),
                    "generalization_gap": best_result.get("generalization_gap"),
                    "train_metrics": train_metrics,
                    "val_metrics": val_metrics,
                    # 多品种公平权重：等权评分
                    "equal_weight_train_score": best_result.get("equal_weight_score"),
                    "equal_weight_val_score": None,  # 需要从val_metrics计算
                    # 多品种公平权重：per-symbol指标
                    "by_symbol_train_metrics": train_metrics.get("by_symbol", {}),
                    "by_symbol_val_metrics": val_metrics.get("by_symbol", {}) if val_metrics else {},
                })
                
                # 计算验证集的等权评分（如果有by_symbol数据）
                if val_metrics and val_metrics.get("by_symbol"):
                    try:
                        from alpha_core.report.multi_symbol_scorer import MultiSymbolScorer
                        scorer = MultiSymbolScorer(symbols_list)
                        val_trial_result = {"metrics": val_metrics}
                        val_multi_result = scorer.calculate_equal_weight_score(val_trial_result)
                        if val_multi_result.get("symbol_count", 0) > 0:
                            fold_results[-1]["equal_weight_val_score"] = val_multi_result.get("equal_weight_score")
                    except Exception as e:
                        logger.debug(f"计算验证集等权评分失败: {e}")
                
                logger.info(f"Fold {fold_idx} 最佳trial: {best_result.get('trial_id')}")
                logger.info(f"  训练分数: {best_result.get('train_score', best_result.get('score')):.4f}")
                logger.info(f"  验证分数: {best_result.get('val_score', 'N/A')}")
                logger.info(f"  泛化差距: {best_result.get('generalization_gap', 'N/A')}")
        
        except Exception as e:
            logger.error(f"Fold {fold_idx} 失败: {e}", exc_info=True)
    
    # 保存walk-forward结果
    wf_results_file = output_dir / "walkforward_results.json"
    with open(wf_results_file, "w", encoding="utf-8") as f:
        json.dump(fold_results, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\nWalk-forward验证完成，结果已保存: {wf_results_file}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

