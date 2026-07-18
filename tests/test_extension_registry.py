from __future__ import annotations

import json
import os
import shutil
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
