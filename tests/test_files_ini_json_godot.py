from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.included_files import IncludedFilesConverter


def _find_godot_binary() -> str | None:
    env_path = os.environ.get("GODOT_BIN")
    if env_path and os.path.isfile(env_path):
        return env_path

    path_binary = shutil.which("godot")
    if path_binary is not None:
        return path_binary

    mac_binary = "/Applications/Godot.app/Contents/MacOS/Godot"
    if os.path.isfile(mac_binary):
        return mac_binary
    return None


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestFilesIniJsonGodotSmoke(unittest.TestCase):
    def test_recovered_committed_included_generation_boots_without_mixing(
        self,
    ) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        version_result = subprocess.run(
            [godot_binary, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        self.assertEqual(version_result.returncode, 0, version_result.stdout)
        if not version_result.stdout.strip().startswith("4.7.1."):
            self.skipTest(
                "Exact Godot 4.7.1 required; found "
                + version_result.stdout.strip()
            )

        interruption_script = textwrap.dedent(
            """\
            import os
            import sys

            from src.conversion import included_files as included_files_module
            from src.conversion.included_files import IncludedFilesConverter

            gm_path, godot_path = sys.argv[1:]

            def stop_after_phase(phase: str) -> None:
                if phase == "generation-committed":
                    os._exit(86)

            included_files_module._after_included_transaction_phase = stop_after_phase
            IncludedFilesConverter(
                gm_path,
                godot_path,
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                max_workers=1,
            ).convert_all()
            """
        )
        smoke_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
            const IncludedRegistry = preload("res://gm2godot/gml_included_file_registry.gd")

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _read_included_text(logical_path):
            \tvar handle = GMRuntime.gml_file_text_open_read(logical_path)
            \tvar value = GMRuntime.gml_file_text_read_string(handle)
            \tGMRuntime.gml_file_text_close(handle)
            \treturn value

            func _ready():
            \tif not _check(IncludedRegistry.gml_included_file_registry_format_version() == 2, "recovered registry format mismatch"):
            \t\treturn
            \tvar entries = IncludedRegistry.gml_included_file_registry_entries()
            \tif not _check(entries is Array and entries.size() == 2, "recovered registry did not describe exactly the new generation"):
            \t\treturn
            \tvar logical_paths = []
            \tfor entry in entries:
            \t\tvar logical_path = str(entry.get("logical_path", ""))
            \t\tvar assigned_path = str(entry.get("assigned_path", ""))
            \t\tvar packaged_path = "res://included_files/" + assigned_path
            \t\tlogical_paths.append(logical_path)
            \t\tif not _check(bool(entry.get("emitted", false)), "registry advertised a non-emitted Included File"):
            \t\t\treturn
            \t\tif not _check(assigned_path == logical_path, "unexpected recovered path assignment"):
            \t\t\treturn
            \t\tif not _check(FileAccess.file_exists(packaged_path), "registry advertised an absent Included File"):
            \t\t\treturn
            \t\tif not _check(FileAccess.get_size(packaged_path) == int(entry.get("byte_count", -1)), "registry byte receipt mismatched its payload"):
            \t\t\treturn
            \t\tif not _check(FileAccess.get_sha256(packaged_path).to_lower() == str(entry.get("content_sha256", "")).to_lower(), "registry hash receipt mismatched its payload"):
            \t\t\treturn
            \tlogical_paths.sort()
            \tif not _check(logical_paths == ["new_only.txt", "shared.txt"], "registry exposed an old or incomplete generation"):
            \t\treturn
            \tif not _check(not FileAccess.file_exists("res://included_files/old_only.txt"), "old generation payload remained public"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("old_only.txt", false) == "user://gm2godot/old_only.txt", "old logical path resolved to packaged data"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_file_exists("old_only.txt"), "old logical path remained readable"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("new_only.txt", false) == "res://included_files/new_only.txt", "new-only logical path did not resolve through the recovered registry"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("shared.txt", false) == "res://included_files/shared.txt", "updated logical path did not resolve through the recovered registry"):
            \t\treturn
            \tif not _check(_read_included_text("new_only.txt") == "NEW_ONLY_GENERATION", "new-only payload mismatch"):
            \t\treturn
            \tif not _check(_read_included_text("shared.txt") == "NEW_SHARED_GENERATION", "shared payload came from the old generation"):
            \t\treturn
            \tif not _check(not FileAccess.file_exists("res://.gm2godot-included-files-transaction.json"), "recovery journal remained at runtime"):
            \t\treturn
            \tif not _check(not FileAccess.file_exists("res://.gm2godot-included-files-commit.json"), "commit marker remained at runtime"):
            \t\treturn

            \tprint("RECOVERED_INCLUDED_GENERATION_GODOT_OK")
            \tget_tree().quit(0)
            """
        )
        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            gm_project_dir = workspace / "gamemaker"
            datafiles_dir = gm_project_dir / "datafiles"
            project_dir = workspace / "godot"
            _write_text(datafiles_dir / "old_only.txt", "OLD_ONLY_GENERATION\n")
            _write_text(datafiles_dir / "shared.txt", "OLD_SHARED_GENERATION\n")

            recovery_logs: list[str] = []
            converter = IncludedFilesConverter(
                os.fspath(gm_project_dir),
                os.fspath(project_dir),
                log_callback=recovery_logs.append,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                max_workers=1,
            )
            converter.convert_all()

            (datafiles_dir / "old_only.txt").unlink()
            _write_text(datafiles_dir / "shared.txt", "NEW_SHARED_GENERATION\n")
            _write_text(datafiles_dir / "new_only.txt", "NEW_ONLY_GENERATION\n")

            project_root = Path(__file__).resolve().parents[1]
            environment = os.environ.copy()
            existing_python_path = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = (
                os.fspath(project_root)
                if not existing_python_path
                else os.fspath(project_root)
                + os.pathsep
                + existing_python_path
            )
            interrupted = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    interruption_script,
                    os.fspath(gm_project_dir),
                    os.fspath(project_dir),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
                env=environment,
                cwd=project_root,
            )
            self.assertEqual(interrupted.returncode, 86, interrupted.stdout)

            published_root = project_dir / "included_files"
            published_registry = (
                project_dir / "gm2godot" / "gml_included_file_registry.gd"
            )

            def published_snapshot() -> tuple[
                tuple[int, int],
                dict[str, bytes],
                tuple[int, int],
                bytes,
            ]:
                root_stat = published_root.stat()
                registry_stat = published_registry.stat()
                files = {
                    path.relative_to(published_root).as_posix(): path.read_bytes()
                    for path in published_root.rglob("*")
                    if path.is_file()
                }
                return (
                    (root_stat.st_dev, root_stat.st_ino),
                    files,
                    (registry_stat.st_dev, registry_stat.st_ino),
                    published_registry.read_bytes(),
                )

            committed_snapshot = published_snapshot()
            self.assertEqual(
                committed_snapshot[1],
                {
                    "new_only.txt": b"NEW_ONLY_GENERATION\n",
                    "shared.txt": b"NEW_SHARED_GENERATION\n",
                },
            )
            self.assertIn(b'"logical_path": "new_only.txt"', committed_snapshot[3])
            self.assertIn(b'"logical_path": "shared.txt"', committed_snapshot[3])
            self.assertNotIn(b'"logical_path": "old_only.txt"', committed_snapshot[3])
            self.assertTrue(
                os.path.lexists(
                    project_dir
                    / ".gm2godot-included-files-transaction.json"
                )
            )
            self.assertTrue(
                os.path.lexists(
                    project_dir / ".gm2godot-included-files-commit.json"
                )
            )

            recovery_logs.clear()
            converter.convert_all()
            self.assertTrue(
                any(message.startswith("Recovered: ") for message in recovery_logs),
                recovery_logs,
            )
            self.assertEqual(published_snapshot(), committed_snapshot)
            self.assertFalse(
                os.path.lexists(
                    project_dir
                    / ".gm2godot-included-files-transaction.json"
                )
            )
            self.assertFalse(
                os.path.lexists(
                    project_dir / ".gm2godot-included-files-commit.json"
                )
            )

            recovery_logs.clear()
            converter.convert_all()
            self.assertEqual(published_snapshot(), committed_snapshot)
            self.assertFalse(
                any(message.startswith("Recovered: ") for message in recovery_logs),
                recovery_logs,
            )

            _write_text(
                project_dir / "project.godot",
                textwrap.dedent(
                    f"""\
                    [application]
                    config/name="GM2Godot Recovery {workspace.name}"
                    """
                ),
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            result = subprocess.run(
                [
                    godot_binary,
                    "--headless",
                    "--path",
                    str(project_dir),
                    "smoke.tscn",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "RECOVERED_INCLUDED_GENERATION_GODOT_OK",
            result.stdout,
        )

    def test_included_files_fail_closed_while_transaction_journal_exists(
        self,
    ) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        version_result = subprocess.run(
            [godot_binary, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        self.assertEqual(version_result.returncode, 0, version_result.stdout)
        if not version_result.stdout.strip().startswith("4.7.1."):
            self.skipTest(
                "Exact Godot 4.7.1 required; found "
                + version_result.stdout.strip()
            )

        smoke_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
            const IncludedRegistry = preload("res://gm2godot/gml_included_file_registry.gd")

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tif not _check(IncludedRegistry.gml_included_file_registry_format_version() == 1, "registry was not downgraded to format v1"):
            \t\treturn
            \tif not _check(FileAccess.file_exists("res://included_files/packaged.txt"), "packaged file fixture is missing"):
            \t\treturn
            \tif not _check(DirAccess.dir_exists_absolute("res://included_files/packaged_folder"), "packaged directory fixture is missing"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Packaged.txt", false) == "user://gm2godot/Packaged.txt", "transaction exposed a packaged file"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_file_exists("Packaged.txt"), "transaction made a packaged file readable"):
            \t\treturn
            \tif not _check(GMRuntime._gml_file_resolve_path("Packaged Folder", false, true) == "user://gm2godot/Packaged Folder", "transaction exposed a packaged directory"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_directory_exists("Packaged Folder"), "transaction made a packaged directory readable"):
            \t\treturn

            \tprint("INCLUDED_FILE_JOURNAL_FAIL_CLOSED_OK")
            \tget_tree().quit(0)
            """
        )
        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node"]
            script = ExtResource("smoke_script")
            """
        )

        for journal_kind in ("file", "directory"):
            with self.subTest(journal_kind=journal_kind):
                with tempfile.TemporaryDirectory() as tmp:
                    workspace = Path(tmp)
                    project_dir = workspace / "godot"
                    _write_text(
                        project_dir / "included_files" / "packaged.txt",
                        "packaged file\n",
                    )
                    _write_text(
                        project_dir
                        / "included_files"
                        / "packaged_folder"
                        / "Nested.txt",
                        "nested packaged file\n",
                    )

                    registry_path = (
                        project_dir
                        / "gm2godot"
                        / "gml_included_file_registry.gd"
                    )
                    _write_text(
                        registry_path,
                        textwrap.dedent(
                            """\
                            extends RefCounted

                            const FORMAT_VERSION = 2
                            const INCLUDED_FILES = [
                            \t{
                            \t\t"assigned_path": "packaged.txt",
                            \t\t"canonical_path": "packaged.txt",
                            \t\t"emitted": true,
                            \t\t"logical_path": "Packaged.txt"
                            \t}
                            ]

                            static func gml_included_file_registry_format_version():
                            \treturn FORMAT_VERSION

                            static func gml_included_file_registry_entries():
                            \treturn INCLUDED_FILES
                            """
                        ),
                    )
                    registry_text = registry_path.read_text(encoding="utf-8")
                    self.assertIn("const FORMAT_VERSION = 2", registry_text)
                    registry_path.write_text(
                        registry_text.replace(
                            "const FORMAT_VERSION = 2",
                            "const FORMAT_VERSION = 1",
                            1,
                        ),
                        encoding="utf-8",
                    )

                    _write_text(
                        project_dir / "project.godot",
                        "[application]\nconfig/name=\"Journal Gate "
                        + journal_kind
                        + "\"\n",
                    )
                    write_gml_runtime(str(project_dir))
                    _write_text(project_dir / "smoke.gd", smoke_script)
                    _write_text(project_dir / "smoke.tscn", smoke_scene)

                    journal_path = (
                        project_dir
                        / ".gm2godot-included-files-transaction.json"
                    )
                    if journal_kind == "file":
                        _write_text(journal_path, "{}\n")
                    else:
                        journal_path.mkdir()

                    result = subprocess.run(
                        [
                            godot_binary,
                            "--headless",
                            "--path",
                            str(project_dir),
                            "smoke.tscn",
                        ],
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=30,
                    )

                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn(
                    "INCLUDED_FILE_JOURNAL_FAIL_CLOSED_OK",
                    result.stdout,
                )

    def test_large_included_file_first_access_uses_startup_prewarm(
        self,
    ) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        version_result = subprocess.run(
            [godot_binary, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        self.assertEqual(version_result.returncode, 0, version_result.stdout)
        if not version_result.stdout.strip().startswith("4.7.1."):
            self.skipTest(
                "Exact Godot 4.7.1 required; found "
                + version_result.stdout.strip()
            )

        payload_size = 64 * 1024 * 1024
        smoke_script = textwrap.dedent(
            f"""\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")
            const PAYLOAD_SIZE = {payload_size}

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tvar before = GMRuntime.gml_included_file_integrity_status()
            \tif not _check(bool(before.get("registry_available", false)), "Included File registry was unavailable"):
            \t\treturn
            \tif not _check(bool(before.get("requires_content_receipts", false)), "format-v2 receipts were not required"):
            \t\treturn
            \tif not _check(bool(before.get("integrity_established", false)), "startup prewarm did not establish generation integrity"):
            \t\treturn
            \tif not _check(int(before.get("entry_count", -1)) == 1 and int(before.get("verified_count", -1)) == 1, "startup prewarm did not verify exactly one entry"):
            \t\treturn
            \tif not _check(int(before.get("hash_attempts", -1)) == 1, "startup prewarm did not perform exactly one hash"):
            \t\treturn
            \tif not _check(int(before.get("hash_payload_bytes", -1)) == PAYLOAD_SIZE, "startup prewarm did not hash the complete 64 MiB payload"):
            \t\treturn
            \tif not _check(int(before.get("hash_elapsed_usec", -1)) > 0, "startup hash duration was not recorded"):
            \t\treturn

            \tvar caller_started_usec = Time.get_ticks_usec()
            \tif not _check(GMRuntime.gml_file_resolve_path("Large Payload.bin", false) == "res://included_files/large_payload.bin", "exact logical path did not resolve"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("LARGE PAYLOAD.BIN", false) == "res://included_files/large_payload.bin", "canonical path did not resolve"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_exists("Large Payload.bin") and GMRuntime.gml_file_exists("LARGE PAYLOAD.BIN"), "file_exists did not share exact/canonical resolution"):
            \t\treturn
            \tvar reader = GMRuntime.gml_file_text_open_read("Large Payload.bin")
            \tif not _check(GMRuntime.gml_file_text_read_string(reader) == "FIRST LINE", "text read did not use the verified payload"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(reader)
            \tvar caller_lookup_usec = Time.get_ticks_usec() - caller_started_usec

            \tvar buffer_started_usec = Time.get_ticks_usec()
            \tvar loaded = GMRuntime.gml_buffer_load("LARGE PAYLOAD.BIN")
            \tvar buffer_load_usec = Time.get_ticks_usec() - buffer_started_usec
            \tif not _check(GMRuntime.gml_buffer_exists(loaded), "buffer_load did not use the verified payload"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_get_used_size(loaded) == PAYLOAD_SIZE, "buffer_load size mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_peek(loaded, 0, 1) == 70, "buffer_load payload mismatch"):
            \t\treturn
            \tGMRuntime.gml_buffer_delete(loaded)

            \tvar after = GMRuntime.gml_included_file_integrity_status()
            \tif not _check(int(after.get("hash_attempts", -1)) == int(before.get("hash_attempts", -2)), "normal first access started another checksum"):
            \t\treturn
            \tif not _check(int(after.get("hash_payload_bytes", -1)) == int(before.get("hash_payload_bytes", -2)), "normal first access read payload bytes for integrity"):
            \t\treturn
            \tif not _check(int(after.get("hash_elapsed_usec", -1)) == int(before.get("hash_elapsed_usec", -2)), "normal first access spent time hashing"):
            \t\treturn

            \tprint(
            \t\t"INCLUDED_FILE_FIRST_ACCESS_OK caller_lookup_usec=",
            \t\tcaller_lookup_usec,
            \t\t" buffer_load_usec=",
            \t\tbuffer_load_usec,
            \t\t" startup_hash_usec=",
            \t\tbefore.get("hash_elapsed_usec", -1),
            \t)
            \tget_tree().quit(0)
            """
        )
        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            gm_project_dir = workspace / "gamemaker"
            project_dir = workspace / "godot"
            payload_path = (
                gm_project_dir / "datafiles" / "Large Payload.bin"
            )
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            with payload_path.open("wb") as payload_file:
                payload_file.write(b"FIRST LINE\n")
                payload_file.truncate(payload_size)

            IncludedFilesConverter(
                os.fspath(gm_project_dir),
                os.fspath(project_dir),
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                max_workers=1,
            ).convert_all()
            _write_text(
                project_dir / "project.godot",
                "[application]\nconfig/name=\"Included File First Access\"\n",
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            result = subprocess.run(
                [
                    godot_binary,
                    "--headless",
                    "--path",
                    str(project_dir),
                    "smoke.tscn",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=60,
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("INCLUDED_FILE_FIRST_ACCESS_OK", result.stdout)
        measurement = re.search(
            r"caller_lookup_usec=(\d+).*buffer_load_usec=(\d+).*"
            r"startup_hash_usec=(\d+)",
            result.stdout,
        )
        self.assertIsNotNone(measurement, result.stdout)
        if measurement is not None:
            caller_lookup_usec = int(measurement.group(1))
            buffer_load_usec = int(measurement.group(2))
            startup_hash_usec = int(measurement.group(3))
            self.assertLess(
                caller_lookup_usec,
                startup_hash_usec,
                (
                    caller_lookup_usec,
                    startup_hash_usec,
                    result.stdout,
                ),
            )
            if os.environ.get("GM2GODOT_REPORT_PERF") == "1":
                print(
                    "64 MiB Included File: "
                    f"startup hash {startup_hash_usec} us; "
                    f"first path/file/text access {caller_lookup_usec} us; "
                    f"buffer load {buffer_load_usec} us"
                )

    def test_same_size_pretrust_mutation_rejects_complete_generation(
        self,
    ) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        version_result = subprocess.run(
            [godot_binary, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        self.assertEqual(version_result.returncode, 0, version_result.stdout)
        if not version_result.stdout.strip().startswith("4.7.1."):
            self.skipTest(
                "Exact Godot 4.7.1 required; found "
                + version_result.stdout.strip()
            )

        smoke_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tvar status = GMRuntime.gml_included_file_integrity_status()
            \tif not _check(bool(status.get("registry_available", false)), "format-v2 registry was not parsed"):
            \t\treturn
            \tif not _check(bool(status.get("requires_content_receipts", false)), "content receipts were not required"):
            \t\treturn
            \tif not _check(not bool(status.get("integrity_established", true)), "same-size mutation established trust"):
            \t\treturn
            \tif not _check(int(status.get("entry_count", -1)) == 2, "unexpected integrity inventory"):
            \t\treturn
            \tif not _check(int(status.get("verified_count", -1)) == 0, "partial generation remained verified"):
            \t\treturn
            \tif not _check(FileAccess.file_exists("res://included_files/changed.txt") and FileAccess.file_exists("res://included_files/trusted.txt"), "loose payload fixture is incomplete"):
            \t\treturn

            \tfor logical_path in ["Changed.txt", "CHANGED.TXT", "Trusted.txt", "TRUSTED.TXT"]:
            \t\tif not _check(GMRuntime.gml_file_resolve_path(logical_path, false).begins_with("user://gm2godot/"), "untrusted exact/canonical path escaped the fail-closed user path: " + logical_path):
            \t\t\treturn
            \t\tif not _check(not GMRuntime.gml_file_exists(logical_path), "untrusted generation remained visible to file_exists: " + logical_path):
            \t\t\treturn

            \tvar reader = GMRuntime.gml_file_text_open_read("Trusted.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(reader) == "", "text read exposed another entry from the rejected generation"):
            \t\treturn
            \tvar loaded = GMRuntime.gml_buffer_load("TRUSTED.TXT")
            \tif not _check(not GMRuntime.gml_buffer_exists(loaded), "buffer_load exposed another entry from the rejected generation"):
            \t\treturn

            \tprint("INCLUDED_FILE_PRETRUST_MUTATION_REJECTED_OK")
            \tget_tree().quit(0)
            """
        )
        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            gm_project_dir = workspace / "gamemaker"
            project_dir = workspace / "godot"
            _write_text(
                gm_project_dir / "datafiles" / "Changed.txt",
                "trusted payload\n",
            )
            _write_text(
                gm_project_dir / "datafiles" / "Trusted.txt",
                "other trusted\n",
            )
            IncludedFilesConverter(
                os.fspath(gm_project_dir),
                os.fspath(project_dir),
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                max_workers=1,
            ).convert_all()

            changed_payload = (
                project_dir / "included_files" / "changed.txt"
            )
            original_size = changed_payload.stat().st_size
            changed_payload.write_text(
                "altered payload\n",
                encoding="utf-8",
            )
            self.assertEqual(changed_payload.stat().st_size, original_size)

            _write_text(
                project_dir / "project.godot",
                "[application]\nconfig/name=\"Included File Mutation\"\n",
            )
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            result = subprocess.run(
                [
                    godot_binary,
                    "--headless",
                    "--path",
                    str(project_dir),
                    "smoke.tscn",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "INCLUDED_FILE_PRETRUST_MUTATION_REJECTED_OK",
            result.stdout,
        )

    def test_untrusted_registry_does_not_expose_loose_payload(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        version_result = subprocess.run(
            [godot_binary, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        self.assertEqual(version_result.returncode, 0, version_result.stdout)
        if not version_result.stdout.strip().startswith("4.7.1."):
            self.skipTest(
                "Exact Godot 4.7.1 required; found "
                + version_result.stdout.strip()
            )

        smoke_script = textwrap.dedent(
            """\
            extends Node

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tvar status = GMRuntime.gml_included_file_integrity_status()
            \tif not _check(not bool(status.get("registry_available", true)), "missing or receiptless registry was treated as available"):
            \t\treturn
            \tif not _check(FileAccess.file_exists("res://included_files/orphan.txt"), "loose payload fixture is missing"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Orphan.txt", false) == "user://gm2godot/Orphan.txt", "untrusted registry fell through to a loose payload"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_file_exists("Orphan.txt"), "file_exists exposed a loose payload without its registry"):
            \t\treturn
            \tvar reader = GMRuntime.gml_file_text_open_read("Orphan.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(reader) == "", "text read exposed a loose payload without its registry"):
            \t\treturn
            \tvar loaded = GMRuntime.gml_buffer_load("ORPHAN.TXT")
            \tif not _check(not GMRuntime.gml_buffer_exists(loaded), "buffer_load exposed a loose payload without its registry"):
            \t\treturn

            \tprint("INCLUDED_FILE_UNTRUSTED_REGISTRY_REJECTED_OK")
            \tget_tree().quit(0)
            """
        )
        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node"]
            script = ExtResource("smoke_script")
            """
        )

        for registry_kind in ("missing", "receiptless"):
            with self.subTest(registry_kind=registry_kind):
                with tempfile.TemporaryDirectory() as tmp:
                    project_dir = Path(tmp) / "godot"
                    _write_text(
                        project_dir / "included_files" / "orphan.txt",
                        "untrusted loose payload\n",
                    )
                    _write_text(
                        project_dir / "project.godot",
                        "[application]\nconfig/name=\"Untrusted Included Registry\"\n",
                    )
                    write_gml_runtime(str(project_dir))
                    if registry_kind == "receiptless":
                        _write_text(
                            project_dir
                            / "gm2godot"
                            / "gml_included_file_registry.gd",
                            textwrap.dedent(
                                """\
                                extends RefCounted

                                const FORMAT_VERSION = 1
                                const INCLUDED_FILES = [{
                                \t"assigned_path": "orphan.txt",
                                \t"canonical_path": "orphan.txt",
                                \t"emitted": true,
                                \t"logical_path": "Orphan.txt",
                                }]

                                static func gml_included_file_registry_format_version():
                                \treturn FORMAT_VERSION

                                static func gml_included_file_registry_entries():
                                \treturn INCLUDED_FILES
                                """
                            ),
                        )
                    _write_text(project_dir / "smoke.gd", smoke_script)
                    _write_text(project_dir / "smoke.tscn", smoke_scene)

                    result = subprocess.run(
                        [
                            godot_binary,
                            "--headless",
                            "--path",
                            str(project_dir),
                            "smoke.tscn",
                        ],
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=30,
                    )

                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn(
                    "INCLUDED_FILE_UNTRUSTED_REGISTRY_REJECTED_OK",
                    result.stdout,
                )

    def test_files_ini_json_and_path_mapping(self) -> None:
        godot_binary = _find_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        version_result = subprocess.run(
            [godot_binary, "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        self.assertEqual(version_result.returncode, 0, version_result.stdout)
        if not version_result.stdout.strip().startswith("4.7.1."):
            self.skipTest(
                "Exact Godot 4.7.1 required; found "
                + version_result.stdout.strip()
            )

        smoke_script = textwrap.dedent(
            """\
            extends Node2D

            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            func _check(condition, message):
            \tif not condition:
            \t\tpush_error(str(message))
            \t\tget_tree().quit(1)
            \t\treturn false
            \treturn true

            func _ready():
            \tcall_deferred("_run")

            func _run():
            \tif not _check(GMRuntime.gml_builtin_global("working_directory").begins_with("user://"), "working_directory not user path"):
            \t\treturn
            \tif not _check(GMRuntime.gml_builtin_global("program_directory") == "res://", "program_directory mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_builtin_global("temp_directory").begins_with("user://"), "temp_directory not user path"):
            \t\treturn

            \tGMRuntime.gml_file_delete("Config/My File.txt")
            \tif not _check(GMRuntime.gml_file_resolve_path("Config/My File.txt", true) == "user://gm2godot/Config/My File.txt", "relative write path was normalized or escaped user storage"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Config/My File.txt", false) == "res://included_files/config/my_file.txt", "included text path was not normalized for packaged lookup"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Binary Data/My Bytes.bin", false) == "res://included_files/binary_data/my_bytes.bin", "nested included binary path was not normalized"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Missing Folder/Missing File.txt", false) == "user://gm2godot/Missing Folder/Missing File.txt", "missing relative read did not fall back to exact user path"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("user://explicit.txt", false) == "user://explicit.txt", "explicit user path changed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("res://included_files/config/my_file.txt", false) == "res://included_files/config/my_file.txt", "explicit resource read path changed"):
            \t\treturn

            \tGMRuntime.gml_file_delete("Read Me.txt")
            \tGMRuntime.gml_file_delete("read_me.txt")
            \tGMRuntime.gml_file_delete("READ_ME_2.TXT")
            \tGMRuntime.gml_file_delete("READ ME.TXT")
            \tGMRuntime.gml_file_delete("foo_bar")
            \tGMRuntime.gml_file_delete("Foo Bar/item.txt")
            \tGMRuntime.gml_file_delete("Ghost File.txt")
            \tif not _check(GMRuntime.gml_file_resolve_path("Read Me.txt", false) == "res://included_files/read_me_3.txt", "exact colliding logical path did not use reserved suffix"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("read_me.txt", false) == "res://included_files/read_me.txt", "canonical collision member resolved incorrectly"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("READ_ME_2.TXT", false) == "res://included_files/read_me_2.txt", "unique canonical natural suffix lookup failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("READ ME.TXT", false) == "user://gm2godot/READ ME.TXT", "ambiguous canonical lookup did not fail closed"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_file_exists("READ ME.TXT"), "ambiguous canonical lookup selected a payload"):
            \t\treturn
            \tvar collision_reader = GMRuntime.gml_file_text_open_read("Read Me.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(collision_reader) == "normalized collision", "exact collision payload mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(collision_reader)
            \tvar canonical_reader = GMRuntime.gml_file_text_open_read("read_me.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(canonical_reader) == "canonical collision", "canonical collision payload mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(canonical_reader)

            \tif not _check(GMRuntime.gml_file_resolve_path("foo_bar", false) == "res://included_files/foo_bar_2", "file/directory blocker file did not resolve to relocation"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Foo Bar/item.txt", false) == "res://included_files/foo_bar/item.txt", "file/directory blocker nested file path mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_directory_exists("Foo Bar"), "file/directory blocker directory lookup failed"):
            \t\treturn
            \tvar blocker_reader = GMRuntime.gml_file_text_open_read("foo_bar")
            \tif not _check(GMRuntime.gml_file_text_read_string(blocker_reader) == "blocking file", "relocated blocking file payload mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(blocker_reader)
            \tvar nested_reader = GMRuntime.gml_file_text_open_read("Foo Bar/item.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(nested_reader) == "nested item", "nested blocker payload mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(nested_reader)

            \tif not _check(GMRuntime.gml_file_resolve_path("Ghost File.txt", false) == "user://gm2godot/Ghost File.txt", "planned but unemitted logical path fell through to canonical payload"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_file_exists("Ghost File.txt"), "planned but unemitted logical path selected canonical payload"):
            \t\treturn
            \tGMRuntime.gml_file_delete(" Leading.txt")
            \tGMRuntime.gml_file_delete("Trailing.txt ")
            \tif not _check(GMRuntime.gml_file_resolve_path(" Leading.txt", true) == "user://gm2godot/ Leading.txt", "leading-space write path lost its literal space"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Trailing.txt ", true) == "user://gm2godot/Trailing.txt ", "trailing-space write path lost its literal space"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path(" Leading.txt", false) == "res://included_files/_leading.txt", "leading-space packaged lookup mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Trailing.txt ", false) == "res://included_files/trailing.txt_", "trailing-space packaged lookup mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_exists(" Leading.txt") and GMRuntime.gml_file_exists("Trailing.txt "), "edge-space included file not found"):
            \t\treturn
            \tvar leading_space_reader = GMRuntime.gml_file_text_open_read(" Leading.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(leading_space_reader) == "leading packaged", "leading-space included text mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(leading_space_reader)
            \tvar trailing_space_reader = GMRuntime.gml_file_text_open_read("Trailing.txt ")
            \tif not _check(GMRuntime.gml_file_text_read_string(trailing_space_reader) == "trailing packaged", "trailing-space included text mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(trailing_space_reader)

            \tvar leading_space_writer = GMRuntime.gml_file_text_open_write(" Leading.txt")
            \tGMRuntime.gml_file_text_write_string(leading_space_writer, "leading user")
            \tGMRuntime.gml_file_text_close(leading_space_writer)
            \tvar trailing_space_writer = GMRuntime.gml_file_text_open_write("Trailing.txt ")
            \tGMRuntime.gml_file_text_write_string(trailing_space_writer, "trailing user")
            \tGMRuntime.gml_file_text_close(trailing_space_writer)
            \tif not _check(GMRuntime.gml_file_resolve_path(" Leading.txt", false) == "user://gm2godot/ Leading.txt", "leading-space user override did not take precedence"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Trailing.txt ", false) == "user://gm2godot/Trailing.txt ", "trailing-space user override did not take precedence"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_delete(" Leading.txt") and GMRuntime.gml_file_delete("Trailing.txt "), "edge-space user override delete failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path(" Leading.txt", false) == "res://included_files/_leading.txt" and GMRuntime.gml_file_resolve_path("Trailing.txt ", false) == "res://included_files/trailing.txt_", "edge-space packaged files did not reappear"):
            \t\treturn

            \tif not _check(GMRuntime.gml_file_exists("Config/My File.txt"), "included file not found through mixed-case logical path"):
            \t\treturn
            \tvar included = GMRuntime.gml_file_text_open_read("Config/My File.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(included) == "included", "included text mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_text_read_real(included) == 42, "included real mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_text_eof(included), "included EOF mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(included)

            \tvar included_buffer = GMRuntime.gml_buffer_load("Binary Data/My Bytes.bin")
            \tif not _check(GMRuntime.gml_buffer_exists(included_buffer), "included binary buffer_load failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_get_used_size(included_buffer) == 5, "included binary size mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_buffer_peek(included_buffer, 0, 1) == 0 and GMRuntime.gml_buffer_peek(included_buffer, 4, 1) == 255, "included binary contents mismatch"):
            \t\treturn
            \tGMRuntime.gml_buffer_delete(included_buffer)

            \tvar override_writer = GMRuntime.gml_file_text_open_write("Config/My File.txt")
            \tGMRuntime.gml_file_text_write_string(override_writer, "user override")
            \tGMRuntime.gml_file_text_close(override_writer)
            \tif not _check(GMRuntime.gml_file_resolve_path("Config/My File.txt", false) == "user://gm2godot/Config/My File.txt", "exact user override did not take precedence"):
            \t\treturn
            \tvar override_reader = GMRuntime.gml_file_text_open_read("Config/My File.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(override_reader) == "user override", "user override content mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(override_reader)
            \tif not _check(GMRuntime.gml_file_delete("Config/My File.txt"), "user override delete failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_file_resolve_path("Config/My File.txt", false) == "res://included_files/config/my_file.txt", "packaged file did not reappear after deleting override"):
            \t\treturn

            \tif not _check(GMRuntime.gml_filename_name("save/profile.txt") == "profile", "filename_name mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_filename_ext("save/profile.txt") == ".txt", "filename_ext mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_filename_dir("save/profile.txt") == "save", "filename_dir mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_filename_path("save/profile.txt") == "save/", "filename_path mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.gml_filename_change_ext("save/profile.txt", "dat") == "save/profile.dat", "filename_change_ext mismatch"):
            \t\treturn

            \tif not _check(GMRuntime.gml_directory_create("save/nested"), "directory_create failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_directory_exists("save/nested"), "directory_exists failed"):
            \t\treturn
            \tif not _check(GMRuntime.gml_directory_destroy("save/nested"), "directory_destroy failed"):
            \t\treturn

            \tvar writer = GMRuntime.gml_file_text_open_write("save/profile.txt")
            \tGMRuntime.gml_file_text_write_string(writer, "Player")
            \tGMRuntime.gml_file_text_writeln(writer)
            \tGMRuntime.gml_file_text_write_real(writer, 12.5)
            \tGMRuntime.gml_file_text_close(writer)
            \tif not _check(GMRuntime.gml_file_exists("save/profile.txt"), "written file not found"):
            \t\treturn
            \tvar reader = GMRuntime.gml_file_text_open_read("save/profile.txt")
            \tif not _check(GMRuntime.gml_file_text_read_string(reader) == "Player", "written string mismatch"):
            \t\treturn
            \tif not _check(abs(GMRuntime.gml_file_text_read_real(reader) - 12.5) < 0.0001, "written real mismatch"):
            \t\treturn
            \tGMRuntime.gml_file_text_close(reader)
            \tif not _check(GMRuntime.gml_file_delete("save/profile.txt"), "file_delete failed"):
            \t\treturn
            \tif not _check(not GMRuntime.gml_file_exists("save/profile.txt"), "deleted file still exists"):
            \t\treturn

            \tGMRuntime.gml_ini_open("save/settings.ini")
            \tGMRuntime.gml_ini_write_string("audio", "device", "headphones")
            \tGMRuntime.gml_ini_write_real("audio", "volume", 0.75)
            \tif not _check(GMRuntime.gml_ini_section_exists("audio"), "ini section missing"):
            \t\treturn
            \tif not _check(GMRuntime.gml_ini_key_exists("audio", "volume"), "ini key missing"):
            \t\treturn
            \tif not _check(GMRuntime.gml_ini_read_string("audio", "device", "default") == "headphones", "ini string mismatch"):
            \t\treturn
            \tif not _check(abs(GMRuntime.gml_ini_read_real("audio", "volume", 1.0) - 0.75) < 0.0001, "ini real mismatch"):
            \t\treturn
            \tGMRuntime.gml_ini_key_delete("audio", "device")
            \tif not _check(not GMRuntime.gml_ini_key_exists("audio", "device"), "ini key delete failed"):
            \t\treturn
            \tGMRuntime.gml_ini_close()

            \tGMRuntime.gml_ini_open("save/settings.ini")
            \tif not _check(abs(GMRuntime.gml_ini_read_real("audio", "volume", 1.0) - 0.75) < 0.0001, "ini persisted real mismatch"):
            \t\treturn
            \tGMRuntime.gml_ini_section_delete("audio")
            \tif not _check(not GMRuntime.gml_ini_section_exists("audio"), "ini section delete failed"):
            \t\treturn
            \tGMRuntime.gml_ini_close()

            \tvar list = GMRuntime.gml_ds_list_create()
            \tGMRuntime.gml_ds_list_add(list, [1, GMRuntime.gml_undefined(), NAN, INF])
            \tvar map = GMRuntime.gml_ds_map_create()
            \tGMRuntime.gml_ds_map_set(map, "name", "Ada")
            \tGMRuntime.gml_ds_map_set(map, "items", list)
            \tvar encoded = GMRuntime.gml_json_encode(map)
            \tvar decoded = GMRuntime.gml_json_decode(encoded)
            \tif not _check(decoded["name"] == "Ada", "json string mismatch"):
            \t\treturn
            \tif not _check(decoded["items"][0] == 1, "json list number mismatch"):
            \t\treturn
            \tif not _check(decoded["items"][1] == null, "json undefined mismatch"):
            \t\treturn
            \tif not _check(decoded["items"][2] == null, "json NaN mismatch"):
            \t\treturn
            \tif not _check(decoded["items"][3] == null, "json infinity mismatch"):
            \t\treturn
            \tif not _check(GMRuntime.is_undefined(GMRuntime.gml_json_decode("{bad")), "json invalid should be undefined"):
            \t\treturn

            \tprint("FILES_INI_JSON_SMOKE_OK")
            \tget_tree().quit(0)
            """
        )

        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node2D"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            gm_project_dir = workspace / "gamemaker"
            project_dir = workspace / "godot"
            _write_text(
                gm_project_dir / "RuntimeParity.yyp",
                json.dumps(
                    {
                        "IncludedFiles": [
                            {
                                "name": "My File.txt",
                                "filePath": "datafiles/Config",
                            },
                            {
                                "name": "My Bytes.bin",
                                "filePath": "datafiles/Binary Data",
                            },
                            {
                                "name": " Leading.txt",
                                "filePath": "datafiles",
                            },
                            {
                                "name": "Trailing.txt ",
                                "filePath": "datafiles",
                            },
                            {
                                "name": "Ghost File.txt",
                                "filePath": "datafiles",
                            },
                        ]
                    }
                ),
            )
            _write_text(
                gm_project_dir / "datafiles" / "Config" / "My File.txt",
                "included\n42\n",
            )
            _write_text(
                gm_project_dir / "datafiles" / " Leading.txt",
                "leading packaged\n",
            )
            _write_text(
                gm_project_dir / "datafiles" / "Trailing.txt ",
                "trailing packaged\n",
            )
            collision_payloads = {
                "Read Me.txt": "normalized collision\n",
                "read_me.txt": "canonical collision\n",
                "read_me_2.txt": "natural suffix\n",
                "foo_bar": "blocking file\n",
                "Foo Bar/item.txt": "nested item\n",
                "ghost_file.txt": "unavailable alias must not leak\n",
            }
            for relative_path, payload in collision_payloads.items():
                _write_text(
                    gm_project_dir
                    / "datafiles"
                    / Path(*relative_path.split("/")),
                    payload,
                )
            binary_source = (
                gm_project_dir
                / "datafiles"
                / "Binary Data"
                / "My Bytes.bin"
            )
            binary_source.parent.mkdir(parents=True, exist_ok=True)
            binary_source.write_bytes(bytes((0, 1, 127, 128, 255)))

            included_files_converter = IncludedFilesConverter(
                os.fspath(gm_project_dir),
                os.fspath(project_dir),
                log_callback=lambda _message: None,
                progress_callback=lambda _value: None,
                conversion_running=lambda: True,
                max_workers=1,
            )
            included_files_converter.convert_all()
            published_root = project_dir / "included_files"
            published_registry = (
                project_dir
                / "gm2godot"
                / "gml_included_file_registry.gd"
            )
            published_root_identity = published_root.stat().st_ino
            published_registry_identity = published_registry.stat().st_ino
            published_registry_content = published_registry.read_bytes()
            included_files_converter.convert_all()
            self.assertEqual(published_root.stat().st_ino, published_root_identity)
            self.assertEqual(
                published_registry.stat().st_ino,
                published_registry_identity,
            )
            self.assertEqual(
                published_registry.read_bytes(),
                published_registry_content,
            )

            self.assertEqual(
                (
                    project_dir
                    / "included_files"
                    / "config"
                    / "my_file.txt"
                ).read_text(encoding="utf-8"),
                "included\n42\n",
            )
            self.assertEqual(
                (
                    project_dir
                    / "included_files"
                    / "binary_data"
                    / "my_bytes.bin"
                ).read_bytes(),
                bytes((0, 1, 127, 128, 255)),
            )
            self.assertEqual(
                (project_dir / "included_files" / "_leading.txt").read_text(
                    encoding="utf-8"
                ),
                "leading packaged\n",
            )
            self.assertEqual(
                (project_dir / "included_files" / "trailing.txt_").read_text(
                    encoding="utf-8"
                ),
                "trailing packaged\n",
            )
            self.assertEqual(
                (project_dir / "included_files" / "read_me_3.txt").read_text(
                    encoding="utf-8"
                ),
                "normalized collision\n",
            )
            self.assertEqual(
                (project_dir / "included_files" / "foo_bar_2").read_text(
                    encoding="utf-8"
                ),
                "blocking file\n",
            )
            self.assertEqual(
                (
                    project_dir
                    / "included_files"
                    / "foo_bar"
                    / "item.txt"
                ).read_text(encoding="utf-8"),
                "nested item\n",
            )
            _write_text(project_dir / "project.godot", "[application]\n")
            write_gml_runtime(str(project_dir))
            _write_text(project_dir / "smoke.gd", smoke_script)
            _write_text(project_dir / "smoke.tscn", smoke_scene)

            result = subprocess.run(
                [godot_binary, "--headless", "--path", str(project_dir), "smoke.tscn"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("FILES_INI_JSON_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
