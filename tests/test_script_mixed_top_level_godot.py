"""Godot checks for scripts that mix function declarations with other code.

Scripts are parsed at a global level and compiled at the very start of the
game: every function in a script is a global script function, and the
variables assigned outside of a function in the script are global variables,
initialised before everything else (manual: GML Overview > Script Functions
And Variables, "Script Scope"; the compiled game runs the code from
gmlGlobalInit in the runner's Globals.js, before the first room starts, in
script asset order). Only a compatibility script (saved with
"isCompatibility": true, a script from before GameMaker 2.3) has its whole
body as a function, with argument0 and so on; the code of any other script
runs at game start, whether or not the script declares functions.
"""
from __future__ import annotations

import unittest

from tests.gamemaker_project_support import EVENT_CREATE
from tests.gml_trace_support import run_gml_trace

_SCRIPTS = {
    "scr_c": (
        "function c() { return 1; }\n"
        "global.a = 1;\n"
        'global.order = "c";\n'
    ),
    "scr_d": (
        'global.order += "d";\n'
        "function d(_x) { return _x + global.a; }\n"
        "if (global.a == 1) global.ifd = 7;\n"
    ),
    "scr_scope": (
        'function Foo() { return "foo"; }\n'
        "blah = 10;\n"
        "function Bar() { return global.blah; }\n"
    ),
    "scr_each": (
        'global.collected = "";\n'
        "function collect_each() {\n"
        "    array_foreach([1, 2], function(_e) { global.collected += string(_e); });\n"
        "}\n"
    ),
    "scr_legacy": "return argument0 * 3;\n",
    "scr_start_only": 'global.start_only = "ran";\n',
}

_CREATE = (
    'trace("init:" + global.order + " " + string(global.ifd));\n'
    'trace("functions:" + string(c()) + string(d(2)));\n'
    'trace("scope:" + Foo() + string(Bar()) + string(global.blah));\n'
    "collect_each();\n"
    'trace("array_foreach:" + global.collected);\n'
    'trace("legacy:" + string(scr_legacy(4)));\n'
    'trace("start only:" + global.start_only);\n'
)


class TestScriptMixedTopLevelGodot(unittest.TestCase):
    def test_functions_register_and_the_other_top_level_statements_run_once(self) -> None:
        trace = run_gml_trace(
            self,
            _SCRIPTS,
            {EVENT_CREATE: _CREATE},
            compatibility_scripts=("scr_legacy",),
        )

        self.assertEqual(
            trace,
            [
                "init:cd 7",
                "functions:13",
                "scope:foo1010",
                "array_foreach:12",
                "legacy:12",
                "start only:ran",
            ],
        )

    def test_script_without_functions_runs_at_start_unless_it_is_a_compatibility_script(self) -> None:
        # Manual: GML Overview > Script Functions And Variables, "Script
        # Scope": scripts are parsed at a global level and compiled at the
        # very start of the game. The Colorful Creature's scr_crashmessage
        # (isCompatibility false) is one top-level statement that installs an
        # unhandled-exception handler.
        scripts = {
            "scr_boot": 'global.boot = "ran at start";\n',
            "scr_handler": (
                "if (os_type != os_android) {\n"
                "    exception_unhandled_handler(function(_exception) { return 0; });\n"
                "}\n"
                'global.handler = "installed";\n'
            ),
            "scr_called": 'global.called = "ran when called";\nreturn argument0 + 1;\n',
        }
        create = (
            'trace("boot:" + global.boot);\n'
            'trace("handler:" + global.handler);\n'
            'trace("before call:" + string(variable_global_exists("called")));\n'
            'trace("call:" + string(scr_called(1)) + " " + global.called);\n'
        )

        trace = run_gml_trace(
            self,
            scripts,
            {EVENT_CREATE: create},
            compatibility_scripts=("scr_called",),
        )

        self.assertEqual(
            trace,
            [
                "boot:ran at start",
                "handler:installed",
                "before call:false",
                "call:2 ran when called",
            ],
        )


if __name__ == "__main__":
    unittest.main()
