#!/usr/bin/env python3
"""P2: 验证单一真源（消除多版本漂移）"""
import ast
import sys
from pathlib import Path
from typing import Dict, List, Set

def find_class_definitions(root_dir: Path, class_names: List[str]) -> Dict[str, List[Path]]:
    """查找类定义的位置"""
    results = {}
    for class_name in class_names:
        results[class_name] = []
    
    for py_file in root_dir.rglob("*.py"):
        if "test" in py_file.name.lower() or "__pycache__" in str(py_file):
            continue
        
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                content = f.read()
                tree = ast.parse(content, filename=str(py_file))
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        if node.name in class_names:
                            results[node.name].append(py_file)
        except Exception as e:
            print(f"[WARN] 解析文件失败 {py_file}: {e}", file=sys.stderr)
            continue
    
    return results

def find_imports(root_dir: Path, module_paths: List[str]) -> Dict[str, List[Path]]:
    """查找import语句"""
    results = {}
    for module_path in module_paths:
        results[module_path] = []
    
    for py_file in root_dir.rglob("*.py"):
        if "test" in py_file.name.lower() or "__pycache__" in str(py_file):
            continue
        
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                content = f.read()
                tree = ast.parse(content, filename=str(py_file))
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name in module_paths:
                                results[alias.name].append(py_file)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and node.module in module_paths:
                            results[node.module].append(py_file)
        except Exception as e:
            print(f"[WARN] 解析文件失败 {py_file}: {e}", file=sys.stderr)
            continue
    
    return results

def check_sqlite_schema(db_path: Path) -> Dict:
    """检查SQLite表结构"""
    import sqlite3
    result = {
        "exists": False,
        "columns": [],
        "primary_key": None,
        "has_run_id": False
    }
    
    if not db_path.exists():
        return result
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signals'")
        if not cursor.fetchone():
            conn.close()
            return result
        
        result["exists"] = True
        
        # 获取列信息
        cursor.execute("PRAGMA table_info(signals)")
        columns = cursor.fetchall()
        result["columns"] = [col[1] for col in columns]
        result["has_run_id"] = "run_id" in result["columns"]
        
        # 获取主键信息
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='signals'")
        table_sql = cursor.fetchone()
        if table_sql:
            sql_str = table_sql[0].upper()
            if "PRIMARY KEY" in sql_str:
                if "RUN_ID" in sql_str and "TS_MS" in sql_str and "SYMBOL" in sql_str:
                    result["primary_key"] = "(run_id, ts_ms, symbol)"
                elif "AUTOINCREMENT" in sql_str:
                    result["primary_key"] = "id AUTOINCREMENT"
                elif "TS_MS" in sql_str and "SYMBOL" in sql_str:
                    result["primary_key"] = "(ts_ms, symbol)"
        
        conn.close()
    except Exception as e:
        print(f"[ERROR] 检查SQLite表结构失败: {e}", file=sys.stderr)
    
    return result

def main():
    root_dir = Path(".")
    
    # 查找关键类定义
    class_names = ["SqliteSink", "JsonlSink", "CoreAlgorithm", "MultiSink"]
    class_defs = find_class_definitions(root_dir, class_names)
    
    # 查找import语句
    module_paths = ["alpha_core.signals.core_algo", "mcp.signal_server.app"]
    imports = find_imports(root_dir, module_paths)
    
    # 检查SQLite表结构
    db_path = Path("runtime/signals.db")
    schema_info = check_sqlite_schema(db_path)
    
    # 输出结果
    print("=" * 80)
    print("单一真源验证报告")
    print("=" * 80)
    print()
    
    # 1. 类定义检查
    print("1. 类定义位置检查:")
    all_ok = True
    for class_name in class_names:
        files = class_defs[class_name]
        if len(files) == 0:
            print(f"  {class_name}: ❌ 未找到定义")
            all_ok = False
        elif len(files) == 1:
            print(f"  {class_name}: ✅ 单一定义 ({files[0]})")
        else:
            print(f"  {class_name}: ❌ 多个定义 ({len(files)}个):")
            for f in files:
                print(f"    - {f}")
            all_ok = False
    print()
    
    # 2. Import路径检查
    print("2. Import路径检查:")
    expected_path = "src/alpha_core/signals/core_algo.py"
    if Path(expected_path).exists():
        print(f"  ✅ 预期路径存在: {expected_path}")
    else:
        print(f"  ❌ 预期路径不存在: {expected_path}")
        all_ok = False
    
    # 检查是否有其他路径的import
    for module_path, files in imports.items():
        if files:
            print(f"  {module_path}: {len(files)}个文件引用")
            # 检查是否有非预期的import路径
            for f in files[:5]:  # 只显示前5个
                print(f"    - {f}")
    print()
    
    # 3. SQLite表结构检查
    print("3. SQLite表结构检查:")
    if schema_info["exists"]:
        print(f"  ✅ 表存在")
        print(f"  列数: {len(schema_info['columns'])}")
        print(f"  列: {', '.join(schema_info['columns'])}")
        print(f"  主键: {schema_info['primary_key'] or '未检测到'}")
        print(f"  有run_id列: {'✅' if schema_info['has_run_id'] else '❌'}")
        
        if schema_info["primary_key"] != "(run_id, ts_ms, symbol)":
            print(f"  ⚠️  主键不是预期格式: {schema_info['primary_key']}")
            all_ok = False
        if not schema_info["has_run_id"]:
            print(f"  ⚠️  缺少run_id列")
            all_ok = False
    else:
        print(f"  ⚠️  表不存在（可能尚未运行测试）")
    print()
    
    # 4. 总结
    print("=" * 80)
    if all_ok:
        print("结果: ✅ 单一真源验证通过")
        return 0
    else:
        print("结果: ❌ 发现多版本漂移问题")
        return 1

if __name__ == "__main__":
    sys.exit(main())

