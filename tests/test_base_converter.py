import os
import sys
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
            def convert_all(self):
                pass

        converter = GoodConverter("/gm", "/godot")
        self.assertIsInstance(converter, BaseConverter)


class TestBaseConverterDefaults(unittest.TestCase):
    """Verify default parameter values."""

    def setUp(self):
        class StubConverter(BaseConverter):
            def convert_all(self):
                pass

        self.converter = StubConverter("/gm", "/godot")

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
            def convert_all(self):
                pass

        self.messages = []
        self.progress_values = []

        self.converter = StubConverter(
            "/gm", "/godot",
            log_callback=lambda msg: self.messages.append(msg),
            progress_callback=lambda val: self.progress_values.append(val),
        )

    def test_safe_log_thread_safety(self):
        errors = []

        def log_many(start):
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
        errors = []

        def progress_many(start):
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


if __name__ == "__main__":
    unittest.main()
