# pyright: reportAbstractUsage=false, reportPrivateUsage=false

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import unittest

# Ensure project root is on sys.path so "src.*" imports work
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.base_converter import BaseConverter


class TestBaseConverterAbstract(unittest.TestCase):
    """Verify that BaseConverter enforces the abstract interface."""

    def test_cannot_instantiate_directly(self):
        """BaseConverter is abstract and should raise TypeError on direct instantiation."""
        with self.assertRaises(TypeError):
            BaseConverter("/fake/gm", "/fake/godot")

    def test_subclass_must_implement_convert_all(self):
        """A subclass that does NOT implement convert_all should still raise TypeError."""

        class IncompleteConverter(BaseConverter):
            pass  # deliberately missing convert_all

        with self.assertRaises(TypeError):
            IncompleteConverter("/fake/gm", "/fake/godot")

    def test_concrete_subclass_can_be_instantiated(self):
        """A proper subclass that implements convert_all should work."""

        class GoodConverter(BaseConverter):
            def convert_all(self) -> None:
                pass

        converter = GoodConverter("/gm", "/godot")
        self.assertIsInstance(converter, BaseConverter)


class TestBaseConverterDefaults(unittest.TestCase):
    """Verify default parameter values."""

    def setUp(self):
        class StubConverter(BaseConverter):
            def convert_all(self) -> None:
                pass

        self.converter: BaseConverter = StubConverter("/gm", "/godot")

    def test_log_callback_defaults_to_print(self):
        self.assertIs(self.converter.log_callback, print)

    def test_progress_callback_defaults_to_none(self):
        self.assertIsNone(self.converter.progress_callback)

    def test_conversion_running_defaults_to_true_lambda(self):
        """When conversion_running is not provided it should default to a callable returning True."""
        self.assertTrue(callable(self.converter.conversion_running))
        self.assertTrue(self.converter.conversion_running())


class TestBaseConverterThreadSafety(unittest.TestCase):
    """Call _safe_log and _safe_progress from multiple threads; verify no crash."""

    def setUp(self):
        class StubConverter(BaseConverter):
            def convert_all(self) -> None:
                pass

        self.messages: list[str] = []
        self.progress_values: list[int | float] = []

        self.converter = StubConverter(
            "/gm", "/godot",
            log_callback=lambda msg: self.messages.append(msg),
            progress_callback=lambda val: self.progress_values.append(val),
        )

    def test_safe_log_thread_safety(self):
        errors: list[Exception] = []

        def log_many(start: int) -> None:
            try:
                for i in range(50):
                    self.converter._safe_log(f"thread-{start}-msg-{i}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=log_many, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(self.messages), 200)

    def test_safe_progress_thread_safety(self):
        errors: list[Exception] = []

        def progress_many(start: int) -> None:
            try:
                for i in range(50):
                    self.converter._safe_progress(start * 100 + i)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=progress_many, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(self.progress_values), 200)


class TestBaseConverterCompactLogging(unittest.TestCase):
    """Verify _log_progress dispatches to the correct callback."""

    def setUp(self):
        class StubConverter(BaseConverter):
            def convert_all(self) -> None:
                pass

        self.log_messages: list[str] = []
        self.update_messages: list[str] = []
        self.converter = StubConverter(
            "/gm", "/godot",
            log_callback=lambda msg: self.log_messages.append(msg),
            update_log_callback=lambda msg: self.update_messages.append(msg),
            compact_logging=True,
        )

    def test_first_item_uses_log_callback(self):
        self.converter._log_progress("test_sprite", 1, 5)
        self.assertEqual(len(self.log_messages), 1)
        self.assertEqual(len(self.update_messages), 0)
        self.assertIn("[1/5]", self.log_messages[0])

    def test_subsequent_items_use_update_log(self):
        self.converter._log_progress("test_sprite", 1, 5)
        self.converter._log_progress("test_sprite", 2, 5)
        self.converter._log_progress("test_sprite", 3, 5)
        self.assertEqual(len(self.log_messages), 1)
        self.assertEqual(len(self.update_messages), 2)
        self.assertIn("[3/5]", self.update_messages[-1])

    def test_new_item_resets_to_log_callback(self):
        """When current resets to 1 (new asset group), a new line is appended."""
        self.converter._log_progress("sprite_a", 1, 3)
        self.converter._log_progress("sprite_a", 2, 3)
        self.converter._log_progress("sprite_a", 3, 3)
        self.converter._log_progress("sprite_b", 1, 2)
        self.converter._log_progress("sprite_b", 2, 2)
        self.assertEqual(len(self.log_messages), 2)  # Two "first items"
        self.assertEqual(len(self.update_messages), 3)  # Three updates

    def test_update_log_defaults_to_log_callback(self):
        """When update_log_callback is not provided, it falls back to log_callback."""
        class StubConverter(BaseConverter):
            def convert_all(self) -> None:
                pass

        messages: list[str] = []
        converter = StubConverter(
            "/gm", "/godot",
            log_callback=lambda msg: messages.append(msg),
        )
        converter._log_progress("item", 1, 3)
        converter._log_progress("item", 2, 3)
        # Both should go to log_callback since update_log_callback defaults to it
        self.assertEqual(len(messages), 2)


