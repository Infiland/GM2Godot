from __future__ import annotations

import copy
from contextlib import chdir, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from typing import Callable, IO, cast

from scripts import verify_dependency_environment as verifier


PYTHON_VERSION = "3.12.13"
PIP_VERSION = "26.1.2"
BASE_PINS = {
    "pip": PIP_VERSION,
    "root-package": "1.0.0",
    "transitive-package": "2.0.0",
}
_OMIT = object()


def _installed_item(
    name: str,
    version: str,
    *,
    installer: object = "pip",
    direct_url: object = _OMIT,
    metadata_location: str | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "metadata": {"name": name, "version": version},
        "metadata_location": metadata_location
        if metadata_location is not None
        else f"/isolated/lib/python3.12/site-packages/{name}-{version}.dist-info",
        "installer": installer,
        "requested": name in {"pip", "root-package"},
    }
    if direct_url is not _OMIT:
        item["direct_url"] = direct_url
    return item


def _inspect_report(
    items: list[dict[str, object]] | None = None,
    *,
    schema: str = "1",
    pip_version: str = PIP_VERSION,
    environment_overrides: dict[str, str] | None = None,
) -> dict[str, object]:
    environment = {
        "implementation_name": "cpython",
        "implementation_version": PYTHON_VERSION,
        "os_name": "posix",
        "platform_machine": "x86_64",
        "platform_python_implementation": "CPython",
        "platform_system": "Linux",
        "python_full_version": PYTHON_VERSION,
        "python_version": "3.12",
        "sys_platform": "linux",
    }
    if environment_overrides is not None:
        environment.update(environment_overrides)
    if items is None:
        items = [
            _installed_item("pip", PIP_VERSION),
            _installed_item("root-package", "1.0.0"),
            _installed_item("transitive-package", "2.0.0"),
        ]
    return {
        "version": schema,
        "pip_version": pip_version,
        "environment": environment,
        "installed": items,
    }


def _constraint_text(pins: dict[str, str]) -> str:
    return "# generated test constraint\n" + "".join(f"{name}=={pins[name]}\n" for name in sorted(pins))


def _completed(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@dataclass(frozen=True)
class _PopenScenario:
    stdout: bytes = b""
    stderr: bytes = b""
    returncode: int | None = 0
    wait_times_out: bool = False
    kill_race: bool = False


class _FakePopen:
    def __init__(self, scenario: _PopenScenario) -> None:
        self.returncode = scenario.returncode
        self.wait_times_out = scenario.wait_times_out
        self.kill_race = scenario.kill_race
        self.kill_calls = 0
        self.wait_calls: list[float | None] = []
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.returncode is not None:
            return self.returncode
        if self.killed:
            self.returncode = -9
            return self.returncode
        if self.wait_times_out:
            raise subprocess.TimeoutExpired(cmd=[], timeout=0.0 if timeout is None else timeout)
        self.returncode = 0
        return self.returncode

    def kill(self) -> None:
        self.kill_calls += 1
        if self.kill_race:
            self.returncode = 0
            raise ProcessLookupError
        self.killed = True


class _PopenFactory:
    def __init__(self, effects: list[object]) -> None:
        self.effects = list(effects)
        self.processes: list[_FakePopen] = []

    def __call__(self, _command: object, **keyword_arguments: object) -> _FakePopen:
        if not self.effects:
            raise AssertionError("Unexpected verifier subprocess invocation.")
        effect = self.effects.pop(0)
        if isinstance(effect, BaseException) and not isinstance(effect, subprocess.TimeoutExpired):
            raise effect
        if isinstance(effect, subprocess.TimeoutExpired):
            scenario = _PopenScenario(returncode=None, wait_times_out=True)
        elif isinstance(effect, subprocess.CompletedProcess):
            completed = cast(subprocess.CompletedProcess[str], effect)
            scenario = _PopenScenario(
                stdout=completed.stdout.encode("utf-8"),
                stderr=completed.stderr.encode("utf-8"),
                returncode=completed.returncode,
            )
        elif isinstance(effect, _PopenScenario):
            scenario = effect
        else:
            raise AssertionError(f"Unsupported verifier subprocess effect: {effect!r}.")

        stdout = cast(IO[bytes], keyword_arguments["stdout"])
        stderr = cast(IO[bytes], keyword_arguments["stderr"])
        stdout.write(scenario.stdout)
        stderr.write(scenario.stderr)
        stdout.flush()
        stderr.flush()
        process = _FakePopen(scenario)
        self.processes.append(process)
        return process


def _create_directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
            text=True,
            timeout=verifier.COMMAND_TIMEOUT_SECONDS,
        )


