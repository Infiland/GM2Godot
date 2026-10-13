"""Godot checks for how a struct made by new reaches its constructor's statics.

Each struct carries its own link to the static struct of its constructor, as a
member GML code never sees. Looking a static up costs the same whatever order
structs are visited in, and a struct that is dropped takes its link with it
(a registry of every struct made by new grew without bound and was searched
linearly). The manual's Static Struct page describes the static chain the link
stands for (GML Overview > Structs > Static Struct).
"""
from __future__ import annotations

import unittest

from tests.gamemaker_project_support import EVENT_CREATE, EVENT_STEP
from tests.gml_trace_support import run_gml_trace, trace_probe

_SCRIPTS = {
    "scr_vec": (
        "function Vec(_x) constructor {\n"
        "    x = _x;\n"
        "    static kind = \"vec\";\n"
        "    static describe = function() { return \"I\"; };\n"
        "}\n"
    ),
    "scr_counter": (
        "function Counter(_n) constructor {\n"
        "    n = _n;\n"
        "    static inc = function() { n += 1; return n; };\n"
        "}\n"
    ),
}

_HIDDEN_CREATE = (
    "var _v = new Vec(3);\n"
    "var _w = {x: 3};\n"
    "var _names = variable_struct_get_names(_v);\n"
    'trace("names:" + string(array_length(_names)) + ":" + _names[0] + " count:" + string(variable_struct_names_count(_v)));\n'
    "global.seen = [];\n"
    "struct_foreach(_v, function(_name, _value) { array_push(global.seen, _name); });\n"
    'trace("foreach:" + string(array_length(global.seen)) + ":" + global.seen[0]);\n'
    'trace("json:" + json_stringify(_v));\n'
    'trace("string:" + string(string(_v) == string(_w)) + string(string([_v, [_v]]) == string([_w, [_w]])));\n'
    "var _c = variable_clone(_v);\n"
    "var _cn = variable_struct_get_names(_c);\n"
    'trace("clone:" + string(array_length(_cn)) + " describe:" + _c.describe() + " kind:" + _c.kind + " same:" + string(_c == _v));\n'
    'trace("eq:" + string(_v == _v) + string(_v == _w) + string(array_equals([_v], [_v])) + string(array_equals([_v], [_c])));\n'
    "var _sn = variable_struct_get_names(static_get(_v));\n"
    'trace("static:" + string(array_length(_sn)) + " count:" + string(variable_struct_names_count(static_get(_v))));\n'
    "var _l = ds_list_create();\n"
    "ds_list_add(_l, _v);\n"
    "var _lw = ds_list_create();\n"
    "ds_list_add(_lw, _w);\n"
    'trace("ds_list_write:" + string(ds_list_write(_l) == ds_list_write(_lw)));\n'
    "var _m = ds_map_create();\n"
    'ds_map_add(_m, "k", _v);\n'
    'trace("ds_map:" + json_encode(_m));\n'
    'trace("exists:" + string(variable_struct_exists(_v, "x")) + string(variable_struct_exists(_v, "kind")) + string(variable_struct_exists(_v, "nope")));\n'
)

_ORDER_CREATE = (
    "var _count = 8000;\n"
    "var _arr = [];\n"
    "for (var _i = 0; _i < _count; _i++) array_push(_arr, new Counter(_i));\n"
    "var _start = get_timer();\n"
    "var _sum = 0;\n"
    "for (var _i = 0; _i < _count; _i++) _sum += _arr[_i].inc();\n"
    "var _middle = get_timer();\n"
    "for (var _i = _count - 1; _i >= 0; _i--) _sum += _arr[_i].inc();\n"
    "var _end = get_timer();\n"
    'trace("sum:" + string(_sum));\n'
    'trace("forward:" + string((_middle - _start) div 1000));\n'
    'trace("reverse:" + string((_end - _middle) div 1000));\n'
)

_CHURN_STEP = (
    "repeat (20000) {\n"
    "    var _temporary = new Counter(1);\n"
    "    _temporary.inc();\n"
    "}\n"
)

_MEMORY_PROBE = trace_probe(
    declarations="var _baseline = 0\n",
    each_frame=(
        "\tif _frames == 2:\n"
        "\t\t_baseline = Performance.get_monitor(Performance.MEMORY_STATIC)\n"
    ),
    final=(
        "\t\tvar growth = Performance.get_monitor(Performance.MEMORY_STATIC) - _baseline\n"
        '\t\ttrace("growth:" + str(int(growth)))\n'
    ),
)


class TestStaticStructLinkGodot(unittest.TestCase):
    def test_the_static_link_is_not_a_visible_member(self) -> None:
        trace = run_gml_trace(self, _SCRIPTS, {EVENT_CREATE: _HIDDEN_CREATE})

        self.assertEqual(
            trace,
            [
                "names:1:x count:1",
                "foreach:1:x",
                'json:{"x":3}',
                "string:truetrue",
                "clone:1 describe:I kind:vec same:false",
                "eq:truefalsetruefalse",
                "static:2 count:2",
                "ds_list_write:true",
                'ds_map:{"k":{"x":3}}',
                "exists:truetruefalse",
            ],
        )

    def test_calls_cost_the_same_in_any_order(self) -> None:
        # 8000 calls in reverse creation order took 41 s while the same calls in
        # creation order took 170 ms (every lookup scanned the registry).
        trace = run_gml_trace(self, _SCRIPTS, {EVENT_CREATE: _ORDER_CREATE}, timeout=60)

        self.assertEqual(trace[0], "sum:64016000")
        forward = int(trace[1].removeprefix("forward:"))
        reverse = int(trace[2].removeprefix("reverse:"))
        self.assertLess(reverse, 3000, trace)
        self.assertLess(forward, 3000, trace)

    def test_dropped_structs_free_their_static_links(self) -> None:
        trace = run_gml_trace(
            self,
            _SCRIPTS,
            {EVENT_STEP: _CHURN_STEP},
            probe=_MEMORY_PROBE,
            timeout=120,
        )

        growth = int(trace[-1].removeprefix("growth:"))
        # 80000 temporary structs were made after the baseline; kept in a
        # registry they would hold tens of megabytes.
        self.assertLess(growth, 4 * 1024 * 1024, trace)


if __name__ == "__main__":
    unittest.main()
