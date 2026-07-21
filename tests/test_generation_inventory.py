from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, cast
from unittest.mock import patch

from src import cli
from src.conversion import generation_inventory as inventory_module
from src.conversion.conversion_manifest import (
    CONVERSION_ATTEMPT_RELATIVE_PATH,
    CONVERSION_MANIFEST_RELATIVE_PATH,
)
from src.conversion.generation_inventory import (
    GenerationInventory,
    GenerationInventoryEntry,
    GenerationInventoryOwner,
    capture_generation_inventory,
    generation_output_kind,
    generation_output_owner,
    migrate_generation_inventory,
    stage_inventory_carry_forward,
    validate_generation_inventory,
    validate_staged_generation_inventory,
)
from src.conversion.managed_output_workspace import (
    DESTINATION_LOCK_NAME,
    WORKSPACE_PARENT_NAME,
    ManagedOutputWorkspace,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "golden" / "basic_scripts"
_DIGEST_A = "sha256:" + ("a" * 64)
_DIGEST_B = "sha256:" + ("b" * 64)


class TestGenerationInventory(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(
            self.temp_dir,
            onexc=self._retry_windows_read_only_cleanup,
        )

    @staticmethod
    def _retry_windows_read_only_cleanup(
        function: Callable[..., object],
        path: str,
        error: BaseException,
    ) -> None:
        if not isinstance(error, PermissionError):
            raise error
        path_stat = os.lstat(path)
        os.chmod(path, stat.S_IMODE(path_stat.st_mode) | stat.S_IWRITE)
        function(path)

    @staticmethod
    def _entry(
        path: str,
        *,
        digest: str = _DIGEST_A,
        byte_count: int = 1,
        mode: int = 0o644,
    ) -> GenerationInventoryEntry:
        normalized = path.replace("\\", "/")
        return GenerationInventoryEntry(
            path=path,
            kind=generation_output_kind(normalized),
            owner=generation_output_owner(normalized),
            byte_count=byte_count,
            sha256=digest,
            mode=mode,
        )

    def test_serialization_is_immutable_sorted_and_separator_independent(self) -> None:
        forward = GenerationInventory(
            (
                self._entry("scripts/zeta.gd", digest=_DIGEST_B),
                self._entry(r"scripts\alpha.gd"),
            )
        )
        reverse = GenerationInventory(tuple(reversed(forward.entries)))

        self.assertEqual(forward, reverse)
        self.assertEqual(forward.to_bytes(), reverse.to_bytes())
        self.assertEqual(
            [entry.path for entry in forward.entries],
            ["scripts/alpha.gd", "scripts/zeta.gd"],
        )
        with self.assertRaisesRegex(AttributeError, "cannot assign"):
            cast(object, forward.entries[0]).path = "scripts/replaced.gd"  # type: ignore[attr-defined]

    def test_parallel_enumeration_order_and_worker_count_are_byte_identical(
        self,
    ) -> None:
        relative_payloads = {
            "project.godot": b"[application]\nconfig/name=\"Inventory\"\n",
            "scripts/a.gd": b"extends Node\n",
            "scripts/b.gd": b"extends Node2D\n",
            "sprites/icon/image.png": b"\x89PNG\r\n\x1a\ninventory",
            "gm2godot/gml_runtime.gd": b"extends RefCounted\n",
        }

        def generate(root: Path, workers: int, reverse: bool) -> None:
            items = list(relative_payloads.items())
            if reverse:
                items.reverse()

            def write(item: tuple[str, bytes]) -> None:
                relative_path, content = item
                output = root / relative_path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(content)

            with ThreadPoolExecutor(max_workers=workers) as executor:
                tuple(executor.map(write, items))

        single = self.temp_dir / "single"
        parallel = self.temp_dir / "parallel"
        single.mkdir()
        parallel.mkdir()
        generate(single, 1, False)
        generate(parallel, 4, True)

        self.assertEqual(
            capture_generation_inventory(single).to_bytes(),
            capture_generation_inventory(parallel).to_bytes(),
        )

    def test_capture_is_complete_and_excludes_private_or_unrelated_state(
        self,
    ) -> None:
        destination = self.temp_dir / "project"
        (destination / "scripts").mkdir(parents=True)
        (destination / "gm2godot").mkdir()
        (destination / ".godot").mkdir()
        (destination / WORKSPACE_PARENT_NAME).mkdir()
        project_bytes = b"[application]\nconfig/name=\"Inventory\"\n"
        script_bytes = b"extends Node\n"
        report_bytes = b"{}\n"
        (destination / "project.godot").write_bytes(project_bytes)
        (destination / "scripts" / "main.gd").write_bytes(script_bytes)
        (destination / "gm2godot" / "architecture_policy.json").write_bytes(
            report_bytes
        )
        (destination / CONVERSION_MANIFEST_RELATIVE_PATH).write_text(
            "{}\n",
            encoding="utf-8",
        )
        (destination / CONVERSION_ATTEMPT_RELATIVE_PATH).write_text(
            "{}\n",
            encoding="utf-8",
        )
        (
            destination
            / "gm2godot"
            / ".conversion_manifest.json.private.tmp"
        ).write_bytes(b"private\n")
        (
            destination
            / "gm2godot"
            / ".gm2godot-conversion-generation.json"
        ).write_bytes(b"private\n")
        (destination / DESTINATION_LOCK_NAME).write_bytes(b"lock\n")
        (destination / ".godot" / "editor-state").write_bytes(b"private\n")
        (destination / "user-sentinel.txt").write_bytes(b"user-owned\n")

        inventory = capture_generation_inventory(destination)
        by_path = inventory.by_path()

        self.assertEqual(
            set(by_path),
            {
                "project.godot",
                "scripts/main.gd",
                "gm2godot/architecture_policy.json",
            },
        )
        self.assertEqual(by_path["project.godot"].owner.owner_class, "shared_owner")
        self.assertEqual(
            by_path["project.godot"].owner.name,
            "project_configuration",
        )
        self.assertEqual(
            by_path["scripts/main.gd"].owner,
            GenerationInventoryOwner("converter_step", "scripts"),
        )
        self.assertEqual(
            by_path["scripts/main.gd"].byte_count,
            len(script_bytes),
        )
        self.assertEqual(
            by_path["scripts/main.gd"].sha256,
            "sha256:" + hashlib.sha256(script_bytes).hexdigest(),
        )

    def test_stage_carries_disabled_and_shared_owners_then_validates_desired(
        self,
    ) -> None:
        destination = self.temp_dir / "project"
        (destination / "scripts").mkdir(parents=True)
        (destination / "sprites" / "hero").mkdir(parents=True)
        (destination / "gm2godot").mkdir()
        (destination / "project.godot").write_bytes(b"[application]\n")
        (destination / "scripts" / "old.gd").write_bytes(b"old script\n")
        (destination / "sprites" / "hero" / "hero.png").write_bytes(
            b"sprite bytes\n"
        )
        (destination / "gm2godot" / "gml_runtime.gd").write_bytes(
            b"runtime bytes\n"
        )
        previous = capture_generation_inventory(destination)

        with ManagedOutputWorkspace.open(destination) as workspace:
            receipts = stage_inventory_carry_forward(
                workspace,
                previous,
                enabled_converters=("scripts",),
            )
            receipt_paths = {receipt.relative_path for receipt in receipts}
            self.assertEqual(
                receipt_paths,
                {
                    "project.godot",
                    "sprites/hero/hero.png",
                    "gm2godot/gml_runtime.gd",
                },
            )
            staged_root = Path(workspace.stage_path)
            (staged_root / "scripts").mkdir()
            (staged_root / "scripts" / "old.gd").write_bytes(b"new script\n")
            desired = capture_generation_inventory(
                staged_root,
                previous_inventory=previous,
                enabled_converters=("scripts",),
            )
            validate_staged_generation_inventory(workspace, desired)

        self.assertEqual(
            (destination / "scripts" / "old.gd").read_bytes(),
            b"old script\n",
        )

    def test_disabled_owner_change_or_new_output_is_rejected(self) -> None:
        destination = self.temp_dir / "project"
        (destination / "sprites").mkdir(parents=True)
        sprite = destination / "sprites" / "hero.png"
        sprite.write_bytes(b"old sprite\n")
        previous = capture_generation_inventory(destination)
        sprite.write_bytes(b"new sprite\n")

        with self.assertRaisesRegex(OSError, "not carried forward exactly"):
            capture_generation_inventory(
                destination,
                previous_inventory=previous,
                enabled_converters=("scripts",),
            )

        sprite.write_bytes(b"old sprite\n")
        (destination / "sprites" / "new.png").write_bytes(b"new\n")
        with self.assertRaisesRegex(OSError, "unexpectedly produced"):
            capture_generation_inventory(
                destination,
                previous_inventory=previous,
                enabled_converters=("scripts",),
            )

    def test_validation_rejects_same_size_mutation_with_restored_timestamp(
        self,
    ) -> None:
        destination = self.temp_dir / "project"
        (destination / "scripts").mkdir(parents=True)
        output = destination / "scripts" / "main.gd"
        output.write_bytes(b"original bytes")
        frozen = capture_generation_inventory(destination)
        original_stat = output.stat()
        output.write_bytes(b"mutated! bytes")
        self.assertEqual(output.stat().st_size, original_stat.st_size)
        os.utime(
            output,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )

        with self.assertRaisesRegex(OSError, "changed"):
            validate_generation_inventory(destination, frozen)

    def test_staged_validation_rehashes_every_inventory_digest(self) -> None:
        destination = self.temp_dir / "project"
        (destination / "scripts").mkdir(parents=True)
        source = destination / "scripts" / "main.gd"
        source.write_bytes(b"original bytes")
        previous = capture_generation_inventory(destination)

        with ManagedOutputWorkspace.open(destination) as workspace:
            stage_inventory_carry_forward(
                workspace,
                previous,
                enabled_converters=(),
            )
            desired = capture_generation_inventory(workspace.stage_path)
            staged = Path(workspace.stage_path) / "scripts" / "main.gd"
            staged_stat = staged.stat()
            staged.write_bytes(b"mutated! bytes")
            os.utime(
                staged,
                ns=(staged_stat.st_atime_ns, staged_stat.st_mtime_ns),
            )

            with self.assertRaisesRegex(OSError, "changed"):
                validate_staged_generation_inventory(workspace, desired)

    def test_legacy_manifest_migration_completes_unchanged_managed_roots(
        self,
    ) -> None:
        destination = self.temp_dir / "project"
        (destination / "scripts").mkdir(parents=True)
        (destination / "sprites").mkdir()
        (destination / "gm2godot").mkdir()
        (destination / "reports" / "gm2godot").mkdir(parents=True)
        script = destination / "scripts" / "main.gd"
        sprite = destination / "sprites" / "hero.png"
        external_report = (
            destination / "reports" / "gm2godot" / "conversion_diagnostics.json"
        )
        script.write_bytes(b"script\n")
        sprite.write_bytes(b"sprite\n")
        external_report.write_bytes(b"{}\n")
        legacy = {
            "format_version": 2,
            "conversion": {"state": "success"},
            "generated_files": [
                {
                    "path": "scripts/main.gd",
                    "kind": "gdscript",
                    "sha256": (
                        "sha256:" + hashlib.sha256(script.read_bytes()).hexdigest()
                    ),
                },
                {
                    "path": "gm2godot/conversion_manifest.json",
                    "kind": "manifest",
                    "sha256": "self",
                },
                {
                    "path": "reports/gm2godot/conversion_diagnostics.json",
                    "kind": "report",
                    "sha256": "sha256:" + ("f" * 64),
                },
            ],
        }
        (destination / CONVERSION_MANIFEST_RELATIVE_PATH).write_text(
            json.dumps(legacy, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        migrated = migrate_generation_inventory(destination)

        self.assertEqual(
            set(migrated.by_path()),
            {"scripts/main.gd", "sprites/hero.png"},
        )
        self.assertEqual(external_report.read_bytes(), b"{}\n")

    def test_inventory_payload_rejects_malformed_escaping_and_colliding_entries(
        self,
    ) -> None:
        valid_entry = self._entry("scripts/main.gd").to_dict()
        cases: tuple[dict[str, object], ...] = (
            {**valid_entry, "path": "/absolute.gd"},
            {**valid_entry, "path": "scripts/../escape.gd"},
            {**valid_entry, "path": r"C:\escape.gd"},
            {**valid_entry, "byte_count": (1 << 63)},
            {**valid_entry, "sha256": "sha256:not-a-digest"},
            {**valid_entry, "mode": 0o10000},
            {
                **valid_entry,
                "owner": {"class": [], "name": "scripts"},
            },
        )
        for entry in cases:
            with self.subTest(entry=entry):
                with self.assertRaises(OSError):
                    GenerationInventory.from_value(
                        {
                            "format_version": 1,
                            "entries": [entry],
                        }
                    )

        with self.assertRaisesRegex(ValueError, "case-insensitively"):
            GenerationInventory(
                (
                    self._entry("scripts/Main.gd"),
                    self._entry("scripts/main.gd"),
                )
            )
        with self.assertRaisesRegex(ValueError, "structurally ambiguous"):
            GenerationInventory(
                (
                    self._entry("scripts/Tree"),
                    self._entry("scripts/tree/leaf.gd"),
                )
            )

    def test_oversized_legacy_manifest_is_rejected_before_parsing(self) -> None:
        destination = self.temp_dir / "project"
        artifact_directory = destination / "gm2godot"
        artifact_directory.mkdir(parents=True)
        manifest = artifact_directory / "conversion_manifest.json"
        manifest.write_bytes(b"x" * 257)

        with (
            patch.object(
                inventory_module,
                "GENERATION_INVENTORY_MAX_BYTES",
                256,
            ),
            self.assertRaisesRegex(OSError, "oversized"),
        ):
            migrate_generation_inventory(destination)

        self.assertEqual(manifest.read_bytes(), b"x" * 257)

    def test_legacy_migration_rejects_ambiguous_or_nonfinite_json(self) -> None:
        destination = self.temp_dir / "project"
        artifact_directory = destination / "gm2godot"
        artifact_directory.mkdir(parents=True)
        manifest = artifact_directory / "conversion_manifest.json"
        malformed_values = (
            (
                b'{"format_version":2,"format_version":2,'
                b'"generated_files":[]}\n'
            ),
            (
                b'{"format_version":2,"generated_files":[],'
                b'"unsupported":NaN}\n'
            ),
        )

        for content in malformed_values:
            with self.subTest(content=content):
                manifest.write_bytes(content)
                with self.assertRaisesRegex(OSError, "Invalid format-v2"):
                    migrate_generation_inventory(destination)
                self.assertEqual(manifest.read_bytes(), content)

    @unittest.skipUnless(os.name == "posix", "POSIX links are required")
    def test_redirected_and_multiply_linked_entries_preserve_external_sentinel(
        self,
    ) -> None:
        external = self.temp_dir / "external"
        external.mkdir()
        sentinel = external / "sentinel.gd"
        sentinel.write_bytes(b"external sentinel\n")

        redirected = self.temp_dir / "redirected"
        (redirected / "scripts").mkdir(parents=True)
        (redirected / "scripts" / "link").symlink_to(sentinel)
        with self.assertRaisesRegex(OSError, "redirected"):
            capture_generation_inventory(redirected)
        self.assertEqual(sentinel.read_bytes(), b"external sentinel\n")

        linked = self.temp_dir / "linked"
        (linked / "scripts").mkdir(parents=True)
        os.link(sentinel, linked / "scripts" / "hardlink.gd")
        with self.assertRaisesRegex(OSError, "multiply-linked"):
            capture_generation_inventory(linked)
        self.assertEqual(sentinel.read_bytes(), b"external sentinel\n")

    def test_nested_mount_is_rejected_before_file_capture(self) -> None:
        destination = self.temp_dir / "project"
        scripts = destination / "scripts"
        scripts.mkdir(parents=True)
        sentinel = scripts / "sentinel.gd"
        sentinel.write_bytes(b"sentinel\n")
        real_ismount = os.path.ismount

        def model_mount(path: str | os.PathLike[str]) -> bool:
            return os.path.normcase(os.path.abspath(path)) == os.path.normcase(
                os.path.abspath(scripts)
            ) or real_ismount(path)

        with (
            patch.object(
                inventory_module.os.path,
                "ismount",
                side_effect=model_mount,
            ),
            self.assertRaisesRegex(OSError, "mounted"),
        ):
            capture_generation_inventory(destination)
        self.assertEqual(sentinel.read_bytes(), b"sentinel\n")

    def test_cli_repeated_run_is_identical_and_only_carries_prior_generation(
        self,
    ) -> None:
        destination = self.temp_dir / "godot"
        destination.mkdir()

        def convert_only(step: str) -> int:
            return cli.main(
                [
                    "convert",
                    "--gm-project",
                    str(FIXTURE_ROOT),
                    "--godot-project",
                    str(destination),
                    "--target-platform",
                    "windows",
                    "--only",
                    step,
                    "--max-warnings",
                    "0",
                ]
            )

        self.assertEqual(convert_only("scripts"), 0)
        user_sentinel = destination / "user-owned.txt"
        user_sentinel.write_bytes(b"user-owned\n")
        first_manifest = (
            destination / CONVERSION_MANIFEST_RELATIVE_PATH
        ).read_bytes()
        self.assertEqual(convert_only("scripts"), 0)
        second_manifest = (
            destination / CONVERSION_MANIFEST_RELATIVE_PATH
        ).read_bytes()
        self.assertEqual(first_manifest, second_manifest)

        self.assertEqual(convert_only("included_files"), 0)
        payload = json.loads(
            (destination / CONVERSION_MANIFEST_RELATIVE_PATH).read_text(
                encoding="utf-8"
            )
        )
        inventory_entries = cast(
            list[dict[str, object]],
            cast(dict[str, object], payload["generation_inventory"])["entries"],
        )
        by_path = {str(entry["path"]): entry for entry in inventory_entries}
        self.assertIn("scripts/game/scr_add.gd", by_path)
        self.assertEqual(
            cast(dict[str, object], by_path["scripts/game/scr_add.gd"]["owner"]),
            {"class": "converter_step", "name": "scripts"},
        )
        self.assertEqual(
            cast(dict[str, object], by_path["project.godot"]["owner"]),
            {
                "class": "shared_owner",
                "name": "project_configuration",
            },
        )
        self.assertNotIn("user-owned.txt", by_path)
        self.assertEqual(user_sentinel.read_bytes(), b"user-owned\n")

    @unittest.skipUnless(sys.platform == "win32", "native Windows junction required")
    def test_windows_junction_managed_root_is_rejected_without_traversal(
        self,
    ) -> None:
        destination = self.temp_dir / "project"
        destination.mkdir()
        external = self.temp_dir / "junction-target"
        external.mkdir()
        sentinel = external / "sentinel.gd"
        sentinel.write_bytes(b"junction sentinel\n")
        junction = destination / "scripts"
        completed = subprocess.run(
            (
                "cmd.exe",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(junction),
                str(external),
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        try:
            with self.assertRaisesRegex(OSError, "redirected"):
                capture_generation_inventory(destination)
            self.assertEqual(sentinel.read_bytes(), b"junction sentinel\n")
        finally:
            if os.path.isjunction(junction):
                os.rmdir(junction)

    @unittest.skipUnless(sys.platform == "win32", "native Windows modes required")
    def test_windows_read_only_carry_forward_preserves_attribute(self) -> None:
        destination = self.temp_dir / "project"
        (destination / "scripts").mkdir(parents=True)
        source = destination / "scripts" / "readonly.gd"
        source.write_bytes(b"readonly\n")
        os.chmod(source, 0o444)
        previous = capture_generation_inventory(destination)

        with ManagedOutputWorkspace.open(destination) as workspace:
            receipts = stage_inventory_carry_forward(
                workspace,
                previous,
                enabled_converters=(),
            )
            staged = Path(workspace.stage_path) / "scripts" / "readonly.gd"
            self.assertEqual(len(receipts), 1)
            self.assertFalse(stat.S_IMODE(staged.stat().st_mode) & stat.S_IWUSR)

        self.assertFalse(stat.S_IMODE(source.stat().st_mode) & stat.S_IWUSR)


if __name__ == "__main__":
    unittest.main()
