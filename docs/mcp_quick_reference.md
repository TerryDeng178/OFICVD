# MCP 服务器快速参考

## 如何查看工具和调用规则

### 方法 1: 使用 --help 参数（推荐）

```powershell
# 查看 HARVEST 服务器的所有可用工具和参数
python -m mcp.harvest_server.app --help
```

这会显示：
- 所有可用参数
- 参数说明和默认值
- 使用示例

### 方法 2: 查看文档

```powershell
# 查看完整使用指南
Get-Content .\docs\mcp_usage_guide.md
```

### 方法 3: 使用工具列表脚本

```powershell
.\scripts\list_mcp_tools.ps1
```

## HARVEST MCP 服务器工具说明

### 可用工具（参数）

| 工具/参数 | 类型 | 必需 | 默认值 | 说明 |
|-----------|------|------|--------|------|
| `--config` | path | 否 | `./config/defaults.yaml` | 全局配置文件路径 |
| `--output` | path | 否 | 配置中的路径 | 输出根目录 |
| `--format` | str | 否 | 配置中的格式 | 输出格式：`jsonl` 或 `parquet` |
| `--rotate.max_rows` | int | 否 | 配置中的值 | 单文件最大行数 |
| `--rotate.max_sec` | int | 否 | 配置中的值 | 轮转时间间隔（秒） |

### 调用规则

#### 基本格式
```powershell
python -m mcp.harvest_server.app [参数]
```

#### 调用示例

**1. 使用默认配置**:
```powershell
python -m mcp.harvest_server.app
```

**2. 指定配置文件**:
```powershell
python -m mcp.harvest_server.app --config ./config/defaults.yaml
```

**3. 覆盖输出目录**:
```powershell
python -m mcp.harvest_server.app --output ./deploy/data/ofi_cvd
```

**4. 完整参数调用**:
```powershell
python -m mcp.harvest_server.app `
  --config ./config/defaults.yaml `
  --output ./deploy/data/ofi_cvd `
  --format parquet `
  --rotate.max_rows 200000 `
  --rotate.max_sec 60
```

**5. 使用启动脚本**:
```powershell
.\scripts\harvest_local.ps1
```

### 参数覆盖规则

1. **命令行参数 > 配置文件 > 默认值**
2. 如果参数未指定，使用配置文件中的值
3. 如果配置文件也没有，使用默认值

### 配置文件中相关设置

在 `config/defaults.yaml` 中：

```yaml
symbols:
  - "BTCUSDT"
  - "ETHUSDT"
  - "BNBUSDT"
  - "SOLUSDT"
  - "XRPUSDT"
  - "DOGEUSDT"

harvest:
  rotate:
    max_rows: 500000
    max_sec: 300
```

### 输出说明

启动时会输出：
- 配置中的交易对数量
- 交易对列表
- 输出目录
- 轮转参数
- 启动事件日志

## 其他 MCP 服务器

### 查看所有服务器
```powershell
Get-ChildItem -Path .\mcp -Directory
```

### 查看特定服务器的帮助
```powershell
python -m mcp.<server_name>.app --help
```

## 快速命令参考

```powershell
# 查看帮助
python -m mcp.harvest_server.app --help

# 启动采集（默认配置）
python -m mcp.harvest_server.app

# 启动采集（自定义配置）
python -m mcp.harvest_server.app --config ./config/defaults.yaml --output ./deploy/data/ofi_cvd

# 使用脚本启动
.\scripts\harvest_local.ps1
```

