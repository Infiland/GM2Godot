"""Public CLI configuration behavior characterized before owner extraction."""
from __future__ import annotations

import io
import signal
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src import cli
from src.cli_configuration import (
    CLISetting,
    ConverterSelection,
    ConvertRequest,
    DiagnosticThresholds,
    build_parser,
    convert_request_from_args,
    converter_inventory,
    settings_for_selection,
)
from tests.cli_test_support import OutcomeConverterStub, partial_outcome, success_outcome

SETTING_KEYS = (
    "sprites", "fonts", "sounds", "included_files", "scripts", "objects", "rooms", "asset_registry",
    "game_icon", "project_name", "project_settings", "audio_buses", "notes", "shaders", "tilesets",
    "sound_group_folders",
)


class TestCLIConfigurationEntry(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.gm = str(Path(self.directory.name, "gm"))
        self.godot = str(Path(self.directory.name, "godot"))
        self.arguments = ["convert", "--gm-project", self.gm, "--godot-project", self.godot]

    def test_default_platform_and_csv_selection_preserve_complete_settings(self) -> None:
        cases: tuple[tuple[list[str], tuple[str, ...], bool], ...] = (
            ([], SETTING_KEYS[:-1], False),
            (["--groups", " , "], (), False),
            (["--only", " scripts, fonts,scripts, ", "--groups", "bad"], ("scripts", "fonts"), False),
            (["--only", " , ", "--groups", "wip, wip", "--sound-group-folders"], ("shaders", "tilesets"), True),
        )
        for flags, selected, modifier in cases:
            with self.subTest(flags=flags):
                converter = OutcomeConverterStub(success_outcome())
                stdout, stderr = io.StringIO(), io.StringIO()
                expected = {key: CLISetting(key in selected) for key in SETTING_KEYS}
                expected["sound_group_folders"] = CLISetting(modifier)
                with (
                    patch("src.cli.Converter", side_effect=converter.bind_factory),
                    patch.object(converter, "convert", wraps=converter.convert) as convert,
                    patch("sys.platform", "darwin"),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    exit_code = cli.main(self.arguments + flags)
                self.assertEqual(exit_code, 0)
                self.assertEqual(convert.call_count, 1)
                self.assertEqual(convert.call_args.args, (self.gm, "macos", self.godot, expected))
                self.assertEqual(tuple(convert.call_args.args[3]), SETTING_KEYS)
                self.assertIs(convert.call_args.kwargs["diagnostics"], converter.diagnostics)
                self.assertEqual(stdout.getvalue(), converter.outcome.summary_line() + "\n")
                self.assertEqual(stderr.getvalue(), "")

    def test_unknown_selection_exits_after_constructor_before_conversion(self) -> None:
        cases = (
            (["--only", "scripts, bad, fonts"], "Unknown converter key for --only: bad"),
            (["--only", "sound_group_folders"], "Unknown converter key for --only: sound_group_folders"),
            (["--groups", "assets, bad, wip"], "Unknown conversion group for --groups: bad"),
        )
        for flags, message in cases:
            with self.subTest(flags=flags):
                converter = OutcomeConverterStub(success_outcome())
                previous = signal.getsignal(signal.SIGINT)
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    patch("src.cli.Converter", side_effect=converter.bind_factory) as factory,
                    patch.object(converter, "convert", wraps=converter.convert) as convert,
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                    self.assertRaises(SystemExit) as raised,
                ):
                    cli.main(self.arguments + flags)
                self.assertEqual(raised.exception.code, message)
                factory.assert_called_once()
                convert.assert_not_called()
                self.assertIsNotNone(converter.conversion_running)
                self.assertEqual(signal.getsignal(signal.SIGINT), previous)
                self.assertEqual((stdout.getvalue(), stderr.getvalue()), ("", ""))
                self.assertFalse(Path(self.godot).exists())

    def test_constructor_error_precedes_invalid_selection_and_restores_signal(self) -> None:
        failure = RuntimeError("constructor failed before selection")
        previous = signal.getsignal(signal.SIGINT)
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch("src.cli.Converter", side_effect=failure) as factory,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
            self.assertRaises(RuntimeError) as raised,
        ):
            cli.main(self.arguments + ["--only", "bad"])
        self.assertIs(raised.exception, failure)
        factory.assert_called_once()
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)
        self.assertEqual((stdout.getvalue(), stderr.getvalue()), ("", ""))

    def test_unsafe_report_destination_precedes_constructor_and_selection(self) -> None:
        report_dir = str(Path(self.godot, "scripts"))
        previous = signal.getsignal(signal.SIGINT)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("src.cli.Converter") as factory, redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = cli.main(self.arguments + ["--report-dir", report_dir, "--only", "bad"])
        self.assertEqual(exit_code, 2)
        factory.assert_not_called()
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            stderr.getvalue(),
            "GM2Godot conversion report destination is unsafe: generated reports would enter a converter-owned "
            "managed root; choose the project root, a path under its gm2godot directory, "
            "or an external report directory\n",
        )
        self.assertFalse(Path(self.godot).exists())

    def test_invalid_boot_frames_are_parser_errors_before_application_work(self) -> None:
        for value in ("-1", "wrong"):
            with self.subTest(value=value):
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    patch("src.cli.Converter") as factory,
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                    self.assertRaises(SystemExit) as raised,
                ):
                    cli.main(["validate", "--godot-project", self.godot, "--godot-boot-frames", value])
                self.assertEqual(raised.exception.code, 2)
                self.assertEqual(stdout.getvalue(), "")
                self.assertTrue(stderr.getvalue().endswith(f"Expected a non-negative integer: {value}\n"))
                factory.assert_not_called()

    def test_warning_threshold_still_precedes_allow_partial(self) -> None:
        cases: tuple[tuple[list[str], int], ...] = (
            ([], 2), (["--allow-partial"], 0), (["--allow-partial", "--max-warnings", "0"], 2),
        )
        for flags, expected in cases:
            with self.subTest(flags=flags):
                converter = OutcomeConverterStub(partial_outcome(), warning=True)
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    patch("src.cli.Converter", side_effect=converter.bind_factory),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    exit_code = cli.main(self.arguments + flags)
                self.assertEqual(exit_code, expected)
                self.assertEqual(converter.last_outcome, converter.outcome)
                self.assertEqual(stdout.getvalue(), converter.outcome.summary_line() + "\n")
                self.assertEqual(stderr.getvalue(), "")


