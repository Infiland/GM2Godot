from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.gml_runtime import (
    GML_RUNTIME_RELATIVE_PATH,
    RUNTIME_MANAGER_RELATIVE_DIR,
    register_runtime_manager_autoloads,
    render_runtime_manager_script,
    runtime_manager_autoloads,
    runtime_manager_definitions,
    write_gml_runtime,
    write_runtime_managers,
)


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class TestRuntimeManagers(unittest.TestCase):
    def setUp(self) -> None:
        self.godot_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.godot_dir)

    def test_runtime_manager_definitions_are_deterministic(self) -> None:
        definitions = runtime_manager_definitions()
        names = [definition.name for definition in definitions]
        orders = [definition.order for definition in definitions]

        self.assertEqual(
            names,
            [
                "GMRuntime",
                "GMAssets",
                "GMRooms",
                "GMInstances",
                "GMEvents",
                "GMDraw",
                "GMInput",
                "GMAudio",
                "GMAsync",
                "GMPlatform",
            ],
        )
        self.assertEqual(orders, sorted(orders))
        self.assertEqual(definitions[0].dependencies, ())
        for definition in definitions[1:]:
            self.assertIn("GMRuntime", definition.dependencies)
            self.assertTrue(definition.state_keys)

    def test_runtime_manager_autoloads_use_generated_resource_paths(self) -> None:
        autoloads = runtime_manager_autoloads()

        self.assertEqual(autoloads[0], ("GMRuntime", "res://gm2godot/managers/gm_runtime_manager.gd"))
        self.assertEqual(autoloads[-1], ("GMPlatform", "res://gm2godot/managers/gm_platform.gd"))

    def test_rendered_manager_script_exposes_registry_and_state_buckets(self) -> None:
        definition = runtime_manager_definitions()[0]

        script = render_runtime_manager_script(definition)

        self.assertIn("extends Node", script)
        self.assertIn('const MANAGER_NAME = "GMRuntime"', script)
        self.assertIn("const QUEUED_GODOT_SIGNALS = []", script)
        self.assertIn("func register_manager(manager):", script)
        self.assertIn("func manager_order():", script)
        self.assertIn("func state_bucket(key = \"default\"):", script)
        self.assertIn("func manager_queued_godot_signals():", script)
        self.assertIn(
            'const GMRuntimeFacade = preload("res://gm2godot/gml_runtime.gd")',
            script,
        )
        self.assertIn("func _exit_tree():", script)
        self.assertIn("GMRuntimeFacade.gm2godot_runtime_shutdown()", script)
        self.assertIn(
            "GMRuntimeFacade.gml_included_file_integrity_prewarm()",
            script,
        )
        self.assertIn("GMRuntimeFacade.gml_script_registry_entries()", script)
        self.assertLess(
            script.index("GMRuntimeFacade.gml_included_file_integrity_prewarm()"),
            script.index("GMRuntimeFacade.gml_script_registry_entries()"),
        )

    def test_events_manager_pumps_central_scheduler(self) -> None:
        definition = next(
            manager_definition
            for manager_definition in runtime_manager_definitions()
            if manager_definition.name == "GMEvents"
        )

        script = render_runtime_manager_script(definition)

        self.assertIn('const GMRuntimeFacade = preload("res://gm2godot/gml_runtime.gd")', script)
        self.assertIn('"Area2D.area_entered"', script)
        self.assertIn('"Timer.timeout"', script)
        self.assertIn("func _process(delta):", script)
        self.assertIn("GMRuntimeFacade.gml_input_dispatch_frame()", script)
        self.assertIn("GMRuntimeFacade.gml_event_scheduler_frame(float(delta), 1)", script)
        self.assertIn("GMRuntimeFacade.gml_input_end_frame()", script)

    def test_input_manager_captures_godot_input_events(self) -> None:
        definition = next(
            manager_definition
            for manager_definition in runtime_manager_definitions()
            if manager_definition.name == "GMInput"
        )

        script = render_runtime_manager_script(definition)

        self.assertIn('const GMRuntimeFacade = preload("res://gm2godot/gml_runtime.gd")', script)
        self.assertIn("func _input(event):", script)
        self.assertIn("GMRuntimeFacade.gml_input_event_capture(event)", script)

    def test_draw_manager_pumps_draw_dispatch(self) -> None:
        definition = next(
            manager_definition
            for manager_definition in runtime_manager_definitions()
            if manager_definition.name == "GMDraw"
        )

        script = render_runtime_manager_script(definition)

        self.assertIn('const GMRuntimeFacade = preload("res://gm2godot/gml_runtime.gd")', script)
        self.assertIn("func _process(_delta):", script)
        self.assertIn("GMRuntimeFacade.gml_draw_event_dispatch_frame()", script)

    def test_async_manager_pumps_async_queue(self) -> None:
        definition = next(
            manager_definition
            for manager_definition in runtime_manager_definitions()
            if manager_definition.name == "GMAsync"
        )

        script = render_runtime_manager_script(definition)

        self.assertIn('const GMRuntimeFacade = preload("res://gm2godot/gml_runtime.gd")', script)
        self.assertIn('"HTTPRequest.request_completed"', script)
        self.assertIn('"AudioStreamPlayer.finished"', script)
        self.assertIn("func _process(_delta):", script)
        self.assertIn("GMRuntimeFacade.gml_async_queue_flush()", script)

    def test_write_runtime_managers_writes_each_manager_script(self) -> None:
        output_paths = write_runtime_managers(self.godot_dir)

        self.assertEqual(len(output_paths), len(runtime_manager_definitions()))
        for definition in runtime_manager_definitions():
            path = os.path.join(self.godot_dir, definition.relative_path)
            self.assertTrue(os.path.isfile(path), definition.name)
        self.assertTrue(os.path.isdir(os.path.join(self.godot_dir, RUNTIME_MANAGER_RELATIVE_DIR)))

    def test_register_runtime_manager_autoloads_updates_project_godot(self) -> None:
        _write_file(os.path.join(self.godot_dir, "project.godot"), "[application]\n")

        self.assertTrue(register_runtime_manager_autoloads(self.godot_dir))

        with open(os.path.join(self.godot_dir, "project.godot"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("[autoload]", content)
        self.assertLess(content.index("GMRuntime="), content.index("GMPlatform="))
        self.assertIn('GMAsync="*res://gm2godot/managers/gm_async.gd"', content)

    def test_write_gml_runtime_writes_facade_managers_and_project_autoloads(self) -> None:
        _write_file(os.path.join(self.godot_dir, "project.godot"), "[application]\n")

        runtime_path = write_gml_runtime(self.godot_dir)

        self.assertEqual(runtime_path, os.path.join(self.godot_dir, GML_RUNTIME_RELATIVE_PATH))
        self.assertTrue(os.path.isfile(os.path.join(self.godot_dir, "gm2godot", "gml_runtime.gd")))
        self.assertTrue(os.path.isfile(os.path.join(self.godot_dir, "gm2godot", "managers", "gm_runtime_manager.gd")))
        with open(os.path.join(self.godot_dir, "project.godot"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('GMRuntime="*res://gm2godot/managers/gm_runtime_manager.gd"', content)
        self.assertIn('GMPlatform="*res://gm2godot/managers/gm_platform.gd"', content)


if __name__ == "__main__":
    unittest.main()
