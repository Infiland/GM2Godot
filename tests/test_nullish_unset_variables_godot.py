"""Godot checks for ?? and ??= on instance variables that were never assigned.

The manual's Expressions And Operators page: "If variable is undefined or
pointer_null, the null_value value will be assigned to it". The runner's
__yy_is_nullish is `v == undefined || v == null`, and a variable that was
never assigned reads undefined there, so ??= creates it and ?? takes the
right-hand side. In a converted object, the instance variables its events and
scripts assign are members of its script that read null until first assigned.
"""
from __future__ import annotations

import unittest

from tests.gamemaker_project_support import EVENT_CREATE
from tests.gml_trace_support import run_gml_trace

_SCRIPTS = {
    "scr_defaults": (
        "function init_bm() {\n"
        "    bm ??= 5;\n"
        "    bm ??= 99;\n"
        "    return bm;\n"
        "}\n"
        "function default_of_unset() {\n"
        "    return script_unset ?? 'fallback';\n"
        "}\n"
        "function assigns_later() {\n"
        "    script_unset = 1;\n"
        "}\n"
    ),
}

_CREATE = (
    "trace('script ??=:' + string(init_bm()));\n"
    "cm ??= 6;\n"
    "cm ??= 99;\n"
    "trace('event ??=:' + string(cm));\n"
    "trace('??:' + string(event_unset ?? 'dflt') + ' ' + default_of_unset());\n"
    "kept = 1;\n"
    "kept ??= 2;\n"
    "trace('kept:' + string(kept));\n"
    "gone = undefined;\n"
    "gone ??= 3;\n"
    "trace('undefined:' + string(gone));\n"
    "if (false) { event_unset = 0; }\n"
)


class TestNullishUnsetVariablesGodot(unittest.TestCase):
    def test_nullish_assignment_and_coalescing_treat_an_unassigned_instance_variable_as_nullish(self) -> None:
        trace = run_gml_trace(self, _SCRIPTS, {EVENT_CREATE: _CREATE})

        self.assertEqual(
            trace,
            [
                "script ??=:5",
                "event ??=:6",
                "??:dflt fallback",
                "kept:1",
                "undefined:3",
            ],
        )


if __name__ == "__main__":
    unittest.main()
