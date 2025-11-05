# Data MCP：接入真实 WS／Harvester（实时）
**任务编号**: TASK-02  
**批次**: M1  
**优先级**: P0  
**所属模块**: data

## 背景
当前为 mock，需要接入真实行情流或你的 harvester 缓存。

## 目标
在 `data_feed_server` 增加 backend=mock|ws|harvester；保证 Row Schema 完整。

## 前置依赖
- TASK-01

## 输出物
- `/get_live_snapshot` 返回真实批次
- `config/defaults.yaml:data.*` 支持 backend 配置

## 实现步骤（Cursor 分步操作）
- [ ] 新增 `backend` 参数与工厂
- [ ] WS：订阅、缓冲、批量吐数；Harvester：共享内存/本地队列读取
- [ ] 统一填充 exch_seq/lag_ms；异常自动重连与退避

## 验收标准（Acceptance Criteria）
- 网络断开时服务不崩溃；rows.len≈limit；字段完整

## 验收命令/脚本
（按具体接入库给出命令；先保留 mock 与 env 切换）

## 代码改动清单（相对仓库根）
- mcp/data_feed_server/app.py
- config/defaults.yaml

## 潜在风险与回滚
- WS 断连/频限：指数退避与 heartbeat
- 字段不一致：映射层统一字段

## 预计工时
1~1.5 天
