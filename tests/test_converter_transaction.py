# pyright: reportPrivateUsage=false
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from src.conversion import converter as converter_module
from src.conversion import managed_output_publisher as publisher_module
from src.conversion import scripts as scripts_module
from src.conversion.architecture_policy import publish_architecture_policy_report
from src.conversion.conversion_manifest import (
    CONVERSION_ATTEMPT_RELATIVE_PATH,
    CONVERSION_MANIFEST_RELATIVE_PATH,
)
from src.conversion.conversion_outcome import ConversionOutcome
from src.conversion.converter import Converter
from src.conversion.generation_inventory import (
    GenerationInventory,
    capture_generation_inventory,
)
from src.conversion.managed_output_publisher import (
    MANAGED_OUTPUT_JOURNAL_NAME,
    MANAGED_OUTPUT_RECOVERY_NAME,
)
from src.conversion.managed_output_workspace import WORKSPACE_PARENT_NAME


class _Setting:
    def __init__(self, value: bool) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value


class TestConverterManagedOutputTransaction(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.gm_dir = self.temp_dir / "gm"
        self.godot_dir = self.temp_dir / "godot"
        self.gm_dir.mkdir()
        self.running = threading.Event()
        self.running.set()
        self._write_source("Baseline Project", "return 1;\n", include_new=False)
        baseline = self._convert()
        self.assertEqual(baseline.state, "success")
        self.baseline_manifest = (
            self.godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH
        ).read_bytes()
        manifest_payload = json.loads(self.baseline_manifest)
        self.baseline_inventory = GenerationInventory.from_value(
            manifest_payload["generation_inventory"]
        )
        self.baseline_files = self._inventory_snapshot(self.baseline_inventory)
        self.sentinel = self.godot_dir / "user-owned-sentinel.txt"
        self.sentinel.write_bytes(b"user-owned\n")
        self._write_source("Changed Project", "return 2;\n", include_new=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    @staticmethod
    def _settings() -> dict[str, _Setting]:
        return {
            "project_name": _Setting(True),
            "scripts": _Setting(True),
            "asset_registry": _Setting(True),
        }

    def _converter(self) -> Converter:
        return Converter(
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=self.running,
        )

    def _convert(self, converter: Converter | None = None) -> ConversionOutcome:
        selected = converter if converter is not None else self._converter()
        return selected.convert(
            str(self.gm_dir),
            "windows",
            str(self.godot_dir),
            self._settings(),
        )

    def _write_source(
        self,
        project_name: str,
        script_body: str,
        *,
        include_new: bool,
    ) -> None:
        scripts = [("scr_existing", script_body)]
        if include_new:
            scripts.append(("scr_new", "return 3;\n"))
        resources: list[dict[str, object]] = []
        for script_name, body in scripts:
            script_dir = self.gm_dir / "scripts" / script_name
            script_dir.mkdir(parents=True, exist_ok=True)
            source_path = f"scripts/{script_name}/{script_name}.yy"
            (script_dir / f"{script_name}.yy").write_text(
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
            (script_dir / f"{script_name}.gml").write_text(
                body,
                encoding="utf-8",
            )
            resources.append(
                {
                    "id": {
                        "name": script_name,
                        "path": source_path,
                    }
                }
            )
        (self.gm_dir / "Transaction.yyp").write_text(
            json.dumps(
                {
                    "%Name": project_name,
                    "resourceType": "GMProject",
                    "resources": resources,
                }
            ),
            encoding="utf-8",
        )

    def _inventory_snapshot(
        self,
        inventory: GenerationInventory,
    ) -> dict[str, tuple[bytes, int]]:
        return {
            entry.path: (
                (self.godot_dir / entry.path).read_bytes(),
                stat.S_IMODE((self.godot_dir / entry.path).stat().st_mode),
            )
            for entry in inventory.entries
        }

    def _assert_baseline_preserved(
        self,
        expected_state: str,
        *,
        expected_failure_phase: str | None = None,
    ) -> None:
        for relative_path, (expected_bytes, expected_mode) in (
            self.baseline_files.items()
        ):
            with self.subTest(relative_path=relative_path):
                path = self.godot_dir / relative_path
                self.assertEqual(path.read_bytes(), expected_bytes)
                actual_mode = stat.S_IMODE(path.stat().st_mode)
                if os.name == "nt":
                    self.assertEqual(
                        bool(actual_mode & stat.S_IWUSR),
                        bool(expected_mode & stat.S_IWUSR),
                    )
                else:
                    self.assertEqual(actual_mode, expected_mode)
        self.assertEqual(
            (self.godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH).read_bytes(),
            self.baseline_manifest,
        )
        self.assertFalse(
            (self.godot_dir / "scripts" / "scr_new.gd").exists()
        )
        self.assertEqual(self.sentinel.read_bytes(), b"user-owned\n")
        self.assertEqual(
            capture_generation_inventory(self.godot_dir),
            self.baseline_inventory,
        )
        attempt = json.loads(
            (self.godot_dir / CONVERSION_ATTEMPT_RELATIVE_PATH).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(attempt["attempt"]["state"], expected_state)
        self.assertEqual(
            attempt["attempt"]["failure_phase"],
            expected_failure_phase,
        )
        self.assertEqual(
            attempt["attempt"]["cancelled"],
            expected_state == "cancelled",
        )
        self.assertEqual(
            attempt["canonical_manifest"],
            {
                "path": "gm2godot/conversion_manifest.json",
                "status": "preserved",
                "updated": False,
                "current_output": "verified",
                "sha256": (
                    "sha256:" + hashlib.sha256(self.baseline_manifest).hexdigest()
                ),
            },
        )
        workspace_parent = self.godot_dir / WORKSPACE_PARENT_NAME
        self.assertFalse(
            (workspace_parent / MANAGED_OUTPUT_JOURNAL_NAME).exists()
        )
        self.assertFalse(
            (workspace_parent / MANAGED_OUTPUT_RECOVERY_NAME).exists()
        )
        self.assertFalse(
            any(path.name.endswith(".stage") for path in workspace_parent.iterdir())
        )

    def test_runtime_failure_after_real_mutations_preserves_baseline(self) -> None:
        converter = self._converter()
        real_build = converter._build_step_runners

        def failing_runners(context: object) -> dict[str, Callable[[], object]]:
            runners = real_build(context)  # type: ignore[arg-type]

            def fail_after_scripts() -> object:
                raise RuntimeError("injected registry failure")

            runners["asset_registry"] = fail_after_scripts
            return runners

        with patch.object(
            converter,
            "_build_step_runners",
            side_effect=failing_runners,
        ):
            with self.assertRaisesRegex(RuntimeError, "registry failure"):
                self._convert(converter)

        self._assert_baseline_preserved(
            "failed",
            expected_failure_phase="runtime",
        )

    def test_mid_run_cancellation_after_real_write_preserves_baseline(self) -> None:
        real_convert_all = scripts_module.ScriptConverter.convert_all

        def convert_then_cancel(script_converter: scripts_module.ScriptConverter) -> str | None:
            result = real_convert_all(script_converter)
            self.running.clear()
            return result

        with patch.object(
            scripts_module.ScriptConverter,
            "convert_all",
            new=convert_then_cancel,
        ):
            outcome = self._convert()

        self.assertEqual(outcome.state, "cancelled")
        self._assert_baseline_preserved("cancelled")

    def test_finalizer_failure_preserves_baseline(self) -> None:
        with patch.object(
            converter_module,
            "publish_conversion_diagnostic_reports",
            side_effect=OSError("injected diagnostic finalizer failure"),
        ):
            with self.assertRaisesRegex(OSError, "diagnostic finalizer failure"):
                self._convert()

        self._assert_baseline_preserved(
            "failed",
            expected_failure_phase="finalizer",
        )

    def test_cancellation_during_finalizer_preserves_baseline(self) -> None:
        def publish_then_cancel(*args: object, **kwargs: object) -> object:
            receipt = publish_architecture_policy_report(*args, **kwargs)  # type: ignore[arg-type]
            self.running.clear()
            return receipt

        with patch.object(
            converter_module,
            "publish_architecture_policy_report",
            side_effect=publish_then_cancel,
        ):
            outcome = self._convert()

        self.assertEqual(outcome.state, "cancelled")
        self._assert_baseline_preserved("cancelled")

    def test_staged_validation_failure_preserves_baseline(self) -> None:
        with patch.object(
            converter_module,
            "validate_staged_generation_inventory",
            side_effect=OSError("injected staged validation failure"),
        ):
            with self.assertRaisesRegex(OSError, "staged validation failure"):
                self._convert()

        self._assert_baseline_preserved(
            "failed",
            expected_failure_phase="validation",
        )

    def test_cancellation_after_validation_preserves_baseline(self) -> None:
        def cancel_after_validation(phase: str, _path: str) -> None:
            if phase == "after_staged_validation":
                self.running.clear()

        with patch.object(
            converter_module,
            "_before_conversion_transaction_phase",
            side_effect=cancel_after_validation,
        ):
            outcome = self._convert()

        self.assertEqual(outcome.state, "cancelled")
        self._assert_baseline_preserved("cancelled")

    def test_cancellation_immediately_before_decision_preserves_baseline(
        self,
    ) -> None:
        def cancel_before_decision(phase: str, _path: str) -> None:
            if phase == "before_commit_decision":
                self.running.clear()

        with patch.object(
            converter_module,
            "_before_conversion_transaction_phase",
            side_effect=cancel_before_decision,
        ):
            outcome = self._convert()

        self.assertEqual(outcome.state, "cancelled")
        self._assert_baseline_preserved("cancelled")

    def test_publication_failure_rolls_back_real_mutations(self) -> None:
        failed = False

        def fail_after_first_install(phase: str, _path: str | None) -> None:
            nonlocal failed
            if phase == "public_installed" and not failed:
                failed = True
                raise OSError("injected managed publication failure")

        with patch.object(
            publisher_module,
            "_before_managed_output_phase",
            side_effect=fail_after_first_install,
        ):
            with self.assertRaisesRegex(OSError, "managed publication failure"):
                self._convert()

        self.assertTrue(failed)
        self._assert_baseline_preserved(
            "failed",
            expected_failure_phase="publication",
        )

    def test_success_commits_changed_generation_and_matching_evidence(self) -> None:
        outcome = self._convert()

        self.assertEqual(outcome.state, "success")
        self.assertIn(
            'config/name="Changed Project"',
            (self.godot_dir / "project.godot").read_text(encoding="utf-8"),
        )
        self.assertTrue(
            (self.godot_dir / "scripts" / "scr_new.gd").is_file()
        )
        self.assertEqual(self.sentinel.read_bytes(), b"user-owned\n")
        manifest_path = self.godot_dir / CONVERSION_MANIFEST_RELATIVE_PATH
        manifest_content = manifest_path.read_bytes()
        manifest = json.loads(manifest_content)
        inventory = GenerationInventory.from_value(
            manifest["generation_inventory"]
        )
        self.assertEqual(
            capture_generation_inventory(self.godot_dir),
            inventory,
        )
        attempt = json.loads(
            (self.godot_dir / CONVERSION_ATTEMPT_RELATIVE_PATH).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(attempt["attempt"]["state"], "success")
        self.assertEqual(attempt["canonical_manifest"]["status"], "updated")
        self.assertEqual(
            attempt["canonical_manifest"]["sha256"],
            "sha256:" + hashlib.sha256(manifest_content).hexdigest(),
        )

    def test_first_cancelled_attempt_can_retry_from_empty_generation(self) -> None:
        retry_destination = self.temp_dir / "retry-godot"
        self.running.clear()
        cancelled = self._converter().convert(
            str(self.gm_dir),
            "windows",
            str(retry_destination),
            self._settings(),
        )
        self.assertEqual(cancelled.state, "cancelled")
        self.assertFalse((retry_destination / "project.godot").exists())
        self.assertTrue(
            (retry_destination / CONVERSION_ATTEMPT_RELATIVE_PATH).is_file()
        )

        self.running.set()
        completed = self._converter().convert(
            str(self.gm_dir),
            "windows",
            str(retry_destination),
            self._settings(),
        )
        self.assertEqual(completed.state, "success")
        self.assertTrue((retry_destination / "project.godot").is_file())
        self.assertTrue(
            (retry_destination / "scripts" / "scr_new.gd").is_file()
        )
