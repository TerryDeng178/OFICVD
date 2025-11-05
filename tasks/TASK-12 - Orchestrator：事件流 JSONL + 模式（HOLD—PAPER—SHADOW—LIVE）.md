# Orchestrator：事件流 JSONL + 模式（HOLD/PAPER/SHADOW/LIVE）
**任务编号**: TASK-16  
**批次**: M1  
**优先级**: P0  
**所属模块**: orchestrator

## 背景
保证可回放、可审计，并支持 Shadow 对照。

## 目标
写入 `ticks/decisions/orders/fills/pnl`；实现 SHADOW 不下发订单。

## 前置依赖
- TASK-01..14

## 输出物
- 运行 10 分钟生成全套事件流
- 切换 SHADOW 无真实下单

## 实现步骤（Cursor 分步操作）
- [ ] 写入 decisions/orders/fills
- [ ] MODE=SHADOW：只生成不下发
- [ ] 回放 CLI：`--from --to`
- [ ] Kill Switch 钩子

## 验收标准（Acceptance Criteria）
- 文件齐全、字段齐全；SHADOW 行为正确

## 验收命令/脚本
```bash
MODE=SHADOW python orchestrator/run.py
```

## 代码改动清单（相对仓库根）
- orchestrator/run.py
- logs/*

## 潜在风险与回滚
- 日志丢失：使用 flush/锁（后续）

## 预计工时
0.5 天
