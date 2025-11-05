# TASK-01 · 统一 Row Schema & 出站 DQ Gate（Data Contract）
> 里程碑：M1 · 数据打通 | 更新：2025-11-05 (Asia/Tokyo)

## 背景
采集层（HARVEST）需要对接多类 WS 主题（aggTrade / bookTicker / depth@100ms）。为保证**上下游可复用**与**回放一致性**，需统一行级 Schema，并在**出站**设置 DQ（数据质量）闸门。

## 目标
- 固定 **Row Schema** 字段与类型；
- 在出站前完成 **stale/空窗/字段缺失/异常量** 拦截；
- 提供 **JSONL/Parquet** 双落地格式与路径规范；
- 形成 `/docs/api_contracts.md` 的对应章节（示例样本 10 条）。

## 成果物
- 代码：`src/alpha_core/ingestion/harvester.py`（导出 `normalize_row`, `dq_gate`）  
- 配置：`config/defaults.yaml` → `harvest.dq`, `harvest.output`  
- 样例：`data/ofi_cvd/date=YYYY-MM-DD/hour=HH/symbol=btcusdt/kind=orderbook/*.parquet|jsonl`  
- 文档：`/docs/api_contracts.md`（“3.1 HARVEST → 特征层”）

## Row Schema（建议）
```json
{
  "ts_ms": 1730790000123,
  "symbol": "BTCUSDT",
  "src": "aggTrade|bookTicker|depth",
  "price": 70321.5,
  "qty": 0.01,
  "side": "buy|sell|null",
  "bid": 70321.4,
  "ask": 70321.6,
  "best_spread_bps": 1.4,
  "meta": {"latency_ms": 12, "recv_ts_ms": 1730790000125}
}
```

## DQ 规则（最低集）
- `stale_ms`：消息接收与 `ts_ms` 之差超过阈值 → 丢弃或打标；  
- `require_fields`: 缺字段 → 丢弃；  
- `spread_bps`：若 bid/ask 缺失，用上次有效值；仍缺则打标；  
- `qty<=0` → 丢弃；`price<=0` → 丢弃。

## 步骤清单
- [ ] 在 `harvester.py` 实现 `normalize_row(event)->dict`；  
- [ ] 在 `harvester.py` 实现 `dq_gate(row)->(ok:bool, reason:str)`；  
- [ ] 支持 `jsonl/parquet` 两种落地；  
- [ ] 输出路径遵循分区：`date=/hour=/symbol=/kind=`；  
- [ ] 增加 10 条样本至 `/docs/api_contracts.md`。

## 验收标准
- [ ] 本地运行 10 分钟，无报错，DQ 丢弃率<5%；  
- [ ] Parquet 可被 pandas/pyarrow 读取；  
- [ ] Schema 字段、命名、类型与文档一致。
