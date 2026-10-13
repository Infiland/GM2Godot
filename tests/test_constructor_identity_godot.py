"""Godot checks for the constructor a struct was made by and its static chain.

instanceof, is_instanceof, static_get and static_set work with the constructors
GML code names: a constructor declared in a script asset is a script index, and
a child constructor (Sword : Item) joins its static struct to its parent's
(GML Reference > Variable Functions: is_instanceof, instanceof, static_get,
static_set; GML Overview > Structs > Static Struct). The runner reads the same
chain from the struct's prototypes (Function_Maths.js: YYIsInstanceof,
YYInstanceof, static_get, static_set).
"""
from __future__ import annotations

import unittest

from tests.gamemaker_project_support import EVENT_CREATE
from tests.gml_trace_support import run_gml_trace

_SCRIPTS = {
    "scr_items": (
        "function Item(_n) constructor {\n"
        "    name = _n;\n"
        "    static hello = function() { return \"hello item\"; };\n"
        "}\n"
        "function Sword(_n) : Item(_n) constructor {\n"
        "    static slash = function() { return \"slash \" + name; };\n"
        "}\n"
        "function Plain() constructor { a = 1; }\n"
    ),
    "scr_shapes": (
        "function Shape() constructor {\n"
        "    static name_of = function() { return \"shape\"; };\n"
        "    static count = 0;\n"
        "    count++;\n"
        "}\n"
        "function Rect() : Shape() constructor {\n"
        "    static rect_only = function() { return \"rect\"; };\n"
        "    static count = 0;\n"
        "    count++;\n"
        "}\n"
        "function Square() : Rect() constructor {\n"
        "    static sq_only = function() { return \"square\"; };\n"
        "    static count = 0;\n"
        "    count++;\n"
        "}\n"
    ),
    "scr_tools": (
        "function counter() {\n"
        "    static count = 0;\n"
        "    return count++;\n"
        "}\n"
        "function vec2(_x, _y) constructor {\n"
        "    x = _x; y = _y;\n"
        "    static add = function(_b) { x += _b.x; y += _b.y; };\n"
        "}\n"
    ),
}

_CREATE = (
    'var _s = new Sword("excal");\n'
    'var _i = new Item("pot");\n'
    "var _p = new Plain();\n"
    "var _lit = {a: 1};\n"
    'trace("instanceof:" + string(instanceof(_s)) + "," + string(instanceof(_i)) + "," + string(instanceof(_p)) + "," + string(instanceof(_lit)) + "," + string(instanceof(self)) + "," + string(instanceof(weak_ref_create(_s))) + "," + string(instanceof(5)));\n'
    'trace("is_instanceof:" + string(is_instanceof(_s, Sword)) + string(is_instanceof(_s, Item)) + string(is_instanceof(_i, Sword)) + string(is_instanceof(_i, Item)) + string(is_instanceof(_p, Item)) + string(is_instanceof(_lit, Item)) + string(is_instanceof(5, Item)));\n'
    "var _ctor = Sword;\n"
    'trace("variable:" + string(is_instanceof(_s, _ctor)) + string(is_instanceof(_i, _ctor)));\n'
    'trace("calls:" + _s.slash() + "," + _s.hello());\n'
    "var _q = new Square();\n"
    'trace("levels:" + _q.sq_only() + "," + _q.rect_only() + "," + _q.name_of());\n'
    'trace("counts:" + string(Shape.count) + string(Rect.count) + string(Square.count));\n'
    'trace("squares:" + string(is_instanceof(_q, Square)) + string(is_instanceof(_q, Rect)) + string(is_instanceof(_q, Shape)) + string(is_instanceof(new Rect(), Square)) + string(instanceof(_q)));\n'
    "var _again = new Square();\n"
    'trace("again:" + _again.rect_only() + string(Shape.count) + string(Rect.count) + string(Square.count));\n'
)

_STATIC_API_CREATE = (
    "repeat (10) counter();\n"
    "var _static_counter = static_get(counter);\n"
    'trace("counter:" + string(counter.count) + " " + string(_static_counter.count));\n'
    'var _sword = new Sword("s");\n'
    "var _static_sword = static_get(_sword);\n"
    "var _static_item = static_get(_static_sword);\n"
    'trace("chain:" + string(_static_sword == static_get(Sword)) + string(_static_item == static_get(Item)));\n'
    'trace("parent:" + _static_item.hello());\n'
    "var _length = 0;\n"
    "var _node = static_get(Sword);\n"
    "while (!is_undefined(_node)) { _length++; _node = static_get(_node); }\n"
    'trace("length:" + string(_length) + " root:" + string(is_undefined(static_get(static_get(static_get(Item))))));\n'
    "var _a = new vec2(10, 10);\n"
    "var _b = {x: 4, y: 9};\n"
    "static_set(_b, static_get(vec2));\n"
    "_b.add(_a);\n"
    'trace("static_set:" + string(_b.x) + "," + string(_b.y) + " " + string(is_instanceof(_b, vec2)) + " " + instanceof(_b));\n'
)


class TestConstructorIdentityGodot(unittest.TestCase):
    def test_constructors_named_in_code_identify_their_structs(self) -> None:
        trace = run_gml_trace(self, _SCRIPTS, {EVENT_CREATE: _CREATE})

        self.assertEqual(
            trace,
            [
                "instanceof:Sword,Item,Plain,struct,instance,weakref,undefined",
                "is_instanceof:truetruefalsetruefalsefalsefalse",
                "variable:truefalse",
                "calls:slash excal,hello item",
                "levels:square,rect,shape",
                "counts:111",
                "squares:truetruetruefalseSquare",
                "again:rect332",
            ],
        )

    def test_static_get_and_static_set_follow_the_static_chain(self) -> None:
        trace = run_gml_trace(self, _SCRIPTS, {EVENT_CREATE: _STATIC_API_CREATE})

        self.assertEqual(
            trace,
            [
                "counter:10 10",
                "chain:truetrue",
                "parent:hello item",
                "length:3 root:true",
                "static_set:14,19 true struct",
            ],
        )


if __name__ == "__main__":
    unittest.main()
