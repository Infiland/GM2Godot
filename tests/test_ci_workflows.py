from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestCIWorkflows(unittest.TestCase):
    def test_godot_smoke_workflow_pins_binary_and_runs_headless_smokes(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "godot-smoke.yml"
        content = workflow.read_text(encoding="utf-8")

        self.assertIn("GODOT_VERSION: 4.4.1-stable", content)
        self.assertIn("GODOT_BIN=$godot_bin", content)
        self.assertIn("actions/cache@v4", content)
        self.assertIn("tests.test_cameras_display_godot", content)
        self.assertIn("tests.test_room_game_flow_godot", content)
        self.assertIn("tests.test_physics_runtime_godot", content)
        self.assertIn("python -m unittest", content)


if __name__ == "__main__":
    unittest.main()
