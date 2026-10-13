"""Godot checks for scripts that mix function declarations with other code.

Scripts are parsed at a global level and compiled at the very start of the
game: every function in a script is a global script function, and the
variables assigned outside of a function in the script are global variables,
initialised before everything else (manual: GML Overview > Script Functions
And Variables, "Script Scope"; the compiled game runs the code from
gmlGlobalInit in the runner's Globals.js, before the first room starts, in
script asset order). A script without any function declaration keeps its
older meaning: its whole body is the function, with argument0 and so on.
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
}

_CREATE = (
    'trace("init:" + global.order + " " + string(global.ifd));\n'
    'trace("functions:" + string(c()) + string(d(2)));\n'
    'trace("scope:" + Foo() + string(Bar()) + string(global.blah));\n'
    "collect_each();\n"
    'trace("array_foreach:" + global.collected);\n'
    'trace("legacy:" + string(scr_legacy(4)));\n'
)


class TestScriptMixedTopLevelGodot(unittest.TestCase):
    def test_functions_register_and_the_other_top_level_statements_run_once(self) -> None:
        trace = run_gml_trace(self, _SCRIPTS, {EVENT_CREATE: _CREATE})

        self.assertEqual(
            trace,
            [
                "init:cd 7",
                "functions:13",
                "scope:foo1010",
                "array_foreach:12",
                "legacy:12",
            ],
        )


if __name__ == "__main__":
    unittest.main()
