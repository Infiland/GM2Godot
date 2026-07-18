import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.shaders import ShaderConverter
from src.conversion.asset_output_paths import build_asset_output_paths
from src.conversion.converter import Converter
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.project_source_paths import ResolvedProjectSourcePath

SAMPLE_FSH = """\
precision highp float;
varying vec2 v_vTexcoord;
varying vec4 v_vColour;
uniform sampler2D gm_BaseTexture;

void main()
{
    vec4 col = texture2D(gm_BaseTexture, v_vTexcoord);
    gl_FragColor = col * v_vColour;
}
"""


class _EnabledSetting:
    def get(self) -> bool:
        return True


class TestShaderConverterBasic(unittest.TestCase):
    """Test ShaderConverter converts .fsh files to .gdshader."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        shaders_dir = os.path.join(self.gm_dir, "shaders")
        os.makedirs(shaders_dir)

        self.fsh_path = os.path.join(shaders_dir, "test_shader.fsh")
        with open(self.fsh_path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_FSH)

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _make_converter(self):
        return ShaderConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )

    def test_creates_gdshader_file(self):
        converter = self._make_converter()
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "shaders", "test_shader.gdshader")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected {expected} to exist after conversion")

    def test_resource_outcome_counts_logical_shader_asset(self):
        converter = self._make_converter()

        converter.convert_all()
        counts = converter.conversion_step_result().resources

        self.assertEqual(counts.requested, 1)
        self.assertEqual(counts.executed, 1)
        self.assertEqual(counts.completed, 1)
        self.assertEqual(counts.skipped, 0)
        self.assertEqual(counts.failed, 0)

    def test_disappearing_only_stage_fails_without_placeholder(self):
        safe_stage_path = os.path.join(
            self.gm_dir,
            "shaders",
            "safe_shader.fsh",
        )
        with open(safe_stage_path, "w", encoding="utf-8") as safe_stage:
            safe_stage.write(SAMPLE_FSH)
        stage_path = self.fsh_path

        class UnlinkAfterDiscoveryShaderConverter(ShaderConverter):
            def _disk_shader_assets(
                self,
                shader_root: ResolvedProjectSourcePath,
            ):
                assets = super()._disk_shader_assets(shader_root)
                os.unlink(stage_path)
                return assets

        converter = UnlinkAfterDiscoveryShaderConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        output = os.path.join(
            self.godot_dir,
            "shaders",
            "test_shader.gdshader",
        )
        safe_output = os.path.join(
            self.godot_dir,
            "shaders",
            "safe_shader.gdshader",
        )
        self.assertFalse(os.path.exists(output))
        self.assertTrue(os.path.isfile(safe_output))
        counts = converter.conversion_step_result().resources
        self.assertEqual(counts.requested, 2)
        self.assertEqual(counts.executed, 2)
        self.assertEqual(counts.completed, 1)
        self.assertEqual(counts.skipped, 0)
        self.assertEqual(counts.failed, 1)

    def test_disappearing_one_of_two_stages_fails_whole_shader(self) -> None:
        vertex_path = os.path.join(
            self.gm_dir,
            "shaders",
            "test_shader.vsh",
        )
        with open(vertex_path, "w", encoding="utf-8") as vertex_file:
            vertex_file.write(
                "attribute vec3 in_Position;\n"
                "void main() { gl_Position = vec4(in_Position, 1.0); }\n"
            )
        fragment_path = self.fsh_path

        class UnlinkFragmentAfterDiscoveryShaderConverter(ShaderConverter):
            def _disk_shader_assets(
                self,
                shader_root: ResolvedProjectSourcePath,
            ):
                assets = super()._disk_shader_assets(shader_root)
                os.unlink(fragment_path)
                return assets

        converter = UnlinkFragmentAfterDiscoveryShaderConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        )

        converter.convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "shaders",
                    "test_shader.gdshader",
                )
            )
        )
        self.assertEqual(
            converter.conversion_step_result().resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )

    def test_blank_only_stage_fails_without_header_only_shader(self) -> None:
        with open(self.fsh_path, "w", encoding="utf-8") as fragment_file:
            fragment_file.write("  \n\t")
        converter = self._make_converter()

        converter.convert_all()

        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "shaders",
                    "test_shader.gdshader",
                )
            )
        )
        self.assertEqual(
            converter.conversion_step_result().resources,
            ConversionCounts(requested=1, executed=1, failed=1),
        )

    def test_gl_fragcolor_converted_to_color(self):
        converter = self._make_converter()
        converter.convert_all()

        output = os.path.join(self.godot_dir, "shaders", "test_shader.gdshader")
        with open(output, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("gl_FragColor", content)
        self.assertIn("COLOR", content)

    def test_texture2d_converted_to_texture(self):
        converter = self._make_converter()
        converter.convert_all()

        output = os.path.join(self.godot_dir, "shaders", "test_shader.gdshader")
        with open(output, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("texture2D", content)
        self.assertIn("texture(", content)

    def test_precision_replaced_with_shader_type(self):
        converter = self._make_converter()
        converter.convert_all()

        output = os.path.join(self.godot_dir, "shaders", "test_shader.gdshader")
        with open(output, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("precision highp float", content)
        self.assertIn("shader_type canvas_item", content)

    def test_main_replaced_with_fragment(self):
        converter = self._make_converter()
        converter.convert_all()

        output = os.path.join(self.godot_dir, "shaders", "test_shader.gdshader")
        with open(output, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("void main()", content)
        self.assertIn("void fragment()", content)

    def test_gm_base_texture_replaced(self):
        converter = self._make_converter()
        converter.convert_all()

        output = os.path.join(self.godot_dir, "shaders", "test_shader.gdshader")
        with open(output, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("gm_BaseTexture", content)
        self.assertIn("TEXTURE", content)


class TestShaderConverterEmpty(unittest.TestCase):
    """No shaders directory should not crash."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []
        # No shaders directory created

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_no_shaders_dir_no_crash(self):
        converter = ShaderConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()  # should not raise
        self.assertTrue(len(self.logs) > 0,
                        "Expected log message when shaders directory missing")


