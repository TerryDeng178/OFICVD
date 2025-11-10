# -*- coding: utf-8 -*-
"""运行实验矩阵（2×2×2=8组实验）"""
import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_base_config(config_path: Path) -> dict:
    """加载基础配置"""
    import yaml
    
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def apply_params(base_config: dict, params: dict) -> dict:
    """应用参数到配置（支持dot路径）"""
    import copy
    
    config = copy.deepcopy(base_config)
    
    for param_path, value in params.items():
        parts = param_path.split(".")
        target = config
        
        # 导航到目标位置
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]
        
        # 设置值
        target[parts[-1]] = value
    
    return config


def save_config(config: dict, output_path: Path) -> None:
    """保存配置到YAML文件"""
    import yaml
    
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def run_experiment(exp_id: str, exp_name: str, config: dict, output_base: Path, args) -> dict:
    """运行单个实验"""
    logger.info(f"开始实验: {exp_id} - {exp_name}")
    
    # 保存实验配置
    exp_output_dir = output_base / exp_id
    exp_output_dir.mkdir(parents=True, exist_ok=True)
    config_file = exp_output_dir / "config.yaml"
    save_config(config, config_file)
    
    # 运行回测
    cmd = [
        sys.executable,
        "scripts/replay_harness.py",
        "--input", str(args.input),
        "--date", args.date,
        "--symbols", args.symbols,
        "--kinds", args.kinds,
        "--minutes", str(args.minutes),
        "--config", str(config_file),
        "--output", str(exp_output_dir),
    ]
    
    logger.info(f"执行命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=1800,  # 30分钟超时
        )
        
        if result.returncode != 0:
            logger.error(f"实验 {exp_id} 失败: {result.stderr}")
            return {
                "exp_id": exp_id,
                "exp_name": exp_name,
                "success": False,
                "error": result.stderr[:500] if result.stderr else "Unknown error",
            }
        
        # 读取结果
        backtest_dirs = list(exp_output_dir.glob("backtest_*"))
        if not backtest_dirs:
            logger.error(f"实验 {exp_id} 未找到结果目录")
            return {
                "exp_id": exp_id,
                "exp_name": exp_name,
                "success": False,
                "error": "No result directory found",
            }
        
        result_dir = backtest_dirs[0]
        metrics_file = result_dir / "metrics.json"
        
        if not metrics_file.exists():
            logger.error(f"实验 {exp_id} 未找到metrics.json")
            return {
                "exp_id": exp_id,
                "exp_name": exp_name,
                "success": False,
                "error": "No metrics.json found",
            }
        
        import json as json_lib
        with open(metrics_file, "r", encoding="utf-8") as f:
            metrics = json_lib.load(f)
        
        # 计算关键指标
        total_trades = metrics.get("total_trades", 0)
        total_pnl = metrics.get("total_pnl", 0)
        total_fee = metrics.get("total_fee", 0)
        total_slippage = metrics.get("total_slippage", 0)
        net_pnl = total_pnl - total_fee - total_slippage
        
        trades_per_hour = total_trades / (args.minutes / 60.0) if args.minutes > 0 else 0
        pnl_per_trade = net_pnl / total_trades if total_trades > 0 else 0
        avg_hold_sec = metrics.get("avg_hold_sec", 0)
        cost_bps_on_turnover = metrics.get("cost_bps_on_turnover", 0)
        win_rate_trades = metrics.get("win_rate_trades", 0)
        
        logger.info(
            f"实验 {exp_id} 完成: "
            f"trades/h={trades_per_hour:.1f}, "
            f"hold_sec={avg_hold_sec:.1f}, "
            f"cost_bps={cost_bps_on_turnover:.2f}, "
            f"pnl/trade=${pnl_per_trade:.2f}, "
            f"win_rate={win_rate_trades:.2%}"
        )
        
        return {
            "exp_id": exp_id,
            "exp_name": exp_name,
            "success": True,
            "metrics": metrics,
            "key_indicators": {
                "trades_per_hour": trades_per_hour,
                "avg_hold_sec": avg_hold_sec,
                "cost_bps_on_turnover": cost_bps_on_turnover,
                "pnl_per_trade": pnl_per_trade,
                "win_rate_trades": win_rate_trades,
                "net_pnl": net_pnl,
                "total_trades": total_trades,
            },
            "output_dir": str(result_dir),
        }
        
    except subprocess.TimeoutExpired:
        logger.error(f"实验 {exp_id} 超时")
        return {
            "exp_id": exp_id,
            "exp_name": exp_name,
            "success": False,
            "error": "Timeout",
        }
    except Exception as e:
        logger.error(f"实验 {exp_id} 异常: {e}", exc_info=True)
        return {
            "exp_id": exp_id,
            "exp_name": exp_name,
            "success": False,
            "error": str(e),
        }


