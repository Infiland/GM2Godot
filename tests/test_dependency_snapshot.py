from __future__ import annotations

from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
import copy
import errno
from io import StringIO
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Generator, Mapping
from types import ModuleType
from typing import Any, cast
import unittest
from unittest import mock

from scripts import build_dependency_snapshot as snapshotter


SHA = "0123456789abcdef0123456789abcdef01234567"
SCANNED = "2026-09-02T12:34:56Z"
ANCHORED_OUTPUT: ModuleType = getattr(snapshotter, "_ANCHORED_OUTPUT")
ANCHORED_OUTPUT_ERROR: Any = getattr(ANCHORED_OUTPUT, "AnchoredOutputError")
OUTPUT_PARENT_BINDING_TYPE: Any = getattr(ANCHORED_OUTPUT, "OutputParentBinding")
OPEN_OUTPUT_PARENT: Any = getattr(ANCHORED_OUTPUT, "open_output_parent")
WINDOWS_FILE_ATTRIBUTE_DIRECTORY = cast(
    int,
    getattr(ANCHORED_OUTPUT, "_WINDOWS_FILE_ATTRIBUTE_DIRECTORY"),
)
WINDOWS_FILE_TYPE_DISK = cast(
    int,
    getattr(ANCHORED_OUTPUT, "_WINDOWS_FILE_TYPE_DISK"),
)
OPEN_WINDOWS_DIRECTORY_HANDLE: Any = getattr(
    ANCHORED_OUTPUT,
    "_open_windows_directory_handle",
)
ENVIRONMENT = {
    "implementation_name": "cpython",
    "implementation_version": "3.12.13",
    "os_name": "posix",
    "platform_machine": "x86_64",
    "platform_python_implementation": "CPython",
    "platform_release": "6.11.0",
    "platform_system": "Linux",
    "platform_version": "#1 SMP",
    "python_full_version": "3.12.13",
    "python_version": "3.12",
    "sys_platform": "linux",
}
PINS = {
    "app": "1.0",
    "core": "2.0",
    "feature-dep": "3.0+local",
    "packaging": "26.2",
    "pip": "26.2.1",
    "pip-tools": "7.6.1",
    "tool": "4.0",
}


