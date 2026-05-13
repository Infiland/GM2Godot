import os
import sys
import tempfile
import unittest
from dataclasses import dataclass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.gml_runtime import GML_RUNTIME_RELATIVE_PATH, GML_RUNTIME_SCRIPT, write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_expression


@dataclass(frozen=True)
class RuntimeValueParityCase:
    gml_expression: str
    gdscript_expression: str


def fnv1a32(value: str) -> int:
    hash_value = 2166136261
    for char in value:
        hash_value = ((hash_value ^ ord(char)) * 16777619) & 0xFFFFFFFF
    return hash_value


RUNTIME_VALUE_PARITY_CASES = (
    RuntimeValueParityCase("undefined", "GMRuntime.gml_undefined()"),
    RuntimeValueParityCase("all", "GMRuntime.gml_instance_all()"),
    RuntimeValueParityCase("noone", "GMRuntime.gml_instance_noone()"),
    RuntimeValueParityCase("with_targets(self)", "GMRuntime.gml_with_targets(self)"),
    RuntimeValueParityCase("with_targets(other)", "GMRuntime.gml_with_targets(other)"),
    RuntimeValueParityCase("with_targets(all)", "GMRuntime.gml_with_targets(GMRuntime.gml_instance_all())"),
    RuntimeValueParityCase("with_targets(noone)", "GMRuntime.gml_with_targets(GMRuntime.gml_instance_noone())"),
    RuntimeValueParityCase(
        "with_targets(o_enemy)",
        'GMRuntime.gml_with_targets(GMRuntime.gml_asset_get_index("o_enemy"))',
    ),
    RuntimeValueParityCase(
        "o_enemy.hp",
        'GMRuntime.gml_selector_get(GMRuntime.gml_asset_get_index("o_enemy"), "hp")',
    ),
    RuntimeValueParityCase("pointer_null", "GMRuntime.gml_pointer_null()"),
    RuntimeValueParityCase("pointer_invalid", "GMRuntime.gml_pointer_invalid()"),
    RuntimeValueParityCase("typeof(undefined)", "GMRuntime.gml_typeof(GMRuntime.gml_undefined())"),
    RuntimeValueParityCase("typeof(null)", "GMRuntime.gml_typeof(null)"),
    RuntimeValueParityCase("typeof(true)", "GMRuntime.gml_typeof(true)"),
    RuntimeValueParityCase("typeof(1)", "GMRuntime.gml_typeof(1)"),
    RuntimeValueParityCase("typeof(1.5)", "GMRuntime.gml_typeof(1.5)"),
    RuntimeValueParityCase("typeof([1])", "GMRuntime.gml_typeof([1])"),
    RuntimeValueParityCase("typeof({a: 1})", 'GMRuntime.gml_typeof(GMRuntime.gml_struct({"a": 1}))'),
    RuntimeValueParityCase("typeof(pointer_null)", "GMRuntime.gml_typeof(GMRuntime.gml_pointer_null())"),
    RuntimeValueParityCase("string(undefined)", "GMRuntime.gml_string(GMRuntime.gml_undefined())"),
    RuntimeValueParityCase("string(pointer_invalid)", "GMRuntime.gml_string(GMRuntime.gml_pointer_invalid())"),
    RuntimeValueParityCase("bool(undefined)", "GMRuntime.gml_bool(GMRuntime.gml_undefined())"),
    RuntimeValueParityCase(
        "undefined == undefined",
        "GMRuntime.gml_eq(GMRuntime.gml_undefined(), GMRuntime.gml_undefined())",
    ),
    RuntimeValueParityCase(
        "undefined != infinity",
        "GMRuntime.gml_ne(GMRuntime.gml_undefined(), INF)",
    ),
    RuntimeValueParityCase("bool(pointer_null)", "GMRuntime.gml_bool(GMRuntime.gml_pointer_null())"),
    RuntimeValueParityCase("bool(0.5)", "GMRuntime.gml_bool(0.5)"),
    RuntimeValueParityCase("bool(0.50001)", "GMRuntime.gml_bool(0.50001)"),
    RuntimeValueParityCase("is_bool(true)", "GMRuntime.is_bool(true)"),
    RuntimeValueParityCase('string("abc")', 'GMRuntime.gml_string("abc")'),
    RuntimeValueParityCase('typeof("abc")', 'GMRuntime.gml_typeof("abc")'),
    RuntimeValueParityCase('is_string("abc")', 'GMRuntime.is_string("abc")'),
    RuntimeValueParityCase("real(score)", "GMRuntime.gml_real(score)"),
    RuntimeValueParityCase("int64(score)", "GMRuntime.gml_int64(score)"),
    RuntimeValueParityCase('int64("42")', 'GMRuntime.gml_int64("42")'),
    RuntimeValueParityCase("int64(pointer_null)", "GMRuntime.gml_int64(GMRuntime.gml_pointer_null())"),
    RuntimeValueParityCase("typeof(int64(score))", "GMRuntime.gml_typeof(GMRuntime.gml_int64(score))"),
    RuntimeValueParityCase("string(int64(score))", "GMRuntime.gml_string(GMRuntime.gml_int64(score))"),
    RuntimeValueParityCase("bool(int64(score))", "GMRuntime.gml_bool(GMRuntime.gml_int64(score))"),
    RuntimeValueParityCase(
        'bool(handle_parse("ref ds_list 1"))',
        'GMRuntime.gml_bool(GMRuntime.gml_handle_parse("ref ds_list 1"))',
    ),
    RuntimeValueParityCase(
        "int64(score) + int64(delta)",
        "GMRuntime.gml_add(GMRuntime.gml_int64(score), GMRuntime.gml_int64(delta))",
    ),
    RuntimeValueParityCase("is_real(score)", "GMRuntime.is_real(score)"),
    RuntimeValueParityCase("is_numeric(score)", "GMRuntime.is_numeric(score)"),
    RuntimeValueParityCase("is_numeric(true)", "GMRuntime.is_numeric(true)"),
    RuntimeValueParityCase("is_int32(score)", "GMRuntime.is_int32(score)"),
    RuntimeValueParityCase("is_int32(2147483647)", "GMRuntime.is_int32(2147483647)"),
    RuntimeValueParityCase("is_int32(2147483648)", "GMRuntime.is_int32(2147483648)"),
    RuntimeValueParityCase("is_int64(score)", "GMRuntime.is_int64(score)"),
    RuntimeValueParityCase("is_int64(int64(2147483648))", "GMRuntime.is_int64(GMRuntime.gml_int64(2147483648))"),
    RuntimeValueParityCase("is_array(items)", "GMRuntime.is_array(items)"),
    RuntimeValueParityCase("is_struct(mystruct)", "GMRuntime.is_struct(mystruct)"),
    RuntimeValueParityCase("is_method(callback)", "GMRuntime.is_method(callback)"),
    RuntimeValueParityCase("is_callable(callback)", "GMRuntime.is_callable(callback)"),
    RuntimeValueParityCase("method(player, callback)", "GMRuntime.gml_method(player, callback)"),
    RuntimeValueParityCase("method(undefined, callback)", "GMRuntime.gml_method(self, callback)"),
    RuntimeValueParityCase("typeof(method(player, callback))", "GMRuntime.gml_typeof(GMRuntime.gml_method(player, callback))"),
    RuntimeValueParityCase(
        'typeof(handle_parse("ref script 1"))',
        'GMRuntime.gml_typeof(GMRuntime.gml_handle_parse("ref script 1"))',
    ),
    RuntimeValueParityCase(
        "method_get_self(method(player, callback))",
        "GMRuntime.gml_method_get_self(GMRuntime.gml_method(player, callback))",
    ),
    RuntimeValueParityCase(
        "method_get_index(method(player, callback))",
        "GMRuntime.gml_method_get_index(GMRuntime.gml_method(player, callback))",
    ),
    RuntimeValueParityCase("method_get_self(callback)", "GMRuntime.gml_method_get_self(callback)"),
    RuntimeValueParityCase("method_get_index(callback)", "GMRuntime.gml_method_get_index(callback)"),
    RuntimeValueParityCase("method_call(callback)", "GMRuntime.gml_method_call(callback)"),
    RuntimeValueParityCase(
        "method_call(callback, [1, 2, 3], 1, 2)",
        "GMRuntime.gml_method_call(callback, [1, 2, 3], 1, 2)",
    ),
    RuntimeValueParityCase(
        "method_call(callback, [1, 2, 3], -1, -2)",
        "GMRuntime.gml_method_call(callback, [1, 2, 3], -1, -2)",
    ),
    RuntimeValueParityCase('handle_parse("ref ds_list 1")', 'GMRuntime.gml_handle_parse("ref ds_list 1")'),
    RuntimeValueParityCase('ref_create(self, "text")', 'GMRuntime.gml_ref_create(self, "text")'),
    RuntimeValueParityCase(
        'handle_parse(string(ref_create(self, "text")))',
        'GMRuntime.gml_handle_parse(GMRuntime.gml_string(GMRuntime.gml_ref_create(self, "text")))',
    ),
    RuntimeValueParityCase("struct_foreach(mystruct, callback)", "GMRuntime.gml_struct_foreach(mystruct, callback)"),
    RuntimeValueParityCase("static_get(counter)", "GMRuntime.gml_static_get(counter)"),
    RuntimeValueParityCase(
        "static_set(mystruct, static_get(counter))",
        "GMRuntime.gml_static_set(mystruct, GMRuntime.gml_static_get(counter))",
    ),
    RuntimeValueParityCase("is_instanceof(mystruct, counter)", "GMRuntime.gml_is_instanceof(mystruct, counter)"),
    RuntimeValueParityCase("instanceof(mystruct)", "GMRuntime.gml_instanceof(mystruct)"),
    RuntimeValueParityCase('variable_get_hash("x")', 'GMRuntime.gml_variable_get_hash("x")'),
    RuntimeValueParityCase(
        'struct_get_from_hash(point, variable_get_hash("x"))',
        'GMRuntime.gml_struct_get_from_hash(point, GMRuntime.gml_variable_get_hash("x"))',
    ),
    RuntimeValueParityCase(
        'struct_set_from_hash(point, variable_get_hash("x"), 10)',
        'GMRuntime.gml_struct_set_from_hash(point, GMRuntime.gml_variable_get_hash("x"), 10)',
    ),
    RuntimeValueParityCase(
        'struct_exists_from_hash(point, variable_get_hash("x"))',
        'GMRuntime.gml_struct_exists_from_hash(point, GMRuntime.gml_variable_get_hash("x"))',
    ),
    RuntimeValueParityCase(
        'struct_remove_from_hash(point, variable_get_hash("x"))',
        'GMRuntime.gml_struct_remove_from_hash(point, GMRuntime.gml_variable_get_hash("x"))',
    ),
    RuntimeValueParityCase("ptr(0)", "GMRuntime.gml_ptr(0)"),
    RuntimeValueParityCase("typeof(ptr(0))", "GMRuntime.gml_typeof(GMRuntime.gml_ptr(0))"),
    RuntimeValueParityCase('ptr("42")', 'GMRuntime.gml_ptr("42")'),
    RuntimeValueParityCase('ptr(int64("42"))', 'GMRuntime.gml_ptr(GMRuntime.gml_int64("42"))'),
    RuntimeValueParityCase("is_ptr(ptr(0))", "GMRuntime.is_ptr(GMRuntime.gml_ptr(0))"),
    RuntimeValueParityCase("is_ptr(pointer_invalid)", "GMRuntime.is_ptr(GMRuntime.gml_pointer_invalid())"),
    RuntimeValueParityCase(
        'is_handle(handle_parse("ref ds_list 1"))',
        'GMRuntime.is_handle(GMRuntime.gml_handle_parse("ref ds_list 1"))',
    ),
    RuntimeValueParityCase(
        "pointer_null == pointer_null",
        "GMRuntime.gml_eq(GMRuntime.gml_pointer_null(), GMRuntime.gml_pointer_null())",
    ),
    RuntimeValueParityCase(
        "pointer_invalid != pointer_null",
        "GMRuntime.gml_ne(GMRuntime.gml_pointer_invalid(), GMRuntime.gml_pointer_null())",
    ),
    RuntimeValueParityCase(
        "instance_id != noone",
        "GMRuntime.gml_ne(instance_id, GMRuntime.gml_instance_noone())",
    ),
    RuntimeValueParityCase(
        "is_undefined(undefined)",
        "GMRuntime.is_undefined(GMRuntime.gml_undefined())",
    ),
    RuntimeValueParityCase("nan", "NAN"),
    RuntimeValueParityCase("real(NaN)", "GMRuntime.gml_real(NAN)"),
    RuntimeValueParityCase("is_numeric(NaN)", "GMRuntime.is_numeric(NAN)"),
    RuntimeValueParityCase("is_real(NaN)", "GMRuntime.is_real(NAN)"),
    RuntimeValueParityCase('real("0x00F")', 'GMRuntime.gml_real("0x00F")'),
    RuntimeValueParityCase(
        'real(handle_parse("ref ds_list 1"))',
        'GMRuntime.gml_real(GMRuntime.gml_handle_parse("ref ds_list 1"))',
    ),
    RuntimeValueParityCase("typeof(NaN)", "GMRuntime.gml_typeof(NAN)"),
    RuntimeValueParityCase("is_nan(NaN)", "GMRuntime.is_nan_value(NAN)"),
    RuntimeValueParityCase("is_nan(int64(0))", "GMRuntime.is_nan_value(GMRuntime.gml_int64(0))"),
    RuntimeValueParityCase("is_infinity(-infinity)", "GMRuntime.is_infinity(-INF)"),
    RuntimeValueParityCase("is_infinity(1)", "GMRuntime.is_infinity(1)"),
    RuntimeValueParityCase("0.5", "0.5"),
    RuntimeValueParityCase("100_000_000", "100000000"),
    RuntimeValueParityCase("3_141.59", "3141.59"),
    RuntimeValueParityCase("1.5 / 2", "GMRuntime.gml_div(1.5, 2)"),
    RuntimeValueParityCase("5 / 2", "GMRuntime.gml_div(5, 2)"),
    RuntimeValueParityCase(
        "int64(5) / int64(2)",
        "GMRuntime.gml_div(GMRuntime.gml_int64(5), GMRuntime.gml_int64(2))",
    ),
    RuntimeValueParityCase(
        "int64(5) div int64(2)",
        "GMRuntime.gml_int_div(GMRuntime.gml_int64(5), GMRuntime.gml_int64(2))",
    ),
    RuntimeValueParityCase("0 / 0", "GMRuntime.gml_div(0, 0)"),
    RuntimeValueParityCase("sqrt(-1)", "GMRuntime.gml_sqrt(-1)"),
    RuntimeValueParityCase("5 div 2", "GMRuntime.gml_int_div(5, 2)"),
    RuntimeValueParityCase("0xDEAD_BEEF", "0xDEADBEEF"),
    RuntimeValueParityCase("$2c8e", "0x2c8e"),
    RuntimeValueParityCase("#dd8e2c", "0x2c8edd"),
    RuntimeValueParityCase("#0000ff", "0xff0000"),
    RuntimeValueParityCase("#ff0000", "0x0000ff"),
    RuntimeValueParityCase("typeof(#dd8e2c)", "GMRuntime.gml_typeof(0x2c8edd)"),
    RuntimeValueParityCase("real($2c8e)", "GMRuntime.gml_real(0x2c8e)"),
    RuntimeValueParityCase("0b01101000_01101001", "0b0110100001101001"),
    RuntimeValueParityCase("0b0010 | 0b0100", "GMRuntime.gml_bit_or(0b0010, 0b0100)"),
    RuntimeValueParityCase("[1, score + 1]", "[1, GMRuntime.gml_add(score, 1)]"),
    RuntimeValueParityCase("items[-1]", "GMRuntime.gml_array_get(items, -1)"),
    RuntimeValueParityCase("room", 'GMRuntime.gml_builtin_global("room")'),
    RuntimeValueParityCase("room_width", 'GMRuntime.gml_builtin_global("room_width")'),
    RuntimeValueParityCase("room_height", 'GMRuntime.gml_builtin_global("room_height")'),
    RuntimeValueParityCase("instance_count", 'GMRuntime.gml_builtin_global("instance_count")'),
    RuntimeValueParityCase("async_load", 'GMRuntime.gml_builtin_global("async_load")'),
    RuntimeValueParityCase("event_data", 'GMRuntime.gml_builtin_global("event_data")'),
    RuntimeValueParityCase("argument", 'GMRuntime.gml_builtin_global("argument")'),
    RuntimeValueParityCase("argument_count", 'GMRuntime.gml_builtin_global("argument_count")'),
    RuntimeValueParityCase(
        "view_xview[0]",
        'GMRuntime.gml_array_get(GMRuntime.gml_builtin_array("view_xview"), 0)',
    ),
    RuntimeValueParityCase("array_equals([NaN], [NaN])", "GMRuntime.gml_array_equals([NAN], [NAN])"),
    RuntimeValueParityCase("array_push(items, 2, 3)", "GMRuntime.gml_array_push(items, 2, 3)"),
    RuntimeValueParityCase('asset_get_index("s_player")', 'GMRuntime.gml_asset_get_index("s_player")'),
    RuntimeValueParityCase("asset_get_type(sprite_index)", "GMRuntime.gml_asset_get_type(sprite_index)"),
    RuntimeValueParityCase("asset_get_ids()", "GMRuntime.gml_asset_get_ids()"),
    RuntimeValueParityCase('asset_get_ids("sprite")', 'GMRuntime.gml_asset_get_ids("sprite")'),
    RuntimeValueParityCase('asset_get_type_name("sprite")', 'GMRuntime.gml_asset_get_type_name("sprite")'),
    RuntimeValueParityCase(
        'asset_get_index_from_id("sprites/s_player/s_player.yy")',
        'GMRuntime.gml_asset_get_index_from_id("sprites/s_player/s_player.yy")',
    ),
    RuntimeValueParityCase(
        'asset_has_any_tag("s_player", ["player"])',
        'GMRuntime.gml_asset_has_any_tag("s_player", ["player"])',
    ),
    RuntimeValueParityCase(
        'instance_create_layer(x, y, "Instances", o_enemy)',
        'GMRuntime.gml_instance_create_layer(position.x, position.y, "Instances", GMRuntime.gml_asset_get_index("o_enemy"), self)',
    ),
    RuntimeValueParityCase(
        "instance_create_depth(x, y, -10, o_enemy)",
        'GMRuntime.gml_instance_create_depth(position.x, position.y, -10, GMRuntime.gml_asset_get_index("o_enemy"), self)',
    ),
    RuntimeValueParityCase("instance_destroy()", "GMRuntime.gml_instance_destroy(self)"),
    RuntimeValueParityCase("instance_destroy(other)", "GMRuntime.gml_instance_destroy(other)"),
    RuntimeValueParityCase(
        "instance_exists(o_enemy)",
        'GMRuntime.gml_instance_exists(GMRuntime.gml_asset_get_index("o_enemy"))',
    ),
    RuntimeValueParityCase(
        "instance_find(o_enemy, 0)",
        'GMRuntime.gml_instance_find(GMRuntime.gml_asset_get_index("o_enemy"), 0)',
    ),
    RuntimeValueParityCase(
        "instance_number(o_enemy)",
        'GMRuntime.gml_instance_number(GMRuntime.gml_asset_get_index("o_enemy"))',
    ),
    RuntimeValueParityCase(
        "instance_nearest(x, y, o_enemy)",
        'GMRuntime.gml_instance_nearest(position.x, position.y, GMRuntime.gml_asset_get_index("o_enemy"))',
    ),
    RuntimeValueParityCase(
        "instance_furthest(x, y, o_enemy)",
        'GMRuntime.gml_instance_furthest(position.x, position.y, GMRuntime.gml_asset_get_index("o_enemy"))',
    ),
    RuntimeValueParityCase("instance_id_get(0)", "GMRuntime.gml_instance_id_get(0)"),
    RuntimeValueParityCase(
        "place_meeting(x, y, o_enemy)",
        'GMRuntime.gml_place_meeting(self, position.x, position.y, GMRuntime.gml_asset_get_index("o_enemy"))',
    ),
    RuntimeValueParityCase(
        "position_meeting(target_x, target_y, all)",
        "GMRuntime.gml_position_meeting(self, target_x, target_y, GMRuntime.gml_instance_all())",
    ),
    RuntimeValueParityCase(
        "instance_place(x, y, o_enemy)",
        'GMRuntime.gml_instance_place(self, position.x, position.y, GMRuntime.gml_asset_get_index("o_enemy"))',
    ),
    RuntimeValueParityCase(
        "instance_position(target_x, target_y, o_enemy)",
        'GMRuntime.gml_instance_position(self, target_x, target_y, GMRuntime.gml_asset_get_index("o_enemy"))',
    ),
    RuntimeValueParityCase(
        "collision_point(target_x, target_y, o_enemy, true, true)",
        'GMRuntime.gml_collision_point(self, target_x, target_y, GMRuntime.gml_asset_get_index("o_enemy"), true, true)',
    ),
    RuntimeValueParityCase(
        "collision_rectangle(0, 0, 10, 10, o_enemy, false, true)",
        'GMRuntime.gml_collision_rectangle(self, 0, 0, 10, 10, GMRuntime.gml_asset_get_index("o_enemy"), false, true)',
    ),
    RuntimeValueParityCase(
        "collision_line(0, 0, 10, 10, o_enemy)",
        'GMRuntime.gml_collision_line(self, 0, 0, 10, 10, GMRuntime.gml_asset_get_index("o_enemy"))',
    ),
    RuntimeValueParityCase(
        "collision_circle(4, 5, 8, o_enemy, false, false)",
        'GMRuntime.gml_collision_circle(self, 4, 5, 8, GMRuntime.gml_asset_get_index("o_enemy"), false, false)',
    ),
    RuntimeValueParityCase("items == other_items", "GMRuntime.gml_eq(items, other_items)"),
    RuntimeValueParityCase("{a: 1}", 'GMRuntime.gml_struct({"a": 1})'),
    RuntimeValueParityCase("mystruct.a", 'GMRuntime.gml_selector_get(mystruct, "a")'),
    RuntimeValueParityCase('mystruct[$ "x"]', 'GMRuntime.gml_struct_get(mystruct, "x")'),
    RuntimeValueParityCase('struct_exists(mystruct, "x")', 'GMRuntime.gml_struct_exists(mystruct, "x")'),
    RuntimeValueParityCase('struct_get(mystruct, "x")', 'GMRuntime.gml_struct_get(mystruct, "x")'),
    RuntimeValueParityCase('struct_set(mystruct, "x", 1)', 'GMRuntime.gml_struct_set(mystruct, "x", 1)'),
    RuntimeValueParityCase('struct_remove(mystruct, "x")', 'GMRuntime.gml_struct_remove(mystruct, "x")'),
    RuntimeValueParityCase(
        'variable_struct_get(mystruct, "x")',
        'GMRuntime.gml_variable_struct_get(mystruct, "x")',
    ),
    RuntimeValueParityCase(
        'variable_instance_get(enemy, "hp")',
        'GMRuntime.gml_variable_instance_get(enemy, "hp")',
    ),
    RuntimeValueParityCase(
        'variable_instance_get(-1, "hp")',
        'GMRuntime.gml_variable_instance_get(self, "hp")',
    ),
    RuntimeValueParityCase(
        'variable_instance_get(-2, "hp")',
        'GMRuntime.gml_variable_instance_get(other, "hp")',
    ),
    RuntimeValueParityCase(
        'variable_instance_get_names(-3)',
        "GMRuntime.gml_variable_instance_get_names(GMRuntime.gml_instance_all())",
    ),
    RuntimeValueParityCase(
        'variable_instance_get(-4, "hp")',
        'GMRuntime.gml_variable_instance_get(GMRuntime.gml_instance_noone(), "hp")',
    ),
    RuntimeValueParityCase(
        'variable_instance_exists(enemy, "hp")',
        'GMRuntime.gml_variable_instance_exists(enemy, "hp")',
    ),
    RuntimeValueParityCase(
        'variable_instance_set(enemy, "hp", 10)',
        'GMRuntime.gml_variable_instance_set(enemy, "hp", 10)',
    ),
    RuntimeValueParityCase(
        'variable_instance_set(noone, "hp", 10)',
        'GMRuntime.gml_variable_instance_set(GMRuntime.gml_instance_noone(), "hp", 10)',
    ),
    RuntimeValueParityCase("global", "GMRuntime.gml_global_scope()"),
    RuntimeValueParityCase("global.score", 'GMRuntime.gml_selector_get(GMRuntime.gml_global_scope(), "score")'),
    RuntimeValueParityCase(
        'variable_instance_get(global, "score")',
        'GMRuntime.gml_variable_instance_get(GMRuntime.gml_global_scope(), "score")',
    ),
    RuntimeValueParityCase(
        "variable_instance_get_names(global)",
        "GMRuntime.gml_variable_instance_get_names(GMRuntime.gml_global_scope())",
    ),
    RuntimeValueParityCase(
        "variable_instance_names_count(global)",
        "GMRuntime.gml_variable_instance_names_count(GMRuntime.gml_global_scope())",
    ),
    RuntimeValueParityCase(
        "variable_instance_get_names(enemy)",
        "GMRuntime.gml_variable_instance_get_names(enemy)",
    ),
    RuntimeValueParityCase(
        "variable_instance_names_count(enemy)",
        "GMRuntime.gml_variable_instance_names_count(enemy)",
    ),
    RuntimeValueParityCase(
        "variable_instance_get_names(noone)",
        "GMRuntime.gml_variable_instance_get_names(GMRuntime.gml_instance_noone())",
    ),
    RuntimeValueParityCase(
        'variable_global_exists("score")',
        'GMRuntime.gml_variable_global_exists("score")',
    ),
    RuntimeValueParityCase(
        'variable_global_get("score")',
        'GMRuntime.gml_variable_global_get("score")',
    ),
    RuntimeValueParityCase(
        'variable_global_set("score", 10)',
        'GMRuntime.gml_variable_global_set("score", 10)',
    ),
    RuntimeValueParityCase(
        'ds_map_find_value(inventory, "food")',
        'GMRuntime.gml_ds_map_find_value(inventory, "food")',
    ),
    RuntimeValueParityCase('inventory[? "food"]', 'GMRuntime.gml_ds_map_find_value(inventory, "food")'),
    RuntimeValueParityCase("struct_get_names(mystruct)", "GMRuntime.gml_struct_get_names(mystruct)"),
    RuntimeValueParityCase("struct_names_count(mystruct)", "GMRuntime.gml_struct_names_count(mystruct)"),
    RuntimeValueParityCase('string({a: 1})', 'GMRuntime.gml_string(GMRuntime.gml_struct({"a": 1}))'),
    RuntimeValueParityCase("variable_clone(mystruct)", "GMRuntime.gml_variable_clone(mystruct)"),
    RuntimeValueParityCase("variable_clone(items, 0)", "GMRuntime.gml_variable_clone(items, 0)"),
    RuntimeValueParityCase("variable_clone(items, 1)", "GMRuntime.gml_variable_clone(items, 1)"),
    RuntimeValueParityCase("a + b", "GMRuntime.gml_add(a, b)"),
    RuntimeValueParityCase('"a" + "b"', 'GMRuntime.gml_add("a", "b")'),
    RuntimeValueParityCase('1 + "px"', 'GMRuntime.gml_add(1, "px")'),
    RuntimeValueParityCase('1.5 + "px"', 'GMRuntime.gml_add(1.5, "px")'),
    RuntimeValueParityCase('true + "!"', 'GMRuntime.gml_add(true, "!")'),
    RuntimeValueParityCase('"px" + 1.5', 'GMRuntime.gml_add("px", 1.5)'),
    RuntimeValueParityCase("true + true", "GMRuntime.gml_add(true, true)"),
    RuntimeValueParityCase('3 * "ha"', 'GMRuntime.gml_mul(3, "ha")'),
    RuntimeValueParityCase('2.5 * "ha"', 'GMRuntime.gml_mul(2.5, "ha")'),
    RuntimeValueParityCase('"ha" * 2', 'GMRuntime.gml_mul("ha", 2)'),
    RuntimeValueParityCase("undefined + 1", "GMRuntime.gml_add(GMRuntime.gml_undefined(), 1)"),
    RuntimeValueParityCase("[1] - 1", "GMRuntime.gml_sub([1], 1)"),
    RuntimeValueParityCase("a - b", "GMRuntime.gml_sub(a, b)"),
    RuntimeValueParityCase("a * b", "GMRuntime.gml_mul(a, b)"),
    RuntimeValueParityCase("a mod b", "GMRuntime.gml_mod(a, b)"),
    RuntimeValueParityCase("!0.5", "not GMRuntime.gml_bool(0.5)"),
    RuntimeValueParityCase(
        "0.25 || 1",
        "GMRuntime.gml_bool(0.25) or GMRuntime.gml_bool(1)",
    ),
    RuntimeValueParityCase(
        "score ?? fallback",
        "score if not GMRuntime.gml_is_nullish(score) else fallback",
    ),
)


