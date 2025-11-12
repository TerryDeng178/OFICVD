#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shadow 24h Continuous Monitoring Script

24小时连续观测Shadow比对结果，分时段（亚盘/欧盘/美盘）检查parity比率
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp.strategy_server.risk import get_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class Shadow24hMonitor:
    """Shadow 24h连续观测器"""
    
    def __init__(self, start_time: str, duration: str, output_path: str):
        """初始化观测器
        
        Args:
            start_time: 开始时间（ISO格式，如 "2025-11-13T00:00:00"）
            duration: 持续时间（如 "24h", "12h"）
            output_path: 输出文件路径
        """
        self.start_time = datetime.fromisoformat(start_time)
        self.duration = self._parse_duration(duration)
        self.end_time = self.start_time + self.duration
        self.output_path = Path(output_path)
        
        # 时段定义（UTC+8）
        self.time_slots = {
            "asia": (9, 17),   # 亚盘：09:00-17:00
            "europe": (14, 22), # 欧盘：14:00-22:00
            "us": (21, 5),      # 美盘：21:00-05:00（跨日）
        }
        
        # 观测结果
        self.observations: List[Dict] = []
    
    def _parse_duration(self, duration: str) -> timedelta:
        """解析持续时间
        
        Args:
            duration: 持续时间字符串（如 "24h", "12h", "1h"）
            
        Returns:
            timedelta对象
        """
        if duration.endswith("h"):
            hours = int(duration[:-1])
            return timedelta(hours=hours)
        elif duration.endswith("m"):
            minutes = int(duration[:-1])
            return timedelta(minutes=minutes)
        else:
            raise ValueError(f"Invalid duration format: {duration}")
    
    def _get_time_slot(self, dt: datetime) -> str:
        """获取当前时段
        
        Args:
            dt: 当前时间
            
        Returns:
            时段名称（asia/europe/us）
        """
        hour = dt.hour
        
        # 亚盘
        if 9 <= hour < 17:
            return "asia"
        # 欧盘
        elif 14 <= hour < 22:
            return "europe"
        # 美盘（跨日）
        elif hour >= 21 or hour < 5:
            return "us"
        else:
            return "other"
    
    def _collect_metrics(self) -> Dict:
        """收集当前指标
        
        Returns:
            指标字典
        """
        metrics = get_metrics()
        
        return {
            "parity_ratio": metrics.get_shadow_parity_ratio(),
            "alert_level": metrics.get_shadow_alert_level(),
            "latency_stats": metrics.get_latency_seconds_stats(),
            "precheck_total": metrics.get_precheck_total(),
        }
    
    def run(self):
        """运行24小时连续观测"""
        logger.info("=" * 80)
        logger.info("Shadow 24h Continuous Monitoring")
        logger.info("=" * 80)
        logger.info(f"Start time: {self.start_time}")
        logger.info(f"End time: {self.end_time}")
        logger.info(f"Duration: {self.duration}")
        
        current_time = datetime.now()
        
        # 如果指定了开始时间，等待到开始时间
        if current_time < self.start_time:
            wait_seconds = (self.start_time - current_time).total_seconds()
            logger.info(f"Waiting {wait_seconds:.0f} seconds until start time...")
            time.sleep(wait_seconds)
        
        # 开始观测
        check_interval = 60  # 每分钟检查一次
        last_slot = None
        
        while datetime.now() < self.end_time:
            current_time = datetime.now()
            current_slot = self._get_time_slot(current_time)
            
            # 时段切换时记录
            if current_slot != last_slot:
                logger.info(f"Time slot changed: {last_slot} -> {current_slot}")
                last_slot = current_slot
            
            # 收集指标
            metrics = self._collect_metrics()
            
            observation = {
                "timestamp": current_time.isoformat(),
                "time_slot": current_slot,
                "parity_ratio": metrics["parity_ratio"],
                "alert_level": metrics["alert_level"],
                "latency_p95": metrics["latency_stats"].get("p95", 0.0),
                "precheck_count": sum(metrics["precheck_total"].values()),
            }
            
            self.observations.append(observation)
            
            # 检查告警条件
            if metrics["parity_ratio"] < 0.99:
                logger.warning(
                    f"[{current_slot}] Parity ratio below 99%: {metrics['parity_ratio']:.4f}"
                )
            
            if metrics["alert_level"] != "ok":
                logger.warning(
                    f"[{current_slot}] Alert level: {metrics['alert_level']}"
                )
            
            # 等待下一次检查
            time.sleep(check_interval)
        
        # 生成报告
        self._generate_report()
    
    def _generate_report(self):
        """生成观测报告"""
        logger.info("\n" + "=" * 80)
        logger.info("Generating Shadow 24h Report")
        logger.info("=" * 80)
        
        # 按时段统计
        slot_stats = {}
        for obs in self.observations:
            slot = obs["time_slot"]
            if slot not in slot_stats:
                slot_stats[slot] = {
                    "count": 0,
                    "parity_sum": 0.0,
                    "min_parity": 1.0,
                    "max_parity": 0.0,
                    "alert_count": 0,
                }
            
            stats = slot_stats[slot]
            stats["count"] += 1
            stats["parity_sum"] += obs["parity_ratio"]
            stats["min_parity"] = min(stats["min_parity"], obs["parity_ratio"])
            stats["max_parity"] = max(stats["max_parity"], obs["parity_ratio"])
            
            if obs["alert_level"] != "ok":
                stats["alert_count"] += 1
        
        # 计算平均parity
        for slot, stats in slot_stats.items():
            if stats["count"] > 0:
                stats["avg_parity"] = stats["parity_sum"] / stats["count"]
        
        # 生成报告
        report = {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_hours": self.duration.total_seconds() / 3600,
            "total_observations": len(self.observations),
            "slot_statistics": slot_stats,
            "observations": self.observations,
        }
        
        # 保存报告
        with self.output_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Report saved to: {self.output_path}")
        
        # 打印摘要
        logger.info("\n" + "=" * 80)
        logger.info("Shadow 24h Report Summary")
        logger.info("=" * 80)
        for slot, stats in slot_stats.items():
            logger.info(
                f"[{slot}] Count: {stats['count']}, "
                f"Avg Parity: {stats.get('avg_parity', 0):.4f}, "
                f"Min: {stats['min_parity']:.4f}, "
                f"Max: {stats['max_parity']:.4f}, "
                f"Alerts: {stats['alert_count']}"
            )


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Shadow 24h Continuous Monitoring")
    parser.add_argument(
        "--start-time",
        type=str,
        default=datetime.now().isoformat(),
        help="Start time (ISO format, e.g., '2025-11-13T00:00:00')",
    )
    parser.add_argument(
        "--duration",
        type=str,
        default="24h",
        help="Duration (e.g., '24h', '12h', '1h')",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./runtime/shadow_24h_report.json",
        help="Output file path",
    )
    
    args = parser.parse_args()
    
    monitor = Shadow24hMonitor(args.start_time, args.duration, args.output)
    monitor.run()


if __name__ == "__main__":
    main()

