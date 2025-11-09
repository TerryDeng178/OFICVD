# -*- coding: utf-8 -*-
"""集中式路径常量（单一真相源）

统一路径约定：
- DEPLOY_ROOT = <project_root>/deploy
- DATA_ROOT = DEPLOY_ROOT/data/ofi_cvd
- RAW_ROOT = DATA_ROOT/raw
- PREVIEW_ROOT = DATA_ROOT/preview
- ARTIFACTS_ROOT = DEPLOY_ROOT/artifacts/ofi_cvd

所有组件只允许在上面这四个目录层级内工作。
"""
import os
from pathlib import Path
from typing import Dict, Optional


def resolve_roots(project_root: Optional[Path] = None) -> Dict[str, Path]:
    """解析所有路径根目录
    
    Args:
        project_root: 项目根目录，如果为None则自动检测
        
    Returns:
        包含所有路径根的字典：
        - DEPLOY_ROOT: deploy根目录
        - DATA_ROOT: data/ofi_cvd根目录
        - RAW_ROOT: raw数据根目录
        - PREVIEW_ROOT: preview数据根目录
        - ARTIFACTS_ROOT: artifacts根目录
    """
    if project_root is None:
        # 自动检测：从当前文件向上查找项目根（包含.git或pyproject.toml的目录）
        current = Path(__file__).resolve()
        while current.parent != current:
            if (current / ".git").exists() or (current / "pyproject.toml").exists():
                project_root = current
                break
            current = current.parent
        if project_root is None:
            # 回退：假设项目根在src的父目录
            project_root = Path(__file__).resolve().parent.parent.parent
    
    project_root = Path(project_root).resolve()
    
    # 支持环境变量覆盖（便于迁移磁盘或挂载点）
    deploy_root_env = os.getenv("V13_DEPLOY_ROOT")
    if deploy_root_env:
        deploy_root = Path(deploy_root_env).resolve()
    else:
        deploy_root = project_root / "deploy"
    
    data_root_env = os.getenv("V13_DATA_ROOT")
    if data_root_env:
        data_root = Path(data_root_env).resolve()
    else:
        data_root = deploy_root / "data" / "ofi_cvd"
    
    artifacts_root_env = os.getenv("V13_ARTIFACTS_ROOT")
    if artifacts_root_env:
        artifacts_root = Path(artifacts_root_env).resolve()
    else:
        artifacts_root = deploy_root / "artifacts" / "ofi_cvd"
    
    return {
        "PROJECT_ROOT": project_root,
        "DEPLOY_ROOT": deploy_root,
        "DATA_ROOT": data_root,
        "RAW_ROOT": data_root / "raw",
        "PREVIEW_ROOT": data_root / "preview",
        "ARTIFACTS_ROOT": artifacts_root,
    }


def get_data_root(input_mode: str = "preview") -> Path:
    """根据input_mode获取数据根目录
    
    Args:
        input_mode: "raw" 或 "preview"
        
    Returns:
        对应的数据根目录
    """
    roots = resolve_roots()
    if input_mode == "raw":
        return roots["RAW_ROOT"]
    elif input_mode == "preview":
        return roots["PREVIEW_ROOT"]
    else:
        raise ValueError(f"Invalid input_mode: {input_mode}. Must be 'raw' or 'preview'")

