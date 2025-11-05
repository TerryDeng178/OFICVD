# Feature MCP：compute_features 接线（OFI/CVD/FUSION/DIVERGENCE）
**任务编号**: TASK-06  
**批次**: M1  
**优先级**: P0  
**所属模块**: feature

## 背景
将批量 ticks 转换为 z_ofi/z_cvd/fusion/divergence 输出。

## 目标
输出 `{z_ofi,z_cvd,fusion,divergence,fp}`；CVD 可在缺成交时退化。

## 前置依赖
- TASK-05

## 输出物
- 连续调用稳定；fusion.consistency ∈[0,1]

## 实现步骤（Cursor 分步操作）
- [ ] L1/L2 → RealOFI.update*
- [ ] Trades → RealCVD.update*
- [ ] Fusion/Divergence 生成方向/一致性/背离
- [ ] `fp = sha256(config_sha + last_ts + symbol)`

## 验收标准（Acceptance Criteria）
- 1 分钟压力跑无异常；指标随 z 变化合理

## 验收命令/脚本
`curl -s http://localhost:9002/compute_features ...`

## 代码改动清单（相对仓库根）
- mcp/ofi_feature_server/app.py

## 潜在风险与回滚
- 数据缺成交：优雅退化

## 预计工时
0.5~1 天
