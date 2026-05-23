from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

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


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class TestExtensionRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

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


if __name__ == "__main__":
    unittest.main()
