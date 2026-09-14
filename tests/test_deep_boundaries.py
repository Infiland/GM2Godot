"""Keep the optional engine out of deterministic conversion and Qt out of its client core."""
from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def imports(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


class DeepBoundaryTests(unittest.TestCase):
    def test_core_client_has_no_gui_dependency(self) -> None:
        for path in (ROOT / "src/deep").glob("*.py"):
            with self.subTest(file=path.name):
                self.assertFalse(any(name.startswith(("PySide6", "src.gui")) for name in imports(path)))

    def test_deterministic_converter_has_no_optional_engine_dependency(self) -> None:
        for path in (ROOT / "src/conversion").rglob("*.py"):
            with self.subTest(file=path.name):
                self.assertFalse(any(name.startswith(("src.deep", "keyring")) for name in imports(path)))

    def test_headless_help_requires_neither_qt_nor_keyring(self) -> None:
        code = """import sys
import main
assert 'PySide6' not in sys.modules
assert 'keyring' not in sys.modules
"""
        subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True)
