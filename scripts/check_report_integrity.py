#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TASK-09: 验收脚本 - 检查报表完整性"""
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

def check_report_integrity(report_dir: Path) -> bool:
    """检查报表完整性
    
    Args:
        report_dir: 报表目录（包含summary.md和metrics.json）
    
    Returns:
        是否通过检查
    """
    logger.info("=" * 80)
    logger.info("检查报表完整性")
    logger.info("=" * 80)
    
    report_dir = Path(report_dir)
    if not report_dir.exists():
        logger.error(f"报表目录不存在: {report_dir}")
        return False
    
    checks = []
    
    # 检查1: summary.md存在
    summary_files = list(report_dir.glob("*_summary.md"))
    if summary_files:
        logger.info(f"[PASS] 找到报表文件: {summary_files[0].name}")
        checks.append(True)
    else:
        logger.error("[FAIL] 未找到summary.md文件")
        checks.append(False)
    
    # 检查2: metrics.json存在
    metrics_files = list(report_dir.glob("*_metrics.json"))
    if metrics_files:
        logger.info(f"[PASS] 找到metrics文件: {metrics_files[0].name}")
        checks.append(True)
        
        # 检查metrics.json内容
        with open(metrics_files[0], "r", encoding="utf-8") as f:
            metrics = json.load(f)
        
        # 检查必需字段
        required_fields = ["overall", "by_hour", "by_scenario", "by_symbol", "cost_breakdown"]
        missing_fields = [f for f in required_fields if f not in metrics]
        if missing_fields:
            logger.error(f"[FAIL] metrics.json缺少字段: {missing_fields}")
            checks.append(False)
        else:
            logger.info("[PASS] metrics.json字段完整")
            checks.append(True)
        
        # 检查by_hour覆盖24小时
        by_hour = metrics.get("by_hour", {})
        if len(by_hour) == 24:
            logger.info("[PASS] by_hour覆盖24小时")
            checks.append(True)
        else:
            logger.warning(f"[WARN] by_hour仅覆盖{len(by_hour)}小时")
            checks.append(True)  # 警告但不失败
        
        # 检查by_scenario非空
        by_scenario = metrics.get("by_scenario", {})
        if by_scenario:
            logger.info(f"[PASS] by_scenario包含{len(by_scenario)}个场景")
            checks.append(True)
        else:
            logger.error("[FAIL] by_scenario为空")
            checks.append(False)
        
        # 检查by_symbol非空
        by_symbol = metrics.get("by_symbol", {})
        if by_symbol:
            logger.info(f"[PASS] by_symbol包含{len(by_symbol)}个交易对")
            checks.append(True)
        else:
            logger.error("[FAIL] by_symbol为空")
            checks.append(False)
        
        # 检查cost_breakdown字段
        cost_breakdown = metrics.get("cost_breakdown", {})
        required_cost_fields = ["total_fee", "total_slippage", "total_cost"]
        missing_cost_fields = [f for f in required_cost_fields if f not in cost_breakdown]
        if missing_cost_fields:
            logger.error(f"[FAIL] cost_breakdown缺少字段: {missing_cost_fields}")
            checks.append(False)
        else:
            logger.info("[PASS] cost_breakdown字段完整")
            checks.append(True)
    else:
        logger.error("[FAIL] 未找到metrics.json文件")
        checks.append(False)
    
    # 检查3: 图表文件（可选）
    chart_files = list(report_dir.glob("fig_*.png"))
    if chart_files:
        logger.info(f"[PASS] 找到{len(chart_files)}个图表文件")
        checks.append(True)
    else:
        logger.warning("[WARN] 未找到图表文件（可选）")
        checks.append(True)  # 警告但不失败
    
    # 汇总
    passed = sum(checks)
    total = len(checks)
    
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"检查结果: {passed}/{total} 通过")
    logger.info("=" * 80)
    
    return all(checks)

def main():
    """主函数"""
    if len(sys.argv) < 2:
        logger.error("用法: python scripts/check_report_integrity.py <report_dir>")
        return 1
    
    report_dir = Path(sys.argv[1])
    
    success = check_report_integrity(report_dir)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())

