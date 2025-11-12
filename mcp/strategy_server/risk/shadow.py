# -*- coding: utf-8 -*-
"""Shadow Comparison Module

影子对比：内联风控与legacy风控的比对
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

from .schemas import OrderCtx, RiskDecision
from .metrics import get_metrics

logger = logging.getLogger(__name__)


class ShadowComparator:
    """影子对比器"""
    
    def __init__(self, config: Dict, output_dir: Path):
        """初始化影子对比器
        
        Args:
            config: 配置字典
            output_dir: 输出目录
        """
        shadow_config = config.get("risk", {}).get("shadow_mode", {})
        self.enabled = shadow_config.get("compare_with_legacy", False)
        self.diff_alert = shadow_config.get("diff_alert", ">=1%")
        self.output_dir = output_dir
        self.output_file = output_dir / "risk_shadow.jsonl"
        
        # 统计信息
        self.total_checks = 0
        self.parity_count = 0
        self.diff_count = 0
    
    def compare_with_legacy(
        self,
        order_ctx: OrderCtx,
        inline_decision: RiskDecision,
        legacy_decision: Optional[Dict] = None
    ) -> Dict:
        """与legacy风控比对
        
        Args:
            order_ctx: 订单上下文
            inline_decision: 内联风控决策
            legacy_decision: legacy风控决策（可选，如果legacy服务不可用则为None）
            
        Returns:
            比对结果字典
        """
        if not self.enabled:
            return {
                "parity": True,
                "legacy_passed": None,
            }
        
        self.total_checks += 1
        
        # 如果legacy服务不可用，记录但不算不一致
        if legacy_decision is None:
            logger.warning("[RISK] Legacy risk service not available for shadow comparison")
            return {
                "parity": True,
                "legacy_passed": None,
            }
        
        legacy_passed = legacy_decision.get("allow", False)
        parity = (inline_decision.passed == legacy_passed)
        
        if parity:
            self.parity_count += 1
        else:
            self.diff_count += 1
        
        # 记录比对结果
        comparison_record = {
            "ts_ms": order_ctx.ts_ms,
            "symbol": order_ctx.symbol,
            "side": order_ctx.side,
            "inline_passed": inline_decision.passed,
            "legacy_passed": legacy_passed,
            "parity": parity,
            "inline_reasons": inline_decision.reason_codes,
            "legacy_reasons": legacy_decision.get("reason", []),
        }
        
        # 写入文件
        try:
            with self.output_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(comparison_record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"[RISK] Failed to write shadow comparison record: {e}")
        
        # 更新决策的shadow_compare字段
        inline_decision.shadow_compare = {
            "legacy_passed": legacy_passed,
            "parity": parity,
        }
        
        # 记录指标
        metrics = get_metrics()
        metrics.record_shadow_parity(parity)
        
        # 更新Shadow一致性告警（自动计算parity比率并更新告警级别）
        parity_ratio = metrics.get_shadow_parity_ratio()
        # 从配置中获取阈值（默认0.99，即99%）
        threshold = 0.99  # TODO: 从配置中读取 diff_alert 阈值
        metrics.update_shadow_alert(parity_ratio, threshold)
        
        return comparison_record
    
    def get_parity_ratio(self) -> float:
        """获取一致率
        
        Returns:
            一致率（0.0-1.0）
        """
        if self.total_checks == 0:
            return 1.0
        return self.parity_count / self.total_checks
    
    def generate_summary(self) -> Dict:
        """生成汇总报告
        
        Returns:
            汇总字典
        """
        parity_ratio = self.get_parity_ratio()
        
        summary = {
            "ts": datetime.utcnow().isoformat(),
            "total_checks": self.total_checks,
            "parity_count": self.parity_count,
            "diff_count": self.diff_count,
            "parity_ratio": parity_ratio,
        }
        
        # 检查是否超过阈值
        if self.diff_alert.startswith(">="):
            threshold = float(self.diff_alert[2:-1]) / 100.0
            if (1.0 - parity_ratio) >= threshold:
                logger.warning(
                    f"[RISK] Shadow comparison parity ratio {parity_ratio:.2%} "
                    f"below threshold {1.0 - threshold:.2%}"
                )
        
        return summary

