from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.conversion.gml_runtime import write_gml_runtime
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

# INI text as GameMaker writes it and as people write it by hand: quoted and
# unquoted values, comments, a value holding a double quote, JSON, a UTF-8
# byte order mark and CR LF line ends.
_AUTHORED_INI = (
    "﻿; settings written by hand\r\n"
    "ignored=before any section\r\n"
    "[audio]\r\n"
    "volume = 0.5 ; master volume\r\n"
    'device="Line Out; HDMI"\r\n'
    "quote='say \"hi\"'\r\n"
    "  name = Bob the Brave   \r\n"
    "empty=\r\n"
    "blank=\"\"\r\n"
    "# comment line\r\n"
    "[data]\r\n"
    'json={"a": [1, 2]} ; not a comment\r\n'
    "count=12abc\r\n"
    "lower=inf\r\n"
    "big=Infinity\r\n"
    "small= -Infinity metres\r\n"
)

_SMOKE = textwrap.dedent(
    """\
    extends Node

    const GMRuntime = preload("res://gm2godot/gml_runtime.gd")

    var _failures = []


    func _expect(label, actual, expected):
    \tif typeof(actual) == typeof(expected) and actual == expected:
    \t\treturn
    \t_failures.append("%s: expected %s, got %s" % [label, var_to_str(expected), var_to_str(actual)])


    func _ready():
    \t_check_authored_text()
    \t_check_reading_creates_no_file()
    \t_check_written_file()
    \t_check_open_closes_previous()
    \tif _failures.is_empty():
    \t\tprint("INI_FILES_OK")
    \t\tget_tree().quit(0)
    \t\treturn
    \tfor failure in _failures:
    \t\tprint("FAIL " + failure)
    \tget_tree().quit(1)


    func _check_authored_text():
    \tGMRuntime.gml_ini_open_from_string(FileAccess.get_file_as_string("res://authored.ini"))
    \t_expect("unquoted value with a comment", GMRuntime.gml_ini_read_string("audio", "volume", ""), "0.5")
    \t_expect("unquoted real", GMRuntime.gml_ini_read_real("audio", "volume", 0), 0.5)
    \t_expect("quoted value keeps ;", GMRuntime.gml_ini_read_string("audio", "device", ""), "Line Out; HDMI")
    \t_expect("single quotes around a double quote", GMRuntime.gml_ini_read_string("audio", "quote", ""), 'say "hi"')
    \t_expect("indented key and spaces", GMRuntime.gml_ini_read_string("audio", "name", ""), "Bob the Brave")
    \t_expect("key without a value", GMRuntime.gml_ini_key_exists("audio", "empty"), false)
    \t_expect("empty quoted value", GMRuntime.gml_ini_read_string("audio", "blank", "default"), "")
    \t_expect("keys before the first section", GMRuntime.gml_ini_key_exists("", "ignored"), false)
    \t_expect("JSON value runs to the end of the line", GMRuntime.gml_ini_read_string("data", "json", ""), '{"a": [1, 2]} ; not a comment')
    \t_expect("number at the start of the text", GMRuntime.gml_ini_read_real("data", "count", 0), 12.0)
    \t# The runner reads reals with JavaScript's parseFloat: NaN without a
    \t# number, and Infinity only spelled that way.
    \t_expect("text without a number", is_nan(GMRuntime.gml_ini_read_real("audio", "name", 3)), true)
    \t_expect("inf is not a number", is_nan(GMRuntime.gml_ini_read_real("data", "lower", 3)), true)
    \t_expect("Infinity", GMRuntime.gml_ini_read_real("data", "big", 0), INF)
    \t_expect("-Infinity before text", GMRuntime.gml_ini_read_real("data", "small", 0), -INF)
    \t_expect("string default with a number", GMRuntime.gml_ini_read_real("data", "missing", "2.5kg"), 2.5)
    \t_expect("string default without a number", is_nan(GMRuntime.gml_ini_read_real("data", "missing", "none")), true)
    \t_expect("missing real", GMRuntime.gml_ini_read_real("audio", "missing", 7), 7.0)
    \t_expect("missing string with a number default", GMRuntime.gml_ini_read_string("audio", "missing", 5), "5")
    \tvar text = GMRuntime.gml_ini_close()
    \t_expect("ini_close returns the INI text", text.begins_with("[audio]\\r\\nvolume=\\"0.5\\"\\r\\n"), true)
    \t_expect("ini_close quotes a value with a double quote in single quotes", text.contains("quote='say \\"hi\\"'\\r\\n"), true)
    \t_expect("closing again", GMRuntime.is_undefined(GMRuntime.gml_ini_close()), true)


    func _check_reading_creates_no_file():
    \tGMRuntime.gml_ini_open("progress.ini")
    \t_expect("default from a missing file", GMRuntime.gml_ini_read_real("save", "level", 1), 1.0)
    \t_expect("nothing written, nothing returned", GMRuntime.gml_ini_close(), "")
    \t_expect("reading does not create the file", GMRuntime.gml_file_exists("progress.ini"), false)


    func _check_written_file():
    \tGMRuntime.gml_ini_open("progress.ini")
    \tGMRuntime.gml_ini_write_real("save", "level", 3)
    \tGMRuntime.gml_ini_write_real("save", "third", 1.0 / 3.0)
    \tGMRuntime.gml_ini_write_string("save", "name", "Ann")
    \tGMRuntime.gml_ini_write_real("old", "gone", 1)
    \tGMRuntime.gml_ini_section_delete("old")
    \tvar text = GMRuntime.gml_ini_close()
    \t_expect("GameMaker INI text", text, "[save]\\r\\nlevel=\\"3\\"\\r\\nthird=\\"0.3333333333333333\\"\\r\\nname=\\"Ann\\"\\r\\n")
    \t_expect("writing creates the file", GMRuntime.gml_file_exists("progress.ini"), true)
    \t_expect("file holds the text", FileAccess.get_file_as_string(GMRuntime.gml_file_resolve_path("progress.ini")), text)
    \tGMRuntime.gml_ini_open("progress.ini")
    \t_expect("whole numbers read back as text without decimals", GMRuntime.gml_ini_read_string("save", "level", ""), "3")
    \t_expect("reals read back exactly", GMRuntime.gml_ini_read_real("save", "third", 0), 1.0 / 3.0)
    \t_expect("deleted section stays deleted", GMRuntime.gml_ini_section_exists("old"), false)
    \tGMRuntime.gml_ini_close()


    func _check_open_closes_previous():
    \tGMRuntime.gml_ini_open("first.ini")
    \tGMRuntime.gml_ini_write_real("a", "b", 2)
    \t# Opening another INI file closes (and saves) the open one.
    \tGMRuntime.gml_ini_open("second.ini")
    \tGMRuntime.gml_ini_close()
    \tGMRuntime.gml_ini_open("first.ini")
    \t_expect("previous INI file was saved", GMRuntime.gml_ini_read_real("a", "b", 0), 2.0)
    \tGMRuntime.gml_ini_close()
    \t_expect("second file was only read", GMRuntime.gml_file_exists("second.ini"), false)
    """
)

