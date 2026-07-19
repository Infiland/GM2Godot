from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from scripts import compile_dependency_lock as compiler


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "dependency-locks.yml"
CONSTRAINT_PATHS = (
    PROJECT_ROOT / "constraints" / "requirements-linux-py312.txt",
    PROJECT_ROOT / "constraints" / "requirements-macos-py312.txt",
    PROJECT_ROOT / "constraints" / "requirements-windows-py312.txt",
)
PIP_ARGUMENTS = "--isolated --disable-pip-version-check --no-input --no-cache-dir --only-binary=:all:"


def _folded_workflow_scalar(workflow: str, name: str) -> str:
    marker = f"      {name}: >-\n"
    if workflow.count(marker) != 1:
        raise AssertionError(f"Workflow must define exactly one folded scalar: {name}")
    _, separator, remainder = workflow.partition(marker)
    if not separator:
        raise AssertionError(f"Workflow scalar not found: {name}")
    lines: list[str] = []
    for line in remainder.splitlines():
        if not line.startswith("        "):
            if not line:
                raise AssertionError(
                    f"Workflow scalar must use one contiguous folded block: {name}"
                )
            break
        lines.append(line[8:])
    if not lines:
        raise AssertionError(f"Workflow scalar is empty: {name}")
    return " ".join(lines)


class DependencyLockCompilerTests(unittest.TestCase):
    def test_isolated_environment_removes_case_insensitive_python_and_pip_settings(self) -> None:
        source = {
            "PATH": "/trusted/bin",
            "KEEP_ME": "yes",
            "PIP_INDEX_URL": "https://example.invalid/simple",
            "pIp_Extra_Index_Url": "https://other.invalid/simple",
            "PIP_TOOLS_CACHE_DIR": "/untrusted/cache",
            "pip_tools_config": "/untrusted/config",
            "PYTHONPATH": "/untrusted/modules",
            "pythonhome": "/untrusted/home",
            "PythonUTF8": "0",
        }

        environment = compiler.build_isolated_environment(source)

        self.assertEqual(environment["PATH"], "/trusted/bin")
        self.assertEqual(environment["KEEP_ME"], "yes")
        self.assertEqual(environment["PIP_CONFIG_FILE"], os.devnull)
        self.assertEqual(
            [name for name in environment if name.upper().startswith("PIP_")],
            ["PIP_CONFIG_FILE"],
        )
        self.assertFalse(any(name.upper().startswith("PYTHON") for name in environment))

    def test_main_invokes_same_interpreter_in_isolated_mode_without_a_shell_or_stdin(self) -> None:
        completed: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(args=[], returncode=0)
        inherited = {
            "PATH": "/trusted/bin",
            "PiP_Config_File": "/untrusted/pip.ini",
            "pythonpath": "/untrusted/modules",
        }
        with (
            mock.patch.object(compiler.os, "environ", inherited),
            mock.patch.object(compiler.subprocess, "run", return_value=completed) as run,
        ):
            status = compiler.main(["--no-config", "requirements-lock.in"])

        self.assertEqual(status, 0)
        run.assert_called_once_with(
            [
                sys.executable,
                "-I",
                "-m",
                "piptools",
                "compile",
                "--no-config",
                "requirements-lock.in",
            ],
            check=False,
            env={"PATH": "/trusted/bin", "PIP_CONFIG_FILE": os.devnull},
            shell=False,
            stdin=subprocess.DEVNULL,
        )

    def test_main_propagates_compiler_exit_status(self) -> None:
        completed: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(args=[], returncode=23)
        with mock.patch.object(compiler.subprocess, "run", return_value=completed):
            self.assertEqual(compiler.main([]), 23)

    def test_main_maps_posix_signal_status_to_shell_convention(self) -> None:
        completed: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(
            args=[], returncode=-2
        )
        with (
            mock.patch.object(compiler.os, "name", "posix"),
            mock.patch.object(compiler.subprocess, "run", return_value=completed),
        ):
            self.assertEqual(compiler.main([]), 130)

    def test_main_uses_nonzero_fallback_for_negative_windows_status(self) -> None:
        completed: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(
            args=[], returncode=-2
        )
        with (
            mock.patch.object(compiler.os, "name", "nt"),
            mock.patch.object(compiler.subprocess, "run", return_value=completed),
        ):
            self.assertEqual(compiler.main([]), 1)

    def test_main_maps_keyboard_interrupt_to_shell_interrupt_status(self) -> None:
        with mock.patch.object(
            compiler.subprocess, "run", side_effect=KeyboardInterrupt
        ):
            self.assertEqual(compiler.main([]), 130)

    def test_main_reports_process_start_failure(self) -> None:
        stderr = StringIO()
        with (
            mock.patch.object(compiler.subprocess, "run", side_effect=OSError("blocked")),
            redirect_stderr(stderr),
        ):
            status = compiler.main([])

        self.assertEqual(status, 127)
        self.assertIn("Unable to start the isolated pip-tools compiler", stderr.getvalue())
        self.assertIn("blocked", stderr.getvalue())


class DependencyLockWorkflowIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_native_matrix_selects_null_pip_configuration_per_host(self) -> None:
        self.assertEqual(self.workflow.count("pip_config_file: /dev/null"), 2)
        self.assertEqual(self.workflow.count("pip_config_file: nul"), 1)
        self.assertIn("PIP_CONFIG_FILE: ${{ matrix.pip_config_file }}", self.workflow)
        for inherited_setting in (
            "PIP_DISABLE_PIP_VERSION_CHECK:",
            "PIP_NO_CACHE_DIR:",
            "PIP_NO_INPUT:",
            "PIP_ONLY_BINARY:",
        ):
            self.assertNotIn(inherited_setting, self.workflow)

    def test_all_six_install_sites_use_isolated_noninteractive_pip(self) -> None:
        install_marker = "-m pip --isolated --disable-pip-version-check --no-input install"
        self.assertEqual(self.workflow.count(install_marker), 6)
        self.assertNotIn("-m pip install", self.workflow)

    def test_both_compiles_use_wrapper_exact_pip_arguments_and_distinct_caches(self) -> None:
        invocation = '-I scripts/compile_dependency_lock.py \\\n'
        self.assertEqual(self.workflow.count(invocation), 2)
        self.assertNotIn("-m piptools compile", self.workflow)
        self.assertEqual(self.workflow.count("--no-config \\\n"), 2)
        self.assertEqual(self.workflow.count(f'"--pip-args={PIP_ARGUMENTS}" \\\n'), 2)
        self.assertEqual(self.workflow.count('--cache-dir="$CURRENT_COMPILE_CACHE"'), 1)
        self.assertEqual(self.workflow.count('--cache-dir="$CANDIDATE_COMPILE_CACHE"'), 1)
        self.assertIn("CURRENT_COMPILE_CACHE: dependency-locks/work/current-pip-tools-cache", self.workflow)
        self.assertIn("CANDIDATE_COMPILE_CACHE: dependency-locks/work/candidate-pip-tools-cache", self.workflow)

    def test_custom_command_and_generated_headers_record_canonical_wrapper(self) -> None:
        command_template = _folded_workflow_scalar(
            self.workflow, "CUSTOM_COMPILE_COMMAND"
        )
        self.assertEqual(command_template.count("${{ matrix.constraint }}"), 1)
        for path in CONSTRAINT_PATHS:
            expected_command = command_template.replace(
                "${{ matrix.constraint }}", path.name
            )
            header_commands = tuple(
                line.removeprefix("#    ")
                for line in path.read_text(encoding="utf-8").splitlines()[:7]
                if line.startswith("#    ")
            )
            self.assertEqual(header_commands, (expected_command,), path.name)


if __name__ == "__main__":
    unittest.main()
