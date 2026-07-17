import os
import subprocess
import tempfile
import textwrap
import shutil
import unittest
from pathlib import Path

def _find_godot_binary() -> str | None:
    env_path = os.environ.get("GODOT_BIN")
    if env_path and os.path.isfile(env_path):
        return env_path
    path_binary = shutil.which("godot")
    if path_binary is not None:
        return path_binary
    mac_binary = "/Applications/Godot.app/Contents/MacOS/Godot"
    if os.path.isfile(mac_binary):
        return mac_binary
    return None

godot_binary = _find_godot_binary()



from src.conversion.gml_runtime import write_gml_runtime

@unittest.skipIf(godot_binary is None, "Godot binary not found")
class TestDSCollectionsGodotSmoke(unittest.TestCase):
    def test_ds_collections_runtime(self):
        assert godot_binary is not None
        

        smoke_script = textwrap.dedent(
            """\
            extends Node2D
            const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

            func _ready():
            	print("SMOKE TEST START")
            	_run.call_deferred()

            func _check(condition: bool, msg: String) -> bool:
            	if not condition:
            		print("FAIL: " + msg)
            	return condition

            func _run():
            \tif not _check(GMRuntime.gml_array_length([1, 2, 3]) == 3, "Current array_length failed"): return
            \tif not _check(GMRuntime.gml_array_length("not an array") == 0, "array_length non-array parity failed"): return
            \tif not _check(GMRuntime.gml_string_byte_length("Aé") == 3, "UTF-8 string_byte_length failed"): return
            	# --- DS Lists ---
            	var l1 = GMRuntime.gml_ds_list_create()
            	GMRuntime.gml_ds_list_add(l1, ["apple", "banana", "cherry"])
            	if not _check(GMRuntime.gml_ds_list_size(l1) == 3, "List size not 3"): return
            	
            	# Set via runtime function
            	GMRuntime.gml_ds_list_set(l1, 1, "orange")
            	if not _check(str(GMRuntime.gml_ds_list_find_value(l1, 1)) == "orange", "List set failed"): return
            	
            	# Accessor lowering simulation:
            	var accessor_val = GMRuntime.gml_ds_list_find_value(l1, 0)
            	if not _check(str(accessor_val) == "apple", "Accessor read failed"): return
            	
            	GMRuntime.gml_ds_list_delete(l1, 0)
            	if not _check(GMRuntime.gml_ds_list_size(l1) == 2, "List size not 2 after delete"): return
            	if not _check(str(GMRuntime.gml_ds_list_find_value(l1, 0)) == "orange", "List delete shift failed"): return
            	
            	GMRuntime.gml_ds_list_insert(l1, 1, "grape")
            	if not _check(str(GMRuntime.gml_ds_list_find_value(l1, 1)) == "grape", "List insert failed"): return
            	var l2 = GMRuntime.gml_ds_list_create()
            	GMRuntime.gml_ds_list_read(l2, GMRuntime.gml_ds_list_write(l1))
            	if not _check(GMRuntime.gml_ds_list_size(l2) == 3, "List read/write size failed"): return
            	if not _check(str(GMRuntime.gml_ds_list_find_value(l2, 1)) == "grape", "List read/write value failed"): return
            	
            	# --- DS Stacks ---
            	var s1 = GMRuntime.gml_ds_stack_create()
            	GMRuntime.gml_ds_stack_push(s1, [10, 20])
            	if not _check(GMRuntime.gml_ds_stack_size(s1) == 2, "Stack size not 2"): return
            	if not _check(int(GMRuntime.gml_ds_stack_top(s1)) == 20, "Stack top not 20"): return
            	if not _check(int(GMRuntime.gml_ds_stack_pop(s1)) == 20, "Stack pop not 20"): return
            	if not _check(GMRuntime.gml_ds_stack_size(s1) == 1, "Stack size not 1 after pop"): return
            	var s2 = GMRuntime.gml_ds_stack_create()
            	GMRuntime.gml_ds_stack_read(s2, GMRuntime.gml_ds_stack_write(s1))
            	if not _check(int(GMRuntime.gml_ds_stack_top(s2)) == 10, "Stack read/write top failed"): return
            	
            	# --- DS Queues ---
            	var q1 = GMRuntime.gml_ds_queue_create()
            	GMRuntime.gml_ds_queue_enqueue(q1, [100, 200])
            	if not _check(int(GMRuntime.gml_ds_queue_head(q1)) == 100, "Queue head not 100"): return
            	if not _check(int(GMRuntime.gml_ds_queue_tail(q1)) == 200, "Queue tail not 200"): return
            	if not _check(int(GMRuntime.gml_ds_queue_dequeue(q1)) == 100, "Queue dequeue not 100"): return
            	var q2 = GMRuntime.gml_ds_queue_create()
            	GMRuntime.gml_ds_queue_read(q2, GMRuntime.gml_ds_queue_write(q1))
            	if not _check(int(GMRuntime.gml_ds_queue_head(q2)) == 200, "Queue read/write head failed"): return
            	
            	# --- DS Priority ---
            	var p1 = GMRuntime.gml_ds_priority_create()
            	GMRuntime.gml_ds_priority_add(p1, "Low", 1)
            	GMRuntime.gml_ds_priority_add(p1, "High", 100)
            	GMRuntime.gml_ds_priority_add(p1, "Medium", 50)
            	if not _check(str(GMRuntime.gml_ds_priority_find_max(p1)) == "High", "Priority max not High"): return
            	if not _check(str(GMRuntime.gml_ds_priority_find_min(p1)) == "Low", "Priority min not Low"): return
            	if not _check(str(GMRuntime.gml_ds_priority_delete_max(p1)) == "High", "Priority delete max not High"): return
            	if not _check(GMRuntime.gml_ds_priority_size(p1) == 2, "Priority size not 2 after delete"): return
            	var p2 = GMRuntime.gml_ds_priority_create()
            	GMRuntime.gml_ds_priority_read(p2, GMRuntime.gml_ds_priority_write(p1))
            	if not _check(str(GMRuntime.gml_ds_priority_find_max(p2)) == "Medium", "Priority read/write max failed"): return
            	if not _check(int(GMRuntime.gml_ds_priority_find_priority(p2, "Low")) == 1, "Priority read/write priority failed"): return
            	
            	# --- DS Maps ---
            	var nested_list = GMRuntime.gml_ds_list_create()
            	GMRuntime.gml_ds_list_add(nested_list, ["nested"])
            	var m1 = GMRuntime.gml_ds_map_create()
            	GMRuntime.gml_ds_map_set(m1, "food", "apple")
            	GMRuntime.gml_ds_map_set(m1, 7, "seven")
            	GMRuntime.gml_ds_map_add_list(m1, "nested", nested_list)
            	var m2 = GMRuntime.gml_ds_map_create()
            	GMRuntime.gml_ds_map_read(m2, GMRuntime.gml_ds_map_write(m1))
            	if not _check(str(GMRuntime.gml_ds_map_find_value(m2, "food")) == "apple", "Map read/write string key failed"): return
            	if not _check(str(GMRuntime.gml_ds_map_find_value(m2, 7)) == "seven", "Map read/write numeric key failed"): return
            	if not _check(GMRuntime.gml_ds_map_is_list(m2, "nested"), "Map read/write nested list mark failed"): return
            	var restored_nested = GMRuntime.gml_ds_map_find_value(m2, "nested")
            	if not _check(str(GMRuntime.gml_ds_list_find_value(restored_nested, 0)) == "nested", "Map read/write nested list value failed"): return
            \tvar cyclic_struct = GMRuntime.gml_struct({"name": "cycle"})
            \tcyclic_struct["self"] = cyclic_struct
            \tGMRuntime.gml_ds_map_set(m2, cyclic_struct, "struct identity key")
            \tif not _check(str(GMRuntime.gml_ds_map_find_value(m2, cyclic_struct)) == "struct identity key", "Map cyclic struct key failed"): return
            \tif not _check(GMRuntime.is_undefined(GMRuntime.gml_ds_map_find_value(m2, GMRuntime.gml_struct({"name": "cycle"}))), "Map struct keys must use identity"): return
            \tvar array_key = [cyclic_struct]
            \tGMRuntime.gml_ds_map_set(m2, array_key, "array identity key")
            \tif not _check(str(GMRuntime.gml_ds_map_find_value(m2, array_key)) == "array identity key", "Map cyclic array key failed"): return
            \tvar map_keys = GMRuntime.gml_ds_map_keys(m2)
            \tif not _check(map_keys.any(func(key): return is_same(key, cyclic_struct)), "Map keys did not preserve original struct reference"): return
            \tGMRuntime.gml_ds_map_delete(m2, cyclic_struct)
            \tif not _check(not GMRuntime.gml_ds_map_exists(m2, cyclic_struct), "Map cyclic struct key delete failed"): return
            	
            	# --- DS Grids ---
            	var g1 = GMRuntime.gml_ds_grid_create(2, 2)
            	GMRuntime.gml_ds_grid_set(g1, 0, 0, "nw")
            	GMRuntime.gml_ds_grid_set(g1, 1, 1, 42)
            	var g2 = GMRuntime.gml_ds_grid_create(1, 1)
            	GMRuntime.gml_ds_grid_read(g2, GMRuntime.gml_ds_grid_write(g1))
            	if not _check(GMRuntime.gml_ds_grid_width(g2) == 2, "Grid read/write width failed"): return
            	if not _check(GMRuntime.gml_ds_grid_height(g2) == 2, "Grid read/write height failed"): return
            	if not _check(str(GMRuntime.gml_ds_grid_get(g2, 0, 0)) == "nw", "Grid read/write string value failed"): return
            	if not _check(int(GMRuntime.gml_ds_grid_get(g2, 1, 1)) == 42, "Grid read/write numeric value failed"): return
            	
            	print("DS_COLLECTIONS_SMOKE_OK")
            	get_tree().quit(0)
            """
        )

        smoke_scene = textwrap.dedent(
            """\
            [gd_scene load_steps=2 format=3]

            [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

            [node name="Smoke" type="Node2D"]
            script = ExtResource("smoke_script")
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            
            project_godot = project_dir / "project.godot"
            project_godot.write_text(
                '[application]\nconfig/name="DSCollectionsSmoke"\nrun/main_scene="res://smoke.tscn"\n',
                encoding="utf-8",
            )

            write_gml_runtime(str(project_dir))

            smoke_gd = project_dir / "smoke.gd"
            smoke_gd.write_text(smoke_script, encoding="utf-8")

            smoke_tscn = project_dir / "smoke.tscn"
            smoke_tscn.write_text(smoke_scene, encoding="utf-8")

            godot_env = dict(os.environ)
            godot_env["HOME"] = str(project_dir)
            result = subprocess.run(
                [
                    godot_binary,
                    "--headless",
                    "--path",
                    str(project_dir),
                    "--scene",
                    "res://smoke.tscn",
                    "--quit",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                env=godot_env,
            )
            output = result.stdout + result.stderr

        self.assertIn("DS_COLLECTIONS_SMOKE_OK", output)

if __name__ == "__main__":
    unittest.main()
