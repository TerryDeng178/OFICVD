# -*- coding: utf-8 -*-
"""实时执行 Worker

持续消费 signal_server 产物，执行幂等控制，写入 executions 记录
"""
import asyncio
import logging
import signal
import time
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import json
import yaml

from .signal_stream import SignalStream, ExecutionSignal, create_signal_stream
from .execution_store import ExecutionStore, ExecutionRecord
from .execution_adapters import ExecutionAdapter, DryRunExecutionAdapter, create_execution_adapter, ExecutionRequest
from .execution_metrics import get_execution_metrics
from .base_executor import ExecResult, ExecResultStatus

logger = logging.getLogger(__name__)


@dataclass
class ExecutionConfig:
    """执行 Worker 配置"""

    enabled: bool = True
    mode: str = "dry_run"  # dry_run | live
    symbols: List[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    sink_type: str = "jsonl"  # jsonl | sqlite
    output_dir: str = "./runtime"
    rate_limit_qps: int = 10
    max_concurrency: int = 2
    retry_max_attempts: int = 3
    retry_backoff_ms: int = 500

    # 业务参数配置
    long_score_threshold: float = 0.5    # score > threshold 时做多
    short_score_threshold: float = -0.5  # score < threshold 时做空
    base_order_qty: float = 100.0        # 基础订单数量

    # 调试配置
    log_skipped_signals: bool = False    # 是否记录被跳过的信号


class ExecutionWorker:
    """实时执行 Worker

    持续消费 signal_server 产物，执行幂等控制，写入 executions 记录
    """

    def __init__(self, config: ExecutionConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # 初始化指标收集
        self.metrics = get_execution_metrics()

        # 初始化skip信号记录器（如果启用）
        self._skipped_signals_log = None
        if config.log_skipped_signals:
            self._init_skipped_signals_log()

        # 初始化组件
        self.signal_stream = create_signal_stream(
            sink_type=config.sink_type,
            base_dir=config.output_dir,
            symbols=config.symbols
        )

        self.execution_store = ExecutionStore(
            db_path=Path(config.output_dir) / "executions" / "executions.db"
        )

        # 高水位对齐：用 execution_store 的高水位初始化 signal_stream，避免重启时重复读取历史信号
        self._align_high_water_marks()

        # 初始化全局QPS限速器
        self._qps_semaphore = asyncio.Semaphore(config.rate_limit_qps)

        # 初始化适配器
        self.adapter = create_execution_adapter(config.mode, config.__dict__ if hasattr(config, '__dict__') else {})

        # 运行状态
        self.running = False
        self._shutdown_event = asyncio.Event()

        # 统计信息
        self.stats = {
            "signals_processed": 0,
            "executions_success": 0,
            "executions_skip": 0,
            "executions_failed": 0,
            "executions_retry": 0,
            "start_time": None,
            "last_signal_ts": None,
        }

    async def run(self) -> None:
        """启动执行 Worker"""
        self.logger.info("启动执行 Worker")
        self.running = True
        self.stats["start_time"] = time.time()

        # 设置信号处理器
        def signal_handler(signum, frame):
            self.logger.info(f"收到信号 {signum}，准备关闭...")
            self._shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            # 创建并发任务
            tasks = []
            semaphore = asyncio.Semaphore(self.config.max_concurrency)

            # 启动QPS令牌补充任务
            qps_refill_task = asyncio.create_task(self._qps_refill_worker())
            tasks.append(qps_refill_task)

            for symbol in self.config.symbols:
                task = asyncio.create_task(
                    self._process_symbol_signals(symbol, semaphore)
                )
                tasks.append(task)

            # 等待所有任务完成或收到关闭信号
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            self.logger.error(f"执行 Worker 运行异常: {e}")
        finally:
            self.running = False
            self._log_final_stats()
            await self._cleanup()

    async def _process_symbol_signals(self, symbol: str, semaphore: asyncio.Semaphore) -> None:
        """处理单个交易对的信号"""
        self.logger.info(f"开始处理交易对 {symbol} 的信号")

        try:
            async for signal in self.signal_stream.iter_signals(symbol):
                if self._shutdown_event.is_set():
                    break

                # 更新统计信息
                self.stats["signals_processed"] += 1
                self.stats["last_signal_ts"] = signal.ts_ms

                # 收集metrics
                self.metrics.increment_signals_processed()

                # 计算延迟
                lag_ms = int(time.time() * 1000) - signal.ts_ms
                self.metrics.observe_lag(lag_ms)
                self.logger.debug(f"处理信号 {signal.symbol}@{signal.ts_ms}, 延迟: {lag_ms}ms")

                # 全局QPS限速 + 并发控制
                async with self._qps_semaphore:
                    async with semaphore:
                        # 更新并发数metrics
                        self.metrics.inc_concurrency()
                        try:
                            await self._process_single_signal(signal)
                        finally:
                            self.metrics.dec_concurrency()

        except Exception as e:
            self.logger.error(f"处理交易对 {symbol} 信号时出错: {e}")

        self.logger.info(f"停止处理交易对 {symbol} 的信号")

    async def _process_single_signal(self, signal: ExecutionSignal) -> None:
        """处理单个信号"""
        try:
            # 1. 准备执行请求
            exec_request = self._prepare_execution_request(signal)

            # 如果是 skip，直接跳过，不记录到数据库
            if exec_request["side"] == "skip":
                self.logger.debug(f"信号被跳过: {signal.symbol}/{signal.signal_id}")
                self.stats["executions_skip"] += 1
                self.metrics.increment_result("skip")
                self._log_skipped_signal(signal, "business_rule")
                return

            # 2. 检查幂等性
            if await self.execution_store.is_already_executed(
                signal.symbol, signal.signal_id, exec_request["order_id"]
            ):
                self.logger.debug(f"信号已执行，跳过: {signal.symbol}/{signal.signal_id}")
                self.stats["executions_skip"] += 1
                self.metrics.increment_result("skip")
                self._log_skipped_signal(signal, "idempotency")
                return

            # 3. 执行下单
            result = await self._execute_order(exec_request)

            # 4. 记录执行结果
            await self._record_execution(signal, exec_request, result)

            # 5. 更新统计
            self._update_stats(result)

        except Exception as e:
            self.logger.error(f"处理信号失败 {signal.symbol}/{signal.signal_id}: {e}")
            # 记录失败的执行
            await self._record_failed_execution(signal, str(e))
            self.stats["executions_failed"] += 1

    def _gate_passed(self, gating) -> bool:
        """统一gating判定，兼容str/list/None格式"""
        if gating is None:
            return True
        if isinstance(gating, str):
            return gating == "ok"
        if isinstance(gating, (list, tuple, set)):
            # 允许 "ok" 或所有以 "_passed" 结尾的通过型标签
            return ("ok" in gating) or all(isinstance(x, str) and x.endswith("_passed") for x in gating) or len(gating) == 0
        return False

    def _prepare_execution_request(self, signal: ExecutionSignal) -> Dict[str, Any]:
        """准备执行请求"""
        # 基于 confirm 和 gating 决定是否执行
        if not signal.confirm or not self._gate_passed(signal.gating):
            side = "skip"
            qty = 0.0
            price = None
        else:
            # 基于配置的阈值进行交易决策
            if signal.score > self.config.long_score_threshold:
                side = "long"
                qty = self.config.base_order_qty
                price = None  # 市价单
            elif signal.score < self.config.short_score_threshold:
                side = "short"
                qty = self.config.base_order_qty
                price = None  # 市价单
            else:
                side = "skip"
                qty = 0.0
                price = None

        order_id = f"dryrun:{signal.signal_id}" if self.config.mode == "dry_run" else f"live:{signal.signal_id}"

        return {
            "symbol": signal.symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "order_id": order_id,
            "signal_id": signal.signal_id,
        }

    async def _execute_order(self, exec_request: Dict[str, Any]) -> ExecResult:
        """执行订单（带重试机制）"""
        # 转换为适配器期望的格式
        adapter_request = ExecutionRequest(
            symbol=exec_request["symbol"],
            side=exec_request["side"],
            quantity=exec_request["qty"],
            price=exec_request["price"],
            client_order_id=exec_request["order_id"],
            signal_id=exec_request["signal_id"],
        )

        # 指数回退重试
        attempt = 0
        backoff = max(0.001, self.config.retry_backoff_ms / 1000.0)  # 转换为秒

        while True:
            result = await self.adapter.send_order(adapter_request)

            # 成功或达到最大重试次数时返回
            if result.status == ExecResultStatus.ACCEPTED or attempt >= self.config.retry_max_attempts:
                # 记录实际重试次数
                setattr(result, "retry_count", attempt)
                return result

            # 等待后重试
            await asyncio.sleep(backoff)
            backoff *= 2  # 指数回退
            attempt += 1

    async def _record_execution(
        self,
        signal: ExecutionSignal,
        exec_request: Dict[str, Any],
        result: ExecResult
    ) -> None:
        """记录执行结果"""
        exec_ts_ms = int(time.time() * 1000)

        record = ExecutionRecord(
            exec_ts_ms=exec_ts_ms,
            signal_ts_ms=signal.ts_ms,
            symbol=signal.symbol,
            signal_id=signal.signal_id,
            order_id=exec_request["order_id"],
            side=exec_request["side"],
            qty=exec_request["qty"],
            price=exec_request.get("price"),
            gating=json.dumps(signal.gating) if isinstance(signal.gating, (list, tuple)) else str(signal.gating),
            guard_reason=signal.guard_reason,
            status=self._map_result_status(result.status),
            error_code=getattr(result, 'reject_reason', None),
            error_msg=getattr(result, 'reject_reason', None),
            meta_json=json.dumps({
                **(result.meta if hasattr(result, 'meta') and result.meta else {}),
                "latency_ms": getattr(result, 'latency_ms', None),
                "slippage_bps": getattr(result, 'slippage_bps', None),
                "exchange_order_id": getattr(result, 'exchange_order_id', None),
                "adapter": self.adapter.__class__.__name__,
                "retry_count": getattr(result, "retry_count", 0),
            }, ensure_ascii=False)
        )

        await self.execution_store.record_execution(record)

    async def _qps_refill_worker(self) -> None:
        """QPS令牌补充工作协程"""
        while not self._shutdown_event.is_set():
            try:
                # 补充令牌到上限
                while self._qps_semaphore._value < self.config.rate_limit_qps:
                    self._qps_semaphore.release()
            except ValueError:
                # 信号量已满，跳过
                pass

            # 每秒补充一次
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break

    async def _record_failed_execution(self, signal: ExecutionSignal, error: str) -> None:
        """记录失败的执行"""
        exec_ts_ms = int(time.time() * 1000)

        record = ExecutionRecord(
            exec_ts_ms=exec_ts_ms,
            signal_ts_ms=signal.ts_ms,
            symbol=signal.symbol,
            signal_id=signal.signal_id,
            order_id=f"failed:{signal.signal_id}",
            side="skip",
            qty=0.0,
            price=None,
            gating=json.dumps(signal.gating) if isinstance(signal.gating, (list, tuple)) else str(signal.gating),
            guard_reason=signal.guard_reason,
            status="failed",
            error_msg=error,
            meta_json=json.dumps({"error": error}, ensure_ascii=False)
        )

        await self.execution_store.record_execution(record)

    def _map_result_status(self, status: ExecResultStatus) -> str:
        """映射执行结果状态"""
        if status == ExecResultStatus.ACCEPTED:
            return "success"
        elif status == ExecResultStatus.REJECTED:
            return "failed"
        else:
            return "unknown"

    def _align_high_water_marks(self) -> None:
        """对齐高水位标记

        用 execution_store 中的高水位初始化 signal_stream，避免重启时重复读取已处理信号
        """
        for symbol in self.config.symbols:
            stored_hw = self.execution_store.get_high_water_mark(symbol)
            if stored_hw > 0:
                self.signal_stream.update_high_water_mark(symbol, stored_hw)
                self.logger.info(f"对齐高水位 {symbol}: {stored_hw}")

    def _update_stats(self, result: ExecResult) -> None:
        """更新统计信息"""
        if result.status == ExecResultStatus.ACCEPTED:
            self.stats["executions_success"] += 1
            self.metrics.increment_result("success")
        else:
            self.stats["executions_failed"] += 1
            self.metrics.increment_result("failed")

        # 更新成功率
        total_attempts = self.stats["executions_success"] + self.stats["executions_failed"]
        if total_attempts > 0:
            success_rate = self.stats["executions_success"] / total_attempts
            self.metrics.update_success_rate(self.stats["executions_success"], total_attempts)

    def _init_skipped_signals_log(self) -> None:
        """初始化跳过信号记录器"""
        import json
        from pathlib import Path

        log_path = Path(self.config.output_dir) / "executions" / "skipped_signals.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # 打开文件用于追加写入
        self._skipped_signals_log = open(log_path, 'a', encoding='utf-8')
        self.logger.info(f"启用跳过信号记录: {log_path}")

    def _log_skipped_signal(self, signal: ExecutionSignal, reason: str) -> None:
        """记录被跳过的信号"""
        if not self._skipped_signals_log:
            return

        try:
            record = {
                "ts_ms": int(time.time() * 1000),  # 记录时间
                "signal_ts_ms": signal.ts_ms,
                "symbol": signal.symbol,
                "signal_id": signal.signal_id,
                "score": signal.score,
                "z_ofi": signal.z_ofi,
                "z_cvd": signal.z_cvd,
                "regime": signal.regime,
                "div_type": signal.div_type,
                "confirm": signal.confirm,
                "gating": signal.gating,
                "guard_reason": signal.guard_reason,
                "skip_reason": reason
            }

            self._skipped_signals_log.write(json.dumps(record, ensure_ascii=False) + '\n')
            self._skipped_signals_log.flush()  # 立即写入

        except Exception as e:
            self.logger.warning(f"记录跳过信号失败: {e}")

    def _log_final_stats(self) -> None:
        """记录最终统计信息"""
        runtime = time.time() - (self.stats["start_time"] or time.time())

        # 记录metrics摘要
        self.metrics.log_summary()

        self.logger.info("=" * 50)
        self.logger.info("执行 Worker 统计信息:")
        self.logger.info(f"运行时间: {runtime:.2f}秒")
        self.logger.info(f"处理信号数: {self.stats['signals_processed']}")
        self.logger.info(f"成功执行数: {self.stats['executions_success']}")
        self.logger.info(f"跳过执行数: {self.stats['executions_skip']}")
        self.logger.info(f"失败执行数: {self.stats['executions_failed']}")
        self.logger.info(f"重试执行数: {self.stats['executions_retry']}")
        if self.stats["last_signal_ts"]:
            self.logger.info(f"最后信号时间戳: {self.stats['last_signal_ts']}")
        self.logger.info("=" * 50)

    async def _cleanup(self) -> None:
        """清理资源"""
        try:
            if hasattr(self.signal_stream, 'close'):
                self.signal_stream.close()
            await self.execution_store.close()

            # 关闭skip信号日志文件
            if self._skipped_signals_log:
                try:
                    self._skipped_signals_log.close()
                    self._skipped_signals_log = None
                except Exception as e:
                    self.logger.warning(f"关闭skip信号日志文件失败: {e}")

        except Exception as e:
            self.logger.warning(f"清理资源时出错: {e}")


async def run_execution_worker(config: ExecutionConfig) -> None:
    """运行执行 Worker 的辅助函数"""
    worker = ExecutionWorker(config)
    await worker.run()


def load_execution_config(config_path: str, cli_symbols: Optional[str] = None) -> ExecutionConfig:
    """加载执行配置

    Args:
        config_path: 配置文件路径
        cli_symbols: CLI指定的交易对列表（逗号分隔）

    Returns:
        ExecutionConfig: 完整的配置对象
    """
    # 1. 读取 defaults.yaml
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            full_config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning(f"配置文件不存在: {config_path}，使用默认配置")
        full_config = {}
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}，使用默认配置")
        full_config = {}

    # 2. 提取 execution 配置，设置默认值
    exec_cfg = full_config.get('execution', {})

    # 3. 环境变量覆盖
    exec_cfg_overridden = {
        'enabled': exec_cfg.get('enabled', True),
        'mode': os.getenv('V13_EXECUTION_MODE', exec_cfg.get('mode', 'dry_run')),
        'symbols': exec_cfg.get('symbols', ['BTCUSDT', 'ETHUSDT']),
        'sink_type': os.getenv('V13_SINK', exec_cfg.get('sink', {}).get('kind', 'jsonl')),
        'output_dir': os.getenv('V13_OUTPUT_DIR', exec_cfg.get('sink', {}).get('base_dir', './runtime')),
        'rate_limit_qps': exec_cfg.get('rate_limit', {}).get('max_qps', 10),
        'max_concurrency': exec_cfg.get('rate_limit', {}).get('max_concurrency', 2),
        'retry_max_attempts': exec_cfg.get('retry', {}).get('max_attempts', 3),
        'retry_backoff_ms': exec_cfg.get('retry', {}).get('backoff_ms', 500),
        # 业务参数配置
        'long_score_threshold': exec_cfg.get('business', {}).get('long_score_threshold', 0.5),
        'short_score_threshold': exec_cfg.get('business', {}).get('short_score_threshold', -0.5),
        'base_order_qty': exec_cfg.get('business', {}).get('base_order_qty', 100.0),
        # 调试配置
        'log_skipped_signals': exec_cfg.get('debug', {}).get('log_skipped_signals', False),
    }

    # 4. CLI symbols 覆盖
    if cli_symbols:
        exec_cfg_overridden['symbols'] = [s.strip() for s in cli_symbols.split(",") if s.strip()]

    # 5. 创建配置对象
    config = ExecutionConfig(**exec_cfg_overridden)

    logger.info("执行配置加载完成:")
    logger.info(f"  模式: {config.mode}")
    logger.info(f"  交易对: {config.symbols}")
    logger.info(f"  Sink类型: {config.sink_type}")
    logger.info(f"  输出目录: {config.output_dir}")
    logger.info(f"  QPS限制: {config.rate_limit_qps}")
    logger.info(f"  最大并发: {config.max_concurrency}")
    logger.info(f"  多头阈值: {config.long_score_threshold}")
    logger.info(f"  空头阈值: {config.short_score_threshold}")
    logger.info(f"  基础数量: {config.base_order_qty}")
    logger.info(f"  记录跳过信号: {config.log_skipped_signals}")

    return config


def main():
    """CLI 入口点"""
    import argparse

    parser = argparse.ArgumentParser(description="实时执行 Worker")
    parser.add_argument("--config", type=str, default="./config/defaults.yaml",
                       help="配置文件路径")
    parser.add_argument("--symbols", type=str,
                       help="要处理的交易对列表（逗号分隔）")
    args = parser.parse_args()

    # 从配置文件加载配置
    config = load_execution_config(args.config, args.symbols)

    # 运行 Worker
    asyncio.run(run_execution_worker(config))


if __name__ == "__main__":
    main()
