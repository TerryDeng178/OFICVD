# Feature MCP：generate_signal 稳定化（冷却/持仓最小/翻转滞后/Regime）
**任务编号**: TASK-07  
**批次**: M1  
**优先级**: P0  
**所属模块**: feature

## 背景
降低抖动与连环反向，提升可成交性与收益稳定性。

## 目标
输出 `{side:-1/0/1, quality:[0..1]}`，支持冷却、最小持仓时长、翻转滞后、Regime 收紧。

## 前置依赖
- TASK-06

## 输出物
- 高频噪声不开仓；连环翻转受限

## 实现步骤（Cursor 分步操作）
- [ ] 维护上次信号时间与方向
- [ ] `cooldown_secs`、`min_position_secs`
- [ ] `hysteresis_exit` 滞后
- [ ] Regime=低活跃→提高 `min_consistency`

## 验收标准（Acceptance Criteria）
- 高频噪声场景下 sig 翻转频次显著下降

## 验收命令/脚本
压力脚本（1000 批）

## 代码改动清单（相对仓库根）
- mcp/ofi_feature_server/app.py

## 潜在风险与回滚
- 过度抑制；参数可配

## 预计工时
0.5 天
