# pyright: reportPrivateUsage=false
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from src import cli
from src.conversion import managed_output_publisher as publisher_module
from src.conversion import managed_output_workspace as workspace_module
from src.conversion.conversion_manifest import (
    CONVERSION_ATTEMPT_RELATIVE_PATH,
    CONVERSION_MANIFEST_RELATIVE_PATH,
)
from src.conversion.converter import Converter
from src.conversion.generation_inventory import (
    GenerationInventory,
    capture_generation_inventory,
)
from src.conversion.managed_output_publisher import (
    MANAGED_OUTPUT_DURABLE_PHASES,
    MANAGED_OUTPUT_JOURNAL_NAME,
    MANAGED_OUTPUT_POINTER_NAME,
    MANAGED_OUTPUT_RECOVERY_NAME,
    recover_managed_output_generation,
)
from src.conversion.managed_output_workspace import (
    MANAGED_OUTPUT_WORKSPACE_DURABLE_PHASES,
    WORKSPACE_PARENT_MARKER_NAME,
    WORKSPACE_PARENT_NAME,
    ManagedOutputWorkspace,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_HARD_EXIT_STATUS = 86


class _Setting:
    def __init__(self, value: bool) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value


def _settings() -> dict[str, _Setting]:
    return {
        "project_name": _Setting(True),
        "scripts": _Setting(True),
        "objects": _Setting(True),
        "asset_registry": _Setting(True),
    }


def _convert_fixture(
    gm_path: str | os.PathLike[str],
    godot_path: str | os.PathLike[str],
) -> str:
    running = threading.Event()
    running.set()
    outcome = Converter(
        log_callback=lambda _message: None,
        progress_callback=lambda _value: None,
        status_callback=lambda _message: None,
        conversion_running=running,
        max_workers=1,
    ).convert(
        os.fspath(gm_path),
        "windows",
        os.fspath(godot_path),
        _settings(),
    )
    return outcome.state


def _write_source_fixture(
    gm_path: Path,
    *,
    changed: bool,
) -> None:
    project_name = "Crash Recovery Changed" if changed else "Crash Recovery Baseline"
    scripts = [
        (
            "scr_existing",
            "return 2;\n" if changed else "return 1;\n",
        )
    ]
    if changed:
        scripts.append(("scr_new", "return 3;\n"))

    resources: list[dict[str, object]] = []
    for script_name, body in scripts:
        script_directory = gm_path / "scripts" / script_name
        script_directory.mkdir(parents=True, exist_ok=True)
        relative_path = f"scripts/{script_name}/{script_name}.yy"
        (script_directory / f"{script_name}.yy").write_text(
            json.dumps(
                {
                    "%Name": script_name,
                    "name": script_name,
                    "resourceType": "GMScript",
                    "parent": {
                        "name": "Scripts",
                        "path": "folders/Scripts.yy",
                    },
                }
            ),
            encoding="utf-8",
        )
        (script_directory / f"{script_name}.gml").write_text(
            body,
            encoding="utf-8",
        )
        resources.append(
            {"id": {"name": script_name, "path": relative_path}}
        )

    if changed:
        object_name = "o_transaction_new"
        object_directory = gm_path / "objects" / object_name
        object_directory.mkdir(parents=True, exist_ok=True)
        object_relative_path = f"objects/{object_name}/{object_name}.yy"
        (object_directory / f"{object_name}.yy").write_text(
            json.dumps(
                {
                    "$GMObject": "",
                    "%Name": object_name,
                    "eventList": [],
                    "managed": True,
                    "name": object_name,
                    "overriddenProperties": [],
                    "parent": {
                        "name": "Objects",
                        "path": "folders/Objects.yy",
                    },
                    "parentObjectId": None,
                    "persistent": False,
                    "physicsObject": False,
                    "properties": [],
                    "resourceType": "GMObject",
                    "resourceVersion": "2.0",
                    "solid": False,
                    "spriteId": None,
                    "spriteMaskId": None,
                    "visible": True,
                }
            ),
            encoding="utf-8",
        )
        resources.append(
            {
                "id": {
                    "name": object_name,
                    "path": object_relative_path,
                }
            }
        )

    (gm_path / "CrashRecovery.yyp").write_text(
        json.dumps(
            {
                "%Name": project_name,
                "name": project_name,
                "resourceType": "GMProject",
                "resources": resources,
                "RoomOrderNodes": [],
            }
        ),
        encoding="utf-8",
    )


@dataclass(frozen=True)
class _PublicGeneration:
    manifest: bytes
    attempt: bytes
    files: tuple[tuple[str, bytes, int], ...]


def _portable_mode(path: Path) -> int:
    mode = stat.S_IMODE(path.stat().st_mode)
    if os.name == "nt":
        return stat.S_IWUSR if mode & stat.S_IWUSR else 0
    return mode


def _capture_public_generation(destination: Path) -> _PublicGeneration:
    manifest_path = destination / CONVERSION_MANIFEST_RELATIVE_PATH
    attempt_path = destination / CONVERSION_ATTEMPT_RELATIVE_PATH
    manifest = manifest_path.read_bytes()
    attempt = attempt_path.read_bytes()
    manifest_payload = json.loads(manifest)
    attempt_payload = json.loads(attempt)
    inventory = GenerationInventory.from_value(
        manifest_payload["generation_inventory"]
    )
    if capture_generation_inventory(destination) != inventory:
        raise AssertionError("Public generation does not match its canonical inventory")
    expected_manifest_digest = "sha256:" + hashlib.sha256(manifest).hexdigest()
    if (
        attempt_payload["canonical_manifest"]["sha256"]
        != expected_manifest_digest
    ):
        raise AssertionError("Attempt does not identify the canonical manifest")
    return _PublicGeneration(
        manifest=manifest,
        attempt=attempt,
        files=tuple(
            (
                entry.path,
                (destination / entry.path).read_bytes(),
                _portable_mode(destination / entry.path),
            )
            for entry in inventory.entries
        ),
    )


def _record_phases(
    events: list[str],
) -> Callable[[str, str | None], None]:
    def record(phase: str, _path: str | None) -> None:
        events.append(phase)

    return record


_INTERRUPTION_SCRIPT = r"""
import os
import sys

from src.conversion import managed_output_publisher as publisher_module
from src.conversion import managed_output_workspace as workspace_module
from tests.test_managed_output_crash_recovery import _convert_fixture

gm_path, godot_path, source, raw_index = sys.argv[1:]
target_index = int(raw_index)
publisher_index = 0
workspace_index = 0
publication_committed = False

def publisher_boundary(phase, _path):
    global publisher_index, publication_committed
    if phase == "commit_decision_published":
        publication_committed = True
    if source != "publisher":
        return
    if publisher_index == target_index:
        os._exit(86)
    publisher_index += 1

def workspace_boundary(_phase, _path):
    global workspace_index
    if source != "workspace" or not publication_committed:
        return
    if workspace_index == target_index:
        os._exit(86)
    workspace_index += 1

publisher_module._after_managed_output_phase = publisher_boundary
workspace_module._after_workspace_phase = workspace_boundary
_convert_fixture(gm_path, godot_path)
raise SystemExit(87)
"""

_ROLLBACK_INTERRUPTION_SCRIPT = r"""
import os
import sys

from src.conversion import managed_output_publisher as publisher_module
from tests.test_managed_output_crash_recovery import _convert_fixture

gm_path, godot_path, raw_index = sys.argv[1:]
target_index = int(raw_index)
install_count = 0
boundary_index = 0

def fail_commit(phase, _path):
    global install_count
    if phase == "before_public_install":
        install_count += 1
        if install_count == 3:
            raise OSError("injected real-converter commit failure")

def stop_during_rollback(phase, _path):
    global boundary_index
    selected = (
        phase.startswith("rollback_")
        or (
            phase.startswith("previous_")
            and phase != "previous_pointer_displaced"
        )
    )
    if not selected:
        return
    if boundary_index == target_index:
        os._exit(86)
    boundary_index += 1

publisher_module._before_managed_output_phase = fail_commit
publisher_module._after_managed_output_phase = stop_during_rollback
_convert_fixture(gm_path, godot_path)
raise SystemExit(87)
"""

_RECOVERY_INTERRUPTION_SCRIPT = r"""
import os
import sys

from src.conversion import managed_output_publisher as publisher_module

godot_path, raw_index = sys.argv[1:]
target_index = int(raw_index)
boundary_index = 0

def stop_during_recovery(_phase, _path):
    global boundary_index
    if boundary_index == target_index:
        os._exit(86)
    boundary_index += 1

publisher_module._after_managed_output_phase = stop_during_recovery
publisher_module.recover_managed_output_generation(godot_path)
raise SystemExit(87)
"""

_WINDOWS_READONLY_CLEANUP_SCRIPT = r"""
import os
import stat
import sys
from pathlib import Path

from src.conversion import managed_output_publisher as publisher_module
from src.conversion import managed_output_workspace as workspace_module
from tests.test_managed_output_crash_recovery import _convert_fixture

gm_path, godot_path = sys.argv[1:]
committed = False

def make_cleanup_tree_read_only(phase, path):
    if phase != "before_private_cleanup" or path is None:
        return
    root = Path(path)
    directories = []
    for current, child_directories, filenames in os.walk(root):
        current_path = Path(current)
        directories.append(current_path)
        for filename in filenames:
            if filename == ".gm2godot-workspace-stage.json":
                continue
            (current_path / filename).chmod(stat.S_IREAD)
        for directory in child_directories:
            directories.append(current_path / directory)
    for directory in sorted(set(directories), key=lambda item: len(item.parts), reverse=True):
        directory.chmod(stat.S_IREAD)

def observe_commit(phase, _path):
    global committed
    if phase == "commit_decision_published":
        committed = True

def stop_after_quarantine(phase, _path):
    if committed and phase == "stage_cleanup_quarantined":
        os._exit(86)

publisher_module._before_managed_output_phase = make_cleanup_tree_read_only
publisher_module._after_managed_output_phase = observe_commit
workspace_module._after_workspace_phase = stop_after_quarantine
_convert_fixture(gm_path, godot_path)
raise SystemExit(87)
"""


class TestManagedOutputCrashRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self._success_boundary_cache: tuple[list[str], list[str]] | None = None

    def tearDown(self) -> None:
        shutil.rmtree(
            self.temp_dir,
            onexc=self._retry_windows_read_only_cleanup,
        )

    @staticmethod
    def _retry_windows_read_only_cleanup(
        function: object,
        path: str,
        error: BaseException,
    ) -> None:
        if not isinstance(error, PermissionError) or not callable(function):
            raise error
        path_stat = os.lstat(path)
        os.chmod(path, stat.S_IMODE(path_stat.st_mode) | stat.S_IWRITE)
        function(path)

    def _create_case(self, name: str) -> tuple[Path, Path, _PublicGeneration]:
        case_root = self.temp_dir / name
        gm_path = case_root / "gamemaker"
        destination = case_root / "godot"
        gm_path.mkdir(parents=True)
        _write_source_fixture(gm_path, changed=False)
        self.assertEqual(_convert_fixture(gm_path, destination), "success")
        sentinel = destination / "user-owned-sentinel.txt"
        sentinel.write_bytes(b"user-owned crash sentinel\n")
        baseline = _capture_public_generation(destination)
        _write_source_fixture(gm_path, changed=True)
        return gm_path, destination, baseline

    def _discover_success_boundaries(
        self,
    ) -> tuple[list[str], list[str]]:
        gm_path, destination, baseline = self._create_case("discovery")
        publisher_events: list[str] = []
        workspace_events: list[str] = []
        committed = False

        def publisher_boundary(phase: str, _path: str | None) -> None:
            nonlocal committed
            publisher_events.append(phase)
            if phase == "commit_decision_published":
                committed = True

        def workspace_boundary(phase: str, _path: str) -> None:
            if committed:
                workspace_events.append(phase)

        with (
            patch.object(
                publisher_module,
                "_after_managed_output_phase",
                side_effect=publisher_boundary,
            ),
            patch.object(
                workspace_module,
                "_after_workspace_phase",
                side_effect=workspace_boundary,
            ),
        ):
            self.assertEqual(_convert_fixture(gm_path, destination), "success")

        desired = _capture_public_generation(destination)
        self.assertNotEqual(desired.manifest, baseline.manifest)
        self._assert_desired_generation(destination, desired)
        self.assertEqual(
            (destination / "user-owned-sentinel.txt").read_bytes(),
            b"user-owned crash sentinel\n",
        )
        return publisher_events, workspace_events

    def _success_boundaries(self) -> tuple[list[str], list[str]]:
        if self._success_boundary_cache is None:
            self._success_boundary_cache = (
                self._discover_success_boundaries()
            )
        publisher_events, workspace_events = self._success_boundary_cache
        return list(publisher_events), list(workspace_events)

    def _assert_desired_generation(
        self,
        destination: Path,
        generation: _PublicGeneration,
    ) -> None:
        manifest = json.loads(generation.manifest)
        attempt = json.loads(generation.attempt)
        self.assertEqual(
            manifest["source_project"]["name"],
            "Crash Recovery Changed",
        )
        self.assertEqual(attempt["attempt"]["state"], "success")
        self.assertIn(
            'config/name="Crash Recovery Changed"',
            (destination / "project.godot").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "return 2",
            (destination / "scripts" / "scr_existing.gd").read_text(
                encoding="utf-8"
            ),
        )
        self.assertTrue(
            (destination / "scripts" / "scr_new.gd").is_file()
        )
        self.assertTrue(
            (
                destination
                / "objects"
                / "o_transaction_new"
                / "o_transaction_new.gd"
            ).is_file()
        )

    def _assert_failed_attempt_preserves_previous(
        self,
        destination: Path,
        baseline: _PublicGeneration,
    ) -> None:
        current = _capture_public_generation(destination)
        self.assertEqual(current.manifest, baseline.manifest)
        self.assertEqual(current.files, baseline.files)
        attempt = json.loads(current.attempt)
        self.assertEqual(attempt["attempt"]["state"], "failed")
        self.assertEqual(
            attempt["canonical_manifest"]["status"],
            "preserved",
        )
        self.assertEqual(
            attempt["canonical_manifest"]["current_output"],
            "verified",
        )
        self.assertEqual(
            attempt["canonical_manifest"]["sha256"],
            "sha256:" + hashlib.sha256(baseline.manifest).hexdigest(),
        )

    def _assert_no_transaction_debris(self, destination: Path) -> None:
        workspace_parent = destination / WORKSPACE_PARENT_NAME
        names = {path.name for path in workspace_parent.iterdir()}
        self.assertIn(WORKSPACE_PARENT_MARKER_NAME, names)
        self.assertIn(MANAGED_OUTPUT_POINTER_NAME, names)
        self.assertNotIn(MANAGED_OUTPUT_JOURNAL_NAME, names)
        self.assertNotIn(MANAGED_OUTPUT_RECOVERY_NAME, names)
        self.assertFalse(
            any(
                name.endswith((".stage", ".cleanup", ".tmp"))
                for name in names
            ),
            sorted(names),
        )
        generation_records = {
            name
            for name in names
            if name.startswith(".gm2godot-managed-output-generation-")
        }
        self.assertEqual(len(generation_records), 1, sorted(names))
        self.assertEqual(
            names,
            {
                WORKSPACE_PARENT_MARKER_NAME,
                MANAGED_OUTPUT_POINTER_NAME,
                *generation_records,
            },
        )

    def _interrupt(
        self,
        gm_path: Path,
        destination: Path,
        *,
        source: str,
        index: int,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            os.fspath(PROJECT_ROOT)
            if not existing_python_path
            else os.fspath(PROJECT_ROOT)
            + os.pathsep
            + existing_python_path
        )
        return subprocess.run(
            (
                sys.executable,
                "-c",
                _INTERRUPTION_SCRIPT,
                os.fspath(gm_path),
                os.fspath(destination),
                source,
                str(index),
            ),
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def _run_child_script(
        self,
        script: str,
        *arguments: str | os.PathLike[str],
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            os.fspath(PROJECT_ROOT)
            if not existing_python_path
            else os.fspath(PROJECT_ROOT)
            + os.pathsep
            + existing_python_path
        )
        return subprocess.run(
            (
                sys.executable,
                "-c",
                script,
                *(os.fspath(argument) for argument in arguments),
            ),
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def _discover_rollback_boundaries(
        self,
    ) -> list[str]:
        gm_path, destination, baseline = self._create_case(
            "rollback-discovery"
        )
        install_count = 0
        events: list[str] = []

        def fail_commit(phase: str, _path: str | None) -> None:
            nonlocal install_count
            if phase == "before_public_install":
                install_count += 1
                if install_count == 3:
                    raise OSError("injected real-converter commit failure")

        def record_boundary(phase: str, _path: str | None) -> None:
            if phase.startswith("rollback_") or (
                phase.startswith("previous_")
                and phase != "previous_pointer_displaced"
            ):
                events.append(phase)

        with (
            patch.object(
                publisher_module,
                "_before_managed_output_phase",
                side_effect=fail_commit,
            ),
            patch.object(
                publisher_module,
                "_after_managed_output_phase",
                side_effect=record_boundary,
            ),
            self.assertRaisesRegex(
                OSError,
                "real-converter commit failure",
            ),
        ):
            _convert_fixture(gm_path, destination)
        self._assert_failed_attempt_preserves_previous(
            destination,
            baseline,
        )
        self._assert_no_transaction_debris(destination)
        return events

    def _create_pending_publication(
        self,
        name: str,
        phase: str,
    ) -> tuple[Path, Path, _PublicGeneration]:
        publisher_events, _workspace_events = (
            self._success_boundaries()
        )
        target_index = publisher_events.index(phase)
        gm_path, destination, baseline = self._create_case(name)
        interrupted = self._interrupt(
            gm_path,
            destination,
            source="publisher",
            index=target_index,
        )
        self.assertEqual(
            interrupted.returncode,
            _HARD_EXIT_STATUS,
            interrupted.stdout + interrupted.stderr,
        )
        return gm_path, destination, baseline

    def _discover_recovery_boundaries(
        self,
        *,
        name: str,
        pending_phase: str,
    ) -> list[str]:
        _gm_path, destination, baseline = self._create_pending_publication(
            name,
            pending_phase,
        )
        events: list[str] = []

        def record_boundary(
            phase: str,
            _path: str | None,
        ) -> None:
            events.append(phase)

        with patch.object(
            publisher_module,
            "_after_managed_output_phase",
            side_effect=record_boundary,
        ):
            recover_managed_output_generation(destination)
        recovered = _capture_public_generation(destination)
        if pending_phase == "commit_decision_published":
            self.assertNotEqual(recovered.manifest, baseline.manifest)
            self._assert_desired_generation(destination, recovered)
        else:
            self.assertEqual(recovered, baseline)
        self._assert_no_transaction_debris(destination)
        return events

    def test_real_converter_recovers_every_success_boundary_old_or_new(
        self,
    ) -> None:
        (
            publisher_events,
            workspace_events,
        ) = self._success_boundaries()
        phase_sides = dict(MANAGED_OUTPUT_DURABLE_PHASES)
        self.assertEqual(
            set(publisher_events) - set(phase_sides),
            set(),
        )
        self.assertEqual(
            set(workspace_events) - set(MANAGED_OUTPUT_WORKSPACE_DURABLE_PHASES),
            set(),
        )
        self.assertIn("journal_durable", publisher_events)
        self.assertIn("commit_decision_published", publisher_events)
        self.assertIn("desired_journal_retired", publisher_events)
        self.assertEqual(
            set(MANAGED_OUTPUT_WORKSPACE_DURABLE_PHASES)
            - set(workspace_events),
            set(),
        )

        workspace_cases = list(enumerate(workspace_events))
        if sys.platform == "win32":
            # Process startup and antivirus scanning dominate native Windows.
            # POSIX gates interrupt every concrete cleanup entry; Windows
            # interrupts every declared cleanup operation and separately
            # exercises NTFS read-only, reparse, and write-through behavior.
            seen_workspace_phases: set[str] = set()
            selected_workspace_cases: list[tuple[int, str]] = []
            for index, phase in workspace_cases:
                if phase in seen_workspace_phases:
                    continue
                seen_workspace_phases.add(phase)
                selected_workspace_cases.append((index, phase))
            workspace_cases = selected_workspace_cases

        cases = [
            *(
                ("publisher", index, phase, phase_sides[phase])
                for index, phase in enumerate(publisher_events)
            ),
            *(
                ("workspace", index, phase, "post_commit")
                for index, phase in workspace_cases
            ),
        ]
        for case_index, (source, index, phase, commit_side) in enumerate(cases):
            with self.subTest(
                source=source,
                index=index,
                phase=phase,
                commit_side=commit_side,
            ):
                gm_path, destination, baseline = self._create_case(
                    f"boundary-{case_index:03d}"
                )
                interrupted = self._interrupt(
                    gm_path,
                    destination,
                    source=source,
                    index=index,
                )
                self.assertEqual(
                    interrupted.returncode,
                    _HARD_EXIT_STATUS,
                    interrupted.stdout + interrupted.stderr,
                )
                workspace_parent = destination / WORKSPACE_PARENT_NAME
                for path in workspace_parent.rglob("*"):
                    self.assertEqual(
                        path.stat(follow_symlinks=False).st_dev,
                        destination.stat().st_dev,
                    )

                recover_managed_output_generation(destination)
                recovered = _capture_public_generation(destination)
                if commit_side == "pre_commit":
                    self.assertEqual(recovered, baseline)
                else:
                    self.assertNotEqual(recovered.manifest, baseline.manifest)
                    self._assert_desired_generation(destination, recovered)
                self.assertEqual(
                    (destination / "user-owned-sentinel.txt").read_bytes(),
                    b"user-owned crash sentinel\n",
                )
                self.assertIsNone(
                    recover_managed_output_generation(destination)
                )
                self._assert_no_transaction_debris(destination)

    def test_real_converter_hard_exit_during_rollback_recovers_previous(
        self,
    ) -> None:
        events = self._discover_rollback_boundaries()
        self.assertIn("rollback_desired_staged", events)
        self.assertIn("rollback_previous_restored", events)
        self.assertIn("rollback_complete", events)
        self.assertIn("previous_journal_retired", events)
        self.assertEqual(
            set(events) - dict(MANAGED_OUTPUT_DURABLE_PHASES).keys(),
            set(),
        )

        for index, phase in enumerate(events):
            with self.subTest(index=index, phase=phase):
                gm_path, destination, baseline = self._create_case(
                    f"rollback-{index:03d}"
                )
                interrupted = self._run_child_script(
                    _ROLLBACK_INTERRUPTION_SCRIPT,
                    gm_path,
                    destination,
                    str(index),
                )
                self.assertEqual(
                    interrupted.returncode,
                    _HARD_EXIT_STATUS,
                    interrupted.stdout + interrupted.stderr,
                )
                recover_managed_output_generation(destination)
                self.assertEqual(
                    _capture_public_generation(destination),
                    baseline,
                )
                self.assertIsNone(
                    recover_managed_output_generation(destination)
                )
                self._assert_no_transaction_debris(destination)

    def test_recovery_is_restartable_at_each_publisher_boundary(
        self,
    ) -> None:
        for recovery_kind, pending_phase in (
            ("previous", "public_installed"),
            ("desired", "commit_decision_published"),
        ):
            events = self._discover_recovery_boundaries(
                name=f"{recovery_kind}-recovery-discovery",
                pending_phase=pending_phase,
            )
            self.assertNotEqual(events, [])
            self.assertEqual(
                set(events) - dict(MANAGED_OUTPUT_DURABLE_PHASES).keys(),
                set(),
            )
            for index, phase in enumerate(events):
                with self.subTest(
                    recovery_kind=recovery_kind,
                    index=index,
                    phase=phase,
                ):
                    _gm_path, destination, baseline = (
                        self._create_pending_publication(
                            f"{recovery_kind}-recovery-{index:03d}",
                            pending_phase,
                        )
                    )
                    interrupted = self._run_child_script(
                        _RECOVERY_INTERRUPTION_SCRIPT,
                        destination,
                        str(index),
                    )
                    self.assertEqual(
                        interrupted.returncode,
                        _HARD_EXIT_STATUS,
                        interrupted.stdout + interrupted.stderr,
                    )
                    recover_managed_output_generation(destination)
                    recovered = _capture_public_generation(destination)
                    if recovery_kind == "previous":
                        self.assertEqual(recovered, baseline)
                    else:
                        self.assertNotEqual(
                            recovered.manifest,
                            baseline.manifest,
                        )
                        self._assert_desired_generation(
                            destination,
                            recovered,
                        )
                    self.assertIsNone(
                        recover_managed_output_generation(destination)
                    )
                    self._assert_no_transaction_debris(destination)

    def test_real_commit_and_recovery_failures_publish_strict_artifact(
        self,
    ) -> None:
        gm_path, destination, baseline = self._create_case(
            "recovery-artifact"
        )
        install_count = 0
        rollback_failed = False
        durable_events: list[str] = []

        def fail_commit_and_rollback(
            phase: str,
            _path: str | None,
        ) -> None:
            nonlocal install_count, rollback_failed
            if phase == "before_public_install":
                install_count += 1
                if install_count == 3:
                    raise OSError("injected real commit failure")
            if phase == "before_rollback_previous" and not rollback_failed:
                rollback_failed = True
                raise OSError("injected independent rollback failure")

        with (
            patch.object(
                publisher_module,
                "_before_managed_output_phase",
                side_effect=fail_commit_and_rollback,
            ),
            patch.object(
                publisher_module,
                "_after_managed_output_phase",
                side_effect=_record_phases(durable_events),
            ),
            self.assertRaisesRegex(
                OSError,
                "injected real commit failure",
            ),
        ):
            _convert_fixture(gm_path, destination)

        workspace_parent = destination / WORKSPACE_PARENT_NAME
        artifact_path = (
            workspace_parent / MANAGED_OUTPUT_RECOVERY_NAME
        )
        journal_path = workspace_parent / MANAGED_OUTPUT_JOURNAL_NAME
        self.assertTrue(artifact_path.is_file())
        self.assertTrue(journal_path.is_file())
        self.assertIn(
            "recovery_artifact_previous_durable",
            durable_events,
        )
        artifact_content = artifact_path.read_bytes()
        self.assertLessEqual(
            len(artifact_content),
            publisher_module._RECOVERY_MAX_BYTES,
        )
        artifact = json.loads(artifact_content)
        self.assertEqual(
            set(artifact),
            {
                "format_version",
                "kind",
                "state",
                "transaction_id",
                "destination_identity",
                "selected_generation",
                "journal",
                "workspace_stage",
                "affected_path_count",
                "affected_paths",
                "affected_paths_truncated",
                "error",
                "next_step",
            },
        )
        journal = json.loads(journal_path.read_bytes())
        self.assertEqual(
            artifact["transaction_id"],
            journal["transaction_id"],
        )
        self.assertRegex(artifact["transaction_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(artifact["selected_generation"], "previous")
        self.assertEqual(artifact["state"], "recovery_required")
        destination_stat = destination.stat()
        self.assertEqual(
            artifact["destination_identity"],
            [
                f"{destination_stat.st_dev:032x}",
                f"{destination_stat.st_ino:032x}",
            ],
        )
        self.assertEqual(
            artifact["affected_path_count"],
            len(journal["transitions"]),
        )
        self.assertLessEqual(len(artifact["affected_paths"]), 100)
        self.assertIn(
            "recover_managed_output_generation",
            artifact["next_step"],
        )
        self.assertLessEqual(len(artifact["error"]), 4096)
        for private_path in workspace_parent.rglob("*"):
            self.assertEqual(
                private_path.stat(follow_symlinks=False).st_dev,
                destination.stat().st_dev,
            )

        recovery_failed = False

        def fail_recovery_once(
            phase: str,
            _path: str | None,
        ) -> None:
            nonlocal recovery_failed
            if phase == "before_rollback_previous" and not recovery_failed:
                recovery_failed = True
                raise OSError("injected independent recovery failure")

        with (
            patch.object(
                publisher_module,
                "_before_managed_output_phase",
                side_effect=fail_recovery_once,
            ),
            self.assertRaisesRegex(
                OSError,
                "independent recovery failure",
            ),
        ):
            recover_managed_output_generation(destination)
        self.assertEqual(artifact_path.read_bytes(), artifact_content)
        self.assertEqual(
            (destination / "user-owned-sentinel.txt").read_bytes(),
            b"user-owned crash sentinel\n",
        )

        durable_events.clear()
        with patch.object(
            publisher_module,
            "_after_managed_output_phase",
            side_effect=_record_phases(durable_events),
        ):
            recover_managed_output_generation(destination)
        self.assertIn(
            "previous_recovery_artifact_retired",
            durable_events,
        )
        self.assertEqual(
            _capture_public_generation(destination),
            baseline,
        )
        self.assertIsNone(recover_managed_output_generation(destination))
        self._assert_no_transaction_debris(destination)

    def test_ambiguous_decision_reports_unknown_without_touching_sentinel(
        self,
    ) -> None:
        _gm_path, destination, baseline = self._create_pending_publication(
            "ambiguous-recovery",
            "public_installed",
        )
        pending = publisher_module._peek_pending_journal(destination)
        self.assertIsNotNone(pending)
        assert pending is not None
        journal_content, journal = pending
        pointer_path = (
            destination
            / WORKSPACE_PARENT_NAME
            / MANAGED_OUTPUT_POINTER_NAME
        )
        previous_pointer = pointer_path.read_bytes()
        foreign_pointer = publisher_module._Pointer(
            transaction_id=journal.transaction_id,
            destination_identity=journal.destination_identity,
            journal_sha256=publisher_module._sha256_bytes(
                journal_content
            ),
            generation_record=journal.previous_record,
        )
        with pointer_path.open("wb") as pointer_file:
            pointer_file.write(
                publisher_module._pointer_content(foreign_pointer)
            )
            pointer_file.flush()
            os.fsync(pointer_file.fileno())

        durable_events: list[str] = []
        with (
            patch.object(
                publisher_module,
                "_after_managed_output_phase",
                side_effect=_record_phases(durable_events),
            ),
            self.assertRaisesRegex(
                OSError,
                "journal and durable commit decision disagree",
            ),
        ):
            recover_managed_output_generation(destination)
        self.assertIn(
            "recovery_artifact_unknown_durable",
            durable_events,
        )
        artifact_path = (
            destination
            / WORKSPACE_PARENT_NAME
            / MANAGED_OUTPUT_RECOVERY_NAME
        )
        artifact = json.loads(artifact_path.read_bytes())
        self.assertEqual(artifact["selected_generation"], "unknown")
        self.assertEqual(
            artifact["transaction_id"],
            journal.transaction_id,
        )
        self.assertEqual(
            (destination / "user-owned-sentinel.txt").read_bytes(),
            b"user-owned crash sentinel\n",
        )

        with pointer_path.open("wb") as pointer_file:
            pointer_file.write(previous_pointer)
            pointer_file.flush()
            os.fsync(pointer_file.fileno())
        recover_managed_output_generation(destination)
        self.assertEqual(
            _capture_public_generation(destination),
            baseline,
        )
        self._assert_no_transaction_debris(destination)

    def test_postcommit_cleanup_failure_reports_desired_recovery_state(
        self,
    ) -> None:
        gm_path, destination, baseline = self._create_case(
            "desired-recovery-artifact"
        )
        cleanup_failed = False
        events: list[str] = []

        def fail_cleanup(
            phase: str,
            _path: str | None,
        ) -> None:
            nonlocal cleanup_failed
            if phase == "before_private_cleanup" and not cleanup_failed:
                cleanup_failed = True
                raise OSError("injected committed cleanup failure")

        with (
            patch.object(
                publisher_module,
                "_before_managed_output_phase",
                side_effect=fail_cleanup,
            ),
            patch.object(
                publisher_module,
                "_after_managed_output_phase",
                side_effect=_record_phases(events),
            ),
            self.assertRaisesRegex(
                OSError,
                "committed cleanup failure",
            ),
        ):
            _convert_fixture(gm_path, destination)
        self.assertTrue(cleanup_failed)
        self.assertIn(
            "recovery_artifact_desired_durable",
            events,
        )
        selected = _capture_public_generation(destination)
        self.assertNotEqual(selected.manifest, baseline.manifest)
        self._assert_desired_generation(destination, selected)
        artifact_path = (
            destination
            / WORKSPACE_PARENT_NAME
            / MANAGED_OUTPUT_RECOVERY_NAME
        )
        artifact = json.loads(artifact_path.read_bytes())
        self.assertEqual(artifact["selected_generation"], "desired")

        events.clear()
        with patch.object(
            publisher_module,
            "_after_managed_output_phase",
            side_effect=_record_phases(events),
        ):
            recover_managed_output_generation(destination)
        self.assertIn(
            "desired_recovery_artifact_retired",
            events,
        )
        self.assertIsNone(recover_managed_output_generation(destination))
        self._assert_no_transaction_debris(destination)

    def test_detached_cleanup_rejects_links_and_root_replacement(
        self,
    ) -> None:
        for case_index, attack in enumerate(
            (
                "symlink",
                "hardlink",
                "reserved_collision",
                "root_replacement",
            )
        ):
            with self.subTest(attack=attack):
                gm_path, destination, baseline = self._create_case(
                    f"detached-attack-{case_index}"
                )
                interrupted = self._interrupt(
                    gm_path,
                    destination,
                    source="workspace",
                    index=0,
                )
                self.assertEqual(
                    interrupted.returncode,
                    _HARD_EXIT_STATUS,
                    interrupted.stdout + interrupted.stderr,
                )
                workspace_parent = destination / WORKSPACE_PARENT_NAME
                cleanup_stages = tuple(
                    path
                    for path in workspace_parent.iterdir()
                    if path.name.endswith(".cleanup")
                )
                self.assertEqual(len(cleanup_stages), 1)
                cleanup_stage = cleanup_stages[0]
                external = (
                    self.temp_dir
                    / f"detached-external-{case_index}.txt"
                )
                external.write_bytes(b"detached external sentinel\n")
                injected = cleanup_stage / "injected"
                parked = cleanup_stage.with_name(
                    cleanup_stage.name + ".parked"
                )

                if attack == "symlink":
                    try:
                        injected.symlink_to(external)
                    except (NotImplementedError, OSError):
                        recover_managed_output_generation(destination)
                        continue
                elif attack == "hardlink":
                    os.link(external, injected)
                elif attack == "reserved_collision":
                    injected = (
                        cleanup_stage
                        / (
                            ".gm2godot-cleanup-"
                            + "f" * 32
                            + "-00000001"
                        )
                    )
                    injected.write_bytes(b"unknown reserved collision\n")
                else:
                    cleanup_stage.rename(parked)
                    cleanup_stage.mkdir()
                    injected = cleanup_stage / "user-sentinel.txt"
                    injected.write_bytes(b"replacement sentinel\n")

                try:
                    with self.assertRaises(OSError):
                        recover_managed_output_generation(destination)
                    self.assertEqual(
                        external.read_bytes(),
                        b"detached external sentinel\n",
                    )
                    if attack == "symlink":
                        self.assertTrue(injected.is_symlink())
                    elif attack == "hardlink":
                        self.assertGreaterEqual(external.stat().st_nlink, 2)
                    elif attack == "reserved_collision":
                        self.assertEqual(
                            injected.read_bytes(),
                            b"unknown reserved collision\n",
                        )
                    else:
                        self.assertEqual(
                            injected.read_bytes(),
                            b"replacement sentinel\n",
                        )
                finally:
                    if attack in {
                        "symlink",
                        "hardlink",
                        "reserved_collision",
                    }:
                        injected.unlink(missing_ok=True)
                    else:
                        shutil.rmtree(cleanup_stage)
                        parked.rename(cleanup_stage)

                recover_managed_output_generation(destination)
                selected = _capture_public_generation(destination)
                self.assertNotEqual(selected.manifest, baseline.manifest)
                self._assert_desired_generation(destination, selected)
                self.assertEqual(
                    external.read_bytes(),
                    b"detached external sentinel\n",
                )
                self._assert_no_transaction_debris(destination)

    @unittest.skipIf(
        os.name == "nt",
        "physical destination replacement requires POSIX rename semantics",
    )
    def test_destination_replacement_is_rejected_without_external_traversal(
        self,
    ) -> None:
        gm_path, destination, baseline = self._create_case(
            "destination-replacement"
        )
        parked = destination.with_name(destination.name + ".parked")
        external = self.temp_dir / "destination-replacement-external"
        external.mkdir()
        sentinel = external / "external-sentinel.txt"
        sentinel.write_bytes(b"destination replacement sentinel\n")
        replaced = False

        def replace_destination(
            phase: str,
            _path: str | None,
        ) -> None:
            nonlocal replaced
            if phase == "before_public_displace" and not replaced:
                destination.rename(parked)
                destination.symlink_to(external, target_is_directory=True)
                replaced = True

        try:
            with (
                patch.object(
                    publisher_module,
                    "_before_managed_output_phase",
                    side_effect=replace_destination,
                ),
                self.assertRaises(OSError),
            ):
                _convert_fixture(gm_path, destination)
            self.assertTrue(replaced)
            self.assertTrue(destination.is_symlink())
            self.assertEqual(
                sentinel.read_bytes(),
                b"destination replacement sentinel\n",
            )
        finally:
            if destination.is_symlink():
                destination.unlink()
            if parked.exists() and not destination.exists():
                parked.rename(destination)

        recover_managed_output_generation(destination)
        current = _capture_public_generation(destination)
        self.assertEqual(current.manifest, baseline.manifest)
        self.assertEqual(current.files, baseline.files)
        self.assertEqual(
            sentinel.read_bytes(),
            b"destination replacement sentinel\n",
        )
        self._assert_no_transaction_debris(destination)

    def test_direct_library_cancellation_during_recovery_and_commit(
        self,
    ) -> None:
        _gm_path, recovery_destination, baseline = (
            self._create_pending_publication(
                "direct-recovery-cancellation",
                "public_installed",
            )
        )
        recovery_gm_path = (
            self.temp_dir
            / "direct-recovery-cancellation"
            / "gamemaker"
        )
        running = threading.Event()
        running.set()
        cancelled_during_recovery = False

        def cancel_recovery(
            phase: str,
            _path: str | None,
        ) -> None:
            nonlocal cancelled_during_recovery
            if phase == "rollback_previous_restored":
                cancelled_during_recovery = True
                running.clear()

        converter = Converter(
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=running,
            max_workers=1,
        )
        with patch.object(
            publisher_module,
            "_after_managed_output_phase",
            side_effect=cancel_recovery,
        ):
            outcome = converter.convert(
                os.fspath(recovery_gm_path),
                "windows",
                os.fspath(recovery_destination),
                _settings(),
            )
        self.assertTrue(cancelled_during_recovery)
        self.assertEqual(outcome.state, "cancelled")
        recovered = _capture_public_generation(recovery_destination)
        self.assertEqual(recovered.manifest, baseline.manifest)
        self.assertEqual(recovered.files, baseline.files)
        self.assertEqual(
            json.loads(recovered.attempt)["attempt"]["state"],
            "cancelled",
        )
        self._assert_no_transaction_debris(recovery_destination)

        gm_path, destination, commit_baseline = self._create_case(
            "direct-commit-cancellation"
        )
        commit_running = threading.Event()
        commit_running.set()
        cancelled_during_commit = False

        def cancel_commit(
            phase: str,
            _path: str | None,
        ) -> None:
            nonlocal cancelled_during_commit
            if phase == "journal_durable" and not cancelled_during_commit:
                cancelled_during_commit = True
                commit_running.clear()

        commit_converter = Converter(
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=commit_running,
            max_workers=1,
        )
        with patch.object(
            publisher_module,
            "_after_managed_output_phase",
            side_effect=cancel_commit,
        ):
            committed = commit_converter.convert(
                os.fspath(gm_path),
                "windows",
                os.fspath(destination),
                _settings(),
            )
        self.assertTrue(cancelled_during_commit)
        self.assertEqual(committed.state, "success")
        selected = _capture_public_generation(destination)
        self.assertNotEqual(selected.manifest, commit_baseline.manifest)
        self._assert_desired_generation(destination, selected)
        self._assert_no_transaction_debris(destination)

    def test_cli_sigint_matches_recovery_and_commit_decisions(self) -> None:
        _gm_path, recovery_destination, baseline = (
            self._create_pending_publication(
                "cli-recovery-cancellation",
                "public_installed",
            )
        )
        recovery_gm_path = (
            self.temp_dir / "cli-recovery-cancellation" / "gamemaker"
        )
        recovery_interrupted = False

        def interrupt_recovery(
            phase: str,
            _path: str | None,
        ) -> None:
            nonlocal recovery_interrupted
            if phase == "rollback_previous_restored" and not recovery_interrupted:
                recovery_interrupted = True
                signal.raise_signal(signal.SIGINT)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(
                publisher_module,
                "_after_managed_output_phase",
                side_effect=interrupt_recovery,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            recovery_exit = cli.main(
                [
                    "convert",
                    "--gm-project",
                    os.fspath(recovery_gm_path),
                    "--godot-project",
                    os.fspath(recovery_destination),
                    "--platform",
                    "windows",
                    "--only",
                    "project_name,scripts,objects,asset_registry",
                ]
            )
        self.assertTrue(recovery_interrupted)
        self.assertEqual(recovery_exit, 130)
        self.assertEqual(
            stdout.getvalue().count("GM2Godot conversion outcome:"),
            1,
        )
        self.assertIn(
            "GM2Godot conversion outcome: cancelled",
            stdout.getvalue(),
        )
        self.assertEqual(stderr.getvalue(), "")
        recovered = _capture_public_generation(recovery_destination)
        self.assertEqual(recovered.manifest, baseline.manifest)
        self.assertEqual(recovered.files, baseline.files)
        self.assertEqual(
            json.loads(recovered.attempt)["attempt"]["state"],
            "cancelled",
        )

        gm_path, destination, commit_baseline = self._create_case(
            "cli-commit-cancellation"
        )
        commit_interrupted = False

        def interrupt_commit(
            phase: str,
            _path: str | None,
        ) -> None:
            nonlocal commit_interrupted
            if phase == "journal_durable" and not commit_interrupted:
                commit_interrupted = True
                signal.raise_signal(signal.SIGINT)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(
                publisher_module,
                "_after_managed_output_phase",
                side_effect=interrupt_commit,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            commit_exit = cli.main(
                [
                    "convert",
                    "--gm-project",
                    os.fspath(gm_path),
                    "--godot-project",
                    os.fspath(destination),
                    "--platform",
                    "windows",
                    "--only",
                    "project_name,scripts,objects,asset_registry",
                ]
            )
        self.assertTrue(commit_interrupted)
        self.assertEqual(commit_exit, 0, stderr.getvalue())
        self.assertEqual(
            stdout.getvalue().count("GM2Godot conversion outcome:"),
            1,
        )
        self.assertIn(
            "GM2Godot conversion outcome: success",
            stdout.getvalue(),
        )
        selected = _capture_public_generation(destination)
        self.assertNotEqual(selected.manifest, commit_baseline.manifest)
        self._assert_desired_generation(destination, selected)

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "native Linux bind mounts required",
    )
    def test_linux_bind_mount_is_rejected_without_reading_external_target(
        self,
    ) -> None:
        if os.environ.get("GM2GODOT_REQUIRE_LINUX_BIND_MOUNT") != "1":
            self.skipTest(
                "set GM2GODOT_REQUIRE_LINUX_BIND_MOUNT=1 on a native Linux gate"
            )
        sudo = shutil.which("sudo")
        mount = shutil.which("mount")
        umount = shutil.which("umount")
        self.assertIsNotNone(sudo)
        self.assertIsNotNone(mount)
        self.assertIsNotNone(umount)
        assert sudo is not None
        assert mount is not None
        assert umount is not None

        destination = self.temp_dir / "linux-bind-destination"
        mounted = destination / "managed" / "mounted"
        external = self.temp_dir / "linux-bind-external"
        mounted.mkdir(parents=True)
        external.mkdir()
        sentinel = external / "external-sentinel.txt"
        sentinel.write_bytes(b"native Linux bind sentinel\n")
        mounted_sentinel = mounted / sentinel.name

        mounted_result = subprocess.run(
            (
                sudo,
                "-n",
                mount,
                "--bind",
                os.fspath(external),
                os.fspath(mounted),
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(
            mounted_result.returncode,
            0,
            mounted_result.stdout + mounted_result.stderr,
        )
        try:
            with ManagedOutputWorkspace.open(destination) as workspace:
                with self.assertRaisesRegex(
                    OSError,
                    "mount boundary",
                ):
                    workspace.snapshot_files(
                        ("managed/mounted/external-sentinel.txt",)
                    )
            self.assertEqual(
                mounted_sentinel.read_bytes(),
                b"native Linux bind sentinel\n",
            )
            self.assertEqual(
                sentinel.read_bytes(),
                b"native Linux bind sentinel\n",
            )
        finally:
            unmounted = subprocess.run(
                (
                    sudo,
                    "-n",
                    umount,
                    os.fspath(mounted),
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(
                unmounted.returncode,
                0,
                unmounted.stdout + unmounted.stderr,
            )

    @unittest.skipUnless(
        sys.platform == "win32",
        "native Windows read-only cleanup required",
    )
    def test_windows_restart_cleans_read_only_quarantined_stage(
        self,
    ) -> None:
        gm_path, destination, baseline = self._create_case(
            "windows-readonly-restart"
        )
        interrupted = self._run_child_script(
            _WINDOWS_READONLY_CLEANUP_SCRIPT,
            gm_path,
            destination,
        )
        self.assertEqual(
            interrupted.returncode,
            _HARD_EXIT_STATUS,
            interrupted.stdout + interrupted.stderr,
        )

        recover_managed_output_generation(destination)
        selected = _capture_public_generation(destination)
        self.assertNotEqual(selected.manifest, baseline.manifest)
        self._assert_desired_generation(destination, selected)
        self.assertEqual(
            (destination / "user-owned-sentinel.txt").read_bytes(),
            b"user-owned crash sentinel\n",
        )
        self.assertIsNone(recover_managed_output_generation(destination))
        self._assert_no_transaction_debris(destination)


if __name__ == "__main__":
    unittest.main()
