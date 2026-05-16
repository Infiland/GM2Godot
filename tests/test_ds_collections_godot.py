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
            	
            	# --- DS Stacks ---
            	var s1 = GMRuntime.gml_ds_stack_create()
            	GMRuntime.gml_ds_stack_push(s1, [10, 20])
            	if not _check(GMRuntime.gml_ds_stack_size(s1) == 2, "Stack size not 2"): return
            	if not _check(int(GMRuntime.gml_ds_stack_top(s1)) == 20, "Stack top not 20"): return
            	if not _check(int(GMRuntime.gml_ds_stack_pop(s1)) == 20, "Stack pop not 20"): return
            	if not _check(GMRuntime.gml_ds_stack_size(s1) == 1, "Stack size not 1 after pop"): return
            	
            	# --- DS Queues ---
            	var q1 = GMRuntime.gml_ds_queue_create()
            	GMRuntime.gml_ds_queue_enqueue(q1, [100, 200])
            	if not _check(int(GMRuntime.gml_ds_queue_head(q1)) == 100, "Queue head not 100"): return
            	if not _check(int(GMRuntime.gml_ds_queue_tail(q1)) == 200, "Queue tail not 200"): return
            	if not _check(int(GMRuntime.gml_ds_queue_dequeue(q1)) == 100, "Queue dequeue not 100"): return
            	
            	# --- DS Priority ---
            	var p1 = GMRuntime.gml_ds_priority_create()
            	GMRuntime.gml_ds_priority_add(p1, "Low", 1)
            	GMRuntime.gml_ds_priority_add(p1, "High", 100)
            	GMRuntime.gml_ds_priority_add(p1, "Medium", 50)
            	if not _check(str(GMRuntime.gml_ds_priority_find_max(p1)) == "High", "Priority max not High"): return
            	if not _check(str(GMRuntime.gml_ds_priority_find_min(p1)) == "Low", "Priority min not Low"): return
            	if not _check(str(GMRuntime.gml_ds_priority_delete_max(p1)) == "High", "Priority delete max not High"): return
            	if not _check(GMRuntime.gml_ds_priority_size(p1) == 2, "Priority size not 2 after delete"): return
            	
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
