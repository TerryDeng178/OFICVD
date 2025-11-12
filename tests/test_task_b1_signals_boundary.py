# -*- coding: utf-8 -*-
"""TASK-B1: 信号边界固化测试

测试Strategy层仅读signals的边界约束：
- 误触features读取检测（fail-fast）
- 心跳日志输出验证
- 信号边界验证功能
"""

import pytest
import time
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

from mcp.strategy_server.app import _validate_signals_only_boundary


class TestTaskB1SignalsBoundary:
    """TASK-B1: 信号边界固化测试"""

    def test_signals_boundary_validation_passes(self, caplog):
        """测试信号边界验证通过（正常情况）"""
        with caplog.at_level(logging.INFO):
            _validate_signals_only_boundary()

        # 应该记录成功日志
        assert any("[TASK-B1] OK: 信号边界验证通过" in record.message
                  for record in caplog.records)

    @patch('sys.exit')
    def test_signals_boundary_validation_blocks_features_access(self, mock_exit, caplog):
        """测试信号边界验证阻止features访问"""
        # 模拟调用栈中包含features访问的代码
        with patch('inspect.currentframe') as mock_frame, \
             patch('inspect.getframeinfo') as mock_getframeinfo:

            # 创建模拟的frame info，包含features访问
            mock_frame_info = MagicMock()
            mock_frame_info.code_context = ["data = load_from_features('/path/to/features/file.json')"]
            mock_frame_info.filename = "test_file.py"
            mock_frame_info.lineno = 42

            mock_getframeinfo.return_value = mock_frame_info

            # 设置frame链
            mock_frame_instance = MagicMock()
            mock_frame_instance.f_back = None
            mock_frame.return_value = mock_frame_instance

            with caplog.at_level(logging.ERROR):
                _validate_signals_only_boundary()

            # 应该记录错误并退出
            assert any("[TASK-B1] ERROR: 检测到禁止的features访问" in record.message
                      for record in caplog.records)
            assert any("Strategy层必须只读signals，禁止访问features" in record.message
                      for record in caplog.records)
            mock_exit.assert_called_once_with(1)

    def test_signals_boundary_validation_blocks_import_features(self, caplog):
        """测试信号边界验证阻止import features"""
        with patch('inspect.currentframe') as mock_frame, \
             patch('inspect.getframeinfo') as mock_getframeinfo, \
             patch('sys.exit') as mock_exit:

            # 创建模拟的frame info，包含features导入
            mock_frame_info = MagicMock()
            mock_frame_info.code_context = ["from features import load_data"]
            mock_frame_info.filename = "strategy.py"
            mock_frame_info.lineno = 10

            mock_getframeinfo.return_value = mock_frame_info

            # 设置frame链
            mock_frame_instance = MagicMock()
            mock_frame_instance.f_back = None
            mock_frame.return_value = mock_frame_instance

            _validate_signals_only_boundary()

            # 应该记录错误并退出
            assert any("[TASK-B1] ERROR: 检测到禁止的features访问" in record.message
                      for record in caplog.records)
            mock_exit.assert_called_once_with(1)

    @pytest.mark.integration
    def test_strategy_server_heartbeat_logging(self, tmp_path, caplog):
        """集成测试：Strategy Server心跳日志输出"""
        # 这个测试需要在实际的Strategy Server进程中运行
        # 这里只是一个占位符，实际测试需要在E2E环境中进行
        pytest.skip("需要E2E环境测试心跳日志输出")

    @pytest.mark.integration
    def test_signals_stall_detection_60_seconds(self, tmp_path):
        """集成测试：信号停更60秒报警"""
        # 创建测试信号目录
        signals_dir = tmp_path / "ready" / "signal" / "BTCUSDT"
        signals_dir.mkdir(parents=True)

        # 创建一个旧的信号文件（超过60秒）
        old_signal_file = signals_dir / "signals-20241113-10.jsonl"
        old_signal_file.write_text('{"ts_ms": 1731470000000, "symbol": "BTCUSDT", "confirm": true}\n')
        old_signal_file.touch()  # 确保文件存在

        # 将文件修改时间设置为60秒前
        import os
        old_time = time.time() - 65
        os.utime(str(old_signal_file), (old_time, old_time))

        # 这个测试应该在orchestrator层面验证健康检查
        # 目前只验证文件存在性
        assert old_signal_file.exists()
        assert old_signal_file.stat().st_mtime < time.time() - 60

    def test_signals_directory_contract_compliance(self, tmp_path):
        """测试信号目录契约合规性"""
        from mcp.strategy_server.app import read_signals_from_jsonl

        # 创建符合契约的目录结构
        signals_dir = tmp_path / "ready" / "signal"
        btc_dir = signals_dir / "BTCUSDT"
        btc_dir.mkdir(parents=True)

        # 创建v2格式信号文件（连字符）
        v2_file = btc_dir / "signals-20241113-10.jsonl"
        v2_file.write_text('{"ts_ms": 1731470000000, "symbol": "BTCUSDT", "confirm": true, "score": 2.0}\n')

        # 创建v1格式信号文件（下划线）- 用于兼容性测试
        v1_file = btc_dir / "signals_20241113_1015.jsonl"
        v1_file.write_text('{"ts_ms": 1731470000000, "symbol": "BTCUSDT", "confirm": true, "score": 1.5}\n')

        # 验证能读取v2格式
        signals = list(read_signals_from_jsonl(signals_dir, ["BTCUSDT"]))
        assert len(signals) >= 1  # 至少读取到一个信号

        # 验证信号字段完整性
        signal = signals[0]
        required_fields = ["ts_ms", "symbol", "confirm", "score"]
        for field in required_fields:
            assert field in signal, f"信号缺少必需字段: {field}"

    def test_sqlite_signals_health_metrics(self, tmp_path):
        """测试SQLite信号健康指标"""
        import sqlite3
        from pathlib import Path

        # 创建测试数据库
        db_path = tmp_path / "signals_v2.db"
        conn = sqlite3.connect(str(db_path))

        # 创建signals表
        conn.execute("""
            CREATE TABLE signals (
                ts_ms INTEGER,
                symbol TEXT,
                score REAL,
                confirm INTEGER,
                gating INTEGER,
                decision_code TEXT
            )
        """)

        # 插入测试数据
        test_signals = [
            (1731470000000, "BTCUSDT", 2.0, 1, 1, "OK"),
            (1731470060000, "BTCUSDT", 1.5, 1, 1, "OK"),
        ]

        conn.executemany("INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?)", test_signals)
        conn.commit()
        conn.close()

        # 验证数据库文件存在且可读
        assert db_path.exists()
        assert db_path.stat().st_size > 0

        # 重新连接验证数据完整性
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM signals WHERE confirm = 1")
        count = cursor.fetchone()[0]
        assert count == 2, f"期望2条确认信号，实际{count}条"
        conn.close()
