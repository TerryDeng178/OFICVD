#!/usr/bin/env python3
"""清理旧数据，为TASK-07A测试做准备"""
import shutil
from pathlib import Path

def cleanup():
    """清理旧数据"""
    project_root = Path(__file__).parent.parent
    
    print("=" * 80)
    print("清理旧数据（为TASK-07A测试做准备）")
    print("=" * 80)
    print()
    
    # 清理目录列表
    cleanup_dirs = [
        project_root / "runtime",
        project_root / "logs",
        project_root / "deploy" / "artifacts" / "ofi_cvd"
    ]
    
    for dir_path in cleanup_dirs:
        if dir_path.exists():
            print(f"清理目录: {dir_path}")
            try:
                shutil.rmtree(dir_path)
                print(f"  [OK] 已删除")
            except Exception as e:
                print(f"  [ERROR] 删除失败: {e}")
        else:
            print(f"目录不存在（跳过）: {dir_path}")
    
    # 重新创建必要的目录结构
    print()
    print("创建必要的目录结构...")
    for dir_path in cleanup_dirs:
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"  [OK] {dir_path}")
    
    # 创建子目录
    (project_root / "logs" / "orchestrator").mkdir(parents=True, exist_ok=True)
    (project_root / "logs" / "report").mkdir(parents=True, exist_ok=True)
    (project_root / "deploy" / "artifacts" / "ofi_cvd" / "run_logs").mkdir(parents=True, exist_ok=True)
    
    print()
    print("=" * 80)
    print("清理完成")
    print("=" * 80)

if __name__ == "__main__":
    cleanup()

