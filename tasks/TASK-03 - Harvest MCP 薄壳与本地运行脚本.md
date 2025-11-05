# TASK-03 · Harvest MCP 薄壳与本地运行脚本
> 里程碑：M1 | 更新：2025-11-05 (Asia/Tokyo)

## 目标
- 最薄的 MCP 服务：`mcp/harvest_server/app.py` 调用 `alpha_core.ingestion.harvester.run_ws_harvest`;  
- 提供命令行参数与 env 支持；  
- 本地脚本：`scripts/harvest_local.sh` 一键启动。

## 成果物
- 文件：`mcp/harvest_server/app.py`, `scripts/harvest_local.sh`  
- 文档：README “M1 · 安装与本地采集”命令可直接运行。

## 步骤清单
- [ ] `argparse`：`--config --output --format --rotate.max_rows --rotate.max_sec`；  
- [ ] 捕获异常并友好退出码；  
- [ ] 记录启动参数与版本到日志。

## 验收标准
- [ ] 在空仓库环境 `pip install -e .` 后可一键启动采集；  
- [ ] 轮转生成的分区路径正确；  
- [ ] CTRL+C 优雅退出。
