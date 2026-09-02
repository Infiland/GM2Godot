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
from types import SimpleNamespace
import unittest
from unittest import mock
from typing import Callable, IO, cast

from scripts import verify_dependency_environment as verifier


PYTHON_VERSION = "3.12.13"
PIP_VERSION = "26.2.1"
PIP_TOOLS_VERSION = "7.6.1"
BASE_PINS = {
    "pip": PIP_VERSION,
    "pip-tools": PIP_TOOLS_VERSION,
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
            _installed_item("pip-tools", PIP_TOOLS_VERSION),
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


def _bootstrap_text(
    pip_version: str = PIP_VERSION,
    pip_tools_version: str = PIP_TOOLS_VERSION,
) -> str:
    return (
        "# Review these exact pins as one compatibility unit.\n"
        f"pip=={pip_version}\n"
        f"pip-tools=={pip_tools_version}\n"
    )


def _write_native_constraints(
    directory: Path,
    *,
    pip_version: str,
    pip_tools_version: str,
    per_platform_pins: tuple[dict[str, str], ...] | None = None,
) -> tuple[Path, ...]:
    paths = tuple(directory / path for path in verifier.NATIVE_CONSTRAINT_PATHS)
    if per_platform_pins is None:
        per_platform_pins = ({"linux-only": "1"}, {"macos-only": "2"}, {"windows-only": "3"})
    for path, platform_pins in zip(paths, per_platform_pins, strict=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        pins = {
            "pip": pip_version,
            "pip-tools": pip_tools_version,
            **platform_pins,
        }
        path.write_text(_constraint_text(pins), encoding="utf-8")
    return paths


def _completed(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _stat_with_overrides(
    source: os.stat_result,
    **overrides: int,
) -> os.stat_result:
    fields = {
        "st_dev": source.st_dev,
        "st_ino": source.st_ino,
        "st_mode": source.st_mode,
        "st_size": source.st_size,
        "st_mtime_ns": source.st_mtime_ns,
        "st_ctime_ns": source.st_ctime_ns,
    }
    fields.update(overrides)
    return cast(os.stat_result, SimpleNamespace(**fields))


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
        bootstrap_text: str | None = None,
        run_side_effect: list[object] | None = None,
    ) -> tuple[int, dict[str, object], bytes, list[tuple[list[str], dict[str, object]]]]:
        selected_pins = dict(BASE_PINS if pins is None else pins)
        selected_report = copy.deepcopy(_inspect_report() if report is None else report)
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            prefix = directory / "isolated"
            prefix.mkdir()
            _materialize_default_metadata_locations(selected_report, prefix)
            constraint = directory / "constraints-linux.txt"
            constraint.write_text(
                _constraint_text(selected_pins) if constraint_text is None else constraint_text,
                encoding="utf-8",
            )
            bootstrap = directory / "requirements-bootstrap.txt"
            bootstrap.write_text(
                _bootstrap_text() if bootstrap_text is None else bootstrap_text,
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
                "--bootstrap",
                str(bootstrap),
                "--bootstrap-policy",
                "stable",
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
        self.assertEqual(receipt["schema_version"], 2)
        self.assertEqual(receipt["errors"], [])
        bootstrap = cast(dict[str, object], receipt["bootstrap"])
        self.assertEqual((bootstrap["policy"], bootstrap["state"]), ("stable", "stable"))
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
            "-X",
            "utf8",
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
                "-X",
                "utf8",
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
            directory = Path(raw_directory).resolve()
            checkout_shadow = directory / "checkout-shadow"
            pythonpath_shadow = directory / "pythonpath-shadow"
            safe_directory = directory / "safe"
            safe_directory.mkdir()
            constraint = directory / "constraints.txt"
            pins["pip-tools"] = PIP_TOOLS_VERSION
            constraint.write_text(_constraint_text(pins), encoding="utf-8")
            bootstrap = directory / "requirements-bootstrap.txt"
            bootstrap.write_text(
                f"pip=={baseline_report['pip_version']}\npip-tools=={PIP_TOOLS_VERSION}\n",
                encoding="utf-8",
            )

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
                                "subset",
                                "--expected-python",
                                cast(str, environment["python_full_version"]),
                                "--expected-platform",
                                cast(str, environment["sys_platform"]),
                                "--expected-machine",
                                cast(str, environment["platform_machine"]),
                                "--bootstrap",
                                str(bootstrap),
                                "--bootstrap-policy",
                                "stable",
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
        pins = {
            "pip": PIP_VERSION,
            "pip-tools": PIP_TOOLS_VERSION,
            "root-package": "1.0.0",
        }
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
        pins = {
            "pip": PIP_VERSION,
            "pip-tools": PIP_TOOLS_VERSION,
            "transitive-package": "2.0.0",
        }
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
        for receipt in (first_receipt, second_receipt):
            bootstrap = cast(dict[str, object], receipt["bootstrap"])
            cast(dict[str, object], bootstrap["source"])["path"] = "<bootstrap>"
            constraints = cast(list[dict[str, object]], bootstrap["constraints"])
            constraints[0]["path"] = "<constraint>"
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
            directory = Path(raw_directory).resolve()
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
            ("missing-pin", missing_pin, _inspect_report(), "bootstrap-pair-missing"),
            (
                "wrong-pin",
                wrong_pin,
                _inspect_report(),
                "bootstrap-source-lock-mismatch",
            ),
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
            "PYTHONIOENCODING": "cp1252",
            "PYTHONPATH": "forged-pythonpath",
            "PYTHONUTF8": "0",
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

    def test_pip_subprocess_forces_utf8_for_unicode_output_under_legacy_locale(self) -> None:
        payload = '{"description":"Hello from pip \U0001f44b"}\n'
        factory = _PopenFactory([_PopenScenario(stdout=payload.encode("utf-8"))])
        run_pip = cast(Callable[..., verifier.CommandResult], getattr(verifier, "_run_pip"))
        poisoned_environment = {
            "LC_ALL": "C",
            "PATH": "safe-path",
            "PYTHONIOENCODING": "cp1252",
            "PYTHONUTF8": "0",
        }

        with (
            mock.patch.dict(verifier.os.environ, poisoned_environment, clear=True),
            mock.patch.object(verifier.subprocess, "Popen", side_effect=factory) as popen_mock,
        ):
            result = run_pip(
                ("inspect",),
                "pip-inspect",
                maximum_stdout_bytes=verifier.MAX_INSPECT_BYTES,
            )

        call = popen_mock.call_args
        self.assertIsNotNone(call)
        self.assertEqual(
            cast(list[str], call.args[0])[:5],
            [sys.executable, "-X", "utf8", "-I", "-m"],
        )
        environment = cast(dict[str, str], call.kwargs["env"])
        self.assertEqual(
            environment,
            {"LC_ALL": "C", "PATH": "safe-path", "PIP_CONFIG_FILE": os.devnull},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, payload)
        self.assertEqual(result.stderr, "")

    def test_constraint_output_aliases_are_rejected_before_pip_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            constraint = directory / "constraints.txt"
            original_constraint = _constraint_text(BASE_PINS).encode("utf-8")
            constraint.write_bytes(original_constraint)
            bootstrap = directory / "requirements-bootstrap.txt"
            bootstrap.write_text(
                f"pip=={PIP_VERSION}\npip-tools=={PIP_TOOLS_VERSION}\n",
                encoding="utf-8",
            )
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
                                "--bootstrap",
                                str(bootstrap),
                                "--bootstrap-policy",
                                "stable",
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

    def test_expected_pip_is_derived_and_literal_override_is_removed(self) -> None:
        result, receipt, _, _ = self.invoke()

        self.assertEqual(result, 0)
        expected = cast(dict[str, object], receipt["expected_environment"])
        self.assertEqual(expected["pip_version"], PIP_VERSION)
        arguments = [
            "--constraint",
            "constraints.lock",
            "--mode",
            "subset",
            "--expected-python",
            PYTHON_VERSION,
            "--expected-platform",
            "linux",
            "--expected-machine",
            "x86_64",
            "--bootstrap",
            "requirements-bootstrap.txt",
            "--bootstrap-policy",
            "stable",
            "--output",
            "receipt.json",
            "--expected-pip",
            "0",
        ]
        parse_arguments = cast(Callable[[list[str]], object], getattr(verifier, "_parse_arguments"))
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            parse_arguments(arguments)
        self.assertEqual(raised.exception.code, 2)

    def test_stable_bootstrap_mismatch_stops_before_pip(self) -> None:
        result, receipt, _, calls = self.invoke(
            bootstrap_text=_bootstrap_text(pip_version="26.3")
        )

        self.assertEqual(result, 1)
        self.assertEqual(calls, [])
        self.assertIn("bootstrap-source-lock-mismatch", self._error_codes(receipt))

    def test_subset_environment_does_not_need_pip_tools_installed(self) -> None:
        report = _inspect_report(
            [
                _installed_item("pip", PIP_VERSION),
                _installed_item("root-package", "1.0.0"),
                _installed_item("transitive-package", "2.0.0"),
            ]
        )

        result, receipt, _, _ = self.invoke(report=report)

        self.assertEqual(result, 0)
        self.assertEqual(receipt["status"], "verified")

    def test_native_transition_derives_current_generator_pip_from_all_locks(self) -> None:
        old_pip = "26.1.1"
        old_pip_tools = "7.5.2"
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            _write_native_constraints(
                directory,
                pip_version=old_pip,
                pip_tools_version=old_pip_tools,
            )
            (directory / "requirements-bootstrap.txt").write_text(_bootstrap_text(), encoding="utf-8")
            prefix = directory / "isolated"
            prefix.mkdir()
            report = _inspect_report(
                [
                    _installed_item("pip", old_pip),
                    _installed_item("pip-tools", old_pip_tools),
                ],
                pip_version=old_pip,
            )
            _materialize_default_metadata_locations(report, prefix)
            output = directory / "receipt.json"
            factory = _PopenFactory(
                [
                    _completed(json.dumps(report, ensure_ascii=True, sort_keys=True)),
                    _completed("No broken requirements found.\n"),
                ]
            )
            with (
                chdir(directory),
                mock.patch.object(verifier.sys, "prefix", str(prefix)),
                mock.patch.object(verifier.subprocess, "Popen", side_effect=factory) as popen_mock,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = verifier.main(
                    [
                        "--constraint",
                        "constraints/requirements-linux-py312.lock",
                        "--mode",
                        "subset",
                        "--require",
                        "pip",
                        "--require",
                        "pip-tools",
                        "--expected-python",
                        PYTHON_VERSION,
                        "--expected-platform",
                        "linux",
                        "--expected-machine",
                        "x86_64",
                        "--bootstrap",
                        "requirements-bootstrap.txt",
                        "--bootstrap-policy",
                        "native-lock-workflow",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(popen_mock.call_count, 2)
            receipt = cast(dict[str, object], json.loads(output.read_bytes()))
            expected = cast(dict[str, object], receipt["expected_environment"])
            self.assertEqual(expected["pip_version"], old_pip)
            bootstrap = cast(dict[str, object], receipt["bootstrap"])
            self.assertEqual(bootstrap["state"], "source-transition")

    def test_native_transition_policy_cannot_verify_an_ordinary_environment(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            _write_native_constraints(
                directory,
                pip_version=PIP_VERSION,
                pip_tools_version=PIP_TOOLS_VERSION,
            )
            (directory / "requirements-bootstrap.txt").write_text(_bootstrap_text(), encoding="utf-8")
            output = directory / "receipt.json"
            with (
                chdir(directory),
                mock.patch.object(verifier.subprocess, "Popen") as popen_mock,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = verifier.main(
                    [
                        "--constraint",
                        "constraints/requirements-linux-py312.lock",
                        "--mode",
                        "subset",
                        "--require",
                        "pip",
                        "--expected-python",
                        PYTHON_VERSION,
                        "--expected-platform",
                        "linux",
                        "--expected-machine",
                        "x86_64",
                        "--bootstrap",
                        "requirements-bootstrap.txt",
                        "--bootstrap-policy",
                        "native-lock-workflow",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(result, 1)
            popen_mock.assert_not_called()
            receipt = cast(dict[str, object], json.loads(output.read_bytes()))
            self.assertIn("bootstrap-native-policy-misuse", self._error_codes(receipt))


class TestDependencyBootstrapPolicy(unittest.TestCase):
    def test_exact_source_is_loaded_with_stable_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            source = Path(raw_directory).resolve() / "requirements-bootstrap.txt"
            source.write_text("\n# compatibility pair\n" + _bootstrap_text(), encoding="utf-8")

            policy = verifier.load_bootstrap_requirements(source)

            self.assertEqual(policy.pair.as_pins(), {"pip": PIP_VERSION, "pip-tools": PIP_TOOLS_VERSION})
            self.assertEqual(policy.sha256, verifier.hashlib.sha256(source.read_bytes()).hexdigest())

    def test_source_rejects_every_non_pair_requirement_form(self) -> None:
        invalid_sources = (
            ("missing", f"pip=={PIP_VERSION}\n"),
            ("extra", _bootstrap_text() + "wheel==1\n"),
            ("duplicate", f"pip=={PIP_VERSION}\npip=={PIP_VERSION}\n"),
            ("reordered", f"pip-tools=={PIP_TOOLS_VERSION}\npip=={PIP_VERSION}\n"),
            ("normalized-alias", f"pip=={PIP_VERSION}\npip_tools=={PIP_TOOLS_VERSION}\n"),
            ("uppercase", f"PIP=={PIP_VERSION}\npip-tools=={PIP_TOOLS_VERSION}\n"),
            ("spaced-operator", f"pip == {PIP_VERSION}\npip-tools=={PIP_TOOLS_VERSION}\n"),
            ("marker", f"pip=={PIP_VERSION}; python_version == '3.12'\npip-tools=={PIP_TOOLS_VERSION}\n"),
            ("range", f"pip>={PIP_VERSION}\npip-tools=={PIP_TOOLS_VERSION}\n"),
            ("url", f"pip @ https://example.invalid/pip.whl\npip-tools=={PIP_TOOLS_VERSION}\n"),
            ("include", f"-r other.txt\npip=={PIP_VERSION}\npip-tools=={PIP_TOOLS_VERSION}\n"),
            ("hash", f"pip=={PIP_VERSION} --hash=sha256:00\npip-tools=={PIP_TOOLS_VERSION}\n"),
            ("continuation", f"pip=={PIP_VERSION} \\\npip-tools=={PIP_TOOLS_VERSION}\n"),
        )
        with tempfile.TemporaryDirectory() as raw_directory:
            source = Path(raw_directory).resolve() / "requirements-bootstrap.txt"
            for label, text_value in invalid_sources:
                with self.subTest(label=label):
                    source.write_text(text_value, encoding="utf-8")
                    with self.assertRaises(verifier.PolicyError) as raised:
                        verifier.load_bootstrap_requirements(source)
                    self.assertEqual(raised.exception.code, "bootstrap-source-invalid")

    def test_source_rejects_non_utf8_oversized_symlink_and_nonregular_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            source = directory / "requirements-bootstrap.txt"
            source.write_bytes(b"pip==\xff\n")
            with self.assertRaises(verifier.PolicyError) as non_utf8:
                verifier.load_bootstrap_requirements(source)
            self.assertEqual(non_utf8.exception.code, "bootstrap-source-invalid")

            source.write_text(_bootstrap_text(), encoding="utf-8")
            with (
                mock.patch.object(verifier, "MAX_CONSTRAINT_BYTES", 8),
                self.assertRaises(verifier.PolicyError) as oversized,
            ):
                verifier.load_bootstrap_requirements(source)
            self.assertEqual(oversized.exception.code, "bootstrap-source-invalid")

            target = directory / "target.txt"
            target.write_text(_bootstrap_text(), encoding="utf-8")
            source.unlink()
            source.symlink_to(target)
            with self.assertRaises(verifier.PolicyError) as symlink:
                verifier.load_bootstrap_requirements(source)
            self.assertEqual(symlink.exception.code, "bootstrap-source-invalid")

            with self.assertRaises(verifier.PolicyError) as nonregular:
                verifier.load_bootstrap_requirements(directory)
            self.assertEqual(nonregular.exception.code, "bootstrap-source-invalid")

    def test_policy_readers_reject_a_path_swapped_after_open(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            trusted = directory / "trusted.txt"
            replacement = directory / "replacement.txt"
            replacement.write_text(_bootstrap_text("9", "8"), encoding="utf-8")
            real_open = verifier.os.open
            swapped = False

            def swapping_open(path: str | os.PathLike[str], flags: int) -> int:
                nonlocal swapped
                descriptor = real_open(path, flags)
                if not swapped and os.path.normcase(os.fspath(path)) == os.path.normcase(os.fspath(trusted)):
                    swapped = True
                    trusted.unlink()
                    trusted.symlink_to(replacement)
                return descriptor

            trusted.write_text(_bootstrap_text(), encoding="utf-8")
            with (
                mock.patch.object(verifier.os, "open", side_effect=swapping_open),
                self.assertRaises(verifier.PolicyError) as source_swap,
            ):
                verifier.load_bootstrap_requirements(trusted)
            self.assertEqual(source_swap.exception.code, "bootstrap-source-invalid")

            trusted.unlink()
            trusted.write_text(_constraint_text(BASE_PINS), encoding="utf-8")
            replacement.write_text(
                _constraint_text({**BASE_PINS, "pip": "9", "pip-tools": "8"}),
                encoding="utf-8",
            )
            swapped = False
            with (
                mock.patch.object(verifier.os, "open", side_effect=swapping_open),
                self.assertRaises(verifier.PolicyError) as constraint_swap,
            ):
                verifier.load_constraint(trusted)
            self.assertEqual(constraint_swap.exception.code, "constraint-binding-changed")

    def test_windows_policy_reader_accepts_cross_interface_ctime_difference(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path = Path(raw_directory).resolve() / "constraint.lock"
            path.write_text(_constraint_text(BASE_PINS), encoding="utf-8")
            real_fstat = os.fstat

            def windows_fstat(descriptor: int) -> os.stat_result:
                observed = real_fstat(descriptor)
                return _stat_with_overrides(
                    observed,
                    st_ctime_ns=observed.st_ctime_ns + 1,
                )

            with (
                mock.patch.object(
                    verifier,
                    "WINDOWS_STAT_INTERFACES_DIVERGE",
                    True,
                ),
                mock.patch.object(verifier.os, "fstat", side_effect=windows_fstat),
            ):
                policy = verifier.load_constraint(path)

            self.assertEqual(policy.pins, BASE_PINS)

    def test_windows_policy_reader_rejects_cross_interface_content_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path = Path(raw_directory).resolve() / "constraint.lock"
            path.write_text(_constraint_text(BASE_PINS), encoding="utf-8")
            real_fstat = os.fstat

            for field in ("st_size", "st_mtime_ns"):
                with self.subTest(field=field):
                    def changed_fstat(descriptor: int) -> os.stat_result:
                        observed = real_fstat(descriptor)
                        return _stat_with_overrides(
                            observed,
                            **{field: cast(int, getattr(observed, field)) + 1},
                        )

                    with (
                        mock.patch.object(
                            verifier,
                            "WINDOWS_STAT_INTERFACES_DIVERGE",
                            True,
                        ),
                        mock.patch.object(
                            verifier.os,
                            "fstat",
                            side_effect=changed_fstat,
                        ),
                        self.assertRaises(verifier.PolicyError) as raised,
                    ):
                        verifier.load_constraint(path)

                    self.assertEqual(raised.exception.code, "constraint-binding-changed")

    def test_policy_reader_close_failure_does_not_mask_primary_base_exception(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path = Path(raw_directory).resolve() / "constraint.lock"
            path.write_text(_constraint_text(BASE_PINS), encoding="utf-8")
            real_close = os.close
            primary_errors = (KeyboardInterrupt("interrupt"), SystemExit(23))

            for primary_error in primary_errors:
                with self.subTest(primary=type(primary_error).__name__):
                    def close_then_fail(descriptor: int) -> None:
                        real_close(descriptor)
                        raise OSError("injected close failure")

                    with (
                        mock.patch.object(verifier.os, "read", side_effect=primary_error),
                        mock.patch.object(verifier.os, "close", side_effect=close_then_fail),
                        self.assertRaises(type(primary_error)) as raised,
                    ):
                        verifier.load_constraint(path)

                    self.assertIs(raised.exception, primary_error)
                    self.assertIn(
                        "Could not close constraint descriptor: injected close failure",
                        "\n".join(getattr(raised.exception, "__notes__", ())),
                    )

    def test_successful_policy_read_translates_descriptor_close_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path = Path(raw_directory).resolve() / "constraint.lock"
            path.write_text(_constraint_text(BASE_PINS), encoding="utf-8")
            real_close = os.close

            def close_then_fail(descriptor: int) -> None:
                real_close(descriptor)
                raise OSError("injected close failure")

            with (
                mock.patch.object(verifier.os, "close", side_effect=close_then_fail),
                self.assertRaises(verifier.PolicyError) as raised,
            ):
                verifier.load_constraint(path)

            self.assertEqual(raised.exception.code, "constraint-unreadable")
            self.assertIn(
                "Cannot close constraint descriptor after a successful read",
                str(raised.exception),
            )

    def test_successful_policy_read_preserves_control_flow_close_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path = Path(raw_directory).resolve() / "constraint.lock"
            path.write_text(_constraint_text(BASE_PINS), encoding="utf-8")
            real_close = os.close
            primary_error = KeyboardInterrupt("injected close interrupt")

            def close_then_interrupt(descriptor: int) -> None:
                real_close(descriptor)
                raise primary_error

            with (
                mock.patch.object(
                    verifier.os,
                    "close",
                    side_effect=close_then_interrupt,
                ),
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                verifier.load_constraint(path)

            self.assertIs(raised.exception, primary_error)

    def test_native_cohort_does_not_synthesize_sequential_file_generations(self) -> None:
        current_pair = (PIP_VERSION, PIP_TOOLS_VERSION)
        other_pair = ("26.1.1", "7.5.2")
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            source = directory / "requirements-bootstrap.txt"
            source.write_text(_bootstrap_text(*current_pair), encoding="utf-8")
            paths = tuple(directory / path for path in verifier.NATIVE_CONSTRAINT_PATHS)
            for path, pair in zip(
                paths,
                (current_pair, other_pair, other_pair),
                strict=True,
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    _constraint_text({"pip": pair[0], "pip-tools": pair[1]}),
                    encoding="utf-8",
                )

            replacements: list[Path] = []
            for index, (path, pair) in enumerate(
                zip(paths, (other_pair, current_pair, current_pair), strict=True)
            ):
                replacement = path.with_name(f".replacement-{index}.lock")
                replacement.write_text(
                    _constraint_text({"pip": pair[0], "pip-tools": pair[1]}),
                    encoding="utf-8",
                )
                replacements.append(replacement)

            real_open = os.open
            real_close = os.close
            first_constraint_descriptor: int | None = None
            switched = False

            def recording_open(
                path: str | os.PathLike[str],
                flags: int,
            ) -> int:
                nonlocal first_constraint_descriptor
                descriptor = real_open(path, flags)
                if Path(path).name == paths[0].name:
                    first_constraint_descriptor = descriptor
                return descriptor

            def switching_close(descriptor: int) -> None:
                nonlocal switched
                real_close(descriptor)
                if descriptor == first_constraint_descriptor and not switched:
                    switched = True
                    for replacement, path in zip(replacements, paths, strict=True):
                        os.replace(replacement, path)

            with (
                chdir(directory),
                mock.patch.object(verifier.os, "open", side_effect=recording_open),
                mock.patch.object(verifier.os, "close", side_effect=switching_close),
                self.assertRaises(verifier.PolicyError) as raised,
            ):
                verifier.load_bootstrap_state(
                    source_path=source,
                    selected_constraint_path=None,
                    policy="native-lock-workflow",
                )

            self.assertTrue(switched)
            self.assertEqual(raised.exception.code, "bootstrap-native-pair-mismatch")

    @unittest.skipIf(os.name == "nt", "Windows can deny replacing an open source file.")
    def test_native_cohort_revalidates_source_after_all_files_are_open(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            source = directory / "requirements-bootstrap.txt"
            source.write_text(_bootstrap_text(), encoding="utf-8")
            paths = _write_native_constraints(
                directory,
                pip_version=PIP_VERSION,
                pip_tools_version=PIP_TOOLS_VERSION,
            )
            replacement = directory / ".replacement-bootstrap.txt"
            replacement.write_text(_bootstrap_text("9", "8"), encoding="utf-8")
            real_open = os.open
            swapped = False

            def swapping_open(
                path: str | os.PathLike[str],
                flags: int,
            ) -> int:
                nonlocal swapped
                descriptor = real_open(path, flags)
                if Path(path).name == paths[-1].name and not swapped:
                    swapped = True
                    os.replace(replacement, source)
                return descriptor

            with (
                chdir(directory),
                mock.patch.object(verifier.os, "open", side_effect=swapping_open),
                self.assertRaises(verifier.PolicyError) as raised,
            ):
                verifier.load_bootstrap_state(
                    source_path=source,
                    selected_constraint_path=None,
                    policy="native-lock-workflow",
                )

            self.assertTrue(swapped)
            self.assertEqual(raised.exception.code, "bootstrap-source-invalid")
            self.assertIn("changed while it was being read", str(raised.exception))

    def test_native_cohort_closes_every_descriptor_in_reverse_on_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            source = directory / "requirements-bootstrap.txt"
            source.write_text(_bootstrap_text(), encoding="utf-8")
            _write_native_constraints(
                directory,
                pip_version=PIP_VERSION,
                pip_tools_version=PIP_TOOLS_VERSION,
            )
            real_open = os.open
            real_close = os.close
            opened: list[int] = []
            closed: list[int] = []
            primary_error = KeyboardInterrupt("injected read interrupt")

            def recording_open(
                path: str | os.PathLike[str],
                flags: int,
            ) -> int:
                descriptor = real_open(path, flags)
                opened.append(descriptor)
                return descriptor

            def close_then_fail(descriptor: int) -> None:
                closed.append(descriptor)
                real_close(descriptor)
                raise OSError(f"injected close failure for {descriptor}")

            with (
                chdir(directory),
                mock.patch.object(verifier.os, "open", side_effect=recording_open),
                mock.patch.object(verifier.os, "read", side_effect=primary_error),
                mock.patch.object(verifier.os, "close", side_effect=close_then_fail),
                self.assertRaises(KeyboardInterrupt) as raised,
            ):
                verifier.load_bootstrap_state(
                    source_path=source,
                    selected_constraint_path=None,
                    policy="native-lock-workflow",
                )

            self.assertIs(raised.exception, primary_error)
            self.assertEqual(len(opened), 4)
            self.assertEqual(closed, list(reversed(opened)))
            notes = getattr(raised.exception, "__notes__", ())
            self.assertEqual(len(notes), 4)
            self.assertTrue(
                all("Could not close constraint descriptor" in note for note in notes)
            )

    def test_held_cohort_rejects_duplicate_file_identities(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            source = directory / "requirements-bootstrap.txt"
            source.write_text(_bootstrap_text(), encoding="utf-8")
            constraint = directory / "constraint.lock"
            os.link(source, constraint)

            with (
                mock.patch.object(verifier, "paths_alias", return_value=False),
                self.assertRaises(verifier.PolicyError) as raised,
            ):
                verifier.load_bootstrap_state(
                    source_path=source,
                    selected_constraint_path=constraint,
                    policy="stable",
                )

            self.assertEqual(raised.exception.code, "bootstrap-path-alias")

    def test_policy_reader_rejects_redirected_external_grandparent(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            physical = directory / "physical"
            nested = physical / "nested"
            nested.mkdir(parents=True)
            constraint = nested / "constraint.lock"
            constraint.write_text(_constraint_text(BASE_PINS), encoding="utf-8")
            redirected_parent = directory / "redirected"
            _create_directory_link(redirected_parent, physical)
            redirected_constraint = redirected_parent / "nested" / constraint.name

            with self.assertRaises(verifier.PolicyError) as raised:
                verifier.load_constraint(redirected_constraint)

            self.assertEqual(raised.exception.code, "constraint-not-physical")

    def test_policy_reader_rejects_parent_traversal_after_linked_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            trusted = directory / "trusted"
            external = directory / "external"
            linked_child = external / "child"
            trusted.mkdir()
            linked_child.mkdir(parents=True)
            (external / "constraint.lock").write_text(
                _constraint_text({**BASE_PINS, "root-package": "external"}),
                encoding="utf-8",
            )
            _create_directory_link(trusted / "linked-child", linked_child)
            redirected_constraint = (
                trusted / "linked-child" / ".." / "constraint.lock"
            )

            with self.assertRaises(verifier.PolicyError) as raised:
                verifier.load_constraint(redirected_constraint)

            self.assertEqual(raised.exception.code, "constraint-not-physical")

    def test_policy_readers_translate_embedded_null_paths(self) -> None:
        invalid_path = Path(f"constraint{chr(0)}.lock")
        cases = (
            (verifier.load_constraint, "constraint-unreadable"),
            (verifier.load_bootstrap_requirements, "bootstrap-source-invalid"),
        )

        for loader, expected_code in cases:
            with self.subTest(loader=loader.__name__):
                with self.assertRaises(verifier.PolicyError) as raised:
                    loader(invalid_path)
                self.assertEqual(raised.exception.code, expected_code)

        with self.assertRaises(verifier.PolicyError) as cohort_error:
            verifier.load_bootstrap_state(
                source_path=invalid_path,
                selected_constraint_path=Path("constraint.lock"),
                policy="stable",
            )
        self.assertEqual(cohort_error.exception.code, "path-alias-check-failed")

    def test_native_policy_rejects_constraints_reached_through_linked_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            checkout = directory / "checkout"
            external = directory / "external"
            checkout.mkdir()
            _write_native_constraints(
                external,
                pip_version=PIP_VERSION,
                pip_tools_version=PIP_TOOLS_VERSION,
            )
            (checkout / "requirements-bootstrap.txt").write_text(_bootstrap_text(), encoding="utf-8")
            _create_directory_link(checkout / "constraints", external / "constraints")

            with chdir(checkout), self.assertRaises(verifier.PolicyError) as redirected:
                verifier.load_bootstrap_state(
                    source_path=Path("requirements-bootstrap.txt"),
                    selected_constraint_path=None,
                    policy="native-lock-workflow",
                )

            self.assertEqual(redirected.exception.code, "constraint-not-physical")

    def test_stable_state_requires_source_and_selected_lock_equality(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            source = directory / "requirements-bootstrap.txt"
            source.write_text(_bootstrap_text(), encoding="utf-8")
            constraint = directory / "constraint.lock"
            constraint.write_text(_constraint_text(BASE_PINS), encoding="utf-8")

            state = verifier.load_bootstrap_state(
                source_path=source,
                selected_constraint_path=constraint,
                policy="stable",
            )

            self.assertEqual(state.state, "stable")
            constraint.write_text(
                _constraint_text({**BASE_PINS, "pip-tools": "7.5.2"}),
                encoding="utf-8",
            )
            with self.assertRaises(verifier.PolicyError) as mismatch:
                verifier.load_bootstrap_state(
                    source_path=source,
                    selected_constraint_path=constraint,
                    policy="stable",
                )
            self.assertEqual(mismatch.exception.code, "bootstrap-source-lock-mismatch")
            self.assertIn("commit all three reviewed lock artifacts", str(mismatch.exception))

    def test_native_state_allows_platform_graph_differences_and_one_source_transition(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            source = directory / "requirements-bootstrap.txt"
            source.write_text(_bootstrap_text(), encoding="utf-8")
            _write_native_constraints(
                directory,
                pip_version=PIP_VERSION,
                pip_tools_version=PIP_TOOLS_VERSION,
            )

            with chdir(directory):
                stable_state = verifier.load_bootstrap_state(
                    source_path=source,
                    selected_constraint_path=None,
                    policy="native-lock-workflow",
                )

            self.assertEqual(stable_state.state, "stable")
            self.assertEqual(stable_state.current_pair, stable_state.proposed_pair)
            _write_native_constraints(
                directory,
                pip_version="26.1.1",
                pip_tools_version="7.5.2",
            )

            with chdir(directory):
                state = verifier.load_bootstrap_state(
                    source_path=source,
                    selected_constraint_path=None,
                    policy="native-lock-workflow",
                )

            self.assertEqual(state.state, "source-transition")
            self.assertEqual(state.current_pair.as_pins(), {"pip": "26.1.1", "pip-tools": "7.5.2"})
            self.assertEqual(state.proposed_pair.as_pins(), {"pip": PIP_VERSION, "pip-tools": PIP_TOOLS_VERSION})

    def test_native_state_rejects_mixed_or_incomplete_platform_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            source = directory / "requirements-bootstrap.txt"
            source.write_text(_bootstrap_text(), encoding="utf-8")
            paths = _write_native_constraints(
                directory,
                pip_version="26.1.1",
                pip_tools_version="7.5.2",
            )
            paths[1].write_text(
                _constraint_text({"pip": PIP_VERSION, "pip-tools": PIP_TOOLS_VERSION}),
                encoding="utf-8",
            )
            with chdir(directory), self.assertRaises(verifier.PolicyError) as mixed:
                verifier.load_bootstrap_state(
                    source_path=source,
                    selected_constraint_path=None,
                    policy="native-lock-workflow",
                )
            self.assertEqual(mixed.exception.code, "bootstrap-native-pair-mismatch")

            paths[1].write_text(_constraint_text({"pip": "26.1.1"}), encoding="utf-8")
            with chdir(directory), self.assertRaises(verifier.PolicyError) as missing:
                verifier.load_bootstrap_state(
                    source_path=source,
                    selected_constraint_path=None,
                    policy="native-lock-workflow",
                )
            self.assertEqual(missing.exception.code, "bootstrap-pair-missing")

    def test_preflight_receipt_is_atomic_deterministic_and_records_transition(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            _write_native_constraints(
                directory,
                pip_version="26.1.1",
                pip_tools_version="7.5.2",
            )
            (directory / "requirements-bootstrap.txt").write_text(_bootstrap_text(), encoding="utf-8")
            output = directory / "receipt.json"
            output.write_text("stale", encoding="utf-8")
            with chdir(directory), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = verifier.bootstrap_preflight_main(
                    [
                        "--source",
                        "requirements-bootstrap.txt",
                        "--policy",
                        "native-lock-workflow",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(result, 0)
            payload = output.read_bytes()
            self.assertTrue(payload.endswith(b"\n"))
            receipt = cast(dict[str, object], json.loads(payload))
            self.assertEqual(receipt["status"], "verified")
            self.assertEqual(receipt["state"], "source-transition")
            constraints = cast(list[dict[str, object]], receipt["constraints"])
            self.assertEqual(
                [item["path"] for item in constraints],
                [str(path) for path in verifier.NATIVE_CONSTRAINT_PATHS],
            )
            for item in constraints:
                self.assertRegex(cast(str, item["sha256"]), r"[0-9a-f]{64}\Z")
                self.assertRegex(cast(str, item["pin_fingerprint"]), r"[0-9a-f]{64}\Z")
            transition = cast(dict[str, object], receipt["source_transition"])
            self.assertEqual(transition["active"], True)
            with chdir(directory), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                repeated_result = verifier.bootstrap_preflight_main(
                    [
                        "--source",
                        "requirements-bootstrap.txt",
                        "--policy",
                        "native-lock-workflow",
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(repeated_result, 0)
            self.assertEqual(output.read_bytes(), payload)

    def test_atomic_receipt_closes_raw_descriptor_when_fdopen_fails(self) -> None:
        for close_fails in (False, True):
            with self.subTest(close_fails=close_fails):
                with tempfile.TemporaryDirectory() as raw_directory:
                    directory = Path(raw_directory).resolve()
                    output = directory / "receipt.json"
                    real_mkstemp = tempfile.mkstemp
                    real_close = os.close
                    created_descriptor = -1
                    primary_error = RuntimeError("injected fdopen failure")

                    def recording_mkstemp(
                        suffix: str | None = None,
                        prefix: str | None = None,
                        directory: str | os.PathLike[str] | None = None,
                        text: bool = False,
                        **kwargs: str | os.PathLike[str] | bool | None,
                    ) -> tuple[int, str]:
                        nonlocal created_descriptor
                        selected_directory = cast(
                            str | os.PathLike[str] | None,
                            kwargs.get("dir", directory),
                        )
                        created_descriptor, temporary_name = real_mkstemp(
                            suffix=suffix,
                            prefix=prefix,
                            dir=selected_directory,
                            text=text,
                        )
                        return created_descriptor, temporary_name

                    def close_descriptor(descriptor: int) -> None:
                        real_close(descriptor)
                        if close_fails:
                            raise OSError("injected descriptor close failure")

                    with (
                        mock.patch.object(
                            verifier.tempfile,
                            "mkstemp",
                            side_effect=recording_mkstemp,
                        ),
                        mock.patch.object(verifier.os, "fdopen", side_effect=primary_error),
                        mock.patch.object(verifier.os, "close", side_effect=close_descriptor),
                        self.assertRaises(RuntimeError) as raised,
                    ):
                        verifier.atomic_write_receipt(output, {"status": "verified"})

                    self.assertIs(raised.exception, primary_error)
                    self.assertGreaterEqual(created_descriptor, 0)
                    with self.assertRaises(OSError):
                        os.fstat(created_descriptor)
                    notes = "\n".join(getattr(raised.exception, "__notes__", ()))
                    if close_fails:
                        self.assertIn(
                            "Could not close receipt temporary descriptor: "
                            "injected descriptor close failure",
                            notes,
                        )
                    else:
                        self.assertEqual(notes, "")
                    self.assertEqual(list(directory.glob(".receipt.json.*.tmp")), [])

    def test_atomic_receipt_cleanup_does_not_mask_primary_base_exception(self) -> None:
        primary_errors = (
            RuntimeError("injected replace failure"),
            KeyboardInterrupt("interrupt"),
            SystemExit(23),
        )
        for primary_error in primary_errors:
            with self.subTest(primary=type(primary_error).__name__):
                with tempfile.TemporaryDirectory() as raw_directory:
                    directory = Path(raw_directory).resolve()
                    output = directory / "receipt.json"
                    with (
                        mock.patch.object(verifier.os, "replace", side_effect=primary_error),
                        mock.patch.object(
                            verifier.Path,
                            "unlink",
                            side_effect=OSError("injected cleanup failure"),
                        ),
                        self.assertRaises(type(primary_error)) as raised,
                    ):
                        verifier.atomic_write_receipt(output, {"status": "verified"})

                    self.assertIs(raised.exception, primary_error)
                    self.assertIn(
                        "Could not remove receipt temporary file: injected cleanup failure",
                        "\n".join(getattr(raised.exception, "__notes__", ())),
                    )
                    temporary_files = list(directory.glob(".receipt.json.*.tmp"))
                    self.assertEqual(len(temporary_files), 1)
                    os.unlink(temporary_files[0])

    def test_stable_preflight_writes_success_and_actionable_failure_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            source = directory / "requirements-bootstrap.txt"
            constraint = directory / "constraint.lock"
            output = directory / "receipt.json"
            source.write_text(_bootstrap_text(), encoding="utf-8")
            constraint.write_text(_constraint_text(BASE_PINS), encoding="utf-8")
            arguments = [
                "--source",
                str(source),
                "--policy",
                "stable",
                "--constraint",
                str(constraint),
                "--output",
                str(output),
            ]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                success = verifier.bootstrap_preflight_main(arguments)
            self.assertEqual(success, 0)
            success_receipt = cast(dict[str, object], json.loads(output.read_bytes()))
            self.assertEqual((success_receipt["status"], success_receipt["state"]), ("verified", "stable"))

            constraint.write_text(
                _constraint_text({**BASE_PINS, "pip-tools": "7.5.2"}),
                encoding="utf-8",
            )
            stderr = StringIO()
            with (
                mock.patch.object(verifier.subprocess, "Popen") as popen_mock,
                redirect_stdout(StringIO()),
                redirect_stderr(stderr),
            ):
                failure = verifier.bootstrap_preflight_main(arguments)
            self.assertEqual(failure, 1)
            popen_mock.assert_not_called()
            diagnostic = stderr.getvalue()
            self.assertEqual(len(diagnostic.splitlines()), 1)
            self.assertEqual(diagnostic.count("bootstrap-source-lock-mismatch"), 1)
            self.assertEqual(
                diagnostic.count(
                    f"source has pip=={PIP_VERSION}, pip-tools=={PIP_TOOLS_VERSION}"
                ),
                1,
            )
            self.assertEqual(
                diagnostic.count(
                    f"selected constraint has pip=={PIP_VERSION}, pip-tools==7.5.2"
                ),
                1,
            )
            self.assertEqual(
                diagnostic.count("Run the native Dependency Locks workflow"),
                1,
            )
            failure_receipt = cast(dict[str, object], json.loads(output.read_bytes()))
            self.assertEqual((failure_receipt["status"], failure_receipt["state"]), ("failed", "invalid"))
            errors = cast(list[dict[str, object]], failure_receipt["errors"])
            self.assertEqual([error["code"] for error in errors], ["bootstrap-source-lock-mismatch"])

    def test_preflight_rejects_source_constraint_and_output_aliases_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory).resolve()
            source = directory / "requirements-bootstrap.txt"
            source_bytes = _bootstrap_text().encode("utf-8")
            source.write_bytes(source_bytes)
            constraint = directory / "constraint.lock"
            constraint_bytes = _constraint_text(BASE_PINS).encode("utf-8")
            constraint.write_bytes(constraint_bytes)

            cases = (
                ("source-output", source, constraint, source),
                ("constraint-output", source, constraint, constraint),
                ("source-constraint", source, source, directory / "receipt.json"),
            )
            for label, selected_source, selected_constraint, output in cases:
                with self.subTest(label=label), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    result = verifier.bootstrap_preflight_main(
                        [
                            "--source",
                            str(selected_source),
                            "--policy",
                            "stable",
                            "--constraint",
                            str(selected_constraint),
                            "--output",
                            str(output),
                        ]
                    )
                self.assertEqual(result, 2)
                self.assertEqual(source.read_bytes(), source_bytes)
                self.assertEqual(constraint.read_bytes(), constraint_bytes)

            native_paths = _write_native_constraints(
                directory,
                pip_version=PIP_VERSION,
                pip_tools_version=PIP_TOOLS_VERSION,
            )
            native_bytes = native_paths[0].read_bytes()
            with chdir(directory), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                native_alias = verifier.bootstrap_preflight_main(
                    [
                        "--source",
                        source.name,
                        "--policy",
                        "native-lock-workflow",
                        "--output",
                        str(native_paths[0]),
                    ]
                )
            self.assertEqual(native_alias, 2)
            self.assertEqual(native_paths[0].read_bytes(), native_bytes)


if __name__ == "__main__":
    unittest.main()
