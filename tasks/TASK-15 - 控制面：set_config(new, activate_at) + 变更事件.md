# 控制面：set_config(new, activate_at) + 变更事件
**任务编号**: TASK-19  
**批次**: M2  
**优先级**: P1  
**所属模块**: orchestrator

## 背景
安全地热切换参数并可回滚。

## 目标
提供配置变更 API；记录变更事件（旧/新/指纹/操作者/时间）。

## 前置依赖
- TASK-16

## 输出物
- `POST /set_config` 可用
- 定时生效/回滚正常

## 实现步骤（Cursor 分步操作）
- [ ] 验证新配置并保存到 overrides.d
- [ ] `activate_at` 定时生效
- [ ] 写 `config_change.jsonl`

## 验收标准（Acceptance Criteria）
- 定时切换成功；异常回滚到旧版

## 验收命令/脚本
`curl -X POST http://.../set_config -d @new.yaml`

## 代码改动清单（相对仓库根）
- orchestrator/config_plane.py（或合入 run.py）
- config/overrides.d/*

## 潜在风险与回滚
- 配置不兼容：先 dry-run 校验

## 预计工时
0.5 天
