# Feature MCP：defaults.yaml → 组件构造器映射（V4）
**任务编号**: TASK-05  
**批次**: M1  
**优先级**: P0  
**所属模块**: feature

## 背景
以配置驱动组件实例化，避免硬编码。

## 目标
从 `config/defaults.yaml` 加载 OFI/CVD/Fusion/Divergence 配置，实例化单例；生成 cfg 指纹。

## 前置依赖
- TASK-04

## 输出物
- 服务启动打印关键配置
- `/compute_features` 可工作

## 实现步骤（Cursor 分步操作）
- [ ] `mcp/ofi_feature_server/config_loader.py` 映射 YAML→Config 类
- [ ] 启动时加载实例化；生成 cfg_fingerprint
- [ ] （可选）`/_config`、`/reload_config`

## 验收标准（Acceptance Criteria）
- 成功打印配置摘要；API 正常返回

## 验收命令/脚本
```bash
curl -s http://localhost:9002/compute_features -X POST -H 'Content-Type: application/json' -d '{"rows":[]}'
```

## 代码改动清单（相对仓库根）
- mcp/ofi_feature_server/{app.py,config_loader.py}
- config/defaults.yaml

## 潜在风险与回滚
- 类型不匹配：强制转换
- 热加载丢状态：先重启替代

## 预计工时
0.5 天
