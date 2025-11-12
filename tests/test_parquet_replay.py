# -*- coding: utf-8 -*-
"""Parquet Replay Consistency Tests

回放数据格式双通道：Parquet回放通路一致性检查（相同样本集，一致率≥99%）
"""

import json
import pytest
import tempfile
from pathlib import Path

try:
    import pandas as pd
    import pyarrow.parquet as pq
    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False

from mcp.strategy_server.risk import pre_order_check, OrderCtx, initialize_risk_manager, get_metrics, reset_metrics


@pytest.mark.skipif(not PARQUET_AVAILABLE, reason="Parquet libraries not available")
class TestParquetReplayConsistency:
    """测试Parquet回放通路一致性"""
    
    @pytest.fixture
    def risk_config(self):
        """风险配置"""
        return {
            "risk": {
                "enabled": True,
                "guards": {
                    "spread_bps_max": 8.0,
                    "lag_sec_cap": 1.5,
                    "activity_min_tpm": 10.0,
                },
                "position": {
                    "max_notional_usd": 20000.0,
                    "max_leverage": 5.0,
                    "symbol_limits": {},
                },
            }
        }
    
    @pytest.fixture
    def sample_data(self, tmp_path):
        """创建示例数据（JSONL和Parquet）"""
        # 创建100个测试样本
        samples = []
        for i in range(100):
            samples.append({
                "ts_ms": 1730790000456 + i * 1000,
                "symbol": "BTCUSDT",
                "side": "buy" if i % 2 == 0 else "sell",
                "order_type": "market",
                "qty": 0.1 + (i % 10) * 0.01,
                "price": 50000.0 + (i % 5) * 10.0,
                "spread_bps": 1.2 + (i % 5) * 0.5,
                "event_lag_sec": 0.04 + (i % 3) * 0.1,
                "activity_tpm": 15.0 + (i % 5) * 2.0,
            })
        
        # 写入JSONL
        jsonl_file = tmp_path / "signals.jsonl"
        with jsonl_file.open("w", encoding="utf-8") as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        
        # 写入Parquet
        parquet_file = tmp_path / "signals.parquet"
        df = pd.DataFrame(samples)
        df.to_parquet(parquet_file, engine="pyarrow", index=False)
        
        return {
            "jsonl": jsonl_file,
            "parquet": parquet_file,
            "samples": samples,
        }
    
    def _process_jsonl(self, jsonl_file, risk_config):
        """处理JSONL文件"""
        initialize_risk_manager(risk_config)
        reset_metrics()
        
        results = []
        with jsonl_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                sample = json.loads(line)
                
                order_ctx = OrderCtx(
                    symbol=sample["symbol"],
                    side=sample["side"],
                    order_type=sample["order_type"],
                    qty=sample["qty"],
                    price=sample["price"],
                    ts_ms=sample["ts_ms"],
                    guards={
                        "spread_bps": sample["spread_bps"],
                        "event_lag_sec": sample["event_lag_sec"],
                        "activity_tpm": sample["activity_tpm"],
                    },
                )
                
                decision = pre_order_check(order_ctx)
                results.append({
                    "ts_ms": sample["ts_ms"],
                    "passed": decision.passed,
                    "reason_codes": decision.reason_codes,
                })
        
        return results
    
    def _process_parquet(self, parquet_file, risk_config):
        """处理Parquet文件"""
        initialize_risk_manager(risk_config)
        reset_metrics()
        
        df = pd.read_parquet(parquet_file)
        results = []
        
        for _, row in df.iterrows():
            order_ctx = OrderCtx(
                symbol=row["symbol"],
                side=row["side"],
                order_type=row["order_type"],
                qty=float(row["qty"]),
                price=float(row["price"]),
                ts_ms=int(row["ts_ms"]),
                guards={
                    "spread_bps": float(row["spread_bps"]),
                    "event_lag_sec": float(row["event_lag_sec"]),
                    "activity_tpm": float(row["activity_tpm"]),
                },
            )
            
            decision = pre_order_check(order_ctx)
            results.append({
                "ts_ms": int(row["ts_ms"]),
                "passed": decision.passed,
                "reason_codes": decision.reason_codes,
            })
        
        return results
    
    def test_jsonl_vs_parquet_consistency(self, risk_config, sample_data):
        """测试JSONL和Parquet回放的一致性"""
        # 处理JSONL
        jsonl_results = self._process_jsonl(sample_data["jsonl"], risk_config)
        
        # 处理Parquet
        parquet_results = self._process_parquet(sample_data["parquet"], risk_config)
        
        # 按ts_ms排序
        jsonl_results.sort(key=lambda x: x["ts_ms"])
        parquet_results.sort(key=lambda x: x["ts_ms"])
        
        # 对比结果
        assert len(jsonl_results) == len(parquet_results)
        
        consistent_count = 0
        total_count = len(jsonl_results)
        
        for j, p in zip(jsonl_results, parquet_results):
            assert j["ts_ms"] == p["ts_ms"], "Timestamp mismatch"
            
            # 检查决策一致性
            if j["passed"] == p["passed"] and set(j["reason_codes"]) == set(p["reason_codes"]):
                consistent_count += 1
        
        consistency_ratio = consistent_count / total_count if total_count > 0 else 0.0
        
        # 验证一致率 ≥ 99%
        assert consistency_ratio >= 0.99, f"Consistency ratio {consistency_ratio:.4f} < 99%"
        
        # 验证指标统计一致
        jsonl_metrics = get_metrics()
        jsonl_latency_stats = jsonl_metrics.get_latency_seconds_stats()
        
        # 重新处理Parquet以获取指标
        initialize_risk_manager(risk_config)
        reset_metrics()
        self._process_parquet(sample_data["parquet"], risk_config)
        parquet_metrics = get_metrics()
        parquet_latency_stats = parquet_metrics.get_latency_seconds_stats()
        
        # 延迟统计应该相近（允许5%误差）
        jsonl_p95 = jsonl_latency_stats.get("p95", 0.0)
        parquet_p95 = parquet_latency_stats.get("p95", 0.0)
        if jsonl_p95 > 0:
            p95_diff_ratio = abs(jsonl_p95 - parquet_p95) / jsonl_p95
            assert p95_diff_ratio < 0.05, f"P95 latency difference {p95_diff_ratio:.4f} > 5%"

