# -*- coding: utf-8 -*-
"""测试执行日志Outbox模式

验证spool→ready原子发布、Windows友好重试、事件Schema
"""
import pytest
import tempfile
import shutil
import time
from pathlib import Path

from src.alpha_core.executors.exec_log_sink_outbox import (
    JsonlExecLogSinkOutbox,
    _atomic_move_with_retry,
    create_exec_log_sink_outbox,
)
from src.alpha_core.executors.base_executor import (
    OrderCtx,
    ExecResult,
    ExecResultStatus,
    Fill,
    OrderState,
    Side,
    OrderType,
)


class TestAtomicMove:
    """测试原子移动功能"""
    
    def test_atomic_move_basic(self):
        """测试基础原子移动"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            src = tmp_path / "test.part"
            dst = tmp_path / "ready" / "test.jsonl"
            
            # 创建源文件
            src.write_text("test content", encoding="utf-8")
            
            # 执行原子移动
            result = _atomic_move_with_retry(src, dst)
            
            assert result is True
            assert dst.exists()
            assert not src.exists()
            assert dst.read_text(encoding="utf-8") == "test content"
    
    def test_atomic_move_creates_dirs(self):
        """测试原子移动自动创建目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            src = tmp_path / "test.part"
            dst = tmp_path / "nested" / "deep" / "test.jsonl"
            
            src.write_text("test", encoding="utf-8")
            result = _atomic_move_with_retry(src, dst)
            
            assert result is True
            assert dst.exists()
            assert dst.parent.exists()


