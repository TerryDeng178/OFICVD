# Data MCP：历史回放（Parquet/CSV）
**任务编号**: TASK-07  
**批次**: M1  
**优先级**: P0  
**所属模块**: data

## 背景
回放=实时一致性验证的关键；同一接口输出。

## 目标
实现 `/get_historical_slice(start,end)`；分页/流式返回 Row Schema 批次。

## 前置依赖
- TASK-01

## 输出物
- 能从 parquet/csv 回放窗口数据
- 与实时结构完全一致

## 实现步骤（Cursor 分步操作）
- [ ] 实作 reader（pyarrow 或 csv）
- [ ] 支持 tz 解析
- [ ] 批量组装为标准行结构
- [ ] 小样本单测

## 验收标准（Acceptance Criteria）
- 指定窗口可稳定回放；性能满足 1h 数据 ≤1s 内分批输出（本地）

## 验收命令/脚本
（可选）`python mcp/data_feed_server/cli.py slice --from ... --to ...`

## 代码改动清单（相对仓库根）
- mcp/data_feed_server/app.py 或 reader.py

## 潜在风险与回滚
- 列名/类型不对齐：增加映射表
- 大文件内存压力：流式迭代

## 预计工时
1 天
