"""Acquisition, fixture writes and transparent smoke-runner contracts."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import godot_test_support as support


class TestGodotTestSupport(unittest.TestCase):
    def test_binary_priority_uses_existing_files_and_live_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configured = root / "Godot configured with spaces"
            configured.write_bytes(b"regular file, not an executable policy check")
            with (
                patch.dict(os.environ, {"GODOT_BIN": str(configured)}),
                patch.object(support.shutil, "which", side_effect=AssertionError("PATH must be later")),
            ):
                self.assertEqual(support.find_smoke_godot_binary(), str(configured))
            with (
                patch.dict(os.environ, {"GODOT_BIN": str(root)}),
                patch.object(support.shutil, "which", return_value="Godot from PATH") as path_lookup,
            ):
                self.assertEqual(support.find_smoke_godot_binary(), "Godot from PATH")
                path_lookup.assert_called_once_with("godot")
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(support.shutil, "which", return_value=None),
                patch.object(support.os.path, "isfile", return_value=True) as app_lookup,
            ):
                self.assertEqual(
                    support.find_smoke_godot_binary(),
                    "/Applications/Godot.app/Contents/MacOS/Godot",
                )
                app_lookup.assert_called_once_with("/Applications/Godot.app/Contents/MacOS/Godot")
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(support.shutil, "which", return_value=None),
                patch.object(support.os.path, "isfile", return_value=False),
            ):
                self.assertIsNone(support.find_smoke_godot_binary())

    def test_fixture_text_creates_parents_overwrites_and_propagates_io_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "nested" / "fixture.gd"
            support.write_fixture_text(target, "first π\n")
            self.assertEqual(target.read_bytes(), "first π\n".encode("utf-8"))
            support.write_fixture_text(target, "second λ\n")
            self.assertEqual(target.read_bytes(), "second λ\n".encode("utf-8"))
            with self.assertRaises(OSError):
                support.write_fixture_text(target.parent, "cannot write a directory")
            self.assertEqual(target.read_bytes(), "second λ\n".encode("utf-8"))

    def test_scene_runner_preserves_result_and_timeout_for_caller_policy(self) -> None:
        project = Path("project path with spaces")
        result: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
            ["observed"], 23, "combined stdout and stderr\n"
        )
        with patch.object(support.subprocess, "run", return_value=result) as run:
            observed = support.run_headless_scene("Godot binary", project, "smoke.tscn", timeout=30)
        self.assertIs(observed, result)
        run.assert_called_once_with(
            ["Godot binary", "--headless", "--path", str(project), "smoke.tscn"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )
        failure = subprocess.TimeoutExpired("original invocation", 30, output=b"partial output")
        with patch.object(support.subprocess, "run", side_effect=failure):
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                support.run_headless_scene("Godot binary", project, "smoke.tscn", timeout=30)
        self.assertIs(caught.exception, failure)
        self.assertEqual(caught.exception.output, b"partial output")


if __name__ == "__main__":
    unittest.main()