class TestShaderGeneratedPathCollisions(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        for resource_name, marker in (("shdGlow", "MARKER_ONE"), ("shd_glow", "MARKER_TWO")):
            shader_dir = os.path.join(self.gm_dir, "shaders", resource_name)
            os.makedirs(shader_dir)
            with open(os.path.join(shader_dir, resource_name + ".yy"), "w", encoding="utf-8") as yy_file:
                yy_file.write(
                    '{"name":"' + resource_name
                    + '","parent":{"name":"Shaders","path":"folders/Shaders.yy"}}'
                )
            with open(os.path.join(shader_dir, resource_name + ".fsh"), "w", encoding="utf-8") as shader_file:
                shader_file.write(SAMPLE_FSH + "\n// " + marker + "\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_emitted_shaders_match_collision_safe_registry_paths(self) -> None:
        converter = ShaderConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        paths = build_asset_output_paths(self.gm_dir, self.godot_dir)["shaders"]
        self.assertEqual(len({path.casefold() for path in paths.values()}), 2)
        contents: list[str] = []
        for resource_name in ("shdGlow", "shd_glow"):
            output_path = os.path.join(
                self.godot_dir,
                *paths[resource_name].removeprefix("res://").split("/"),
            )
            with open(output_path, encoding="utf-8") as shader_file:
                contents.append(shader_file.read())
        self.assertIn("MARKER_ONE", contents[0])
        self.assertIn("MARKER_TWO", contents[1])


class TestShaderAssetOwnershipAndStages(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_shader_asset(
        self,
        resource_name: str,
        *,
        vertex_source: str | None = None,
        fragment_source: str | None = None,
    ) -> str:
        shader_dir = os.path.join(self.gm_dir, "shaders", resource_name)
        os.makedirs(shader_dir)
        yy_path = os.path.join(shader_dir, resource_name + ".yy")
        with open(yy_path, "w", encoding="utf-8") as yy_file:
            json.dump(
                {
                    "name": resource_name,
                    "resourceType": "GMShader",
                    "parent": {
                        "name": "Shaders",
                        "path": "folders/Shaders.yy",
                    },
                },
                yy_file,
            )
        if vertex_source is not None:
            with open(
                os.path.join(shader_dir, resource_name + ".vsh"),
                "w",
                encoding="utf-8",
            ) as vertex_file:
                vertex_file.write(vertex_source)
        if fragment_source is not None:
            with open(
                os.path.join(shader_dir, resource_name + ".fsh"),
                "w",
                encoding="utf-8",
            ) as fragment_file:
                fragment_file.write(fragment_source)
        return f"shaders/{resource_name}/{resource_name}.yy"

    def _write_yyp(self, resources: list[tuple[str, str]]) -> None:
        with open(
            os.path.join(self.gm_dir, "ShaderOwnership.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump(
                {
                    "%Name": "Shader Ownership",
                    "resources": [
                        {"id": {"name": name, "path": path}}
                        for name, path in resources
                    ],
                },
                project_file,
            )

    def _convert(self) -> None:
        ShaderConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=lambda _message: None,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=2,
        ).convert_all()

    def test_dual_stage_asset_publishes_one_complete_shader(self) -> None:
        vertex_source = """\
precision highp float;
varying vec2 v_shared;
uniform float amount;

void main()
{
    v_shared = vec2(amount);
}
// VERTEX_MARKER
"""
        fragment_source = """\
precision mediump float;
varying vec2 v_shared;
uniform float amount;

void main()
{
    gl_FragColor = vec4(v_shared, amount, 1.0);
}
// FRAGMENT_MARKER
"""
        shader_path = self._write_shader_asset(
            "shdPair",
            vertex_source=vertex_source,
            fragment_source=fragment_source,
        )
        self._write_yyp([("shdPair", shader_path)])

        self._convert()

        resource_path = build_asset_output_paths(
            self.gm_dir,
            self.godot_dir,
        )["shaders"]["shdPair"]
        output_path = os.path.join(
            self.godot_dir,
            *resource_path.removeprefix("res://").split("/"),
        )
        with open(output_path, encoding="utf-8") as shader_file:
            content = shader_file.read()

        self.assertEqual(content.count("shader_type canvas_item;"), 1)
        self.assertEqual(content.count("varying vec2 v_shared;"), 1)
        self.assertEqual(content.count("uniform float amount;"), 1)
        self.assertEqual(content.count("void vertex()"), 1)
        self.assertEqual(content.count("void fragment()"), 1)
        self.assertIn("VERTEX_MARKER", content)
        self.assertIn("FRAGMENT_MARKER", content)
        self.assertNotIn("precision ", content)

    def test_yyp_ownership_excludes_orphan_normalized_path_collision(self) -> None:
        referenced_path = self._write_shader_asset(
            "shdGlow",
            fragment_source=SAMPLE_FSH + "\n// REFERENCED_MARKER\n",
        )
        self._write_shader_asset(
            "shd_glow",
            fragment_source=SAMPLE_FSH + "\n// ORPHAN_MARKER\n",
        )
        self._write_yyp([("shdGlow", referenced_path)])

        self._convert()

        paths = build_asset_output_paths(self.gm_dir, self.godot_dir)["shaders"]
        self.assertEqual(set(paths), {"shdGlow"})
        output_path = os.path.join(
            self.godot_dir,
            *paths["shdGlow"].removeprefix("res://").split("/"),
        )
        with open(output_path, encoding="utf-8") as shader_file:
            content = shader_file.read()
        self.assertIn("REFERENCED_MARKER", content)
        self.assertNotIn("ORPHAN_MARKER", content)
        generated_shaders = [
            os.path.join(root, filename)
            for root, _directories, filenames in os.walk(
                os.path.join(self.godot_dir, "shaders")
            )
            for filename in filenames
            if filename.endswith(".gdshader")
        ]
        self.assertEqual(generated_shaders, [output_path])


class TestShaderManifestOutcomeAccounting(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def _write_yyp(self, resources: list[dict[str, object]]) -> None:
        with open(
            os.path.join(self.gm_dir, "ShaderAccounting.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            json.dump(
                {
                    "%Name": "Shader Accounting",
                    "resources": resources,
                },
                project_file,
            )

    @staticmethod
    def _shader_declaration(name: str, path: str) -> dict[str, object]:
        return {
            "id": {"name": name, "path": path},
            "resourceType": "GMShader",
        }

    def _make_converter(
        self,
        *,
        diagnostics: DiagnosticCollector | None = None,
    ) -> ShaderConverter:
        return ShaderConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            max_workers=2,
            diagnostics=diagnostics,
        )

    def test_missing_only_manifest_shader_makes_converter_outcome_partial(
        self,
    ) -> None:
        self._write_yyp(
            [
                self._shader_declaration(
                    "shd_missing",
                    "shaders/shd_missing/shd_missing.yy",
                )
            ]
        )
        running = threading.Event()
        running.set()
        converter = Converter(
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            status_callback=lambda _message: None,
            conversion_running=running,
            max_workers=1,
        )

        outcome = converter.convert(
            self.gm_dir,
            "windows",
            self.godot_dir,
            {"shaders": _EnabledSetting()},
        )

        self.assertEqual(outcome.state, "partial")
        self.assertEqual(
            outcome.resources,
            ConversionCounts(requested=1, skipped=1),
        )
        self.assertEqual(
            outcome.converters,
            ConversionCounts(requested=1, executed=1, completed=1),
        )

    def test_safe_and_missing_manifest_shaders_have_strict_counts(self) -> None:
        safe_directory = os.path.join(
            self.gm_dir,
            "shaders",
            "shd_safe",
        )
        os.makedirs(safe_directory)
        with open(
            os.path.join(safe_directory, "shd_safe.yy"),
            "w",
            encoding="utf-8",
        ) as metadata_file:
            json.dump(
                {"name": "shd_safe", "resourceType": "GMShader"},
                metadata_file,
            )
        with open(
            os.path.join(safe_directory, "shd_safe.fsh"),
            "w",
            encoding="utf-8",
        ) as fragment_file:
            fragment_file.write(SAMPLE_FSH)
        self._write_yyp(
            [
                self._shader_declaration(
                    "shd_missing",
                    "shaders/shd_missing/shd_missing.yy",
                ),
                self._shader_declaration(
                    "shd_safe",
                    "shaders/shd_safe/shd_safe.yy",
                ),
            ]
        )

        converter = self._make_converter()
        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result().resources,
            ConversionCounts(
                requested=2,
                executed=1,
                completed=1,
                skipped=1,
            ),
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "shaders",
                    "shd_safe.gdshader",
                )
            )
        )

    def test_declared_shader_without_stages_is_skipped(self) -> None:
        shader_directory = os.path.join(
            self.gm_dir,
            "shaders",
            "shd_empty",
        )
        os.makedirs(shader_directory)
        with open(
            os.path.join(shader_directory, "shd_empty.yy"),
            "w",
            encoding="utf-8",
        ) as metadata_file:
            json.dump(
                {"name": "shd_empty", "resourceType": "GMShader"},
                metadata_file,
            )
        self._write_yyp(
            [
                self._shader_declaration(
                    "shd_empty",
                    "shaders/shd_empty/shd_empty.yy",
                )
            ]
        )
        diagnostics = DiagnosticCollector()

        converter = self._make_converter(diagnostics=diagnostics)
        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result().resources,
            ConversionCounts(requested=1, skipped=1),
        )
        unavailable = [
            diagnostic
            for diagnostic in diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SHADER-SOURCE-UNAVAILABLE"
        ]
        self.assertEqual(len(unavailable), 1, unavailable)
        self.assertEqual(unavailable[0].resource, "shd_empty")

    def test_duplicate_manifest_shader_declaration_is_counted_once(self) -> None:
        declaration = self._shader_declaration(
            "shd_missing",
            "shaders/shd_missing/shd_missing.yy",
        )
        self._write_yyp([declaration, declaration])

        converter = self._make_converter()
        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result().resources,
            ConversionCounts(requested=1, skipped=1),
        )

    def test_malformed_yyp_uses_contained_disk_fallback(self) -> None:
        shader_directory = os.path.join(
            self.gm_dir,
            "shaders",
            "shd_fallback",
        )
        os.makedirs(shader_directory)
        with open(
            os.path.join(shader_directory, "shd_fallback.fsh"),
            "w",
            encoding="utf-8",
        ) as fragment_file:
            fragment_file.write(SAMPLE_FSH)
        with open(
            os.path.join(self.gm_dir, "ShaderAccounting.yyp"),
            "w",
            encoding="utf-8",
        ) as project_file:
            project_file.write("{ malformed")

        converter = self._make_converter()
        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result().resources,
            ConversionCounts(requested=1, executed=1, completed=1),
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    self.godot_dir,
                    "shaders",
                    "shd_fallback.gdshader",
                )
            )
        )

    def test_valid_yyp_does_not_use_disk_fallback_for_orphan_shader(self) -> None:
        shader_directory = os.path.join(
            self.gm_dir,
            "shaders",
            "shd_orphan",
        )
        os.makedirs(shader_directory)
        with open(
            os.path.join(shader_directory, "shd_orphan.fsh"),
            "w",
            encoding="utf-8",
        ) as fragment_file:
            fragment_file.write(SAMPLE_FSH)
        self._write_yyp([])

        converter = self._make_converter()
        converter.convert_all()

        self.assertEqual(
            converter.conversion_step_result().resources,
            ConversionCounts(),
        )
        self.assertFalse(
            os.path.exists(
                os.path.join(
                    self.godot_dir,
                    "shaders",
                    "shd_orphan.gdshader",
                )
            )
        )


