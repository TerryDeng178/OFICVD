# Report MCP：日报 + 分层指标 + 参数 Scoreboard
**任务编号**: TASK-14  
**批次**: M2  
**优先级**: P1  
**所属模块**: report

## 背景
让“赚在哪/亏在哪”一眼可见，驱动调参。

## 目标
输出 Markdown：胜率、盈亏比、EV/Trade、MDD、Sharpe、Turnover、成本占比、分时/Regime/一致性分层；参数榜按 cfg 指纹聚合。

## 前置依赖
- TASK-12, TASK-13

## 输出物
- `/daily_report?date=YYYY-MM-DD` 输出 Markdown

## 实现步骤（Cursor 分步操作）
- [ ] 读取事件流与 ledger
- [ ] 计算 KPI 与分层
- [ ] 生成 Markdown
- [ ] 参数指纹聚合

## 验收标准（Acceptance Criteria）
- 指标合理，与人工核验一致

## 验收命令/脚本
```bash
curl 'http://localhost:9005/daily_report?date=2025-11-05'
```

## 代码改动清单（相对仓库根）
- mcp/report_server/app.py

## 潜在风险与回滚
- 指标定义差异：文档给出定义

## 预计工时
0.5~1 天
