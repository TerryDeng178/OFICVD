# HARVEST 输出目录说明

## 默认输出目录

根据 `scripts/run_success_harvest.py` 的配置逻辑：

### 主数据输出目录（RAW 数据）

**默认路径**: `F:\OFICVD\scripts\data\ofi_cvd`

**目录结构**:
```
scripts/data/ofi_cvd/
├── date=YYYY-MM-DD/
│   └── hour=HH/
│       └── symbol=XXX/
│           └── kind=XXX/
│               └── part-{纳秒时间戳}-{UUID}.parquet
```

**如何修改**:
- 设置环境变量 `OUTPUT_DIR`:
  ```bash
  export OUTPUT_DIR=./data/my_custom_output
  python scripts/run_success_harvest.py
  ```

### Preview 数据目录

**默认路径**: `F:\OFICVD\preview\ofi_cvd`

**说明**: Preview 数据是 RAW 数据的精简版本，只包含核心列，用于快速预览和可视化。

**如何修改**:
- 设置环境变量 `PREVIEW_DIR`:
  ```bash
  export PREVIEW_DIR=./preview/my_custom_preview
  python scripts/run_success_harvest.py
  ```

### Artifacts 目录（元数据和报告）

**默认路径**: `F:\OFICVD\artifacts`

**包含内容**:
- `dq_reports/`: 数据质量检查报告
- `deadletter/`: 坏数据和被过滤的数据
- `slices_manifest_*.json`: 运行清单文件

**目录结构**:
```
artifacts/
├── dq_reports/
│   └── dq_{symbol}_{kind}_{timestamp}.json
├── deadletter/
│   └── {kind}/
│       └── {symbol}_{timestamp}_{rows}.ndjson
└── slices_manifest_{timestamp}.json
```

## 配置优先级

1. **环境变量** `OUTPUT_DIR` (最高优先级)
2. **脚本计算的默认值**: `scripts/data/ofi_cvd`
3. **harvester.py 的 base_dir**: `src/alpha_core/ingestion/data/ofi_cvd` (仅在兼容模式下，如果未传入 output_dir)

## 当前运行进程的输出目录

如果使用 `scripts/run_success_harvest.py` 启动，且没有设置 `OUTPUT_DIR` 环境变量：

**输出目录**: `F:\OFICVD\scripts\data\ofi_cvd`

## 检查当前输出目录的方法

### 方法1: 查看环境变量
```bash
echo %OUTPUT_DIR%
```

### 方法2: 查看进程启动参数
检查运行 HARVEST 的命令行，看是否有 `OUTPUT_DIR` 设置。

### 方法3: 查看实际文件系统
```bash
# Windows
dir /s /b f:\OFICVD\scripts\data\ofi_cvd

# 或查找最新的 parquet 文件
dir /s /b /o-d f:\OFICVD\scripts\data\ofi_cvd\*.parquet | more
```

## 常见问题

### Q: 如何知道当前运行的 HARVEST 使用的输出目录？

A: 
1. 检查进程启动时的环境变量
2. 查看 `scripts/run_success_harvest.py` 的默认值（第2297行）
3. 查看实际文件系统中最新的数据文件位置

### Q: 如何为新的 HARVEST 进程设置不同的输出目录？

A: 在启动新进程前设置环境变量：
```bash
# Windows PowerShell
$env:OUTPUT_DIR = "F:\OFICVD\scripts\data\harvest_instance2"
python scripts/run_success_harvest.py

# Windows CMD
set OUTPUT_DIR=F:\OFICVD\scripts\data\harvest_instance2
python scripts/run_success_harvest.py
```

### Q: 输出目录不存在怎么办？

A: 输出目录会在首次运行时自动创建，无需手动创建。

## 相关代码位置

- `scripts/run_success_harvest.py`: 第2296-2298行
- `src/alpha_core/ingestion/harvester.py`: 第355-372行（兼容模式），第436-444行（配置模式）