class TestReadYYFile(unittest.TestCase):
    """Test _read_yy_file() JSON parsing with trailing-comma cleanup."""

    def setUp(self):
        class StubConverter(BaseConverter):
            def convert_all(self) -> None:
                pass

        self.converter: BaseConverter = StubConverter("/gm", "/godot")
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_reads_valid_json(self):
        yy_path = os.path.join(self.tmp_dir, "test.yy")
        with open(yy_path, "w") as f:
            f.write('{"name": "test", "value": 42}')
        result = self.converter._read_yy_file(yy_path)
        self.assertEqual(result, {"name": "test", "value": 42})

    def test_cleans_trailing_commas(self):
        yy_path = os.path.join(self.tmp_dir, "test.yy")
        with open(yy_path, "w") as f:
            f.write('{"name": "test", "items": [1, 2, 3,],}')
        result = self.converter._read_yy_file(yy_path)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["items"], [1, 2, 3])

    def test_returns_none_for_missing_file(self):
        result = self.converter._read_yy_file("/nonexistent/path.yy")
        self.assertIsNone(result)

    def test_returns_none_for_invalid_json(self):
        yy_path = os.path.join(self.tmp_dir, "bad.yy")
        with open(yy_path, "w") as f:
            f.write("not valid json {{{")
        result = self.converter._read_yy_file(yy_path)
        self.assertIsNone(result)


class TestGetSubfolderFromYY(unittest.TestCase):
    """Test _get_subfolder_from_yy() extraction of IDE folder paths."""

    def setUp(self):
        class StubConverter(BaseConverter):
            def convert_all(self) -> None:
                pass

        self.converter: BaseConverter = StubConverter("/gm", "/godot")
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def _write_yy(self, parent_path: str) -> str:
        yy_path = os.path.join(self.tmp_dir, "test.yy")
        content = '{{"name": "test", "parent": {{"name": "folder", "path": "{path}",}},}}'.format(
            path=parent_path)
        with open(yy_path, "w") as f:
            f.write(content)
        return yy_path

    def test_nested_path(self):
        yy_path = self._write_yy("folders/Sprites/Player/Abilities.yy")
        self.assertEqual(self.converter._get_subfolder_from_yy(yy_path), "Player/Abilities")

    def test_deeply_nested_path(self):
        yy_path = self._write_yy("folders/Objects/Game/Enemies/Bosses.yy")
        self.assertEqual(self.converter._get_subfolder_from_yy(yy_path), "Game/Enemies/Bosses")

    def test_root_level_path(self):
        yy_path = self._write_yy("folders/Sprites.yy")
        self.assertEqual(self.converter._get_subfolder_from_yy(yy_path), "")

    def test_single_subfolder(self):
        yy_path = self._write_yy("folders/Objects/CLASSIC.yy")
        self.assertEqual(self.converter._get_subfolder_from_yy(yy_path), "CLASSIC")

    def test_missing_parent_field(self):
        yy_path = os.path.join(self.tmp_dir, "no_parent.yy")
        with open(yy_path, "w") as f:
            f.write('{"name": "test"}')
        self.assertEqual(self.converter._get_subfolder_from_yy(yy_path), "")

    def test_missing_file(self):
        self.assertEqual(self.converter._get_subfolder_from_yy("/nonexistent.yy"), "")

    def test_malformed_file(self):
        yy_path = os.path.join(self.tmp_dir, "bad.yy")
        with open(yy_path, "w") as f:
            f.write("not json")
        self.assertEqual(self.converter._get_subfolder_from_yy(yy_path), "")


if __name__ == "__main__":
    unittest.main()
