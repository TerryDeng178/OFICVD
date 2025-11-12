---
id: "TASK-F-Stage1-Optimize"
title: "F系列·STAGE1参数寻优（胜率&PNL专注）"
stage: "F/STAGE1"
priority: "P0"
status: "Planned"
owners: ["TBD"]
deps: ["TASK-B2 回测模式（独立运行）"]
estimate: "~2d 首轮；滚动复验 ~1d/折"
tags: ["Optimization","Stage1","Signals","OFI","CVD","CursorRunnable"]
created: "2025-11-13"
---

## 目标与判据
**核心目标（三窗口中位数口径）**  
- `win_rate_trades ≥ 35%`
- `avg_pnl_per_trade ≥ 0`
- `pnl_net ≥ 0`  
- 软约束：`trades_per_hour ≤ 30`（只防刷频，不做硬闸）  

**评分权重（Stage1 专注胜率&PNL）**
```json
{
  "win_rate_trades": 0.40,
  "pnl_net": 0.30,
  "avg_pnl_per_trade": 0.20,
  "trades_per_hour": 0.10,
  "trades_per_hour_threshold": 30,
  "cost_bps_on_turnover": 0.0
}
```

## 范围（Scope）
**纳入**
- 仅优化 **STAGE1 信号侧/确认侧**旋钮：弱信号节流、一致性阈值、连击、去重窗口、退出后冷静期、场景化阈值、融合阈值/连击与权重（确保 `w_ofi + w_cvd = 1`）。
- 评估以回测 B2 产物为准：`trades.jsonl`、`pnl_daily.jsonl`、`run_manifest.json`。
- 固定 Sink：`sqlite`；每批次跑前执行**双 Sink 预检（2min）**。
- 三窗口交叉验证（3 个不同时间窗取中位数）；支持早停与最大试验数上限。

**不纳入**
- 执行/成本层参数（maker/taker、滑点、延迟等）与策略执行器行为调整；这些在 Stage2/执行侧专项完成。

## 数据与时间窗
- 交易对：`BTCUSDT, ETHUSDT, BNBUSDT`（可扩展）
- 单窗时长：60 分钟（默认），三窗交叉验证
- 时区切日：`Asia/Tokyo`
- 输入源：`deploy/data/ofi_cvd`（或你当前回测数据根目录）

## 实验组与搜索空间
### F1｜入口质量闸（弱信号/一致性/连击）
- `signal.weak_signal_threshold`: 0.75 → 0.82（步长 0.01）
- `signal.consistency_min`: 0.45 → 0.55（步长 0.01）
- `components.fusion.min_consecutive`: 3 / 4 / 5
- `signal.dedupe_ms`: 4000 / 6000 / 8000
- `execution.cooldown_ms`: 500 / 800 / 1200  

### F2｜融合权重与阈值（提升“信号纯度”）
- `components.fusion.w_ofi, components.fusion.w_cvd`: (0.7,0.3) | (0.6,0.4) | (0.5,0.5)  且 `w_ofi+w_cvd=1.0`
- `thresholds.active.buy/sell`: 1.2 / 1.5 / 1.8
- `execution.adaptive_cooldown_k`: 0.8 / 1.0 / 1.2

### F3｜反向防抖 & 翻向重臂（抑制亏损翻手）
- `execution.flip_rearm_margin`: 0.5 / 0.8 / 1.0
- `execution.cooldown_after_exit_sec`: 60 / 120 / 180  

### F4｜场景化阈值（活跃/安静分档）
- A_H/Q_H：在 F1 最优全局基线基础上做偏移：`weak +0.02`、`consistency_min +0.02`、`min_consecutive +1`
- A_L/Q_L：沿用全局基线  

## 基线与参照
- **推荐基线**：采用「Trial-5」参数（唯一满足三条主判据的 Trial），作为 F2/F3/F4 的起始对照：
```yaml
signal:
  weak_signal_threshold: 0.76
  consistency_min: 0.53
  dedupe_ms: 8000
components:
  fusion:
    min_consecutive: 3
execution:
  cooldown_ms: 500
```
- 本轮输出对比时，重点关注：
  - 胜率≥35% 保持不降；
  - `avg_pnl_per_trade` 与 `pnl_net` 不低于基线；
  - 频率保持 ≤30/h；样本量过低（<10 笔）须打 “low_sample” 告警。

