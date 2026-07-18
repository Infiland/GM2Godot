from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.extension_registry import (
    EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
    ExtensionEntry,
    build_extension_entries,
    extension_stub_relative_script_path,
    extension_stub_resource_path,
    render_extension_compatibility_report,
    render_extension_stub_script,
    write_extension_compatibility_outputs,
)
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.project_source_paths import ResolvedProjectSourcePath
import src.conversion.extension_registry as extension_registry


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class TestExtensionRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.outside_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)
        shutil.rmtree(self.outside_dir)

    @staticmethod
    def _write_minimal_extension(path: str, name: str) -> None:
        _write_file(
            path,
            json.dumps(
                {
                    "name": name,
                    "files": [
                        {
                            "filename": "native.dll",
                            "functions": [{"name": "extension_call"}],
                        }
                    ],
                    "resourceType": "GMExtension",
                }
            ),
        )

    @staticmethod
    def _source_path_rejections(
        diagnostics: DiagnosticCollector,
    ):
        return [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]

    def _make_symlink(self, target: str, link_path: str) -> None:
        try:
            os.symlink(target, link_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

    def _write_extension(self, folder_name: str = "AdSDK", display_name: str = "AdSDK") -> None:
        _write_file(
            os.path.join(self.gm_dir, "extensions", folder_name, folder_name + ".yy"),
            textwrap.dedent(
                f"""\
                {{
                  "%Name": "{display_name}",
                  "name": "{display_name}",
                  "version": "1.2.3",
                  "platforms": ["windows", "android"],
                  "options": [{{"name": "app_id", "value": "demo"}}],
                  "constants": [{{"name": "ADS_READY", "value": 1}}],
                  "macros": [{{"name": "ADS_DEBUG", "value": "1"}}],
                  "files": [
                    {{
                      "filename": "ads.dll",
                      "platform": "windows",
                      "constants": [{{"name": "ADS_REWARDED", "value": 2}}],
                      "macros": [{{"name": "ADS_PLATFORM", "value": "windows"}}],
                      "options": [{{"name": "sdk", "value": "win"}}],
                      "functions": [
                        {{
                          "name": "ads_show_rewarded",
                          "externalName": "AdsShowRewarded",
                          "argCount": 1,
                          "returnType": "double",
                          "help": "Show rewarded ad"
                        }},
                        {{
                          "name": "analytics_track",
                          "externalName": "AnalyticsTrack",
                          "args": [{{"type": "string"}}, {{"type": "double"}}]
                        }}
                      ]
                    }},
                    {{
                      "filename": "ads_android.aar",
                      "copyToTargets": "android",
                      "functions": [
                        {{"name": "ads_show_rewarded", "externalName": "AdsShowRewardedAndroid", "argCount": 1}}
                      ]
                    }}
                  ],
                  "resourceType": "GMExtension",
                }}
                """
            ),
        )

    def test_parses_extension_metadata_and_reports_mapping_diagnostics(self) -> None:
        self._write_extension()

        entries = build_extension_entries(self.gm_dir)

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.name, "AdSDK")
        self.assertEqual(entry.source_path, "extensions/AdSDK/AdSDK.yy")
        self.assertEqual(entry.version, "1.2.3")
        self.assertEqual(entry.platforms, ("android", "windows"))
        self.assertEqual(entry.options[0]["name"], "app_id")
        self.assertEqual(entry.constants[0]["name"], "ADS_READY")
        self.assertEqual(entry.macros[0]["name"], "ADS_DEBUG")
        self.assertEqual(entry.files[0].platform, "windows")
        self.assertEqual(entry.files[0].constants[0]["name"], "ADS_REWARDED")
        self.assertEqual(entry.files[0].macros[0]["name"], "ADS_PLATFORM")
        self.assertEqual(entry.files[0].functions[0].arg_count, 1)
        self.assertEqual(entry.files[0].functions[1].arg_count, 2)

        report = render_extension_compatibility_report(entries, {"ads_show_rewarded"})
        diagnostics = report["diagnostics"]
        codes = [diagnostic["code"] for diagnostic in diagnostics]
        self.assertEqual(codes.count("extension_native_binding_required"), 2)
        self.assertEqual(codes.count("extension_function_mapping_required"), 1)
        mapping_diagnostics = [
            diagnostic
            for diagnostic in diagnostics
            if diagnostic["code"] == "extension_function_mapping_required"
        ]
        self.assertEqual(mapping_diagnostics[0]["function"], "analytics_track")
        bindings = {
            (binding["function"], binding["file"]): binding
            for binding in report["function_bindings"]
        }
        self.assertTrue(bindings[("ads_show_rewarded", "ads.dll")]["mapped"])
        self.assertFalse(bindings[("analytics_track", "ads.dll")]["mapped"])
        self.assertEqual(report["mapped_functions"], ["ads_show_rewarded"])
        self.assertEqual(report["stubs"][0]["path"], extension_stub_resource_path("AdSDK"))

    def test_renders_unique_actionable_stub_methods(self) -> None:
        self._write_extension()
        entry = build_extension_entries(self.gm_dir)[0]

        stub = render_extension_stub_script(entry)

        self.assertIn("extends EditorPlugin", stub)
        self.assertIn("# GameMaker extension: AdSDK", stub)
        self.assertIn("# Native file: ads.dll (windows)", stub)
        self.assertEqual(stub.count("func ads_show_rewarded(arg0):"), 1)
        self.assertIn("# Duplicate platform binding for ads_show_rewarded", stub)
        self.assertIn("func analytics_track(arg0, arg1):", stub)
        self.assertIn("needs a project-specific implementation", stub)

    def test_writes_report_and_plugin_stubs(self) -> None:
        self._write_extension(display_name="Ad SDK")
        _write_file(
            os.path.join(self.gm_dir, "gm2godot_extension_functions.json"),
            json.dumps({"functions": {"ads_show_rewarded": "AdBridge.show_rewarded"}}),
        )

        report_path = write_extension_compatibility_outputs(self.gm_dir, self.godot_dir)

        self.assertEqual(
            report_path,
            os.path.join(self.godot_dir, EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH),
        )
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        self.assertEqual(report["extensions"][0]["name"], "Ad SDK")
        self.assertIn("ads_show_rewarded", report["mapped_functions"])
        mapping_diagnostics = [
            diagnostic
            for diagnostic in report["diagnostics"]
            if diagnostic["code"] == "extension_function_mapping_required"
        ]
        self.assertEqual([diagnostic["function"] for diagnostic in mapping_diagnostics], ["analytics_track"])

        script_relative_path = extension_stub_relative_script_path("Ad SDK")
        script_path = os.path.join(self.godot_dir, script_relative_path)
        plugin_path = os.path.join(os.path.dirname(script_path), "plugin.cfg")
        self.assertTrue(os.path.isfile(script_path))
        self.assertTrue(os.path.isfile(plugin_path))
        with open(plugin_path, "r", encoding="utf-8") as f:
            plugin = f.read()
        self.assertIn('script="ad_sdk_extension.gd"', plugin)

    def test_report_replaces_final_symlink_without_mutating_referent(self) -> None:
        report_path = os.path.join(
            self.godot_dir,
            EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
        )
        os.makedirs(os.path.dirname(report_path))
        external_path = os.path.join(self.outside_dir, "report.json")
        _write_file(external_path, "external sentinel\n")
        self._make_symlink(external_path, report_path)

        returned_path = write_extension_compatibility_outputs(
            self.gm_dir,
            self.godot_dir,
        )

        self.assertEqual(returned_path, report_path)
        self.assertFalse(os.path.islink(report_path))
        with open(report_path, "r", encoding="utf-8") as report_file:
            self.assertEqual(json.load(report_file)["extensions"], [])
        with open(external_path, "r", encoding="utf-8") as external_file:
            self.assertEqual(external_file.read(), "external sentinel\n")

    def test_report_refuses_symlinked_output_directory(self) -> None:
        report_path = os.path.join(
            self.godot_dir,
            EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
        )
        external_directory = os.path.join(self.outside_dir, "report_directory")
        os.makedirs(external_directory)
        self._make_symlink(external_directory, os.path.dirname(report_path))

        with self.assertRaisesRegex(
            OSError,
            "redirected extension-report output directory",
        ):
            write_extension_compatibility_outputs(self.gm_dir, self.godot_dir)

        self.assertEqual(os.listdir(external_directory), [])

    def test_report_replaces_hardlink_without_mutating_referent(self) -> None:
        report_path = os.path.join(
            self.godot_dir,
            EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
        )
        os.makedirs(os.path.dirname(report_path))
        external_path = os.path.join(self.outside_dir, "report.json")
        _write_file(external_path, "external sentinel\n")
        try:
            os.link(external_path, report_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Hard links are unavailable: {error}")

        returned_path = write_extension_compatibility_outputs(
            self.gm_dir,
            self.godot_dir,
        )

        self.assertEqual(returned_path, report_path)
        with open(external_path, "r", encoding="utf-8") as external_file:
            self.assertEqual(external_file.read(), "external sentinel\n")
        with open(report_path, "r", encoding="utf-8") as report_file:
            self.assertEqual(json.load(report_file)["extensions"], [])
        self.assertNotEqual(
            os.stat(external_path).st_ino,
            os.stat(report_path).st_ino,
        )

    def test_report_refuses_nonregular_target(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable")
        report_path = os.path.join(
            self.godot_dir,
            EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
        )
        os.makedirs(os.path.dirname(report_path))
        os.mkfifo(report_path)

        with self.assertRaisesRegex(
            OSError,
            "non-regular extension compatibility report",
        ):
            write_extension_compatibility_outputs(self.gm_dir, self.godot_dir)

    def test_report_publish_failure_invalidates_previous_and_cleans_temp(self) -> None:
        report_path = os.path.join(
            self.godot_dir,
            EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
        )
        report_directory = os.path.dirname(report_path)
        _write_file(report_path, "previous report\n")
        os.chmod(report_path, 0o640)

        with patch(
            "src.conversion.extension_registry.os.replace",
            side_effect=OSError("report publish failed"),
        ):
            with self.assertRaisesRegex(OSError, "report publish failed"):
                write_extension_compatibility_outputs(
                    self.gm_dir,
                    self.godot_dir,
                )

        self.assertFalse(os.path.lexists(report_path))
        self.assertFalse(
            any(
                name.startswith(f".{os.path.basename(report_path)}.")
                for name in os.listdir(report_directory)
            )
        )

    def test_later_stub_failure_leaves_previous_report_absent(self) -> None:
        self._write_extension("First", "First")
        self._write_extension("Second", "Second")
        report_path = os.path.join(
            self.godot_dir,
            EXTENSION_COMPATIBILITY_REPORT_RELATIVE_PATH,
        )
        _write_file(report_path, "previous report\n")
        real_writer = getattr(extension_registry, "_write_extension_stub")
        write_count = 0

        def fail_second_stub(
            godot_project_path: str,
            entry: ExtensionEntry,
            *,
            stub_resource_path: str | None = None,
        ) -> None:
            nonlocal write_count
            write_count += 1
            if write_count == 2:
                raise OSError("later stub failed")
            real_writer(
                godot_project_path,
                entry,
                stub_resource_path=stub_resource_path,
            )

        with patch.object(
            extension_registry,
            "_write_extension_stub",
            side_effect=fail_second_stub,
        ):
            with self.assertRaisesRegex(OSError, "later stub failed"):
                write_extension_compatibility_outputs(
                    self.gm_dir,
                    self.godot_dir,
                )

        self.assertEqual(write_count, 2)
        self.assertFalse(os.path.lexists(report_path))

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are required")
    def test_confined_stub_writer_preserves_existing_mode_under_umask(self) -> None:
        confined_supported = getattr(
            extension_registry,
            "_confined_directory_fds_supported",
        )
        if not confined_supported():
            self.skipTest("directory-relative output operations are unavailable")
        self._write_extension()
        write_extension_compatibility_outputs(self.gm_dir, self.godot_dir)
        script_path = os.path.join(
            self.godot_dir,
            extension_stub_relative_script_path("AdSDK"),
        )
        plugin_path = os.path.join(os.path.dirname(script_path), "plugin.cfg")
        os.chmod(script_path, 0o664)
        os.chmod(plugin_path, 0o664)

        previous_umask = os.umask(0o077)
        try:
            write_extension_compatibility_outputs(self.gm_dir, self.godot_dir)
        finally:
            os.umask(previous_umask)

        self.assertEqual(stat.S_IMODE(os.stat(script_path).st_mode), 0o664)
        self.assertEqual(stat.S_IMODE(os.stat(plugin_path).st_mode), 0o664)

    def test_windows_fallback_does_not_require_os_fchmod(self) -> None:
        self._write_extension()

        with (
            patch.object(
                extension_registry,
                "_confined_directory_fds_supported",
                return_value=False,
            ),
            patch.object(
                os,
                "fchmod",
                side_effect=AssertionError("os.fchmod must not be called"),
                create=True,
            ),
        ):
            report_path = write_extension_compatibility_outputs(
                self.gm_dir,
                self.godot_dir,
            )

        self.assertTrue(os.path.isfile(report_path))
        script_path = os.path.join(
            self.godot_dir,
            extension_stub_relative_script_path("AdSDK"),
        )
        self.assertTrue(os.path.isfile(script_path))

    def test_windows_fallback_refuses_final_stub_symlink(self) -> None:
        external_path = os.path.join(self.outside_dir, "plugin.cfg")
        _write_file(external_path, "external sentinel\n")
        relative_path = os.path.join(
            "addons",
            "gm2godot_extensions",
            "safe",
            "plugin.cfg",
        )
        output_path = os.path.join(self.godot_dir, relative_path)
        os.makedirs(os.path.dirname(output_path))
        self._make_symlink(external_path, output_path)

        with patch.object(
            extension_registry,
            "_confined_directory_fds_supported",
            return_value=False,
        ):
            with self.assertRaisesRegex(
                OSError,
                "non-regular generated extension output",
            ):
                fallback_writer = getattr(
                    extension_registry,
                    "_atomic_write_extension_text",
                )
                fallback_writer(
                    self.godot_dir,
                    relative_path,
                    "replacement\n",
                )

        with open(external_path, "r", encoding="utf-8") as external_file:
            self.assertEqual(external_file.read(), "external sentinel\n")

    def test_writes_distinct_stubs_for_normalized_name_collisions(self) -> None:
        self._write_extension("Ext-One", "Ext-One")
        self._write_extension("Ext_One", "Ext_One")

        report_path = write_extension_compatibility_outputs(
            self.gm_dir,
            self.godot_dir,
        )

        with open(report_path, "r", encoding="utf-8") as report_file:
            report = json.load(report_file)
        stub_paths = {
            stub["extension"]: stub["path"]
            for stub in report["stubs"]
        }
        self.assertEqual(
            stub_paths,
            {
                "Ext-One": (
                    "res://addons/gm2godot_extensions/ext_one/"
                    "ext_one_extension.gd"
                ),
                "Ext_One": (
                    "res://addons/gm2godot_extensions/ext_one_2/"
                    "ext_one_2_extension.gd"
                ),
            },
        )
        for extension_name, stub_path in stub_paths.items():
            output_path = os.path.join(
                self.godot_dir,
                *stub_path.removeprefix("res://").split("/"),
            )
            with open(output_path, "r", encoding="utf-8") as script_file:
                self.assertIn(
                    f"# GameMaker extension: {extension_name}",
                    script_file.read(),
                )
            with open(
                os.path.join(os.path.dirname(output_path), "plugin.cfg"),
                "r",
                encoding="utf-8",
            ) as plugin_file:
                self.assertIn(
                    f'script="{os.path.basename(output_path)}"',
                    plugin_file.read(),
                )

    def test_refuses_extension_output_symlink_swaps_without_external_write(
        self,
    ) -> None:
        self._write_extension()
        real_writer = getattr(extension_registry, "_atomic_write_extension_text")

        for swap_level in ("addons", "managed_root"):
            with self.subTest(swap_level=swap_level):
                destination = os.path.join(self.godot_dir, swap_level)
                managed_root = os.path.join(
                    destination,
                    "addons",
                    "gm2godot_extensions",
                )
                os.makedirs(managed_root)
                external_target = os.path.join(
                    self.outside_dir,
                    swap_level,
                )
                os.makedirs(external_target)
                swapped = False

                def swap_then_write(
                    project_path: str,
                    relative_path: str,
                    content: str,
                ) -> None:
                    nonlocal swapped
                    if not swapped:
                        swapped = True
                        if swap_level == "addons":
                            shutil.rmtree(os.path.join(destination, "addons"))
                            self._make_symlink(
                                external_target,
                                os.path.join(destination, "addons"),
                            )
                        else:
                            shutil.rmtree(managed_root)
                            self._make_symlink(external_target, managed_root)
                    real_writer(project_path, relative_path, content)

                with patch.object(
                    extension_registry,
                    "_atomic_write_extension_text",
                    side_effect=swap_then_write,
                ):
                    with self.assertRaises(OSError):
                        write_extension_compatibility_outputs(
                            self.gm_dir,
                            destination,
                        )

                self.assertTrue(swapped)
                self.assertEqual(os.listdir(external_target), [])
                self.assertFalse(
                    os.path.exists(
                        os.path.join(
                            external_target,
                            "gm2godot_extensions",
                        )
                    )
                )

    def test_rejects_extensions_root_symlink_outside_project(self) -> None:
        outside_extensions = os.path.join(self.outside_dir, "extensions")
        self._write_minimal_extension(
            os.path.join(outside_extensions, "Outside", "Outside.yy"),
            "Outside",
        )
        self._make_symlink(
            outside_extensions,
            os.path.join(self.gm_dir, "extensions"),
        )
        diagnostics = DiagnosticCollector()
        logs: list[str] = []

        entries = build_extension_entries(
            self.gm_dir,
            diagnostics=diagnostics,
            log_callback=logs.append,
        )

        self.assertEqual(entries, ())
        rejected = self._source_path_rejections(diagnostics)
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "extensions")
        self.assertEqual(rejected[0].resource, "extensions")
        self.assertEqual(rejected[0].manifest_entry, "extensions directory")
        self.assertEqual(logs, [rejected[0].message])

    def test_rejects_extension_directory_symlink_outside_project(self) -> None:
        os.makedirs(os.path.join(self.gm_dir, "extensions"))
        outside_extension = os.path.join(self.outside_dir, "ExternalSDK")
        self._write_minimal_extension(
            os.path.join(outside_extension, "ExternalSDK.yy"),
            "ExternalSDK",
        )
        self._make_symlink(
            outside_extension,
            os.path.join(self.gm_dir, "extensions", "ExternalSDK"),
        )
        diagnostics = DiagnosticCollector()

        entries = build_extension_entries(
            self.gm_dir,
            diagnostics=diagnostics,
        )

        self.assertEqual(entries, ())
        rejected = self._source_path_rejections(diagnostics)
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, "extensions/ExternalSDK")
        self.assertEqual(rejected[0].resource, "ExternalSDK")
        self.assertEqual(rejected[0].manifest_entry, "extension directory")

    def test_rejects_extension_metadata_symlink_outside_project(self) -> None:
        extension_dir = os.path.join(self.gm_dir, "extensions", "ExternalSDK")
        os.makedirs(extension_dir)
        outside_yy = os.path.join(self.outside_dir, "ExternalSDK.yy")
        self._write_minimal_extension(outside_yy, "ExternalSDK")
        self._make_symlink(
            outside_yy,
            os.path.join(extension_dir, "ExternalSDK.yy"),
        )
        diagnostics = DiagnosticCollector()

        entries = build_extension_entries(
            self.gm_dir,
            diagnostics=diagnostics,
        )

        self.assertEqual(entries, ())
        rejected = self._source_path_rejections(diagnostics)
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(
            rejected[0].source_path,
            "extensions/ExternalSDK/ExternalSDK.yy",
        )
        self.assertEqual(rejected[0].manifest_entry, "extension metadata")

    def test_rejects_extension_metadata_symlink_to_contained_wrong_family(
        self,
    ) -> None:
        wrong_family_target = os.path.join(
            self.gm_dir,
            "objects",
            "o_extension_decoy",
            "o_extension_decoy.yy",
        )
        self._write_minimal_extension(wrong_family_target, "WrongFamilySDK")

        linked_name = "LinkedSDK"
        linked_metadata = os.path.join(
            self.gm_dir,
            "extensions",
            linked_name,
            linked_name + ".yy",
        )
        os.makedirs(os.path.dirname(linked_metadata), exist_ok=True)
        self._make_symlink(wrong_family_target, linked_metadata)

        safe_name = "SafeSDK"
        self._write_minimal_extension(
            os.path.join(
                self.gm_dir,
                "extensions",
                safe_name,
                safe_name + ".yy",
            ),
            safe_name,
        )
        diagnostics = DiagnosticCollector()

        with patch("builtins.open", wraps=open) as tracked_open:
            entries = build_extension_entries(
                self.gm_dir,
                diagnostics=diagnostics,
            )

        self.assertEqual([entry.name for entry in entries], [safe_name])
        opened_paths = {
            os.path.realpath(call.args[0])
            for call in tracked_open.call_args_list
            if call.args and isinstance(call.args[0], str)
        }
        self.assertNotIn(os.path.realpath(wrong_family_target), opened_paths)
        rejected = self._source_path_rejections(diagnostics)
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(
            rejected[0].source_path,
            f"extensions/{linked_name}/{linked_name}.yy",
        )
        self.assertEqual(rejected[0].resource, linked_name)
        self.assertEqual(rejected[0].manifest_entry, "extension metadata")

    def test_rejects_external_extension_mapping_symlink(self) -> None:
        self._write_extension()
        outside_mapping = os.path.join(
            self.outside_dir,
            "gm2godot_extension_functions.json",
        )
        _write_file(
            outside_mapping,
            json.dumps(
                {"functions": {"ads_show_rewarded": "AdBridge.show"}}
            ),
        )
        self._make_symlink(
            outside_mapping,
            os.path.join(
                self.gm_dir,
                "gm2godot_extension_functions.json",
            ),
        )
        diagnostics = DiagnosticCollector()

        report_path = write_extension_compatibility_outputs(
            self.gm_dir,
            self.godot_dir,
            diagnostics=diagnostics,
        )

        with open(report_path, "r", encoding="utf-8") as report_file:
            report = json.load(report_file)
        self.assertEqual(report["mapped_functions"], [])
        rejected = self._source_path_rejections(diagnostics)
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(
            rejected[0].source_path,
            "gm2godot_extension_functions.json",
        )
        self.assertEqual(
            rejected[0].manifest_entry,
            "extension function mapping",
        )

    def test_revalidates_extension_metadata_immediately_before_read(self) -> None:
        yy_path = os.path.join(
            self.gm_dir,
            "extensions",
            "SwapSDK",
            "SwapSDK.yy",
        )
        self._write_minimal_extension(yy_path, "SafeSDK")
        outside_yy = os.path.join(self.outside_dir, "SwapSDK.yy")
        self._write_minimal_extension(outside_yy, "OutsideSDK")
        diagnostics = DiagnosticCollector()
        real_resolver = extension_registry.resolve_project_filesystem_source_path
        metadata_resolutions = 0

        def _swap_before_revalidation(
            project_root: str,
            candidate: str,
        ) -> ResolvedProjectSourcePath:
            nonlocal metadata_resolutions
            if os.path.abspath(candidate) == os.path.abspath(yy_path):
                metadata_resolutions += 1
                if metadata_resolutions == 2:
                    os.unlink(yy_path)
                    self._make_symlink(outside_yy, yy_path)
            return real_resolver(project_root, candidate)

        with patch(
            "src.conversion.extension_registry.resolve_project_filesystem_source_path",
            side_effect=_swap_before_revalidation,
        ):
            entries = build_extension_entries(
                self.gm_dir,
                diagnostics=diagnostics,
            )

        self.assertEqual(metadata_resolutions, 2)
        self.assertEqual(entries, ())
        rejected = self._source_path_rejections(diagnostics)
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].manifest_entry, "extension metadata")


if __name__ == "__main__":
    unittest.main()
