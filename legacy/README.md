# Legacy Services (只读)

本目录包含已下线或冻结的MCP服务代码，仅作为示例/备档保留，**不进入部署链路**。

## 服务清单

- **data_feed_server**: 功能由 `harvest_server` 覆盖，无需单独服务
- **ofi_feature_server**: 特征计算在库层（`alpha_core.microstructure.*`），由 `signal_server` 内部调用
- **ofi_risk_server**: 逻辑已合并到 `strategy_server/risk/`，保留为只读参考

## 迁移说明

- **data_feed_server** → 功能已由 `harvest_server` 实现
- **ofi_feature_server** → 特征计算逻辑在 `src/alpha_core/microstructure/`，由 `signal_server` 调用
- **ofi_risk_server** → 风控逻辑已迁移到 `mcp/strategy_server/risk/`

## 注意事项

- **不要修改**：这些文件已标记为只读，不应修改
- **不要引用**：新代码不应引用这些服务
- **仅供参考**：如需了解历史实现，可查看此目录