TYPE_TABLE_VALUES = (
    ("Real", "1.5"),
    ("Bool", "true"),
    ("String", '"s"'),
    ("Int32", "1"),
    ("Int64", "int64(1)"),
    ("Ptr", "pointer_null"),
    ("undefined", "undefined"),
    ("Array", "[1]"),
)

TYPE_TABLE_COLUMNS = tuple(label for label, _source in TYPE_TABLE_VALUES)

_TYPE_TABLE_ALL_ERRORS = {
    column: "Error"
    for column in TYPE_TABLE_COLUMNS
}

_TYPE_TABLE_NUMERIC_ROWS = {
    "Real": {
        "Real": "Real",
        "Bool": "Real",
        "String": "Error",
        "Int32": "Real",
        "Int64": "Real",
        "Ptr": "Error",
        "undefined": "Error",
        "Array": "Error",
    },
    "Bool": {
        "Real": "Real",
        "Bool": "Real",
        "String": "Error",
        "Int32": "Real",
        "Int64": "Real",
        "Ptr": "Error",
        "undefined": "Error",
        "Array": "Error",
    },
    "String": _TYPE_TABLE_ALL_ERRORS,
    "Int32": {
        "Real": "Real",
        "Bool": "Real",
        "String": "Error",
        "Int32": "Int32",
        "Int64": "Int64",
        "Ptr": "Error",
        "undefined": "Error",
        "Array": "Error",
    },
    "Int64": {
        "Real": "Real",
        "Bool": "Real",
        "String": "Error",
        "Int32": "Int64",
        "Int64": "Int64",
        "Ptr": "Error",
        "undefined": "Error",
        "Array": "Error",
    },
    "Ptr": _TYPE_TABLE_ALL_ERRORS,
    "undefined": _TYPE_TABLE_ALL_ERRORS,
    "Array": _TYPE_TABLE_ALL_ERRORS,
}

