"""Godot checks for the names a static method reaches through self.

Static variables are scoped to the function that declares them (manual: GML
Overview > Functions > Static Variables). A function written inside it, a
static method or a method, reads and calls every other name through self, which
finds a static along the static chain (manual: Static Struct, "How the Dot
Operator Looks Up a Variable Name"), so a bare call inside Item's static method
runs the override a child constructor declares. A static method called through
a constructor (Registry.get()) runs with that constructor's static struct as
self, the struct static_get(Registry) returns.
"""
from __future__ import annotations

import unittest

from tests.gamemaker_project_support import EVENT_CREATE
from tests.gml_trace_support import run_gml_trace

_SCRIPTS = {
    "scr_items": (
        "function Item(_n) constructor {\n"
        "    name = _n;\n"
        "    static kind = function() { return \"item\"; };\n"
        "    static who = function() { return \"who:\" + kind() + \":\" + name; };\n"
        "    static tag = \"t-item\";\n"
        "    static tagged = function() { return tag; };\n"
        "    static rank = function() { static seen = 0; seen++; return seen; };\n"
        "    peek = function() { return tag + \"/\" + kind(); };\n"
        "    static init = function() { return \"init item\"; };\n"
        "    static fact = function(_n) { return _n <= 1 ? 1 : _n * fact(_n - 1); };\n"
        "    static tally = 0;\n"
        "    tally++;\n"
        "}\n"
        "function Potion(_n) : Item(_n) constructor {\n"
        "    static kind = function() { return \"potion\"; };\n"
        "    static tag = \"t-potion\";\n"
        "    static init = function() {\n"
        "        var _parent = static_get(static_get(self));\n"
        "        return \"init potion > \" + _parent.init();\n"
        "    };\n"
        "    static tally = 0;\n"
        "    tally++;\n"
        "}\n"
        "function Sword(_n) : Item(_n) constructor {\n"
        "    static kind = function() { return \"sword\"; };\n"
        "}\n"
        "function Registry() constructor {\n"
        "    static instance = undefined;\n"
        "    static get = function() {\n"
        "        if (is_undefined(instance)) instance = new Registry();\n"
        "        return instance;\n"
        "    };\n"
        "}\n"
    ),
}

_CREATE = (
    'var _item = new Item("a");\n'
    'var _potion = new Potion("b");\n'
    'var _sword = new Sword("c");\n'
    'trace("who:" + _item.who() + "," + _potion.who() + "," + _sword.who());\n'
    'trace("tagged:" + _item.tagged() + "," + _potion.tagged() + "," + _sword.tagged());\n'
    'trace("peek:" + _item.peek() + "," + _potion.peek() + "," + _sword.peek());\n'
    'trace("init:" + _potion.init());\n'
    'trace("rank:" + string(_item.rank()) + string(_potion.rank()) + string(_item.rank()));\n'
    'trace("fact:" + string(_item.fact(5)) + "," + string(Item.fact(5)) + "," + string(_potion.fact(4)));\n'
    'trace("tally:" + string(Item.tally) + string(Potion.tally));\n'
    "var _seed = new Registry();\n"
    'trace("registry:" + string(Registry.get() == Registry.get()) + " " + instanceof(Registry.get()));\n'
)


class TestStaticMethodSelfGodot(unittest.TestCase):
    def test_bare_names_in_a_static_method_resolve_through_self_and_the_static_chain(self) -> None:
        trace = run_gml_trace(self, _SCRIPTS, {EVENT_CREATE: _CREATE})

        self.assertEqual(
            trace,
            [
                "who:who:item:a,who:potion:b,who:sword:c",
                "tagged:t-item,t-potion,t-item",
                "peek:t-item/item,t-potion/potion,t-item/sword",
                "init:init potion > init item",
                "rank:123",
                "fact:120,120,24",
                "tally:31",
                "registry:true Registry",
            ],
        )


if __name__ == "__main__":
    unittest.main()
