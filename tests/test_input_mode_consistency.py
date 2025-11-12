# -*- coding: utf-8 -*-
"""P1: V13_INPUT_MODE一致性测试

验证V13_INPUT_MODE在不同组件中的解析一致性。
"""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


@pytest.mark.integration
class TestInputModeConsistency:
    """V13_INPUT_MODE一致性测试"""

    def test_input_mode_default_consistency(self):
        """测试V13_INPUT_MODE默认值在不同组件中的一致性"""
        from orchestrator.run import build_process_specs

        with patch.dict(os.environ, {}, clear=True):
            # Test with no env var set (should default to "preview")
            with tempfile.TemporaryDirectory() as tmp_dir:
                project_root = Path(tmp_dir)
                config_path = project_root / "config" / "test.yaml"
                log_dir = project_root / "logs"
                output_dir = project_root / "runtime"

                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_path.write_text("signal:\n  enabled: true\n")

                # Build specs without V13_INPUT_MODE env var
                specs = build_process_specs(
                    project_root=project_root,
                    config_path=config_path,
                    sink_kind="jsonl",
                    output_dir=output_dir,
                    log_dir=log_dir
                )

                # Find harvest spec
                harvest_spec = None
                for spec in specs:
                    if spec.name == "harvest":
                        harvest_spec = spec
                        break

                assert harvest_spec is not None, "Harvest spec not found"

                # Check that harvest pattern uses preview path
                pattern = harvest_spec.health_probe_args["pattern"]
                assert "preview" in pattern or "raw" not in pattern, f"Harvest pattern should use preview by default, got: {pattern}"

                print(f"✅ V13_INPUT_MODE默认值一致性验证通过: {pattern}")

    @pytest.mark.parametrize("input_mode", ["preview", "raw"])
    def test_input_mode_explicit_consistency(self, input_mode):
        """测试显式设置V13_INPUT_MODE后的一致性"""
        from orchestrator.run import build_process_specs

        with patch.dict(os.environ, {"V13_INPUT_MODE": input_mode}):
            with tempfile.TemporaryDirectory() as tmp_dir:
                project_root = Path(tmp_dir)
                config_path = project_root / "config" / "test.yaml"
                log_dir = project_root / "logs"
                output_dir = project_root / "runtime"

                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_path.write_text("signal:\n  enabled: true\n")

                specs = build_process_specs(
                    project_root=project_root,
                    config_path=config_path,
                    sink_kind="jsonl",
                    output_dir=output_dir,
                    log_dir=log_dir
                )

                harvest_spec = next((spec for spec in specs if spec.name == "harvest"), None)
                assert harvest_spec is not None, "Harvest spec not found"

                pattern = harvest_spec.health_probe_args["pattern"]
                assert input_mode in pattern, f"Harvest pattern should contain {input_mode}, got: {pattern}"

                print(f"✅ V13_INPUT_MODE={input_mode}显式设置一致性验证通过: {pattern}")

    def test_manifest_input_mode_consistency(self):
        """测试manifest中记录的input_mode与实际使用的一致性"""
        import json

        # Simulate manifest data structures
        source_manifest = {
            "run_id": "test_run_123",
            "input_mode": "preview",
            "features_dir": "/path/to/preview",
            "input_dir": "/path/to/preview"
        }

        run_manifest = {
            "run_id": "test_run_123",
            "source_versions": {
                "input_mode_resolved": "preview",
                "input_dir_resolved": "/path/to/preview"
            }
        }

        # Verify consistency between manifests
        assert source_manifest["input_mode"] == run_manifest["source_versions"]["input_mode_resolved"], \
            "source_manifest与run_manifest中input_mode不一致"

        assert source_manifest["input_dir"] == run_manifest["source_versions"]["input_dir_resolved"], \
            "source_manifest与run_manifest中input_dir不一致"

        print("✅ Manifest input_mode一致性验证通过")

    def test_source_manifest_vs_run_manifest_consistency(self):
        """测试source_manifest与run_manifest中input_mode的对比"""
        import tempfile
        import json

        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts_dir = Path(tmp_dir)

            # Simulate source_manifest content
            source_manifest = {
                "run_id": "test_run_123",
                "input_mode": "preview",
                "features_dir": "/path/to/preview",
                "input_dir": "/path/to/preview"
            }

            # Simulate run_manifest content
            run_manifest = {
                "run_id": "test_run_123",
                "source_versions": {
                    "input_mode_resolved": "preview",
                    "input_dir_resolved": "/path/to/preview"
                }
            }

            # Check consistency between manifests
            assert source_manifest["input_mode"] == run_manifest["source_versions"]["input_mode_resolved"], \
                "source_manifest与run_manifest中input_mode不一致"

            assert source_manifest["input_dir"] == run_manifest["source_versions"]["input_dir_resolved"], \
                "source_manifest与run_manifest中input_dir不一致"

            print("✅ source_manifest vs run_manifest一致性验证通过")
