"""Godot checks for variable_clone and the text of a struct made by new.

A clone of a struct made by a constructor keeps the static chain, and a method
bound to the struct that is being cloned is bound to the clone, so the clone's
methods work on the clone (manual: variable_clone, Usage Notes and Example 2;
the runner's __internal_variable_clone keeps the prototype and rebinds with
method()). string() and show_debug_message of a struct call its toString, which
a constructor can declare static and a child constructor inherits (manual:
GML Overview > Structs > String Output, Static Struct; the runner's yyGetString
reads gmltoString through the struct's prototype chain).
"""
from __future__ import annotations

import unittest

from tests.gamemaker_project_support import EVENT_CREATE
from tests.gml_trace_support import run_gml_trace

_SCRIPTS = {
    "scr_points": (
        "function Pt(_x) constructor {\n"
        "    x = _x;\n"
        "    static toString = function() { return \"Pt(\" + string(x) + \")\"; };\n"
        "    static scaled = function(_k) { return x * _k; };\n"
        "    own = function() { return x * 2; };\n"
        "}\n"
        "function Pt3(_x) : Pt(_x) constructor {\n"
        "    static twice = function() { return x * 2; };\n"
        "}\n"
        "function Quiet(_x) : Pt(_x) constructor {\n"
        "    toString = function() { return \"quiet \" + string(x); };\n"
        "}\n"
    ),
}

_CREATE = (
    "var _the_struct = { my_value: 12, my_method: function() { return my_value; } };\n"
    "var _the_new_struct = variable_clone(_the_struct);\n"
    "_the_new_struct.my_value = 24;\n"
    'trace("example 2:" + string(_the_struct.my_method()) + "," + string(_the_new_struct.my_method()));\n'
    "var _p = new Pt3(4);\n"
    "var _c = variable_clone(_p);\n"
    "_c.x = 9;\n"
    'trace("constructor clone:" + string(is_instanceof(_c, Pt3)) + string(is_instanceof(_c, Pt)) + " " + instanceof(_c) + " " + string(static_get(_c) == static_get(_p)));\n'
    'trace("statics:" + string(_c.twice()) + "," + string(_c.scaled(10)) + "," + string(_p.scaled(10)));\n'
    'trace("own method:" + string(_p.own()) + "," + string(_c.own()));\n'
    "var _outer = { v: 1 };\n"
    "var _inner = { run: method(_outer, function() { return v; }) };\n"
    "var _outer_clone = variable_clone(_inner);\n"
    "_outer.v = 5;\n"
    'trace("bound outside:" + string(_outer_clone.run()));\n'
    "var _nest = { val: 1, child: { } };\n"
    "_nest.child.read = method(_nest, function() { return val; });\n"
    "var _nest_clone = variable_clone(_nest);\n"
    "_nest_clone.val = 99;\n"
    'trace("nested:" + string(_nest.child.read()) + "," + string(_nest_clone.child.read()));\n'
    "var _shallow = variable_clone(_the_struct, 0);\n"
    "_shallow.my_value = 7;\n"
    'trace("shallow:" + string(_the_struct.my_method()) + "," + string(_shallow.my_method()));\n'
    'trace("static toString:" + string(_p) + " " + string(new Pt(2)));\n'
    'trace("own toString:" + string(new Quiet(3)));\n'
    'trace("template:" + $"{_p}!");\n'
    'show_debug_message(_p);\n'
    'show_debug_message(new Quiet(8));\n'
    'var _literal = { a: 20, b: "Hello World", toString: function() { return "This struct says " + b + ", " + string(a) + " times!"; } };\n'
    "show_debug_message(_literal);\n"
)


class TestStructCloneAndTextGodot(unittest.TestCase):
    def test_clone_keeps_the_static_chain_and_rebinds_methods(self) -> None:
        trace = run_gml_trace(self, _SCRIPTS, {EVENT_CREATE: _CREATE})

        self.assertEqual(
            trace,
            [
                "example 2:12,24",
                "constructor clone:truetrue Pt3 true",
                "statics:18,90,40",
                "own method:8,18",
                "bound outside:5",
                "nested:1,99",
                "shallow:12,7",
                "static toString:Pt(4) Pt(2)",
                "own toString:quiet 3",
                "template:Pt(4)!",
            ],
        )

    def test_show_debug_message_prints_the_to_string_text(self) -> None:
        output: list[str] = []
        run_gml_trace(self, _SCRIPTS, {EVENT_CREATE: _CREATE}, output_lines=output)

        printed = [line for line in output if line in {"Pt(4)", "quiet 8"} or line.startswith("This struct says")]
        self.assertEqual(printed, ["Pt(4)", "quiet 8", "This struct says Hello World, 20 times!"])


if __name__ == "__main__":
    unittest.main()
