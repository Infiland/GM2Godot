"""Godot checks for constructor statics read and called through a struct.

A struct made by new sees the static variables of its constructor (and of the
constructors it inherits from) as its own members, and a static function runs
with the struct it is called through as self: the runner's static_get returns
the function's prototype, so inst.method() finds the static function by the
prototype chain and calls it with inst (manual: GML Overview > Structs >
Constructor Functions, Static Struct).
"""
from __future__ import annotations

import unittest

from tests.gamemaker_project_support import EVENT_CREATE
from tests.gml_trace_support import run_gml_trace

_SCRIPTS = {
    "scr_vec": (
        "function Vec(_x) constructor {\n"
        "    x = _x;\n"
        "    static describe = function() { return \"I\"; };\n"
        "    static add = function(_d) { x += _d; return x; };\n"
        "    static twice = function() { return add(x); };\n"
        "    static me = function() { return self; };\n"
        "}\n"
    ),
    "scr_weapon": (
        "function Weapon() constructor {\n"
        "    static number_of_weapons = 0;\n"
        "    number_of_weapons++;\n"
        "}\n"
    ),
    "scr_family": (
        "function Item() constructor {\n"
        "    static number = 0;\n"
        "    static ident = function() { return \"item\"; };\n"
        "}\n"
        "function Sword() : Item() constructor {\n"
        "    static ident = function() { return \"sword/\" + string(number); };\n"
        "}\n"
    ),
}

_CREATE = (
    'trace("direct:" + (new Vec(1)).describe());\n'
    "var _a = new Vec(1);\n"
    "var _b = new Vec(10);\n"
    'trace("describe:" + _a.describe() + _b.describe());\n'
    'trace("add:" + string(_b.add(5)) + " a.x:" + string(_a.x) + " b.x:" + string(_b.x));\n'
    'trace("twice:" + string(_a.twice()) + " a.x:" + string(_a.x) + " b.x:" + string(_b.x));\n'
    'trace("me:" + string(_a.me() == _a) + string(_b.me() == _b) + string(_b.me() == _a));\n'
    "var _w1 = new Weapon();\n"
    "var _w2 = new Weapon();\n"
    'trace("weapons:" + string(_w1.number_of_weapons) + string(_w2.number_of_weapons));\n'
    "var _s = new Sword();\n"
    'trace("sword:" + string(_s.number) + " " + _s.ident());\n'
    'trace("exists:" + string(variable_struct_exists(_s, "number")) + string(variable_struct_exists(_s, "nope")));\n'
)


class TestStaticMethodReceiversGodot(unittest.TestCase):
    def test_statics_are_members_of_their_structs_and_methods_run_on_the_caller(self) -> None:
        trace = run_gml_trace(self, _SCRIPTS, {EVENT_CREATE: _CREATE})

        self.assertEqual(
            trace,
            [
                "direct:I",
                "describe:II",
                "add:15 a.x:1 b.x:15",
                "twice:2 a.x:2 b.x:15",
                "me:truetruefalse",
                "weapons:22",
                "sword:0 sword/0",
                "exists:truefalse",
            ],
        )


if __name__ == "__main__":
    unittest.main()
