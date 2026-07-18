from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from src.conversion.converter import Converter
from src.conversion.project_godot import (
    DEFAULT_GODOT_PROJECT_NAME,
    ConversionPreflightError,
    GodotProjectDestinationState,
    inspect_godot_project_destination,
    prepare_godot_project_destination,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_yyp(gm_directory: Path, filename: str, project_name: str) -> None:
    gm_directory.mkdir(parents=True, exist_ok=True)
    (gm_directory / filename).write_text(
        json.dumps({"%Name": project_name}),
        encoding="utf-8",
    )


def _converter() -> Converter:
    running = threading.Event()
    running.set()
    return Converter(
        log_callback=lambda _message: None,
        progress_callback=lambda _value: None,
        status_callback=lambda _message: None,
        conversion_running=running,
    )


class _EnabledSetting:
    def get(self) -> bool:
        return True


def _run_cli_convert(
    gm_directory: Path,
    destination: Path,
    *extra_args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "main.py",
            "convert",
            "--gm-project",
            os.fspath(gm_directory),
            "--godot-project",
            os.fspath(destination),
            *extra_args,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


class ProjectDestinationPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.gm_directory = self.root / "game-maker"

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_preserves_existing_project_file_byte_for_byte(self) -> None:
        _write_yyp(self.gm_directory, "Existing.yyp", "Replacement Name")
        destination = self.root / "godot"
        destination.mkdir()
        project_file = destination / "project.godot"
        original = (
            b'\xef\xbb\xbfconfig_version=5\r\n\r\n[application]\r\n'
            b'config/name="Existing"\r\n'
        )
        project_file.write_bytes(original)

        returned_path = prepare_godot_project_destination(
            self.gm_directory,
            destination,
        )

        self.assertEqual(Path(returned_path), project_file)
        self.assertEqual(project_file.read_bytes(), original)

    def test_creates_minimal_4_7_project_in_truly_empty_directory(self) -> None:
        project_name = 'Quoted "Project" \\ Test'
        _write_yyp(self.gm_directory, "Quoted.yyp", project_name)
        destination = self.root / "godot"
        destination.mkdir()

        project_file = Path(
            prepare_godot_project_destination(self.gm_directory, destination)
        )

        content = project_file.read_text(encoding="utf-8")
        self.assertIn("config_version=5\n", content)
        self.assertIn("[application]\n", content)
        self.assertIn(
            f"config/name={json.dumps(project_name, ensure_ascii=False)}\n",
            content,
        )
        self.assertIn('config/features=PackedStringArray("4.7")\n', content)

    def test_creates_absent_destination_with_safe_name_fallbacks(self) -> None:
        self.gm_directory.mkdir()
        (self.gm_directory / "Fallback Name.yyp").write_text("{not json", encoding="utf-8")

        from_yyp_filename = self.root / "from-yyp-filename"
        prepare_godot_project_destination(self.gm_directory, from_yyp_filename)
        self.assertIn(
            'config/name="Fallback Name"',
            (from_yyp_filename / "project.godot").read_text(encoding="utf-8"),
        )

        no_yyp_directory = self.root / "game-maker-without-yyp"
        no_yyp_directory.mkdir()
        default_name_destination = self.root / "default-name"
        prepare_godot_project_destination(no_yyp_directory, default_name_destination)
        self.assertIn(
            f"config/name={json.dumps(DEFAULT_GODOT_PROJECT_NAME)}",
            (default_name_destination / "project.godot").read_text(encoding="utf-8"),
        )

    def test_refuses_nonempty_destination_without_project_file(self) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        destination = self.root / "godot"
        destination.mkdir()
        sentinel = destination / "keep.txt"
        sentinel.write_bytes(b"do not overwrite")

        with self.assertRaises(ConversionPreflightError) as raised:
            prepare_godot_project_destination(self.gm_directory, destination)

        self.assertEqual(
            raised.exception.code,
            "GM2GD-CONVERT-DESTINATION-NOT-EMPTY",
        )
        self.assertEqual(raised.exception.destination_path, os.fspath(destination))
        self.assertEqual(sentinel.read_bytes(), b"do not overwrite")
        self.assertEqual([path.name for path in destination.iterdir()], ["keep.txt"])

    def test_rejects_project_file_symlink_without_touching_external_file(self) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        destination = self.root / "godot"
        destination.mkdir()
        external_project = self.root / "external-project.godot"
        original = b'config_version=5\n[application]\nconfig/name="Outside"\n'
        external_project.write_bytes(original)
        (destination / "project.godot").symlink_to(external_project)

        with self.assertRaises(ConversionPreflightError) as raised:
            prepare_godot_project_destination(self.gm_directory, destination)

        self.assertEqual(
            raised.exception.code,
            "GM2GD-CONVERT-PROJECT-FILE-INVALID",
        )
        self.assertEqual(external_project.read_bytes(), original)

    def test_rejects_symbolic_link_destination(self) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        external_destination = self.root / "external-destination"
        external_destination.mkdir()
        destination = self.root / "godot-link"
        destination.symlink_to(external_destination, target_is_directory=True)

        with self.assertRaises(ConversionPreflightError) as raised:
            prepare_godot_project_destination(self.gm_directory, destination)

        self.assertEqual(
            raised.exception.code,
            "GM2GD-CONVERT-DESTINATION-SYMLINK",
        )
        self.assertEqual(list(external_destination.iterdir()), [])

    def test_rejects_destination_reported_as_windows_junction(self) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        destination = self.root / "godot-junction"
        destination.mkdir()
        destination_path = os.path.normcase(os.path.abspath(destination))

        def is_mock_junction(path: str) -> bool:
            return os.path.normcase(os.path.abspath(path)) == destination_path

        with mock.patch.object(
            os.path,
            "isjunction",
            side_effect=is_mock_junction,
            create=True,
        ):
            with self.assertRaises(ConversionPreflightError) as raised:
                prepare_godot_project_destination(
                    self.gm_directory,
                    destination,
                )

        self.assertEqual(
            raised.exception.code,
            "GM2GD-CONVERT-DESTINATION-SYMLINK",
        )
        self.assertEqual(list(destination.iterdir()), [])

    def test_converter_rejects_managed_output_directory_symlink_without_external_write(
        self,
    ) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        destination = self.root / "godot"
        destination.mkdir()
        project_file = destination / "project.godot"
        original = b'config_version=5\n[application]\nconfig/name="Keep Me"\n'
        project_file.write_bytes(original)
        external_scripts = self.root / "external-scripts"
        external_scripts.mkdir()
        (destination / "scripts").symlink_to(
            external_scripts,
            target_is_directory=True,
        )

        with self.assertRaises(ConversionPreflightError) as raised:
            _converter().convert(
                os.fspath(self.gm_directory),
                "windows",
                os.fspath(destination),
                {},
            )

        self.assertEqual(
            raised.exception.code,
            "GM2GD-CONVERT-MANAGED-OUTPUT-SYMLINK",
        )
        self.assertEqual(raised.exception.destination_path, os.fspath(destination))
        self.assertEqual(project_file.read_bytes(), original)
        self.assertEqual(list(external_scripts.iterdir()), [])

    def test_rejects_nested_symlink_in_managed_output_tree(self) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        destination = self.root / "godot"
        destination.mkdir()
        (destination / "project.godot").write_text(
            'config_version=5\n[application]\nconfig/name="Demo"\n',
            encoding="utf-8",
        )
        scripts = destination / "scripts"
        scripts.mkdir()
        external_directory = self.root / "external-nested"
        external_directory.mkdir()
        (scripts / "generated").symlink_to(
            external_directory,
            target_is_directory=True,
        )

        with self.assertRaises(ConversionPreflightError) as raised:
            prepare_godot_project_destination(self.gm_directory, destination)

        self.assertEqual(
            raised.exception.code,
            "GM2GD-CONVERT-MANAGED-OUTPUT-SYMLINK",
        )
        self.assertEqual(list(external_directory.iterdir()), [])

    def test_rejects_nested_managed_directory_reported_as_windows_junction(
        self,
    ) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        destination = self.root / "godot"
        destination.mkdir()
        (destination / "project.godot").write_text(
            'config_version=5\n[application]\nconfig/name="Demo"\n',
            encoding="utf-8",
        )
        scripts = destination / "scripts"
        scripts.mkdir()
        nested = scripts / "junction-cycle"
        nested.mkdir()
        nested_path = os.path.normcase(os.path.abspath(nested))
        real_scandir = os.scandir

        def is_mock_junction(path: str) -> bool:
            return os.path.normcase(os.path.abspath(path)) == nested_path

        def refuse_nested_scan(path: str):
            self.assertNotEqual(
                os.path.normcase(os.path.abspath(path)),
                nested_path,
                "junction-marked managed directories must not be traversed",
            )
            return real_scandir(path)

        with (
            mock.patch.object(
                os.path,
                "isjunction",
                side_effect=is_mock_junction,
                create=True,
            ),
            mock.patch(
                "src.conversion.project_godot.os.scandir",
                side_effect=refuse_nested_scan,
            ),
        ):
            with self.assertRaises(ConversionPreflightError) as raised:
                prepare_godot_project_destination(
                    self.gm_directory,
                    destination,
                )

        self.assertEqual(
            raised.exception.code,
            "GM2GD-CONVERT-MANAGED-OUTPUT-SYMLINK",
        )

    def test_rejects_managed_output_file_symlink_without_external_write(self) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        destination = self.root / "godot"
        destination.mkdir()
        (destination / "project.godot").write_text(
            'config_version=5\n[application]\nconfig/name="Demo"\n',
            encoding="utf-8",
        )
        external_icon = self.root / "external-icon.png"
        original = b"outside icon"
        external_icon.write_bytes(original)
        (destination / "icon.png").symlink_to(external_icon)

        with self.assertRaises(ConversionPreflightError) as raised:
            prepare_godot_project_destination(self.gm_directory, destination)

        self.assertEqual(
            raised.exception.code,
            "GM2GD-CONVERT-MANAGED-OUTPUT-SYMLINK",
        )
        self.assertEqual(external_icon.read_bytes(), original)

    def test_converter_rejects_managed_output_hardlink_without_external_write(
        self,
    ) -> None:
        script_directory = self.gm_directory / "scripts" / "foo"
        script_directory.mkdir(parents=True)
        (script_directory / "foo.yy").write_text(
            json.dumps({"name": "foo", "resourceType": "GMScript"}),
            encoding="utf-8",
        )
        (script_directory / "foo.gml").write_text(
            "function foo() { return 42; }\n",
            encoding="utf-8",
        )
        (self.gm_directory / "Hardlink.yyp").write_text(
            json.dumps(
                {
                    "%Name": "Hardlink",
                    "resources": [
                        {
                            "id": {
                                "name": "foo",
                                "path": "scripts/foo/foo.yy",
                            }
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        destination = self.root / "godot"
        destination.mkdir()
        project_file = destination / "project.godot"
        project_original = (
            b'config_version=5\n[application]\nconfig/name="Keep Me"\n'
        )
        project_file.write_bytes(project_original)
        output_script = destination / "scripts" / "foo.gd"
        output_script.parent.mkdir()
        external_script = self.root / "external-script.gd"
        external_original = b"OUTSIDE_SENTINEL\n"
        external_script.write_bytes(external_original)
        os.link(external_script, output_script)

        with self.assertRaises(ConversionPreflightError) as raised:
            _converter().convert(
                os.fspath(self.gm_directory),
                "windows",
                os.fspath(destination),
                {"scripts": _EnabledSetting()},
            )

        self.assertEqual(
            raised.exception.code,
            "GM2GD-CONVERT-MANAGED-OUTPUT-HARDLINK",
        )
        self.assertEqual(raised.exception.destination_path, os.fspath(destination))
        self.assertEqual(project_file.read_bytes(), project_original)
        self.assertEqual(external_script.read_bytes(), external_original)
        self.assertEqual(output_script.read_bytes(), external_original)

    def test_rejects_extension_stub_root_symlink_without_external_write(self) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        destination = self.root / "godot"
        destination.mkdir()
        project_file = destination / "project.godot"
        project_file.write_text(
            'config_version=5\n[application]\nconfig/name="Demo"\n',
            encoding="utf-8",
        )
        addons = destination / "addons"
        addons.mkdir()
        external_stubs = self.root / "external-extension-stubs"
        external_stubs.mkdir()
        (addons / "gm2godot_extensions").symlink_to(
            external_stubs,
            target_is_directory=True,
        )

        with self.assertRaises(ConversionPreflightError) as raised:
            _converter().convert(
                os.fspath(self.gm_directory),
                "windows",
                os.fspath(destination),
                {},
            )

        self.assertEqual(
            raised.exception.code,
            "GM2GD-CONVERT-MANAGED-OUTPUT-SYMLINK",
        )
        self.assertEqual(list(external_stubs.iterdir()), [])

    def test_rejects_addons_ancestor_symlink_when_external_subtree_is_missing(
        self,
    ) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        destination = self.root / "godot"
        destination.mkdir()
        project_file = destination / "project.godot"
        project_file.write_text(
            'config_version=5\n[application]\nconfig/name="Demo"\n',
            encoding="utf-8",
        )
        external_addons = self.root / "external-addons"
        external_addons.mkdir()
        (destination / "addons").symlink_to(
            external_addons,
            target_is_directory=True,
        )

        with self.assertRaises(ConversionPreflightError) as raised:
            _converter().convert(
                os.fspath(self.gm_directory),
                "windows",
                os.fspath(destination),
                {},
            )

        self.assertEqual(
            raised.exception.code,
            "GM2GD-CONVERT-MANAGED-OUTPUT-SYMLINK",
        )
        self.assertFalse((external_addons / "gm2godot_extensions").exists())
        self.assertEqual(list(external_addons.iterdir()), [])

    def test_allows_unrelated_addons_without_traversing_their_contents(self) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        destination = self.root / "godot"
        destination.mkdir()
        project_file = destination / "project.godot"
        project_file.write_text(
            'config_version=5\n[application]\nconfig/name="Demo"\n',
            encoding="utf-8",
        )
        addons = destination / "addons"
        addons.mkdir()
        external_plugin = self.root / "external-unrelated-plugin"
        external_plugin.mkdir()
        unrelated_plugin = addons / "third_party_plugin"
        unrelated_plugin.symlink_to(external_plugin, target_is_directory=True)

        returned_path = prepare_godot_project_destination(
            self.gm_directory,
            destination,
        )

        self.assertEqual(Path(returned_path), project_file)
        self.assertTrue(unrelated_plugin.is_symlink())
        self.assertEqual(list(external_plugin.iterdir()), [])

    def test_rejects_project_files_that_godot_cannot_parse(self) -> None:
        invalid_projects = (
            b"not = [valid\n",
            b"foo=bar\n",
            b"config_version=5\n\xff\n",
        )
        for index, project_bytes in enumerate(invalid_projects):
            with self.subTest(project_bytes=project_bytes):
                destination = self.root / f"invalid-{index}"
                destination.mkdir()
                (destination / "project.godot").write_bytes(project_bytes)

                with self.assertRaises(ConversionPreflightError) as raised:
                    inspect_godot_project_destination(destination)

                self.assertEqual(
                    raised.exception.code,
                    "GM2GD-CONVERT-PROJECT-FILE-INVALID",
                )
                self.assertEqual(
                    (destination / "project.godot").read_bytes(),
                    project_bytes,
                )

    def test_accepts_empty_project_file_like_exact_godot_4_7_1(self) -> None:
        destination = self.root / "empty-project"
        destination.mkdir()
        (destination / "project.godot").write_bytes(b"")

        state = inspect_godot_project_destination(destination)

        self.assertIs(state, GodotProjectDestinationState.EXISTING_PROJECT)

    def test_rechecks_empty_destination_before_creating_project(self) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        destination = self.root / "godot"
        destination.mkdir()
        sentinel = destination / "appeared-during-preflight.txt"
        original_inspector = inspect_godot_project_destination

        def inspect_then_mutate(path: object) -> GodotProjectDestinationState:
            state = original_inspector(path)  # type: ignore[arg-type]
            sentinel.write_bytes(b"keep")
            return state

        with mock.patch(
            "src.conversion.project_godot.inspect_godot_project_destination",
            side_effect=inspect_then_mutate,
        ):
            with self.assertRaises(ConversionPreflightError) as raised:
                prepare_godot_project_destination(self.gm_directory, destination)

        self.assertEqual(
            raised.exception.code,
            "GM2GD-CONVERT-DESTINATION-NOT-EMPTY",
        )
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertFalse((destination / "project.godot").exists())

    def test_failed_project_write_removes_partial_file(self) -> None:
        _write_yyp(self.gm_directory, "Demo.yyp", "Demo")
        destination = self.root / "godot"
        destination.mkdir()

        with mock.patch(
            "src.conversion.project_godot._write_project_bytes",
            side_effect=OSError("injected write failure"),
        ):
            with self.assertRaises(ConversionPreflightError) as raised:
                prepare_godot_project_destination(self.gm_directory, destination)

        self.assertEqual(raised.exception.code, "GM2GD-CONVERT-DESTINATION-IO")
        self.assertFalse((destination / "project.godot").exists())

    def test_converter_uses_preflight_for_empty_destination(self) -> None:
        _write_yyp(self.gm_directory, "Converter.yyp", "Converter Project")
        destination = self.root / "converter-output"
        destination.mkdir()

        _converter().convert(
            os.fspath(self.gm_directory),
            "windows",
            os.fspath(destination),
            {},
        )

        content = (destination / "project.godot").read_text(encoding="utf-8")
        self.assertIn('config/name="Converter Project"', content)
        self.assertIn('config/features=PackedStringArray("4.7")', content)

    def test_converter_preflight_does_not_rewrite_existing_project(self) -> None:
        _write_yyp(self.gm_directory, "Converter.yyp", "Replacement")
        destination = self.root / "existing-converter-output"
        destination.mkdir()
        project_file = destination / "project.godot"
        original = b'config_version=5\r\n[application]\r\nconfig/name="Keep Me"\r\n'
        project_file.write_bytes(original)

        _converter().convert(
            os.fspath(self.gm_directory),
            "windows",
            os.fspath(destination),
            {},
        )

        self.assertEqual(project_file.read_bytes(), original)


class ProjectDestinationCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.gm_directory = self.root / "game-maker"
        self.project_name = 'CLI "Project" \\ Test'
        _write_yyp(self.gm_directory, "CLI.yyp", self.project_name)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_cli_creates_project_file_for_absent_destination(self) -> None:
        destination = self.root / "cli-output"

        result = _run_cli_convert(
            self.gm_directory,
            destination,
            "--allow-partial",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        project_file = destination / "project.godot"
        self.assertTrue(project_file.is_file())
        project_content = project_file.read_text(encoding="utf-8")
        self.assertIn(
            f"config/name={json.dumps(self.project_name)}",
            project_content,
        )
        self.assertIn(
            'config/features=PackedStringArray("4.7")',
            project_content,
        )

    def test_cli_reports_structured_error_for_nonempty_destination(self) -> None:
        destination = self.root / "occupied-output"
        destination.mkdir()
        sentinel = destination / "keep.txt"
        sentinel.write_bytes(b"keep")

        result = _run_cli_convert(self.gm_directory, destination)

        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        diagnostic = json.loads(result.stderr)
        self.assertEqual(diagnostic["severity"], "error")
        self.assertEqual(
            diagnostic["code"],
            "GM2GD-CONVERT-DESTINATION-NOT-EMPTY",
        )
        self.assertEqual(diagnostic["source_path"], os.fspath(destination))
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertEqual([path.name for path in destination.iterdir()], ["keep.txt"])


if __name__ == "__main__":
    unittest.main()