def _materialize_default_metadata_locations(report_value: object, prefix: Path) -> None:
    if not isinstance(report_value, dict):
        return
    report = cast(dict[str, object], report_value)
    installed_value = report.get("installed")
    if not isinstance(installed_value, list):
        return
    for item_value in cast(list[object], installed_value):
        if not isinstance(item_value, dict):
            continue
        item = cast(dict[str, object], item_value)
        location = item.get("metadata_location")
        if not isinstance(location, str) or not location.startswith("/isolated/"):
            continue
        mapped_location = prefix.joinpath(*location.removeprefix("/isolated/").split("/"))
        mapped_location.mkdir(parents=True, exist_ok=True)
        item["metadata_location"] = str(mapped_location)


class DependencyVerifierHarness:
    def invoke(
        self,
        *,
        pins: dict[str, str] | None = None,
        report: object | None = None,
        mode: str = "subset",
        required: tuple[str, ...] = ("root-package",),
        inspect_returncode: int = 0,
        check_returncode: int = 0,
        inspect_stderr: str = "",
        check_stdout: str = "No broken requirements found.\n",
        constraint_text: str | None = None,
        run_side_effect: list[object] | None = None,
    ) -> tuple[int, dict[str, object], bytes, list[tuple[list[str], dict[str, object]]]]:
        selected_pins = dict(BASE_PINS if pins is None else pins)
        selected_report = copy.deepcopy(_inspect_report() if report is None else report)
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            prefix = directory / "isolated"
            prefix.mkdir()
            _materialize_default_metadata_locations(selected_report, prefix)
            constraint = directory / "constraints-linux.txt"
            constraint.write_text(
                _constraint_text(selected_pins) if constraint_text is None else constraint_text,
                encoding="utf-8",
            )
            output = directory / "nested" / "receipt.json"
            if run_side_effect is None:
                run_side_effect = [
                    _completed(
                        json.dumps(selected_report, ensure_ascii=True, sort_keys=True),
                        returncode=inspect_returncode,
                        stderr=inspect_stderr,
                    ),
                    _completed(check_stdout, returncode=check_returncode),
                ]
            popen_factory = _PopenFactory(run_side_effect)
            arguments = [
                "--constraint",
                str(constraint),
                "--mode",
                mode,
                "--expected-python",
                PYTHON_VERSION,
                "--expected-platform",
                "linux",
                "--expected-machine",
                "x86_64",
                "--expected-pip",
                PIP_VERSION,
                "--output",
                str(output),
            ]
            for name in required:
                arguments.extend(("--require", name))
            with (
                mock.patch.object(verifier.subprocess, "Popen", side_effect=popen_factory) as popen_mock,
                mock.patch.object(verifier.sys, "prefix", str(prefix)),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = verifier.main(arguments)
            receipt_bytes = output.read_bytes()
            receipt = cast(dict[str, object], json.loads(receipt_bytes))
            calls: list[tuple[list[str], dict[str, object]]] = []
            for call in popen_mock.call_args_list:
                calls.append(
                    (
                        cast(list[str], call.args[0]),
                        cast(dict[str, object], call.kwargs),
                    )
                )
            return result, receipt, receipt_bytes, calls


class TestDependencyEnvironmentVerifier(unittest.TestCase, DependencyVerifierHarness):
    def _error_codes(self, receipt: dict[str, object]) -> set[str]:
        errors = cast(list[dict[str, object]], receipt["errors"])
        return {cast(str, error["code"]) for error in errors}

    def _invoke_pip_scenario(
        self,
        scenario: _PopenScenario,
        *,
        maximum_stdout_bytes: int = 8,
    ) -> tuple[verifier.CommandResult, _FakePopen, dict[str, object]]:
        factory = _PopenFactory([scenario])
        run_pip = cast(Callable[..., verifier.CommandResult], getattr(verifier, "_run_pip"))
        with mock.patch.object(verifier.subprocess, "Popen", side_effect=factory) as popen_mock:
            result = run_pip(
                ("inspect",),
                "pip-inspect",
                maximum_stdout_bytes=maximum_stdout_bytes,
            )
        self.assertEqual(len(factory.processes), 1)
        call = popen_mock.call_args
        self.assertIsNotNone(call)
        return result, factory.processes[0], cast(dict[str, object], call.kwargs)

    def test_subset_success_emits_atomic_stable_receipt_and_bounded_commands(self) -> None:
        result, receipt, receipt_bytes, calls = self.invoke()

        self.assertEqual(result, 0)
        self.assertEqual(receipt["status"], "verified")
        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(receipt["errors"], [])
        self.assertTrue(receipt_bytes.endswith(b"\n"))
        observation = cast(dict[str, object], receipt["observation"])
        self.assertRegex(cast(str, observation["installed_fingerprint"]), r"[0-9a-f]{64}\Z")
        self.assertEqual(len(calls), 2)
        for _, keyword_arguments in calls:
            self.assertEqual(keyword_arguments["stdin"], subprocess.DEVNULL)
            self.assertIsNot(keyword_arguments["stdout"], subprocess.PIPE)
            self.assertIsNot(keyword_arguments["stderr"], subprocess.PIPE)
            self.assertIsNot(keyword_arguments["stdout"], keyword_arguments["stderr"])
            self.assertTrue(keyword_arguments["close_fds"])
            self.assertFalse(keyword_arguments["shell"])
            environment = cast(dict[str, str], keyword_arguments["env"])
            self.assertEqual(environment.pop("PIP_CONFIG_FILE"), os.devnull)
            self.assertFalse(
                any(key.upper().startswith(("PIP_", "PYTHON")) for key in environment)
            )
        command_prefix = [
            sys.executable,
            "-I",
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "--no-input",
            "--no-color",
        ]
        self.assertEqual(calls[0][0], [*command_prefix, "inspect"])
        self.assertEqual(calls[1][0], [*command_prefix, "check"])

    def test_pip_commands_ignore_checkout_and_pythonpath_shadow_modules(self) -> None:
        baseline_environment = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith(("PIP_", "PYTHON"))
        }
        baseline_environment["PIP_CONFIG_FILE"] = os.devnull
        baseline = subprocess.run(
            [
                sys.executable,
                "-I",
                "-m",
                "pip",
                "--isolated",
                "--disable-pip-version-check",
                "--no-input",
                "--no-color",
                "inspect",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=verifier.COMMAND_TIMEOUT_SECONDS,
            env=baseline_environment,
        )
        baseline_report = cast(dict[str, object], verifier.parse_inspect_json(baseline.stdout))
        installed = cast(list[dict[str, object]], baseline_report["installed"])
        pins: dict[str, str] = {}
        for item in installed:
            metadata = cast(dict[str, object], item["metadata"])
            pins[verifier.normalize_name(cast(str, metadata["name"]))] = cast(str, metadata["version"])
        environment = cast(dict[str, object], baseline_report["environment"])
        forged_report = json.dumps(baseline_report, ensure_ascii=True, sort_keys=True)

        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            checkout_shadow = directory / "checkout-shadow"
            pythonpath_shadow = directory / "pythonpath-shadow"
            safe_directory = directory / "safe"
            safe_directory.mkdir()
            constraint = directory / "constraints.txt"
            constraint.write_text(_constraint_text(pins), encoding="utf-8")

            cases = (
                ("checkout", checkout_shadow, checkout_shadow, safe_directory),
                ("pythonpath", pythonpath_shadow, safe_directory, pythonpath_shadow),
            )
            receipt_bytes: list[bytes] = []
            for label, shadow_root, working_directory, pythonpath in cases:
                with self.subTest(label=label):
                    sentinel = directory / f"{label}-forged-pip-executed"
                    output = directory / f"{label}-receipt.json"
                    fake_pip = shadow_root / "pip"
                    fake_pip.mkdir(parents=True)
                    (fake_pip / "__init__.py").write_text("", encoding="utf-8")
                    (fake_pip / "__main__.py").write_text(
                        "from pathlib import Path\n"
                        "import sys\n"
                        f"Path({str(sentinel)!r}).write_text('forged', encoding='utf-8')\n"
                        "if sys.argv[1:] == ['inspect']:\n"
                        f"    print({forged_report!r})\n"
                        "elif sys.argv[1:] == ['check']:\n"
                        "    print('No broken requirements found.')\n"
                        "else:\n"
                        "    raise SystemExit(91)\n",
                        encoding="utf-8",
                    )

                    with (
                        mock.patch.dict(os.environ, {"PYTHONPATH": str(pythonpath)}, clear=False),
                        chdir(working_directory),
                        redirect_stdout(StringIO()),
                        redirect_stderr(StringIO()),
                    ):
                        result = verifier.main(
                            [
                                "--constraint",
                                str(constraint),
                                "--mode",
                                "complete",
                                "--expected-python",
                                cast(str, environment["python_full_version"]),
                                "--expected-platform",
                                cast(str, environment["sys_platform"]),
                                "--expected-machine",
                                cast(str, environment["platform_machine"]),
                                "--expected-pip",
                                cast(str, baseline_report["pip_version"]),
                                "--output",
                                str(output),
                            ]
                        )

                    self.assertFalse(sentinel.exists())
                    self.assertEqual(result, 0)
                    receipt = cast(dict[str, object], json.loads(output.read_bytes()))
                    self.assertEqual(receipt["status"], "verified")
                    receipt_bytes.append(output.read_bytes())

            self.assertEqual(receipt_bytes[0], receipt_bytes[1])

    def test_complete_mode_requires_lock_and_environment_equality(self) -> None:
        success, success_receipt, _, _ = self.invoke(mode="complete")
        missing_report = _inspect_report(
            [
                _installed_item("pip", PIP_VERSION),
                _installed_item("root-package", "1.0.0"),
            ]
        )
        failure, failure_receipt, _, _ = self.invoke(mode="complete", report=missing_report)

        self.assertEqual(success, 0)
        self.assertEqual(success_receipt["status"], "verified")
        self.assertEqual(failure, 1)
        self.assertIn("complete-distribution-missing", self._error_codes(failure_receipt))

    def test_removed_transitive_pin_is_rejected(self) -> None:
        pins = {"pip": PIP_VERSION, "root-package": "1.0.0"}
        result, receipt, _, _ = self.invoke(pins=pins)

        self.assertEqual(result, 1)
        self.assertIn("unexpected-installed-distribution", self._error_codes(receipt))

    def test_changed_transitive_pin_is_rejected(self) -> None:
        pins = dict(BASE_PINS)
        pins["transitive-package"] = "2.1.0"
        result, receipt, _, _ = self.invoke(pins=pins)

        self.assertEqual(result, 1)
        self.assertIn("installed-version-mismatch", self._error_codes(receipt))

    def test_escaped_transitive_distribution_is_rejected(self) -> None:
        report = _inspect_report()
        installed = cast(list[dict[str, object]], report["installed"])
        installed.append(_installed_item("escaped-package", "9.0.0"))
        result, receipt, _, _ = self.invoke(report=report)

        self.assertEqual(result, 1)
        errors = cast(list[dict[str, object]], receipt["errors"])
        escaped = [error for error in errors if error.get("name") == "escaped-package"]
        self.assertEqual([error["code"] for error in escaped], ["unexpected-installed-distribution"])

    def test_required_root_must_be_pinned_and_installed(self) -> None:
        report = _inspect_report([_installed_item("pip", PIP_VERSION)])
        pins = {"pip": PIP_VERSION, "transitive-package": "2.0.0"}
        result, receipt, _, _ = self.invoke(pins=pins, report=report)

        self.assertEqual(result, 1)
        self.assertTrue({"required-pin-missing", "required-distribution-missing"}.issubset(self._error_codes(receipt)))

    def test_reordered_inspect_items_produce_identical_receipt_and_fingerprint(self) -> None:
        forward = _inspect_report()
        reverse = _inspect_report(list(reversed(cast(list[dict[str, object]], forward["installed"]))))

        first_result, first_receipt, _, _ = self.invoke(report=forward, mode="complete")
        second_result, second_receipt, _, _ = self.invoke(report=reverse, mode="complete")

        self.assertEqual((first_result, second_result), (0, 0))
        first_observation = cast(dict[str, object], first_receipt["observation"])
        second_observation = cast(dict[str, object], second_receipt["observation"])
        self.assertEqual(first_observation["installed_fingerprint"], second_observation["installed_fingerprint"])
        cast(dict[str, object], first_receipt["constraint"])["path"] = "<constraint>"
        cast(dict[str, object], second_receipt["constraint"])["path"] = "<constraint>"
        self.assertEqual(first_receipt, second_receipt)

    def test_duplicate_normalized_installed_names_are_rejected(self) -> None:
        report = _inspect_report()
        installed = cast(list[dict[str, object]], report["installed"])
        installed.append(_installed_item("transitive_package", "2.0.0"))
        result, receipt, _, _ = self.invoke(report=report)

        self.assertEqual(result, 1)
        self.assertIn("installed-duplicate-name", self._error_codes(receipt))

    def test_non_pip_installer_and_direct_url_are_rejected(self) -> None:
        cases = (
            (
                "installer",
                _installed_item("transitive-package", "2.0.0", installer="conda"),
                "installer-mismatch",
            ),
            (
                "direct-url",
                _installed_item(
                    "transitive-package",
                    "2.0.0",
                    direct_url={"url": "file:///tmp/transitive-package.whl"},
                ),
                "direct-url-forbidden",
            ),
        )
        for label, item, expected_code in cases:
            with self.subTest(label=label):
                report = _inspect_report(
                    [
                        _installed_item("pip", PIP_VERSION),
                        _installed_item("root-package", "1.0.0"),
                        item,
                    ]
                )
                result, receipt, _, _ = self.invoke(report=report)
                self.assertEqual(result, 1)
                self.assertIn(expected_code, self._error_codes(receipt))

    def test_metadata_location_must_be_local_modern_distribution_metadata(self) -> None:
        outside = _installed_item("transitive-package", "2.0.0")
        outside["metadata_location"] = "/foreign/transitive-package-2.0.0.dist-info"
        legacy = _installed_item("transitive-package", "2.0.0")
        legacy["metadata_location"] = "/isolated/lib/python3.12/site-packages/transitive-package.egg-info"
        for label, item in (("outside", outside), ("legacy", legacy)):
            with self.subTest(label=label):
                report = _inspect_report(
                    [
                        _installed_item("pip", PIP_VERSION),
                        _installed_item("root-package", "1.0.0"),
                        item,
                    ]
                )
                result, receipt, _, _ = self.invoke(report=report)
                self.assertEqual(result, 1)
                self.assertIn("metadata-location-outside-environment", self._error_codes(receipt))

    def test_metadata_location_resolves_real_directory_link_targets(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            prefix = directory / "isolated"
            site_packages = prefix / "site-packages"
            outside = directory / "outside"
            site_packages.mkdir(parents=True)
            outside.mkdir()

            pip_location = site_packages / f"pip-{PIP_VERSION}.dist-info"
            root_location = site_packages / "root-package-1.0.0.dist-info"
            internal_target = site_packages / "internal-target-transitive-2.0.0.dist-info"
            external_target = outside / "external-target-transitive-2.0.0.dist-info"
            for metadata_directory in (pip_location, root_location, internal_target, external_target):
                metadata_directory.mkdir()

            policy = verifier.ConstraintPolicy(
                path=directory / "constraints.txt",
                sha256="0" * 64,
                pins=BASE_PINS,
            )
            expected_environment = verifier.parse_expected_environment(
                python_full_version=PYTHON_VERSION,
                sys_platform="linux",
                platform_machine="x86_64",
                pip_version=PIP_VERSION,
            )
            cases = (
                ("internal", internal_target, False),
                ("external", external_target, True),
            )
            for label, target, expect_escape in cases:
                with self.subTest(label=label):
                    linked_location = site_packages / f"{label}-transitive-2.0.0.dist-info"
                    _create_directory_link(linked_location, target)
                    report = _inspect_report(
                        [
                            _installed_item("pip", PIP_VERSION, metadata_location=str(pip_location)),
                            _installed_item("root-package", "1.0.0", metadata_location=str(root_location)),
                            _installed_item(
                                "transitive-package",
                                "2.0.0",
                                metadata_location=str(linked_location),
                            ),
                        ]
                    )
                    with mock.patch.object(verifier.sys, "prefix", str(prefix)):
                        analysis = verifier.analyze_inspect_report(
                            report,
                            policy=policy,
                            expected_environment=expected_environment,
                            mode="complete",
                            required_names=("root-package",),
                        )
                    error_codes = {finding.code for finding in analysis.findings}
                    if expect_escape:
                        self.assertIn("metadata-location-outside-environment", error_codes)
                    else:
                        self.assertNotIn("metadata-location-outside-environment", error_codes)

    def test_schema_environment_and_pip_drift_are_rejected(self) -> None:
        cases = (
            ("schema", _inspect_report(schema="2"), "pip-inspect-schema-mismatch"),
            (
                "python",
                _inspect_report(environment_overrides={"python_full_version": "3.12.12"}),
                "environment-mismatch",
            ),
            (
                "platform",
                _inspect_report(environment_overrides={"sys_platform": "darwin"}),
                "environment-mismatch",
            ),
            (
                "machine",
                _inspect_report(environment_overrides={"platform_machine": "aarch64"}),
                "environment-mismatch",
            ),
            ("pip", _inspect_report(pip_version="26.1.1"), "pip-version-mismatch"),
        )
        for label, report, expected_code in cases:
            with self.subTest(label=label):
                result, receipt, _, _ = self.invoke(report=report)
                self.assertEqual(result, 1)
                self.assertIn(expected_code, self._error_codes(receipt))

    def test_pip_is_the_only_bootstrap_and_must_match_constraint_and_metadata(self) -> None:
        missing_pin = {name: version for name, version in BASE_PINS.items() if name != "pip"}
        wrong_pin = dict(BASE_PINS)
        wrong_pin["pip"] = "26.1.1"
        wrong_metadata = _inspect_report(
            [
                _installed_item("pip", "26.1.1"),
                _installed_item("root-package", "1.0.0"),
                _installed_item("transitive-package", "2.0.0"),
            ]
        )
        setuptools_report = _inspect_report()
        cast(list[dict[str, object]], setuptools_report["installed"]).append(_installed_item("setuptools", "80.9.0"))
        cases = (
            ("missing-pin", missing_pin, _inspect_report(), "pip-pin-missing"),
            ("wrong-pin", wrong_pin, _inspect_report(), "pip-constraint-mismatch"),
            (
                "wrong-metadata",
                dict(BASE_PINS),
                wrong_metadata,
                "pip-installed-version-mismatch",
            ),
            (
                "setuptools-is-not-bootstrap",
                dict(BASE_PINS),
                setuptools_report,
                "unexpected-installed-distribution",
            ),
        )
        for label, pins, report, expected_code in cases:
            with self.subTest(label=label):
                result, receipt, _, _ = self.invoke(pins=pins, report=report)
                self.assertEqual(result, 1)
                self.assertIn(expected_code, self._error_codes(receipt))

    def test_pip_check_failure_is_independent_and_terminal(self) -> None:
        result, receipt, _, _ = self.invoke(
            check_returncode=1,
            check_stdout="root-package 1.0.0 requires missing-package, which is not installed.\n",
        )

        self.assertEqual(result, 1)
        self.assertIn("pip-check-failed", self._error_codes(receipt))

    def test_timeout_is_bounded_and_still_produces_failure_receipt(self) -> None:
        timeout = subprocess.TimeoutExpired(cmd=[sys.executable, "-m", "pip", "inspect"], timeout=30)
        with mock.patch.object(verifier, "COMMAND_TIMEOUT_SECONDS", 0.0):
            result, receipt, _, calls = self.invoke(
                run_side_effect=[timeout, _completed("No broken requirements found.\n")]
            )

        self.assertEqual(result, 1)
        self.assertIn("pip-inspect-timeout", self._error_codes(receipt))
        self.assertEqual(len(calls), 2)

    def test_stdout_overflow_kills_reaps_and_discards_output(self) -> None:
        result, process, _ = self._invoke_pip_scenario(
            _PopenScenario(stdout=b"123456789", returncode=None)
        )

        self.assertIsNotNone(result.failure)
        self.assertEqual(cast(verifier.Finding, result.failure).code, "pip-inspect-stdout-too-large")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (None, "", ""))
        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(process.wait_calls, [None])

    def test_stderr_overflow_kills_reaps_and_discards_output(self) -> None:
        with mock.patch.object(verifier, "MAX_COMMAND_OUTPUT_BYTES", 8):
            result, process, _ = self._invoke_pip_scenario(
                _PopenScenario(stderr=b"123456789", returncode=None)
            )

        self.assertIsNotNone(result.failure)
        self.assertEqual(cast(verifier.Finding, result.failure).code, "pip-inspect-stderr-too-large")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (None, "", ""))
        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(process.wait_calls, [None])

    def test_finished_process_overflow_is_rejected_by_final_size_check(self) -> None:
        result, process, _ = self._invoke_pip_scenario(_PopenScenario(stdout=b"123456789"))

        self.assertIsNotNone(result.failure)
        self.assertEqual(cast(verifier.Finding, result.failure).code, "pip-inspect-stdout-too-large")
        self.assertEqual(process.kill_calls, 0)
        self.assertEqual(process.wait_calls, [])

    def test_exact_output_limit_is_accepted(self) -> None:
        result, process, _ = self._invoke_pip_scenario(_PopenScenario(stdout=b"12345678"))

        self.assertIsNone(result.failure)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "12345678", ""))
        self.assertEqual(process.kill_calls, 0)

    def test_direct_timeout_kills_and_reaps_without_captured_output(self) -> None:
        with mock.patch.object(verifier, "COMMAND_TIMEOUT_SECONDS", 0.0):
            result, process, _ = self._invoke_pip_scenario(
                _PopenScenario(returncode=None, wait_times_out=True)
            )

        self.assertIsNotNone(result.failure)
        self.assertEqual(cast(verifier.Finding, result.failure).code, "pip-inspect-timeout")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (None, "", ""))
        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(process.wait_calls, [None])

    def test_capture_failure_after_spawn_kills_and_reaps(self) -> None:
        with mock.patch.object(verifier.os, "fstat", side_effect=OSError("capture failed")):
            result, process, _ = self._invoke_pip_scenario(_PopenScenario(returncode=None))

        self.assertIsNotNone(result.failure)
        self.assertEqual(cast(verifier.Finding, result.failure).code, "pip-inspect-execution-failed")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (None, "", ""))
        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(process.wait_calls, [None])

    def test_process_exit_race_during_overflow_cleanup_is_reaped(self) -> None:
        result, process, _ = self._invoke_pip_scenario(
            _PopenScenario(stdout=b"123456789", returncode=None, kill_race=True)
        )

        self.assertIsNotNone(result.failure)
        self.assertEqual(cast(verifier.Finding, result.failure).code, "pip-inspect-stdout-too-large")
        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(process.wait_calls, [None])

    def test_overflow_results_do_not_depend_on_discarded_content(self) -> None:
        first, _, _ = self._invoke_pip_scenario(
            _PopenScenario(stdout=b"aaaaaaaaa", returncode=None)
        )
        second, _, _ = self._invoke_pip_scenario(
            _PopenScenario(stdout=b"bbbbbbbbb", returncode=None)
        )

        self.assertEqual(first, second)

    def test_pip_environment_is_filtered_without_dropping_required_os_values(self) -> None:
        poisoned_environment = {
            "PATH": "safe-path",
            "SystemRoot": "C:\\Windows",
            "PIP_PATH": "forged-site-packages",
            "PIP_CONFIG_FILE": "forged-pip.ini",
            "PYTHONPATH": "forged-pythonpath",
            "pythonwarnings": "error",
        }
        with mock.patch.dict(verifier.os.environ, poisoned_environment, clear=True):
            _, _, keyword_arguments = self._invoke_pip_scenario(_PopenScenario())

        environment = cast(dict[str, str], keyword_arguments["env"])
        self.assertEqual(
            environment,
            {
                "PATH": "safe-path",
                "PIP_CONFIG_FILE": os.devnull,
                "SystemRoot": "C:\\Windows",
            },
        )
        self.assertEqual(keyword_arguments["stdin"], subprocess.DEVNULL)
        self.assertIsNot(keyword_arguments["stdout"], subprocess.PIPE)
        self.assertIsNot(keyword_arguments["stderr"], subprocess.PIPE)
        self.assertIsNot(keyword_arguments["stdout"], keyword_arguments["stderr"])

    def test_constraint_output_aliases_are_rejected_before_pip_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            constraint = directory / "constraints.txt"
            original_constraint = _constraint_text(BASE_PINS).encode("utf-8")
            constraint.write_bytes(original_constraint)
            normalized_parent = directory / "normalized-parent"
            normalized_parent.mkdir()
            same_file_alias = directory / "same-file-constraints.txt"
            os.link(constraint, same_file_alias)
            aliases = (
                ("direct", constraint),
                ("normalized", normalized_parent / ".." / constraint.name),
                ("same-file", same_file_alias),
            )

            for label, output in aliases:
                with self.subTest(label=label):
                    with (
                        mock.patch.object(verifier.subprocess, "Popen") as popen_mock,
                        redirect_stdout(StringIO()),
                        redirect_stderr(StringIO()),
                    ):
                        result = verifier.main(
                            [
                                "--constraint",
                                str(constraint),
                                "--mode",
                                "complete",
                                "--expected-python",
                                PYTHON_VERSION,
                                "--expected-platform",
                                "linux",
                                "--expected-machine",
                                "x86_64",
                                "--expected-pip",
                                PIP_VERSION,
                                "--output",
                                str(output),
                            ]
                        )

                    self.assertEqual(result, 2)
                    popen_mock.assert_not_called()
                    self.assertEqual(constraint.read_bytes(), original_constraint)
                    self.assertEqual(output.read_bytes(), original_constraint)

    def test_constraint_parser_rejects_nonexact_and_duplicate_normalized_pins(self) -> None:
        cases = (
            ("range", "pip==26.1.2\nroot-package>=1.0\n", "constraint-non-exact-pin"),
            ("wildcard", "pip==26.1.2\nroot-package==1.*\n", "constraint-non-exact-pin"),
            ("unpinned", "pip==26.1.2\nroot-package\n", "constraint-non-exact-pin"),
            (
                "duplicate",
                "pip==26.1.2\nroot-package==1.0\nroot_package==1.0\n",
                "constraint-duplicate-name",
            ),
            ("include", "pip==26.1.2\n-r other.txt\n", "constraint-non-exact-pin"),
            ("editable", "pip==26.1.2\n-e ./root-package\n", "constraint-non-exact-pin"),
            ("emitted-option", "--only-binary :all:\npip==26.1.2\n", "constraint-non-exact-pin"),
            ("marker", 'pip==26.1.2\nroot-package==1.0 ; sys_platform == "linux"\n', "constraint-non-exact-pin"),
            ("direct-url", "pip==26.1.2\nroot-package @ https://example.invalid/x.whl\n", "constraint-non-exact-pin"),
            ("unicode-kelvin-name", "pip==26.1.2\npacKage==1.0\n", "constraint-non-exact-pin"),
            ("unicode-dotless-i-name", "pip==26.1.2\npıp==1.0\n", "constraint-non-exact-pin"),
            ("unicode-long-s-name", "pip==26.1.2\nſetuptools==1.0\n", "constraint-non-exact-pin"),
            ("unicode-kelvin-version", "pip==26.1.2\nroot-package==1.K\n", "constraint-non-exact-pin"),
        )
        for label, constraint_text, expected_code in cases:
            with self.subTest(label=label):
                result, receipt, _, calls = self.invoke(constraint_text=constraint_text)
                self.assertEqual(result, 1)
                self.assertIn(expected_code, self._error_codes(receipt))
                self.assertEqual(calls, [])

    def test_distribution_name_grammar_rejects_unicode_casefold_aliases(self) -> None:
        for name in ("pacKage", "pıp", "ſetuptools"):
            with self.subTest(name=name), self.assertRaises(verifier.PolicyError) as raised:
                verifier.normalize_name(name)
            self.assertEqual(raised.exception.code, "invalid-distribution-name")

    def test_malformed_inspect_schema_fails_closed(self) -> None:
        malformed_reports: tuple[tuple[str, object], ...] = (
            ("missing-installed", {"version": "1", "pip_version": PIP_VERSION, "environment": {}}),
            (
                "non-string-environment",
                {
                    **_inspect_report(),
                    "environment": {"python_full_version": 31213},
                },
            ),
            (
                "missing-item-metadata",
                {
                    **_inspect_report(),
                    "installed": [{"metadata_location": "/isolated/broken.dist-info", "installer": "pip"}],
                },
            ),
        )
        for label, report in malformed_reports:
            with self.subTest(label=label):
                result, receipt, _, _ = self.invoke(report=report)
                self.assertEqual(result, 1)
                self.assertIn("pip-inspect-invalid-schema", self._error_codes(receipt))

    def test_invalid_inspect_json_and_duplicate_json_keys_fail_closed(self) -> None:
        cases = (
            ("syntax", "{", "pip-inspect-invalid-json"),
            (
                "duplicate-key",
                '{"version":"1","version":"1","pip_version":"26.1.2","environment":{},"installed":[]}',
                "pip-inspect-invalid-json",
            ),
        )
        for label, stdout, expected_code in cases:
            with self.subTest(label=label):
                result, receipt, _, _ = self.invoke(
                    run_side_effect=[
                        _completed(stdout),
                        _completed("No broken requirements found.\n"),
                    ]
                )
                self.assertEqual(result, 1)
                self.assertIn(expected_code, self._error_codes(receipt))


if __name__ == "__main__":
    unittest.main()
