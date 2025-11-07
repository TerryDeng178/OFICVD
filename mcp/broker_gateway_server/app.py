# -*- coding: utf-8 -*-
"""
Broker Gateway MCP Server

交易所网关服务器：幂等键 + 订单状态机
Mock 模式：模拟订单执行
"""

import argparse
import json
import logging
import random
import sys
import time
from pathlib import Path
from typing import Dict, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


class MockBroker:
    """Mock Broker Gateway - 模拟订单执行"""
    
    def __init__(self, output_file: Path, sample_rate: float = 0.2):
        self.output_file = output_file
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.order_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sample_rate = sample_rate  # P0: Broker 抽样率参数
        
        logger.info(f"Mock Broker initialized, output: {output_file}, sample_rate: {sample_rate}")
    
    def process_signal(self, signal: Dict) -> Optional[Dict]:
        """处理信号，生成模拟订单"""
        # 解析信号类型：signal_type 可能是 "strong_buy", "buy", "strong_sell", "sell", "pending", "neutral"
        signal_type = signal.get("signal_type", "").lower()
        confirm = signal.get("confirm", False)
        symbol = signal.get("symbol", "")
        ts_ms = signal.get("ts_ms", 0)
        score = signal.get("score", 0.0)
        
        # 只处理确认的信号（confirm=True）
        if not confirm:
            return None
        
        # 解析 side 和 strength
        side = None
        strength = "normal"
        
        if "strong_buy" in signal_type:
            side = "BUY"
            strength = "STRONG"
        elif "buy" in signal_type:
            side = "BUY"
            strength = "NORMAL"
        elif "strong_sell" in signal_type:
            side = "SELL"
            strength = "STRONG"
        elif "sell" in signal_type:
            side = "SELL"
            strength = "NORMAL"
        else:
            # 无法解析，跳过
            return None
        
        # P0: Broker 抽样率参数化
        should_order = False
        if strength == "STRONG":
            should_order = True
        else:
            # 普通信号：按 sample_rate 概率下单
            should_order = (random.random() < self.sample_rate)
        
        if not should_order:
            return None
        
        # 生成模拟订单
        order = {
            "order_id": f"MOCK_{self.order_count:06d}",
            "symbol": symbol,
            "side": side,
            "strength": strength,
            "signal_type": signal_type,
            "signal_score": score,
            "signal_ts_ms": ts_ms,
            "order_ts_ms": int(time.time() * 1000),
            "status": "FILLED",  # Mock 模式直接成交
            "filled_qty": 0.001,  # Mock 数量
            "filled_price": 50000.0,  # Mock 价格（实际应从市场数据获取）
            "fee": 0.0001
        }
        
        self.order_count += 1
        if side == "BUY":
            self.buy_count += 1
        elif side == "SELL":
            self.sell_count += 1
        
        # 写入文件
        try:
            with self.output_file.open("a", encoding="utf-8", newline="") as fp:
                fp.write(json.dumps(order, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"写入订单失败: {e}")
        
        return order


def watch_signals(signal_source: Path, broker: MockBroker, check_interval: float = 1.0):
    """监听信号文件，处理信号"""
    logger.info(f"开始监听信号: {signal_source}")
    
    if signal_source.is_dir():
        # 目录模式：监听所有 JSONL 文件
        watched_files = set()
        last_positions = {}
        
        while True:
            try:
                # 查找新的或更新的文件
                jsonl_files = sorted(signal_source.rglob("*.jsonl"))
                
                for jsonl_file in jsonl_files:
                    file_key = str(jsonl_file)
                    
                    if file_key not in watched_files:
                        watched_files.add(file_key)
                        last_positions[file_key] = 0
                        logger.info(f"发现新文件: {jsonl_file}")
                    
                    # 读取新内容
                    try:
                        with jsonl_file.open("r", encoding="utf-8") as fp:
                            fp.seek(last_positions[file_key])
                            new_lines = fp.readlines()
                            
                            for line in new_lines:
                                line = line.strip()
                                if not line:
                                    continue
                                
                                try:
                                    signal = json.loads(line)
                                    broker.process_signal(signal)
                                except json.JSONDecodeError:
                                    continue
                            
                            last_positions[file_key] = fp.tell()
                    except Exception as e:
                        logger.debug(f"读取文件失败 {jsonl_file}: {e}")
                
                time.sleep(check_interval)
            except KeyboardInterrupt:
                logger.info("收到中断信号，停止监听")
                break
            except Exception as e:
                logger.error(f"监听出错: {e}", exc_info=True)
                time.sleep(check_interval)
    else:
        # 文件模式：一次性处理
        logger.info(f"处理信号文件: {signal_source}")
        try:
            with signal_source.open("r", encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        signal = json.loads(line)
                        broker.process_signal(signal)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"处理信号文件失败: {e}")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Broker Gateway MCP Server (Mock)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m mcp.broker_gateway_server.app --mock 1
  python -m mcp.broker_gateway_server.app --mock 1 --signal-dir ./runtime/ready/signal --output ./runtime/mock_orders.jsonl
        """
    )
    
    parser.add_argument(
        "--mock",
        type=int,
        default=0,
        help="Mock 模式（1=启用，0=禁用，默认: 0）"
    )
    
    parser.add_argument(
        "--signal-dir",
        type=str,
        default="./runtime/ready/signal",
        help="信号目录（默认: ./runtime/ready/signal）"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default="./runtime/mock_orders.jsonl",
        help="订单输出文件（默认: ./runtime/mock_orders.jsonl）"
    )
    
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="随机数种子（默认: 42，用于可复现的抽样）"
    )
    
    parser.add_argument(
        "--sample_rate",
        type=float,
        default=0.2,
        help="普通信号抽样率（默认: 0.2，即 1/5 概率下单）"
    )
    
    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()
    
    if args.mock != 1:
        logger.error("当前仅支持 Mock 模式，请使用 --mock 1")
        return 1
    
    # 设置随机数种子（用于可复现的抽样）
    random.seed(args.seed)
    logger.info(f"随机数种子已设置: {args.seed}, 抽样率: {args.sample_rate}")
    
    # 确定项目根目录
    project_root = Path(__file__).resolve().parents[2]
    signal_source = project_root / args.signal_dir
    output_file = project_root / args.output
    
    # P0: 创建 Mock Broker（带抽样率参数）
    broker = MockBroker(output_file, sample_rate=args.sample_rate)
    
    logger.info("Mock Broker started")
    logger.info(f"  信号源: {signal_source}")
    logger.info(f"  订单输出: {output_file}")
    
    try:
        # 监听信号
        watch_signals(signal_source, broker, check_interval=1.0)
    except KeyboardInterrupt:
        logger.info("收到中断信号，优雅退出")
    except Exception as e:
        logger.exception("程序异常退出")
        return 1
    
    logger.info(f"Mock Broker 统计: 总订单={broker.order_count}, 买入={broker.buy_count}, 卖出={broker.sell_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
