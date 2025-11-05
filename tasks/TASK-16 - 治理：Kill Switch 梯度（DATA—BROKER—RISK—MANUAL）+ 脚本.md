# 治理：Kill Switch 梯度（DATA/BROKER/RISK/MANUAL）+ 脚本
**任务编号**: TASK-16  
**批次**: M1  
**优先级**: P0  
**所属模块**: ops

## 背景
黑天鹅与异常时必须一键停手，并能快速恢复。

## 目标
支持多原因 HOLD；提供脚本与 README。

## 前置依赖
- TASK-08, TASK-12

## 输出物
- `set_trading_mode(HOLD)` 等 API
- `scripts/hold.sh`/`resume.sh`

## 实现步骤（Cursor 分步操作）
- [ ] 风控 server 增加 `set_trading_mode`
- [ ] Orchestrator 读取 mode 决策
- [ ] 包装脚本：hold/resume

## 验收标准（Acceptance Criteria）
- 脚本后 1s 内停止下单；恢复立即生效

## 验收命令/脚本
```bash
bash scripts/hold.sh
```

## 代码改动清单（相对仓库根）
- mcp/ofi_risk_server/app.py
- orchestrator/run.py
- scripts/hold.sh scripts/resume.sh

## 潜在风险与回滚
- 多处 mode 不一致：统一从风控读

## 预计工时
0.5 天
