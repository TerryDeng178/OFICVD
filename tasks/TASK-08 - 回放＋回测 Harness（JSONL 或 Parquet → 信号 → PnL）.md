# TASK-08 · 回放/回测 Harness（JSONL/Parquet → 信号 → PnL）
> 里程碑：M3 | 更新：2025-11-05 (Asia/Tokyo)

## 目标
- 读取历史分片（jsonl/parquet），按时间顺序回放；
- 调用 CoreAlgo 生成信号，使用撮合规则与费用模型计算 PnL；
- 指标：胜率、盈亏比、交易频次、毛收益与手续费对比。

## 成果物
- 代码：`backtest/replay.py`, `backtest/eval.py`（目录可自定）；
- 文档：`/docs/architecture_flow.md` 增加“回放/回测”泳道；
- 报表：`reports/backtest/*.jsonl` + 汇总 CSV。

## 验收标准
- [ ] 给定 24 小时样本，目标指标可输出；  
- [ ] 费用模型可配置（maker/taker, bps）。
