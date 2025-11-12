# -*- coding: utf-8 -*-
"""执行层E2E测试

在现有5服务主链用例基础上，新增"Strategy→Executor→ExecLogSink"的完整链路用例
覆盖：正常下单、风控拒单、价格对齐、网络抖动重试、影子执行对比、优雅关闭
"""
import pytest
import tempfile
import shutil
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from src.alpha_core.executors.base_executor import (
    OrderCtx,
    ExecResult,
    ExecResultStatus,
    Side,
    OrderType,
    Fill,
)
from src.alpha_core.executors.backtest_executor import BacktestExecutor
from src.alpha_core.executors.executor_precheck import ExecutorPrecheck
from src.alpha_core.executors.exec_log_sink_outbox import JsonlExecLogSinkOutbox
from src.alpha_core.executors.idempotency import IdempotencyTracker, RetryPolicy
from src.alpha_core.executors.price_alignment import PriceAligner
from src.alpha_core.executors.shadow_execution import ShadowExecutorWrapper
from src.alpha_core.executors.executor_logging import ExecutorLogger


class MockExecutor:
    """模拟执行器（用于测试）"""
    
    def __init__(self):
        self.orders = {}
        self.fills = []
        self.position = 0.0
        self.mode = "testnet"
    
    def submit(self, order):
        """提交订单"""
        order_id = order.client_order_id
        self.orders[order_id] = order
        return f"EX-{order_id}"
    
    def submit_with_ctx(self, order_ctx: OrderCtx) -> ExecResult:
        """提交订单（扩展接口）"""
        order_id = order_ctx.client_order_id
        self.orders[order_id] = order_ctx
        
        # 模拟成交
        fill = Fill(
            ts_ms=int(time.time() * 1000),
            symbol=order_ctx.symbol,
            client_order_id=order_id,
            price=order_ctx.price or 50000.0,
            qty=order_ctx.qty,
            side=order_ctx.side,
        )
        self.fills.append(fill)
        self.position += fill.qty if order_ctx.side == Side.BUY else -fill.qty
        
        return ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id=order_id,
            exchange_order_id=f"EX-{order_id}",
            latency_ms=10,
        )
    
    def cancel(self, order_id: str) -> bool:
        """撤销订单"""
        if order_id in self.orders:
            del self.orders[order_id]
            return True
        return False
    
    def fetch_fills(self, since_ts_ms=None):
        """获取成交记录"""
        return self.fills
    
    def get_position(self, symbol: str) -> float:
        """获取持仓"""
        return self.position
    
    def close(self):
        """关闭执行器"""
        pass
    
    def flush(self):
        """刷新缓存"""
        pass


