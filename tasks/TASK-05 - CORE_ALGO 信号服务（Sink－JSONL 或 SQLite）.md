# TASK-05 · CORE_ALGO 信号服务（Sink: JSONL/SQLite）
> 里程碑：M2 | 更新：2025-11-05 (Asia/Tokyo)

## 背景
统一信号服务，融合 OFI/CVD/FUSION/DIVERGENCE，施加一致性与护栏；可插拔 Sink：JSONL / SQLite。

## 目标
- 模块：`src/alpha_core/signals/core_algo.py`（`class CoreAlgo`）；
- 薄壳：`mcp/signal_server/app.py` 暴露 CLI / HTTP（可选）；
- 环境变量：`V13_SINK`、`V13_OUTPUT_DIR`、`V13_REPLAY_MODE`、`V13_DEBUG`。

## 成果物
- 代码：`CoreAlgo.process(feature_row)->signal_row`；
- 落地：`runtime/signals*.jsonl` 或 `runtime/signals.db`；
- 文档：README 中的“3.3 CORE_ALGO → 风控/执行”。

## 验收标准
- [ ] 连续运行 2 小时无漏写；  
- [ ] SQLite 模式下并发读不阻塞（WAL）；  
- [ ] `confirm/gating` 字段含义与文档一致。
