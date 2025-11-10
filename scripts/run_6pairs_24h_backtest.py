#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行6个交易对的24小时回测"""
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

def find_latest_date():
    """查找最新的数据日期"""
    preview_dir = Path("deploy/data/ofi_cvd/preview")
    if not preview_dir.exists():
        logger.error("preview目录不存在")
        return None
    
    dates = []
    for d in preview_dir.iterdir():
        if d.is_dir() and d.name.startswith("date="):
            dates.append(d.name.replace("date=", ""))
    
    if not dates:
        logger.error("未找到数据日期")
        return None
    
    latest_date = sorted(dates)[-1]
    logger.info(f"找到最新日期: {latest_date}")
    return latest_date

def find_available_symbols(date: str, limit: int = 6):
    """查找可用的交易对"""
    preview_dir = Path("deploy/data/ofi_cvd/preview")
    date_dir = preview_dir / f"date={date}"
    
    symbols = set()
    for hour_dir in date_dir.iterdir():
        if hour_dir.is_dir() and hour_dir.name.startswith("hour="):
            for symbol_dir in hour_dir.iterdir():
                if symbol_dir.is_dir() and symbol_dir.name.startswith("symbol="):
                    symbol = symbol_dir.name.split("=")[1].upper()
                    # 检查是否有features数据
                    kind_dir = symbol_dir / "kind=features"
                    if kind_dir.exists():
                        symbols.add(symbol)
    
    sorted_symbols = sorted(symbols)
    logger.info(f"找到 {len(sorted_symbols)} 个可用交易对: {sorted_symbols[:limit]}")
    return sorted_symbols[:limit]

def run_backtest(date: str, symbols: list, output_dir: Path):
    """运行回测"""
    symbols_str = ",".join(symbols)
    
    cmd = [
        sys.executable,
        "scripts/replay_harness.py",
        "--input", "deploy/data/ofi_cvd",
        "--date", date,
        "--symbols", symbols_str,
        "--kinds", "features",
        "--config", "config/backtest.yaml",
        "--output", str(output_dir)
    ]
    
    logger.info(f"运行回测命令: {' '.join(cmd)}")
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    
    if result.returncode != 0:
        logger.error(f"回测失败，退出码: {result.returncode}")
        logger.error(f"错误输出: {result.stderr[:500]}")
        return None
    
    logger.info("回测完成")
    return result.stdout

def main():
    """主函数"""
    logger.info("=" * 80)
    logger.info("6个交易对24小时回测")
    logger.info("=" * 80)
    
    # 查找最新日期
    date = find_latest_date()
    if not date:
        return 1
    
    # 查找可用交易对
    symbols = find_available_symbols(date, limit=6)
    if not symbols:
        logger.error("未找到可用交易对")
        return 1
    
    logger.info(f"选择的交易对: {symbols}")
    
    # 创建输出目录
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = Path(f"runtime/backtest/6pairs_24h_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 运行回测
    stdout = run_backtest(date, symbols, output_dir)
    if stdout is None:
        return 1
    
    # 保存回测信息
    backtest_info = {
        "date": date,
        "symbols": symbols,
        "output_dir": str(output_dir),
        "timestamp": timestamp,
        "duration_hours": 24,
    }
    
    info_file = output_dir / "backtest_info.json"
    with open(info_file, "w", encoding="utf-8") as f:
        json.dump(backtest_info, f, ensure_ascii=False, indent=2)
    
    logger.info(f"回测信息已保存: {info_file}")
    logger.info(f"输出目录: {output_dir}")
    
    # 查找实际的回测结果目录
    subdirs = list(output_dir.glob("backtest_*"))
    if subdirs:
        actual_output = subdirs[0]
        logger.info(f"实际结果目录: {actual_output}")
        
        # 检查关键文件
        trades_file = actual_output / "trades.jsonl"
        metrics_file = actual_output / "metrics.json"
        
        if trades_file.exists():
            with open(trades_file, "r", encoding="utf-8") as f:
                trade_count = sum(1 for line in f if line.strip())
            logger.info(f"交易数: {trade_count}")
        
        if metrics_file.exists():
            with open(metrics_file, "r", encoding="utf-8") as f:
                metrics = json.load(f)
            logger.info(f"总PnL: {metrics.get('total_pnl', 0):.2f}")
            logger.info(f"总交易数: {metrics.get('total_trades', 0)}")
    
    logger.info("=" * 80)
    logger.info("回测完成")
    logger.info("=" * 80)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