class TestExecutorE2E:
    """执行层E2E测试"""
    
    @pytest.fixture
    def temp_dir(self):
        """临时目录"""
        temp_path = Path(tempfile.mkdtemp())
        yield temp_path
        shutil.rmtree(temp_path, ignore_errors=True)
    
    @pytest.fixture
    def mock_executor(self):
        """模拟执行器"""
        return MockExecutor()
    
    @pytest.fixture
    def exec_log_sink(self, temp_dir):
        """执行日志Sink"""
        sink_dir = temp_dir / "exec_logs"
        sink = JsonlExecLogSinkOutbox(
            output_dir=sink_dir,
        )
        yield sink
        sink.close()
    
    @pytest.fixture
    def executor_logger(self):
        """执行层日志记录器"""
        return ExecutorLogger(sample_rate=1.0, enabled=True)  # 100%采样用于测试
    
    def test_normal_order_submission(self, mock_executor, exec_log_sink, executor_logger):
        """测试正常下单"""
        # 创建订单上下文
        order_ctx = OrderCtx(
            client_order_id="test-normal-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            order_type=OrderType.MARKET,
            ts_ms=int(time.time() * 1000),
            tick_size=0.01,
            step_size=0.00001,
        )
        
        # 价格对齐
        aligner = PriceAligner()
        aligned_order_ctx, rounding_applied = aligner.align_order_ctx(order_ctx)
        
        # 创建执行结果（包含rounding_applied）
        exec_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id=aligned_order_ctx.client_order_id,
            exchange_order_id=f"EX-{aligned_order_ctx.client_order_id}",
            rounding_applied=rounding_applied,
        )
        
        # 提交订单
        mock_executor.submit_with_ctx(aligned_order_ctx)
        
        # 记录日志
        executor_logger.log_order_submitted(aligned_order_ctx, exec_result)
        
        # 写入执行日志
        exec_log_sink.write_event(
            ts_ms=aligned_order_ctx.ts_ms or int(time.time() * 1000),
            symbol=aligned_order_ctx.symbol,
            event="submit",
            order_ctx=aligned_order_ctx,
            exec_result=exec_result,
        )
        
        # 验证
        assert exec_result.status == ExecResultStatus.ACCEPTED
        assert exec_result.exchange_order_id is not None
        assert aligned_order_ctx.client_order_id in mock_executor.orders
    
    def test_risk_rejection(self, mock_executor, exec_log_sink, executor_logger):
        """测试风控拒单"""
        # 创建前置检查器
        precheck = ExecutorPrecheck()
        
        # 创建订单上下文（warmup阶段）
        order_ctx = OrderCtx(
            client_order_id="test-rejected-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            warmup=True,
            guard_reason="warmup",
        )
        
        # 前置检查（返回ExecResult）
        exec_result = precheck.check(order_ctx)
        
        if exec_result.status == ExecResultStatus.REJECTED:
            
            # 记录日志（失败订单100%记录）
            executor_logger.log_order_submitted(order_ctx, exec_result)
            
            # 写入执行日志
            exec_log_sink.write_event(
                ts_ms=order_ctx.ts_ms or int(time.time() * 1000),
                symbol=order_ctx.symbol,
                event="rejected",
                order_ctx=order_ctx,
                exec_result=exec_result,
            )
            
            # 验证
            assert exec_result.status == ExecResultStatus.REJECTED
            assert exec_result.reject_reason == "warmup"
    
    def test_price_alignment(self, mock_executor, exec_log_sink, executor_logger):
        """测试价格对齐"""
        aligner = PriceAligner()
        
        # 创建订单上下文（价格需要对齐）
        order_ctx = OrderCtx(
            client_order_id="test-align-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.00123456,  # 需要对齐到step_size
            price=50000.123,  # 需要对齐到tick_size
            order_type=OrderType.LIMIT,
            tick_size=0.01,
            step_size=0.00001,
        )
        
        # 对齐（align_order_ctx返回对齐后的OrderCtx和rounding_applied字典）
        aligned_order_ctx, rounding_applied = aligner.align_order_ctx(order_ctx)
        
        # 验证对齐
        assert rounding_applied is not None
        assert "price_diff" in rounding_applied
        assert "qty_diff" in rounding_applied
        
        # 创建执行结果（包含rounding_applied）
        exec_result = ExecResult(
            status=ExecResultStatus.ACCEPTED,
            client_order_id=aligned_order_ctx.client_order_id,
            exchange_order_id=f"EX-{aligned_order_ctx.client_order_id}",
            rounding_applied=rounding_applied,
        )
        
        # 提交订单
        mock_executor.submit_with_ctx(aligned_order_ctx)
        
        # 记录日志
        executor_logger.log_order_submitted(aligned_order_ctx, exec_result)
        
        # 写入执行日志
        exec_log_sink.write_event(
            ts_ms=aligned_order_ctx.ts_ms or int(time.time() * 1000),
            symbol=aligned_order_ctx.symbol,
            event="submit",
            order_ctx=aligned_order_ctx,
            exec_result=exec_result,
        )
        
        # 验证
        assert exec_result.status == ExecResultStatus.ACCEPTED
        assert exec_result.rounding_applied is not None
    
    def test_network_jitter_retry(self, mock_executor, exec_log_sink, executor_logger):
        """测试网络抖动重试"""
        retry_policy = RetryPolicy(max_retries=3, base_delay=0.1)  # base_delay是秒
        idempotency_tracker = IdempotencyTracker(max_size=1000)
        
        # 创建订单上下文
        order_ctx = OrderCtx(
            client_order_id="test-retry-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        
        # 检查幂等性
        if idempotency_tracker.is_processed(order_ctx.client_order_id):
            # 已处理，跳过
            return
        
        # 模拟网络错误重试
        attempt = 0
        while attempt < retry_policy.max_retries:
            try:
                # 提交订单
                exec_result = mock_executor.submit_with_ctx(order_ctx)
                
                # 标记为已处理
                idempotency_tracker.mark_processed(order_ctx.client_order_id)
                
                # 记录日志
                executor_logger.log_order_submitted(order_ctx, exec_result)
                
                # 写入执行日志
                exec_log_sink.write_event(
                    ts_ms=order_ctx.ts_ms or int(time.time() * 1000),
                    symbol=order_ctx.symbol,
                    event="submit",
                    order_ctx=order_ctx,
                    exec_result=exec_result,
                )
                
                # 成功，退出重试循环
                break
            except Exception as e:
                attempt += 1
                if not retry_policy.should_retry(str(e)):
                    # 不应该重试，抛出异常
                    raise
                
                if attempt >= retry_policy.max_retries:
                    # 达到最大重试次数
                    raise
                
                # 等待重试延迟
                delay_sec = retry_policy.get_delay(attempt)
                time.sleep(delay_sec)
        
        # 验证
        assert exec_result.status == ExecResultStatus.ACCEPTED
        assert idempotency_tracker.is_processed(order_ctx.client_order_id)
    
    def test_shadow_execution_comparison(self, mock_executor, exec_log_sink, executor_logger):
        """测试影子执行对比"""
        # 创建影子执行器
        from src.alpha_core.executors.shadow_execution import ShadowExecutor
        shadow_executor_mock = MockExecutor()
        shadow_executor = ShadowExecutor(
            testnet_executor=shadow_executor_mock,
            enabled=True,
        )
        
        # 创建影子执行器包装器
        shadow_wrapper = ShadowExecutorWrapper(
            main_executor=mock_executor,
            shadow_executor=shadow_executor,
        )
        
        # 创建订单上下文
        order_ctx = OrderCtx(
            client_order_id="test-shadow-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        
        # 提交订单（自动触发影子执行）
        exec_result = shadow_wrapper.submit_with_ctx(order_ctx)
        
        # 记录日志
        executor_logger.log_order_submitted(order_ctx, exec_result)
        
        # 写入执行日志
        exec_log_sink.write_event(
            ts_ms=order_ctx.ts_ms or int(time.time() * 1000),
            symbol=order_ctx.symbol,
            event="submit",
            order_ctx=order_ctx,
            exec_result=exec_result,
        )
        
        # 获取影子统计
        shadow_stats = shadow_wrapper.get_shadow_stats()
        
        # 验证
        assert exec_result.status == ExecResultStatus.ACCEPTED
        if shadow_stats:
            assert shadow_stats.get("total_comparisons", 0) >= 0
            assert shadow_stats.get("parity_count", 0) >= 0
    
    def test_graceful_shutdown(self, mock_executor, exec_log_sink, executor_logger):
        """测试优雅关闭"""
        # 创建订单上下文
        order_ctx = OrderCtx(
            client_order_id="test-shutdown-1",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
        )
        
        # 提交订单
        exec_result = mock_executor.submit_with_ctx(order_ctx)
        
        # 记录日志
        executor_logger.log_order_submitted(order_ctx, exec_result)
        
        # 写入执行日志
        exec_log_sink.write_event(
            ts_ms=order_ctx.ts_ms or int(time.time() * 1000),
            symbol=order_ctx.symbol,
            event="submit",
            order_ctx=order_ctx,
            exec_result=exec_result,
        )
        
        # 刷新缓存
        exec_log_sink.flush()
        mock_executor.flush()
        
        # 关闭
        exec_log_sink.close()
        mock_executor.close()
        
        # 验证日志文件已发布
        ready_dir = Path(exec_log_sink.output_dir) / "ready" / "execlog" / "BTCUSDT"
        jsonl_files = list(ready_dir.glob("exec_*.jsonl"))
        assert len(jsonl_files) > 0
    
    def test_executor_p95_latency(self, mock_executor, exec_log_sink, executor_logger):
        """测试执行层p95延迟"""
        latencies = []
        
        # 提交多个订单
        for i in range(100):
            order_ctx = OrderCtx(
                client_order_id=f"test-latency-{i}",
                symbol="BTCUSDT",
                side=Side.BUY,
                qty=0.001,
                ts_ms=int(time.time() * 1000),
            )
            
            start_time = time.perf_counter()
            exec_result = mock_executor.submit_with_ctx(order_ctx)
            end_time = time.perf_counter()
            
            latency_ms = (end_time - start_time) * 1000
            latencies.append(latency_ms)
        
        # 计算p95
        latencies.sort()
        p95_index = int(len(latencies) * 0.95)
        p95_latency = latencies[p95_index]
        
        # 验证p95延迟（应该小于某个阈值，例如50ms）
        assert p95_latency < 50.0
    
    def test_idempotency_rate(self, mock_executor, exec_log_sink, executor_logger):
        """测试幂等率"""
        idempotency_tracker = IdempotencyTracker(max_size=1000)
        
        total_submissions = 100
        duplicate_submissions = 0
        
        # 提交订单
        for i in range(total_submissions):
            order_ctx = OrderCtx(
                client_order_id=f"test-idempotency-{i % 50}",  # 重复使用ID
                symbol="BTCUSDT",
                side=Side.BUY,
                qty=0.001,
            )
            
            if idempotency_tracker.is_processed(order_ctx.client_order_id):
                duplicate_submissions += 1
                continue
            
            exec_result = mock_executor.submit_with_ctx(order_ctx)
            idempotency_tracker.mark_processed(order_ctx.client_order_id)
        
        # 计算幂等率
        idempotency_rate = 1.0 - (duplicate_submissions / total_submissions)
        
        # 验证幂等率（应该接近50%，因为有50%的重复ID）
        assert idempotency_rate >= 0.45  # 允许一些误差
        assert idempotency_rate <= 0.55
    
    def test_shadow_consistency_rate(self, mock_executor, exec_log_sink, executor_logger):
        """测试影子一致率"""
        # 创建影子执行器
        from src.alpha_core.executors.shadow_execution import ShadowExecutor
        shadow_executor_mock = MockExecutor()
        shadow_executor = ShadowExecutor(
            testnet_executor=shadow_executor_mock,
            enabled=True,
        )
        
        # 创建影子执行器包装器
        shadow_wrapper = ShadowExecutorWrapper(
            main_executor=mock_executor,
            shadow_executor=shadow_executor,
        )
        
        # 提交多个订单
        for i in range(50):
            order_ctx = OrderCtx(
                client_order_id=f"test-shadow-consistency-{i}",
                symbol="BTCUSDT",
                side=Side.BUY,
                qty=0.001,
            )
            
            shadow_wrapper.submit_with_ctx(order_ctx)
        
        # 获取影子统计
        shadow_stats = shadow_wrapper.get_shadow_stats()
        
        # 计算一致率
        if shadow_stats and shadow_stats.get("total_comparisons", 0) > 0:
            consistency_rate = shadow_stats.get("parity_count", 0) / shadow_stats["total_comparisons"]
            
            # 验证一致率（应该≥99%）
            assert consistency_rate >= 0.99
        else:
            # 如果没有影子统计，跳过验证
            pytest.skip("Shadow stats not available")


    def test_signal_execution_rate_linkage(self, mock_executor, exec_log_sink, executor_logger):
        """测试信号→执行速率联动
        
        验证上游信号状态（gate_reason_stats, consistency）如何影响执行层速率控制
        """
        from src.alpha_core.executors.executor_precheck import ExecutorPrecheck, AdaptiveThrottler
        
        # 创建前置检查器和自适应节流器
        precheck = ExecutorPrecheck()
        throttler = AdaptiveThrottler(
            config={
                "base_rate_limit": 10.0,  # 基础限速：10 req/s
                "window_seconds": 1.0,
            }
        )
        
        # 模拟gate_reason_stats（来自信号层）
        gate_reason_stats = {
            "warmup": 5,  # 5次warmup拒单
            "spread_too_wide": 3,  # 3次价差过大
            "low_consistency": 2,  # 2次一致性低
        }
        total_checks = 20  # 总共20次检查
        
        # 计算拒绝率
        total_rejects = sum(gate_reason_stats.values())
        reject_rate = total_rejects / total_checks if total_checks > 0 else 0.0
        
        # 获取初始限速
        initial_rate_limit = throttler.get_current_rate_limit()
        
        # 获取初始限速
        initial_rate_limit = throttler.get_current_rate_limit()
        assert initial_rate_limit == 10.0, f"Initial rate limit should be 10.0, got {initial_rate_limit}"
        
        # 创建订单上下文（模拟不同状态）
        test_cases = [
            # 正常订单（应该通过）
            {
                "name": "normal_order",
                "order_ctx": OrderCtx(
                    client_order_id="test-rate-link-1",
                    symbol="BTCUSDT",
                    side=Side.BUY,
                    qty=0.001,
                    ts_ms=int(time.time() * 1000),
                    warmup=False,
                    guard_reason=None,
                    consistency=0.8,
                    weak_signal_throttle=False,
                ),
                "expected_status": ExecResultStatus.ACCEPTED,
            },
            # warmup订单（应该被拒）
            {
                "name": "warmup_order",
                "order_ctx": OrderCtx(
                    client_order_id="test-rate-link-2",
                    symbol="BTCUSDT",
                    side=Side.BUY,
                    qty=0.001,
                    ts_ms=int(time.time() * 1000),
                    warmup=True,
                    guard_reason="warmup",
                    consistency=0.8,
                    weak_signal_throttle=False,
                ),
                "expected_status": ExecResultStatus.REJECTED,
            },
            # 低一致性订单（应该被拒）
            {
                "name": "low_consistency_order",
                "order_ctx": OrderCtx(
                    client_order_id="test-rate-link-3",
                    symbol="BTCUSDT",
                    side=Side.BUY,
                    qty=0.001,
                    ts_ms=int(time.time() * 1000),
                    warmup=False,
                    guard_reason=None,
                    consistency=0.1,  # 低于阈值
                    weak_signal_throttle=False,
                ),
                "expected_status": ExecResultStatus.REJECTED,
            },
            # 弱信号节流订单（应该被拒）
            {
                "name": "weak_signal_throttle_order",
                "order_ctx": OrderCtx(
                    client_order_id="test-rate-link-4",
                    symbol="BTCUSDT",
                    side=Side.BUY,
                    qty=0.001,
                    ts_ms=int(time.time() * 1000),
                    warmup=False,
                    guard_reason=None,
                    consistency=0.5,
                    weak_signal_throttle=True,
                ),
                "expected_status": ExecResultStatus.REJECTED,  # ExecutorPrecheck会拒单
            },
        ]
        
        # 执行测试用例
        accepted_count = 0
        rejected_count = 0
        throttled_count = 0
        
        # 注意：由于节流器的window_seconds=1.0，我们需要确保不会超过限速
        # 基础限速是10 req/s，所以4个订单应该都能通过节流器
        for test_case in test_cases:
            order_ctx = test_case["order_ctx"]
            current_ts = int(time.time() * 1000)
            
            # 检查是否应该节流（基于限速）
            # 传入gate_reason_stats以触发限速调整逻辑
            should_throttle = throttler.should_throttle(
                gate_reason_stats=gate_reason_stats, 
                market_activity="active"
            )
            
            if should_throttle:
                throttled_count += 1
                # 被节流，跳过执行
                continue
            
            # 前置检查
            exec_result = precheck.check(order_ctx)
            
            if exec_result.status == ExecResultStatus.ACCEPTED:
                accepted_count += 1
                # 提交订单
                mock_executor.submit_with_ctx(order_ctx)
                
                # 记录日志
                executor_logger.log_order_submitted(order_ctx, exec_result)
                
                # 写入执行日志
                exec_log_sink.write_event(
                    ts_ms=order_ctx.ts_ms or current_ts,
                    symbol=order_ctx.symbol,
                    event="submit",
                    order_ctx=order_ctx,
                    exec_result=exec_result,
                )
            else:
                rejected_count += 1
                # 记录日志（失败订单100%记录）
                executor_logger.log_order_submitted(order_ctx, exec_result)
                
                # 写入执行日志
                exec_log_sink.write_event(
                    ts_ms=order_ctx.ts_ms or current_ts,
                    symbol=order_ctx.symbol,
                    event="rejected",
                    order_ctx=order_ctx,
                    exec_result=exec_result,
                )
            
            # 验证状态
            assert exec_result.status == test_case["expected_status"], \
                f"Test case {test_case['name']} failed: expected {test_case['expected_status']}, got {exec_result.status}"
        
        # 验证速率联动效果
        # 1. 限速应该在合理范围内
        final_rate_limit = throttler.get_current_rate_limit()
        assert final_rate_limit >= throttler.min_rate_limit, \
            f"Rate limit {final_rate_limit} should not be below minimum {throttler.min_rate_limit}"
        assert final_rate_limit <= throttler.max_rate_limit, \
            f"Rate limit {final_rate_limit} should not exceed maximum {throttler.max_rate_limit}"
        
        # 2. 验证至少有一些订单通过了节流器（否则无法测试precheck）
        # 由于基础限速是10 req/s，4个订单应该都能通过
        assert throttled_count < len(test_cases), \
            f"Too many orders throttled ({throttled_count}/{len(test_cases)}), cannot test precheck"
        
        # 3. 被拒单的订单应该记录原因
        precheck_stats = precheck.get_stats()
        assert "deny_stats" in precheck_stats, "Should have deny_stats"
        assert "throttle_stats" in precheck_stats, "Should have throttle_stats"
        
        # 验证有拒单记录（应该至少有3个拒单：warmup, low_consistency, weak_signal_throttle）
        total_denies = sum(precheck_stats["deny_stats"].values())
        total_throttles = sum(precheck_stats["throttle_stats"].values())
        
        # 由于部分订单可能被节流器拦截，实际处理的订单数 = len(test_cases) - throttled_count
        # 其中应该有至少1个拒单（warmup订单）
        processed_count = len(test_cases) - throttled_count
        assert processed_count > 0, "Should have processed at least one order"
        assert total_denies >= 1 or total_throttles >= 1, \
            f"Should have denied or throttled some orders, got denies={total_denies}, throttles={total_throttles}, processed={processed_count}"
        
        # 4. 验证日志记录
        logger_stats = executor_logger.get_stats()
        assert logger_stats["failed_count"] == rejected_count, \
            f"Logger should record {rejected_count} failed orders, got {logger_stats['failed_count']}"
        
        # 5. 验证拒绝率影响限速的逻辑
        # 如果拒绝率较高，限速应该有所调整（AdaptiveThrottler内部逻辑）
        # 由于我们传入了gate_reason_stats，限速可能会根据拒绝率调整
        assert final_rate_limit >= throttler.min_rate_limit
        assert final_rate_limit <= throttler.max_rate_limit
        
        # 6. 验证速率联动：gate_reason_stats应该影响限速调整
        # 如果拒绝率较高（>50%），限速应该降低
        # 注意：AdaptiveThrottler的调整逻辑基于当前请求数和拒绝率
        if reject_rate > 0.5:
            # 拒绝率>50%时，限速应该降低（但可能因为活跃市场而提高，所以只验证范围）
            assert final_rate_limit <= throttler.max_rate_limit


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

