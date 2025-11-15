# -*- coding: utf-8 -*-
"""TASK-STRATEGY-LAYER-MIGRATION: 策略层E2E测试

测试策略层迁移后的完整端到端流程：
- CLI参数解析和传递
- 完整的回测执行流程
- 策略决策输出验证
- 质量档位和gating mode的端到端效果
"""

import pytest
import json
import tempfile
import yaml
from pathlib import Path

from backtest.app import build_run_manifest


class TestStrategyLayerE2E:
    """策略层端到端测试"""

    @pytest.fixture
    def temp_config_file(self):
        """创建临时配置文件"""
        config = {
            "data": {
                "features_price_dir": "./deploy/data/ofi_cvd"
            },
            "signal": {
                "min_abs_score_for_side": 0.1
            },
            "broker": {
                "fee_bps_maker": -25,
                "fee_bps_taker": 75,
                "slippage_bps": 0,
                "latency_ms": 0,
                "maker_first": True,
                "min_order_qty": 0.001
            },
            "order": {
                "qty": 0.01
            },
            "output": {
                "emit_sqlite": False
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.safe_dump(config, f, default_flow_style=False)
            config_path = f.name

        yield config_path

        # 清理
        Path(config_path).unlink(missing_ok=True)

    def test_strategy_layer_parameter_handling(self, temp_config_file):
        """测试策略层参数处理"""
        # 创建参数对象模拟CLI解析结果
        class MockArgs:
            def __init__(self):
                self.mode = "A"
                self.start = "2024-01-01T00:00:00Z"
                self.end = "2024-01-01T01:00:00Z"
                self.config = temp_config_file
                self.gating_mode = "ignore_soft"
                self.quality_mode = "conservative"
                self.legacy_backtest_mode = True
                self.run_id = "test_run"
                self.out_dir = "/tmp"

        args = MockArgs()

        # 验证manifest构建
        config = {"test": "config"}
        symbols = {"BTCUSDT"}
        manifest = build_run_manifest(args, config, symbols)

        assert manifest["gating_mode"] == "ignore_soft"
        assert manifest["quality_mode"] == "conservative"
        assert manifest["legacy_backtest_mode"] is True

    @patch('alpha_core.signals.CoreAlgorithm')
    @patch('backtest.app.BacktestAdapter._load_price_cache')
    def test_full_backtest_execution_with_strategy(self, mock_price_cache, mock_core_algo, temp_config_file):
        """测试完整回测执行中的策略层效果"""
        # 模拟CoreAlgorithm
        mock_algo_instance = MagicMock()
        mock_core_algo.return_value = mock_algo_instance

        # 模拟信号生成
        mock_signals = [
            # 信号1：应该交易（BUY）
            {
                "ts_ms": 1640995200000,
                "symbol": "BTCUSDT",
                "score": 0.5,
                "confirm": True,
                "gating": [],
                "mid_px": 50000.0,
                "quality_tier": "strong",
                "run_id": "test_run"
            },
            # 信号2：应该被gating阻塞
            {
                "ts_ms": 1640995260000,
                "symbol": "BTCUSDT",
                "score": -0.3,
                "confirm": True,
                "gating": ["weak_signal"],
                "mid_px": 49900.0,
                "quality_tier": "normal",
                "run_id": "test_run"
            }
        ]
        mock_algo_instance.process_feature_row.side_effect = mock_signals

        # 模拟价格缓存
        mock_price_cache_instance = MagicMock()
        mock_price_cache_instance.lookup.return_value = 50000.0

        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建模拟features目录
            features_dir = Path(temp_dir) / "features"
            features_dir.mkdir()

            # 创建输出目录
            output_dir = Path(temp_dir) / "output"
            output_dir.mkdir()

            # 创建测试参数
            test_args = [
                "--mode", "A",
                "--features-dir", str(features_dir),
                "--config", temp_config_file,
                "--start", "2022-01-01T00:00:00Z",
                "--end", "2022-01-01T00:05:00Z",
                "--out-dir", str(output_dir),
                "--run-id", "test_strategy_e2e",
                "--symbols", "BTCUSDT",
                "--gating-mode", "strict",
                "--quality-mode", "all"
            ]

            # 执行回测
            with patch('sys.argv', ['backtest.app'] + test_args):
                try:
                    main()
                except SystemExit as e:
                    # main()会调用sys.exit(0)，这是正常的
                    assert e.code == 0

            # 验证输出文件
            run_dir = output_dir / "test_strategy_e2e"
            assert run_dir.exists()

            # 检查信号文件
            signals_file = run_dir / "signals.jsonl"
            assert signals_file.exists()

            # 检查交易文件
            trades_file = run_dir / "trades.jsonl"
            assert trades_file.exists()

            # 检查manifest文件
            manifest_file = run_dir / "run_manifest.json"
            assert manifest_file.exists()

            # 验证manifest内容
            with manifest_file.open('r', encoding='utf-8') as f:
                manifest = json.load(f)

            assert manifest["gating_mode"] == "strict"
            assert manifest["quality_mode"] == "all"
            assert manifest["legacy_backtest_mode"] is False

            # 验证信号输出（应该只有1个信号被写入，因为第2个被gating阻塞）
            with signals_file.open('r', encoding='utf-8') as f:
                signals = [json.loads(line) for line in f]
                assert len(signals) == 2  # 所有信号都写入，但只有1个生成交易

            # 验证交易输出（应该只有1个交易）
            with trades_file.open('r', encoding='utf-8') as f:
                trades = [json.loads(line) for line in f]
                assert len(trades) == 1  # 只有第1个信号生成交易
                assert trades[0]["side"] == "BUY"

    def test_strategy_mode_e2e_with_different_configs(self, temp_config_file):
        """测试不同策略配置的端到端效果"""
        test_configs = [
            {
                "name": "strict_all",
                "args": ["--gating-mode", "strict", "--quality-mode", "all"],
                "expected_trades": 1
            },
            {
                "name": "ignore_soft_conservative",
                "args": ["--gating-mode", "ignore_soft", "--quality-mode", "conservative"],
                "expected_trades": 1  # 第1个信号是strong，应该交易
            },
            {
                "name": "legacy_mode",
                "args": ["--legacy-backtest-mode"],
                "expected_trades": 2  # legacy模式忽略所有护栏
            }
        ]

        for config in test_configs:
            with self._run_strategy_e2e_test(temp_config_file, config) as result:
                assert result["trades_count"] == config["expected_trades"], \
                    f"Config {config['name']}: expected {config['expected_trades']} trades, got {result['trades_count']}"

    def _run_strategy_e2e_test(self, config_file, config):
        """运行策略E2E测试的辅助方法"""
        from contextlib import contextmanager

        @contextmanager
        def test_context():
            with patch('alpha_core.signals.CoreAlgorithm') as mock_core_algo, \
                 patch('backtest.app.BacktestAdapter._load_price_cache') as mock_price_cache:

                # 模拟CoreAlgorithm
                mock_algo_instance = MagicMock()
                mock_core_algo.return_value = mock_algo_instance

                mock_signals = [
                    {
                        "ts_ms": 1640995200000,
                        "symbol": "BTCUSDT",
                        "score": 0.5,
                        "confirm": True,
                        "gating": [],
                        "mid_px": 50000.0,
                        "quality_tier": "strong",
                        "run_id": "test_run"
                    },
                    {
                        "ts_ms": 1640995260000,
                        "symbol": "BTCUSDT",
                        "score": -0.3,
                        "confirm": True,
                        "gating": ["weak_signal"],
                        "mid_px": 49900.0,
                        "quality_tier": "normal",
                        "run_id": "test_run"
                    }
                ]
                mock_algo_instance.process_feature_row.side_effect = mock_signals

                # 模拟价格缓存
                mock_price_cache_instance = MagicMock()
                mock_price_cache_instance.lookup.return_value = 50000.0

                with tempfile.TemporaryDirectory() as temp_dir:
                    # 创建目录结构
                    features_dir = Path(temp_dir) / "features"
                    features_dir.mkdir()
                    output_dir = Path(temp_dir) / "output"
                    output_dir.mkdir()

                    # 构建测试参数
                    test_args = [
                        "--mode", "A",
                        "--features-dir", str(features_dir),
                        "--config", config_file,
                        "--start", "2022-01-01T00:00:00Z",
                        "--end", "2022-01-01T00:05:00Z",
                        "--out-dir", str(output_dir),
                        "--run-id", f"test_{config['name']}",
                        "--symbols", "BTCUSDT"
                    ] + config["args"]

                    # 执行回测
                    with patch('sys.argv', ['backtest.app'] + test_args):
                        try:
                            main()
                        except SystemExit as e:
                            assert e.code == 0

                    # 收集结果
                    run_dir = output_dir / f"test_{config['name']}"

                    trades_count = 0
                    if (run_dir / "trades.jsonl").exists():
                        with (run_dir / "trades.jsonl").open('r', encoding='utf-8') as f:
                            trades_count = len([line for line in f if line.strip()])

                    yield {
                        "trades_count": trades_count,
                        "run_dir": run_dir
                    }

        return test_context()

    def test_strategy_layer_import_consistency(self):
        """测试策略层导入的一致性"""
        # 验证可以通过不同路径导入相同的组件
        from alpha_core.strategy import StrategyEmulator as DirectStrategyEmulator
        from alpha_core.strategy.policy import StrategyEmulator as PolicyStrategyEmulator
        from backtest.app import StrategyEmulator as AppStrategyEmulator

        # 所有导入的类应该是相同的
        assert DirectStrategyEmulator is PolicyStrategyEmulator
        assert PolicyStrategyEmulator is AppStrategyEmulator

        # 验证常量一致性
        from alpha_core.strategy import SOFT_GATING as DirectSoftGating
        from alpha_core.strategy.policy import SOFT_GATING as PolicySoftGating
        from backtest.app import SOFT_GATING as AppSoftGating

        assert DirectSoftGating == PolicySoftGating == AppSoftGating

    def test_e2e_error_handling(self, temp_config_file):
        """测试端到端错误处理"""
        # 测试无效的gating-mode参数
        test_args = [
            "--mode", "A",
            "--features-dir", "/tmp/test",
            "--config", temp_config_file,
            "--start", "2024-01-01T00:00:00Z",
            "--end", "2024-01-01T01:00:00Z",
            "--gating-mode", "invalid_mode"  # 无效参数
        ]

        from backtest.app import _create_parser
        parser = _create_parser()

        # 应该抛出参数错误
        with pytest.raises(SystemExit):
            parser.parse_args(test_args)
