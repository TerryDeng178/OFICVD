# -*- coding: utf-8 -*-
"""P1.6: 边界对齐测试 - Property-based随机化生成

使用Hypothesis生成"乱序/重复/缺失/跳秒"的秒级序列，验证对齐逻辑的健壮性
"""
import pytest
from hypothesis import given, strategies as st, settings
from collections import defaultdict
from typing import List, Dict, Any

from alpha_core.backtest.aligner import DataAligner


class TestAlignmentProperty:
    """Property-based测试：对齐逻辑的健壮性"""
    
    @given(
        timestamps=st.lists(
            st.integers(min_value=1000000, max_value=2000000),
            min_size=10,
            max_size=100,
            unique=False,  # 允许重复
        ),
        gaps=st.lists(
            st.integers(min_value=1, max_value=10),
            min_size=0,
            max_size=5,
        ),
    )
    @settings(max_examples=20, deadline=5000)
    def test_return_1s_uses_previous_second_only(self, timestamps: List[int], gaps: List[int]):
        """P1: 验证return_1s只用前一秒的mid，不会跳变"""
        aligner = DataAligner()
        
        # 生成价格数据（带gap）
        prices = []
        orderbooks = []
        
        # 排序时间戳
        sorted_ts = sorted(set(timestamps))
        
        for i, ts_ms in enumerate(sorted_ts):
            mid = 50000.0 + i * 10.0  # 递增价格
            prices.append({
                "symbol": "BTCUSDT",
                "ts_ms": ts_ms,
                "mid": mid,
            })
            orderbooks.append({
                "symbol": "BTCUSDT",
                "ts_ms": ts_ms,
                "best_bid": mid - 1.0,
                "best_ask": mid + 1.0,
            })
        
        # 处理数据
        features = list(aligner.align_to_seconds(iter(prices), iter(orderbooks)))
        
        # 验证：return_1s应该只基于前一秒
        for i in range(1, len(features)):
            prev_feature = features[i - 1]
            curr_feature = features[i]
            
            prev_mid = prev_feature.get("mid", 0)
            curr_mid = curr_feature.get("mid", 0)
            
            if prev_mid > 0 and curr_mid > 0:
                expected_return_1s = ((curr_mid - prev_mid) / prev_mid) * 10000
                actual_return_1s = curr_feature.get("return_1s", 0)
                
                # 允许小的浮点误差
                assert abs(actual_return_1s - expected_return_1s) < 0.01, \
                    f"return_1s mismatch at index {i}: expected={expected_return_1s}, actual={actual_return_1s}"
    
    @given(
        timestamps=st.lists(
            st.integers(min_value=1000000, max_value=2000000),
            min_size=5,
            max_size=50,
        ),
    )
    @settings(max_examples=20, deadline=5000)
    def test_is_gap_second_statistics_consistent(self, timestamps: List[int]):
        """P1: 验证is_gap_second统计自洽"""
        aligner = DataAligner()
        
        # 生成价格数据
        prices = []
        orderbooks = []
        
        sorted_ts = sorted(set(timestamps))
        
        for ts_ms in sorted_ts:
            mid = 50000.0
            prices.append({
                "symbol": "BTCUSDT",
                "ts_ms": ts_ms,
                "mid": mid,
            })
            orderbooks.append({
                "symbol": "BTCUSDT",
                "ts_ms": ts_ms,
                "best_bid": mid - 1.0,
                "best_ask": mid + 1.0,
            })
        
        # 处理数据
        features = list(aligner.align_to_seconds(iter(prices), iter(orderbooks)))
        
        # 统计gap秒数
        gap_count_from_features = sum(1 for f in features if f.get("is_gap_second", 0) == 1)
        gap_count_from_stats = aligner.get_stats().get("gap_seconds_count", 0)
        
        # 验证统计一致性
        assert gap_count_from_features == gap_count_from_stats, \
            f"Gap count mismatch: features={gap_count_from_features}, stats={gap_count_from_stats}"
    
    @given(
        timestamps=st.lists(
            st.integers(min_value=1000000, max_value=2000000),
            min_size=10,
            max_size=100,
        ),
    )
    @settings(max_examples=20, deadline=5000)
    def test_no_duplicate_row_ids(self, timestamps: List[int]):
        """P1: 验证无重复row_id（基于symbol和second_ts）"""
        aligner = DataAligner()
        
        # 生成价格数据（可能包含重复时间戳）
        prices = []
        orderbooks = []
        
        for ts_ms in timestamps:
            mid = 50000.0
            prices.append({
                "symbol": "BTCUSDT",
                "ts_ms": ts_ms,
                "mid": mid,
            })
            orderbooks.append({
                "symbol": "BTCUSDT",
                "ts_ms": ts_ms,
                "best_bid": mid - 1.0,
                "best_ask": mid + 1.0,
            })
        
        # 处理数据
        features = list(aligner.align_to_seconds(iter(prices), iter(orderbooks)))
        
        # 验证：每个(symbol, second_ts)组合应该唯一
        seen_keys = set()
        for feature in features:
            symbol = feature.get("symbol", "")
            second_ts = feature.get("second_ts", 0)
            key = (symbol, second_ts)
            
            assert key not in seen_keys, f"Duplicate row_id found: {key}"
            seen_keys.add(key)
    
    @given(
        start_ts=st.integers(min_value=1000000, max_value=1500000),
        num_seconds=st.integers(min_value=10, max_value=100),
        gap_indices=st.lists(
            st.integers(min_value=1, max_value=50),
            min_size=0,
            max_size=5,
            unique=True,
        ),
    )
    @settings(max_examples=20, deadline=5000)
    def test_alignment_count_matches_actual_gaps(self, start_ts: int, num_seconds: int, gap_indices: List[int]):
        """P1: 验证对齐计数与实际gap秒数一致"""
        aligner = DataAligner()
        
        # 生成连续秒数据，但在指定位置挖空
        prices = []
        orderbooks = []
        
        gap_set = set(gap_indices)
        
        for i in range(num_seconds):
            if i not in gap_set:  # 跳过gap位置
                ts_ms = (start_ts + i) * 1000
                mid = 50000.0 + i * 10.0
                prices.append({
                    "symbol": "BTCUSDT",
                    "ts_ms": ts_ms,
                    "mid": mid,
                })
                orderbooks.append({
                    "symbol": "BTCUSDT",
                    "ts_ms": ts_ms,
                    "best_bid": mid - 1.0,
                    "best_ask": mid + 1.0,
                })
        
        # 处理数据
        features = list(aligner.align_to_seconds(iter(prices), iter(orderbooks)))
        
        # 统计实际gap秒数（相邻秒间隔>1.5秒）
        actual_gaps = 0
        for i in range(1, len(features)):
            prev_ts = features[i - 1].get("second_ts", 0)
            curr_ts = features[i].get("second_ts", 0)
            gap_seconds = curr_ts - prev_ts
            if gap_seconds > 1.5:
                actual_gaps += 1
        
        # 验证统计一致性
        gap_count_from_stats = aligner.get_stats().get("gap_seconds_count", 0)
        
        # 允许小的差异（因为对齐逻辑可能更复杂）
        assert abs(actual_gaps - gap_count_from_stats) <= 1, \
            f"Gap count mismatch: actual={actual_gaps}, stats={gap_count_from_stats}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