TYPE_TABLE_OPERATORS = (
    (
        "+",
        "gml_add",
        {
            **_TYPE_TABLE_NUMERIC_ROWS,
            "Real": {**_TYPE_TABLE_NUMERIC_ROWS["Real"], "String": "String"},
            "Bool": {**_TYPE_TABLE_NUMERIC_ROWS["Bool"], "String": "String"},
            "String": {**_TYPE_TABLE_ALL_ERRORS, "String": "String"},
            "Int32": {**_TYPE_TABLE_NUMERIC_ROWS["Int32"], "String": "String"},
            "Int64": {**_TYPE_TABLE_NUMERIC_ROWS["Int64"], "String": "String"},
        },
    ),
    ("-", "gml_sub", _TYPE_TABLE_NUMERIC_ROWS),
    (
        "*",
        "gml_mul",
        {
            **_TYPE_TABLE_NUMERIC_ROWS,
            "Real": {**_TYPE_TABLE_NUMERIC_ROWS["Real"], "String": "String"},
            "Int32": {**_TYPE_TABLE_NUMERIC_ROWS["Int32"], "String": "String"},
        },
    ),
    ("/", "gml_div", _TYPE_TABLE_NUMERIC_ROWS),
    ("div", "gml_int_div", _TYPE_TABLE_NUMERIC_ROWS),
    ("mod", "gml_mod", _TYPE_TABLE_NUMERIC_ROWS),
)


