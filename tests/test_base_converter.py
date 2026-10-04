# pyright: reportAbstractUsage=false, reportPrivateUsage=false

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import SupportsIndex
from unittest.mock import mock_open, patch

# Ensure project root is on sys.path so "src.*" imports work
if (PROJECT_ROOT := os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.base_converter import BaseConverter
from src.conversion.conversion_outcome import ConversionCounts
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.gamemaker_json import GameMakerJsonDocument, decode_gamemaker_json
from src.conversion.json_values import JsonObject, JsonValue
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectManifestDiagnostic,
    ProjectSourceLocation,
    load_gamemaker_project_manifest,
)
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
    resolve_project_filesystem_source_path,
)
from src.conversion.resource_parent_metadata import (
    parse_gamemaker_resource_parent_metadata,
)


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

    def test_source_path_rejection_is_structured_and_owner_linked(self) -> None:
        class StubConverter(BaseConverter):
            def convert_all(self) -> None:
                pass

        with tempfile.TemporaryDirectory() as root:
            messages: list[str] = []
            diagnostics = DiagnosticCollector()
            converter = StubConverter(
                root,
                os.path.join(root, "godot"),
                log_callback=diagnostics.wrap_log_callback(messages.append),
                diagnostics=diagnostics,
            )

            resolved = converter._resolve_project_source(
                "../../../outside.gml",
                owner_source_path="rooms/r_test/r_test.yy",
                resource="r_test",
                resource_type="room",
                field="creationCodeFile",
            )

            self.assertIsNone(resolved)
            diagnostic = diagnostics.diagnostics()[0]
            self.assertEqual(diagnostic.code, "GM2GD-SOURCE-PATH-REJECTED")
            self.assertEqual(diagnostic.source_path, "rooms/r_test/r_test.yy")
            self.assertEqual(diagnostic.resource, "r_test")
            self.assertEqual(diagnostic.resource_type, "room")
            self.assertEqual(diagnostic.manifest_entry, "creationCodeFile")
            self.assertEqual(len(diagnostics.diagnostics()), 1)
            self.assertEqual(len(messages), 1)
            self.assertIn("Warning: Rejected GameMaker source path", messages[0])


