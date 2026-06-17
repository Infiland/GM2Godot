from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestCIWorkflows(unittest.TestCase):
    def test_unit_workflow_runs_discovery_for_golden_and_threshold_gates(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "tests.yml"
        content = workflow.read_text(encoding="utf-8")

        self.assertIn("python -m unittest discover tests/ -v", content)
        self.assertTrue((PROJECT_ROOT / "tests" / "test_golden_conversion.py").is_file())
        self.assertTrue((PROJECT_ROOT / "tests" / "test_cli.py").is_file())

    def test_godot_smoke_workflow_pins_binary_and_runs_headless_smokes(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "godot-smoke.yml"
        content = workflow.read_text(encoding="utf-8")

        self.assertIn("GODOT_VERSION: 4.4.1-stable", content)
        self.assertIn("GODOT_BIN=$godot_bin", content)
        self.assertIn("actions/cache@v4", content)
        self.assertIn("tests.test_godot_validation", content)
        self.assertIn("tests.test_cameras_display_godot", content)
        self.assertIn("tests.test_room_game_flow_godot", content)
        self.assertIn("tests.test_physics_runtime_godot", content)
        self.assertIn("python -m unittest", content)

    def test_external_game_workflow_installs_godot_before_all_fixture_tests(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "tcc-conversion-test.yml"
        content = workflow.read_text(encoding="utf-8")

        install_index = content.index("- name: Install pinned Godot")
        self.assertIn("GODOT_BIN=$godot_bin", content)
        self.assertLess(install_index, content.index("- name: Run SimpleTopDown conversion test"))
        self.assertLess(install_index, content.index("- name: Run TCC conversion test"))
        self.assertLess(install_index, content.index("- name: Run Monophobia conversion test"))


if __name__ == "__main__":
    unittest.main()