def _publish_new_json(path: Path, value: Mapping[str, object]) -> None:
    payload = (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    ANCHORED_OUTPUT.publish_new_bytes(path, payload)


def _installed_item(
    name: str,
    version: str,
    *,
    requirements: list[str] | None = None,
    extras: list[str] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {"name": name, "version": version}
    if requirements is not None:
        metadata["requires_dist"] = requirements
    if extras is not None:
        metadata["provides_extra"] = extras
    return {
        "metadata": metadata,
        "metadata_location": f"/verified/lib/{name}-{version}.dist-info",
        "installer": "pip",
        "requested": name in {"app", "pip", "pip-tools", "tool"},
    }


def _inspect_value() -> dict[str, object]:
    return {
        "version": "1",
        "pip_version": PINS["pip"],
        "environment": dict(ENVIRONMENT),
        "installed": [
            _installed_item(
                "App",
                PINS["app"],
                requirements=[
                    "Core>=2",
                    "Feature_Dep==3.0+local; extra == 'feature'",
                    "missing-package; extra == 'other'",
                ],
                extras=["feature", "other"],
            ),
            _installed_item("core", PINS["core"]),
            _installed_item("feature-dep", PINS["feature-dep"]),
            _installed_item("packaging", PINS["packaging"]),
            _installed_item("pip", PINS["pip"]),
            _installed_item("pip_tools", PINS["pip-tools"], requirements=["packaging>=26"]),
            _installed_item("tool", PINS["tool"], requirements=["core>=2"]),
        ],
    }


def _distribution(
    name: str,
    *,
    requirements: tuple[str, ...] = (),
    extras: tuple[str, ...] = (),
) -> snapshotter.InstalledDistribution:
    return snapshotter.InstalledDistribution(
        name=name,
        version="1",
        requirements=tuple(snapshotter.REQUIREMENT(requirement) for requirement in requirements),
        provided_extras=frozenset(extras),
    )


def _authored_policy(root_names: tuple[str, ...]) -> snapshotter.AuthoredPolicy:
    return snapshotter.AuthoredPolicy(
        files=(),
        roots={
            name: snapshotter.AuthoredRoot(
                name=name,
                version="1",
                extras=frozenset(),
                scope="development",
                sources=("requirements-tooling.txt",),
            )
            for name in root_names
        },
        fingerprint="fixture",
    )


@contextmanager
def _working_directory(path: Path) -> Generator[None, None, None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class SnapshotFixture:
    def __init__(self, root: Path, *, platform_label: str = "linux-x64") -> None:
        self.root = root
        (root / "requirements.txt").write_text(
            'App[feature]==1.0; python_version >= "3.12"\n',
            encoding="utf-8",
        )
        (root / "requirements-bootstrap.txt").write_text(
            "# Review these exact pins as one compatibility unit.\n"
            "pip==26.2.1\n"
            "pip-tools==7.6.1\n",
            encoding="utf-8",
        )
        (root / "requirements-tooling.txt").write_text("Tool==4.0\n", encoding="utf-8")
        self.constraint_path = root / "candidate.lock"
        self.constraint_path.write_text(
            "# generated\n" + "".join(f"{name}=={version}\n" for name, version in sorted(PINS.items())),
            encoding="utf-8",
        )
        self.inspect_value = _inspect_value()
        (
            sys_platform,
            os_name,
            platform_system,
            platform_machine,
            python_full_version,
            _,
        ) = snapshotter.PLATFORM_POLICIES[platform_label]
        environment = cast(dict[str, str], self.inspect_value["environment"])
        environment.update(
            {
                "implementation_version": python_full_version,
                "os_name": os_name,
                "platform_machine": platform_machine,
                "platform_system": platform_system,
                "python_full_version": python_full_version,
                "python_version": python_full_version.rpartition(".")[0],
                "sys_platform": sys_platform,
            }
        )
        self.inspect = snapshotter.parse_inspect_report(self.inspect_value)
        with _working_directory(root):
            self.authored = snapshotter.load_authored_policy(self.inspect.environment)
        self.constraint = snapshotter.load_constraint(self.constraint_path)
        self.receipt_path = root / "fresh-2.json"
        self.write_receipt()

    def receipt(self) -> dict[str, object]:
        installed_pins = {
            name: distribution.version for name, distribution in self.inspect.installed.items()
        }
        constraint_pins = [
            {"name": name, "version": self.constraint.pins[name]}
            for name in sorted(self.constraint.pins)
        ]
        observed_pins = [
            {"name": name, "version": installed_pins[name]} for name in sorted(installed_pins)
        ]
        bootstrap_file = next(
            file for file in self.authored.files if file.path.name == "requirements-bootstrap.txt"
        )
        bootstrap_pins = {"pip": PINS["pip"], "pip-tools": PINS["pip-tools"]}
        pair_fingerprint = snapshotter.pin_fingerprint(bootstrap_pins)
        constraint_entries = [
            {
                "path": str(self.constraint_path),
                "sha256": self.constraint.file.sha256,
                "pin_fingerprint": snapshotter.pin_fingerprint(self.constraint.pins),
                "bootstrap_pins": dict(bootstrap_pins),
            }
        ]
        observed_environment = {
            key: self.inspect.environment[key] for key in snapshotter.RECEIPT_ENVIRONMENT_KEYS
        }
        return {
            "schema_version": 2,
            "status": "verified",
            "mode": "complete",
            "errors": [],
            "required": ["app", "pip", "pip-tools", "tool"],
            "bootstrap": {
                "policy": "stable",
                "state": "stable",
                "source": {
                    "path": str(bootstrap_file.path),
                    "sha256": bootstrap_file.sha256,
                    "pin_fingerprint": pair_fingerprint,
                    "pins": dict(bootstrap_pins),
                },
                "constraints": constraint_entries,
                "source_transition": {
                    "active": False,
                    "from": dict(bootstrap_pins),
                    "to": dict(bootstrap_pins),
                },
            },
            "constraint": {
                "path": str(self.constraint_path),
                "sha256": self.constraint.file.sha256,
                "fingerprint": snapshotter.pin_fingerprint(self.constraint.pins),
                "pins": constraint_pins,
            },
            "expected_environment": {
                "implementation_name": self.inspect.environment["implementation_name"],
                "pip_version": self.inspect.pip_version,
                "platform_machine": self.inspect.environment["platform_machine"],
                "python_full_version": self.inspect.environment["python_full_version"],
                "python_version": self.inspect.environment["python_version"],
                "sys_platform": self.inspect.environment["sys_platform"],
            },
            "observation": {
                "environment": observed_environment,
                "installed": observed_pins,
                "installed_fingerprint": snapshotter.pin_fingerprint(installed_pins),
                "pip_inspect_schema": "1",
                "pip_version": self.inspect.pip_version,
                "pip_inspect": {"returncode": 0, "stderr": ""},
                "pip_check": {"returncode": 0, "stderr": "", "stdout": "ok\n"},
            },
        }

    def write_receipt(self, value: dict[str, object] | None = None) -> None:
        self.receipt_path.write_text(
            json.dumps(self.receipt() if value is None else value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def verify(self, platform_label: str = "linux-x64") -> snapshotter.RegularFile:
        receipt_file = snapshotter.read_regular_file(
            self.receipt_path,
            snapshotter.MAX_RECEIPT_BYTES,
            label="verification receipt",
        )
        snapshotter.verify_receipt(
            snapshotter.parse_json_bytes(receipt_file.content, label="verification receipt"),
            receipt_file=receipt_file,
            constraint=self.constraint,
            authored=self.authored,
            inspect=self.inspect,
            platform_label=platform_label,
        )
        return receipt_file


class DependencySnapshotTests(unittest.TestCase):
    def test_extra_markers_use_complete_requested_set_semantics(self) -> None:
        equals_both = snapshotter.REQUIREMENT(
            'dependency; extra == "feature" and extra == "other"'
        )
        excludes_feature = snapshotter.REQUIREMENT(
            'dependency; extra != "feature"'
        )
        reversed_equals = snapshotter.REQUIREMENT(
            'dependency; "feature" == extra'
        )
        unsupported_order = snapshotter.REQUIREMENT(
            'dependency; extra > "feature"'
        )
        quoted_word = snapshotter.REQUIREMENT(
            'dependency; platform_version == "has extra feature"'
        )

        self.assertTrue(
            snapshotter.marker_is_active(
                equals_both,
                ENVIRONMENT,
                ("feature", "other"),
            )
        )
        self.assertFalse(
            snapshotter.marker_is_active(equals_both, ENVIRONMENT, ("feature",))
        )
        self.assertFalse(
            snapshotter.marker_is_active(excludes_feature, ENVIRONMENT, ("feature",))
        )
        self.assertTrue(snapshotter.marker_is_active(excludes_feature, ENVIRONMENT, ()))
        self.assertTrue(
            snapshotter.marker_is_active(reversed_equals, ENVIRONMENT, ("feature",))
        )
        self.assertTrue(
            snapshotter.marker_is_active(
                quoted_word,
                {**ENVIRONMENT, "platform_version": "has extra feature"},
                ("feature",),
            )
        )
        with self.assertRaisesRegex(
            snapshotter.SnapshotError,
            "Only extra equality and inequality are supported",
        ):
            snapshotter.marker_is_active(unsupported_order, ENVIRONMENT, ("feature",))

    def test_each_platform_label_rejects_self_consistent_wrong_native_tuple(self) -> None:
        mutations = (
            {"platform_machine": "aarch64"},
            {
                "implementation_version": "3.13.9",
                "python_full_version": "3.13.9",
                "python_version": "3.13",
            },
        )
        for platform_label in snapshotter.PLATFORM_POLICIES:
            for mutation in mutations:
                with (
                    self.subTest(platform=platform_label, mutation=mutation),
                    tempfile.TemporaryDirectory() as raw_directory,
                ):
                    root = Path(raw_directory)
                    fixture = SnapshotFixture(root, platform_label=platform_label)
                    environment = cast(
                        dict[str, str],
                        fixture.inspect_value["environment"],
                    )
                    environment.update(mutation)
                    fixture.inspect = snapshotter.parse_inspect_report(
                        fixture.inspect_value
                    )
                    with _working_directory(root):
                        fixture.authored = snapshotter.load_authored_policy(
                            fixture.inspect.environment
                        )
                    fixture.write_receipt()

                    with self.assertRaisesRegex(
                        snapshotter.SnapshotError,
                        f"Selected platform {platform_label!r} disagrees",
                    ):
                        fixture.verify(platform_label)

    def test_verified_snapshot_closes_extras_markers_and_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            fixture = SnapshotFixture(Path(raw_directory))
            snapshotter.verify_exact_sets(fixture.constraint, fixture.authored, fixture.inspect)
            receipt_file = fixture.verify()
            graph = snapshotter.build_dependency_graph(fixture.authored, fixture.inspect)

            self.assertEqual(graph.scopes["app"], "runtime")
            self.assertEqual(graph.scopes["core"], "runtime")
            self.assertEqual(graph.scopes["feature-dep"], "runtime")
            self.assertEqual(graph.scopes["pip-tools"], "development")
            self.assertEqual(graph.scopes["packaging"], "development")
            self.assertEqual(graph.edges["app"], frozenset({"core", "feature-dep"}))
            self.assertNotIn("missing-package", graph.edges["app"])

            value = snapshotter.build_snapshot(
                constraint=fixture.constraint,
                receipt_file=receipt_file,
                authored=fixture.authored,
                inspect=fixture.inspect,
                graph=graph,
                platform_label="linux-x64",
                repository="Infiland/GM2Godot",
                sha=SHA,
                ref="refs/heads/main",
                run_id="12345",
                run_attempt="2",
                scanned=SCANNED,
            )

            self.assertEqual(value["version"], 0)
            self.assertEqual(value["sha"], SHA)
            self.assertEqual(value["scanned"], SCANNED)
            self.assertEqual(cast(dict[str, object], value["detector"])["version"], "1")
            self.assertEqual(
                cast(dict[str, object], value["job"])["correlator"],
                "gm2godot-dependency-locks-linux-x64",
            )
            self.assertEqual(
                cast(dict[str, object], value["job"])["html_url"],
                "https://github.com/Infiland/GM2Godot/actions/runs/12345",
            )
            manifests = cast(dict[str, dict[str, object]], value["manifests"])
            manifest_path = "constraints/requirements-linux-py312.lock"
            resolved = cast(dict[str, dict[str, object]], manifests[manifest_path]["resolved"])
            app_purl = "pkg:pypi/app@1.0"
            feature_purl = "pkg:pypi/feature-dep@3.0%2Blocal"
            self.assertEqual(resolved[app_purl]["relationship"], "direct")
            self.assertEqual(resolved[app_purl]["scope"], "runtime")
            self.assertIn(feature_purl, cast(list[str], resolved[app_purl]["dependencies"]))
            self.assertEqual(resolved["pkg:pypi/packaging@26.2"]["relationship"], "indirect")
            self.assertEqual(resolved["pkg:pypi/packaging@26.2"]["scope"], "development")
            self.assertEqual(len(cast(dict[str, object], value["metadata"])), 8)

    def test_negative_extra_graph_policy_is_root_order_independent(self) -> None:
        inspect = snapshotter.InspectReport(
            pip_version="1",
            environment=ENVIRONMENT,
            installed={
                "a": _distribution(
                    "a",
                    requirements=('b[foo]==1; extra != "bar"',),
                    extras=("bar",),
                ),
                "b": _distribution(
                    "b",
                    requirements=('d==1; extra == "foo"',),
                    extras=("foo",),
                ),
                "d": _distribution("d"),
                "y": _distribution("y", requirements=("b==1",)),
                "z": _distribution("z", requirements=("a[bar]==1",)),
            },
        )

        failures: list[tuple[str, str]] = []
        for roots in (("a", "y", "z"), ("z", "a", "y")):
            with self.subTest(roots=roots), self.assertRaises(
                snapshotter.SnapshotError
            ) as raised:
                snapshotter.build_dependency_graph(_authored_policy(roots), inspect)
            failures.append((raised.exception.code, str(raised.exception)))

        self.assertEqual(failures[0], failures[1])
        self.assertEqual(failures[0][0], "negative-extra-marker-unsupported")
        self.assertIn('extra != "bar"', failures[0][1])

    def test_positive_extra_closure_is_order_independent_across_a_cycle(self) -> None:
        inspect = snapshotter.InspectReport(
            pip_version="1",
            environment=ENVIRONMENT,
            installed={
                "a": _distribution(
                    "a",
                    requirements=("b==1", 'c==1; extra == "feature"'),
                    extras=("feature",),
                ),
                "b": _distribution("b", requirements=("a[feature]==1",)),
                "c": _distribution("c"),
                "z": _distribution("z", requirements=("c==1",)),
            },
        )

        first = snapshotter.build_dependency_graph(_authored_policy(("a", "z")), inspect)
        reversed_roots = snapshotter.build_dependency_graph(
            _authored_policy(("z", "a")),
            inspect,
        )

        self.assertEqual(first, reversed_roots)
        self.assertEqual(first.edges["a"], frozenset({"b", "c"}))
        self.assertEqual(first.edges["b"], frozenset({"a"}))
        self.assertEqual(first.edges["z"], frozenset({"c"}))

    def test_self_referential_extras_expand_without_a_self_dependency_edge(self) -> None:
        authored = snapshotter.AuthoredPolicy(
            files=(),
            roots={
                "a": snapshotter.AuthoredRoot(
                    name="a",
                    version="1",
                    extras=frozenset({"all"}),
                    scope="runtime",
                    sources=("requirements.txt",),
                )
            },
            fingerprint="fixture",
        )
        inspect = snapshotter.InspectReport(
            pip_version="1",
            environment=ENVIRONMENT,
            installed={
                "a": _distribution(
                    "a",
                    requirements=(
                        'a[feature]==1; extra == "all"',
                        'b==1; extra == "feature"',
                    ),
                    extras=("all", "feature"),
                ),
                "b": _distribution("b"),
            },
        )

        graph = snapshotter.build_dependency_graph(authored, inspect)

        self.assertEqual(graph.edges["a"], frozenset({"b"}))
        self.assertEqual(graph.scopes, {"a": "runtime", "b": "runtime"})

    def test_negative_extra_policy_handles_reversed_and_quoted_comparisons(self) -> None:
        reversed_negative = snapshotter.InspectReport(
            pip_version="1",
            environment=ENVIRONMENT,
            installed={
                "a": _distribution("a", requirements=('b==1; "foo" != extra',)),
                "b": _distribution("b"),
            },
        )
        with self.assertRaises(snapshotter.SnapshotError) as raised:
            snapshotter.build_dependency_graph(
                _authored_policy(("a",)),
                reversed_negative,
            )
        self.assertEqual(raised.exception.code, "negative-extra-marker-unsupported")

        quoted_text_environment = {
            **ENVIRONMENT,
            "platform_version": "contains extra != marker",
        }
        quoted_text = snapshotter.InspectReport(
            pip_version="1",
            environment=quoted_text_environment,
            installed={
                "a": _distribution(
                    "a",
                    requirements=(
                        'b==1; platform_version == "contains extra != marker"',
                    ),
                ),
                "b": _distribution("b"),
            },
        )
        graph = snapshotter.build_dependency_graph(
            _authored_policy(("a",)),
            quoted_text,
        )
        self.assertEqual(graph.edges["a"], frozenset({"b"}))

    def test_cli_writes_one_deterministic_new_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            fixture = SnapshotFixture(root)
            output = root / "dependency-submission.json"
            arguments = [
                "--constraint",
                str(fixture.constraint_path),
                "--verification-receipt",
                str(fixture.receipt_path),
                "--platform",
                "linux-x64",
                "--repository",
                "Infiland/GM2Godot",
                "--sha",
                SHA,
                "--ref",
                "refs/heads/main",
                "--run-id",
                "12345",
                "--run-attempt",
                "2",
                "--scanned",
                SCANNED,
                "--output",
                str(output),
            ]
            stdout = StringIO()
            with (
                _working_directory(root),
                mock.patch.object(snapshotter, "run_pip_inspect", return_value=fixture.inspect_value),
                redirect_stdout(stdout),
            ):
                status = snapshotter.main(arguments)

            self.assertEqual(status, 0)
            self.assertIn("snapshot written", stdout.getvalue())
            first_bytes = output.read_bytes()
            self.assertTrue(first_bytes.endswith(b"\n"))
            first_value = json.loads(first_bytes)
            self.assertEqual(first_value["scanned"], SCANNED)

            stderr = StringIO()
            with (
                _working_directory(root),
                mock.patch.object(snapshotter, "run_pip_inspect", return_value=fixture.inspect_value),
                redirect_stderr(stderr),
            ):
                second_status = snapshotter.main(arguments)
            self.assertEqual(second_status, 1)
            self.assertIn("output-exists", stderr.getvalue())
            self.assertEqual(output.read_bytes(), first_bytes)

    def test_receipt_lock_installed_source_and_tuple_bindings_fail_closed(self) -> None:
        mutations: dict[str, Callable[[dict[str, object]], object]] = {
            "status": lambda value: value.__setitem__("status", "failed"),
            "schema": lambda value: value.__setitem__("schema_version", 1),
            "constraint-sha": lambda value: cast(dict[str, object], value["constraint"]).__setitem__(
                "sha256", "0" * 64
            ),
            "constraint-pins": lambda value: cast(
                list[dict[str, str]], cast(dict[str, object], value["constraint"])["pins"]
            )[0].__setitem__("version", "999"),
            "installed": lambda value: cast(
                list[dict[str, str]], cast(dict[str, object], value["observation"])["installed"]
            )[0].__setitem__("version", "999"),
            "environment": lambda value: cast(
                dict[str, str], cast(dict[str, object], value["expected_environment"])
            ).__setitem__("platform_machine", "arm64"),
            "bootstrap-sha": lambda value: cast(
                dict[str, object], cast(dict[str, object], value["bootstrap"])["source"]
            ).__setitem__("sha256", "0" * 64),
            "transition": lambda value: cast(
                dict[str, object], cast(dict[str, object], value["bootstrap"])["source_transition"]
            ).__setitem__("active", True),
            "pip-command": lambda value: cast(
                dict[str, object], cast(dict[str, object], value["observation"])["pip_check"]
            ).__setitem__("returncode", 1),
            "pip-command-bool": lambda value: cast(
                dict[str, object], cast(dict[str, object], value["observation"])["pip_check"]
            ).__setitem__("returncode", False),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw_directory:
                fixture = SnapshotFixture(Path(raw_directory))
                receipt = fixture.receipt()
                mutate(receipt)
                fixture.write_receipt(receipt)
                with self.assertRaises(snapshotter.SnapshotError):
                    fixture.verify()

    def test_exact_set_rejects_missing_extra_and_unreachable_lock_pin(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            fixture = SnapshotFixture(Path(raw_directory))
            missing_extra_value = copy.deepcopy(fixture.inspect_value)
            app_metadata = cast(
                dict[str, object], cast(list[dict[str, object]], missing_extra_value["installed"])[0]["metadata"]
            )
            app_metadata["provides_extra"] = ["other"]
            missing_extra = snapshotter.parse_inspect_report(missing_extra_value)
            with self.assertRaisesRegex(snapshotter.SnapshotError, "does not provide requested extras"):
                snapshotter.build_dependency_graph(fixture.authored, missing_extra)

            orphan_value = copy.deepcopy(fixture.inspect_value)
            cast(list[dict[str, object]], orphan_value["installed"]).append(
                _installed_item("orphan", "1.0")
            )
            orphan_inspect = snapshotter.parse_inspect_report(orphan_value)
            orphan_pins = dict(fixture.constraint.pins)
            orphan_pins["orphan"] = "1.0"
            orphan_constraint = snapshotter.ConstraintPolicy(
                file=fixture.constraint.file,
                pins=orphan_pins,
            )
            snapshotter.verify_exact_sets(orphan_constraint, fixture.authored, orphan_inspect)
            with self.assertRaisesRegex(snapshotter.SnapshotError, "unreachable"):
                snapshotter.build_dependency_graph(fixture.authored, orphan_inspect)

    def test_active_dependency_must_exist_and_satisfy_declared_version(self) -> None:
        scenarios = (
            ("missing", ["Missing>=1"], "absent"),
            ("version", ["Core>=99"], "does not satisfy"),
        )
        for label, requirements, message in scenarios:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw_directory:
                fixture = SnapshotFixture(Path(raw_directory))
                inspect_value = copy.deepcopy(fixture.inspect_value)
                app_metadata = cast(
                    dict[str, object], cast(list[dict[str, object]], inspect_value["installed"])[0]["metadata"]
                )
                app_metadata["requires_dist"] = requirements
                inspect = snapshotter.parse_inspect_report(inspect_value)
                with self.assertRaisesRegex(snapshotter.SnapshotError, message):
                    snapshotter.build_dependency_graph(fixture.authored, inspect)

    def test_authored_sources_reject_non_exact_urls_duplicates_and_symlinks(self) -> None:
        invalid_lines = (
            "thing>=1\n",
            "thing @ https://example.invalid/thing.whl\n",
            "-r nested.txt\n",
            "thing==1  # ambiguous\n",
            "thing==1; extra == 'feature'\n",
            "thing==1 \\\n  --hash=sha256:00\n",
        )
        for content in invalid_lines:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as raw_directory:
                path = Path(raw_directory) / "requirements.txt"
                path.write_text(content, encoding="utf-8")
                source = snapshotter.read_regular_file(
                    path,
                    snapshotter.MAX_REQUIREMENTS_BYTES,
                    label="authored requirements",
                )
                with self.assertRaises(snapshotter.SnapshotError):
                    snapshotter.parse_source_requirements(source)

        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            target = root / "target.txt"
            target.write_text("thing==1\n", encoding="utf-8")
            link = root / "requirements.txt"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("This platform cannot create file symlinks.")
            with self.assertRaisesRegex(snapshotter.SnapshotError, "non-symlink"):
                snapshotter.read_regular_file(
                    link,
                    snapshotter.MAX_REQUIREMENTS_BYTES,
                    label="authored requirements",
                )

    def test_authored_fingerprint_normalizes_only_ascii_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            source = root / "requirements.txt"
            source_policy: tuple[tuple[Path, snapshotter.Scope], ...] = ((source, "runtime"),)

            fingerprints: list[str] = []
            raw_hashes: list[str] = []
            for content in (
                b"# roots\nthing==1\n",
                b"# roots\r\nthing==1\r\n",
                b"# roots\rthing==1\r",
            ):
                source.write_bytes(content)
                policy = snapshotter.load_authored_policy(ENVIRONMENT, source_policy)
                fingerprints.append(policy.fingerprint)
                raw_hashes.append(policy.files[0].sha256)

            self.assertEqual(len(set(fingerprints)), 1)
            self.assertEqual(len(set(raw_hashes)), 3)

            source.write_bytes(b"# substantively changed roots\nthing==1\n")
            changed_content = snapshotter.load_authored_policy(ENVIRONMENT, source_policy)
            self.assertNotEqual(changed_content.fingerprint, fingerprints[0])

            renamed_source = root / "renamed-requirements.txt"
            renamed_source.write_bytes(b"# roots\nthing==1\n")
            changed_path = snapshotter.load_authored_policy(
                ENVIRONMENT,
                ((renamed_source, "runtime"),),
            )
            self.assertNotEqual(changed_path.fingerprint, fingerprints[0])

    def test_authored_source_duplicates_are_merged_after_marker_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            source = root / "requirements.txt"
            source.write_text(
                'thing[linux-extra]==1; sys_platform == "linux"\n'
                'thing[windows-extra]==2; sys_platform == "win32"\n',
                encoding="utf-8",
            )
            source_policies: tuple[tuple[Path, snapshotter.Scope], ...] = (
                (source, "runtime"),
            )

            linux_policy = snapshotter.load_authored_policy(
                ENVIRONMENT,
                source_policies,
            )
            windows_policy = snapshotter.load_authored_policy(
                {**ENVIRONMENT, "sys_platform": "win32"},
                source_policies,
            )

            self.assertEqual(linux_policy.roots["thing"].version, "1")
            self.assertEqual(
                linux_policy.roots["thing"].extras,
                frozenset({"linux-extra"}),
            )
            self.assertEqual(windows_policy.roots["thing"].version, "2")
            self.assertEqual(
                windows_policy.roots["thing"].extras,
                frozenset({"windows-extra"}),
            )

            source.write_text(
                'thing[first]==1; python_version >= "3.12"\n'
                'thing[second]==1; sys_platform == "linux"\n',
                encoding="utf-8",
            )
            merged = snapshotter.load_authored_policy(ENVIRONMENT, source_policies)
            self.assertEqual(
                merged.roots["thing"].extras,
                frozenset({"first", "second"}),
            )
            self.assertEqual(merged.roots["thing"].sources, (source.as_posix(),))

            source.write_text(
                'thing==1\nthing==2; sys_platform == "linux"\n',
                encoding="utf-8",
            )
            with self.assertRaises(snapshotter.SnapshotError) as raised:
                snapshotter.load_authored_policy(ENVIRONMENT, source_policies)
            self.assertEqual(raised.exception.code, "source-pin-conflict")

            bootstrap = root / "requirements-bootstrap.txt"
            bootstrap.write_text(
                "pip==1\npip==1\npip-tools==1\n",
                encoding="utf-8",
            )
            with self.assertRaises(snapshotter.SnapshotError) as raised:
                snapshotter.load_authored_policy(
                    ENVIRONMENT,
                    ((bootstrap, "development"),),
                )
            self.assertEqual(raised.exception.code, "bootstrap-source-invalid")

    def test_constraint_and_json_parsers_reject_ambiguous_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            for label, content in (
                ("duplicate", "pip==1\npip==1\n"),
                ("range", "pip>=1\n"),
                ("continuation", "pip==1 \\\n+  --hash=x\n"),
                ("invalid-version", "pip==not@version\n"),
            ):
                with self.subTest(label=label):
                    path = root / f"{label}.lock"
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(snapshotter.SnapshotError):
                        snapshotter.load_constraint(path)
            with self.assertRaises(snapshotter.SnapshotError):
                snapshotter.parse_json_bytes(b'{"version": 1, "version": 1}', label="test JSON")
            with self.assertRaises(snapshotter.SnapshotError):
                snapshotter.parse_json_bytes(b'{"value": NaN}', label="test JSON")

    def test_constraint_source_inspect_and_purl_require_canonical_versions(self) -> None:
        noncanonical_versions = ("1.0RC1", "01.0", "1.0-1", "1.0+LOCAL.Build")
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            constraint = root / "candidate.lock"
            source = root / "requirements.txt"
            for version in noncanonical_versions:
                with self.subTest(boundary="constraint", version=version):
                    constraint.write_text(f"thing=={version}\n", encoding="utf-8")
                    with self.assertRaises(snapshotter.SnapshotError) as raised:
                        snapshotter.load_constraint(constraint)
                    self.assertEqual(
                        raised.exception.code,
                        "constraint-noncanonical-version",
                    )

                with self.subTest(boundary="source", version=version):
                    source.write_text(f"thing=={version}\n", encoding="utf-8")
                    source_file = snapshotter.read_regular_file(
                        source,
                        snapshotter.MAX_REQUIREMENTS_BYTES,
                        label="authored requirements",
                    )
                    with self.assertRaises(snapshotter.SnapshotError) as raised:
                        snapshotter.parse_source_requirements(source_file)
                    self.assertEqual(
                        raised.exception.code,
                        "source-noncanonical-version",
                    )

                with self.subTest(boundary="pip inspect", version=version):
                    report = _inspect_value()
                    metadata = cast(
                        dict[str, object],
                        cast(list[dict[str, object]], report["installed"])[0]["metadata"],
                    )
                    metadata["version"] = version
                    with self.assertRaises(snapshotter.SnapshotError) as raised:
                        snapshotter.parse_inspect_report(report)
                    self.assertEqual(
                        raised.exception.code,
                        "inspect-noncanonical-version",
                    )

                with self.subTest(boundary="PURL", version=version):
                    with self.assertRaises(snapshotter.SnapshotError) as raised:
                        snapshotter.package_url("thing", version)
                    self.assertEqual(
                        raised.exception.code,
                        "purl-noncanonical-version",
                    )

    def test_inspect_schema_rejects_duplicates_direct_urls_and_malformed_metadata(self) -> None:
        mutations: dict[str, Callable[[dict[str, object]], object]] = {
            "schema": lambda value: value.__setitem__("version", "2"),
            "missing-environment": lambda value: cast(dict[str, str], value["environment"]).pop(
                "python_version"
            ),
            "duplicate": lambda value: cast(list[dict[str, object]], value["installed"]).append(
                _installed_item("APP", PINS["app"])
            ),
            "direct-url": lambda value: cast(list[dict[str, object]], value["installed"])[0].__setitem__(
                "direct_url", {"url": "https://example.invalid"}
            ),
            "bad-requirement": lambda value: cast(
                dict[str, object], cast(list[dict[str, object]], value["installed"])[0]["metadata"]
            ).__setitem__("requires_dist", ["not a requirement ???"]),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                value = _inspect_value()
                mutate(value)
                with self.assertRaises(snapshotter.SnapshotError):
                    snapshotter.parse_inspect_report(value)

    def test_anchored_output_exact_loader_supports_isolated_script_execution(
        self,
    ) -> None:
        loader = cast(
            Callable[[], object],
            getattr(snapshotter, "_load_anchored_output_module"),
        )
        before_path = tuple(sys.path)
        self.assertIs(loader(), ANCHORED_OUTPUT)
        self.assertEqual(tuple(sys.path), before_path)
        anchored_output_path = ANCHORED_OUTPUT.__file__
        self.assertIsNotNone(anchored_output_path)
        assert anchored_output_path is not None
        self.assertEqual(
            Path(anchored_output_path).resolve(strict=True),
            Path(snapshotter.__file__)
            .resolve(strict=True)
            .with_name("_anchored_output.py"),
        )

        with tempfile.TemporaryDirectory() as raw_directory:
            shadow = Path(raw_directory) / "_anchored_output.py"
            shadow.write_text(
                'raise RuntimeError("loaded shadow anchored output")\n',
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["PYTHONPATH"] = raw_directory
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    os.fspath(Path(snapshotter.__file__).resolve(strict=True)),
                    "--help",
                ],
                cwd=raw_directory,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("loaded shadow anchored output", completed.stderr)

    def test_snapshot_json_adapter_preserves_publication_error_and_cleanup_note(
        self,
    ) -> None:
        real_close = OUTPUT_PARENT_BINDING_TYPE.close

        def close_then_report_failure(binding: Any) -> tuple[BaseException, ...]:
            self.assertEqual(real_close(binding), ())
            return (OSError("injected adapter close failure"),)

        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            output = root / "snapshot.json"
            output.write_bytes(b"existing\n")
            with (
                _working_directory(root),
                mock.patch.object(
                    OUTPUT_PARENT_BINDING_TYPE,
                    "close",
                    close_then_report_failure,
                ),
                self.assertRaises(snapshotter.SnapshotError) as raised,
            ):
                snapshotter.atomic_write_new_json(output, {"version": 0})

            self.assertEqual(raised.exception.code, "output-exists")
            self.assertIn(
                "injected adapter close failure",
                "\n".join(getattr(raised.exception, "__notes__", ())),
            )
            self.assertEqual(output.read_bytes(), b"existing\n")

    def test_atomic_output_never_overwrites_and_rejects_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            output = root / "snapshot.json"
            with _working_directory(root):
                _publish_new_json(output, {"version": 0})
                original = output.read_bytes()
                with self.assertRaisesRegex(ANCHORED_OUTPUT_ERROR, "overwrite"):
                    _publish_new_json(output, {"version": 1})
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(list(root.glob(".snapshot.json.*.tmp")), [])

            real_parent = root / "real"
            real_parent.mkdir()
            linked_parent = root / "linked"
            try:
                linked_parent.symlink_to(real_parent, target_is_directory=True)
            except OSError:
                self.skipTest("This platform cannot create directory symlinks.")
            with self.assertRaisesRegex(snapshotter.SnapshotError, "not a regular directory"):
                snapshotter.validate_output_path(linked_parent / "out.json", ())

    def test_atomic_output_rejects_dangling_final_symlink_without_writing_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            output = root / "snapshot.json"
            redirected = root / "redirected.json"
            try:
                output.symlink_to(redirected.name)
            except OSError:
                self.skipTest("This platform cannot create file symlinks.")

            with (
                _working_directory(root),
                self.assertRaisesRegex(ANCHORED_OUTPUT_ERROR, "overwrite"),
            ):
                _publish_new_json(output, {"version": 0})

            self.assertTrue(output.is_symlink())
            self.assertFalse(redirected.exists())
            self.assertEqual(list(root.glob(".snapshot.json.*.tmp")), [])

    def test_atomic_output_rejects_in_checkout_redirected_ancestor_before_binding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            safe = root / "safe"
            original_safe = root / "safe-original"
            redirected_safe = root / "redirected-safe"
            (safe / "out").mkdir(parents=True)
            (redirected_safe / "out").mkdir(parents=True)
            output = safe / "out" / "snapshot.json"

            with _working_directory(root):
                snapshotter.validate_output_path(output, ())
                safe.rename(original_safe)
                try:
                    safe.symlink_to(redirected_safe, target_is_directory=True)
                except OSError:
                    self.skipTest("This platform cannot create directory symlinks.")

                with self.assertRaisesRegex(
                    ANCHORED_OUTPUT_ERROR,
                    "Cannot bind snapshot output parent",
                ):
                    _publish_new_json(output, {"version": 0})

            self.assertFalse((redirected_safe / "out" / output.name).exists())
            self.assertFalse((original_safe / "out" / output.name).exists())
            self.assertEqual(
                list((redirected_safe / "out").glob(f".{output.name}.*.tmp")),
                [],
            )
            self.assertEqual(
                list((original_safe / "out").glob(f".{output.name}.*.tmp")),
                [],
            )

    @unittest.skipUnless(
        ANCHORED_OUTPUT.descriptor_relative_output_supported(),
        "Descriptor-relative output binding is unavailable on this platform.",
    )
    def test_atomic_output_recovers_when_initial_fstat_fails_once(
        self,
    ) -> None:
        real_fstat = os.fstat
        real_open_new = OUTPUT_PARENT_BINDING_TYPE.open_new
        created_descriptor = -1
        injected = False

        def recording_open_new(
            binding: Any,
            name: str,
        ) -> int:
            nonlocal created_descriptor
            created_descriptor = real_open_new(binding, name)
            return created_descriptor

        def fail_created_descriptor_once(descriptor: int) -> os.stat_result:
            nonlocal injected
            if descriptor == created_descriptor and not injected:
                injected = True
                raise OSError("injected post-open fstat failure")
            return real_fstat(descriptor)

        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            output = root / "snapshot.json"
            with (
                _working_directory(root),
                mock.patch.object(
                    OUTPUT_PARENT_BINDING_TYPE,
                    "open_new",
                    recording_open_new,
                ),
                mock.patch.object(
                    ANCHORED_OUTPUT.os,
                    "fstat",
                    side_effect=fail_created_descriptor_once,
                ),
                self.assertRaisesRegex(OSError, "injected post-open fstat failure"),
            ):
                _publish_new_json(output, {"version": 0})

            self.assertTrue(injected)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".snapshot.json.*.tmp")), [])
            with self.assertRaises(OSError):
                real_fstat(created_descriptor)

    @unittest.skipUnless(
        ANCHORED_OUTPUT.descriptor_relative_output_supported(),
        "Descriptor-relative output binding is unavailable on this platform.",
    )
    def test_atomic_output_persistent_initial_fstat_failure_is_bounded(
        self,
    ) -> None:
        real_fstat = os.fstat
        real_open_new = OUTPUT_PARENT_BINDING_TYPE.open_new
        created_descriptor = -1

        def recording_open_new(binding: Any, name: str) -> int:
            nonlocal created_descriptor
            created_descriptor = real_open_new(binding, name)
            return created_descriptor

        def fail_created_descriptor(descriptor: int) -> os.stat_result:
            if descriptor == created_descriptor:
                raise OSError("persistent post-open fstat failure")
            return real_fstat(descriptor)

        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            output = root / "snapshot.json"
            with (
                _working_directory(root),
                mock.patch.object(
                    OUTPUT_PARENT_BINDING_TYPE,
                    "open_new",
                    recording_open_new,
                ),
                mock.patch.object(
                    ANCHORED_OUTPUT.os,
                    "fstat",
                    side_effect=fail_created_descriptor,
                ),
                self.assertRaisesRegex(OSError, "persistent post-open fstat failure") as raised,
            ):
                _publish_new_json(output, {"version": 0})

            self.assertFalse(output.exists())
            temporary_files = list(root.glob(".snapshot.json.*.tmp"))
            self.assertEqual(len(temporary_files), 1)
            self.assertEqual(temporary_files[0].stat().st_size, 0)
            self.assertIn(
                "intentionally left in place",
                "\n".join(getattr(raised.exception, "__notes__", ())),
            )
            with self.assertRaises(OSError):
                real_fstat(created_descriptor)

    @unittest.skipUnless(
        ANCHORED_OUTPUT.descriptor_relative_output_supported(),
        "Descriptor-relative output binding is unavailable on this platform.",
    )
    def test_atomic_output_propagates_directory_sync_failure_and_cleans_up(
        self,
    ) -> None:
        real_fsync = os.fsync

        def reject_directory_sync(descriptor: int) -> None:
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError(errno.EIO, "injected directory sync failure")
            real_fsync(descriptor)

        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            output = root / "snapshot.json"
            with (
                _working_directory(root),
                mock.patch.object(
                    ANCHORED_OUTPUT.os,
                    "fsync",
                    side_effect=reject_directory_sync,
                ),
                self.assertRaises(OSError) as raised,
            ):
                _publish_new_json(output, {"version": 0})

            self.assertEqual(raised.exception.errno, errno.EIO)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".snapshot.json.*.tmp")), [])

    def test_output_binding_close_attempts_every_resource(self) -> None:
        closed_descriptors: list[int] = []

        def close_descriptor(descriptor: int) -> None:
            closed_descriptors.append(descriptor)
            if descriptor != 2:
                raise OSError(f"cannot close descriptor {descriptor}")

        posix_binding = OUTPUT_PARENT_BINDING_TYPE(
            checkout=Path("checkout"),
            parent=Path("parent"),
            leaf="snapshot.json",
            strategy="posix-dir-fd",
            descriptors=(1, 2, 3),
        )
        with mock.patch.object(ANCHORED_OUTPUT.os, "close", side_effect=close_descriptor):
            posix_failures = posix_binding.close()
        self.assertEqual(closed_descriptors, [3, 2, 1])
        self.assertEqual(len(posix_failures), 2)

        class FakeWindowsApi:
            def __init__(self) -> None:
                self.closed: list[int] = []

            def CloseHandle(self, handle: int) -> int:
                self.closed.append(handle)
                return int(handle == 20)

        windows_api = FakeWindowsApi()
        windows_binding = OUTPUT_PARENT_BINDING_TYPE(
            checkout=Path("checkout"),
            parent=Path("parent"),
            leaf="snapshot.json",
            strategy="windows-handle",
            windows_api=windows_api,
            windows_entries=(
                (Path("one"), (1, 1), 10),
                (Path("two"), (2, 2), 20),
                (Path("three"), (3, 3), 30),
            ),
        )
        windows_failures = windows_binding.close()
        self.assertEqual(windows_api.closed, [30, 20, 10])
        self.assertEqual(len(windows_failures), 2)

    def test_output_binding_close_collects_control_flow_and_keeps_closing(self) -> None:
        for strategy in ("posix-dir-fd", "windows-handle"):
            for failure_type in (KeyboardInterrupt, SystemExit):
                with self.subTest(strategy=strategy, failure=failure_type.__name__):
                    failure = failure_type("injected close control flow")
                    attempted: list[int] = []
                    if strategy == "posix-dir-fd":
                        binding = OUTPUT_PARENT_BINDING_TYPE(
                            checkout=Path("checkout"),
                            parent=Path("parent"),
                            leaf="snapshot.json",
                            strategy=strategy,
                            descriptors=(1, 2),
                        )

                        def close_descriptor(descriptor: int) -> None:
                            attempted.append(descriptor)
                            if descriptor == 2:
                                raise failure

                        context = mock.patch.object(
                            ANCHORED_OUTPUT.os,
                            "close",
                            side_effect=close_descriptor,
                        )
                    else:
                        class FakeWindowsApi:
                            def CloseHandle(self, handle: int) -> int:
                                attempted.append(handle)
                                if handle == 2:
                                    raise failure
                                return 1

                        binding = OUTPUT_PARENT_BINDING_TYPE(
                            checkout=Path("checkout"),
                            parent=Path("parent"),
                            leaf="snapshot.json",
                            strategy=strategy,
                            windows_api=FakeWindowsApi(),
                            windows_entries=(
                                (Path("one"), (1, 1), 1),
                                (Path("two"), (2, 2), 2),
                            ),
                        )
                        context = nullcontext()

                    with context:
                        failures = binding.close()

                    self.assertEqual(attempted, [2, 1])
                    self.assertEqual(failures, (failure,))

    def test_anchor_close_failure_preserves_primary_or_reports_published_output(
        self,
    ) -> None:
        real_close = OUTPUT_PARENT_BINDING_TYPE.close

        def close_then_report_failure(
            binding: Any,
        ) -> tuple[BaseException, ...]:
            self.assertEqual(real_close(binding), ())
            return (OSError("injected anchor close failure"),)

        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            output = root / "snapshot.json"
            output.write_text("existing\n", encoding="utf-8")
            with (
                _working_directory(root),
                mock.patch.object(
                    OUTPUT_PARENT_BINDING_TYPE,
                    "close",
                    close_then_report_failure,
                ),
                self.assertRaises(ANCHORED_OUTPUT_ERROR) as raised,
            ):
                _publish_new_json(output, {"version": 0})
            self.assertEqual(raised.exception.code, "output-exists")
            self.assertIn(
                "injected anchor close failure",
                "\n".join(getattr(raised.exception, "__notes__", ())),
            )

        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            output = root / "snapshot.json"
            with (
                _working_directory(root),
                mock.patch.object(
                    OUTPUT_PARENT_BINDING_TYPE,
                    "close",
                    close_then_report_failure,
                ),
                self.assertRaises(ANCHORED_OUTPUT_ERROR) as raised,
            ):
                _publish_new_json(output, {"version": 0})
            self.assertEqual(raised.exception.code, "output-anchor-close-failed")
            self.assertEqual(json.loads(output.read_bytes()), {"version": 0})

    def test_anchor_close_control_flow_respects_active_primary_cross_product(
        self,
    ) -> None:
        real_close = OUTPUT_PARENT_BINDING_TYPE.close
        primary_types = (OSError, KeyboardInterrupt, SystemExit)
        cleanup_types = (OSError, KeyboardInterrupt, SystemExit)

        for primary_type in primary_types:
            for cleanup_type in cleanup_types:
                with (
                    self.subTest(
                        primary=primary_type.__name__,
                        cleanup=cleanup_type.__name__,
                    ),
                    tempfile.TemporaryDirectory() as raw_directory,
                ):
                    root = Path(raw_directory)
                    output = root / "snapshot.json"
                    primary = primary_type("injected primary")
                    cleanup = cleanup_type("injected cleanup")

                    def close_then_report_failure(
                        binding: Any,
                    ) -> tuple[BaseException, ...]:
                        self.assertEqual(real_close(binding), ())
                        return (cleanup,)

                    with (
                        _working_directory(root),
                        mock.patch.object(
                            OUTPUT_PARENT_BINDING_TYPE,
                            "open_new",
                            side_effect=primary,
                        ),
                        mock.patch.object(
                            OUTPUT_PARENT_BINDING_TYPE,
                            "close",
                            close_then_report_failure,
                        ),
                        self.assertRaises(primary_type) as raised,
                    ):
                        ANCHORED_OUTPUT.publish_new_bytes(output, b"payload\n")

                    self.assertIs(raised.exception, primary)
                    self.assertIn(
                        "injected cleanup",
                        "\n".join(getattr(raised.exception, "__notes__", ())),
                    )
                    self.assertFalse(output.exists())

    def test_anchor_close_control_flow_without_primary_is_propagated(self) -> None:
        real_close = OUTPUT_PARENT_BINDING_TYPE.close
        for cleanup_type in (KeyboardInterrupt, SystemExit):
            with (
                self.subTest(cleanup=cleanup_type.__name__),
                tempfile.TemporaryDirectory() as raw_directory,
            ):
                root = Path(raw_directory)
                output = root / "snapshot.json"
                cleanup = cleanup_type("injected cleanup")

                def close_then_report_failure(
                    binding: Any,
                ) -> tuple[BaseException, ...]:
                    self.assertEqual(real_close(binding), ())
                    return (cleanup,)

                with (
                    _working_directory(root),
                    mock.patch.object(
                        OUTPUT_PARENT_BINDING_TYPE,
                        "close",
                        close_then_report_failure,
                    ),
                    self.assertRaises(cleanup_type) as raised,
                ):
                    ANCHORED_OUTPUT.publish_new_bytes(output, b"payload\n")

                self.assertIs(raised.exception, cleanup)
                self.assertEqual(output.read_bytes(), b"payload\n")

    @unittest.skipUnless(
        ANCHORED_OUTPUT.descriptor_relative_output_supported(),
        "Descriptor-relative output binding is unavailable on this platform.",
    )
    def test_cli_rejects_output_ancestor_replaced_during_snapshot_build(self) -> None:
        with (
            tempfile.TemporaryDirectory() as raw_checkout,
            tempfile.TemporaryDirectory() as raw_external,
        ):
            checkout = Path(raw_checkout)
            external = Path(raw_external)
            fixture = SnapshotFixture(checkout)
            safe = checkout / "safe"
            original_safe = checkout / "safe-original"
            output_parent = safe / "out"
            output_parent.mkdir(parents=True)
            external_safe = external / "safe"
            (external_safe / "out").mkdir(parents=True)
            output = output_parent / "snapshot.json"

            real_open_output_parent = OPEN_OUTPUT_PARENT

            def bind_then_replace_output_ancestor(
                path: Path,
            ) -> Any:
                binding = real_open_output_parent(path)
                safe.rename(original_safe)
                safe.symlink_to(external_safe, target_is_directory=True)
                return binding

            stderr = StringIO()
            with (
                _working_directory(checkout),
                mock.patch.object(
                    snapshotter,
                    "run_pip_inspect",
                    return_value=fixture.inspect_value,
                ),
                mock.patch.object(
                    ANCHORED_OUTPUT,
                    "open_output_parent",
                    side_effect=bind_then_replace_output_ancestor,
                ),
                redirect_stderr(stderr),
            ):
                status = snapshotter.main(
                    [
                        "--constraint",
                        str(fixture.constraint_path),
                        "--verification-receipt",
                        str(fixture.receipt_path),
                        "--platform",
                        "linux-x64",
                        "--repository",
                        "Infiland/GM2Godot",
                        "--sha",
                        SHA,
                        "--ref",
                        "refs/heads/main",
                        "--run-id",
                        "1",
                        "--run-attempt",
                        "1",
                        "--scanned",
                        SCANNED,
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(status, 1)
            self.assertIn("output-parent-changed", stderr.getvalue())
            self.assertFalse((external_safe / "out" / output.name).exists())
            self.assertFalse((original_safe / "out" / output.name).exists())
            self.assertEqual(
                list((original_safe / "out").glob(f".{output.name}.*.tmp")),
                [],
            )

    def test_windows_binding_control_flow_detects_replaced_ancestor(self) -> None:
        class FakeWindowsApi:
            def __init__(self) -> None:
                self.closed: list[int] = []

            def CloseHandle(self, handle: int) -> int:
                self.closed.append(handle)
                return 1

        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            parent = root / "parent"
            original_parent = root / "parent-original"
            parent.mkdir()
            parent_stat = parent.lstat()
            identity = (parent_stat.st_dev, parent_stat.st_ino)
            windows_api = FakeWindowsApi()
            binding = OUTPUT_PARENT_BINDING_TYPE(
                checkout=root,
                parent=parent,
                leaf="snapshot.json",
                strategy="windows-handle",
                windows_api=windows_api,
                windows_entries=((parent, identity, 10),),
            )
            with (
                mock.patch.object(
                    ANCHORED_OUTPUT,
                    "_windows_directory_attributes",
                    return_value=WINDOWS_FILE_ATTRIBUTE_DIRECTORY,
                ),
                mock.patch.object(
                    ANCHORED_OUTPUT,
                    "_windows_handle_identity",
                    return_value=identity,
                ),
            ):
                binding.verify()
                parent.rename(original_parent)
                parent.mkdir()
                with self.assertRaisesRegex(
                    ANCHORED_OUTPUT_ERROR,
                    "ancestor changed",
                ):
                    binding.verify()
            self.assertEqual(binding.close(), ())
            self.assertEqual(windows_api.closed, [10])

    def test_rejected_windows_handle_close_failure_preserves_primary_error(
        self,
    ) -> None:
        class FakeWindowsApi:
            def __init__(self, close_failure: BaseException | None) -> None:
                self.close_failure = close_failure
                self.closed: list[int] = []

            def CreateFileW(self, *_arguments: object) -> int:
                return 10

            def GetFileType(self, _handle: int) -> int:
                return WINDOWS_FILE_TYPE_DISK

            def CloseHandle(self, handle: int) -> int:
                self.closed.append(handle)
                if self.close_failure is not None:
                    raise self.close_failure
                return 0

        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            directory_stat = directory.lstat()
            identity = (directory_stat.st_dev, directory_stat.st_ino)
            for close_failure in (None, OSError("injected CloseHandle failure")):
                with self.subTest(close_failure=close_failure):
                    windows_api = FakeWindowsApi(close_failure)
                    with (
                        mock.patch.object(
                            ANCHORED_OUTPUT,
                            "_windows_directory_attributes",
                            return_value=0,
                        ),
                        mock.patch.object(
                            ANCHORED_OUTPUT,
                            "_windows_handle_identity",
                            return_value=identity,
                        ),
                        self.assertRaisesRegex(
                            OSError,
                            "Snapshot output directory changed",
                        ) as raised,
                    ):
                        OPEN_WINDOWS_DIRECTORY_HANDLE(
                            windows_api,
                            directory,
                            identity,
                        )

                    self.assertEqual(windows_api.closed, [10])
                    notes = "\n".join(getattr(raised.exception, "__notes__", ()))
                    self.assertIn("Could not close the rejected", notes)
                    if close_failure is not None:
                        self.assertIn("injected CloseHandle failure", notes)

    @unittest.skipUnless(
        ANCHORED_OUTPUT.descriptor_relative_output_supported(),
        "Descriptor-relative output binding is unavailable on this platform.",
    )
    def test_output_parent_binding_preserves_control_flow_exceptions(self) -> None:
        real_close = os.close
        for exception in (KeyboardInterrupt("stop"), SystemExit("stop")):
            with self.subTest(exception=type(exception).__name__), tempfile.TemporaryDirectory() as raw_directory:
                root = Path(raw_directory)
                closed_descriptors: list[int] = []

                def recording_close(descriptor: int) -> None:
                    closed_descriptors.append(descriptor)
                    real_close(descriptor)

                with (
                    _working_directory(root),
                    mock.patch.object(
                        ANCHORED_OUTPUT.os,
                        "close",
                        side_effect=recording_close,
                    ),
                    mock.patch.object(
                        OUTPUT_PARENT_BINDING_TYPE,
                        "verify",
                        side_effect=exception,
                    ),
                    self.assertRaises(type(exception)) as raised,
                ):
                    OPEN_OUTPUT_PARENT(root / "snapshot.json")

                self.assertIs(raised.exception, exception)
                self.assertGreaterEqual(len(closed_descriptors), 1)
                for descriptor in closed_descriptors:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)

    def test_trusted_input_hardlink_aliases_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("trusted\n", encoding="utf-8")
            try:
                os.link(first, second)
            except OSError:
                self.skipTest("This platform cannot create file hardlinks.")
            with self.assertRaisesRegex(snapshotter.SnapshotError, "different files"):
                snapshotter.validate_distinct_inputs((("first", first), ("second", second)))

    def test_all_native_platform_policies_bind_exact_tuple_and_manifest(self) -> None:
        self.assertEqual(
            snapshotter.PLATFORM_POLICIES,
            {
                "linux-x64": (
                    "linux",
                    "posix",
                    "Linux",
                    "x86_64",
                    "3.12.13",
                    "constraints/requirements-linux-py312.lock",
                ),
                "macos-arm64": (
                    "darwin",
                    "posix",
                    "Darwin",
                    "arm64",
                    "3.12.10",
                    "constraints/requirements-macos-py312.lock",
                ),
                "windows-x64": (
                    "win32",
                    "nt",
                    "Windows",
                    "AMD64",
                    "3.12.10",
                    "constraints/requirements-windows-py312.lock",
                ),
            },
        )
        for platform_label, policy in snapshotter.PLATFORM_POLICIES.items():
            with self.subTest(platform=platform_label, boundary="repository lock"):
                snapshotter.load_constraint(Path(policy[-1]))
        for platform_label in ("macos-arm64", "windows-x64"):
            with (
                self.subTest(platform=platform_label),
                tempfile.TemporaryDirectory() as raw_directory,
            ):
                fixture = SnapshotFixture(
                    Path(raw_directory),
                    platform_label=platform_label,
                )
                fixture.verify(platform_label)

    def test_identity_timestamp_and_purl_validation_is_strict(self) -> None:
        self.assertEqual(snapshotter.package_url("Feature_Dep", "3.0+local"), "pkg:pypi/feature-dep@3.0%2Blocal")
        snapshotter.validate_identity(
            repository="Infiland/GM2Godot",
            sha=SHA,
            ref="refs/pull/838/merge",
            run_id="1",
            run_attempt="2",
        )
        for keyword, value in (
            ("repository", "bad"),
            ("sha", SHA.upper()),
            ("ref", "main"),
            ("run_id", "01"),
            ("run_attempt", "0"),
        ):
            arguments = {
                "repository": "Infiland/GM2Godot",
                "sha": SHA,
                "ref": "refs/heads/main",
                "run_id": "1",
                "run_attempt": "1",
            }
            arguments[keyword] = value
            with self.subTest(keyword=keyword), self.assertRaises(snapshotter.SnapshotError):
                snapshotter.validate_identity(**arguments)
        self.assertEqual(snapshotter.validate_scanned(SCANNED), SCANNED)
        for value in ("2026-09-02T12:34:56+00:00", "2026-02-30T00:00:00Z", "2026-9-2T00:00:00Z"):
            with self.subTest(value=value), self.assertRaises(snapshotter.SnapshotError):
                snapshotter.validate_scanned(value)

    def test_pip_inspect_invocation_is_isolated_and_uses_no_shell(self) -> None:
        command = snapshotter.pip_inspect_command()
        self.assertEqual(command[:6], [snapshotter.sys.executable, "-X", "utf8", "-I", "-m", "pip"])
        self.assertEqual(command[-2:], ["inspect", "--local"])
        environment = snapshotter.isolated_pip_environment(
            {
                "PATH": "/trusted",
                "PIP_INDEX_URL": "https://untrusted.invalid",
                "pip_config_file": "/untrusted",
                "PYTHONPATH": "/untrusted",
                "pythonhome": "/untrusted",
            }
        )
        self.assertEqual(environment, {"PATH": "/trusted", "PIP_CONFIG_FILE": os.devnull})

    def test_cli_failure_does_not_create_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            fixture = SnapshotFixture(root)
            output = root / "snapshot.json"
            stderr = StringIO()
            with (
                _working_directory(root),
                mock.patch.object(
                    snapshotter,
                    "run_pip_inspect",
                    side_effect=snapshotter.SnapshotError("inspect-failed", "blocked"),
                ),
                redirect_stderr(stderr),
            ):
                status = snapshotter.main(
                    [
                        "--constraint",
                        str(fixture.constraint_path),
                        "--verification-receipt",
                        str(fixture.receipt_path),
                        "--platform",
                        "linux-x64",
                        "--repository",
                        "Infiland/GM2Godot",
                        "--sha",
                        SHA,
                        "--ref",
                        "refs/heads/main",
                        "--run-id",
                        "1",
                        "--run-attempt",
                        "1",
                        "--scanned",
                        SCANNED,
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(status, 1)
            self.assertIn("inspect-failed", stderr.getvalue())
            self.assertFalse(output.exists())

    def test_cli_rejects_inputs_redirected_outside_checkout_by_ancestor_link(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as raw_checkout,
            tempfile.TemporaryDirectory() as raw_external,
        ):
            checkout = Path(raw_checkout)
            external = Path(raw_external)
            fixture = SnapshotFixture(checkout)
            external_constraint = external / "candidate.lock"
            external_constraint.write_bytes(fixture.constraint_path.read_bytes())
            linked_directory = checkout / "redirected"
            try:
                linked_directory.symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest("This platform cannot create directory symlinks.")
            output = checkout / "snapshot.json"
            stderr = StringIO()
            with _working_directory(checkout), redirect_stderr(stderr):
                status = snapshotter.main(
                    [
                        "--constraint",
                        str(linked_directory / external_constraint.name),
                        "--verification-receipt",
                        str(fixture.receipt_path),
                        "--platform",
                        "linux-x64",
                        "--repository",
                        "Infiland/GM2Godot",
                        "--sha",
                        SHA,
                        "--ref",
                        "refs/heads/main",
                        "--run-id",
                        "1",
                        "--run-attempt",
                        "1",
                        "--scanned",
                        SCANNED,
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(status, 1)
            self.assertIn("path-outside-checkout", stderr.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