class TestBaseConverterResourceOutcomes(unittest.TestCase):
    def setUp(self) -> None:
        class StubConverter(BaseConverter):
            def convert_all(self) -> None:
                pass

        self.running = threading.Event()
        self.running.set()
        self.converter = StubConverter(
            "/gm",
            "/godot",
            conversion_running=self.running.is_set,
        )

    def test_resource_wrappers_build_public_step_result(self) -> None:
        self.converter._resource_requested("script:completed")
        self.converter._resource_started("script:completed")
        self.converter._resource_completed("script:completed")
        self.converter._resource_requested("script:skipped")
        self.converter._resource_skipped("script:skipped")
        self.converter._resource_requested("script:failed")
        self.converter._resource_started("script:failed")
        self.converter._resource_failed("script:failed")

        result = self.converter.conversion_step_result()

        self.assertEqual(
            result.resources,
            ConversionCounts(
                requested=3,
                executed=2,
                completed=1,
                skipped=1,
                failed=1,
            ),
        )
        self.assertFalse(result.cancelled)

    def test_step_result_infers_cancellation_from_running_flag(self) -> None:
        self.running.clear()

        result = self.converter._conversion_step_result()

        self.assertTrue(result.cancelled)

    def test_explicit_cancellation_overrides_running_flag(self) -> None:
        self.assertTrue(self.running.is_set())

        result = self.converter.conversion_step_result(cancelled=True)

        self.assertTrue(result.cancelled)

    def test_default_finalization_marks_unfinished_resources_skipped(self) -> None:
        self.converter._resource_requested("script:not-started")
        self.converter._resource_requested("script:started")
        self.converter._resource_started("script:started")

        result = self.converter.conversion_step_result()

        self.assertEqual(
            result.resources,
            ConversionCounts(
                requested=2,
                executed=1,
                completed=0,
                skipped=2,
                failed=0,
            ),
        )

    def test_failed_finalization_preserves_unstarted_resource_as_skipped(self) -> None:
        self.converter._resource_requested("not-started")
        self.converter._resource_requested("started")
        self.converter._resource_started("started")

        result = self.converter.conversion_step_result(
            finalize_unfinished_as="failed",
        )

        self.assertEqual(
            result.resources,
            ConversionCounts(
                requested=2,
                executed=1,
                completed=0,
                skipped=1,
                failed=1,
            ),
        )

    def test_no_finalization_rejects_unfinished_resource(self) -> None:
        self.converter._resource_requested("opaque resource key")

        with self.assertRaises(ValueError):
            self.converter.conversion_step_result(
                finalize_unfinished_as=None,
            )

    def test_resource_wrappers_are_safe_across_threads(self) -> None:
        errors: list[Exception] = []

        def complete_resource(index: int) -> None:
            try:
                key = f"resource:{index}"
                self.converter._resource_requested(key)
                self.converter._resource_started(key)
                self.converter._resource_completed(key)
            except Exception as error:
                errors.append(error)

        threads = [
            threading.Thread(target=complete_resource, args=(index,))
            for index in range(40)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        result = self.converter.conversion_step_result()
        self.assertEqual(errors, [])
        self.assertEqual(
            result.resources,
            ConversionCounts(
                requested=40,
                executed=40,
                completed=40,
                skipped=0,
                failed=0,
            ),
        )


class TestProjectManifestSourcePathDiagnosticBridge(unittest.TestCase):
    class StubConverter(BaseConverter):
        def convert_all(self) -> None:
            pass

    def test_logs_and_returns_rejected_fields_without_collector(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with open(
                os.path.join(root, "Manifest.yyp"),
                "w",
                encoding="utf-8",
            ) as yyp_file:
                yyp_file.write(
                    '{"resources":[{"id":{"name":"snd_bad",'
                    '"path":"sounds/../../outside.yy"},'
                    '"resourceType":"GMSound"}]}'
                )
            manifest = load_gamemaker_project_manifest(root)
            messages: list[str] = []
            converter = self.StubConverter(
                root,
                os.path.join(root, "godot"),
                log_callback=messages.append,
            )

            rejected_fields = (
                converter._record_project_manifest_source_path_diagnostics(
                    manifest,
                    resource_type="sound",
                )
            )

        self.assertEqual(
            rejected_fields,
            frozenset({"resources[0].id.path"}),
        )
        self.assertEqual(len(messages), 1, messages)
        self.assertIn("Rejected GameMaker source path", messages[0])

    def test_unknown_resource_diagnostic_is_project_typed_and_order_independent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            with open(
                os.path.join(root, "Manifest.yyp"),
                "w",
                encoding="utf-8",
            ) as yyp_file:
                yyp_file.write(
                    '{"resources":[{"id":{"name":"unknown",'
                    '"path":"../../outside.yy"}}]}'
                )
            manifest = load_gamemaker_project_manifest(root)

            for resource_order in (("sound", "shader"), ("shader", "sound")):
                with self.subTest(resource_order=resource_order):
                    diagnostics = DiagnosticCollector()
                    messages: list[str] = []
                    returned_fields: list[frozenset[str]] = []
                    for resource_type in resource_order:
                        converter = self.StubConverter(
                            root,
                            os.path.join(root, "godot"),
                            log_callback=messages.append,
                            diagnostics=diagnostics,
                        )
                        returned_fields.append(
                            converter._record_project_manifest_source_path_diagnostics(
                                manifest,
                                resource_type=resource_type,
                            )
                        )

                    emitted = diagnostics.diagnostics()
                    self.assertEqual(len(emitted), 1, emitted)
                    self.assertEqual(emitted[0].resource_type, "project")
                    self.assertEqual(
                        emitted[0].manifest_entry,
                        "resources[0].id.path",
                    )
                    self.assertEqual(len(messages), 1, messages)
                    self.assertEqual(
                        returned_fields,
                        [
                            frozenset({"resources[0].id.path"}),
                            frozenset({"resources[0].id.path"}),
                        ],
                    )

    def test_project_sources_require_explicit_bridge_opt_in(self) -> None:
        manifest = GameMakerProjectManifest(
            project_name="",
            yyp_path=None,
            diagnostics=(
                ProjectManifestDiagnostic(
                    severity="warning",
                    code="GM2GD-SOURCE-PATH-REJECTED",
                    message="Rejected external project source",
                    source=ProjectSourceLocation(
                        path="AOutside.yyp",
                        line=1,
                        field_path="AOutside.yyp",
                    ),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as root:
            diagnostics = DiagnosticCollector()
            messages: list[str] = []
            converter = self.StubConverter(
                root,
                os.path.join(root, "godot"),
                log_callback=messages.append,
                diagnostics=diagnostics,
            )

            default_fields = (
                converter._record_project_manifest_source_path_diagnostics(
                    manifest
                )
            )
            included_fields = (
                converter._record_project_manifest_source_path_diagnostics(
                    manifest,
                    resource_type="sprite",
                    include_project_sources=True,
                )
            )

        self.assertEqual(default_fields, frozenset())
        self.assertEqual(included_fields, frozenset({"AOutside.yyp"}))
        emitted = diagnostics.diagnostics()
        self.assertEqual(len(emitted), 1, emitted)
        self.assertEqual(emitted[0].resource_type, "project")
        self.assertEqual(emitted[0].manifest_entry, "AOutside.yyp")
        self.assertEqual(messages, ["Rejected external project source"])


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

        self.tmp_dir = tempfile.mkdtemp()
        self.converter: BaseConverter = StubConverter(self.tmp_dir, "/godot")

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

    def test_does_not_read_valid_json_outside_project(self):
        with tempfile.TemporaryDirectory() as outside_dir:
            yy_path = os.path.join(outside_dir, "outside.yy")
            with open(yy_path, "w", encoding="utf-8") as source_file:
                source_file.write('{"outside": true}')

            result = self.converter._read_yy_file(yy_path)

        self.assertIsNone(result)


class TestGetSubfolderFromYY(unittest.TestCase):
    """Test _get_subfolder_from_yy() extraction of IDE folder paths."""

    def setUp(self):
        class StubConverter(BaseConverter):
            def convert_all(self) -> None:
                pass

        self.tmp_dir = tempfile.mkdtemp()
        self.converter: BaseConverter = StubConverter(self.tmp_dir, "/godot")

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
        self.assertEqual(self.converter._get_subfolder_from_yy(yy_path), "player/abilities")

    def test_deeply_nested_path(self):
        yy_path = self._write_yy("folders/Objects/Game/Enemies/Bosses.yy")
        self.assertEqual(self.converter._get_subfolder_from_yy(yy_path), "game/enemies/bosses")

    def test_root_level_path(self):
        yy_path = self._write_yy("folders/Sprites.yy")
        self.assertEqual(self.converter._get_subfolder_from_yy(yy_path), "")

    def test_single_subfolder(self):
        yy_path = self._write_yy("folders/Objects/CLASSIC.yy")
        self.assertEqual(self.converter._get_subfolder_from_yy(yy_path), "classic")

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


class TestSharedYYBoundary(unittest.TestCase):
    class StubConverter(BaseConverter):
        def convert_all(self) -> None:
            pass

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "metadata.yy"
        self.converter = self.StubConverter(self.root, self.root / "godot")

    def write_source(self, source: str) -> None:
        self.path.write_text(source, encoding="utf-8")

    def test_real_utf8_comma_dialect_and_literal_rewrite(self) -> None:
        self.write_source('{"name":"café", "literal":", }", "items":[1,2,],}')
        self.assertEqual(
            self.converter._read_yy_file(self.path),
            {"name": "café", "literal": "}", "items": [1, 2]},
        )

    def test_empty_object_and_legal_nonobject_roots(self) -> None:
        cases: list[tuple[str, JsonObject | None]] = [
            ("{}", {}), ("[]", None), ("null", None), ("true", None),
            ("42", None), ('"text"', None),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.write_source(source)
                self.assertEqual(self.converter._read_yy_file(self.path), expected)

    def test_resolution_open_and_shared_decode_order_and_source(self) -> None:
        source = '{"parent":{"path":"folders/Sprites/New.yy"}}'
        self.write_source(source)
        events: list[str] = []
        actual_open = open

        def resolve(root: str, path: os.PathLike[str]) -> ResolvedProjectSourcePath:
            events.append("resolve")
            self.assertIs(path, self.path)
            return resolve_project_filesystem_source_path(root, path)

        def acquire(path: str, mode: str, *, encoding: str):
            events.append("open")
            self.assertEqual((path, mode, encoding), (str(self.path), "r", "utf-8"))
            return actual_open(path, mode, encoding=encoding)

        def decode(contents: str, *, source_path: str) -> GameMakerJsonDocument:
            events.append("decode")
            return decode_gamemaker_json(contents, source_path=source_path)

        with (
            patch("src.conversion.base_converter.resolve_project_filesystem_source_path", side_effect=resolve),
            patch("builtins.open", side_effect=acquire),
            patch("src.conversion.base_converter.decode_gamemaker_json", side_effect=decode) as decoder,
        ):
            result = self.converter._read_yy_file(self.path)
        self.assertEqual(events, ["resolve", "open", "decode"])
        decoder.assert_called_once_with(source, source_path=str(self.path))
        self.assertEqual(result, {"parent": {"path": "folders/Sprites/New.yy"}})

    def test_decoded_unknown_shared_deep_and_native_values_keep_identity(self) -> None:
        self.write_source("{}")
        deep: JsonValue = {"unknown": "bottom"}
        for _ in range(1600):
            deep = [deep]
        shared: JsonObject = {"unknown": [True, None, 2**256, 2.5]}
        root: JsonObject = {
            "first": shared, "second": shared, "deep": deep,
            "nan": float("nan"), "infinity": float("inf"),
        }
        with patch("src.conversion.gamemaker_json.json.loads", return_value=root):
            result = self.converter._read_yy_file(self.path)
        self.assertIs(result, root)
        self.assertIs(root["first"], shared)
        self.assertIs(root["second"], shared)
        self.assertIs(root["deep"], deep)
        self.assertEqual(list(root), ["first", "second", "deep", "nan", "infinity"])

    def test_real_nonfinite_decoder_policy_is_retained(self) -> None:
        self.write_source('{"n":NaN,"p":Infinity,"m":-Infinity,"overflow":1e999,"b":true}')
        result = self.converter._read_yy_file(self.path)
        self.assertIsNotNone(result)
        assert result is not None
        nan_value = result["n"]
        assert isinstance(nan_value, float)
        self.assertTrue(math.isnan(nan_value))
        self.assertEqual((result["p"], result["m"], result["overflow"]), (math.inf, -math.inf, math.inf))
        self.assertIs(result["b"], True)

    def test_acquired_graph_rejects_cycles_keys_subclasses_and_non_json_children(self) -> None:
        class DerivedDict(dict[str, object]):
            pass

        class DerivedString(str):
            pass

        class DerivedList(list[object]):
            pass

        cycle: dict[str, object] = {}
        cycle["self"] = cycle
        self.write_source("{}")
        invalid: list[object] = [
            cycle, {1: "key"}, {"child": b"bytes"}, {"child": (1,)},
            {"child": object()}, DerivedDict(parent={"path": "folders/Sprites/X.yy"}),
            {"child": DerivedString("text")}, {"child": DerivedList([1])},
        ]
        for value in invalid:
            with self.subTest(kind=type(value).__name__), patch(
                "src.conversion.gamemaker_json.json.loads", return_value=value,
            ):
                self.assertIsNone(self.converter._read_yy_file(self.path))

    def test_invalid_utf8_bom_and_malformed_source_return_none(self) -> None:
        for contents in [b"\xff", b"\xef\xbb\xbf{}", b'{"broken":']:
            with self.subTest(contents=contents):
                self.path.write_bytes(contents)
                self.assertIsNone(self.converter._read_yy_file(self.path))

    def test_handled_exception_classes_remain_inside_each_acquisition_seam(self) -> None:
        self.write_source("{}")
        handled: list[Exception] = [
            OSError("read"), ProjectSourcePathError("containment"),
            json.JSONDecodeError("decode", "!", 0), KeyError("key"),
            TypeError("type"), ValueError("value"),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte"),
        ]
        for target in [
            "src.conversion.base_converter.resolve_project_filesystem_source_path",
            "builtins.open", "src.conversion.base_converter.decode_gamemaker_json",
        ]:
            for error in handled:
                with self.subTest(target=target, error=type(error).__name__), patch(target, side_effect=error):
                    self.assertIsNone(self.converter._read_yy_file(self.path))

    def test_unhandled_exception_instances_escape_each_acquisition_seam(self) -> None:
        self.write_source("{}")
        errors: list[BaseException] = [
            OverflowError("overflow"), RecursionError("recursion"),
            MemoryError("memory"), RuntimeError("runtime"),
            KeyboardInterrupt("interrupt"), SystemExit("exit"),
        ]
        for target in [
            "src.conversion.base_converter.resolve_project_filesystem_source_path",
            "builtins.open", "src.conversion.base_converter.decode_gamemaker_json",
        ]:
            for error in errors:
                with self.subTest(target=target, error=type(error).__name__), patch(target, side_effect=error):
                    with self.assertRaises(type(error)) as raised:
                        self.converter._read_yy_file(self.path)
                    self.assertIs(raised.exception, error)

    def test_real_decoder_recursion_and_integer_limit_policy(self) -> None:
        depth = sys.getrecursionlimit() + 100
        nested = '{"deep":' + "[" * depth + "0" + "]" * depth + "}"
        self.write_source(nested)
        try:
            json.loads(nested)
        except RecursionError:
            with self.assertRaises(RecursionError):
                self.converter._read_yy_file(self.path)
        else:
            result = self.converter._read_yy_file(self.path)
            self.assertIsNotNone(result)
            assert result is not None
            value: JsonValue = result["deep"]
            for _ in range(depth):
                self.assertIsInstance(value, list)
                assert isinstance(value, list)
                value = value[0]
            self.assertEqual(value, 0)
        limit = sys.get_int_max_str_digits()
        source = '{"integer":' + "1" * (limit + 1 if limit else 5000) + "}"
        self.write_source(source)
        if limit:
            with self.assertRaises(ValueError):
                json.loads(source)
            self.assertIsNone(self.converter._read_yy_file(self.path))
        else:
            self.assertEqual(self.converter._read_yy_file(self.path), json.loads(source))

    def test_outside_and_escaping_symlink_are_rejected_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "external.yy"
            external.write_text("{}", encoding="utf-8")
            self.path.symlink_to(external)
            with patch("builtins.open") as opened:
                self.assertIsNone(self.converter._read_yy_file(external))
                self.assertIsNone(self.converter._read_yy_file(self.path))
            opened.assert_not_called()

    def test_late_source_swap_is_revalidated_before_open(self) -> None:
        self.write_source("{}")
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "external.yy"
            external.write_text("{}", encoding="utf-8")

            def swap_then_resolve(root: str, path: os.PathLike[str]) -> ResolvedProjectSourcePath:
                self.path.unlink()
                self.path.symlink_to(external)
                return resolve_project_filesystem_source_path(root, path)

            with (
                patch("src.conversion.base_converter.resolve_project_filesystem_source_path", side_effect=swap_then_resolve),
                patch("builtins.open") as opened,
            ):
                self.assertIsNone(self.converter._read_yy_file(self.path))
            opened.assert_not_called()

    def test_original_pathlike_is_resolved_only_once(self) -> None:
        self.write_source('{"parent":{"path":"folders/Sprites/Folder.yy"}}')
        calls: list[str] = []

        class CountingPath(os.PathLike[str]):
            def __fspath__(self) -> str:
                calls.append("fspath")
                return str(self_path)

        self_path = self.path
        self.assertEqual(self.converter._get_subfolder_from_yy(CountingPath()), "folder")
        self.assertEqual(calls, ["fspath"])

    def test_read_exception_in_file_context_is_handled(self) -> None:
        source = mock_open(read_data="{}")
        error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte")
        source.return_value.read.side_effect = error
        with patch("builtins.open", source):
            self.assertIsNone(self.converter._read_yy_file(self.path))


class TestTypedResourceParentDispatch(unittest.TestCase):
    class StubConverter(BaseConverter):
        def convert_all(self) -> None:
            pass

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "metadata.yy"
        self.converter = self.StubConverter(self.root, self.root / "godot")

    def test_virtual_reader_receives_original_input_once_without_fspath(self) -> None:
        class UnreadPath(os.PathLike[str]):
            def __fspath__(self) -> str:
                raise AssertionError("parent extraction must not resolve virtual input")

        original = UnreadPath()
        data = {"parent": {"path": "folders/Sprites/Override.yy"}}
        with patch.object(self.converter, "_read_yy_file", return_value=data) as reader:
            self.assertEqual(self.converter._get_subfolder_from_yy(original), "override")
        reader.assert_called_once_with(original)

    def test_override_get_string_subclass_and_formatter_order(self) -> None:
        events: list[tuple[str, object]] = []

        class TracedString(str):
            def startswith(self, prefix: str | tuple[str, ...], start: SupportsIndex | None = 0, end: SupportsIndex | None = None) -> bool:
                events.append(("startswith", prefix))
                return super().startswith(prefix, start) if end is None else super().startswith(prefix, start, end)

            def endswith(self, suffix: str | tuple[str, ...], start: SupportsIndex | None = 0, end: SupportsIndex | None = None) -> bool:
                events.append(("endswith", suffix))
                return super().endswith(suffix, start) if end is None else super().endswith(suffix, start, end)

            def __getitem__(self, key: SupportsIndex | slice[SupportsIndex | None, SupportsIndex | None, SupportsIndex | None]) -> str:
                events.append(("slice", key))
                return TracedString(super().__getitem__(key))

            def split(self, sep: str | None = None, maxsplit: SupportsIndex = -1) -> list[str]:
                events.append(("split", sep))
                return super().split(sep, maxsplit)

        class TracedDict(dict[str, object]):
            def get(self, key: str, default: object = None) -> object:
                events.append(("get", key))
                return super().get(key, default)

        parent_path = TracedString("folders/Sprites/One/Two.yy")
        parent = TracedDict(path=parent_path)
        root = TracedDict(parent=parent)
        root["unknown"] = root

        def format_path(value: str) -> str:
            events.append(("formatter", value))
            return "formatted"

        with (
            patch.object(self.converter, "_read_yy_file", return_value=root),
            patch("src.conversion.base_converter.generated_subfolder_path", side_effect=format_path),
        ):
            self.assertEqual(self.converter._get_subfolder_from_yy(self.path), "formatted")
        self.assertEqual(events, [
            ("get", "parent"), ("get", "path"), ("startswith", "folders/"),
            ("slice", slice(8, None)), ("endswith", ".yy"),
            ("slice", slice(None, -3)), ("split", "/"), ("formatter", "One/Two"),
        ])

    def test_wrong_kind_parent_defaults_and_none_reader_short_circuit(self) -> None:
        roots: list[object] = [
            None, {}, {"parent": None}, {"parent": []}, {"parent": "text"},
            {"parent": {}}, {"parent": {"path": None}},
            {"parent": {"path": 4}}, {"parent": {"path": []}},
        ]
        for root in roots:
            with (
                self.subTest(root=root),
                patch.object(self.converter, "_read_yy_file", return_value=root),
                patch("src.conversion.base_converter.generated_subfolder_path") as formatter,
            ):
                self.assertEqual(self.converter._get_subfolder_from_yy(self.path), "")
            formatter.assert_not_called()
        with (
            patch.object(self.converter, "_read_yy_file", return_value=None),
            patch("src.conversion.base_converter.parse_gamemaker_resource_parent_metadata") as parser,
        ):
            self.assertEqual(self.converter._get_subfolder_from_yy(self.path), "")
        parser.assert_not_called()

    def test_valid_empty_string_still_observes_string_methods_before_root_return(self) -> None:
        events: list[str] = []

        class EmptyString(str):
            def startswith(self, prefix: str | tuple[str, ...], start: SupportsIndex | None = 0, end: SupportsIndex | None = None) -> bool:
                events.append("startswith")
                return super().startswith(prefix, start) if end is None else super().startswith(prefix, start, end)

            def endswith(self, suffix: str | tuple[str, ...], start: SupportsIndex | None = 0, end: SupportsIndex | None = None) -> bool:
                events.append("endswith")
                return super().endswith(suffix, start) if end is None else super().endswith(suffix, start, end)

            def split(self, sep: str | None = None, maxsplit: SupportsIndex = -1) -> list[str]:
                events.append("split")
                return super().split(sep, maxsplit)

        with (
            patch.object(self.converter, "_read_yy_file", return_value={"parent": {"path": EmptyString("")}}),
            patch("src.conversion.base_converter.generated_subfolder_path") as formatter,
        ):
            self.assertEqual(self.converter._get_subfolder_from_yy(self.path), "")
        self.assertEqual(events, ["startswith", "endswith", "split"])
        formatter.assert_not_called()

    def test_virtual_get_exceptions_keep_actual_leaf_extraction_catch(self) -> None:
        for error in [KeyError("key"), TypeError("type"), AttributeError("attribute"), ValueError("value")]:
            class FailingDict(dict[str, object]):
                def get(self, key: str, default: object = None) -> object:
                    raise error

            for root in [FailingDict(), {"parent": FailingDict()}]:
                with self.subTest(error=type(error).__name__, at_root=isinstance(root, FailingDict)), patch.object(self.converter, "_read_yy_file", return_value=root):
                    if isinstance(error, ValueError):
                        with self.assertRaises(ValueError) as raised:
                            self.converter._get_subfolder_from_yy(self.path)
                        self.assertIs(raised.exception, error)
                    else:
                        self.assertEqual(self.converter._get_subfolder_from_yy(self.path), "")

    def test_reader_exceptions_are_outside_extraction_catch(self) -> None:
        for error in [KeyError("key"), TypeError("type"), AttributeError("attribute")]:
            with self.subTest(error=type(error).__name__), patch.object(self.converter, "_read_yy_file", side_effect=error):
                with self.assertRaises(type(error)) as raised:
                    self.converter._get_subfolder_from_yy(self.path)
                self.assertIs(raised.exception, error)

    def test_parser_and_formatter_preserve_handled_and_unhandled_boundaries(self) -> None:
        root = {"parent": {"path": "folders/Sprites/Folder.yy"}}
        for target in [
            "src.conversion.base_converter.parse_gamemaker_resource_parent_metadata",
            "src.conversion.base_converter.generated_subfolder_path",
        ]:
            for error in [KeyError("key"), TypeError("type"), AttributeError("attribute")]:
                with self.subTest(target=target, error=type(error).__name__), patch.object(self.converter, "_read_yy_file", return_value=root), patch(target, side_effect=error):
                    self.assertEqual(self.converter._get_subfolder_from_yy(self.path), "")
            for error in [ValueError("value"), OverflowError("overflow"), RuntimeError("runtime"), KeyboardInterrupt("interrupt")]:
                with self.subTest(target=target, error=type(error).__name__), patch.object(self.converter, "_read_yy_file", return_value=root), patch(target, side_effect=error):
                    with self.assertRaises(type(error)) as raised:
                        self.converter._get_subfolder_from_yy(self.path)
                    self.assertIs(raised.exception, error)

    def test_captured_parent_authority_and_next_real_read_are_distinct(self) -> None:
        root: JsonObject = {"parent": {"path": "folders/Sprites/Captured.yy"}}

        def capture_then_replace(data: JsonObject):
            metadata = parse_gamemaker_resource_parent_metadata(data)
            self.assertIs(metadata.raw_data, root)
            data["parent"] = {"path": "folders/Sprites/Replaced.yy"}
            return metadata

        with (
            patch.object(self.converter, "_read_yy_file", return_value=root),
            patch("src.conversion.base_converter.parse_gamemaker_resource_parent_metadata", side_effect=capture_then_replace),
        ):
            self.assertEqual(self.converter._get_subfolder_from_yy(self.path), "captured")
        self.path.write_text('{"parent":{"path":"folders/Sprites/First.yy"}}', encoding="utf-8")
        self.assertEqual(self.converter._get_subfolder_from_yy(self.path), "first")
        self.path.write_text('{"parent":{"path":"folders/Sprites/Second.yy"}}', encoding="utf-8")
        self.assertEqual(self.converter._get_subfolder_from_yy(self.path), "second")

    def test_case_slashes_backslashes_and_punctuation_keep_formatting_order(self) -> None:
        cases = [
            ("Folders/Sprites/Foo.yy", "sprites/foo"),
            ("folders/Sprites/Foo.YY", "foo_yy"),
            ("folders//Sprites/Foo.yy", "sprites/foo"),
            ("folders/Sprites/One\\Two.yy", "one/two"),
            ("folders\\Sprites\\Foo.yy", ""),
            ("folders/Sprites/Hello-World/2Boss.yy", "hello_world/_2_boss"),
        ]
        for parent_path, expected in cases:
            with self.subTest(path=parent_path), patch.object(
                self.converter, "_read_yy_file", return_value={"parent": {"path": parent_path}},
            ):
                self.assertEqual(self.converter._get_subfolder_from_yy(self.path), expected)


if __name__ == "__main__":
    unittest.main()
