# Orchestrator：编排与烟囱测试（M1→M3）
**任务编号**: TASK-06  
**批次**: M1  
**优先级**: P0  
**所属模块**: orchestrator

## 背景
实现 Orchestrator 主控循环，编排 HARVEST → CORE_ALGO → Risk → Broker 的完整流程

## 目标
- 实现主控循环
- 编排各 MCP 服务调用
- 实现烟囱测试（M1→M3）

## 前置依赖
- TASK-03（HARVEST）
- TASK-04（CORE_ALGO）
- TASK-12（Risk）
- TASK-14（Broker）

## 输出物
- 完整的编排流程
- 烟囱测试脚本

## 实现步骤（Cursor 分步操作）
- [ ] 实现主控循环
- [ ] 编排 HARVEST → CORE_ALGO → Risk → Broker
- [ ] 实现事件流记录（JSONL）
- [ ] 实现烟囱测试

## 验收标准（Acceptance Criteria）
- 完整流程可运行
- 事件流记录完整
- 烟囱测试通过

## 验收命令/脚本
```bash
python -m orchestrator.run --config ./config/defaults.yaml --enable harvest,signal,broker,report
```

## 代码改动清单（相对仓库根）
- orchestrator/run.py
- scripts/dev_run.sh

## 潜在风险与回滚
- 服务间通信失败：实现重试机制
- 事件流丢失：实现持久化

## 预计工时
1-2 天

