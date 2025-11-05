# 回放一致性：Replay Harness（离线→在线对齐）
**任务编号**: TASK-17  
**批次**: M2  
**优先级**: P1  
**所属模块**: test

## 背景
确保回放=实时决策一致，避免“纸面胜利”。

## 目标
给定历史窗口，复现决策序列并与在线 decisions 对齐（允许微偏差）。

## 前置依赖
- TASK-03, TASK-12

## 输出物
- `scripts/replay.py` 输出对齐率报告

## 实现步骤（Cursor 分步操作）
- [ ] 读 `/get_historical_slice`
- [ ] 调 Feature/Risk 产出决策序列
- [ ] 与 `logs/decisions.jsonl` 对齐

## 验收标准（Acceptance Criteria）
- 对齐率≥95%（阈值可调）

## 验收命令/脚本
```bash
python scripts/replay.py --from ... --to ...
```

## 代码改动清单（相对仓库根）
- scripts/replay.py

## 潜在风险与回滚
- 数据缺口导致偏差：在报告注明并剔除

## 预计工时
0.5 天
