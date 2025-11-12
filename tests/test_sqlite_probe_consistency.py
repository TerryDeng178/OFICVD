# -*- coding: utf-8 -*-
"""P1: SQLite探针一致性测试

验证ready_probe与health_probe的v2/v1数据库选择一致性。
"""

import pytest
import tempfile
import os
from pathlib import Path


@pytest.mark.integration
class TestSqliteProbeConsistency:
    """SQLite探针一致性测试"""

    def test_sqlite_probe_v2_priority_consistency(self):
        """测试同时存在v1和v2数据库时，两探针都选择v2"""
        from orchestrator.run import build_process_specs

        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            config_path = project_root / "config" / "test.yaml"
            log_dir = project_root / "logs"
            output_dir = project_root / "runtime"

            # Create config
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("signal:\n  enabled: true\n  sink: sqlite\n")

            # Create output directory and both v1 and v2 database files
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "signals.db").touch()  # v1
            (output_dir / "signals_v2.db").touch()  # v2

            specs = build_process_specs(
                project_root=project_root,
                config_path=config_path,
                sink_kind="sqlite",
                output_dir=output_dir,
                log_dir=log_dir
            )

            # Find signal spec
            signal_spec = next((spec for spec in specs if spec.name == "signal"), None)
            assert signal_spec is not None, "Signal spec not found"

            # Check ready probe path
            ready_args = signal_spec.ready_probe_args
            ready_db_path = ready_args["db_path"]

            # Check health probe path
            health_args = signal_spec.health_probe_args
            health_db_path = health_args["db_path"]

            # Both should point to v2 database
            assert "signals_v2.db" in ready_db_path, f"Ready probe should use v2, got: {ready_db_path}"
            assert "signals_v2.db" in health_db_path, f"Health probe should use v2, got: {health_db_path}"

            # Both should be identical
            assert ready_db_path == health_db_path, f"Ready and health probes should use same DB: {ready_db_path} != {health_db_path}"

            print(f"✅ SQLite探针v2优先级一致性验证通过: {ready_db_path}")

    def test_sqlite_probe_v1_fallback_consistency(self):
        """测试只有v1数据库时，两探针都选择v1"""
        from orchestrator.run import build_process_specs

        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            config_path = project_root / "config" / "test.yaml"
            log_dir = project_root / "logs"
            output_dir = project_root / "runtime"

            # Create config
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("signal:\n  enabled: true\n  sink: sqlite\n")

            # Create output directory and only v1 database file
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "signals.db").touch()  # v1 only

            specs = build_process_specs(
                project_root=project_root,
                config_path=config_path,
                sink_kind="sqlite",
                output_dir=output_dir,
                log_dir=log_dir
            )

            signal_spec = next((spec for spec in specs if spec.name == "signal"), None)
            assert signal_spec is not None, "Signal spec not found"

            ready_args = signal_spec.ready_probe_args
            health_args = signal_spec.health_probe_args

            ready_db_path = ready_args["db_path"]
            health_db_path = health_args["db_path"]

            # Both should point to v1 database
            assert "signals.db" in ready_db_path, f"Ready probe should use v1, got: {ready_db_path}"
            assert "signals_v2.db" not in ready_db_path, f"Ready probe should not use v2, got: {ready_db_path}"

            assert "signals.db" in health_db_path, f"Health probe should use v1, got: {health_db_path}"
            assert "signals_v2.db" not in health_db_path, f"Health probe should not use v2, got: {health_db_path}"

            # Both should be identical
            assert ready_db_path == health_db_path, f"Ready and health probes should use same DB: {ready_db_path} != {health_db_path}"

            print(f"✅ SQLite探针v1回退一致性验证通过: {ready_db_path}")

    def test_sqlite_probe_no_database_files(self):
        """测试没有数据库文件时，两探针的行为一致性"""
        from orchestrator.run import build_process_specs

        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            config_path = project_root / "config" / "test.yaml"
            log_dir = project_root / "logs"
            output_dir = project_root / "runtime"

            # Create config
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("signal:\n  enabled: true\n  sink: sqlite\n")

            # Create output directory but don't create any database files
            output_dir.mkdir(parents=True, exist_ok=True)

            specs = build_process_specs(
                project_root=project_root,
                config_path=config_path,
                sink_kind="sqlite",
                output_dir=output_dir,
                log_dir=log_dir
            )

            signal_spec = next((spec for spec in specs if spec.name == "signal"), None)
            assert signal_spec is not None, "Signal spec not found"

            ready_args = signal_spec.ready_probe_args
            health_args = signal_spec.health_probe_args

            ready_db_path = ready_args["db_path"]
            health_db_path = health_args["db_path"]

            # Both should point to v1 (fallback when no files exist)
            assert "signals.db" in ready_db_path, f"Ready probe should fallback to v1, got: {ready_db_path}"
            assert "signals.db" in health_db_path, f"Health probe should fallback to v1, got: {health_db_path}"

            # Both should be identical
            assert ready_db_path == health_db_path, f"Ready and health probes should use same DB: {ready_db_path} != {health_db_path}"

            print(f"✅ SQLite探针无文件时一致性验证通过: {ready_db_path}")

    def test_sqlite_probe_path_resolution(self):
        """测试SQLite探针路径解析的正确性"""
        from orchestrator.run import build_process_specs

        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            config_path = project_root / "config" / "test.yaml"
            log_dir = project_root / "logs"
            output_dir = project_root / "runtime"

            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("signal:\n  enabled: true\n  sink: sqlite\n")

            # Create output directory and v2 database
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "signals_v2.db").touch()

            specs = build_process_specs(
                project_root=project_root,
                config_path=config_path,
                sink_kind="sqlite",
                output_dir=output_dir,
                log_dir=log_dir
            )

            signal_spec = next((spec for spec in specs if spec.name == "signal"), None)
            assert signal_spec is not None, "Signal spec not found"

            ready_db_path = signal_spec.ready_probe_args["db_path"]
            health_db_path = signal_spec.health_probe_args["db_path"]

            # Verify paths are relative to project_root (not absolute paths)
            assert not ready_db_path.startswith(str(project_root)), f"Ready probe path should be relative, got: {ready_db_path}"
            assert not health_db_path.startswith(str(project_root)), f"Health probe path should be relative, got: {health_db_path}"

            # Verify they contain expected components
            assert "runtime" in ready_db_path, f"Ready probe path should include runtime dir, got: {ready_db_path}"
            assert "signals_v2.db" in ready_db_path, f"Ready probe should use v2 DB, got: {ready_db_path}"

            assert "runtime" in health_db_path, f"Health probe path should include runtime dir, got: {health_db_path}"
            assert "signals_v2.db" in health_db_path, f"Health probe should use v2 DB, got: {health_db_path}"

            print(f"✅ SQLite探针路径解析验证通过: ready={ready_db_path}, health={health_db_path}")
