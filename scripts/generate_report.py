#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TASK-09: 生成复盘报表的CLI脚本"""
import argparse
import logging
import sys
from pathlib import Path

# Fix 2: 添加src路径到sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_core.report.summary import ReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="生成复盘报表")
    parser.add_argument(
        "--run",
        type=str,
        required=True,
        help="回测结果目录（包含backtest_*子目录）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="报表输出目录（默认：reports/daily/YYYYMMDD/）",
    )
    
    args = parser.parse_args()
    
    backtest_dir = Path(args.run)
    if not backtest_dir.exists():
        logger.error(f"回测目录不存在: {backtest_dir}")
        return 1
    
    output_dir = Path(args.output) if args.output else None
    
    logger.info("=" * 80)
    logger.info("生成复盘报表")
    logger.info("=" * 80)
    
    try:
        generator = ReportGenerator(backtest_dir, output_dir)
        report_file = generator.generate_report()
        
        if report_file:
            logger.info(f"报表已生成: {report_file}")
            logger.info(f"输出目录: {generator.output_dir}")
            return 0
        else:
            logger.error("报表生成失败")
            return 1
    except Exception as e:
        logger.error(f"生成报表时出错: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())

