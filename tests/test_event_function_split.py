"""Transpiler checks for the functions an object event declares.

The object converter binds the named functions declared at the top of an event
when the instance is built, and sends the event's own calls to them straight to
the member that holds the function (manual: GML Overview > Script Functions vs.
Methods, "Overridden Script Functions": a call to a script function goes to the
function with that name, not to the variable of the same name).
"""
from __future__ import annotations

import unittest

from src.conversion.gml_transpiler import transpile_gml_code_with_source_map
from src.conversion.gml_transpiler_parts.function_declarations import event_function_names
from src.conversion.gml_transpiler_parts.shared_models import EventFunctionSplit

_MEMBERS = {"talk": "_member_talk", "say_hello": "_member_say_hello"}
_NAMES = {*_MEMBERS, *_MEMBERS.values()}


def _transpile(source: str, part: str, members: dict[str, str] | None = None) -> str:
    assert part in ("body", "declarations")
    return transpile_gml_code_with_source_map(
        source,
        instance_target="self",
        instance_variables=set(_NAMES),
        direct_instance_names=set(_NAMES),
        event_functions=EventFunctionSplit(members if members is not None else _MEMBERS, part),
    ).code


class TestEventFunctionSplit(unittest.TestCase):
    def test_names_are_the_functions_declared_at_the_top_of_the_event(self) -> None:
        source = (
            "function talk() { say_hello(); }\n"
            "var f = function() {};\n"
            "if (x) { function nested() {} }\n"
            "function say_hello() {}\n"
            "function say_hello() {}\n"
        )

        self.assertEqual(event_function_names(source), ("talk", "say_hello"))
        self.assertEqual(event_function_names("x = 1;"), ())

    def test_body_holds_what_is_not_a_declaration_and_calls_the_member(self) -> None:
        source = (
            "function talk() { say_hello(); }\n"
            "function say_hello() { return 1; }\n"
            "var r = say_hello();\n"
            "other.say_hello();\n"
            "var s = say_hello;\n"
        )

        body = _transpile(source, "body")

        self.assertEqual(
            body.splitlines(),
            [
                '\tvar r = GMRuntime.gml_call_named("_member_say_hello", [], self, other)',
                '\tGMRuntime.gml_call_member(other, "say_hello", [], self, other)',
                "\tvar s = say_hello",
            ],
        )

    def test_declarations_are_followed_by_the_assignment_of_each_to_its_member(self) -> None:
        source = (
            "function talk() { say_hello(); }\n"
            "function say_hello() { return 1; }\n"
            "x = 1;\n"
        )

        declarations = _transpile(source, "declarations")

        self.assertIn('GMRuntime.gml_call_named("_member_say_hello", [], _gml_method_self, _gml_method_other)', declarations)
        self.assertIn("\t_member_talk = talk", declarations.splitlines())
        self.assertIn("\t_member_say_hello = say_hello", declarations.splitlines())
        self.assertNotIn("x = 1", declarations)

    def test_name_that_is_also_a_parameter_or_local_is_called_through_the_variable(self) -> None:
        source = (
            "function say_hello() {}\n"
            "function call_it(say_hello) { say_hello(); }\n"
            "say_hello();\n"
        )

        body = _transpile(source, "body", {"say_hello": "_member_say_hello"})

        self.assertEqual(body.splitlines(), ['\tGMRuntime.gml_call_named("say_hello", [], self, other)'])


if __name__ == "__main__":
    unittest.main()
