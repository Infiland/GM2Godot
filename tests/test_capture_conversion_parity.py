from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable, cast
from unittest.mock import Mock, patch

from scripts._anchored_output import AnchoredOutputError
from scripts import capture_conversion_parity as parity
from scripts import conversion_parity_contract as contract
from scripts import conversion_parity_inputs as inputs
from scripts import conversion_parity_snapshot as snapshots
from src import cli
from src.conversion import managed_output_publisher as publisher
from src.conversion.generation_inventory import capture_generation_inventory
from src.conversion.managed_output_publisher import publish_managed_output_generation
from src.conversion.managed_output_workspace import ManagedOutputWorkspace
from src.conversion import godot_validation

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def phase_hook() -> Callable[[str, str | None], None]:
    return cast(Callable[[str, str | None], None], getattr(publisher, "_after_managed_output_phase"))


class TestCaptureConversionParity(unittest.TestCase):
    def test_manifest_freezes_required_gate_selection(self) -> None:
        document = json.loads((PROJECT_ROOT / "architecture-verification.json").read_text(encoding="utf-8"))
        gate = cast(dict[str, object], cast(dict[str, object], document["gates"])["R01"])
        self.assertEqual(gate["validation_kind"], "conversion-parity")
        self.assertEqual(
            gate["unittest_ids"],
            [
                "tests.test_gml_transpiler_architecture",
                "tests.test_gml_transpiler",
                "tests.test_gml_tokenizer",
                "tests.test_gml_source_maps",
                "tests.test_conversion_architecture",
                "tests.test_scripts",
                "tests.test_objects",
                "tests.test_script_generator",
                "tests.test_project_macros",
                "tests.test_project_enums",
                "tests.test_gml_language_metadata",
                "tests.test_gml_lexical_api",
                "tests.test_gml_expression_api",
                "tests.test_gml_statement_api",
                "tests.test_gml_transpiler_models",
                "tests.test_lts_2026_conversion",
                "tests.test_simple_topdown_conversion",
                "tests.test_required_unittest_runner",
                "tests.test_capture_conversion_parity",
                "tests.test_conversion_parity_snapshot",
            ],
        )
        self.assertEqual(
            gate["required_environment"],
            {
                "GODOT_BIN": "required-executable",
                "SNAP_PROJECT_PATH": "required-git-checkout",
                "ADDING_PROJECT_PATH": "required-git-checkout",
                "SIMPLE_TOPDOWN_PROJECT_PATH": "required-git-checkout",
            },
        )
        self.assertEqual(
            gate["required_paths"],
            [
                "src/conversion/gml_transpiler.py",
                "tests/gml_transpiler_architecture_support.py",
                "tests/test_gml_transpiler_architecture.py",
                "tests/fixtures/golden/basic_scripts/BasicScripts.yyp",
                "tests/fixtures/part2/projects/resource_matrix/ResourceMatrix.yyp",
                "constraints/requirements-macos-py312.lock",
            ],
        )
        self.assertEqual(gate["allowed_skips"], {})

    def test_manifest_freezes_runtime_and_parity_inputs(self) -> None:
        definition = contract.load_parity_definition(PROJECT_ROOT / "architecture-verification.json", "R01")
        self.assertEqual(
            definition.runtime,
            contract.RuntimeRequirement(
                python_version="3.12.10",
                platform_name="darwin",
                machine="arm64",
                godot_binary_environment="GODOT_BIN",
                godot_version="4.7.2.stable.official.ed1daf0bf",
            ),
        )
        self.assertEqual(
            definition.external_repositories,
            (
                contract.ExternalRepository(
                    "snap",
                    "SNAP_PROJECT_PATH",
                    "https://github.com/JujuAdams/SNAP.git",
                    "b4191e195c7c84359f995d568d8906c452b83e50",
                    "d933a9cd28ce965779e75f5d961b65a8203fb534",
                ),
                contract.ExternalRepository(
                    "adding",
                    "ADDING_PROJECT_PATH",
                    "https://github.com/WuffMakesGames/Adding.git",
                    "1bf032618be258242f78505de7cd151242452776",
                    "b5e9d66287101b90227460d54becd6dbd12c0578",
                ),
                contract.ExternalRepository(
                    "simple_topdown",
                    "SIMPLE_TOPDOWN_PROJECT_PATH",
                    "https://github.com/Infiland/GM2GodotGameTest_SimpleTopDown.git",
                    "2413d7714b0dbd5d548058ea4c74f591f0d4e1e3",
                    "26e60949d2ce9ab69ca6122255b5a16e641f72fa",
                ),
            ),
        )
        self.assertEqual(
            definition.dependency_locks,
            (
                contract.HashRequirement(
                    "constraints/requirements-macos-py312.lock",
                    "9970b900ba446d73b50fc5fd0d3aa1a3d012ca99839a8a200c9ce6499a294f42",
                ),
                contract.HashRequirement(
                    "requirements-bootstrap.txt",
                    "90c82b6bda1db6d1665cdab218349663bd7903622fb010ddc01438141497a0d2",
                ),
                contract.HashRequirement(
                    "requirements.txt",
                    "176c4a48cff65bd65eb3908044b4c715aacd24eabaa508e3d74806eb77305cca",
                ),
                contract.HashRequirement(
                    "requirements-tooling.txt",
                    "ea632cc2f500df05d59e7b203772a334da64347ad8ec57f3f8927218931407ee",
                ),
            ),
        )
        self.assertEqual(
            definition.fixtures,
            (
                contract.FixtureDefinition(
                    "golden-basic-scripts", "tests/fixtures/golden/basic_scripts", None,
                    "BasicScripts.yyp", "c9577649cac4c807d94ed0049e9175ffcb2448bb168939f5882debaef0562cef",
                    ("scripts",), 0, 0, 0, 0,
                ),
                contract.FixtureDefinition(
                    "part2-resource-matrix", "tests/fixtures/part2/projects/resource_matrix", None,
                    "ResourceMatrix.yyp", "f3326f6db31a99ec36c53476b1ae405094b2e7efd925fcc534b582c996aea957",
                    (), 0, None, None, None,
                    expected_runtime_warnings=(
                        "WARNING: GM2Godot stores multiple active GameMaker views as compatibility state; render-backed split viewports require a custom SubViewport pipeline.",
                        "WARNING: GM2Godot does not preserve full persistent room state; room lifecycle code runs when the generated Godot scene enters.",
                    ),
                ),
                contract.FixtureDefinition(
                    "snap-lts", None, "SNAP_PROJECT_PATH", "snap.yyp",
                    "a837cc7aacb9b21898f0d117e88b365c47a19985d375675828377ea32cc9a6e8",
                    (), 0, None, None, None, "partial", 1,
                ),
                contract.FixtureDefinition(
                    "adding-lts", None, "ADDING_PROJECT_PATH", "Adding.yyp",
                    "ee4d6eeca8078b16621abe3f8796c68bd3a8177b9184007d69d399315c93bac0",
                    (), 0, None, None, None, "partial", 1,
                ),
                contract.FixtureDefinition(
                    "simple-topdown", None, "SIMPLE_TOPDOWN_PROJECT_PATH",
                    "GM2GodotGameTest_SimpleTopDown.yyp",
                    "9ed406accd7a5697703fdd69055ce359ae211632ae23775f5f8f3d2d6b72ff6d",
                    (), 0, None, None, None, "partial", 1,
                ),
            ),
        )
        self.assertEqual(
            definition.destination,
            contract.DestinationDefinition(
                "[application]\nconfig/name=\"GM2Godot parity seed\"\n",
                True,
                True,
                ".gm2godot-managed-output",
                ".gm2godot-managed-output.lock",
                (
                    "workspace_marker.destination_identity", "workspace_marker.parent_identity",
                    "pointer.transaction_id", "pointer.destination_identity", "pointer.journal_sha256",
                    "pointer.generation_record.name", "pointer.generation_record.identity", "pointer.generation_record.sha256",
                    "desired_generation.transaction_id", "desired_generation.destination_identity",
                    "desired_generation.managed_identities[*][1:]", "desired_generation.evidence.attempt.identity",
                    "desired_generation.evidence.manifest.identity", "desired_generation.record_path.transaction_id",
                    "previous_generation.transaction_id", "previous_generation.destination_identity",
                    "previous_generation.managed_identities[*][1:]", "previous_generation.evidence.attempt.identity",
                    "previous_generation.evidence.manifest.identity", "previous_generation.record_path.transaction_id",
                    "journal.transaction_id", "journal.destination_identity", "journal.workspace_parent_identity",
                    "journal.stage_identity", "journal.publication_identity", "journal.pointer_stage_identity",
                    "journal.previous_record.name", "journal.previous_record.identity", "journal.previous_record.sha256",
                    "journal.desired_record.name", "journal.desired_record.identity", "journal.desired_record.sha256",
                    "journal.directories[*].identity", "journal.transitions[*].previous_public_identity",
                    "journal.transitions[*].backup.identity", "journal.transitions[*].desired_stage.identity",
                ),
            ),
        )
        self.assertEqual(
            definition.fields,
            (
                "relative_paths", "file_bytes", "modes", "generated_gdscript",
                "source_maps", "diagnostics", "diagnostic_ids", "parser_error",
                "stdout", "stderr", "exit_status", "terminal_output_state",
                "transaction_provenance", "runtime_markers",
            ),
        )
        self.assertEqual(definition.facade_module, "src.conversion.gml_transpiler")
    def test_facade_probe_reports_all_direct_owner_identities(self) -> None:
        snapshot = inputs.capture_facade_contract(
            PROJECT_ROOT,
            facade_module="src.conversion.gml_transpiler",
            environment=dict(os.environ),
        )
        self.assertEqual(len(cast(list[object], snapshot["public_exports"])), 44)
        self.assertEqual(snapshot["private_export_count"], 0)
        bindings = cast(list[dict[str, object]], snapshot["bindings"])
        self.assertTrue(all(binding["identity"] is True for binding in bindings))
        self.assertEqual(bindings[0]["name"], "GMLTranspileError")
        self.assertEqual(bindings[-1]["name"], "write_gml_source_map")
    def test_ordinary_test_has_no_platform_specific_godot_path(self) -> None:
        macos_applications_prefix = "/" + "Applications/"
        self.assertNotIn(macos_applications_prefix, Path(__file__).read_text(encoding="utf-8"))

    def test_receipt_writer_preserves_native_text_bytes_and_identity(self) -> None:
        payload = {"equal": True, "purpose": "receipt-publication-test-only", "text": "Ω\nvalue\r\n"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline.json"
            with baseline.open("w", encoding="utf-8") as file:
                file.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            receipt = root / "nested" / "receipt.json"
            parity.write_receipt(receipt, payload)
            self.assertEqual(receipt.read_bytes(), baseline.read_bytes())
            identity = (receipt.stat().st_dev, receipt.stat().st_ino)
            parity.write_receipt(receipt, payload)
            self.assertEqual((receipt.stat().st_dev, receipt.stat().st_ino), identity)
            with self.assertRaises(AnchoredOutputError) as error:
                parity.write_receipt(receipt, {"different": True})
            self.assertEqual(error.exception.code, "output-different")
            self.assertEqual(receipt.read_bytes(), baseline.read_bytes())
            self.assertEqual((receipt.stat().st_dev, receipt.stat().st_ino), identity)

    def test_receipt_windows_newlines_are_preserved_without_platform_faking(self) -> None:
        payload = {"purpose": "receipt-publication-test-only", "text": "escaped\nvalue"}
        with patch.object(parity.os, "linesep", "\r\n"), patch.object(parity, "publish_identical_receipt_bytes") as publish:
            parity.write_receipt(Path("receipt.json"), payload)
        publish.assert_called_once_with(Path("receipt.json"), (json.dumps(payload, indent=2, sort_keys=True) + "\n").replace("\n", "\r\n").encode("utf-8"))

    def test_parity_receipt_cli_reports_anchored_error_details(self) -> None:
        payload = {"equal": True, "purpose": "receipt-publication-test-only"}
        error = AnchoredOutputError("output-different", "existing bytes differ")
        error.__cause__ = OSError("causal failure")
        error.add_note("owned cleanup detail")
        stderr = io.StringIO()
        with patch.object(parity, "load_parity_definition", return_value=object()), patch.object(
            parity, "capture_parity", return_value=payload
        ), patch.object(parity, "write_receipt", side_effect=error), contextlib.redirect_stderr(stderr):
            status = parity.main(["--manifest", "manifest.json", "--gate", "R01", "--base-ref", "base",
                                  "--head-ref", "head", "--receipt", "receipt.json"])
        self.assertEqual(status, 2)
        for expected in ("output-different", "causal failure", "owned cleanup detail", "fresh receipt path"):
            self.assertIn(expected, stderr.getvalue())

    def test_receipt_controls_preserve_writer_identity_and_exit_cli_nonzero(self) -> None:
        payload = {"equal": True, "purpose": "receipt-publication-test-only"}
        for interruption in (KeyboardInterrupt(), SystemExit(0), SystemExit(7)):
            with self.subTest(interruption=type(interruption).__name__), patch.object(
                parity, "publish_identical_receipt_bytes", side_effect=interruption
            ):
                with self.assertRaises(type(interruption)) as caught:
                    parity.write_receipt(Path("receipt.json"), payload)
                self.assertIs(caught.exception, interruption)
                stderr = io.StringIO()
                interruption.add_note("control cleanup detail")
                with patch.object(parity, "load_parity_definition", return_value=object()), patch.object(
                    parity, "capture_parity", return_value=payload
                ), contextlib.redirect_stderr(stderr), tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "receipt.json"
                    path.write_bytes(b"prior immutable receipt")
                    identity = (path.stat().st_dev, path.stat().st_ino)
                    status = parity.main(["--manifest", "manifest.json", "--gate", "R01", "--base-ref", "base",
                                          "--head-ref", "head", "--receipt", str(path)])
                    self.assertEqual(status, 2)
                    self.assertEqual(path.read_bytes(), b"prior immutable receipt")
                    self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity)
                self.assertIn("publication interrupted", stderr.getvalue())
                self.assertIn("control cleanup detail", stderr.getvalue())
                self.assertIn("may remain", stderr.getvalue())

    def test_receipt_cli_bounds_messages_and_notes_without_mutating_errors(self) -> None:
        payload = {"equal": True, "purpose": "receipt-publication-test-only"}
        errors = (AnchoredOutputError("output-different", "primary-" * 1000),
                  KeyboardInterrupt("primary-" * 1000), SystemExit(0), SystemExit(7))
        for error in errors:
            cause = OSError("causal-" * 1000)
            error.__cause__ = cause
            notes = [f"note-{index:02d}-" + "detail-" * 1000 for index in range(12)]
            for note in notes:
                error.add_note(note)
            original_text = str(error)
            stderr = io.StringIO()
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "receipt.json"
                path.write_bytes(b"prior immutable receipt")
                identity = (path.stat().st_dev, path.stat().st_ino)
                with patch.object(parity, "load_parity_definition", return_value=object()), patch.object(
                    parity, "capture_parity", return_value=payload
                ), patch.object(parity, "write_receipt", side_effect=error), contextlib.redirect_stderr(stderr):
                    status = parity.main(["--manifest", "manifest.json", "--gate", "R01", "--base-ref", "base",
                                          "--head-ref", "head", "--receipt", str(path)])
                self.assertEqual(status, 2)
                self.assertEqual(path.read_bytes(), b"prior immutable receipt")
                self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity)
            lines = stderr.getvalue().splitlines()
            self.assertTrue(lines[0].startswith("parity receipt publication"))
            if len(original_text) > 512:
                self.assertIn("primary-", lines[0])
                self.assertTrue(lines[0].endswith("... [truncated]"))
            self.assertTrue(lines[1].startswith("cause: OSError: causal-"))
            self.assertTrue(lines[1].endswith("... [truncated]"))
            self.assertLessEqual(max(len(line) for line in lines), 512)
            self.assertLessEqual(len(stderr.getvalue()), 5400)
            self.assertIn("An immutable candidate or prior identical receipt may remain", stderr.getvalue())
            self.assertEqual(sum(line.startswith("note: note-") for line in lines), 8)
            for index in range(8):
                self.assertTrue(lines[index + 2].startswith(f"note: note-{index:02d}-detail-"))
                self.assertTrue(lines[index + 2].endswith("... [truncated]"))
            self.assertIn("note: additional diagnostic notes omitted [truncated]", lines)
            self.assertNotIn("note-08-", stderr.getvalue())
            self.assertEqual(str(error), original_text)
            self.assertIs(error.__cause__, cause)
            self.assertEqual(getattr(error, "__notes__"), notes)

    def test_fixture_hash_mismatch_fails_before_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            source = root / "fixture"
            source.mkdir()
            (source / "project.yyp").write_text("{}", encoding="utf-8")
            fixture = self._fixture("fixture", "fixture", "project.yyp", "0" * 64)
            with self.assertRaisesRegex(contract.ParityError, "fixture hash mismatch"):
                inputs.validate_fixtures((fixture,), root=root, environment={}, external_paths={})

    def test_fixture_resolution_is_portable_across_equivalent_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            source = root / "alternate"
            source.mkdir()
            (source / "project.yyp").write_text("{}", encoding="utf-8")
            fixture = self._fixture("alternate", "alternate", "project.yyp", inputs.tree_sha256(source))
            resolved = inputs.validate_fixtures((fixture,), root=root, environment={}, external_paths={})
            self.assertEqual(resolved, {"alternate": source.resolve()})

    def test_project_relative_path_escape_fails_before_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            source = root / "fixture"
            source.mkdir()
            (source / "project.yyp").write_text("{}", encoding="utf-8")
            (root / "outside.yyp").write_text("{}", encoding="utf-8")
            fixture = self._fixture(
                "fixture",
                "fixture",
                "../outside.yyp",
                inputs.tree_sha256(source),
            )
            with self.assertRaisesRegex(contract.ParityError, "escapes its fixture root"):
                inputs.validate_fixtures((fixture,), root=root, environment={}, external_paths={})

    def test_absolute_project_path_escape_fails_before_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            source = root / "fixture"
            source.mkdir()
            (source / "project.yyp").write_text("{}", encoding="utf-8")
            outside = root / "outside.yyp"
            outside.write_text("{}", encoding="utf-8")
            fixture = self._fixture(
                "fixture",
                "fixture",
                str(outside),
                inputs.tree_sha256(source),
            )
            with self.assertRaisesRegex(contract.ParityError, "escapes its fixture root"):
                inputs.validate_fixtures((fixture,), root=root, environment={}, external_paths={})
    def test_directory_symlinks_fail_closed_in_fixture_and_output_trees(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("directory symlinks are unavailable")
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            outside = root / "outside"
            outside.mkdir()
            (outside / "sentinel.txt").write_text("outside", encoding="utf-8")

            def make_link(link: Path) -> None:
                try:
                    link.symlink_to(outside, target_is_directory=True)
                except OSError as error:
                    self.skipTest(f"directory symlinks are unavailable: {error}")

            fixture = root / "fixture"
            fixture.mkdir()
            make_link(fixture / "linked")
            with self.assertRaisesRegex(contract.ParityError, "must not contain a symlink"):
                inputs.tree_sha256(fixture)
            output = root / "output"
            output.mkdir()
            make_link(output / "linked")
            with self.assertRaisesRegex(contract.ParityError, "must not contain a symlink"):
                snapshots.collect_output_files(output)
    def test_external_commit_mismatch_fails_before_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            checkout = Path(temporary_root) / "fixture"
            checkout.mkdir()
            self._git(checkout, "init", "--quiet")
            self._git(checkout, "config", "user.email", "test@example.invalid")
            self._git(checkout, "config", "user.name", "Parity Test")
            (checkout / "fixture.txt").write_text("fixture", encoding="utf-8")
            self._git(checkout, "add", "fixture.txt")
            self._git(checkout, "commit", "--quiet", "-m", "fixture")
            self._git(checkout, "remote", "add", "origin", "https://example.invalid/fixture.git")
            repository = contract.ExternalRepository(
                name="fixture",
                environment="FIXTURE_PATH",
                remote="https://example.invalid/fixture.git",
                commit="0" * 40,
                tree=self._git(checkout, "rev-parse", "HEAD^{tree}"),
            )
            with self.assertRaisesRegex(contract.ParityError, "identity mismatch"):
                inputs.validate_external_repositories((repository,), environment={"FIXTURE_PATH": str(checkout)})

    def test_resolved_commit_survives_requested_ref_move(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            repository = Path(temporary_root) / "repository"
            repository.mkdir()
            self._git(repository, "init", "--quiet")
            self._git(repository, "config", "user.email", "test@example.invalid")
            self._git(repository, "config", "user.name", "Parity Test")
            (repository / "value.txt").write_text("first", encoding="utf-8")
            self._git(repository, "add", "value.txt")
            self._git(repository, "commit", "--quiet", "-m", "first")
            resolved_first = parity.resolve_commit_ref(repository, "HEAD")
            (repository / "value.txt").write_text("second", encoding="utf-8")
            self._git(repository, "commit", "--quiet", "-am", "second")
            self.assertNotEqual(resolved_first, parity.resolve_commit_ref(repository, "HEAD"))
            exported = parity.export_ref(repository, resolved_first, Path(temporary_root) / "export")
            self.assertEqual((exported / "value.txt").read_text(encoding="utf-8"), "first")
    def test_runtime_godot_version_mismatch_uses_platform_neutral_executable(self) -> None:
        requirement = contract.RuntimeRequirement(
            python_version=platform.python_version(),
            platform_name=sys.platform,
            machine=platform.machine(),
            godot_binary_environment="GODOT_BIN",
            godot_version="not-the-current-python-version",
        )
        with self.assertRaisesRegex(contract.ParityError, "Godot version mismatch"):
            inputs.validate_runtime(
                requirement,
                environment={"GODOT_BIN": sys.executable},
            )

    def test_unlaunchable_fake_godot_maps_to_parity_error(self) -> None:
        requirement = contract.RuntimeRequirement(
            python_version=platform.python_version(),
            platform_name=sys.platform,
            machine=platform.machine(),
            godot_binary_environment="GODOT_BIN",
            godot_version="ignored",
        )
        with patch.object(inputs.subprocess, "run", side_effect=OSError("unlaunchable")):
            with self.assertRaisesRegex(contract.ParityError, "could not launch"):
                inputs.validate_runtime(
                    requirement,
                    environment={"GODOT_BIN": sys.executable},
                )
    def test_missing_godot_environment_fails_before_conversion(self) -> None:
        requirement = contract.RuntimeRequirement(
            python_version=platform.python_version(),
            platform_name=sys.platform,
            machine=platform.machine(),
            godot_binary_environment="GODOT_BIN",
            godot_version="4.7.2.stable.official.ed1daf0bf",
        )
        with self.assertRaisesRegex(contract.ParityError, "Missing required environment variable"):
            inputs.validate_runtime(requirement, environment={})

    def test_parity_manifest_schema_requires_an_exact_integer(self) -> None:
        original = json.loads((PROJECT_ROOT / "architecture-verification.json").read_text(encoding="utf-8"))
        for version in (True, 1.0):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "manifest.json"
                path.write_text(json.dumps({**original, "schema_version": version}), encoding="utf-8")
                with self.assertRaisesRegex(contract.ParityError, "schema_version"):
                    contract.load_parity_definition(path, "R01")

    def test_runtime_probe_rejects_skipped_failed_and_incomplete_boot_reports(self) -> None:
        for status, returncode, frames in (("skipped", None, 0), ("failed", 0, 0), ("passed", 0, 2)):
            report = godot_validation.GodotValidationReport(
                status=cast(godot_validation.GodotValidationStatus, status), godot_binary="fake",
                project_path="/project", resource_paths=(), returncode=returncode,
                boot_frames=frames, message="probe did not complete",
            )
            with self.subTest(status=status, frames=frames), patch.object(
                godot_validation, "validate_generated_godot_project", return_value=report
            ), patch.object(sys, "argv", ["probe", "/project", str(frames), "[]", "false"]), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    exec(parity.RUNTIME_PROBE_CODE, {"__name__": "__main__"})
        with patch.object(parity.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, json.dumps({"status": "skipped"}), ""
        )):
            with self.assertRaisesRegex(contract.ParityError, "malformed"):
                parity.runtime_marker_snapshot(PROJECT_ROOT, Path("/project"), boot_frames=0)

    def test_warning_expectation_is_default_empty_and_exactly_fixture_bound(self) -> None:
        document = json.loads((PROJECT_ROOT / "architecture-verification.json").read_text(encoding="utf-8"))
        definition = contract.load_parity_definition(PROJECT_ROOT / "architecture-verification.json", "R01")
        resource = next(fixture for fixture in definition.fixtures if fixture.identifier == "part2-resource-matrix")
        self.assertEqual(resource.expected_runtime_warnings, contract.RESOURCE_MATRIX_RUNTIME_WARNINGS)
        self.assertTrue(all(not fixture.expected_runtime_warnings for fixture in definition.fixtures if fixture is not resource))
        mutations: tuple[tuple[str, object], ...] = (
            ("id", "renamed"), ("repository_path", "another/source"), ("project_relative_path", "Another.yyp"),
            ("sha256", "0" * 64), ("expected_runtime_warnings", list(reversed(resource.expected_runtime_warnings))),
            ("expected_runtime_warnings", [resource.expected_runtime_warnings[0]]),
            ("expected_runtime_warnings", [*resource.expected_runtime_warnings, "WARNING: extra"]),
            ("expected_runtime_warnings", ["WARNING: changed", resource.expected_runtime_warnings[1]]),
        )
        for key, value in mutations:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as temporary:
                malformed = copy.deepcopy(document)
                row = malformed["gates"]["R01"]["parity"]["fixtures"][1]
                row[key] = value
                path = Path(temporary) / "manifest.json"
                path.write_text(json.dumps(malformed), encoding="utf-8")
                with self.assertRaises(contract.ParityError):
                    contract.load_parity_definition(path, "R01")
        with tempfile.TemporaryDirectory() as temporary:
            malformed = copy.deepcopy(document)
            malformed["gates"]["R01"]["parity"]["fixtures"][0]["expected_runtime_warnings"] = list(resource.expected_runtime_warnings)
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaisesRegex(contract.ParityError, "pinned resource-matrix"):
                contract.load_parity_definition(path, "R01")

    def test_declared_warning_probe_preserves_failed_status_and_actual_output(self) -> None:
        fixture = self._warning_fixture()
        boot_output = "Godot boot\n" + "\n".join(fixture.expected_runtime_warnings) + "\n"
        output = "Godot import\nGodot resource validation\n" + boot_output
        report = godot_validation.GodotValidationReport(
            status="failed", godot_binary="fake", project_path="/project", resource_paths=(),
            returncode=0, import_returncode=0, boot_returncode=0, boot_frames=2, output=output,
            boot_output=boot_output, output_issues=tuple(
                godot_validation.GodotOutputIssue("warning", line) for line in fixture.expected_runtime_warnings
            ),
        )
        with patch.object(godot_validation, "validate_generated_godot_project", return_value=report), patch.object(
            sys, "argv", ["probe", "/project", "2", json.dumps(fixture.expected_runtime_warnings), "true"]
        ), contextlib.redirect_stdout(io.StringIO()) as captured:
            exec(parity.RUNTIME_PROBE_CODE, {"__name__": "__main__"})
        markers = cast(dict[str, object], json.loads(captured.getvalue()))
        self.assertEqual(markers["status"], "failed")
        self.assertIs(markers["probe_accepted"], True)
        self.assertEqual(markers["output"], output)
        self.assertEqual(markers["boot_output"], boot_output)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            (destination / "asset.png").write_bytes(b"fixture")
            with patch.object(parity.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(markers), "")) as probe:
                self.assertEqual(parity.runtime_marker_snapshot(PROJECT_ROOT, destination, boot_frames=2, fixture=fixture), markers)
            argv = probe.call_args.args[0]
            self.assertEqual(json.loads(argv[-2]), list(fixture.expected_runtime_warnings))
            self.assertIs(json.loads(argv[-1]), True)

    def test_parity_receipt_declares_the_exact_fixture_warning_policy(self) -> None:
        definition = contract.load_parity_definition(PROJECT_ROOT / "architecture-verification.json", "R01")
        sources = {fixture.identifier: Path("/fixtures") / fixture.identifier for fixture in definition.fixtures}
        with patch.multiple(
            parity,
            resolve_commit_ref=Mock(side_effect=["a" * 40, "b" * 40]),
            validate_parity_inputs=Mock(return_value=sources),
            export_ref=Mock(side_effect=[Path("/base"), Path("/head")]),
            validate_hash_requirements=Mock(),
            capture_facade_contract=Mock(return_value={"public_exports": [], "bindings": []}),
            capture_fixture_receipts=Mock(return_value=[]),
        ):
            receipt = parity.capture_parity(definition, base_ref="base", head_ref="head", root=PROJECT_ROOT)
        saved_contract = cast(dict[str, object], receipt["contract"])
        saved_fixtures = cast(list[dict[str, object]], saved_contract["fixtures"])
        self.assertEqual(
            {row["id"]: row["expected_runtime_warnings"] for row in saved_fixtures},
            {fixture.identifier: list(fixture.expected_runtime_warnings) for fixture in definition.fixtures},
        )

    def test_warning_probe_rejects_missing_extra_reordered_errors_and_nonzero_stages(self) -> None:
        fixture = self._warning_fixture()
        good = self._runtime_markers(warnings=True)
        variants: list[dict[str, object]] = []
        for key in ("returncode", "import_returncode", "boot_returncode"):
            for value in (None, False, 0.0, 1):
                variants.append({**good, key: value})
        for key, value in (("status", "passed"), ("status", "skipped"), ("boot_frames", 0),
                           ("boot_frames", True), ("boot_frames", 2.0), ("probe_accepted", 1),
                           ("import_required", 1), ("boot_output", "different boot\n"),
                           ("operations", ["Adding: Performed invented"]), ("unexpected", True)):
            variants.append({**good, key: value})
        issue_rows = cast(list[dict[str, object]], good["output_issues"])
        for rows in ([], list(reversed(issue_rows)), [*issue_rows, {"severity": "warning", "line": "WARNING: extra"}],
                     [{"severity": "error", "line": issue_rows[0]["line"]}, issue_rows[1]],
                     [{"severity": "warning", "line": "WARNING: changed"}, issue_rows[1]]):
            variants.append({**good, "output_issues": rows})
        missing = dict(good)
        del missing["output"]
        variants.append(missing)
        for index, markers in enumerate(variants):
            with self.subTest(index=index), patch.object(parity.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(markers), "")):
                with self.assertRaises(contract.ParityError):
                    parity.runtime_marker_snapshot(PROJECT_ROOT, Path("/project"), boot_frames=2, fixture=fixture)
        for severity, lines in (("warning", tuple(reversed(fixture.expected_runtime_warnings))),
                                ("warning", fixture.expected_runtime_warnings[:1]),
                                ("error", fixture.expected_runtime_warnings)):
            report = godot_validation.GodotValidationReport(
                status="failed", godot_binary="fake", project_path="/project", resource_paths=(),
                returncode=0, import_returncode=0, boot_returncode=0, boot_frames=2,
                output_issues=tuple(godot_validation.GodotOutputIssue(cast(godot_validation.GodotOutputIssueSeverity, severity), line) for line in lines),
            )
            with self.subTest(severity=severity, lines=lines), patch.object(
                godot_validation, "validate_generated_godot_project", return_value=report
            ), patch.object(sys, "argv", ["probe", "/project", "2", json.dumps(fixture.expected_runtime_warnings), "true"]):
                with self.assertRaises(SystemExit):
                    exec(parity.RUNTIME_PROBE_CODE, {"__name__": "__main__"})

    def test_runtime_defaults_reject_undeclared_warnings_and_optional_import_mismatch(self) -> None:
        warnings = self._runtime_markers(warnings=True)
        with patch.object(parity.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(warnings), "")):
            with self.assertRaisesRegex(contract.ParityError, "undeclared"):
                parity.runtime_marker_snapshot(PROJECT_ROOT, Path("/project"), boot_frames=2)
        clean = self._runtime_markers(warnings=False)
        with patch.object(parity.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(clean), "")):
            self.assertEqual(parity.runtime_marker_snapshot(PROJECT_ROOT, Path("/project"), boot_frames=0), clean)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            (destination / "texture.png").write_bytes(b"fixture")
            clean["import_required"] = True
            with patch.object(parity.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(clean), "")):
                with self.assertRaisesRegex(contract.ParityError, "required stage"):
                    parity.runtime_marker_snapshot(PROJECT_ROOT, destination, boot_frames=0)
        clean["import_required"] = False
        clean["boot_output"] = "unexpected boot"
        with patch.object(parity.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(clean), "")):
            with self.assertRaisesRegex(contract.ParityError, "inconsistent boot output"):
                parity.runtime_marker_snapshot(PROJECT_ROOT, Path("/project"), boot_frames=0)

    def test_raw_colored_errors_and_duplicate_probe_fields_are_rejected(self) -> None:
        fixture = self._warning_fixture()
        markers = self._runtime_markers(warnings=True)
        markers["output"] = "\x1b[31mERROR: hidden\x1b[0m\n" + cast(str, markers["output"])
        with patch.object(parity.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(markers), "")):
            with self.assertRaisesRegex(contract.ParityError, "undeclared"):
                parity.runtime_marker_snapshot(PROJECT_ROOT, Path("/project"), boot_frames=2, fixture=fixture)
        duplicate = '{"status":"skipped",' + json.dumps(self._runtime_markers(warnings=False))[1:]
        with patch.object(parity.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, duplicate, "")):
            with self.assertRaisesRegex(contract.ParityError, "duplicate"):
                parity.runtime_marker_snapshot(PROJECT_ROOT, Path("/project"), boot_frames=0)

    @staticmethod
    def _warning_fixture() -> contract.FixtureDefinition:
        definition = contract.load_parity_definition(PROJECT_ROOT / "architecture-verification.json", "R01")
        return next(fixture for fixture in definition.fixtures if fixture.identifier == "part2-resource-matrix")

    @classmethod
    def _runtime_markers(cls, *, warnings: bool) -> dict[str, object]:
        lines = cls._warning_fixture().expected_runtime_warnings if warnings else ()
        boot_output = "\n".join(lines) + "\n" if warnings else ""
        return {"probe_accepted": True, "status": "failed" if warnings else "passed", "import_required": False,
                "returncode": 0, "import_returncode": 0 if warnings else None, "boot_returncode": 0 if warnings else None,
                "boot_frames": 2 if warnings else 0, "output": "Godot validation\n" + boot_output,
                "boot_output": boot_output, "operations": [],
                "output_issues": [{"severity": "warning", "line": line} for line in lines]}

    def test_observer_preserves_original_hook_order_exception_and_restoration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "project.yyp").write_text("{}", encoding="utf-8")
            fixture = self._fixture("fixture", "source", "project.yyp", inputs.tree_sha256(source))
            receipt_path = root / "observation.json"
            command = parity.build_conversion_command(source, root / "destination", fixture, receipt_path)
            original_error = RuntimeError("original phase hook failure")
            original = Mock(side_effect=original_error)

            def fake_cli(_arguments: list[str]) -> int:
                phase_hook()("commit_decision_published", None)
                return 0

            with patch.object(publisher, "_after_managed_output_phase", original), patch.object(
                cli, "main", side_effect=fake_cli
            ), patch.object(sys, "argv", ["probe", command[-1]]), patch.object(os, "cpu_count", os.cpu_count):
                with self.assertRaises(RuntimeError) as caught:
                    exec(parity.CLI_PROBE_CODE, {"__name__": "__main__"})
                self.assertIs(caught.exception, original_error)
                self.assertIs(phase_hook(), original)
            original.assert_called_once_with("commit_decision_published", None)
            self.assertFalse(receipt_path.exists())

    def test_observer_failure_or_missing_phase_cannot_emit_success_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "project.yyp").write_text("{}", encoding="utf-8")
            fixture = self._fixture("fixture", "source", "project.yyp", inputs.tree_sha256(source))
            receipt_path = root / "observation.json"
            command = parity.build_conversion_command(source, root / "destination", fixture, receipt_path)
            for observe in (False, True):
                events: list[str] = []

                def original(_phase: str, _path: str | None) -> None:
                    events.append("original")

                def fake_cli(_arguments: list[str]) -> int:
                    if observe:
                        phase_hook()("commit_decision_published", None)
                    return 0

                with self.subTest(observe=observe), patch.object(publisher, "_after_managed_output_phase", original), patch.object(
                    cli, "main", side_effect=fake_cli
                ), patch.object(sys, "argv", ["probe", command[-1]]), patch.object(os, "cpu_count", os.cpu_count):
                    with self.assertRaises((SystemExit, FileNotFoundError)):
                        exec(parity.CLI_PROBE_CODE, {"__name__": "__main__"})
                    self.assertIs(phase_hook(), original)
                self.assertEqual(events, ["original"] if observe else [])
                self.assertFalse(receipt_path.exists())

    @unittest.skipUnless(sys.platform == "darwin" and platform.machine() == "arm64", "Requires native Darwin arm64 publication observation")
    def test_observer_authenticates_real_native_publication_without_a_converter_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination, receipt_path = root / "source", root / "destination", root / "observation.json"
            source.mkdir()
            destination.mkdir()
            (source / "project.yyp").write_text("{}", encoding="utf-8")
            (destination / "project.godot").write_text('[application]\nconfig/name="seed"\n', encoding="utf-8")
            fixture = self._fixture("fixture", "source", "project.yyp", inputs.tree_sha256(source))
            command = parity.build_conversion_command(source, destination, fixture, receipt_path)

            def json_bytes(value: object) -> bytes:
                return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode()

            def fake_cli(_arguments: list[str]) -> int:
                previous = capture_generation_inventory(destination)
                with ManagedOutputWorkspace.open(destination, transaction_id="a" * 32) as workspace:
                    stage = Path(workspace.stage_path)
                    outputs = {"project.godot": b'[application]\nconfig/name="desired"\n',
                               "scripts/sample.gd": b"extends Node\n",
                               "gm2godot/architecture_policy.json": json_bytes({}),
                               "gm2godot/conversion_diagnostics.json": json_bytes({"diagnostics": []})}
                    for path, content in outputs.items():
                        output = stage / path
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(content)
                    desired = capture_generation_inventory(stage)
                    manifest = json_bytes({"format_version": 2, "generation_inventory": desired.to_dict()})
                    attempt = json_bytes({"format_version": 1, "canonical_manifest": {
                        "path": "gm2godot/conversion_manifest.json", "status": "updated", "updated": True,
                        "current_output": "verified", "sha256": "sha256:" + hashlib.sha256(manifest).hexdigest(),
                    }})
                    publish_managed_output_generation(workspace, previous_inventory=previous, desired_inventory=desired,
                                                     canonical_manifest_content=manifest, attempt_content=attempt)
                return 0

            original_hook = phase_hook()
            with patch.object(cli, "main", side_effect=fake_cli), patch.object(
                sys, "argv", ["probe", command[-1]]
            ), patch.object(os, "cpu_count", os.cpu_count):
                with self.assertRaises(SystemExit) as caught:
                    exec(parity.CLI_PROBE_CODE, {"__name__": "__main__"})
                self.assertEqual(caught.exception.code, 0)
            self.assertIs(phase_hook(), original_hook)
            observation = cast(dict[str, object], json.loads(receipt_path.read_text(encoding="utf-8")))
            definition = contract.load_parity_definition(PROJECT_ROOT / "architecture-verification.json", "R01").destination
            files = snapshots.collect_output_files(destination)
            snapshots.validate_required_outputs(files)
            snapshots.verify_publication_identities(destination, observation, definition)
            snapshot = snapshots.output_snapshot(files, destination=destination, definition=definition, stdout="", stderr="",
                exit_status=0, parser_error={}, runtime_markers={}, publication_observation=observation)
            self.assertTrue(cast(dict[str, object], snapshot["transaction_provenance"])["validated"])
            self.assertFalse((destination / ".gm2godot-managed-output/.gm2godot-managed-output-transaction.json").exists())

    def test_lock_hash_mismatch_fails_before_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            (root / "lock.txt").write_text("actual", encoding="utf-8")
            with self.assertRaisesRegex(contract.ParityError, "hash mismatch"):
                inputs.validate_hash_requirements(
                    root,
                    (contract.HashRequirement(path="lock.txt", sha256="f" * 64),),
                    label="test",
                )

    def test_capture_ref_resolution_failure_stops_before_input_validation(self) -> None:
        definition = contract.load_parity_definition(PROJECT_ROOT / "architecture-verification.json", "R01")
        with (
            patch.object(
                parity,
                "resolve_commit_ref",
                side_effect=contract.ParityError("bad ref"),
            ),
            patch.object(parity, "validate_parity_inputs") as validate_inputs,
            patch.object(parity, "export_ref") as export,
        ):
            with self.assertRaisesRegex(contract.ParityError, "bad ref"):
                parity.capture_parity(definition, base_ref="base", head_ref="head", root=PROJECT_ROOT)
        validate_inputs.assert_not_called()
        export.assert_not_called()

    def test_capture_resolves_both_refs_before_input_validation_and_export(self) -> None:
        definition = contract.load_parity_definition(PROJECT_ROOT / "architecture-verification.json", "R01")
        events: list[str] = []

        def resolve(_root: Path, requested: str) -> str:
            events.append(f"resolve:{requested}")
            return "a" * 40 if requested == "base" else "b" * 40

        def reject_inputs(*_args: object, **_kwargs: object) -> dict[str, Path]:
            events.append("validate")
            raise contract.ParityError("bad input")

        with (
            patch.object(parity, "resolve_commit_ref", side_effect=resolve),
            patch.object(parity, "validate_parity_inputs", side_effect=reject_inputs),
            patch.object(parity, "export_ref") as export,
        ):
            with self.assertRaisesRegex(contract.ParityError, "bad input"):
                parity.capture_parity(definition, base_ref="base", head_ref="head", root=PROJECT_ROOT)
        self.assertEqual(events, ["resolve:base", "resolve:head", "validate"])
        export.assert_not_called()
    def test_capture_export_lock_failure_stops_before_fixture_runs(self) -> None:
        definition = contract.load_parity_definition(PROJECT_ROOT / "architecture-verification.json", "R01")
        with tempfile.TemporaryDirectory() as temporary_root:
            exported_base = Path(temporary_root) / "base"
            exported_head = Path(temporary_root) / "head"
            with (
                patch.object(parity, "resolve_commit_ref", side_effect=["a" * 40, "b" * 40]),
                patch.object(parity, "validate_parity_inputs", return_value={}),
                patch.object(parity, "export_ref", side_effect=[exported_base, exported_head]),
                patch.object(
                    parity,
                    "validate_hash_requirements",
                    side_effect=[None, contract.ParityError("bad exported lock")],
                ),
                patch.object(parity, "capture_fixture_receipts") as capture_fixtures,
            ):
                with self.assertRaisesRegex(contract.ParityError, "bad exported lock"):
                    parity.capture_parity(
                        definition,
                        base_ref="base",
                        head_ref="head",
                        root=PROJECT_ROOT,
                    )
        capture_fixtures.assert_not_called()

    def test_capture_resets_destination_between_base_and_head_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            source = root / "source"
            source.mkdir()
            (source / "project.yyp").write_text("{}", encoding="utf-8")
            fixture = self._fixture(
                "fixture",
                "source",
                "project.yyp",
                inputs.tree_sha256(source),
            )
            destination = contract.DestinationDefinition(
                seed_project_godot="",
                same_absolute_path=True,
                reset_between_base_and_head=True,
                transaction_root=".gm2godot-managed-output",
                transaction_lock=".gm2godot-managed-output.lock",
                volatile_transaction_fields=("transaction_id",),
            )
            definition = contract.ParityDefinition(
                runtime=contract.RuntimeRequirement("", "", "", "", ""),
                external_repositories=(),
                dependency_locks=(),
                fixtures=(fixture,),
                fields=("stdout",),
                facade_module="src.conversion.gml_transpiler",
                destination=destination,
            )
            events: list[str] = []
            run_destinations: list[Path] = []
            reset_destinations: list[Path] = []
            base = snapshots.FixtureRun("/same", {}, {"stdout": ""})
            head = snapshots.FixtureRun("/same", {}, {"stdout": ""})

            def fake_run_fixture(
                _code_tree: Path,
                _source: Path,
                target: Path,
                _fixture: contract.FixtureDefinition,
                _definition: contract.DestinationDefinition,
            ) -> snapshots.FixtureRun:
                events.append("run")
                run_destinations.append(target)
                return base if len(run_destinations) == 1 else head

            def fake_remove_target(target: Path) -> None:
                events.append("reset")
                reset_destinations.append(target)

            with patch.multiple(
                parity,
                resolve_commit_ref=Mock(side_effect=["a" * 40, "b" * 40]),
                validate_parity_inputs=Mock(return_value={fixture.identifier: source}),
                export_ref=Mock(side_effect=[root / "base", root / "head"]),
                validate_hash_requirements=Mock(),
                capture_facade_contract=Mock(
                    side_effect=[
                        {"public_exports": [], "bindings": [], "private_export_count": 30},
                        {"public_exports": [], "bindings": [], "private_export_count": 0},
                    ],
                ),
                run_fixture=Mock(side_effect=fake_run_fixture),
                _remove_generated_target=Mock(side_effect=fake_remove_target),
            ):
                receipt = parity.capture_parity(
                    definition,
                    base_ref="base",
                    head_ref="head",
                    root=root,
                )
        self.assertEqual(events, ["run", "reset", "run"])
        self.assertEqual(len(run_destinations), 2)
        self.assertEqual(run_destinations[0], run_destinations[1])
        self.assertEqual(reset_destinations, [run_destinations[0]])
        self.assertTrue(run_destinations[0].is_absolute())
        self.assertTrue(receipt["equal"])
        facade_contract = cast(dict[str, object], receipt["facade_contract"])
        base_facade = cast(dict[str, object], facade_contract["base"])
        head_facade = cast(dict[str, object], facade_contract["head"])
        self.assertEqual(base_facade["private_export_count"], 30)
        self.assertEqual(head_facade["private_export_count"], 0)
    def test_yyp_path_and_partial_success_are_explicit_in_conversion_argv(self) -> None:
        fixture = self._fixture("fixture", "fixture", "real/project.yyp", "a" * 64)
        command = parity.build_conversion_command(Path("/source"), Path("/destination"), fixture)
        payload = json.loads(command[-1])
        self.assertEqual(payload["project_yyp"], "/source/real/project.yyp")
        arguments = payload["arguments"]
        self.assertEqual(arguments[arguments.index("--gm-project") + 1], "/source/real")
        self.assertIn("--allow-partial", arguments)

    def test_fixture_mutation_by_head_is_rejected_after_the_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            project = source / "project.yyp"
            project.write_text("{}", encoding="utf-8")
            fixture = self._fixture("fixture", "source", "project.yyp", inputs.tree_sha256(source))
            definition = contract.ParityDefinition(
                runtime=contract.RuntimeRequirement("", "", "", "", ""), external_repositories=(),
                dependency_locks=(), fixtures=(fixture,), fields=("stdout",),
                facade_module="src.conversion.gml_transpiler",
                destination=contract.load_parity_definition(PROJECT_ROOT / "architecture-verification.json", "R01").destination,
            )
            invocations: list[Path] = []

            def fake_run(code_tree: Path, _source: Path, destination: Path,
                         _fixture: contract.FixtureDefinition, _definition: contract.DestinationDefinition) -> snapshots.FixtureRun:
                invocations.append(code_tree)
                if code_tree == root / "head":
                    project.write_text('{"mutated":true}', encoding="utf-8")
                return snapshots.FixtureRun(str(destination), {}, {"stdout": "same"})

            with patch.object(parity, "run_fixture", side_effect=fake_run), patch.object(parity, "_remove_generated_target"):
                with self.assertRaisesRegex(contract.ParityError, "hash mismatch"):
                    parity.capture_fixture_receipts(definition, sources={"fixture": source}, base_tree=root / "base",
                        head_tree=root / "head", output_root=root / "output")
            self.assertEqual(invocations, [root / "base", root / "head"])

    def test_run_fixture_surfaces_real_cli_probe_missing_yyp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            source = root / "source"
            source.mkdir()
            (source / "present.yyp").write_text("{}", encoding="utf-8")
            fixture = self._fixture(
                "fixture",
                "source",
                "missing.yyp",
                inputs.tree_sha256(source),
            )
            definition = contract.DestinationDefinition(
                seed_project_godot="",
                same_absolute_path=True,
                reset_between_base_and_head=True,
                transaction_root=".gm2godot-managed-output",
                transaction_lock=".gm2godot-managed-output.lock",
                volatile_transaction_fields=(),
            )
            with self.assertRaisesRegex(contract.ParityError, "Parity project is missing"):
                parity.run_fixture(
                    PROJECT_ROOT,
                    source,
                    root / "output",
                    fixture,
                    definition,
                )


    def test_receipt_writer_uses_sorted_canonical_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            receipt_path = Path(temporary_root) / "receipt.json"
            parity.write_receipt(receipt_path, {"z": 1, "a": {"b": 2}})
            self.assertEqual(
                receipt_path.read_text(encoding="utf-8"),
                '{\n  "a": {\n    "b": 2\n  },\n  "z": 1\n}\n',
            )

    @staticmethod
    def _fixture(identifier: str, repository_path: str, project: str, digest: str) -> contract.FixtureDefinition:
        return contract.FixtureDefinition(
            identifier=identifier,
            repository_path=repository_path,
            environment=None,
            project_relative_path=project,
            sha256=digest,
            only=(),
            expected_exit=0,
            max_warnings=None,
            max_errors=None,
            max_unsupported=None,
        )

    @staticmethod
    def _git(path: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(path), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()


if __name__ == "__main__":
    unittest.main()
