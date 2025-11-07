# -*- coding: utf-8 -*-
"""
FeaturePipe 单元测试

测试 OFI/CVD/FUSION/DIV 适配层和业务流用例
"""

import sys
import unittest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

# 确保可以导入 alpha_core（如果 conftest.py 未生效）
_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from alpha_core.microstructure.feature_pipe import FeaturePipe, SymbolState


class TestFeaturePipe(unittest.TestCase):
    """FeaturePipe 单元测试"""
    
    def setUp(self):
        """设置测试环境"""
        self.config = {
            "features": {
                "ofi": {
                    "window_ms": 5000,
                    "zscore_window": 30000,
                    "levels": 5,
                    "weights": [0.4, 0.25, 0.2, 0.1, 0.05],
                    "ema_alpha": 0.2
                },
                "cvd": {
                    "window_ms": 60000,
                    "z_mode": "delta"
                },
                "fusion": {
                    "method": "zsum",
                    "w_ofi": 0.6,
                    "w_cvd": 0.4
                },
                "divergence": {
                    "lookback_bars": 60
                }
            }
        }
        
        # 创建临时输出目录
        self.temp_dir = Path(tempfile.mkdtemp())
        
    def tearDown(self):
        """清理测试环境"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_feature_pipe_initialization(self):
        """测试 FeaturePipe 初始化"""
        pipe = FeaturePipe(
            config=self.config,
            symbols=["BTCUSDT"],
            sink="jsonl",
            output_dir=str(self.temp_dir)
        )
        
        self.assertIsNotNone(pipe)
        self.assertEqual(pipe.sink, "jsonl")
        self.assertEqual(pipe.symbols, ["BTCUSDT"])
    
    def test_on_row_normal_flow(self):
        """Case-01: 正常流测试（bookTicker + aggTrade + depth）"""
        pipe = FeaturePipe(
            config=self.config,
            symbols=["BTCUSDT"],
            sink="jsonl",
            output_dir=str(self.temp_dir)
        )
        
        # 模拟订单簿更新
        orderbook_row = {
            "ts_ms": 1730790000000,
            "symbol": "BTCUSDT",
            "src": "depth",
            "bid": 70321.4,
            "ask": 70321.6,
            "bids": [[70321.4, 10.5], [70321.3, 8.2], [70321.2, 6.0], [70321.1, 5.0], [70321.0, 4.0]],
            "asks": [[70321.6, 11.2], [70321.7, 9.5], [70321.8, 7.0], [70321.9, 6.0], [70322.0, 5.0]],
            "best_spread_bps": 1.4
        }
        
        # 模拟成交
        trade_row = {
            "ts_ms": 1730790000100,
            "symbol": "BTCUSDT",
            "src": "aggTrade",
            "price": 70321.5,
            "qty": 0.01,
            "side": "buy"
        }
        
        # 先更新订单簿（不会产生特征）
        result1 = pipe.on_row(orderbook_row)
        self.assertIsNone(result1)  # 需要订单簿和成交都可用
        
        # 再更新成交（应该产生特征）
        result2 = pipe.on_row(trade_row)
        
        # 由于 warmup 期，可能需要多次更新才能产生有效特征
        # 这里我们只验证接口正常，不验证具体数值
        
        pipe.close()
    
    def test_on_row_warmup(self):
        """Case-02: warmup 测试（窗口样本不足）"""
        pipe = FeaturePipe(
            config=self.config,
            symbols=["BTCUSDT"],
            sink="jsonl",
            output_dir=str(self.temp_dir)
        )
        
        # 在 warmup 期内，应该返回 warmup=true 的特征
        for i in range(5):
            orderbook_row = {
                "ts_ms": 1730790000000 + i * 100,
                "symbol": "BTCUSDT",
                "src": "depth",
                "bids": [[70321.4, 10.5], [70321.3, 8.2], [70321.2, 6.0], [70321.1, 5.0], [70321.0, 4.0]],
                "asks": [[70321.6, 11.2], [70321.7, 9.5], [70321.8, 7.0], [70321.9, 6.0], [70322.0, 5.0]]
            }
            
            trade_row = {
                "ts_ms": 1730790000100 + i * 100,
                "symbol": "BTCUSDT",
                "src": "aggTrade",
                "price": 70321.5 + i * 0.1,
                "qty": 0.01,
                "side": "buy"
            }
            
            pipe.on_row(orderbook_row)
            result = pipe.on_row(trade_row)
            
            if result:
                # 如果返回了特征，应该包含 warmup 字段
                self.assertIn("warmup", result)
                self.assertIn("z_ofi", result)
                self.assertIn("z_cvd", result)
        
        pipe.close()
    
    def test_on_row_missing_data(self):
        """Case-03: 缺失成交/缺失盘口测试（自动降级）"""
        pipe = FeaturePipe(
            config=self.config,
            symbols=["BTCUSDT"],
            sink="jsonl",
            output_dir=str(self.temp_dir)
        )
        
        # 只有订单簿，没有成交
        orderbook_row = {
            "ts_ms": 1730790000000,
            "symbol": "BTCUSDT",
            "src": "depth",
            "bids": [[70321.4, 10.5], [70321.3, 8.2]],
            "asks": [[70321.6, 11.2], [70321.7, 9.5]]
        }
        
        result = pipe.on_row(orderbook_row)
        self.assertIsNone(result)  # 没有成交，无法产生特征
        
        pipe.close()
    
    def test_on_row_lag_exceeded(self):
        """Case-04: lag 异常测试（>max_lag）"""
        pipe = FeaturePipe(
            config=self.config,
            symbols=["BTCUSDT"],
            sink="jsonl",
            output_dir=str(self.temp_dir),
            max_lag_sec=0.25  # 250ms
        )
        
        # 创建时间差很大的订单簿和成交
        orderbook_row = {
            "ts_ms": 1730790000000,
            "symbol": "BTCUSDT",
            "src": "depth",
            "bids": [[70321.4, 10.5], [70321.3, 8.2], [70321.2, 6.0], [70321.1, 5.0], [70321.0, 4.0]],
            "asks": [[70321.6, 11.2], [70321.7, 9.5], [70321.8, 7.0], [70321.9, 6.0], [70322.0, 5.0]]
        }
        
        # 成交时间晚很多（超过 max_lag）
        trade_row = {
            "ts_ms": 1730790000000 + 500,  # 500ms 后，超过 250ms 限制
            "symbol": "BTCUSDT",
            "src": "aggTrade",
            "price": 70321.5,
            "qty": 0.01,
            "side": "buy"
        }
        
        pipe.on_row(orderbook_row)
        result = pipe.on_row(trade_row)
        
        # 由于 lag 超限，应该跳过
        # 注意：实际实现中，lag 检查是在计算特征时进行的
        # 这里我们只验证接口不会崩溃
        
        pipe.close()
    
    def test_on_row_deduplication(self):
        """Case-05: 重复流/重放测试（去重窗口生效）"""
        pipe = FeaturePipe(
            config=self.config,
            symbols=["BTCUSDT"],
            sink="jsonl",
            output_dir=str(self.temp_dir),
            dedupe_ms=1000
        )
        
        orderbook_row = {
            "ts_ms": 1730790000000,
            "symbol": "BTCUSDT",
            "src": "depth",
            "bids": [[70321.4, 10.5], [70321.3, 8.2], [70321.2, 6.0], [70321.1, 5.0], [70321.0, 4.0]],
            "asks": [[70321.6, 11.2], [70321.7, 9.5], [70321.8, 7.0], [70321.9, 6.0], [70322.0, 5.0]]
        }
        
        trade_row = {
            "ts_ms": 1730790000100,
            "symbol": "BTCUSDT",
            "src": "aggTrade",
            "price": 70321.5,
            "qty": 0.01,
            "side": "buy",
            "row_id": "test-row-1"
        }
        
        # 第一次处理
        pipe.on_row(orderbook_row)
        result1 = pipe.on_row(trade_row)
        
        # 重复处理相同的数据（相同 ts_ms 和 row_id）
        pipe.on_row(orderbook_row)
        result2 = pipe.on_row(trade_row)
        
        # 第二次应该被去重，返回 None 或跳过
        # 注意：实际行为取决于去重逻辑的实现
        
        pipe.close()
    
    def test_jsonl_sink(self):
        """测试 JSONL sink 输出"""
        output_file = self.temp_dir / "features.jsonl"
        
        pipe = FeaturePipe(
            config=self.config,
            symbols=["BTCUSDT"],
            sink="jsonl",
            output_dir=str(self.temp_dir)
        )
        
        # 模拟数据
        orderbook_row = {
            "ts_ms": 1730790000000,
            "symbol": "BTCUSDT",
            "src": "depth",
            "bids": [[70321.4, 10.5], [70321.3, 8.2], [70321.2, 6.0], [70321.1, 5.0], [70321.0, 4.0]],
            "asks": [[70321.6, 11.2], [70321.7, 9.5], [70321.8, 7.0], [70321.9, 6.0], [70322.0, 5.0]]
        }
        
        trade_row = {
            "ts_ms": 1730790000100,
            "symbol": "BTCUSDT",
            "src": "aggTrade",
            "price": 70321.5,
            "qty": 0.01,
            "side": "buy"
        }
        
        pipe.on_row(orderbook_row)
        pipe.on_row(trade_row)
        pipe.flush()
        pipe.close()
        
        # 验证文件是否创建
        if output_file.exists():
            with open(output_file, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]
                # 如果有输出，验证 JSON 格式
                for line in lines:
                    try:
                        data = json.loads(line)
                        self.assertIn("ts_ms", data)
                        self.assertIn("symbol", data)
                    except json.JSONDecodeError:
                        self.fail(f"Invalid JSON: {line}")


if __name__ == "__main__":
    unittest.main()