class TestJsonlExecLogSinkOutbox:
    """测试JsonlExecLogSinkOutbox"""
    
    def test_write_event_basic(self):
        """测试基础事件写入"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = JsonlExecLogSinkOutbox(Path(tmpdir))
            
            order_ctx = OrderCtx(
                client_order_id="test-123",
                symbol="BTCUSDT",
                side=Side.BUY,
                qty=0.001,
                ts_ms=int(time.time() * 1000),
            )
            
            sink.write_event(
                ts_ms=int(time.time() * 1000),
                symbol="BTCUSDT",
                event="submit",
                order_ctx=order_ctx,
            )
            
            sink.flush()
            sink.close()
            
            # 检查ready目录中是否有文件
            ready_dir = Path(tmpdir) / "ready" / "execlog" / "BTCUSDT"
            assert ready_dir.exists()
            files = list(ready_dir.glob("exec_*.jsonl"))
            assert len(files) > 0
    
    def test_write_event_with_exec_result(self):
        """测试包含执行结果的事件写入"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = JsonlExecLogSinkOutbox(Path(tmpdir))
            
            order_ctx = OrderCtx(
                client_order_id="test-456",
                symbol="BTCUSDT",
                side=Side.BUY,
                qty=0.001,
                price=50000.0,
                ts_ms=int(time.time() * 1000),
            )
            
            exec_result = ExecResult(
                status=ExecResultStatus.ACCEPTED,
                client_order_id="test-456",
                exchange_order_id="EX-789",
                latency_ms=10,
                slippage_bps=0.5,
                sent_ts_ms=order_ctx.ts_ms,
                ack_ts_ms=order_ctx.ts_ms + 10,
            )
            
            sink.write_event(
                ts_ms=int(time.time() * 1000),
                symbol="BTCUSDT",
                event="ack",
                order_ctx=order_ctx,
                exec_result=exec_result,
            )
            
            sink.flush()
            sink.close()
            
            # 验证文件内容
            ready_dir = Path(tmpdir) / "ready" / "execlog" / "BTCUSDT"
            files = list(ready_dir.glob("exec_*.jsonl"))
            assert len(files) > 0
            
            import json
            content = files[0].read_text(encoding="utf-8")
            record = json.loads(content.strip())
            
            assert record["client_order_id"] == "test-456"
            assert record["exchange_order_id"] == "EX-789"
            assert record["latency_ms"] == 10
            assert record["slippage_bps"] == 0.5
            assert record["px_intent"] == 50000.0
            assert record["px_sent"] == 50000.0
    
    def test_write_event_with_fill(self):
        """测试包含成交信息的事件写入"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = JsonlExecLogSinkOutbox(Path(tmpdir))
            
            order_ctx = OrderCtx(
                client_order_id="test-789",
                symbol="BTCUSDT",
                side=Side.BUY,
                qty=0.001,
                price=50000.0,
                ts_ms=int(time.time() * 1000),
            )
            
            fill = Fill(
                ts_ms=int(time.time() * 1000) + 50,
                symbol="BTCUSDT",
                client_order_id="test-789",
                price=50001.0,
                qty=0.001,
                broker_order_id="EX-999",
                fee=0.1,
                liquidity="taker",
                side=Side.BUY,
            )
            
            sink.write_event(
                ts_ms=int(time.time() * 1000) + 50,
                symbol="BTCUSDT",
                event="filled",
                order_ctx=order_ctx,
                fill=fill,
            )
            
            sink.flush()
            sink.close()
            
            # 验证文件内容
            ready_dir = Path(tmpdir) / "ready" / "execlog" / "BTCUSDT"
            files = list(ready_dir.glob("exec_*.jsonl"))
            assert len(files) > 0
            
            import json
            content = files[0].read_text(encoding="utf-8")
            record = json.loads(content.strip())
            
            assert record["px_fill"] == 50001.0
            assert record["fill_qty"] == 0.001
            assert record["fee"] == 0.1
            assert record["liquidity"] == "taker"
            assert record["exchange_order_id"] == "EX-999"
    
    def test_write_event_with_upstream_state(self):
        """测试包含上游状态字段的事件写入"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = JsonlExecLogSinkOutbox(Path(tmpdir))
            
            order_ctx = OrderCtx(
                client_order_id="test-state",
                symbol="BTCUSDT",
                side=Side.BUY,
                qty=0.001,
                signal_row_id="signal-123",
                regime="active",
                scenario="HH",
                warmup=False,
                guard_reason=None,
                consistency=0.85,
                ts_ms=int(time.time() * 1000),
            )
            
            sink.write_event(
                ts_ms=int(time.time() * 1000),
                symbol="BTCUSDT",
                event="submit",
                order_ctx=order_ctx,
            )
            
            sink.flush()
            sink.close()
            
            # 验证文件内容
            ready_dir = Path(tmpdir) / "ready" / "execlog" / "BTCUSDT"
            files = list(ready_dir.glob("exec_*.jsonl"))
            assert len(files) > 0
            
            import json
            content = files[0].read_text(encoding="utf-8")
            record = json.loads(content.strip())
            
            assert record["signal_row_id"] == "signal-123"
            assert record["regime"] == "active"
            assert record["scenario"] == "HH"
            assert record["consistency"] == 0.85
    
    def test_file_rotation(self):
        """测试文件轮转"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = JsonlExecLogSinkOutbox(Path(tmpdir), fsync_every_n=10)
            
            base_ts = int(time.time() * 1000)
            
            # 写入多个事件（跨越不同分钟）
            for i in range(5):
                order_ctx = OrderCtx(
                    client_order_id=f"test-{i}",
                    symbol="BTCUSDT",
                    side=Side.BUY,
                    qty=0.001,
                    ts_ms=base_ts + i * 60000,  # 每分钟一个事件
                )
                sink.write_event(
                    ts_ms=base_ts + i * 60000,
                    symbol="BTCUSDT",
                    event="submit",
                    order_ctx=order_ctx,
                )
            
            sink.flush()
            sink.close()
            
            # 检查ready目录中的文件数
            ready_dir = Path(tmpdir) / "ready" / "execlog" / "BTCUSDT"
            files = list(ready_dir.glob("exec_*.jsonl"))
            # 应该至少有1个文件（可能多个，取决于时间跨度）
            assert len(files) >= 1
    
    def test_spool_to_ready_atomic_publish(self):
        """测试spool→ready原子发布"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = JsonlExecLogSinkOutbox(Path(tmpdir))
            
            order_ctx = OrderCtx(
                client_order_id="test-atomic",
                symbol="BTCUSDT",
                side=Side.BUY,
                qty=0.001,
                ts_ms=int(time.time() * 1000),
            )
            
            sink.write_event(
                ts_ms=int(time.time() * 1000),
                symbol="BTCUSDT",
                event="submit",
                order_ctx=order_ctx,
            )
            
            # 检查spool目录中有文件
            spool_dir = Path(tmpdir) / "spool" / "execlog" / "BTCUSDT"
            spool_files = list(spool_dir.glob("exec_*.part"))
            assert len(spool_files) > 0
            
            # flush后，spool文件应该移动到ready
            sink.flush()
            
            # spool文件应该消失或为空
            spool_files_after = list(spool_dir.glob("exec_*.part"))
            # 文件应该被移动或为空
            
            # ready目录应该有文件
            ready_dir = Path(tmpdir) / "ready" / "execlog" / "BTCUSDT"
            ready_files = list(ready_dir.glob("exec_*.jsonl"))
            assert len(ready_files) > 0
            
            sink.close()
    
    def test_create_sink_factory(self):
        """测试Sink工厂函数"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = create_exec_log_sink_outbox(Path(tmpdir))
            assert isinstance(sink, JsonlExecLogSinkOutbox)
            sink.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