def main():
    parser = argparse.ArgumentParser(description="运行实验矩阵")
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("tasks/TASK-09/experiment_matrix_2x2x2.json"),
        help="实验矩阵JSON文件",
    )
    parser.add_argument(
        "--base-config",
        type=Path,
        default=Path("config/backtest.yaml"),
        help="基础配置文件",
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
        help="回测日期",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTCUSDT,ETHUSDT",
        help="交易对（逗号分隔）",
    )
    parser.add_argument(
        "--kinds",
        type=str,
        default="features",
        help="数据类型",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=60,
        help="数据窗口（分钟）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="输出目录（默认：runtime/optimizer/experiment_matrix_YYYYMMDD_HHMMSS）",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=2,
        help="最大并行worker数",
    )
    
    args = parser.parse_args()
    
    # 加载实验矩阵
    with open(args.matrix, "r", encoding="utf-8") as f:
        matrix = json.load(f)
    
    # 加载基础配置
    base_config = load_base_config(args.base_config)
    
    # 确定输出目录
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = Path(f"runtime/optimizer/experiment_matrix_{timestamp}")
    args.output.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"实验矩阵: {len(matrix['experiments'])} 组实验")
    logger.info(f"输出目录: {args.output}")
    
    # 运行所有实验
    results = []
    for exp in matrix["experiments"]:
        exp_id = exp["id"]
        exp_name = exp["name"]
        params = exp["params"]
        
        # 应用参数到基础配置
        exp_config = apply_params(base_config, params)
        
        # 运行实验
        result = run_experiment(exp_id, exp_name, exp_config, args.output, args)
        results.append(result)
    
    # 保存结果
    results_file = args.output / "experiment_results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump({
            "matrix": matrix,
            "results": results,
            "baseline": matrix.get("baseline", {}),
            "acceptance_criteria": matrix.get("acceptance_criteria", {}),
        }, f, ensure_ascii=False, indent=2)
    
    # 生成对比报告
    generate_comparison_report(results, matrix, args.output)
    
    logger.info(f"所有实验完成，结果已保存: {results_file}")


