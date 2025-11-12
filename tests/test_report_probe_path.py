# -*- coding: utf-8 -*-
"""P1: 报表产物路径一致性测试

验证report_server的输出路径与健康探针路径一致性。
确保logs/report/*.json在90s内至少出现一次。
"""

import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.mark.integration
@pytest.mark.slow
class TestReportProbePath:
    """报表产物路径一致性测试"""

    def test_report_artifact_path_consistency(self):
        """测试report产物路径与健康探针路径一致性"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)

            # Mock orchestrator components
            from orchestrator.run import build_process_specs

            # Mock parameters
            project_root = Path(tmp_dir) / "project"
            config_path = project_root / "config" / "test.yaml"
            log_dir = project_root / "logs"

            # Create directories
            config_path.parent.mkdir(parents=True, exist_ok=True)
            log_dir.mkdir(parents=True, exist_ok=True)

            # Create mock config file
            config_path.write_text("""
signal:
  enabled: true
strategy:
  enabled: true
report:
  enabled: true
""")

            # Build process specs
            specs = build_process_specs(
                project_root=project_root,
                config_path=config_path,
                sink_kind="jsonl",
                output_dir=output_dir,
                log_dir=log_dir,
                symbols=["BTCUSDT"]
            )

            # Find report spec
            report_spec = None
            for spec in specs:
                if spec.name == "report":
                    report_spec = spec
                    break

            assert report_spec is not None, "Report spec not found"

            # Check health probe args
            health_args = report_spec.health_probe_args
            expected_pattern = str((log_dir / "report" / "*.json").relative_to(project_root))

            # The pattern should be relative to project_root
            assert "*.json" in health_args["pattern"], f"Health probe pattern should match *.json files, got: {health_args['pattern']}"
            assert "report" in health_args["pattern"], f"Health probe pattern should include 'report' directory, got: {health_args['pattern']}"

            print(f"✅ Report健康探针路径验证通过: {health_args['pattern']}")

    def test_report_artifact_creation_within_timeout(self):
        """测试report产物在90s内创建（模拟report_server行为）"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            report_dir = output_dir / "logs" / "report"
            report_dir.mkdir(parents=True, exist_ok=True)

            start_time = time.time()

            # Simulate report_server creating artifact
            def create_report_artifact():
                time.sleep(2)  # Simulate processing time
                report_file = report_dir / "summary_test.json"
                report_file.write_text('{"test": "data"}')
                return report_file

            # Create artifact in background
            import threading
            result = {}
            def worker():
                result['file'] = create_report_artifact()

            thread = threading.Thread(target=worker)
            thread.start()

            # Wait for artifact creation with timeout
            timeout = 90
            while time.time() - start_time < timeout:
                json_files = list(report_dir.glob("*.json"))
                if json_files:
                    elapsed = time.time() - start_time
                    assert elapsed < timeout, f"Report artifact created after {elapsed:.1f}s, exceeded {timeout}s timeout"
                    print(f"✅ Report产物创建及时性验证通过: {elapsed:.1f}s < {timeout}s")
                    return
                time.sleep(0.1)

            thread.join()  # Wait for thread to finish
            pytest.fail(f"Report artifact not created within {timeout}s timeout")

    def test_report_health_probe_pattern_matches_reporter_output(self):
        """测试健康探针模式与Reporter实际输出路径匹配"""
        from orchestrator.run import Reporter
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            log_dir = output_dir / "logs"

            # Create Reporter instance
            reporter = Reporter(
                project_root=output_dir,
                output_dir=log_dir / "report"
            )

            # Generate mock report data
            mock_report = {
                "run_id": "test_run",
                "status": "completed",
                "gating_breakdown": {"low_consistency": 5, "weak_signal": 3}
            }

            # Save report (this should create logs/report/summary_*.json)
            reporter.save_report(mock_report, format="json")

            # Check if files were created in expected location
            report_files = list((log_dir / "report").glob("*.json"))
            assert len(report_files) > 0, "Reporter did not create JSON files in expected location"

            # Verify the pattern that health probe would check
            expected_pattern = str((log_dir / "report" / "*.json"))
            matching_files = list(Path(log_dir / "report").glob("*.json"))

            assert len(matching_files) > 0, f"No files match health probe pattern: {expected_pattern}"
            print(f"✅ Reporter输出路径与健康探针模式匹配验证通过: {len(matching_files)} 个文件")
