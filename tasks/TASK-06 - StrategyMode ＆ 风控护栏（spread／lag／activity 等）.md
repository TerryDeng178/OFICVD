# TASK-06 · StrategyMode & 风控护栏（spread/lag/activity 等）
> 里程碑：M2 | 更新：2025-11-05 (Asia/Tokyo)

## 背景
结合 `strategy_mode_manager.py`，实现交易时间窗/市场状态切换；在信号后加风险护栏（spread、lag、missing、activity）。

## 目标
- 风控规则可配置（`config.defaults.yaml:risk.gates.*`）；
- `CoreAlgo` 输出携带 `gating` 标记；
- 提供单元测试用例。

## 验收标准
- [ ] 当 `spread_bps` 超阈、或 `lag_sec` 超阈时，信号被屏蔽且记录原因；  
- [ ] 低活跃（activity）时仅观测不下单。
