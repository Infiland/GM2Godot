"""Godot checks for named functions declared inside object events.

A function declared in an event is available only in the context of its
instance, throughout the instance's lifetime (manual: GML Overview > Method
Variables, "Defining a function in an Object's event"). The instance's other
events call it by name, a call can come before the declaration in the same
event, and another object's function of the same name is a separate one. A
function declared in the Alarm 0 event can be called in the Create event,
"regardless of when that alarm event runs (or whether it runs at all)". A call
to a function by name goes straight to the function declared in the same
event, so a parent's talk() still reaches the parent's say_hello() when the
child declares its own (manual: GML Overview > Script Functions vs. Methods,
"Overridden Script Functions").
"""
from __future__ import annotations

import unittest

from tests.gamemaker_project_support import EVENT_CREATE, EVENT_STEP, GameMakerObject
from tests.gml_trace_support import run_gml_trace

EVENT_ALARM_0 = (2, 0)
EVENT_USER_0 = (7, 10)

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

    def test_function_declared_in_an_event_that_has_not_run_is_available_from_creation(self) -> None:
        create = (
            'trace("create:" + string(from_alarm(2)) + " " + string(from_user(3)));\n'
            "function in_create(_q) { return from_alarm(_q) + 1; }\n"
            'trace("nested:" + string(in_create(5)));\n'
        )
        step = (
            'if (!variable_global_exists("stepped")) {\n'
            "    global.stepped = true;\n"
            '    trace("step:" + string(from_alarm(4)));\n'
            "}\n"
        )
        # Alarm 0 is never set, and no user event 0 is ever performed.
        alarm = "function from_alarm(_q) { return _q * 10; }\ntrace(\"alarm ran\");\n"
        user = "function from_user(_q) { return _q + 100; }\n"

        trace = run_gml_trace(
            self,
            {},
            {EVENT_CREATE: create, EVENT_STEP: step, EVENT_ALARM_0: alarm, EVENT_USER_0: user},
        )

        self.assertEqual(trace, ["create:20 103", "nested:51", "step:40"])

    def test_call_goes_to_the_function_declared_in_the_same_event_not_to_the_variable(self) -> None:
        # The manual's example: talk() runs in the child, yet reaches the
        # parent's say_hello(), because the parent declared both with the
        # script function syntax. self.say_hello() calls the variable, which
        # the child's declaration assigned after the parent's.
        parent_create = (
            "function talk() { say_hello(); }\n"
            'function say_hello() { trace("I am the parent!"); }\n'
        )
        child_create = (
            "event_inherited();\n"
            'function say_hello() { trace("I am the child!"); }\n'
            'trace("talk");\n'
            "talk();\n"
            'trace("direct");\n'
            "say_hello();\n"
            'trace("self");\n'
            "self.say_hello();\n"
        )

        trace = run_gml_trace(
            self,
            {},
            {EVENT_CREATE: 'instance_create_layer(0, 0, "Instances", o_child);\n'},
            objects=(
                GameMakerObject("o_parent", {EVENT_CREATE: parent_create}),
                GameMakerObject("o_child", {EVENT_CREATE: child_create}, parent="o_parent"),
            ),
        )

        self.assertEqual(
            trace,
            [
                "talk",
                "I am the parent!",
                "direct",
                "I am the child!",
                "self",
                "I am the child!",
            ],
        )

    def test_method_variables_are_called_through_the_variable_so_the_child_overrides(self) -> None:
        # The manual's fix for the example above: method variable syntax makes
        # every call go through the variable.
        parent_create = (
            "talk = function() { say_hello(); };\n"
            'say_hello = function() { trace("I am the parent!"); };\n'
        )
        child_create = (
            "event_inherited();\n"
            'say_hello = function() { trace("I am the child!"); };\n'
            "talk();\n"
            "say_hello();\n"
        )

        trace = run_gml_trace(
            self,
            {},
            {EVENT_CREATE: 'instance_create_layer(0, 0, "Instances", o_child);\n'},
            objects=(
                GameMakerObject("o_parent", {EVENT_CREATE: parent_create}),
                GameMakerObject("o_child", {EVENT_CREATE: child_create}, parent="o_parent"),
            ),
        )

        self.assertEqual(trace, ["I am the child!", "I am the child!"])


if __name__ == "__main__":
    unittest.main()