class TestGMLRuntimeScript(unittest.TestCase):
    def test_runtime_defines_shared_value_helpers(self):
        for helper_name in (
            "gml_undefined",
            "gml_pointer_null",
            "gml_pointer_invalid",
            "gml_builtin_array",
            "gml_builtin_global",
            "is_undefined",
            "is_bool",
            "is_string",
            "is_number",
            "is_real",
            "is_numeric",
            "is_int32",
            "is_int64",
            "is_ptr",
            "is_handle",
            "is_array",
            "is_struct",
            "is_method",
            "is_callable",
            "is_gml_exception",
            "is_nan_value",
            "is_infinity",
            "gml_eq",
            "gml_ne",
            "gml_div",
            "gml_int_div",
            "gml_real",
            "gml_int64",
            "gml_ptr",
            "gml_handle_register",
            "gml_handle_get",
            "gml_handle_invalid",
            "gml_instance_noone",
            "gml_instance_all",
            "gml_instance_register",
            "gml_instance_unregister",
            "gml_instance_destroy",
            "gml_instance_exists",
            "gml_instance_find",
            "gml_instance_number",
            "gml_instance_id_get",
            "gml_instance_nearest",
            "gml_instance_furthest",
            "gml_instance_create_layer",
            "gml_instance_create_depth",
            "gml_with_targets",
            "gml_place_meeting",
            "gml_position_meeting",
            "gml_instance_place",
            "gml_instance_position",
            "gml_collision_point",
            "gml_collision_rectangle",
            "gml_collision_line",
            "gml_collision_circle",
            "gml_selector_get",
            "gml_selector_exists",
            "gml_selector_set",
            "gml_selector_update",
            "gml_selector_set_if_nullish",
            "gml_selector_get_names",
            "gml_selector_names_count",
            "gml_handle_is_valid",
            "gml_handle_parse",
            "gml_ref_create",
            "gml_handle_from_value",
            "gml_handle_resolve_for_kind",
            "gml_handle_resolve",
            "gml_handle_invalidate",
            "gml_method",
            "gml_constructor",
            "gml_new",
            "gml_throw",
            "gml_exception_value",
            "gml_exception_struct",
            "gml_method_call",
            "gml_method_get_self",
            "gml_method_get_index",
            "gml_repeat_count",
            "gml_sqrt",
            "gml_add",
            "gml_sub",
            "gml_mul",
            "gml_mod",
            "gml_array_get",
            "gml_array_set",
            "gml_array_push",
            "gml_array_equals",
            "gml_asset_registry_set",
            "gml_asset_registry_entries",
            "gml_asset_get_index",
            "gml_asset_get_type",
            "gml_asset_get_ids",
            "gml_asset_get_type_name",
            "gml_asset_get_index_from_id",
            "gml_asset_has_any_tag",
            "gml_asset_register_dynamic",
            "gml_asset_release",
            "gml_struct",
            "gml_enum",
            "gml_struct_exists",
            "gml_struct_get",
            "gml_struct_get_names",
            "gml_struct_names_count",
            "gml_struct_set",
            "gml_struct_remove",
            "gml_struct_foreach",
            "gml_static_get",
            "gml_static_set",
            "gml_is_instanceof",
            "gml_instanceof",
            "gml_variable_get_hash",
            "gml_struct_get_from_hash",
            "gml_struct_set_from_hash",
            "gml_struct_exists_from_hash",
            "gml_struct_remove_from_hash",
            "gml_global_scope",
            "gml_variable_struct_get",
            "gml_variable_instance_exists",
            "gml_variable_instance_get",
            "gml_variable_instance_set",
            "gml_variable_instance_get_names",
            "gml_variable_instance_names_count",
            "gml_variable_global_exists",
            "gml_variable_global_get",
            "gml_variable_global_set",
            "gml_ds_map_find_value",
            "gml_ds_map_exists",
            "gml_ds_map_set",
            "gml_variable_clone",
            "gml_bit_and",
            "gml_bit_or",
            "gml_bit_xor",
            "gml_bit_not",
            "gml_shift_left",
            "gml_shift_right",
            "gml_typeof",
            "gml_string",
            "gml_bool",
            "gml_is_nullish",
            "gml_type_name",
            "gml_unsupported_type_error",
            "gml_unsupported_binary_type_error",
        ):
            self.assertIn(f"static func {helper_name}", GML_RUNTIME_SCRIPT)

    def test_runtime_helpers_keep_any_values_untyped(self):
        self.assertNotRegex(GML_RUNTIME_SCRIPT, r"static func \w+\([^)]*:\s")
        self.assertNotIn("Array[", GML_RUNTIME_SCRIPT)
        self.assertNotIn("Dictionary[", GML_RUNTIME_SCRIPT)
        self.assertNotIn("->", GML_RUNTIME_SCRIPT)

    def test_runtime_unsupported_any_diagnostics_name_type(self):
        self.assertIn("static func gml_type_name(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return \"godot_type_\" + str(typeof(value))", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_unsupported_type_error(api_name, value):", GML_RUNTIME_SCRIPT)
        self.assertIn(
            'return gml_error(str(api_name) + " does not support value of type " + gml_type_name(value))',
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("static func gml_unsupported_binary_type_error(api_name, left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("+ gml_type_name(left)", GML_RUNTIME_SCRIPT)
        self.assertIn("+ gml_type_name(right)", GML_RUNTIME_SCRIPT)

    def test_runtime_uses_distinct_undefined_sentinel(self):
        self.assertIn("class GMLUndefined:", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_undefined = GMLUndefined.new()", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_undefined():\n\treturn _gml_undefined", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_undefined(value):\n\treturn value is GMLUndefined", GML_RUNTIME_SCRIPT)

    def test_runtime_represents_pointer_values(self):
        self.assertIn('const GML_TYPE_POINTER = "ptr"', GML_RUNTIME_SCRIPT)
        self.assertIn("class GMLPointer:", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_pointer_null = GMLPointer.new(0)", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_pointer_invalid = GMLPointer.new(-1, true)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_pointer_null():\n\treturn _gml_pointer_null", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_pointer_invalid():\n\treturn _gml_pointer_invalid", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_ptr(value):\n\treturn value is GMLPointer", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_ptr(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_string(value):\n\t\tvar pointer_value = _gml_string_to_int64(value)", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_undefined(pointer_value):\n\t\t\treturn pointer_value", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLPointer.new(pointer_value)", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_number(value):\n\t\treturn GMLPointer.new(int(value))", GML_RUNTIME_SCRIPT)

    def test_runtime_defines_shared_handle_registry(self):
        self.assertIn("class GMLHandle:", GML_RUNTIME_SCRIPT)
        self.assertIn("var kind = \"\"", GML_RUNTIME_SCRIPT)
        self.assertIn("var index = -1", GML_RUNTIME_SCRIPT)
        self.assertIn("var reference = null", GML_RUNTIME_SCRIPT)
        self.assertIn("var valid = false", GML_RUNTIME_SCRIPT)
        self.assertIn("var name = \"\"", GML_RUNTIME_SCRIPT)
        self.assertIn("var type_id = 0", GML_RUNTIME_SCRIPT)
        self.assertIn("var value = 0", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_handle_registry = {}", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_handle_next_indices = {}", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_handle_register(kind, reference, name = \"\"):", GML_RUNTIME_SCRIPT)
        self.assertIn("var handle_index = _gml_next_handle_index(handle_kind)", GML_RUNTIME_SCRIPT)
        self.assertIn("var handle = _gml_make_handle(handle_kind, handle_index, reference, str(name), true)", GML_RUNTIME_SCRIPT)
        self.assertIn("_gml_handle_registry[_gml_handle_key(handle_kind, handle_index)] = handle", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_handle_get(kind, index):", GML_RUNTIME_SCRIPT)
        self.assertIn("if _gml_handle_registry.has(key):", GML_RUNTIME_SCRIPT)
        self.assertIn("return _gml_make_handle(handle_kind, handle_index, null, \"\", false)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_handle_resolve(handle):", GML_RUNTIME_SCRIPT)
        self.assertIn("if gml_handle_is_valid(handle):", GML_RUNTIME_SCRIPT)
        self.assertIn("return handle.reference", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_handle_invalidate(handle):", GML_RUNTIME_SCRIPT)
        self.assertIn("handle.valid = false", GML_RUNTIME_SCRIPT)
        self.assertIn("_gml_handle_registry.erase(old_key)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_next_handle_index(kind):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_handle_key(kind, index):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_make_handle(kind, index, reference, name, is_valid):", GML_RUNTIME_SCRIPT)

    def test_runtime_encodes_typed_handle_values(self):
        self.assertIn("const GML_HANDLE_TYPE_SHIFT = 32", GML_RUNTIME_SCRIPT)
        self.assertIn("const GML_HANDLE_INDEX_MASK = 0xffffffff", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_handle_type_ids = {}", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_handle_next_type_id = 1", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_handle(value):\n\treturn value is GMLHandle", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_int64(value):\n\treturn value is GMLInt64", GML_RUNTIME_SCRIPT)
        self.assertIn("var handle_type_id = _gml_handle_type_id(handle_kind)", GML_RUNTIME_SCRIPT)
        self.assertIn("var encoded_value = _gml_encode_handle_value(handle_type_id, handle_index)", GML_RUNTIME_SCRIPT)
        self.assertIn("type_id = int(handle_type_id)", GML_RUNTIME_SCRIPT)
        self.assertIn("value = int(encoded_value)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_handle_type_id(kind):", GML_RUNTIME_SCRIPT)
        self.assertIn("_gml_handle_type_ids[handle_kind] = _gml_handle_next_type_id", GML_RUNTIME_SCRIPT)
        self.assertIn("_gml_handle_next_type_id += 1", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_encode_handle_value(type_id, index):", GML_RUNTIME_SCRIPT)
        self.assertIn(
            "return (int(type_id) << GML_HANDLE_TYPE_SHIFT) | (int(index) & GML_HANDLE_INDEX_MASK)",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("if is_handle(value):\n\t\treturn GMLInt64.new(value.index)", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_handle(value):\n\t\treturn float(value.index)", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_handle(value):\n\t\treturn int(value.value)", GML_RUNTIME_SCRIPT)

    def test_runtime_normalizes_invalid_handle_values(self):
        self.assertIn("const GML_HANDLE_INVALID_INDEX = -1", GML_RUNTIME_SCRIPT)
        self.assertIn("const GML_INSTANCE_SELF_INDEX = -1", GML_RUNTIME_SCRIPT)
        self.assertIn("const GML_INSTANCE_OTHER_INDEX = -2", GML_RUNTIME_SCRIPT)
        self.assertIn("const GML_INSTANCE_ALL_INDEX = -3", GML_RUNTIME_SCRIPT)
        self.assertIn("const GML_INSTANCE_INVALID_INDEX = -4", GML_RUNTIME_SCRIPT)
        self.assertIn('const GML_INSTANCE_HANDLE_KIND = "instance"', GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_handle_invalid(kind = \"\", invalid_index = GML_HANDLE_INVALID_INDEX):", GML_RUNTIME_SCRIPT)
        self.assertIn("return _gml_make_handle(str(kind), int(invalid_index), null, \"\", false)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_instance_noone():", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_handle_invalid(GML_INSTANCE_HANDLE_KIND, GML_INSTANCE_INVALID_INDEX)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_instance_all():", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_handle_invalid(GML_INSTANCE_HANDLE_KIND, GML_INSTANCE_ALL_INDEX)", GML_RUNTIME_SCRIPT)
        self.assertIn('const GML_REFERENCE_HANDLE_KIND = "dbgref"', GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_handle_is_valid(handle):", GML_RUNTIME_SCRIPT)
        self.assertIn("if _gml_is_invalid_handle_index(handle.kind, handle.index):", GML_RUNTIME_SCRIPT)
        self.assertIn("if handle.reference is Object and not is_instance_valid(handle.reference):", GML_RUNTIME_SCRIPT)

    def test_runtime_resolves_instance_keywords_as_with_targets(self):
        self.assertIn("static func gml_with_targets(target, current_self = null, current_other = null):", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_undefined(target):\n\t\treturn []", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_handle(target) and target.kind == GML_INSTANCE_HANDLE_KIND:", GML_RUNTIME_SCRIPT)
        self.assertIn("return _gml_instance_keyword_targets(target, current_self, current_other)", GML_RUNTIME_SCRIPT)
        self.assertIn(
            "var keyword_targets = _gml_legacy_instance_keyword_targets(keyword_index, current_self, current_other)",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("if keyword_targets != null:\n\t\t\treturn keyword_targets", GML_RUNTIME_SCRIPT)
        self.assertIn("return [resolved_instance]", GML_RUNTIME_SCRIPT)
        self.assertIn(
            "static func _gml_instance_keyword_targets(handle, current_self = null, current_other = null):",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn(
            "var keyword_targets = _gml_legacy_instance_keyword_targets(handle.index, current_self, current_other)",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("static func _gml_legacy_instance_keyword_targets(keyword_index, current_self, current_other):", GML_RUNTIME_SCRIPT)
        self.assertIn("if keyword_index == GML_INSTANCE_SELF_INDEX:\n\t\treturn [] if current_self == null else [current_self]", GML_RUNTIME_SCRIPT)
        self.assertIn("if keyword_index == GML_INSTANCE_OTHER_INDEX:\n\t\treturn [] if current_other == null else [current_other]", GML_RUNTIME_SCRIPT)
        self.assertIn("if keyword_index == GML_INSTANCE_ALL_INDEX:\n\t\treturn _gml_all_instance_targets()", GML_RUNTIME_SCRIPT)
        self.assertIn("if keyword_index == GML_INSTANCE_INVALID_INDEX:\n\t\treturn []", GML_RUNTIME_SCRIPT)
        self.assertIn("return null", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_all_instance_targets():", GML_RUNTIME_SCRIPT)
        self.assertIn("for entry in _gml_live_instance_entries():", GML_RUNTIME_SCRIPT)
        self.assertIn('targets.append(entry["instance"])', GML_RUNTIME_SCRIPT)
        self.assertIn("gml_handle_invalidate(handle)", GML_RUNTIME_SCRIPT)
        self.assertIn("if _gml_is_invalid_handle_index(handle_kind, handle_index):", GML_RUNTIME_SCRIPT)

    def test_runtime_selector_helpers_use_with_targets(self):
        self.assertIn("static func gml_selector_get(target, member_name, current_self = null, current_other = null):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_struct_get(targets[0], member_name)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_selector_exists(target, member_name, current_self = null, current_other = null):", GML_RUNTIME_SCRIPT)
        self.assertIn("if gml_struct_exists(instance, member_name):\n\t\t\treturn true", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_selector_set(target, member_name, value, current_self = null, current_other = null):", GML_RUNTIME_SCRIPT)
        self.assertIn("for instance in targets:\n\t\tgml_struct_set(instance, member_name, value)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_selector_update(target, member_name, update_callable, current_self = null, current_other = null):", GML_RUNTIME_SCRIPT)
        self.assertIn("result = update_callable.call(gml_struct_get(instance, member_name))", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_selector_set_if_nullish(target, member_name, value_callable, current_self = null, current_other = null):", GML_RUNTIME_SCRIPT)
        self.assertIn("result = gml_struct_set(instance, member_name, value_callable.call())", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_selector_get_names(target, current_self = null, current_other = null):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_selector_names_count(target, current_self = null, current_other = null):", GML_RUNTIME_SCRIPT)
        self.assertIn("handle.reference = null", GML_RUNTIME_SCRIPT)
        self.assertIn("handle.index = _gml_invalid_handle_index(handle.kind)", GML_RUNTIME_SCRIPT)
        self.assertIn("handle.value = _gml_encode_handle_value(handle.type_id, handle.index)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_invalid_handle_index(kind):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_is_invalid_handle_index(kind, index):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_handle_eq(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return left.kind == right.kind and left.index == right.index", GML_RUNTIME_SCRIPT)
        self.assertIn("return left.index == _to_int64_value(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_handle(value):\n\t\treturn gml_handle_is_valid(value)", GML_RUNTIME_SCRIPT)

    def test_runtime_tracks_instance_registry_and_object_selectors(self):
        self.assertIn("static var _gml_instance_entries = {}", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_instance_ids_by_object = {}", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_instance_register(instance, object_selector = null, parent_selectors = []):", GML_RUNTIME_SCRIPT)
        self.assertIn('"selector_ids": selector_ids,', GML_RUNTIME_SCRIPT)
        self.assertIn('"selector_names": selector_names,', GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_instance_unregister(instance_or_handle):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_instance_selector_targets(selector):", GML_RUNTIME_SCRIPT)
        self.assertIn("_gml_instance_targets_from_indices(_gml_instance_ids_by_object[object_id])", GML_RUNTIME_SCRIPT)
        self.assertIn("_gml_instance_targets_from_indices(_gml_instance_ids_by_object_name[object_name])", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_instance_create_layer(x, y, layer, object_selector, current_self = null):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_instance_destroy(target = null):", GML_RUNTIME_SCRIPT)
        self.assertIn("instance.call(\"_on_destroy\")", GML_RUNTIME_SCRIPT)
        self.assertIn("instance.queue_free()", GML_RUNTIME_SCRIPT)

    def test_runtime_collision_queries_use_generated_shape_bounds(self):
        self.assertIn("static func gml_place_meeting(current_self, x, y, target):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_position_meeting(current_self, x, y, target):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_instance_place(current_self, x, y, target):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_instance_position(current_self, x, y, target):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_collision_point(current_self, x, y, target, precise = false, notme = false):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_collision_rectangle(current_self, x1, y1, x2, y2, target, precise = false, notme = false):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_collision_line(current_self, x1, y1, x2, y2, target, precise = false, notme = false):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_collision_circle(current_self, x, y, radius, target, precise = false, notme = false):", GML_RUNTIME_SCRIPT)
        self.assertIn("push_warning(\"GML precise collision masks are approximated with generated collision shape bounds\")", GML_RUNTIME_SCRIPT)
        self.assertIn("if node is CollisionShape2D:", GML_RUNTIME_SCRIPT)
        self.assertIn("if shape is RectangleShape2D:", GML_RUNTIME_SCRIPT)
        self.assertIn("if shape is CircleShape2D:", GML_RUNTIME_SCRIPT)
        self.assertIn("if query_rect.intersects(target_rect, true):", GML_RUNTIME_SCRIPT)
        self.assertIn("_gml_collision_segments_intersect(start, finish, top_left, top_right)", GML_RUNTIME_SCRIPT)
        self.assertIn("return center.distance_squared_to(Vector2(nearest_x, nearest_y)) <= radius * radius", GML_RUNTIME_SCRIPT)

    def test_runtime_converts_and_parses_handle_strings(self):
        self.assertIn("static func gml_string(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_handle(value):\n\t\treturn _gml_handle_to_string(value)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_handle_to_string(handle):", GML_RUNTIME_SCRIPT)
        self.assertIn("var label = handle.name if str(handle.name) != \"\" else str(handle.index)", GML_RUNTIME_SCRIPT)
        self.assertIn('return "ref " + str(handle.kind) + " " + str(label)', GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_handle_parse(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("var parts = str(value).split(\" \", false)", GML_RUNTIME_SCRIPT)
        self.assertIn("if parts.size() != 3 or parts[0] != \"ref\":", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_handle_invalid()", GML_RUNTIME_SCRIPT)
        self.assertIn("if _gml_string_is_int(identifier):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_handle_get(kind, int(identifier))", GML_RUNTIME_SCRIPT)
        self.assertIn("return _gml_handle_get_by_name(kind, identifier)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_handle_get_by_name(kind, name):", GML_RUNTIME_SCRIPT)
        self.assertIn("for handle in _gml_handle_registry.values():", GML_RUNTIME_SCRIPT)
        self.assertIn("if handle.kind == handle_kind and handle.name == handle_name:", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_handle_invalid(handle_kind)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_string_is_int(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("var start = 1 if text.begins_with(\"-\") else 0", GML_RUNTIME_SCRIPT)
        self.assertIn("var code = text.unicode_at(index)", GML_RUNTIME_SCRIPT)

    def test_runtime_creates_debug_reference_handles_for_round_trip(self):
        self.assertIn("static func gml_ref_create(target, member_or_index, array_index = null):", GML_RUNTIME_SCRIPT)
        self.assertIn('"target": target,', GML_RUNTIME_SCRIPT)
        self.assertIn('"member_or_index": member_or_index,', GML_RUNTIME_SCRIPT)
        self.assertIn('"has_array_index": array_index != null,', GML_RUNTIME_SCRIPT)
        self.assertIn('"array_index": array_index', GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_handle_register(GML_REFERENCE_HANDLE_KIND, descriptor)", GML_RUNTIME_SCRIPT)

    def test_runtime_accepts_legacy_numeric_handle_ids_at_api_boundary(self):
        self.assertIn("static func gml_handle_from_value(kind, value):", GML_RUNTIME_SCRIPT)
        self.assertIn("var handle_kind = str(kind)", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_handle(value):\n\t\tif value.kind == handle_kind:\n\t\t\treturn value", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_string(value):\n\t\tvar parsed = gml_handle_parse(value)", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_handle(parsed) and parsed.kind == handle_kind:\n\t\t\treturn parsed", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_numeric(value):\n\t\treturn gml_handle_get(handle_kind, _to_int64_value(value))", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_handle_invalid(handle_kind)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_handle_resolve_for_kind(kind, value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_handle_resolve(gml_handle_from_value(kind, value))", GML_RUNTIME_SCRIPT)

    def test_runtime_method_call_slices_array_arguments(self):
        self.assertIn("static func gml_method_call(method, array_args = null, offset = 0, num_args = null):", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_type_error("GML method_call", method)', GML_RUNTIME_SCRIPT)
        self.assertIn("var call_args = _gml_method_call_args(array_args, offset, num_args)", GML_RUNTIME_SCRIPT)
        self.assertIn("return method.gml_callv(call_args)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_method_call_args(array_args, offset, num_args):", GML_RUNTIME_SCRIPT)
        self.assertIn("var source = [] if array_args == null else array_args", GML_RUNTIME_SCRIPT)
        self.assertIn("if typeof(source) != TYPE_ARRAY:", GML_RUNTIME_SCRIPT)
        self.assertIn("if start < 0:\n\t\tstart = source_size + start", GML_RUNTIME_SCRIPT)
        self.assertIn("var count = source_size - start if num_args == null else int(_to_real(num_args))", GML_RUNTIME_SCRIPT)
        self.assertIn("var step = -1 if count < 0 else 1", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_error(\"GML method_call argument range out of bounds\")", GML_RUNTIME_SCRIPT)

    def test_runtime_method_accessors_expose_bound_self_and_index(self):
        self.assertIn("class GMLMethod:", GML_RUNTIME_SCRIPT)
        self.assertIn("var bound_self = null", GML_RUNTIME_SCRIPT)
        self.assertIn("var function_value = null", GML_RUNTIME_SCRIPT)
        self.assertIn("var is_constructor = false", GML_RUNTIME_SCRIPT)
        self.assertIn("bound_self = method_self", GML_RUNTIME_SCRIPT)
        self.assertIn("function_value = method_function", GML_RUNTIME_SCRIPT)
        self.assertIn("is_constructor = bool(method_is_constructor)", GML_RUNTIME_SCRIPT)
        self.assertIn("func gml_callv(args):", GML_RUNTIME_SCRIPT)
        self.assertIn("return function_value.callv(args)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_method(scope, func_or_method, method_is_constructor = false):", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_type_error("GML method", func_or_method)', GML_RUNTIME_SCRIPT)
        self.assertIn("var function_value = gml_method_get_index(func_or_method)", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLMethod.new(scope, function_value, method_is_constructor)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_method_get_self(method):", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_type_error("GML method_get_self", method)', GML_RUNTIME_SCRIPT)
        self.assertIn("if method is GMLMethod:", GML_RUNTIME_SCRIPT)
        self.assertIn("return method.bound_self", GML_RUNTIME_SCRIPT)
        self.assertIn("var bound_self = method.get_object()", GML_RUNTIME_SCRIPT)
        self.assertIn("if bound_self == null:\n\t\treturn gml_undefined()", GML_RUNTIME_SCRIPT)
        self.assertIn("return bound_self", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_method_get_index(method):", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_type_error("GML method_get_index", method)', GML_RUNTIME_SCRIPT)
        self.assertIn("return method.function_value", GML_RUNTIME_SCRIPT)
        self.assertIn("return method", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_method(value):\n\t\treturn GML_TYPE_METHOD", GML_RUNTIME_SCRIPT)

    def test_runtime_constructor_methods_allocate_new_structs(self):
        self.assertIn("static func gml_constructor(scope, func_or_method):", GML_RUNTIME_SCRIPT)
        self.assertIn("var constructor_method = gml_method(scope, func_or_method, true)", GML_RUNTIME_SCRIPT)
        self.assertIn("gml_static_get(constructor_method)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_new(constructor, args = []):", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_type_error("GML new constructor", constructor)', GML_RUNTIME_SCRIPT)
        self.assertIn("if not constructor.is_constructor:", GML_RUNTIME_SCRIPT)
        self.assertIn("var instance = gml_struct({})", GML_RUNTIME_SCRIPT)
        self.assertIn("var constructor_static = gml_static_get(constructor)", GML_RUNTIME_SCRIPT)
        self.assertIn("gml_static_set(instance, constructor_static)", GML_RUNTIME_SCRIPT)
        self.assertIn("var call_args = [instance]", GML_RUNTIME_SCRIPT)
        self.assertIn("call_args.append_array(args)", GML_RUNTIME_SCRIPT)
        self.assertIn("constructor.function_value.callv(call_args)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_constructor_inherit(instance, constructor, args = []):", GML_RUNTIME_SCRIPT)
        self.assertIn("var parent_static = gml_static_get(constructor)", GML_RUNTIME_SCRIPT)
        self.assertIn("gml_static_set(current_static, parent_static)", GML_RUNTIME_SCRIPT)
        self.assertIn("return instance", GML_RUNTIME_SCRIPT)

    def test_runtime_throw_preserves_arbitrary_payload_values(self):
        self.assertIn("class GMLException:", GML_RUNTIME_SCRIPT)
        self.assertIn("var value = null", GML_RUNTIME_SCRIPT)
        self.assertIn("func _init(exception_value = null):", GML_RUNTIME_SCRIPT)
        self.assertIn("value = exception_value", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_gml_exception(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return value is GMLException", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_throw(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLException.new(value)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_exception_value(exception):", GML_RUNTIME_SCRIPT)
        self.assertIn("if exception is GMLException:\n\t\treturn exception.value", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_undefined()", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_exception_struct(exception):", GML_RUNTIME_SCRIPT)
        self.assertIn('"message": gml_string(exception)', GML_RUNTIME_SCRIPT)
        self.assertIn("if is_struct(exception.value):\n\t\treturn exception.value", GML_RUNTIME_SCRIPT)
        self.assertIn("var message = gml_string(exception.value)", GML_RUNTIME_SCRIPT)
        self.assertIn('"longMessage": message', GML_RUNTIME_SCRIPT)
        self.assertIn('"script": ""', GML_RUNTIME_SCRIPT)
        self.assertIn('"stacktrace": []', GML_RUNTIME_SCRIPT)

    def test_runtime_undefined_equality_is_special_cased(self):
        self.assertIn("static func gml_eq(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_undefined(left) or is_undefined(right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return is_undefined(left) and is_undefined(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_ne(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return not gml_eq(left, right)", GML_RUNTIME_SCRIPT)

    def test_runtime_reference_equality_uses_identity(self):
        self.assertIn("static func _is_gml_reference_value(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("if _is_gml_reference_value(left) or _is_gml_reference_value(right):", GML_RUNTIME_SCRIPT)
        self.assertIn(
            "return _is_gml_reference_value(left) and _is_gml_reference_value(right) and is_same(left, right)",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn(
            "return value_type == TYPE_ARRAY or value_type == TYPE_DICTIONARY or value_type == TYPE_OBJECT",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("if is_undefined(value) or is_int64(value) or is_ptr(value) or is_handle(value):", GML_RUNTIME_SCRIPT)

    def test_runtime_pointer_equality_and_nullish_are_special_cased(self):
        self.assertIn("if is_ptr(left) or is_ptr(right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return is_ptr(left) and is_ptr(right) and left.value == right.value and left.invalid == right.invalid", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_is_nullish(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return is_undefined(value) or (is_ptr(value) and value.value == 0)", GML_RUNTIME_SCRIPT)

    def test_runtime_rejects_pointer_numeric_operations(self):
        self.assertIn(
            'return gml_unsupported_binary_type_error("GML pointer arithmetic", left, right)',
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn(
            'return gml_unsupported_type_error("GML numeric conversion", value)',
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn(
            'return gml_unsupported_type_error("GML bitwise conversion", value)',
            GML_RUNTIME_SCRIPT,
        )

    def test_runtime_converts_real_int64_and_ptr_strings_strictly(self):
        self.assertIn("static func _gml_string_to_real(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_string_to_int64(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("var text = str(value).strip_edges()", GML_RUNTIME_SCRIPT)
        self.assertIn("if text.to_lower().is_valid_hex_number(true):", GML_RUNTIME_SCRIPT)
        self.assertIn("return float(_gml_hex_string_to_int(text))", GML_RUNTIME_SCRIPT)
        self.assertIn("if text.is_valid_float():\n\t\treturn text.to_float()", GML_RUNTIME_SCRIPT)
        self.assertIn("if text.is_valid_float():\n\t\treturn int(text.to_float())", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML real conversion does not support string " + text)', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML int64 conversion does not support string " + text)', GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_hex_string_to_int(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_hex_digit_value(code):", GML_RUNTIME_SCRIPT)

    def test_runtime_undefined_truthiness_and_conversions(self):
        self.assertIn(
            "static func gml_typeof(value):\n\tif is_undefined(value):\n\t\treturn GML_TYPE_UNDEFINED",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn(
            "static func gml_string(value):\n\tif is_undefined(value):\n\t\treturn GML_TYPE_UNDEFINED",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn(
            "static func gml_bool(value):\n\tif is_undefined(value):\n\t\treturn false",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("if is_ptr(value):\n\t\treturn not value.invalid and value.value != 0", GML_RUNTIME_SCRIPT)

    def test_runtime_helpers_keep_variant_backed_parameters(self):
        self.assertIn("static func gml_typeof(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_bool(value):", GML_RUNTIME_SCRIPT)
        self.assertNotIn("static func gml_typeof(value:", GML_RUNTIME_SCRIPT)
        self.assertNotIn("static func gml_bool(value:", GML_RUNTIME_SCRIPT)

    def test_runtime_primitive_type_predicates_cover_gml_value_categories(self):
        self.assertIn("static func is_array(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return typeof(value) == TYPE_ARRAY", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_struct(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return typeof(value) == TYPE_DICTIONARY or typeof(value) == TYPE_OBJECT", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_method(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return value is GMLMethod or typeof(value) == TYPE_CALLABLE", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_callable(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return is_method(value)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_numeric(value):\n\treturn is_real(value) or is_int64(value) or is_bool(value)", GML_RUNTIME_SCRIPT)

    def test_runtime_typeof_agrees_with_specific_predicate_categories(self):
        for constant in (
            'const GML_TYPE_UNDEFINED = "undefined"',
            'const GML_TYPE_NULL = "null"',
            'const GML_TYPE_BOOL = "bool"',
            'const GML_TYPE_NUMBER = "number"',
            'const GML_TYPE_INT32 = "int32"',
            'const GML_TYPE_INT64 = "int64"',
            'const GML_TYPE_POINTER = "ptr"',
            'const GML_TYPE_STRING = "string"',
            'const GML_TYPE_ARRAY = "array"',
            'const GML_TYPE_STRUCT = "struct"',
            'const GML_TYPE_METHOD = "method"',
            'const GML_TYPE_HANDLE = "ref"',
            'const GML_TYPE_UNKNOWN = "unknown"',
        ):
            with self.subTest(constant=constant):
                self.assertIn(constant, GML_RUNTIME_SCRIPT)
        self.assertIn("if value == null:\n\t\treturn GML_TYPE_NULL", GML_RUNTIME_SCRIPT)
        self.assertIn(
            "if is_undefined(value):\n\t\treturn GML_TYPE_UNDEFINED\n\tif value == null:\n\t\treturn GML_TYPE_NULL\n\tif is_handle(value):",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("if is_handle(value):\n\t\treturn GML_TYPE_HANDLE", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_handle(value):\n\t\treturn GML_TYPE_HANDLE\n\tif is_int64(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("if value_type == TYPE_ARRAY:\n\t\treturn GML_TYPE_ARRAY\n\tif is_method(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_int64(value):\n\t\treturn GML_TYPE_INT64", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_int32(value):\n\t\treturn GML_TYPE_INT32", GML_RUNTIME_SCRIPT)
        self.assertIn("return GML_TYPE_NUMBER", GML_RUNTIME_SCRIPT)

    def test_runtime_preserves_real_operations_as_float_helpers(self):
        self.assertIn(
            "if right_value == 0.0:\n\t\tif left_value == 0.0:\n\t\t\treturn NAN",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("return INF if left_value > 0.0 else -INF", GML_RUNTIME_SCRIPT)
        self.assertIn("return left_value / right_value", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_sqrt(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("if real_value < 0.0:\n\t\treturn NAN", GML_RUNTIME_SCRIPT)
        self.assertIn("return sqrt(real_value)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _is_arithmetic_real_operand(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return _to_real(left) + _to_real(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("return fmod(_to_real(left), _to_real(right))", GML_RUNTIME_SCRIPT)
        self.assertIn("return float(value)", GML_RUNTIME_SCRIPT)

    def test_runtime_repeat_count_preserves_gml_rounding(self):
        self.assertIn("static func gml_repeat_count(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return max(0, int(round(_to_real(value))))", GML_RUNTIME_SCRIPT)

    def test_runtime_array_helpers_reject_negative_indices(self):
        self.assertIn("static func gml_array_get(array_value, index):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_array_set(array_value, index, value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _to_array_index(value):", GML_RUNTIME_SCRIPT)
        self.assertIn('gml_error("Negative GML array index")', GML_RUNTIME_SCRIPT)

    def test_runtime_array_reads_check_bounds_before_access(self):
        self.assertIn("if typeof(array_value) != TYPE_ARRAY:", GML_RUNTIME_SCRIPT)
        self.assertIn(
            'return gml_unsupported_type_error("GML array access", array_value)',
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("if resolved_index >= array_value.size():", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML array index out of bounds")', GML_RUNTIME_SCRIPT)

    def test_runtime_array_set_mutates_reference_without_copying(self):
        self.assertIn("array_value[resolved_index] = value", GML_RUNTIME_SCRIPT)
        self.assertIn("return value", GML_RUNTIME_SCRIPT)
        self.assertNotIn("array_value.duplicate", GML_RUNTIME_SCRIPT)

    def test_runtime_array_push_mutates_reference_without_copying(self):
        self.assertIn("static func gml_array_push(array_value, ...values):", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_type_error("GML array_push", array_value)', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML array_push requires at least one value")', GML_RUNTIME_SCRIPT)
        self.assertIn("for value in values:", GML_RUNTIME_SCRIPT)
        self.assertIn("array_value.append(value)", GML_RUNTIME_SCRIPT)
        self.assertIn("return null", GML_RUNTIME_SCRIPT)
        self.assertNotIn("array_value.duplicate", GML_RUNTIME_SCRIPT)

    def test_runtime_array_equals_uses_gml_element_equality(self):
        self.assertIn("static func gml_array_equals(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("if left.size() != right.size():", GML_RUNTIME_SCRIPT)
        self.assertIn("for index in range(left.size()):", GML_RUNTIME_SCRIPT)
        self.assertIn("if not _gml_values_equal_for_array(left[index], right[index]):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_values_equal_for_array(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_eq(left, right)", GML_RUNTIME_SCRIPT)

    def test_runtime_preserves_nan_numeric_type_and_inequality(self):
        self.assertIn("static func is_nan_value(value):\n\treturn is_number(value) and is_nan(float(value))", GML_RUNTIME_SCRIPT)
        self.assertIn("if value_type == TYPE_INT or value_type == TYPE_FLOAT:\n\t\treturn GML_TYPE_NUMBER", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_nan_value(left) or is_nan_value(right):\n\t\treturn false", GML_RUNTIME_SCRIPT)
        self.assertIn("if not _gml_values_equal_for_array(left[index], right[index]):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_eq(left, right)", GML_RUNTIME_SCRIPT)

    def test_runtime_array_deletion_uses_undefined_without_registries(self):
        self.assertIn("static func gml_undefined():\n\treturn _gml_undefined", GML_RUNTIME_SCRIPT)
        self.assertNotIn("array_registry", GML_RUNTIME_SCRIPT)

    def test_runtime_array_copy_on_write_flag_emits_diagnostic(self):
        self.assertIn("const GML_ARRAY_COPY_ON_WRITE_ENABLED = false", GML_RUNTIME_SCRIPT)
        self.assertIn(
            'const GML_ARRAY_COPY_ON_WRITE_DIAGNOSTIC = "Legacy GML array copy-on-write mode is not supported by GM2Godot"',
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("if GML_ARRAY_COPY_ON_WRITE_ENABLED:", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_error(GML_ARRAY_COPY_ON_WRITE_DIAGNOSTIC)", GML_RUNTIME_SCRIPT)

    def test_runtime_struct_helper_keeps_dictionary_reference(self):
        self.assertIn("static func gml_struct(fields = {}):", GML_RUNTIME_SCRIPT)
        self.assertIn("if typeof(fields) != TYPE_DICTIONARY:", GML_RUNTIME_SCRIPT)
        self.assertIn(
            'return gml_unsupported_type_error("GML struct literal", fields)',
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("if typeof(fields[key]) == TYPE_CALLABLE:", GML_RUNTIME_SCRIPT)
        self.assertIn("fields[key] = gml_method(fields, fields[key])", GML_RUNTIME_SCRIPT)
        self.assertIn("return fields", GML_RUNTIME_SCRIPT)
        self.assertNotIn("fields.duplicate", GML_RUNTIME_SCRIPT)

    def test_runtime_enum_helper_wraps_members_as_int64_values(self):
        self.assertIn("static func gml_enum(fields = {}):", GML_RUNTIME_SCRIPT)
        self.assertIn(
            'return gml_unsupported_type_error("GML enum declaration", fields)',
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("var enum_fields = {}", GML_RUNTIME_SCRIPT)
        self.assertIn("for key in fields.keys():", GML_RUNTIME_SCRIPT)
        self.assertIn("enum_fields[key] = gml_int64(fields[key])", GML_RUNTIME_SCRIPT)
        self.assertIn("return enum_fields", GML_RUNTIME_SCRIPT)

    def test_runtime_struct_access_helpers_preserve_gml_missing_member_behavior(self):
        self.assertIn("static func gml_struct_get(struct_value, member_name):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_struct_exists(struct_value, member_name):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_struct_set(struct_value, member_name, value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_struct_remove(struct_value, member_name):", GML_RUNTIME_SCRIPT)
        self.assertIn("if typeof(struct_value) == TYPE_DICTIONARY:", GML_RUNTIME_SCRIPT)
        self.assertIn("if struct_value.has(key):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_undefined()", GML_RUNTIME_SCRIPT)
        self.assertIn("struct_value[key] = value", GML_RUNTIME_SCRIPT)
        self.assertIn("struct_value.erase(key)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _object_has_property(object_value, property_name):", GML_RUNTIME_SCRIPT)
        self.assertIn(
            'return gml_unsupported_type_error("GML struct access", struct_value)',
            GML_RUNTIME_SCRIPT,
        )

    def test_runtime_missing_value_helpers_return_undefined(self):
        self.assertIn("static func gml_variable_struct_get(struct_value, member_name):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_struct_get(struct_value, member_name)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_variable_instance_get(instance_value, member_name):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_selector_get(instance_value, member_name)", GML_RUNTIME_SCRIPT)
        self.assertIn("if targets.is_empty():\n\t\treturn gml_undefined()", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_ds_map_find_value(map_value, key):", GML_RUNTIME_SCRIPT)
        self.assertIn("var resolved_map = _gml_resolve_ds_map(map_value)", GML_RUNTIME_SCRIPT)
        self.assertIn("if resolved_map.has(key):\n\t\t\treturn resolved_map[key]", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_ds_map_set(map_value, key, value):", GML_RUNTIME_SCRIPT)
        self.assertIn("resolved_map[key] = value", GML_RUNTIME_SCRIPT)
        self.assertNotIn("resolved_map.get(", GML_RUNTIME_SCRIPT)

    def test_runtime_preserves_undefined_value_model(self):
        self.assertIn("class GMLUndefined:", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_undefined = GMLUndefined.new()", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_undefined():\n\treturn _gml_undefined", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_undefined(value):\n\treturn value is GMLUndefined", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_undefined(left) or is_undefined(right):\n\t\treturn is_undefined(left) and is_undefined(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_typeof(value):\n\tif is_undefined(value):\n\t\treturn GML_TYPE_UNDEFINED", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_string(value):\n\tif is_undefined(value):\n\t\treturn GML_TYPE_UNDEFINED", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_bool(value):\n\tif is_undefined(value):\n\t\treturn false", GML_RUNTIME_SCRIPT)
        self.assertIn("if targets.is_empty():\n\t\treturn gml_undefined()", GML_RUNTIME_SCRIPT)
        self.assertIn("if resolved_map.has(key):\n\t\t\treturn resolved_map[key]", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_undefined()", GML_RUNTIME_SCRIPT)

    def test_runtime_instance_variable_helpers_resolve_instances_and_invalid_ids(self):
        self.assertIn("static func gml_variable_instance_exists(instance_value, member_name):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_selector_exists(instance_value, member_name)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_variable_instance_set(instance_value, member_name, value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_selector_set(instance_value, member_name, value)", GML_RUNTIME_SCRIPT)
        self.assertIn("for instance in gml_with_targets(target, current_self, current_other):", GML_RUNTIME_SCRIPT)
        self.assertIn("for instance in targets:\n\t\tgml_struct_set(instance, member_name, value)", GML_RUNTIME_SCRIPT)

    def test_runtime_global_scope_is_a_shared_struct_for_instance_apis(self):
        self.assertIn("static var _gml_global_scope = {", GML_RUNTIME_SCRIPT)
        self.assertIn('"score": 0', GML_RUNTIME_SCRIPT)
        self.assertIn('"health": 100,', GML_RUNTIME_SCRIPT)
        self.assertIn('"lives": 0,', GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_global_scope():\n\treturn _gml_global_scope", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_variable_instance_get_names(instance_value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_variable_instance_names_count(instance_value):", GML_RUNTIME_SCRIPT)

    def test_runtime_builtin_array_variables_are_shared_fixed_slot_arrays(self):
        self.assertIn("const GML_BUILTIN_ARRAY_SIZE = 8", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_builtin_arrays = {}", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_builtin_array(name):", GML_RUNTIME_SCRIPT)
        self.assertIn("var key = str(name)", GML_RUNTIME_SCRIPT)
        self.assertIn("if not _gml_builtin_arrays.has(key):", GML_RUNTIME_SCRIPT)
        self.assertIn("for _index in range(GML_BUILTIN_ARRAY_SIZE):", GML_RUNTIME_SCRIPT)
        self.assertIn("values.append(gml_undefined())", GML_RUNTIME_SCRIPT)
        self.assertIn("_gml_builtin_arrays[key] = values", GML_RUNTIME_SCRIPT)
        self.assertIn("return _gml_builtin_arrays[key]", GML_RUNTIME_SCRIPT)

    def test_runtime_builtin_globals_have_shared_defaults(self):
        self.assertIn("static var _gml_builtin_globals = {", GML_RUNTIME_SCRIPT)
        self.assertIn('"room": _gml_undefined,', GML_RUNTIME_SCRIPT)
        self.assertIn('"room_width": 0', GML_RUNTIME_SCRIPT)
        self.assertIn('"room_height": 0,', GML_RUNTIME_SCRIPT)
        self.assertIn('"instance_count": 0,', GML_RUNTIME_SCRIPT)
        self.assertIn('"async_load": {},', GML_RUNTIME_SCRIPT)
        self.assertIn('"event_data": {},', GML_RUNTIME_SCRIPT)
        self.assertIn('"argument": [],', GML_RUNTIME_SCRIPT)
        self.assertIn('"argument_count": 0,', GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_builtin_global(name):", GML_RUNTIME_SCRIPT)
        self.assertIn("if _gml_builtin_globals.has(key):", GML_RUNTIME_SCRIPT)
        self.assertIn("return _gml_builtin_globals[key]", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_undefined()", GML_RUNTIME_SCRIPT)

    def test_runtime_asset_registry_helpers_lazy_load_generated_registry(self):
        self.assertIn('const GML_ASSET_REGISTRY_PATH = "res://gm2godot/gml_asset_registry.gd"', GML_RUNTIME_SCRIPT)
        self.assertIn("const GML_DYNAMIC_ASSET_ID_START = 1073741824", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_asset_registry_loaded = false", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_asset_by_name = {}", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_asset_by_legacy_id = {}", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_asset_registry_ensure_loaded():", GML_RUNTIME_SCRIPT)
        self.assertIn("ResourceLoader.exists(GML_ASSET_REGISTRY_PATH)", GML_RUNTIME_SCRIPT)
        self.assertIn("gml_asset_registry_set(registry_script.gml_asset_registry_entries())", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_asset_get_index(asset_name):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_asset_get_ids(asset_type = null):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_asset_register_dynamic(asset_name, asset_type, godot_resource = null, tags = []):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_asset_release(asset):", GML_RUNTIME_SCRIPT)
        self.assertIn("_gml_asset_dynamic_ids[asset_id] = true", GML_RUNTIME_SCRIPT)
        self.assertIn("return false", GML_RUNTIME_SCRIPT)

    def test_runtime_instance_name_helpers_enumerate_visible_names_and_invalid_instances(self):
        self.assertIn("static func gml_variable_instance_get_names(instance_value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_selector_get_names(instance_value)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_variable_instance_names_count(instance_value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_selector_names_count(instance_value)", GML_RUNTIME_SCRIPT)
        self.assertIn("if targets.is_empty():\n\t\treturn []", GML_RUNTIME_SCRIPT)
        self.assertIn("if targets.is_empty():\n\t\treturn -1", GML_RUNTIME_SCRIPT)

    def test_runtime_global_variable_helpers_use_shared_global_scope(self):
        self.assertIn("static func gml_variable_global_exists(member_name):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_struct_exists(gml_global_scope(), member_name)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_variable_global_get(member_name):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_struct_get(gml_global_scope(), member_name)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_variable_global_set(member_name, value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_struct_set(gml_global_scope(), member_name, value)", GML_RUNTIME_SCRIPT)

    def test_runtime_struct_name_helpers_return_visible_member_names(self):
        self.assertIn("static func gml_struct_get_names(struct_value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_struct_names_count(struct_value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return struct_value.keys()", GML_RUNTIME_SCRIPT)
        self.assertIn("return struct_value.size()", GML_RUNTIME_SCRIPT)
        self.assertIn("return -1", GML_RUNTIME_SCRIPT)

    def test_runtime_struct_foreach_invokes_callback_for_visible_members(self):
        self.assertIn("static func gml_struct_foreach(struct_value, callback):", GML_RUNTIME_SCRIPT)
        self.assertIn("if not is_struct(struct_value):", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_type_error("GML struct_foreach", struct_value)', GML_RUNTIME_SCRIPT)
        self.assertIn("if not is_method(callback):", GML_RUNTIME_SCRIPT)
        self.assertIn(
            'return gml_unsupported_type_error("GML struct_foreach callback", callback)',
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("for member_name in gml_struct_get_names(struct_value):", GML_RUNTIME_SCRIPT)
        self.assertIn("var member_value = gml_struct_get(struct_value, member_name)", GML_RUNTIME_SCRIPT)
        self.assertIn("gml_method_call(callback, [member_name, member_value])", GML_RUNTIME_SCRIPT)
        self.assertIn("return null", GML_RUNTIME_SCRIPT)

    def test_runtime_static_helpers_track_static_chain_relationships(self):
        self.assertIn("static var _gml_static_root = {}", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_static_registry = []", GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_static_named_scopes = {}", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_static_get(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("if value is GMLMethod:\n\t\treturn gml_static_get(value.function_value)", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_method(value):\n\t\treturn _gml_static_ensure(value)", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_type_error("GML static_get", value)', GML_RUNTIME_SCRIPT)
        self.assertIn("if is_same(value, _gml_static_root):\n\t\treturn gml_undefined()", GML_RUNTIME_SCRIPT)
        self.assertIn("var static_struct = _gml_static_lookup(value)", GML_RUNTIME_SCRIPT)
        self.assertIn("return _gml_static_root", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_static_set(struct_value, static_struct):", GML_RUNTIME_SCRIPT)
        self.assertIn("if struct_value is GMLMethod:\n\t\treturn null", GML_RUNTIME_SCRIPT)
        self.assertIn(
            "if is_method(struct_value):\n\t\treturn gml_unsupported_type_error(\"GML static_set\", struct_value)",
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn('return gml_unsupported_type_error("GML static_set static struct", static_struct)', GML_RUNTIME_SCRIPT)
        self.assertIn("_gml_static_set_parent(struct_value, static_struct)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_static_scope(scope_id):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_static_bind(value, scope_id, constructor_name = \"\"):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_static_initialize(static_struct, initializers):", GML_RUNTIME_SCRIPT)
        self.assertIn('static_struct["__gml_static_initialized"] = true', GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_static_ensure(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("_gml_static_set_parent(static_struct, _gml_static_root, constructor_name)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_static_lookup(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_static_same(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return left == right", GML_RUNTIME_SCRIPT)

    def test_runtime_constructor_identity_uses_static_chain(self):
        self.assertIn("static func gml_is_instanceof(struct_value, constructor):", GML_RUNTIME_SCRIPT)
        self.assertIn("if not is_struct(struct_value):\n\t\treturn false", GML_RUNTIME_SCRIPT)
        self.assertIn("if not is_method(constructor):\n\t\treturn false", GML_RUNTIME_SCRIPT)
        self.assertIn("var constructor_static = gml_static_get(constructor)", GML_RUNTIME_SCRIPT)
        self.assertIn("var current_static = gml_static_get(struct_value)", GML_RUNTIME_SCRIPT)
        self.assertIn("while not is_undefined(current_static):", GML_RUNTIME_SCRIPT)
        self.assertIn("if _gml_static_same(current_static, constructor_static):\n\t\t\treturn true", GML_RUNTIME_SCRIPT)
        self.assertIn("current_static = gml_static_get(current_static)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_instanceof(struct_value):", GML_RUNTIME_SCRIPT)
        self.assertIn('if typeof(struct_value) == TYPE_OBJECT:\n\t\treturn "instance"', GML_RUNTIME_SCRIPT)
        self.assertIn('return "struct"', GML_RUNTIME_SCRIPT)
        self.assertIn("var constructor_name = _gml_static_name(static_struct)", GML_RUNTIME_SCRIPT)
        self.assertIn("if constructor_name != \"\":\n\t\treturn constructor_name", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_static_name(value):", GML_RUNTIME_SCRIPT)
        self.assertIn('entry.has("constructor_name")', GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_static_constructor_name(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return _gml_static_constructor_name(value.function_value)", GML_RUNTIME_SCRIPT)
        self.assertIn("var method_name = str(value.get_method())", GML_RUNTIME_SCRIPT)

    def test_runtime_hashes_struct_member_names_with_documented_vectors(self):
        self.assertEqual(fnv1a32(""), 2166136261)
        self.assertEqual(fnv1a32("a"), 3826002220)
        self.assertEqual(fnv1a32("x"), 4245442695)
        self.assertEqual(fnv1a32("position"), 2471448074)
        self.assertEqual(fnv1a32("image_index"), 1603152005)
        self.assertIn('const GML_VARIABLE_HASH_ALGORITHM = "fnv1a32"', GML_RUNTIME_SCRIPT)
        self.assertIn("static var _gml_variable_hash_names = {}", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_variable_get_hash(name):", GML_RUNTIME_SCRIPT)
        self.assertIn("var key = str(name)", GML_RUNTIME_SCRIPT)
        self.assertIn("var hash = _gml_hash_string(key)", GML_RUNTIME_SCRIPT)
        self.assertIn("_gml_variable_hash_names[hash] = key", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_hash_string(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("var hash = 2166136261", GML_RUNTIME_SCRIPT)
        self.assertIn("var code = text.unicode_at(index)", GML_RUNTIME_SCRIPT)
        self.assertIn("hash = int((hash ^ code) * 16777619) & 0xffffffff", GML_RUNTIME_SCRIPT)

    def test_runtime_hashed_struct_helpers_resolve_registered_or_existing_names(self):
        self.assertIn("static func gml_struct_get_from_hash(struct_value, member_hash):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_struct_set_from_hash(struct_value, member_hash, value):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_struct_exists_from_hash(struct_value, member_hash):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_struct_remove_from_hash(struct_value, member_hash):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_struct_name_from_hash(struct_value, member_hash):", GML_RUNTIME_SCRIPT)
        self.assertIn("var hash = _to_int64_value(member_hash)", GML_RUNTIME_SCRIPT)
        self.assertIn("for member_name in gml_struct_get_names(struct_value):", GML_RUNTIME_SCRIPT)
        self.assertIn("if _gml_hash_string(member_name) == hash:\n\t\t\t\treturn str(member_name)", GML_RUNTIME_SCRIPT)
        self.assertIn("if _gml_variable_hash_names.has(hash):\n\t\treturn _gml_variable_hash_names[hash]", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_struct_get(struct_value, member_name)", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_struct_set(struct_value, member_name, value)", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_struct_exists(struct_value, member_name)", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_struct_remove(struct_value, member_name)", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("Unknown GML variable hash " + str(member_hash))', GML_RUNTIME_SCRIPT)

    def test_runtime_struct_string_output_uses_to_string_convention(self):
        self.assertIn("static func gml_string(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("if typeof(value) == TYPE_DICTIONARY:", GML_RUNTIME_SCRIPT)
        self.assertIn('if value.has("toString") and is_method(value["toString"]):', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_string(gml_method_call(value["toString"]))', GML_RUNTIME_SCRIPT)
        self.assertIn("return str(value)", GML_RUNTIME_SCRIPT)

    def test_runtime_variable_clone_preserves_documented_depth_behavior(self):
        self.assertIn("static func gml_variable_clone(value, depth = 128):", GML_RUNTIME_SCRIPT)
        self.assertIn("return _gml_clone_value(value, max(0, int(_to_real(depth))))", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _gml_clone_value(value, depth):", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_handle(value):\n\t\treturn value", GML_RUNTIME_SCRIPT)
        self.assertIn("if value_type == TYPE_ARRAY:", GML_RUNTIME_SCRIPT)
        self.assertIn("if value_type == TYPE_DICTIONARY:", GML_RUNTIME_SCRIPT)
        self.assertIn("clone.append(_gml_clone_value(element, depth - 1) if depth > 0 else element)", GML_RUNTIME_SCRIPT)
        self.assertIn("clone[key] = _gml_clone_value(value[key], depth - 1) if depth > 0 else value[key]", GML_RUNTIME_SCRIPT)
        self.assertNotIn(".duplicate(", GML_RUNTIME_SCRIPT)
        self.assertIn("return value", GML_RUNTIME_SCRIPT)

    def test_runtime_represents_explicit_int64_values(self):
        self.assertIn("const GML_TYPE_INT64", GML_RUNTIME_SCRIPT)
        self.assertIn("class GMLInt64", GML_RUNTIME_SCRIPT)
        self.assertIn("var _value = 0", GML_RUNTIME_SCRIPT)
        self.assertIn("get:\n\t\t\treturn _value", GML_RUNTIME_SCRIPT)
        self.assertIn('push_error("GML int64 values are immutable")', GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_int64(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return value is GMLInt64", GML_RUNTIME_SCRIPT)
        self.assertIn("return GML_TYPE_INT64", GML_RUNTIME_SCRIPT)

    def test_runtime_converts_supported_int64_inputs(self):
        self.assertIn("static func gml_int64(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_int64(value):\n\t\treturn GMLInt64.new(value.value)", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_ptr(value):\n\t\treturn GMLInt64.new(value.value)", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_string(value):\n\t\tvar int64_value = _gml_string_to_int64(value)", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_undefined(int64_value):\n\t\t\treturn int64_value", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(int64_value)", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_number(value):\n\t\treturn GMLInt64.new(value)", GML_RUNTIME_SCRIPT)
        self.assertIn(
            'return gml_unsupported_type_error("GML int64 conversion", value)',
            GML_RUNTIME_SCRIPT,
        )

    def test_runtime_preserves_int64_arithmetic_results(self):
        self.assertIn("static func _returns_int64_arithmetic_result(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(_to_int64_value(left) + _to_int64_value(right))", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(_to_int64_value(left) - _to_int64_value(right))", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(_to_int64_value(left) * _to_int64_value(right))", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(_to_int64_value(left) % right_int)", GML_RUNTIME_SCRIPT)
        self.assertIn("(is_int64(left) and (is_int64(right) or is_int32(right)))", GML_RUNTIME_SCRIPT)
        self.assertIn("or (is_int64(right) and is_int32(left))", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML int64 modulo by zero")', GML_RUNTIME_SCRIPT)

    def test_runtime_preserves_int32_arithmetic_results(self):
        self.assertIn("static func _returns_int32_arithmetic_result(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return is_int32(left) and is_int32(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _to_int32_value(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return _to_int32_value(left) + _to_int32_value(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("return _to_int32_value(left) - _to_int32_value(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("return _to_int32_value(left) * _to_int32_value(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("return int(_to_int32_value(left) / right_int)", GML_RUNTIME_SCRIPT)
        self.assertIn("return _to_int32_value(left) % right_int", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML int32 division by zero")', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML int32 modulo by zero")', GML_RUNTIME_SCRIPT)

    def test_runtime_preserves_int64_division_behavior(self):
        self.assertIn("static func gml_div(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_int_div(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(int(_to_int64_value(left) / right_int))", GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_error("GML int64 division by zero")', GML_RUNTIME_SCRIPT)

    def test_runtime_checks_int32_range_over_godot_ints(self):
        self.assertIn("static func is_int32(value):", GML_RUNTIME_SCRIPT)
        self.assertIn(
            "return typeof(value) == TYPE_INT and int(value) >= -2147483648 and int(value) <= 2147483647",
            GML_RUNTIME_SCRIPT,
        )

    def test_runtime_special_numeric_predicates_only_accept_real_numbers(self):
        self.assertIn("static func is_nan_value(value):\n\treturn is_number(value) and is_nan(float(value))", GML_RUNTIME_SCRIPT)
        self.assertIn("static func is_infinity(value):\n\treturn is_number(value) and is_inf(float(value))", GML_RUNTIME_SCRIPT)

    def test_runtime_bitwise_helpers_return_int64_values(self):
        self.assertIn("static func gml_bit_or(left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(_to_int64_value(left) | _to_int64_value(right))", GML_RUNTIME_SCRIPT)
        self.assertIn("return GMLInt64.new(~_to_int64_value(value))", GML_RUNTIME_SCRIPT)
        self.assertIn("static func _to_int64_value(value):", GML_RUNTIME_SCRIPT)

    def test_runtime_handles_string_conversion_and_concat_deliberately(self):
        self.assertIn("static func is_string(value):", GML_RUNTIME_SCRIPT)
        self.assertIn("return value_type == TYPE_STRING or value_type == TYPE_STRING_NAME", GML_RUNTIME_SCRIPT)
        self.assertIn("if is_string(right):\n\t\tif is_string(left):", GML_RUNTIME_SCRIPT)
        self.assertIn("return str(left) + str(right)", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_string(left) + str(right)", GML_RUNTIME_SCRIPT)
        self.assertIn(
            'if is_string(left):\n\t\treturn gml_unsupported_binary_type_error("GML add", left, right)',
            GML_RUNTIME_SCRIPT,
        )
        self.assertIn("if is_string(right):\n\t\tif is_number(left):", GML_RUNTIME_SCRIPT)
        self.assertIn("return str(right).repeat(max(0, int(_to_real(left))))", GML_RUNTIME_SCRIPT)
        self.assertIn('return "true" if value else "false"', GML_RUNTIME_SCRIPT)

    def test_runtime_type_table_errors_are_centralized(self):
        self.assertIn('return gml_unsupported_binary_type_error("GML add", left, right)', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_binary_type_error("GML subtract", left, right)', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_binary_type_error("GML multiply", left, right)', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_binary_type_error("GML divide", left, right)', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_binary_type_error("GML integer divide", left, right)', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_binary_type_error("GML modulo", left, right)', GML_RUNTIME_SCRIPT)
        self.assertIn('return gml_unsupported_binary_type_error("GML pointer arithmetic", left, right)', GML_RUNTIME_SCRIPT)
        self.assertIn("static func gml_unsupported_binary_type_error(api_name, left, right):", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_error(", GML_RUNTIME_SCRIPT)

    def test_runtime_centralizes_error_reporting(self):
        self.assertIn("static func gml_error(message):", GML_RUNTIME_SCRIPT)
        self.assertIn("push_error", GML_RUNTIME_SCRIPT)
        self.assertIn("return gml_undefined()", GML_RUNTIME_SCRIPT)

    def test_write_gml_runtime_writes_support_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_path = write_gml_runtime(tmpdir)

            self.assertEqual(runtime_path, os.path.join(tmpdir, GML_RUNTIME_RELATIVE_PATH))
            with open(runtime_path, encoding="utf-8") as runtime_file:
                self.assertEqual(runtime_file.read(), GML_RUNTIME_SCRIPT)


class TestGMLRuntimeParityFixtures(unittest.TestCase):
    def test_runtime_value_expression_fixtures(self):
        for parity_case in RUNTIME_VALUE_PARITY_CASES:
            with self.subTest(gml_expression=parity_case.gml_expression):
                self.assertEqual(
                    transpile_gml_expression(parity_case.gml_expression, asset_names={"o_enemy"}),
                    parity_case.gdscript_expression,
                )


class TestGMLRuntimeTypeTableFixtures(unittest.TestCase):
    def test_documented_arithmetic_type_tables_cover_every_cell(self):
        expected_columns = set(TYPE_TABLE_COLUMNS)

        for operator, _helper_name, table in TYPE_TABLE_OPERATORS:
            with self.subTest(operator=operator):
                self.assertEqual(set(table), expected_columns)
                for row_name, row in table.items():
                    self.assertEqual(set(row), expected_columns, row_name)

    def test_arithmetic_type_table_cells_lower_to_runtime_helpers(self):
        source_values = dict(TYPE_TABLE_VALUES)
        gd_values = {
            label: transpile_gml_expression(source)
            for label, source in TYPE_TABLE_VALUES
        }

        for operator, helper_name, table in TYPE_TABLE_OPERATORS:
            for left_type, row in table.items():
                for right_type, expected_result in row.items():
                    with self.subTest(
                        operator=operator,
                        left_type=left_type,
                        right_type=right_type,
                        expected_result=expected_result,
                    ):
                        source = f"{source_values[left_type]} {operator} {source_values[right_type]}"
                        expected = f"GMRuntime.{helper_name}({gd_values[left_type]}, {gd_values[right_type]})"
                        self.assertEqual(transpile_gml_expression(source), expected)


if __name__ == "__main__":
    unittest.main()