def generate_comparison_report(results: list, matrix: dict, output_dir: Path) -> None:
    """生成对比报告"""
    baseline = matrix.get("baseline", {})
    baseline_metrics = baseline.get("metrics", {})
    
    report_lines = [
        "# 实验矩阵对比报告",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 基线指标",
        "",
        f"- `trades_per_hour`: {baseline_metrics.get('trades_per_hour', 'N/A')}",
        f"- `avg_hold_sec`: {baseline_metrics.get('avg_hold_sec', 'N/A')}s",
        f"- `cost_bps_on_turnover`: {baseline_metrics.get('cost_bps_on_turnover', 'N/A')}bps",
        f"- `pnl_per_trade`: ${baseline_metrics.get('pnl_per_trade', 'N/A')}",
        f"- `win_rate_trades`: {baseline_metrics.get('win_rate_trades', 'N/A'):.2%}",
        "",
        "## 实验结果对比",
        "",
        "| 实验ID | 实验名称 | 成功 | trades/h | avg_hold_sec | cost_bps | pnl/trade | win_rate | vs基线 |",
        "|--------|----------|------|----------|--------------|----------|-----------|----------|--------|",
    ]
    
    for result in results:
        if not result.get("success"):
            report_lines.append(
                f"| {result['exp_id']} | {result['exp_name']} | ❌ | - | - | - | - | - | 失败 |"
            )
            continue
        
        indicators = result.get("key_indicators", {})
        trades_h = indicators.get("trades_per_hour", 0)
        hold_sec = indicators.get("avg_hold_sec", 0)
        cost_bps = indicators.get("cost_bps_on_turnover", 0)
        pnl_trade = indicators.get("pnl_per_trade", 0)
        win_rate = indicators.get("win_rate_trades", 0)
        
        # 计算vs基线改善
        vs_baseline = []
        baseline_trades_h = baseline_metrics.get("trades_per_hour", 102)
        baseline_hold_sec = baseline_metrics.get("avg_hold_sec", 33)
        baseline_cost_bps = baseline_metrics.get("cost_bps_on_turnover", 2.5)
        baseline_pnl_trade = baseline_metrics.get("pnl_per_trade", -1.07)
        baseline_win_rate = baseline_metrics.get("win_rate_trades", 0.037)
        
        if hold_sec >= baseline_hold_sec * 1.5:  # ↑50%
            vs_baseline.append("持仓↑")
        if cost_bps <= baseline_cost_bps * 0.7:  # ↓30%
            vs_baseline.append("成本↓")
        if win_rate >= baseline_win_rate * 1.2:  # ↑20%
            vs_baseline.append("胜率↑")
        if pnl_trade > baseline_pnl_trade:
            vs_baseline.append("收益↑")
        
        vs_str = ", ".join(vs_baseline) if vs_baseline else "-"
        
        report_lines.append(
            f"| {result['exp_id']} | {result['exp_name']} | ✅ | "
            f"{trades_h:.1f} | {hold_sec:.1f}s | {cost_bps:.2f}bps | "
            f"${pnl_trade:.2f} | {win_rate:.2%} | {vs_str} |"
        )
    
    # 验收标准检查
    report_lines.extend([
        "",
        "## 验收标准检查",
        "",
    ])
    
    criteria = matrix.get("acceptance_criteria", {})
    for criterion, threshold in criteria.items():
        report_lines.append(f"- **{criterion}**: {threshold}")
    
    # 找出最优组合
    successful_results = [r for r in results if r.get("success")]
    if successful_results:
        report_lines.extend([
            "",
            "## 最优组合推荐",
            "",
        ])
        
        # 按综合评分排序（简单加权）
        def score_result(result):
            indicators = result.get("key_indicators", {})
            hold_sec = indicators.get("avg_hold_sec", 0)
            cost_bps = indicators.get("cost_bps_on_turnover", 0)
            win_rate = indicators.get("win_rate_trades", 0)
            pnl_trade = indicators.get("pnl_per_trade", 0)
            
            # 简单评分：持仓时间权重0.3，成本降低权重0.3，胜率权重0.2，收益权重0.2
            score = (
                (hold_sec / 100.0) * 0.3 +  # 持仓时间（归一化到100s）
                (1.0 - cost_bps / 5.0) * 0.3 +  # 成本降低（归一化到5bps）
                win_rate * 0.2 +  # 胜率
                max(0, pnl_trade + 2.0) / 4.0 * 0.2  # 收益（归一化-2到+2）
            )
            return score
        
        sorted_results = sorted(successful_results, key=score_result, reverse=True)
        
        for i, result in enumerate(sorted_results[:3], 1):
            indicators = result.get("key_indicators", {})
            report_lines.append(
                f"{i}. **{result['exp_name']}** ({result['exp_id']})\n"
                f"   - trades/h: {indicators.get('trades_per_hour', 0):.1f}\n"
                f"   - avg_hold_sec: {indicators.get('avg_hold_sec', 0):.1f}s\n"
                f"   - cost_bps: {indicators.get('cost_bps_on_turnover', 0):.2f}bps\n"
                f"   - pnl/trade: ${indicators.get('pnl_per_trade', 0):.2f}\n"
                f"   - win_rate: {indicators.get('win_rate_trades', 0):.2%}\n"
            )
    
    # 保存报告
    report_file = output_dir / "comparison_report.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    
    logger.info(f"对比报告已保存: {report_file}")


if __name__ == "__main__":
    main()

