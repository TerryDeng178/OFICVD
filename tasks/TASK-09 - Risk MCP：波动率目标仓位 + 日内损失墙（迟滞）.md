# Risk MCP：波动率目标仓位 + 日内损失墙（迟滞）
**任务编号**: TASK-09  
**批次**: M1  
**优先级**: P0  
**所属模块**: risk

## 背景
控制头寸规模与回撤，建立可上线的底线保护。

## 目标
在 `propose_order` 里加入 `w=min(cap,k/vol)` 与 `daily_loss_limit_pct`；超限进入 HOLD_RISK，带迟滞恢复。

## 前置依赖
- TASK-08

## 输出物
- 允许/拒绝、建议 qty/lev、risk_state

## 实现步骤（Cursor 分步操作）
- [ ] 读取 rolling 波动或常数 vol_annualized
- [ ] 计算 w 与目标头寸
- [ ] 亏损超阈→HOLD_RISK；恢复条件：阈×β

## 验收标准（Acceptance Criteria）
- 人工构造亏损示例后能进入 HOLD 并保持；满足条件才恢复

## 验收命令/脚本
模拟账务输入即可

## 代码改动清单（相对仓库根）
- mcp/ofi_risk_server/app.py

## 潜在风险与回滚
- 波动估计失真：先常数，后迭代

## 预计工时
0.5~1 天