class TestCLIConfigurationModels(unittest.TestCase):
    def test_request_copies_raw_selection_and_thresholds_without_resolving(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "convert", "--gm-project", "raw gm", "--godot-project", "raw out", "--target-platform", "linux",
            "--only", " bad, scripts ", "--groups", "bad too", "--sound-group-folders", "--allow-partial",
            "--report-dir", "raw reports", "--max-errors", "-2", "--max-warnings", "3", "--fail-on-unsupported",
        ])
        request = convert_request_from_args(args)
        self.assertEqual(
            request,
            ConvertRequest(
                "raw gm", "linux", "raw out", ConverterSelection(" bad, scripts ", "bad too", True),
                "raw reports", True, DiagnosticThresholds(True, None, -2, 3),
            ),
        )
        args.only = "fonts"
        self.assertEqual(request.selection.only, " bad, scripts ")
        with self.assertRaises(SystemExit) as raised:
            settings_for_selection(request.selection)
        self.assertEqual(raised.exception.code, "Unknown converter key for --only: bad")

    def test_inventory_returns_fresh_lists_and_exact_modifier_exclusion(self) -> None:
        first = converter_inventory()
        second = converter_inventory()
        self.assertEqual(first, second)
        self.assertEqual(first["default_groups"], ["assets", "project", "wip"])
        self.assertEqual(first["converter_keys"], sorted(SETTING_KEYS[:-1]))
        self.assertNotIn("sound_group_folders", first["groups"]["assets"])
        first["default_groups"].clear()
        first["groups"]["assets"].clear()
        first["converter_keys"].clear()
        self.assertEqual(second["default_groups"], ["assets", "project", "wip"])
        self.assertEqual(second["groups"]["assets"], list(SETTING_KEYS[:8]))
        self.assertEqual(second["converter_keys"], sorted(SETTING_KEYS[:-1]))
