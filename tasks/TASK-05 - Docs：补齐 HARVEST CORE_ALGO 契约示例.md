# Docs：补齐 HARVEST/CORE_ALGO 契约示例
**任务编号**: TASK-05  
**批次**: M1  
**优先级**: P1  
**所属模块**: docs

## 背景
在 `/docs/api_contracts.md` 中补充 HARVEST 和 CORE_ALGO 的接口契约与示例

## 目标
- 完善 HARVEST 接口文档
- 完善 CORE_ALGO 接口文档
- 提供请求/响应示例

## 前置依赖
- TASK-03（HARVEST）
- TASK-04（CORE_ALGO）

## 输出物
- 更新 `/docs/api_contracts.md`

## 实现步骤（Cursor 分步操作）
- [ ] 添加 HARVEST 接口契约
- [ ] 添加 CORE_ALGO 接口契约
- [ ] 提供请求/响应示例
- [ ] 添加错误处理说明

## 验收标准（Acceptance Criteria）
- 文档完整，示例可运行
- 与代码实现一致

## 验收命令/脚本
```bash
# 文档检查
grep -r "HARVEST\|CORE_ALGO" docs/api_contracts.md
```

## 代码改动清单（相对仓库根）
- docs/api_contracts.md

## 潜在风险与回滚
- 文档与实现不一致：定期同步更新

## 预计工时
0.5 天

