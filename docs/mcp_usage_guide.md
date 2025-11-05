# MCP 服务器使用指南

## 概述

MCP（Model Context Protocol）服务器是薄壳层，提供命令行接口来调用核心功能。本项目的 MCP 服务器使用标准的 Python argparse 实现。

## 如何查看工具和调用规则

### 1. 查看帮助信息（显示所有可用工具和参数）

**PowerShell 命令**:
```powershell
# 查看 HARVEST MCP 服务器的帮助
python -m mcp.harvest_server.app --help
```

**输出示例**:
```
usage: app.py [-h] [--config CONFIG] [--output OUTPUT]
              [--format {jsonl,parquet}] [--rotate.max_rows ROTATE_MAX_ROWS]
              [--rotate.max_sec ROTATE_MAX_SEC]

Harvest MCP (薄壳)

options:
  -h, --help            show this help message and exit
  --config CONFIG       全局配置文件路径（默认: ./config/defaults.yaml）
  --output OUTPUT       输出根目录（覆盖 harvest.output.base_dir，默认: 使用配置中的路径）
  --format {jsonl,parquet}
                        输出格式（jsonl/parquet，默认: 使用配置中的格式）
  --rotate.max_rows ROTATE_MAX_ROWS
                        单文件最大行数（默认: 使用配置中的 harvest.rotate.max_rows）
  --rotate.max_sec ROTATE_MAX_SEC
                        轮转时间间隔（秒，默认: 使用配置中的 harvest.rotate.max_sec）

示例:
  python -m mcp.harvest_server.app --config ./config/defaults.yaml
  python -m mcp.harvest_server.app --config ./config/defaults.yaml --output ./data/ofi_cvd --format parquet
  python -m mcp.harvest_server.app --config ./config/defaults.yaml --rotate.max_rows 200000 --rotate.max_sec 60
```

### 2. 可用的 MCP 服务器工具

#### HARVEST 服务器（数据采集）
- **模块**: `mcp.harvest_server.app`
- **功能**: 实时采集 Binance Futures 数据（价格、订单簿、成交）
- **工具/参数**:
  - `--config`: 配置文件路径
  - `--output`: 输出目录
  - `--format`: 输出格式（jsonl/parquet）
  - `--rotate.max_rows`: 轮转最大行数
  - `--rotate.max_sec`: 轮转时间间隔

#### SIGNAL 服务器（信号生成）
- **模块**: `mcp.signal_server.app`
- **功能**: 生成交易信号
- **状态**: TODO（待实现）

#### BROKER 服务器（交易所网关）
- **模块**: `mcp.broker_gateway_server.app`
- **功能**: 订单管理和执行
- **状态**: TODO（待实现）

#### 其他服务器
- `mcp.data_feed_server.app`: 数据源接口
- `mcp.ofi_feature_server.app`: OFI 特征服务
- `mcp.ofi_risk_server.app`: 风险控制服务
- `mcp.report_server.app`: 报表服务

### 3. 调用规则

#### 基本调用格式

**PowerShell**:
```powershell
python -m mcp.<server_name>.app [参数]
```

#### HARVEST 服务器调用示例

**最小调用**（使用默认配置）:
```powershell
python -m mcp.harvest_server.app
```

**完整调用**（指定所有参数）:
```powershell
python -m mcp.harvest_server.app `
  --config ./config/defaults.yaml `
  --output ./deploy/data/ofi_cvd `
  --format parquet `
  --rotate.max_rows 200000 `
  --rotate.max_sec 60
```

**部分参数调用**:
```powershell
# 只覆盖输出目录
python -m mcp.harvest_server.app --output ./custom/data

# 只覆盖轮转参数
python -m mcp.harvest_server.app --rotate.max_rows 100000 --rotate.max_sec 30
```

### 4. 参数说明

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--config` | path | 否 | `./config/defaults.yaml` | 全局配置文件路径 |
| `--output` | path | 否 | 配置中的路径 | 输出根目录 |
| `--format` | str | 否 | 配置中的格式 | 输出格式（jsonl/parquet） |
| `--rotate.max_rows` | int | 否 | 配置中的值 | 单文件最大行数 |
| `--rotate.max_sec` | int | 否 | 配置中的值 | 轮转时间间隔（秒） |

### 5. 使用脚本启动

**PowerShell 脚本**:
```powershell
.\scripts\harvest_local.ps1
```

**Bash 脚本**（Linux/macOS）:
```bash
bash scripts/harvest_local.sh
```

### 6. 查看所有可用工具

**列出所有 MCP 服务器**:
```powershell
Get-ChildItem -Path .\mcp -Directory | ForEach-Object { Write-Host $_.Name }
```

**查看特定服务器的帮助**:
```powershell
python -m mcp.<server_name>.app --help
```

### 7. 配置说明

所有 MCP 服务器都使用 `config/defaults.yaml` 作为默认配置。配置文件中包含：

- **symbols**: 交易对列表（6个）
- **paths**: 路径配置
- **harvest**: 采集配置
- **components**: 组件配置（OFI/CVD/Fusion等）

### 8. 日志和监控

启动时，MCP 服务器会输出：
- 启动事件：`{"event": "harvest.start", "args": {...}}`
- 配置信息：交易对列表、输出目录等
- 退出事件：`{"event": "harvest.exit", "code": 0}`

### 9. 错误处理

- **配置错误**: 会显示详细的错误信息
- **参数错误**: `--help` 会显示正确的参数格式
- **运行时错误**: 会记录到日志并返回非零退出码

## 快速参考

```powershell
# 查看帮助
python -m mcp.harvest_server.app --help

# 启动采集（使用默认配置）
python -m mcp.harvest_server.app

# 启动采集（自定义配置）
python -m mcp.harvest_server.app --config ./config/defaults.yaml --output ./deploy/data/ofi_cvd

# 使用脚本启动
.\scripts\harvest_local.ps1
```