class TestShaderSourcePathContainment(unittest.TestCase):
    def setUp(self) -> None:
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.outside_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.gm_dir, "shaders"))
        self.diagnostics = DiagnosticCollector()
        self.logs: list[str] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)
        shutil.rmtree(self.outside_dir)

    @staticmethod
    def _write_json(path: str, value: object) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as output_file:
            json.dump(value, output_file)

    @staticmethod
    def _write_fragment(path: str, marker: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fragment_file:
            fragment_file.write(SAMPLE_FSH + f"\n// {marker}\n")

    def _write_yyp(self, resources: list[tuple[str, str]]) -> str:
        yyp_path = os.path.join(self.gm_dir, "ShaderContainment.yyp")
        self._write_json(
            yyp_path,
            {
                "%Name": "Shader Containment",
                "resources": [
                    {
                        "id": {"name": name, "path": path},
                        "resourceType": "GMShader",
                    }
                    for name, path in resources
                ],
            },
        )
        return yyp_path

    def _make_converter(self) -> ShaderConverter:
        return ShaderConverter(
            self.gm_dir,
            self.godot_dir,
            log_callback=self.logs.append,
            progress_callback=lambda _value: None,
            conversion_running=lambda: True,
            diagnostics=self.diagnostics,
        )

    def _source_path_rejections(self):
        return [
            diagnostic
            for diagnostic in self.diagnostics.diagnostics()
            if diagnostic.code == "GM2GD-SOURCE-PATH-REJECTED"
        ]

    def _generated_shaders(self) -> list[str]:
        return [
            os.path.join(root, filename)
            for root, _directories, filenames in os.walk(self.godot_dir)
            for filename in filenames
            if filename.endswith(".gdshader")
        ]

    def test_rejects_malformed_manifest_shader_paths_with_yyp_diagnostics(
        self,
    ) -> None:
        outside_yy = os.path.join(self.outside_dir, "outside.yy")
        self._write_json(
            outside_yy,
            {"name": "outside", "resourceType": "GMShader"},
        )
        self._write_fragment(
            os.path.splitext(outside_yy)[0] + ".fsh",
            "OUTSIDE_MANIFEST_STAGE",
        )
        relative_outside = os.path.relpath(outside_yy, self.gm_dir).replace(
            os.sep,
            "/",
        )
        unsafe_paths = [
            f"shaders/../{relative_outside}",
            outside_yy,
            r"C:\Games\Outside\shader.yy",
            r"C:Outside\shader.yy",
            r"\\server\share\shader.yy",
            "shaders/bad\0shader.yy",
        ]
        self._write_yyp(
            [
                (f"shd_unsafe_{index}", path)
                for index, path in enumerate(unsafe_paths)
            ]
        )

        converter = self._make_converter()
        converter.convert_all()

        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), len(unsafe_paths), rejected)
        self.assertEqual(
            {diagnostic.resource for diagnostic in rejected},
            {f"shd_unsafe_{index}" for index in range(len(unsafe_paths))},
        )
        self.assertEqual(
            {diagnostic.source_path for diagnostic in rejected},
            {"ShaderContainment.yyp"},
        )
        self.assertEqual(
            {diagnostic.manifest_entry for diagnostic in rejected},
            {
                f"resources[{index}].id.path"
                for index in range(len(unsafe_paths))
            },
        )
        self.assertTrue(
            all(diagnostic.resource_type == "shader" for diagnostic in rejected)
        )
        self.assertEqual(self._generated_shaders(), [])
        self.assertEqual(
            converter.conversion_step_result().resources,
            ConversionCounts(
                requested=len(unsafe_paths),
                skipped=len(unsafe_paths),
            ),
        )

    def test_rejects_manifest_yy_and_stage_symlink_escapes(self) -> None:
        outside_yy = os.path.join(self.outside_dir, "outside.yy")
        outside_fragment = os.path.join(self.outside_dir, "outside.fsh")
        self._write_json(
            outside_yy,
            {"name": "outside", "resourceType": "GMShader"},
        )
        self._write_fragment(outside_fragment, "OUTSIDE_FILE_LINK")

        yy_link_directory = os.path.join(
            self.gm_dir,
            "shaders",
            "shd_yy_link",
        )
        os.makedirs(yy_link_directory)
        stage_link_directory = os.path.join(
            self.gm_dir,
            "shaders",
            "shd_stage_link",
        )
        os.makedirs(stage_link_directory)
        self._write_json(
            os.path.join(stage_link_directory, "shd_stage_link.yy"),
            {"name": "shd_stage_link", "resourceType": "GMShader"},
        )

        outside_asset_directory = os.path.join(
            self.outside_dir,
            "outside_asset",
        )
        self._write_json(
            os.path.join(outside_asset_directory, "shd_directory_link.yy"),
            {"name": "shd_directory_link", "resourceType": "GMShader"},
        )
        self._write_fragment(
            os.path.join(outside_asset_directory, "shd_directory_link.fsh"),
            "OUTSIDE_DIRECTORY_LINK",
        )
        try:
            os.symlink(
                outside_yy,
                os.path.join(yy_link_directory, "shd_yy_link.yy"),
            )
            os.symlink(
                outside_fragment,
                os.path.join(stage_link_directory, "shd_stage_link.fsh"),
            )
            os.symlink(
                outside_asset_directory,
                os.path.join(
                    self.gm_dir,
                    "shaders",
                    "shd_directory_link",
                ),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        self._write_yyp(
            [
                ("shd_yy_link", "shaders/shd_yy_link/shd_yy_link.yy"),
                (
                    "shd_stage_link",
                    "shaders/shd_stage_link/shd_stage_link.yy",
                ),
                (
                    "shd_directory_link",
                    "shaders/shd_directory_link/shd_directory_link.yy",
                ),
            ]
        )

        converter = self._make_converter()
        converter.convert_all()

        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 3, rejected)
        self.assertEqual(
            {diagnostic.resource for diagnostic in rejected},
            {"shd_yy_link", "shd_stage_link", "shd_directory_link"},
        )
        stage_rejection = next(
            diagnostic
            for diagnostic in rejected
            if diagnostic.resource == "shd_stage_link"
        )
        self.assertEqual(
            stage_rejection.source_path,
            "shaders/shd_stage_link/shd_stage_link.yy",
        )
        self.assertEqual(stage_rejection.manifest_entry, "derived .fsh stage")
        self.assertEqual(self._generated_shaders(), [])
        self.assertEqual(
            converter.conversion_step_result().resources,
            ConversionCounts(requested=3, skipped=3),
        )

    def test_manifest_requires_shader_yy_family_and_suffix(self) -> None:
        cross_family_yy = os.path.join(
            self.gm_dir,
            "objects",
            "shd_cross_family",
            "shd_cross_family.yy",
        )
        self._write_json(
            cross_family_yy,
            {"name": "shd_cross_family", "resourceType": "GMShader"},
        )
        self._write_fragment(
            os.path.splitext(cross_family_yy)[0] + ".fsh",
            "CROSS_FAMILY_STAGE",
        )
        non_yy_path = os.path.join(
            self.gm_dir,
            "shaders",
            "shd_non_yy",
            "shd_non_yy.fsh",
        )
        self._write_fragment(non_yy_path, "NON_YY_MANIFEST_STAGE")
        safe_yy = os.path.join(
            self.gm_dir,
            "shaders",
            "shd_safe",
            "shd_safe.yy",
        )
        self._write_json(
            safe_yy,
            {"name": "shd_safe", "resourceType": "GMShader"},
        )
        self._write_fragment(
            os.path.splitext(safe_yy)[0] + ".fsh",
            "SAFE_MANIFEST_STAGE",
        )
        self._write_yyp(
            [
                (
                    "shd_cross_family",
                    "shaders/../objects/shd_cross_family/shd_cross_family.yy",
                ),
                ("shd_non_yy", "shaders/shd_non_yy/shd_non_yy.fsh"),
                ("shd_safe", "shaders/shd_safe/shd_safe.yy"),
            ]
        )

        converter = self._make_converter()
        converter.convert_all()

        rejected = self._source_path_rejections()
        self.assertEqual(
            [
                (
                    diagnostic.resource,
                    diagnostic.source_path,
                    diagnostic.manifest_entry,
                )
                for diagnostic in rejected
            ],
            [
                (
                    "shd_cross_family",
                    "ShaderContainment.yyp",
                    "resources[0].id.path",
                ),
                (
                    "shd_non_yy",
                    "ShaderContainment.yyp",
                    "resources[1].id.path",
                ),
            ],
        )
        generated = self._generated_shaders()
        self.assertEqual(len(generated), 1, generated)
        with open(generated[0], encoding="utf-8") as shader_file:
            contents = shader_file.read()
        self.assertIn("SAFE_MANIFEST_STAGE", contents)
        self.assertNotIn("CROSS_FAMILY_STAGE", contents)
        self.assertNotIn("NON_YY_MANIFEST_STAGE", contents)
        self.assertEqual(
            converter.conversion_step_result().resources,
            ConversionCounts(
                requested=3,
                executed=1,
                completed=1,
                skipped=2,
            ),
        )

    def test_disk_fallback_rejects_file_and_directory_symlink_escapes(
        self,
    ) -> None:
        outside_fragment = os.path.join(self.outside_dir, "outside.fsh")
        self._write_fragment(outside_fragment, "OUTSIDE_DISK_FILE")
        outside_shader_directory = os.path.join(
            self.outside_dir,
            "outside_shader_directory",
        )
        self._write_fragment(
            os.path.join(outside_shader_directory, "outside_dir.fsh"),
            "OUTSIDE_DISK_DIRECTORY",
        )
        containing_directory = os.path.join(
            self.gm_dir,
            "shaders",
            "contained",
        )
        self._write_fragment(
            os.path.join(containing_directory, "shd_safe_sibling.fsh"),
            "SAFE_DISK_SIBLING",
        )
        try:
            os.symlink(
                outside_fragment,
                os.path.join(containing_directory, "shd_file_link.fsh"),
            )
            os.symlink(
                outside_shader_directory,
                os.path.join(containing_directory, "linked_directory"),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        self._make_converter().convert_all()

        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 2, rejected)
        self.assertEqual(
            {
                (
                    diagnostic.resource,
                    diagnostic.source_path,
                    diagnostic.manifest_entry,
                )
                for diagnostic in rejected
            },
            {
                (
                    "shd_file_link",
                    "shaders/contained",
                    "discovered .fsh stage",
                ),
                (
                    "linked_directory",
                    "shaders/contained",
                    "discovered shader directory",
                ),
            },
        )
        generated = self._generated_shaders()
        self.assertEqual(len(generated), 1, generated)
        with open(generated[0], encoding="utf-8") as shader_file:
            contents = shader_file.read()
        self.assertIn("SAFE_DISK_SIBLING", contents)
        self.assertNotIn("OUTSIDE_DISK_FILE", contents)
        self.assertNotIn("OUTSIDE_DISK_DIRECTORY", contents)

    def test_disk_fallback_rejects_yy_symlink_but_converts_safe_stage(
        self,
    ) -> None:
        shader_directory = os.path.join(
            self.gm_dir,
            "shaders",
            "shd_safe_stage",
        )
        self._write_fragment(
            os.path.join(shader_directory, "shd_safe_stage.fsh"),
            "SAFE_STAGE",
        )
        outside_yy = os.path.join(self.outside_dir, "outside.yy")
        self._write_json(
            outside_yy,
            {"name": "outside_name", "resourceType": "GMShader"},
        )
        try:
            os.symlink(
                outside_yy,
                os.path.join(shader_directory, "shd_safe_stage.yy"),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")

        self._make_converter().convert_all()

        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].resource, "shd_safe_stage")
        self.assertEqual(rejected[0].manifest_entry, "discovered .yy")
        self.assertEqual(
            rejected[0].source_path,
            "shaders/shd_safe_stage",
        )
        generated = self._generated_shaders()
        self.assertEqual(len(generated), 1, generated)
        with open(generated[0], encoding="utf-8") as shader_file:
            self.assertIn("SAFE_STAGE", shader_file.read())

    def test_disk_fallback_rejects_contained_cross_family_shader_yy_link(
        self,
    ) -> None:
        linked_name = "shd_cross_family_link"
        wrong_family_yy = os.path.join(
            self.gm_dir,
            "objects",
            "wrong_shader",
            "target.yy",
        )
        self._write_json(
            wrong_family_yy,
            {
                "name": "WRONG_FAMILY_SHADER_NAME",
                "resourceType": "GMShader",
            },
        )
        linked_directory = os.path.join(self.gm_dir, "shaders", linked_name)
        os.makedirs(linked_directory)
        try:
            os.symlink(
                wrong_family_yy,
                os.path.join(linked_directory, linked_name + ".yy"),
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symbolic links are unavailable: {error}")
        self._write_fragment(
            os.path.join(linked_directory, linked_name + ".fsh"),
            "LINKED_DIRECTORY_SAFE_STAGE",
        )

        safe_name = "shd_safe_sibling"
        safe_directory = os.path.join(self.gm_dir, "shaders", safe_name)
        self._write_json(
            os.path.join(safe_directory, safe_name + ".yy"),
            {"name": safe_name, "resourceType": "GMShader"},
        )
        self._write_fragment(
            os.path.join(safe_directory, safe_name + ".fsh"),
            "SAFE_SIBLING_STAGE",
        )

        self._make_converter().convert_all()

        generated = self._generated_shaders()
        self.assertEqual(len(generated), 2, generated)
        generated_by_name = {os.path.basename(path): path for path in generated}
        self.assertNotIn("wrong_family_shader_name.gdshader", generated_by_name)
        with open(
            generated_by_name[linked_name + ".gdshader"],
            encoding="utf-8",
        ) as shader_file:
            self.assertIn("LINKED_DIRECTORY_SAFE_STAGE", shader_file.read())
        with open(
            generated_by_name[safe_name + ".gdshader"],
            encoding="utf-8",
        ) as shader_file:
            self.assertIn("SAFE_SIBLING_STAGE", shader_file.read())
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].source_path, f"shaders/{linked_name}")
        self.assertEqual(rejected[0].resource, linked_name)
        self.assertEqual(rejected[0].resource_type, "shader")
        self.assertEqual(rejected[0].manifest_entry, "discovered .yy")

    def test_convert_shader_rejects_direct_source_outside_project(self) -> None:
        outside_fragment = os.path.join(self.outside_dir, "outside.fsh")
        output_path = os.path.join(self.godot_dir, "outside.gdshader")
        self._write_fragment(outside_fragment, "DIRECT_OUTSIDE")

        self._make_converter().convert_shader(outside_fragment, output_path)

        self.assertFalse(os.path.exists(output_path))
        rejected = self._source_path_rejections()
        self.assertEqual(len(rejected), 1, rejected)
        self.assertEqual(rejected[0].resource, "outside")
        self.assertEqual(rejected[0].resource_type, "shader")
        self.assertEqual(rejected[0].manifest_entry, "shader stage")


