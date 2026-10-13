"""Godot checks for named functions declared inside object events.

A function declared in an event is available only in the context of its
instance, throughout the instance's lifetime (manual: GML Overview > Method
Variables, "Defining a function in an Object's event"). The instance's other
events call it by name, a call can come before the declaration in the same
event, and another object's function of the same name is a separate one.
"""
from __future__ import annotations

import unittest

from tests.gamemaker_project_support import EVENT_CREATE, EVENT_STEP, GameMakerObject
from tests.gml_trace_support import run_gml_trace

_SCRIPTS = {
    "scr_counter": (
        "function Counter() constructor {\n"
        "    n = 0;\n"
        "    function bump() { n += 1; return n; }\n"
        "    function bump_twice() { bump(); return bump(); }\n"
        "}\n"
        "function outer_with_inner(_start) {\n"
        "    function inner(_q) { return _q + 1; }\n"
        "    return inner(_start);\n"
        "}\n"
    ),
}

_CREATE = (
    "factor = 3;\n"
    'trace("early:" + string(ev_helper3(4)));\n'
    "function ev_helper3(_q) { return _q * 2; }\n"
    "function ev_scale(_q) { return _q * factor; }\n"
    'trace("same event:" + string(ev_helper3(3)) + " " + string(ev_scale(2)));\n'
    "var _m = ev_helper3;\n"
    'trace("as value:" + string(_m(7)));\n'
    "instance_create_layer(0, 0, \"Instances\", o_second);\n"
    'trace("after second:" + string(ev_helper3(5)));\n'
    "var _c = new Counter();\n"
    '_c.bump();\n'
    'trace("constructor:" + string(_c.bump()) + " " + string(_c.bump_twice()));\n'
    'trace("nested:" + string(outer_with_inner(1)));\n'
)

_STEP = (
    'if (!variable_global_exists("stepped")) {\n'
    "    global.stepped = true;\n"
    '    trace("step event:" + string(ev_helper3(6)) + " " + string(ev_scale(5)));\n'
    "}\n"
)

_SECOND_CREATE = (
    "function ev_helper3(_q) { return _q * 100; }\n"
    'trace("second:" + string(ev_helper3(1)));\n'
)


class TestEventFunctionDeclarationsGodot(unittest.TestCase):
    def test_event_function_is_a_method_of_its_instance_in_every_event(self) -> None:
        trace = run_gml_trace(
            self,
            _SCRIPTS,
            {EVENT_CREATE: _CREATE, EVENT_STEP: _STEP},
            objects=(GameMakerObject("o_second", {EVENT_CREATE: _SECOND_CREATE}),),
        )

        self.assertEqual(
            trace,
            [
                "early:8",
                "same event:6 6",
                "as value:14",
                "second:100",
                "after second:10",
                "constructor:2 4",
                "nested:2",
                "step event:12 15",
            ],
        )


if __name__ == "__main__":
    unittest.main()