_SCENE = textwrap.dedent(
    """\
    [gd_scene load_steps=2 format=3]

    [ext_resource type="Script" path="res://smoke.gd" id="smoke_script"]

    [node name="Smoke" type="Node"]
    script = ExtResource("smoke_script")
    """
)


class TestIniFilesGodot(unittest.TestCase):
    def test_ini_files_follow_gamemaker_format_and_rules(self) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")

        with tempfile.TemporaryDirectory() as temporary_directory:
            project_dir = Path(temporary_directory)
            write_fixture_text(project_dir / "project.godot", '[application]\nconfig/name="IniFiles"\n')
            write_gml_runtime(str(project_dir))
            (project_dir / "authored.ini").write_bytes(_AUTHORED_INI.encode("utf-8"))
            write_fixture_text(project_dir / "smoke.gd", _SMOKE)
            write_fixture_text(project_dir / "smoke.tscn", _SCENE)
            environment = dict(os.environ)
            # Keep user:// inside the temporary project.
            environment["HOME"] = str(project_dir)
            result = subprocess.run(
                [godot_binary, "--headless", "--path", str(project_dir), "smoke.tscn"],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                env=environment,
            )
            output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("INI_FILES_OK", output)
        self.assertNotIn("ERROR:", output)


if __name__ == "__main__":
    unittest.main()
