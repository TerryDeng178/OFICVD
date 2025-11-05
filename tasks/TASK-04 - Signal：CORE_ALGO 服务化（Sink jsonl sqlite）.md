# Signal：CORE_ALGO 服务化（Sink: jsonl/sqlite）
**任务编号**: TASK-04  
**批次**: M1  
**优先级**: P0  
**所属模块**: signal

## 背景
将核心算法封装为 CORE_ALGO 服务，支持可插拔 Sink（JSONL/SQLite）

## 目标
- 封装 `alpha_core.signals.core_algo` 为可复用库
- 实现 CORE_ALGO MCP 服务器薄壳
- 支持 JSONL/SQLite 双 Sink
- 提供健康度指标

## 前置依赖
- TASK-08（alpha_core 打包）
- TASK-10（compute_features 接线）

## 输出物
- `src/alpha_core/signals/core_algo.py`（已移动，需完善导入）
- `mcp/signal_server/app.py`（MCP 薄壳）
- 信号输出文件（jsonl/sqlite）

## 实现步骤（Cursor 分步操作）
- [ ] 修复 `core_algo.py` 中的导入路径
- [ ] 实现 CORE_ALGO MCP 服务器接口
- [ ] 实现可插拔 Sink（JSONL/SQLite）
- [ ] 实现健康度指标输出

## 验收标准（Acceptance Criteria）
- CORE_ALGO 可独立运行，输出信号格式正确
- Sink 切换正常，数据可回放

## 验收命令/脚本
```bash
V13_SINK=jsonl python -m mcp.signal_server.app --config ./config/defaults.yaml
```

## 代码改动清单（相对仓库根）
- src/alpha_core/signals/core_algo.py
- mcp/signal_server/app.py

## 潜在风险与回滚
- 导入路径错误：统一使用 alpha_core 包路径
- Sink 性能问题：优化写入逻辑

## 预计工时
1-2 天

