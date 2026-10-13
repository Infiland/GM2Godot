"""Godot checks for nested constructs that reuse a variable name.

GameMaker locals are function-wide, so a catch variable, a loop variable or a
local can reuse the name of one in an enclosing block. GDScript refuses a
second variable of the same name in a function, and one script Godot cannot
parse leaves the whole script without its functions.
"""
from __future__ import annotations

import unittest

from tests.gamemaker_project_support import EVENT_CREATE
from tests.gml_trace_support import run_gml_trace

_SCRIPTS = {
    "scr_nested_names": (
        "function nested_catch() {\n"
        "    var _out = '';\n"
        "    try {\n"
        "        throw 'outer';\n"
        "    } catch (e) {\n"
        "        _out += 'caught1:' + string(e) + ';';\n"
        "        try {\n"
        "            throw 'inner';\n"
        "        } catch (e) {\n"
        "            _out += 'caught2:' + string(e) + ';';\n"
        "        }\n"
        "    }\n"
        "    return _out;\n"
        "}\n"
        "function catch_named_like_a_local() {\n"
        "    var e = 'local';\n"
        "    var _out = '';\n"
        "    try { throw 'thrown'; } catch (e) { _out += string(e) + ';'; }\n"
        "    try { throw 'again'; } catch (e) { _out += string(e) + ';'; }\n"
        "    return _out;\n"
        "}\n"
        "function catch_named_like_a_loop_variable() {\n"
        "    var _out = '';\n"
        "    for (var i = 0; i < 2; i++) {\n"
        "        try { throw i + 10; } catch (i) { _out += string(i) + ';'; break; }\n"
        "    }\n"
        "    return _out;\n"
        "}\n"
        "function catch_in_a_method_in_a_catch() {\n"
        "    try { throw 'outer'; } catch (err) {\n"
        "        var _f = function() {\n"
        "            try { throw 'in method'; } catch (err) { return string(err); }\n"
        "        };\n"
        "        return _f() + ';' + string(err);\n"
        "    }\n"
        "}\n"
        "function nested_loops_and_with() {\n"
        "    var _out = '';\n"
        "    for (var i = 0; i < 2; i++) {\n"
        "        for (var j = 0; j < 2; j++) {\n"
        "            for (var i = 5; i < 7; i++) { _out += string(i); }\n"
        "        }\n"
        "    }\n"
        "    var _a = { v: 1 };\n"
        "    var _b = { v: 2 };\n"
        "    with (_a) { with (_b) { _out += ';' + string(v); } _out += string(v); }\n"
        "    repeat (2) { repeat (2) { _out += '.'; } }\n"
        "    return _out;\n"
        "}\n"
    ),
}

_CREATE = (
    "trace('nested catch:' + nested_catch());\n"
    "trace('catch like a local:' + catch_named_like_a_local());\n"
    "trace('catch like a loop variable:' + catch_named_like_a_loop_variable());\n"
    "trace('catch in a method:' + catch_in_a_method_in_a_catch());\n"
    "trace('loops and with:' + nested_loops_and_with());\n"
    "try { throw 'a'; } catch (e) { try { throw 'b'; } catch (e) { trace('event:' + string(e)); } }\n"
)


class TestNestedNameReuseGodot(unittest.TestCase):
    def test_nested_constructs_reusing_a_name_convert_to_scripts_godot_loads(self) -> None:
        trace = run_gml_trace(self, _SCRIPTS, {EVENT_CREATE: _CREATE})

        self.assertEqual(
            trace,
            [
                "nested catch:caught1:outer;caught2:inner;",
                "catch like a local:thrown;again;",
                "catch like a loop variable:10;",
                "catch in a method:in method;outer",
                "loops and with:5656;21....",
                "event:b",
            ],
        )


if __name__ == "__main__":
    unittest.main()
