# CI：Mermaid/JSON 契约校验 + Smoke 起停
**任务编号**: TASK-22  
**批次**: M2  
**优先级**: P1  
**所属模块**: ci

## 背景
降低回归风险，形成最小但有用的自动化保障。

## 目标
GitHub Actions：ruff/flake8、JSON 契约校验、服务起停 smoke。

## 前置依赖
- TASK-01..21

## 输出物
- `.github/workflows/ci.yml` 通过

## 实现步骤（Cursor 分步操作）
- [ ] 规范检查（ruff/flake8）
- [ ] `docs/api_contracts.md` 示例 JSON 做 schema 校验
- [ ] 启动 5 服务→跑一次 orchestrator→断言日志产出

## 验收标准（Acceptance Criteria）
- PR 必须通过 CI 才能合并

## 验收命令/脚本
（推送触发）

## 代码改动清单（相对仓库根）
- .github/workflows/ci.yml

## 潜在风险与回滚
- 端口占用：使用动态端口

## 预计工时
0.5~1 天
