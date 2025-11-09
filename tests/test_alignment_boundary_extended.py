# -*- coding: utf-8 -*-
"""P1.4: 边界对齐回归测试（扩充分层用例：符号×数据源×时间窗）

将已有的关键用例分层到：符号×数据源×时间窗，作为小样本多组合的回归集合
"""
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from alpha_core.backtest import DataAligner, DataReader


class TestAlignmentBoundaryExtended:
    """P1.4: 边界对齐回归测试（扩充分层用例）"""
    
    @pytest.fixture
    def temp_dir(self, tmp_path):
        """创建临时数据目录"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        return data_dir
    
    def _create_test_data(self, data_dir: Path, symbol: str, source: str, start_ts: int, num_seconds: int):
        """创建测试数据文件
        
        Args:
            data_dir: 数据目录
            symbol: 交易对符号
            source: 数据源（ready/preview）
            start_ts: 起始时间戳（秒）
            num_seconds: 秒数
        """
        # 创建price和orderbook目录（DataReader期望的结构）
        price_dir = data_dir / source / "price"
        price_dir.mkdir(parents=True, exist_ok=True)
        ob_dir = data_dir / source / "orderbook"
        ob_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建Price JSONL文件
        price_file = price_dir / f"{symbol}_{start_ts}.jsonl"
        with price_file.open("w", encoding="utf-8") as f:
            for i in range(num_seconds):
                ts_ms = (start_ts + i) * 1000
                mid_price = 50000.0 + (i * 0.1)  # 模拟价格变化
                
                price_row = {
                    "symbol": symbol,
                    "ts_ms": ts_ms,
                    "mid": mid_price,
                    "ofi_z": 0.5 if i % 2 == 0 else -0.5,
                    "cvd_z": 0.3 if i % 3 == 0 else -0.3,
                    "consistency": 0.8,
                    "warmup": False,
                }
                f.write(json.dumps(price_row, ensure_ascii=False) + "\n")
        
        # 创建Orderbook JSONL文件
        ob_file = ob_dir / f"{symbol}_{start_ts}.jsonl"
        with ob_file.open("w", encoding="utf-8") as f:
            for i in range(num_seconds):
                ts_ms = (start_ts + i) * 1000
                mid_price = 50000.0 + (i * 0.1)
                
                ob_row = {
                    "symbol": symbol,
                    "ts_ms": ts_ms,
                    "best_bid": mid_price * 0.9999,
                    "best_ask": mid_price * 1.0001,
                    "consistency": 0.8,
                    "warmup": False,
                }
                f.write(json.dumps(ob_row, ensure_ascii=False) + "\n")
        
        return price_file, ob_file
    
    @pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT"])
    @pytest.mark.parametrize("source", ["ready", "preview"])
    @pytest.mark.parametrize("time_window_minutes", [5, 30, 60])
    def test_alignment_consistency(self, temp_dir, symbol, source, time_window_minutes):
        """P1.4: 测试对齐一致性（符号×数据源×时间窗）"""
        # 创建测试数据
        start_ts = int(datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp())
        num_seconds = time_window_minutes * 60
        
        self._create_test_data(temp_dir, symbol, source, start_ts, num_seconds)
        
        # 创建DataReader和DataAligner
        reader = DataReader(
            input_dir=temp_dir,
            kinds=["features"],
            source_priority=[source],
        )
        
        aligner = DataAligner(max_lag_ms=5000)
        
        # 读取并对齐数据
        price_iter = reader._read_data("price")
        ob_iter = reader._read_data("orderbook")
        
        aligned_features = list(aligner.align_to_seconds(price_iter, ob_iter))
        
        # 验证对齐结果
        assert len(aligned_features) > 0, f"No aligned features for {symbol}/{source}/{time_window_minutes}min"
        
        # 验证关键字段存在
        for feat in aligned_features:
            assert "symbol" in feat
            assert "ts_ms" in feat
            assert "mid" in feat
            assert "return_1s" in feat
            assert "lag_ms_price" in feat
            assert "lag_ms_orderbook" in feat
            assert "scenario_2x2" in feat
            assert "is_gap_second" in feat
        
        # 验证没有重复的row_id（如果有）
        ts_list = [f["ts_ms"] for f in aligned_features]
        assert len(ts_list) == len(set(ts_list)), f"Duplicate timestamps found for {symbol}/{source}/{time_window_minutes}min"
        
        # 验证对齐统计
        assert aligner.stats["aligned_rows"] > 0
    
    def test_extreme_gap_scenario(self, temp_dir):
        """P1.4: 极端场景 - 高丢包（gap-second连续命中）"""
        symbol = "BTCUSDT"
        source = "ready"
        
        # 创建有大量gap的数据（每隔10秒一个数据点）
        start_ts = int(datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp())
        
        features_dir = temp_dir / source / "features"
        features_dir.mkdir(parents=True, exist_ok=True)
        
        jsonl_file = features_dir / f"{symbol}_gap.jsonl"
        
        with jsonl_file.open("w", encoding="utf-8") as f:
            for i in range(0, 60, 10):  # 每10秒一个点
                ts_ms = (start_ts + i) * 1000
                mid_price = 50000.0 + (i * 0.1)
                
                price_row = {
                    "symbol": symbol,
                    "ts_ms": ts_ms,
                    "mid": mid_price,
                    "ofi_z": 0.5,
                    "cvd_z": 0.3,
                    "consistency": 0.8,
                    "warmup": False,
                }
                f.write(json.dumps(price_row, ensure_ascii=False) + "\n")
                
                ob_row = {
                    "symbol": symbol,
                    "ts_ms": ts_ms,
                    "best_bid": mid_price * 0.9999,
                    "best_ask": mid_price * 1.0001,
                    "consistency": 0.8,
                    "warmup": False,
                }
                f.write(json.dumps(ob_row, ensure_ascii=False) + "\n")
        
        # 对齐数据
        reader = DataReader(
            input_dir=temp_dir,
            kinds=["features"],
            source_priority=[source],
        )
        
        aligner = DataAligner(max_lag_ms=5000)
        
        price_iter = reader.read("price")
        ob_iter = reader.read("orderbook")
        
        aligned_features = list(aligner.align_to_seconds(price_iter, ob_iter))
        
        # 验证gap秒被正确标记
        gap_count = sum(1 for f in aligned_features if f.get("is_gap_second", 0) == 1)
        assert gap_count > 0, "Expected gap seconds to be marked"
        
        # 验证return_1s计算的稳定性（即使有gap）
        for i in range(1, len(aligned_features)):
            feat = aligned_features[i]
            prev_feat = aligned_features[i-1]
            
            # return_1s应该能处理gap情况
            if feat.get("is_gap_second", 0) == 0:
                # 非gap秒，return_1s应该合理
                assert isinstance(feat.get("return_1s"), (int, float))
    
    def test_extreme_spread_volatility(self, temp_dir):
        """P1.4: 极端场景 - 价差骤宽 + 高波动（scenario_2x2连续跳档）"""
        symbol = "BTCUSDT"
        source = "ready"
        
        start_ts = int(datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp())
        
        features_dir = temp_dir / source / "features"
        features_dir.mkdir(parents=True, exist_ok=True)
        
        jsonl_file = features_dir / f"{symbol}_volatile.jsonl"
        
        with jsonl_file.open("w", encoding="utf-8") as f:
            for i in range(60):
                ts_ms = (start_ts + i) * 1000
                
                # 模拟高波动：价格大幅跳跃
                if i % 10 < 5:
                    mid_price = 50000.0 + (i * 10.0)  # 大幅上涨
                    spread_bps = 5.0  # 宽价差
                else:
                    mid_price = 50000.0 - (i * 10.0)  # 大幅下跌
                    spread_bps = 10.0  # 更宽价差
                
                price_row = {
                    "symbol": symbol,
                    "ts_ms": ts_ms,
                    "mid": mid_price,
                    "ofi_z": 2.0 if i % 2 == 0 else -2.0,  # 高OFI
                    "cvd_z": 1.5 if i % 3 == 0 else -1.5,  # 高CVD
                    "consistency": 0.5,  # 低一致性
                    "warmup": False,
                }
                f.write(json.dumps(price_row, ensure_ascii=False) + "\n")
                
                ob_row = {
                    "symbol": symbol,
                    "ts_ms": ts_ms,
                    "best_bid": mid_price * (1 - spread_bps / 20000),
                    "best_ask": mid_price * (1 + spread_bps / 20000),
                    "consistency": 0.5,
                    "warmup": False,
                }
                f.write(json.dumps(ob_row, ensure_ascii=False) + "\n")
        
        # 对齐数据
        reader = DataReader(
            input_dir=temp_dir,
            kinds=["features"],
            source_priority=[source],
        )
        
        aligner = DataAligner(max_lag_ms=5000)
        
        price_iter = reader.read("price")
        ob_iter = reader.read("orderbook")
        
        aligned_features = list(aligner.align_to_seconds(price_iter, ob_iter))
        
        # 验证scenario_2x2正确标记高波动场景
        scenarios = [f.get("scenario_2x2") for f in aligned_features]
        assert "Q_H" in scenarios or "A_H" in scenarios, "Expected high volatility scenarios"
        
        # 验证return_1s和lag标记的稳定性
        for feat in aligned_features:
            assert isinstance(feat.get("return_1s"), (int, float))
            assert isinstance(feat.get("lag_ms_price"), (int, float))
            assert isinstance(feat.get("lag_ms_orderbook"), (int, float))
    
    def test_reader_source_priority_multi_symbol(self, temp_dir):
        """P1.4: Reader源优先级 - 多symbol验证"""
        symbols = ["BTCUSDT", "ETHUSDT"]
        source = "ready"
        
        # 为每个symbol创建数据
        start_ts = int(datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp())
        
        for symbol in symbols:
            self._create_test_data(temp_dir, symbol, source, start_ts, 60)
        
        # 创建Reader（优先ready）
        reader = DataReader(
            input_dir=temp_dir,
            kinds=["features"],
            source_priority=["ready", "preview"],
        )
        
        # 读取所有symbol的数据
        price_iter = reader._read_data("price")
        ob_iter = reader._read_data("orderbook")
        
        # 验证数据按source_priority顺序读取
        price_data = list(price_iter)
        ob_data = list(ob_iter)
        
        # 验证所有symbol的数据都被读取
        symbols_found = set(d.get("symbol") for d in price_data)
        assert symbols_found == set(symbols), f"Expected symbols {symbols}, got {symbols_found}"

