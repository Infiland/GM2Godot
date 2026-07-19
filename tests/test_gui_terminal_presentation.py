# pyright: reportPrivateUsage=false
# ruff: noqa: E402

from __future__ import annotations

import os
import unittest
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QTextCursor
from PySide6.QtWidgets import QApplication

from src.conversion.conversion_outcome import ConversionTerminalState
from src.gui.panels.console_panel import ConsoleLogStyle, ConsolePanel
from src.gui.panels.progress_panel import ProgressPanel
from src.gui.theme import THEME


def _first_character_color(panel: ConsolePanel, block_number: int) -> str:
    block = panel._text_edit.document().findBlockByNumber(block_number)
    cursor = QTextCursor(block)
    cursor.movePosition(
        QTextCursor.MoveOperation.NextCharacter,
        QTextCursor.MoveMode.KeepAnchor,
    )
    return cursor.charFormat().foreground().color().name()


def _relative_luminance(color: QColor) -> float:
    def linearize(component: float) -> float:
        if component <= 0.04045:
            return component / 12.92
        return ((component + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * linearize(color.redF())
        + 0.7152 * linearize(color.greenF())
        + 0.0722 * linearize(color.blueF())
    )


def _contrast_ratio(first: QColor, second: QColor) -> float:
    lighter = max(_relative_luminance(first), _relative_luminance(second))
    darker = min(_relative_luminance(first), _relative_luminance(second))
    return (lighter + 0.05) / (darker + 0.05)


class GuiTerminalPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        existing_app = QApplication.instance()
        cls.app = existing_app if isinstance(existing_app, QApplication) else QApplication([])

    def setUp(self) -> None:
        self.console = ConsolePanel()
        self.progress = ProgressPanel()

    def tearDown(self) -> None:
        self.console.deleteLater()
        self.progress.deleteLater()

    def test_explicit_console_styles_do_not_depend_on_english_prefixes(self) -> None:
        messages_and_styles: tuple[tuple[str, ConsoleLogStyle, str], ...] = (
            ("Conversion complete", "success", str(THEME["log_success"])),
            ("Unvollstaendige Ausgabe", "warning", str(THEME["log_warning"])),
            ("Datentraeger voll", "error", str(THEME["log_error"])),
            ("Konvertierung gestoppt", "cancelled", str(THEME["log_cancelled"])),
        )

        for message, style, _expected_color in messages_and_styles:
            self.console.append_log(message, style)

        for block_number, (_message, _style, expected_color) in enumerate(messages_and_styles):
            self.assertEqual(
                _first_character_color(self.console, block_number),
                expected_color,
            )

    def test_auto_console_style_preserves_prefix_detection(self) -> None:
        self.console.append_log("Warning: incomplete output")
        self.console.append_log("step: error: failed")
        self.console.append_log("ordinary progress")

        self.assertEqual(
            _first_character_color(self.console, 0),
            THEME["log_warning"],
        )
        self.assertEqual(
            _first_character_color(self.console, 1),
            THEME["log_error"],
        )
        self.assertEqual(
            _first_character_color(self.console, 2),
            THEME["fg_primary"],
        )

    def test_update_last_line_accepts_explicit_style(self) -> None:
        self.console.append_log("working")
        self.console.update_last_line("stopped", "cancelled")

        self.assertEqual(self.console._text_edit.toPlainText(), "stopped")
        self.assertEqual(
            _first_character_color(self.console, 0),
            THEME["log_cancelled"],
        )

    def test_console_rejects_unknown_explicit_style(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported console log style"):
            self.console.append_log("message", cast(ConsoleLogStyle, "unknown"))

    def test_terminal_progress_states_override_bar_and_label_colors(self) -> None:
        states_and_colors: tuple[tuple[ConversionTerminalState, str], ...] = (
            ("success", str(THEME["log_success"])),
            ("partial", str(THEME["log_warning"])),
            ("failed", str(THEME["log_error"])),
            ("cancelled", str(THEME["log_cancelled"])),
        )
        self.progress.progress_bar.set_progress(43)

        for state, expected_color in states_and_colors:
            message = f"terminal: {state}"
            self.progress.set_terminal_status(message, state)

            self.assertEqual(self.progress.presentation_state, state)
            self.assertEqual(self.progress.progress_bar.presentation_state, state)
            self.assertEqual(self.progress.progress_bar._progress, 43)
            self.assertEqual(self.progress.status_label.text(), message)
            self.assertIn(f"color: {expected_color};", self.progress.status_label.styleSheet())
            self.assertIn("font-weight: bold;", self.progress.status_label.styleSheet())
            self.assertEqual(
                self.progress.progress_bar._get_progress_color(0.43).name(),
                expected_color,
            )

    def test_full_terminal_bar_renders_dark_text_with_accessible_contrast(self) -> None:
        bar = self.progress.progress_bar
        bar.resize(240, 30)
        bar.set_progress(100)
        dark_text = QColor(THEME["bg_primary"])
        white_text = QColor(THEME["fg_white"])

        states_and_color_keys: tuple[
            tuple[ConversionTerminalState, str], ...
        ] = (
            ("success", "log_success"),
            ("partial", "log_warning"),
            ("failed", "log_error"),
            ("cancelled", "log_cancelled"),
        )
        for state, color_key in states_and_color_keys:
            with self.subTest(state=state):
                bar.set_terminal_status(state)
                fill_color = QColor(THEME[color_key])
                self.assertGreaterEqual(
                    _contrast_ratio(fill_color, dark_text),
                    4.5,
                )

                image = QImage(240, 30, QImage.Format.Format_ARGB32)
                image.fill(QColor(0, 0, 0, 0))
                bar.render(image)
                pixels = (
                    image.pixelColor(x, y)
                    for y in range(image.height())
                    for x in range(image.width())
                )
                rendered_colors = tuple(pixels)
                self.assertIn(dark_text, rendered_colors)
                self.assertNotIn(white_text, rendered_colors)

    def test_running_status_resets_terminal_color_override(self) -> None:
        self.progress.set_terminal_status("partial", "partial")
        terminal_color = self.progress.progress_bar._get_progress_color(0.43).name()

        self.progress.set_running_status("Converting sprites")

        self.assertEqual(self.progress.presentation_state, "running")
        self.assertEqual(self.progress.progress_bar.presentation_state, "running")
        self.assertEqual(self.progress.status_label.text(), "Converting sprites")
        self.assertIn(
            f"color: {THEME['fg_primary']};",
            self.progress.status_label.styleSheet(),
        )
        self.assertIn("font-weight: bold;", self.progress.status_label.styleSheet())
        self.assertNotEqual(
            self.progress.progress_bar._get_progress_color(0.43).name(),
            terminal_color,
        )

    def test_terminal_status_rejects_unknown_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported conversion terminal state"):
            self.progress.set_terminal_status(
                "unknown",
                cast(ConversionTerminalState, "unknown"),
            )


if __name__ == "__main__":
    unittest.main()
