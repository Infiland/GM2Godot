from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from tests.godot_test_support import require_exact_godot

EXACT_VERSION = "4.7.2.stable.official.ed1daf0bf"


def _version_result(stdout: str = EXACT_VERSION, stderr: str = "", status: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["engine", "--version"], status, stdout, stderr)


class TestGodotTestSupport(unittest.TestCase):
    def test_discovery_preserves_environment_path_and_macos_fallbacks(self) -> None:
        macos = "/Applications/Godot.app/Contents/MacOS/Godot"
        cases: tuple[tuple[dict[str, str], list[bool], str | None, str | None, list[object]], ...] = (
            ({"GODOT_BIN": "/engine/env"}, [True], "/engine/path", "/engine/env", [call.isfile("/engine/env")]),
            ({"GODOT_BIN": "/missing"}, [False], "/engine/path", "/engine/path",
             [call.isfile("/missing"), call.which("godot")]),
            ({"GODOT_BIN": ""}, [], "/engine/path", "/engine/path", [call.which("godot")]),
            ({}, [], "/engine/path", "/engine/path", [call.which("godot")]),
            ({}, [True], None, macos, [call.which("godot"), call.isfile(macos)]),
            ({}, [False], None, None, [call.which("godot"), call.isfile(macos)]),
        )
        for environment, file_results, path_binary, expected, expected_queries in cases:
            queries = Mock()
            with (
                self.subTest(environment=environment, expected=expected),
                patch.dict(os.environ, environment, clear=True),
                patch("src.conversion.godot_validation.os.path.isfile", side_effect=file_results) as isfile,
                patch("src.conversion.godot_validation.shutil.which", return_value=path_binary) as which,
                patch("tests.godot_test_support.subprocess.run", return_value=_version_result()) as launch,
            ):
                queries.attach_mock(isfile, "isfile")
                queries.attach_mock(which, "which")
                if expected is None:
                    with self.assertRaisesRegex(unittest.SkipTest, "^Godot binary not available$"):
                        require_exact_godot()
                    launch.assert_not_called()
                else:
                    self.assertEqual(require_exact_godot(), expected)
                    launch.assert_called_once_with(
                        [expected, "--version"], capture_output=True, text=True, timeout=10, check=False,
                    )
                self.assertEqual(queries.mock_calls, expected_queries)

    def test_absent_optional_engine_skips_before_launch(self) -> None:
        with (
            patch("tests.godot_test_support.find_godot_binary", return_value=None) as discover,
            patch("tests.godot_test_support.subprocess.run") as launch,
        ):
            with self.assertRaisesRegex(unittest.SkipTest, "^Godot binary not available$"):
                require_exact_godot()
        discover.assert_called_once_with()
        launch.assert_not_called()

    def test_explicit_path_bypasses_discovery(self) -> None:
        selected = "relative/../custom engine"
        with (
            patch("tests.godot_test_support.find_godot_binary") as discover,
            patch("tests.godot_test_support.subprocess.run", return_value=_version_result()) as launch,
        ):
            self.assertIs(require_exact_godot(selected), selected)
        discover.assert_not_called()
        launch.assert_called_once_with([selected, "--version"], capture_output=True, text=True, timeout=10, check=False)

    def test_empty_explicit_path_is_launch_error_without_fallback(self) -> None:
        with patch("tests.godot_test_support.find_godot_binary") as discover:
            with self.assertRaises(OSError):
                require_exact_godot("")
        discover.assert_not_called()

    def test_exact_build_requires_successful_combined_output(self) -> None:
        cases = ((EXACT_VERSION + "\n", ""), ("", " " + EXACT_VERSION + "\n"),
                 (EXACT_VERSION[:10], EXACT_VERSION[10:]))
        for stdout, stderr in cases:
            with self.subTest(stdout=stdout, stderr=stderr):
                with patch("tests.godot_test_support.subprocess.run", return_value=_version_result(stdout, stderr)):
                    self.assertEqual(require_exact_godot("selected"), "selected")
        with patch(
            "tests.godot_test_support.subprocess.run",
            return_value=_version_result(EXACT_VERSION, "unexpected stderr"),
        ):
            with self.assertRaisesRegex(AssertionError, "unexpected stderr"):
                require_exact_godot("selected")

    def test_wrong_build_is_failure_not_skip(self) -> None:
        for output in ("", "4.7.2.stable.custom.wrong", "4.7.1.stable.official.old"):
            with self.subTest(output=output):
                with patch("tests.godot_test_support.subprocess.run", return_value=_version_result(output)):
                    with self.assertRaisesRegex(AssertionError, "Exact Godot") as error:
                        require_exact_godot("selected")
                self.assertIn(EXACT_VERSION, str(error.exception))
                self.assertIn(repr(output), str(error.exception))

    def test_nonzero_version_exit_is_failure(self) -> None:
        with patch(
            "tests.godot_test_support.subprocess.run", return_value=_version_result(EXACT_VERSION, " stderr", 7),
        ):
            with self.assertRaisesRegex(AssertionError, "Godot --version exited with 7:") as error:
                require_exact_godot("selected")
        self.assertIn(EXACT_VERSION + " stderr", str(error.exception))

    def test_timeout_and_oserror_propagate(self) -> None:
        errors = (subprocess.TimeoutExpired(["selected", "--version"], 10),
                  PermissionError("not executable"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"))
        for original in errors:
            with self.subTest(error=type(original).__name__):
                with patch("tests.godot_test_support.subprocess.run", side_effect=original):
                    with self.assertRaises(type(original)) as raised:
                        require_exact_godot("selected")
                self.assertIs(raised.exception, original)

    def test_version_timeout_values_are_preserved(self) -> None:
        for timeout in (10, 20, 30):
            with self.subTest(timeout=timeout):
                with patch("tests.godot_test_support.subprocess.run", return_value=_version_result()) as launch:
                    self.assertEqual(require_exact_godot("selected", timeout=timeout), "selected")
                launch.assert_called_once_with(
                    ["selected", "--version"], capture_output=True, text=True, timeout=timeout, check=False,
                )

    def test_import_does_not_discover_or_launch_engine(self) -> None:
        source = """\
import importlib
import sys
from pathlib import Path
from unittest.mock import patch
with patch("src.conversion.godot_validation.find_godot_binary", side_effect=AssertionError("discovery during import")):
    with patch("subprocess.run", side_effect=AssertionError("launch during import")):
        module = importlib.import_module("tests.godot_test_support")
assert Path(module.__file__).resolve() == Path(sys.argv[1]) / "tests/godot_test_support.py"
print("IMPORT_ONLY_OK")
"""
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-c", source, str(root)], cwd=root,
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "IMPORT_ONLY_OK")

    def test_wrong_build_executes_real_version_process(self) -> None:
        with patch("tests.godot_test_support.subprocess.run", wraps=subprocess.run) as launch:
            with self.assertRaisesRegex(AssertionError, "Exact Godot.*Python"):
                require_exact_godot(sys.executable)
        launch.assert_called_once_with(
            [sys.executable, "--version"], capture_output=True, text=True, timeout=10, check=False,
        )

    def test_repeated_calls_rediscover_and_revalidate(self) -> None:
        with (
            patch("tests.godot_test_support.find_godot_binary", side_effect=["first", "second"]) as discover,
            patch("tests.godot_test_support.subprocess.run", return_value=_version_result()) as launch,
        ):
            self.assertEqual(require_exact_godot(), "first")
            self.assertEqual(require_exact_godot(), "second")
        self.assertEqual(discover.call_args_list, [call(), call()])
        self.assertEqual(launch.call_args_list, [
            call(["first", "--version"], capture_output=True, text=True, timeout=10, check=False),
            call(["second", "--version"], capture_output=True, text=True, timeout=10, check=False),
        ])