## 执行命令（Cursor 可直接跑）
### 批量执行（四组并行）
```powershell
python scripts/param_search.py ^
  --group-config runtime/optimizer/group_f1_entry_gating.yaml ^
  --search-space tasks/TASK-09/search_space_f1.json ^
  --mode B --signals-src sqlite://./runtime/signals.sqlite ^
  --out-root ./runtime/optimizer/out ^
  --symbols BTCUSDT,ETHUSDT,BNBUSDT ^
  --start 2025-11-10T00:00:00Z --end 2025-11-10T23:59:59Z ^
  --tz Asia/Tokyo --seed 42 --max-workers 6 --max-trials 200
```

### 单组执行（示例：F2）
```powershell
python scripts/param_search.py ^
  --group-config runtime/optimizer/group_f2_fusion.yaml ^
  --search-space tasks/TASK-09/search_space_f2.json ^
  --mode B --signals-src sqlite://./runtime/signals.sqlite ^
  --out-root ./runtime/optimizer/out ^
  --symbols BTCUSDT,ETHUSDT,BNBUSDT ^
  --start 2025-11-10T00:00:00Z --end 2025-11-10T23:59:59Z ^
  --tz Asia/Tokyo --seed 42 --max-workers 6 --max-trials 200
```

## 业务流 & 约束
1. **预检**：先跑 2 分钟双 Sink 等价性（可选），失败即中止批次。  
2. **三窗交叉验证**：每个 Trial 在三段时间窗上重复，取中位数作为评分口径。  
3. **早停/预算**：支持 `--max-trials` 与 `--early-stop-rounds`；负 PnL 且 MDD 过大时，Trial 直接早停。  
4. **权重与门槛**：评分函数按本文权重执行；频率>30/h 触发警戒降权。  
5. **Top-K 入围**：各组保留 3–5 套满足三条主判据的参数，进入下一轮合并微调。  
6. **融合权重和为 1**：在优化器层面强约束 `w_ofi+w_cvd=1.0`。

## 产物与目录
每次批次输出目录示例：`runtime/optimizer/out/<run_id>/`
- `trial_results.json` / `trial_results.csv`（排行榜与明细）
- `trial_manifest.json`（批次元数据）
- `trial_<N>_config.yaml`（每个试验的最终配置）
- `trial_<N>_output/`（回测产物：`trades.jsonl`、`pnl_daily.jsonl`、`run_manifest.json`）
- `logs/`（预检、心跳与错误）

## DoD（Definition of Done）
- [ ] 四组（F1–F4）均完成至少一轮带交叉验证与早停的搜索，产出 `trial_results.csv/json`。  
- [ ] 至少 1 套参数**同时**满足：`win_rate_trades ≥35%`、`avg_pnl_per_trade ≥0`、`pnl_net ≥0`。  
- [ ] Top-K（每组 3–5 套）出炉，并与基线（Trial-5）做显著性对照。  
- [ ] 产物可复现：相同输入/种子下排行榜哈希一致；回测产物 Schema 与 B2 契约一致。  
- [ ] 报告页（Markdown）包含：Top-K 参数表、三窗曲线、low_sample 告警、后续建议。  

## 风险与对策
- **高胜率/负 PnL**：重点检查止盈/止损与成本侵蚀；若出现，优先转入 F2（提高纯度）或 F3（抑制翻向亏损）。  
- **样本量不足**：交易笔数 <10 的 Trial 打 `low_sample` 告警，降权或剔除。  
- **搜索爆炸**：优先 grid+max-trials 与早停；仅在 F1 收敛后再放开 F2/F3/F4。  

## 下一步（触发条件）
- 若 Top-K 多数仍 **avg_pnl_per_trade<0** 或 **pnl_net<0**：进入 F2（融合权重/阈值）与 F3（反向防抖）专案；  
- 若活跃时段胜率明显提升而频率未反弹：启用 F4 的 `scenario_overrides` 固化分档策略。  
