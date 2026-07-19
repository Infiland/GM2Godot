from __future__ import annotations

from pathlib import Path
import runpy
import sys
from types import ModuleType
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = (
    PROJECT_ROOT / "packaging" / "linux" / "hooks" / "hook-PySide6.QtGui.py"
)


def _run_hook(
    binaries: list[tuple[str, str]],
) -> tuple[dict[str, object], list[str]]:
    calls: list[str] = []
    pyinstaller = ModuleType("PyInstaller")
    utils = ModuleType("PyInstaller.utils")
    hooks = ModuleType("PyInstaller.utils.hooks")
    qt = ModuleType("PyInstaller.utils.hooks.qt")

    def add_qt6_dependencies(hook_file: str):
        calls.append(hook_file)
        return ["qt-hidden-import"], list(binaries), [("qt-data", "qt-data")]

    qt.add_qt6_dependencies = add_qt6_dependencies  # type: ignore[attr-defined]
    modules = {
        "PyInstaller": pyinstaller,
        "PyInstaller.utils": utils,
        "PyInstaller.utils.hooks": hooks,
        "PyInstaller.utils.hooks.qt": qt,
    }
    with patch.dict(sys.modules, modules):
        namespace = runpy.run_path(str(HOOK_PATH))
    return namespace, calls


class LinuxQtHookPolicyTests(unittest.TestCase):
    def test_hook_preserves_qt_dependencies_and_excludes_only_tiff(self) -> None:
        tiff = (
            "/wheel/PySide6/Qt/plugins/imageformats/libqtiff.so",
            "PySide6/Qt/plugins/imageformats",
        )
        qxcb = (
            "/wheel/PySide6/Qt/plugins/platforms/libqxcb.so",
            "PySide6/Qt/plugins/platforms",
        )
        png = (
            "/wheel/PySide6/Qt/plugins/imageformats/libqpng.so",
            "PySide6/Qt/plugins/imageformats",
        )

        namespace, calls = _run_hook([qxcb, tiff, png])

        self.assertEqual(calls, [str(HOOK_PATH)])
        self.assertEqual(namespace["hiddenimports"], ["qt-hidden-import"])
        self.assertEqual(namespace["datas"], [("qt-data", "qt-data")])
        self.assertEqual(namespace["binaries"], [qxcb, png])
        self.assertEqual(namespace["unsupported_tiff_plugins"], [tiff])

    def test_hook_accepts_windows_style_plugin_destination(self) -> None:
        tiff = (
            "/wheel/PySide6/Qt/plugins/imageformats/libqtiff.so",
            "PySide6\\Qt\\plugins\\imageformats",
        )

        namespace, _ = _run_hook([tiff])

        self.assertEqual(namespace["binaries"], [])

    def test_hook_fails_closed_when_tiff_plugin_is_missing(self) -> None:
        qxcb = (
            "/wheel/PySide6/Qt/plugins/platforms/libqxcb.so",
            "PySide6/Qt/plugins/platforms",
        )

        with self.assertRaisesRegex(RuntimeError, "found 0"):
            _run_hook([qxcb])

    def test_hook_fails_closed_when_tiff_plugin_is_duplicated(self) -> None:
        plugins = [
            (
                "/wheel-a/PySide6/Qt/plugins/imageformats/libqtiff.so",
                "PySide6/Qt/plugins/imageformats",
            ),
            (
                "/wheel-b/PySide6/Qt/plugins/imageformats/libqtiff.so",
                "PySide6/Qt/plugins/imageformats",
            ),
        ]

        with self.assertRaisesRegex(RuntimeError, "found 2"):
            _run_hook(plugins)

    def test_same_basename_outside_qt_imageformats_is_not_silently_removed(
        self,
    ) -> None:
        unrelated = ("/vendor/libqtiff.so", "vendor")

        with self.assertRaisesRegex(RuntimeError, "found 0"):
            _run_hook([unrelated])


if __name__ == "__main__":
    unittest.main()
