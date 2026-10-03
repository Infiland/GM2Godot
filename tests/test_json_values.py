import ast
import pathlib
import sys
import unittest

from src.conversion.json_values import JsonValueError, validate_json_value


class _Opaque:
    def __str__(self) -> str:
        raise AssertionError("Invalid values must not be stringified")

    def __repr__(self) -> str:
        raise AssertionError("Invalid values must not be represented")


class _StringSubclass(str):
    pass


class _IntegerSubclass(int):
    pass


class _FloatSubclass(float):
    pass


class _ArraySubclass(list[object]):
    pass


class _ObjectSubclass(dict[str, object]):
    pass


class TestJsonValueValidation(unittest.TestCase):
    def test_nested_native_values_keep_identity_and_order(self) -> None:
        child: dict[str, object] = {"second": 2, "first": "one"}
        array: list[object] = [child, False, 0, 1.5, None]
        root: dict[str, object] = {"z": array, "a": child}

        result = validate_json_value(root, source_path="project/Example.yyp")

        self.assertIs(result, root)
        assert isinstance(result, dict)
        self.assertEqual(list(result), ["z", "a"])
        self.assertIs(result["z"], array)
        self.assertIs(result["a"], child)
        assert isinstance(result["z"], list)
        self.assertIs(result["z"][0], child)
        self.assertEqual(list(child), ["second", "first"])

    def test_all_scalar_kinds_and_nonfinite_floats_keep_identity(self) -> None:
        values: tuple[object, ...] = (
            "text", "", 0, 12345678901234567890, 1.25, True, False, None,
            float("nan"), float("inf"), float("-inf"),
        )
        for value in values:
            with self.subTest(kind=type(value).__name__):
                self.assertIs(validate_json_value(value, source_path="scalar.yy"), value)

    def test_empty_containers_keep_identity(self) -> None:
        array: list[object] = []
        data: dict[object, object] = {}
        self.assertIs(validate_json_value(array, source_path="array.yy"), array)
        self.assertIs(validate_json_value(data, source_path="object.yy"), data)

    def test_shared_acyclic_containers_are_legal(self) -> None:
        shared: list[object] = [{"leaf": True}]
        left: dict[str, object] = {"shared": shared}
        right: dict[str, object] = {"shared": shared}
        root: list[object] = [left, shared, right, left]

        result = validate_json_value(root, source_path="shared.yy")

        self.assertIs(result, root)
        self.assertIs(left["shared"], right["shared"])

    def test_native_depth_over_1500_needs_no_recursion_change(self) -> None:
        recursion_limit = sys.getrecursionlimit()
        root: list[object] = []
        cursor = root
        for _ in range(1600):
            child: list[object] = []
            cursor.append(child)
            cursor = child
        cursor.append("leaf")

        result = validate_json_value(root, source_path="deep.yy")

        self.assertIs(result, root)
        self.assertEqual(sys.getrecursionlimit(), recursion_limit)
        for _ in range(1601):
            assert isinstance(result, list)
            self.assertEqual(len(result), 1)
            result = result[0]
        self.assertEqual(result, "leaf")

    def test_invalid_deep_leaf_reports_complete_prefixed_path(self) -> None:
        root: list[object] = []
        cursor = root
        for _ in range(1600):
            child: list[object] = []
            cursor.append(child)
            cursor = child
        cursor.append(b"invalid")

        with self.assertRaises(JsonValueError) as raised:
            validate_json_value(root, source_path="deep.yy", field_path=("extras", 4))

        error = raised.exception
        self.assertEqual(error.source_path, "deep.yy")
        self.assertEqual(error.field_path, ("extras", 4) + (0,) * 1601)
        self.assertEqual(error.actual, "bytes")
        self.assertEqual(error.reason, "unsupported-type")

    def test_self_referential_array_is_a_cycle(self) -> None:
        root: list[object] = []
        root.append(root)

        with self.assertRaises(JsonValueError) as raised:
            validate_json_value(root, source_path="cycle.yy")

        self.assertEqual(raised.exception.field_path, (0,))
        self.assertEqual(raised.exception.actual, "array")
        self.assertEqual(raised.exception.reason, "cycle")

    def test_mixed_ancestor_cycle_is_not_accepted_as_shared(self) -> None:
        root: dict[str, object] = {}
        child: list[object] = [root]
        root["child"] = child

        with self.assertRaises(JsonValueError) as raised:
            validate_json_value(root, source_path="mixed.yy", field_path=("config",))

        self.assertEqual(raised.exception.field_path, ("config", "child", 0))
        self.assertEqual(raised.exception.actual, "object")
        self.assertEqual(raised.exception.reason, "cycle")

    def test_invalid_shared_subtree_still_requires_validation(self) -> None:
        child: list[object] = [b"invalid"]
        root: dict[str, object] = {"first": child, "second": child}

        with self.assertRaises(JsonValueError) as raised:
            validate_json_value(root, source_path="shared-invalid.yy")

        self.assertEqual(raised.exception.field_path, ("first", 0))
        self.assertEqual(raised.exception.reason, "unsupported-type")

    def test_nonstring_keys_report_the_containing_object_without_formatting(self) -> None:
        keys: tuple[object, ...] = (0, True, None, ("tuple",), _Opaque(), _StringSubclass("key"))
        for key in keys:
            data: dict[object, object] = {key: "value"}
            root: dict[str, object] = {"nested": data}
            with self.subTest(kind=type(key).__name__):
                with self.assertRaises(JsonValueError) as raised:
                    validate_json_value(root, source_path="keys.yy", field_path=(2,))
                error = raised.exception
                self.assertEqual(error.field_path, (2, "nested"))
                self.assertEqual(error.expected, "string key")
                self.assertEqual(error.actual, type(key).__name__)
                self.assertEqual(error.reason, "non-string-key")

    def test_unsupported_values_and_builtin_subclasses_are_rejected(self) -> None:
        values: tuple[object, ...] = (
            b"bytes", {1, 2}, ("tuple",), _Opaque(),
            _StringSubclass("value"), _IntegerSubclass(1), _FloatSubclass(1.5),
            _ArraySubclass(), _ObjectSubclass(),
        )
        for value in values:
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(JsonValueError) as raised:
                    validate_json_value(value, source_path="unsupported.yy")
                self.assertEqual(raised.exception.field_path, ())
                self.assertEqual(raised.exception.actual, type(value).__name__)
                self.assertEqual(raised.exception.reason, "unsupported-type")

    def test_boundary_leaf_has_no_project_service_imports(self) -> None:
        source_path = pathlib.Path(__file__).resolve().parents[1] / "src/conversion/json_values.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "Boundary leaf must not import relative project owners")
                assert node.module is not None
                imported_modules.add(node.module)
        for module in imported_modules:
            with self.subTest(module=module):
                self.assertIn(module.split(".")[0], sys.stdlib_module_names)


if __name__ == "__main__":
    unittest.main()
