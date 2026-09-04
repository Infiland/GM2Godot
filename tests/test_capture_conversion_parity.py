from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

from scripts import capture_conversion_parity as parity
from scripts import conversion_parity_contract as contract
from scripts import conversion_parity_inputs as inputs
from scripts import conversion_parity_snapshot as snapshots

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestCaptureConversionParity(unittest.TestCase):
    def test_manifest_freezes_required_gate_selection(self) -> None:
        document = json.loads((PROJECT_ROOT / "architecture-verification.json").read_text(encoding="utf-8"))
        gate = cast(dict[str, object], cast(dict[str, object], document["gates"])["R01"])
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
                    "739ffd4c1281f1d6d279c0830b792fa71c7fb34e6849bccb4bd44207e0f9ad53",
                ),
                contract.HashRequirement(
                    "requirements-bootstrap.txt",
                    "90c82b6bda1db6d1665cdab218349663bd7903622fb010ddc01438141497a0d2",
                ),
                contract.HashRequirement(
                    "requirements.txt",
                    "6d55718ca1e4fc63ab64a2efa2dd6612a31b010d908b02662cebc2d2d56d0ad4",
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
                    "transaction_id", "destination_identity", "parent_identity",
                    "managed_identities", "evidence.attempt.identity",
                    "evidence.manifest.identity", "generation_record.identity",
                    "generation_record.name", "generation_record.sha256",
                    "journal_sha256",
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
                patch.object(parity, "_capture_fixture_receipts") as capture_fixtures,
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