class TestShaderConverterSubfolders(unittest.TestCase):
    """Test that shaders respect GameMaker's folder hierarchy."""

    def setUp(self):
        self.gm_dir = tempfile.mkdtemp()
        self.godot_dir = tempfile.mkdtemp()
        self.logs: list[str] = []

        # Create a shader in a named directory with a .yy specifying subfolder
        shader_dir = os.path.join(self.gm_dir, "shaders", "sh_blur")
        os.makedirs(shader_dir)
        with open(os.path.join(shader_dir, "sh_blur.fsh"), "w") as f:
            f.write(SAMPLE_FSH)
        with open(os.path.join(shader_dir, "sh_blur.yy"), "w") as f:
            f.write('{"name": "sh_blur", "parent": {"name": "Effects", "path": "folders/Shaders/Effects.yy",},}')

    def tearDown(self):
        shutil.rmtree(self.gm_dir)
        shutil.rmtree(self.godot_dir)

    def test_shader_in_subfolder(self):
        converter = ShaderConverter(
            self.gm_dir, self.godot_dir,
            log_callback=lambda msg: self.logs.append(msg),
            progress_callback=lambda v: None,
            conversion_running=lambda: True,
        )
        converter.convert_all()

        expected = os.path.join(self.godot_dir, "shaders", "effects", "sh_blur.gdshader")
        self.assertTrue(os.path.isfile(expected),
                        f"Expected shader at {expected}")


if __name__ == "__main__":
    unittest.main()
