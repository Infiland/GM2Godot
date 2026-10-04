from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest import mock

from scripts import check_complexity as gate
from src.conversion.json_values import JsonArray, JsonObject, JsonValue


def _function_source(name: str = "work", complexity: int = 16) -> str:
    lines = [f"def {name}(value):"]
    for number in range(complexity - 1):
        lines.extend((f"    if value == {number}:", f"        return {number}"))
    return "\n".join((*lines, "    return None", ""))


def _json_decoder_raises_recursion(text: str) -> bool:
    try:
        json.loads(text)
    except RecursionError:
        return True
    return False


class TestComplexityPolicy(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="gm2godot-complexity-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.policy_path = self.root / "complexity-exceptions.json"
        docs = self.root / "docs"
        docs.mkdir()
        (docs / "complexity-removal.md").write_text("# Work\nSplit the branch responsibilities.\n", encoding="utf-8")

    def _source(self, text: str, path: str = "work.py") -> Path:
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        return destination

    def _record(self, function: str = "work", score: int = 16, path: str = "work.py") -> JsonObject:
        return {
            "path": path, "function": function, "measured_complexity": score, "ceiling": score,
            "reason": "The fixture keeps independent branch decisions while decomposition is reviewed.",
            "removal_action": "Separate named branch responsibilities and preserve the branch-result tests.",
            "tracking_url": "docs/complexity-removal.md#work",
        }

    def _write_policy(self, records: Sequence[JsonObject] = ()) -> gate.ComplexityPolicy:
        exceptions: JsonArray = [record for record in records]
        payload: JsonObject = {"schema_version": 1, "max_complexity": 15, "exceptions": exceptions}
        self.policy_path.write_text(json.dumps(payload), encoding="utf-8")
        return gate.load_policy(self.policy_path)

    def _diagnostic(self, function: str = "work", score: int = 16, row: int = 1) -> JsonObject:
        return {
            "code": "C901", "filename": str(self.root / "work.py"),
            "location": {"row": row, "column": 5},
            "message": f"`{function}` is too complex ({score} > 15)", "cell": None,
        }

    def _tool_output(self, *records: JsonObject, returncode: int = 1) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(("ruff",), returncode, json.dumps(records), "")

    def _track(self, *names: str) -> None:
        initialization = subprocess.run(
            ("git", "init", "--quiet", str(self.root)), capture_output=True, text=True, check=False,
        )
        self.assertEqual(initialization.returncode, 0, initialization.stderr)
        addition = subprocess.run(
            ("git", "-C", str(self.root), "add", "--force", "--", *names),
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(addition.returncode, 0, addition.stderr)

    def test_real_ruff_accepts_15_and_rejects_new_16(self) -> None:
        self._source(_function_source(complexity=15))
        self._track("work.py")
        self._write_policy()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(gate.main(("--root", str(self.root))), 0)
        self._source(_function_source(complexity=16))
        error = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(error):
            self.assertEqual(gate.main(("--root", str(self.root))), 1)
        self.assertIn("new complexity debt: work.py::work (16)", error.getvalue())
        self._track("docs/complexity-removal.md")
        self._write_policy((self._record(),))
        before = self.policy_path.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(gate.main(("--root", str(self.root))), 0)
        self.assertEqual(self.policy_path.read_bytes(), before)

    def test_named_allowance_growth_improvement_and_removal_ratchet(self) -> None:
        policy = self._write_policy((self._record(),))
        key = gate.FunctionKey("work.py", "work")
        self.assertEqual(gate.evaluate_policy(policy, (gate.ComplexityFinding(key, 16, 1),)), ())
        self.assertEqual(
            gate.evaluate_policy(policy, (gate.ComplexityFinding(key, 17, 1),)),
            ("complexity ceiling exceeded: work.py::work (17 > 16)",),
        )
        larger = self._write_policy((self._record(score=17),))
        self.assertEqual(
            gate.evaluate_policy(larger, (gate.ComplexityFinding(key, 16, 1),)),
            ("tighten measured score and ceiling: work.py::work (17 -> 16)",),
        )
        self.assertEqual(
            gate.evaluate_policy(policy, ()),
            ("remove stale exception: work.py::work (absent or complexity <= 15)",),
        )
        self.assertEqual(gate.evaluate_policy(self._write_policy(), ()), ())

    def test_rename_move_and_delete_need_explicit_policy_changes(self) -> None:
        policy = self._write_policy((self._record(),))
        moved = gate.ComplexityFinding(gate.FunctionKey("nested/new.py", "renamed"), 16, 1)
        errors = gate.evaluate_policy(policy, (moved,))
        self.assertEqual(len(errors), 2)
        self.assertIn("new complexity debt: nested/new.py::renamed (16)", errors)
        self.assertIn("remove stale exception: work.py::work (absent or complexity <= 15)", errors)
        transferred = self._write_policy((self._record("renamed", path="nested/new.py"),))
        self.assertEqual(transferred.exceptions[0].ceiling, policy.exceptions[0].ceiling)
        self.assertEqual(gate.evaluate_policy(transferred, (moved,)), ())
        self.assertTrue(gate.evaluate_policy(transferred, ()))

    def test_lexical_class_nested_and_async_identities_are_distinct(self) -> None:
        self._source(
            "class First:\n    def work(self):\n        return None\n"
            "class Second:\n    def work(self):\n        return None\n"
            "def outer():\n    async def inner():\n        return None\n    return inner\n"
        )
        index = gate.index_functions(self.root, ("work.py",))
        keys = {key.function for key in index.by_key}
        self.assertEqual(keys, {"First.work", "Second.work", "outer", "outer.inner"})
        findings = gate.parse_findings(
            self._tool_output(self._diagnostic(row=2), self._diagnostic(row=5)),
            self.root, ("work.py",), index,
        )
        self.assertEqual([finding.key.function for finding in findings], ["First.work", "Second.work"])
        inner = self._diagnostic("inner", row=8)
        findings = gate.parse_findings(self._tool_output(inner), self.root, ("work.py",), index)
        self.assertEqual(findings[0].key.function, "outer.inner")

    def test_harmless_line_shifts_preserve_the_policy_key(self) -> None:
        self._source("\n\n" + _function_source())
        index = gate.index_functions(self.root, ("work.py",))
        findings = gate.parse_findings(self._tool_output(self._diagnostic(row=3)), self.root, ("work.py",), index)
        self.assertEqual(gate.evaluate_policy(self._write_policy((self._record(),)), findings), ())

    def test_duplicate_qualified_definitions_or_findings_are_rejected(self) -> None:
        self._source(_function_source() + _function_source())
        index = gate.index_functions(self.root, ("work.py",))
        with self.assertRaisesRegex(gate.ComplexityError, "unique qualified function"):
            gate.parse_findings(self._tool_output(self._diagnostic()), self.root, ("work.py",), index)
        self._source(_function_source())
        index = gate.index_functions(self.root, ("work.py",))
        repeated = self._tool_output(self._diagnostic(), self._diagnostic())
        with self.assertRaisesRegex(gate.ComplexityError, "duplicate path/function findings"):
            gate.parse_findings(repeated, self.root, ("work.py",), index)

    def test_diagnostic_name_row_threshold_and_schema_must_match(self) -> None:
        self._source(_function_source())
        index = gate.index_functions(self.root, ("work.py",))
        changes: tuple[tuple[str, JsonValue], ...] = (
            ("code", "F401"), ("cell", 1), ("unknown", True),
            ("message", "`different` is too complex (16 > 15)"),
            ("message", "`work` is too complex (16 > 20)"),
            ("message", "`work` is too complex (15 > 15)"),
            ("location", {"row": 2, "column": 5}),
            ("location", {"row": True, "column": 5}),
            ("severity", "warning"), ("noqa_row", False),
        )
        for field, value in changes:
            diagnostic = self._diagnostic()
            diagnostic[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(gate.ComplexityError):
                gate.parse_findings(self._tool_output(diagnostic), self.root, ("work.py",), index)

    def test_outside_untracked_and_notebook_diagnostic_paths_are_rejected(self) -> None:
        self._source(_function_source())
        self._source(_function_source(), "untracked.py")
        self._source("{}", "notebook.ipynb")
        index = gate.index_functions(self.root, ("work.py",))
        for filename in (self.root.parent / "missing.py", self.root / "untracked.py", self.root / "notebook.ipynb"):
            diagnostic = self._diagnostic()
            diagnostic["filename"] = str(filename)
            with self.subTest(filename=filename), self.assertRaises(gate.ComplexityError):
                gate.parse_findings(self._tool_output(diagnostic), self.root, ("work.py", "notebook.ipynb"), index)

    def test_policy_rejects_stale_schema_duplicate_keys_and_unratcheted_records(self) -> None:
        changes: tuple[tuple[str, JsonValue], ...] = (
            ("ceiling", 17), ("measured_complexity", 15), ("measured_complexity", True), ("ceiling", -1),
            ("reason", ""), ("removal_action", " "), ("tracking_url", ""),
            ("path", "../work.py"), ("function", "First..work"), ("extra", "not allowed"),
        )
        for field, value in changes:
            record = self._record()
            record[field] = value
            with self.subTest(field=field), self.assertRaises(gate.ComplexityError):
                self._write_policy((record,))
        with self.assertRaisesRegex(gate.ComplexityError, "duplicate path/function"):
            self._write_policy((self._record(), self._record()))
        for text in (
            'not JSON', '{}',
            '{"schema_version":2,"max_complexity":15,"exceptions":[]}',
            '{"schema_version":1,"max_complexity":20,"exceptions":[]}',
            '{"schema_version":true,"max_complexity":15,"exceptions":[]}',
            '{"schema_version":1,"max_complexity":15,"exceptions":[],"ignore":[]}',
            '{"schema_version":1,"max_complexity":15,"max_complexity":15,"exceptions":[]}',
        ):
            self.policy_path.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaises(gate.ComplexityError):
                gate.load_policy(self.policy_path)

    def test_removal_links_accept_docs_or_https_and_reject_malformed_locations(self) -> None:
        for link in ("docs/complexity-removal.md#work", "https://example.invalid/plan/work"):
            record = self._record()
            record["tracking_url"] = link
            self.assertEqual(self._write_policy((record,)).exceptions[0].tracking_url, link)
        for link in ("http://example.invalid/plan", "https://", "https://[bad/plan", "https://host:bad/plan", "docs/../plan.md", "docs/a.md\n"):
            record = self._record()
            record["tracking_url"] = link
            with self.subTest(link=link), self.assertRaises(gate.ComplexityError):
                self._write_policy((record,))

    def test_relative_removal_plan_must_be_in_the_tracked_inputs(self) -> None:
        policy = self._write_policy((self._record(),))
        with self.assertRaisesRegex(gate.ComplexityError, "removal-plan document must be tracked"):
            gate.validate_local_plan_links(self.root, policy, ("work.py",))
        gate.validate_local_plan_links(self.root, policy, ("work.py", "docs/complexity-removal.md"))

    def test_real_ruff_cannot_be_hidden_by_noqa_config_or_gitignore(self) -> None:
        source = "# ruff: noqa: C901\n" + _function_source().replace("def work(value):", "def work(value):  # noqa: C901")
        self._source(source, "hidden/work.py")
        (self.root / ".gitignore").write_text("hidden/\n", encoding="utf-8")
        (self.root / "pyproject.toml").write_text(
            '[tool.ruff.lint]\nignore = ["C901"]\n[tool.ruff.lint.mccabe]\nmax-complexity = 999\n', encoding="utf-8",
        )
        self._track("hidden/work.py")
        self._write_policy()
        before = self.policy_path.read_bytes()
        error = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(error):
            self.assertEqual(gate.main(("--root", str(self.root))), 1)
        self.assertIn("new complexity debt: hidden/work.py::work (16)", error.getvalue())
        self.assertEqual(self.policy_path.read_bytes(), before)

    def test_operational_exit_malformed_output_and_status_inconsistency_fail(self) -> None:
        self._source(_function_source())
        index = gate.index_functions(self.root, ("work.py",))
        outputs = (
            subprocess.CompletedProcess(("ruff",), 2, "[]", "operational failure"),
            subprocess.CompletedProcess(("ruff",), 0, "not JSON", ""),
            subprocess.CompletedProcess(("ruff",), 0, "{}", ""),
            subprocess.CompletedProcess(("ruff",), 1, "[]", ""),
            self._tool_output(self._diagnostic(), returncode=0),
        )
        for output in outputs:
            with self.subTest(returncode=output.returncode, stdout=output.stdout), self.assertRaises(gate.ComplexityError):
                gate.parse_findings(output, self.root, ("work.py",), index)

    def test_tracked_input_enumeration_and_invalid_source_fail_closed(self) -> None:
        for raw in (b"", b"work.py", b"work.py\0work.py\0", b"../work.py\0", b"\xff.py\0"):
            result = subprocess.CompletedProcess(("git",), 0, raw, b"")
            with mock.patch.object(gate.subprocess, "run", return_value=result):
                with self.subTest(raw=raw), self.assertRaises(gate.ComplexityError):
                    gate.tracked_inputs(self.root)
        self._source("def broken(:\n")
        with self.assertRaisesRegex(gate.ComplexityError, "cannot parse tracked Python source"):
            gate.index_functions(self.root, ("work.py",))
        with mock.patch.object(gate.subprocess, "run", side_effect=OSError("missing executable")):
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                self.assertEqual(gate.main(("--root", str(self.root))), 2)
            self.assertIn("cannot enumerate tracked lint inputs", error.getvalue())
        with mock.patch.object(gate.subprocess, "run", side_effect=subprocess.TimeoutExpired(("ruff",), 120)):
            with self.assertRaisesRegex(gate.ComplexityError, "cannot execute the required complexity command"):
                gate.run_ruff(self.root, ("work.py",))

    def test_command_keeps_the_fixed_threshold_and_every_tracked_input(self) -> None:
        inputs = ("src/example.py", "tests/example.py", "hidden/example.py", "docs/example.md", "example.ipynb")
        command = gate.ruff_command("/chosen/python", inputs)
        self.assertEqual(command[:4], ("/chosen/python", "-m", "ruff", "check"))
        self.assertEqual(command[command.index("--") + 1:], inputs)
        self.assertEqual(command[command.index("--select") + 1], "C90")
        self.assertEqual(command[command.index("--config") + 1], "lint.mccabe.max-complexity=15")
        for required in ("--isolated", "--ignore-noqa", "--no-respect-gitignore", "--no-force-exclude", "--no-cache"):
            self.assertIn(required, command)
        self.assertEqual(gate.LINT_PATTERNS, ("*.py", "*.pyi", "*.pyw", "*.ipynb", "*.md"))

    def test_main_retains_timeout_partial_bytes_and_text_before_invalid_exit(self) -> None:
        self._source(_function_source(complexity=15))
        self._track("work.py")
        self._write_policy()
        before = self.policy_path.read_bytes()
        cases: tuple[tuple[bytes | str | None, bytes | str | None, str, str], ...] = (
            (
                b"partial \xce\xbb\xff", b"warning already terminated\n",
                "partial \u03bb\ufffd\n", "warning already terminated\n",
            ),
            ("partial text already terminated\n", "warning text", "partial text already terminated\n", "warning text\n"),
            (None, b"", "", ""),
        )
        for partial_stdout, partial_stderr, expected_stdout, expected_stderr in cases:
            timeout = subprocess.TimeoutExpired(("ruff",), 120, output=partial_stdout, stderr=partial_stderr)
            enumeration = subprocess.CompletedProcess(("git",), 0, b"work.py\0", b"")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                self.subTest(stdout=partial_stdout, stderr=partial_stderr),
                mock.patch.object(gate.subprocess, "run", side_effect=(enumeration, timeout)) as runner,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(gate.main(("--root", str(self.root))), 2)
                self.assertEqual(runner.call_count, 2)
                self.assertEqual(stdout.getvalue(), expected_stdout)
                self.assertEqual(
                    stderr.getvalue(),
                    expected_stderr
                    + f"Complexity gate invalid: cannot execute the required complexity command: {timeout}\n",
                )
                self.assertEqual(self.policy_path.read_bytes(), before)
                self.assertNotIn("Complexity gate passed", stdout.getvalue())
            with mock.patch.object(gate.subprocess, "run", side_effect=timeout):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(gate.ComplexityError) as caught:
                        gate.run_ruff(self.root, ("work.py",))
                self.assertIs(caught.exception.__cause__, timeout)

    def test_nested_policy_json_returns_invalid_exit_without_executing_ruff(self) -> None:
        self._source(_function_source(complexity=15))
        self._track("work.py")
        depth = sys.getrecursionlimit() * 2
        raw_policy = "[" * depth + "0" + "]" * depth
        decoder_recursion = _json_decoder_raises_recursion(raw_policy)
        self.policy_path.write_text(raw_policy, encoding="utf-8")
        before = self.policy_path.read_bytes()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(gate, "run_ruff") as runner,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(gate.main(("--root", str(self.root))), 2)
        runner.assert_not_called()
        self.assertEqual(stdout.getvalue(), "")
        if decoder_recursion:
            self.assertTrue(stderr.getvalue().startswith(f"Complexity gate invalid: {self.policy_path}: "))
            self.assertIn("recursion", stderr.getvalue().lower())
        else:
            self.assertEqual(stderr.getvalue(), "Complexity gate invalid: complexity policy must be an object\n")
        self.assertEqual(self.policy_path.read_bytes(), before)

    def test_nested_ruff_json_returns_invalid_exit_and_retains_original_output(self) -> None:
        self._source(_function_source(complexity=15))
        self._track("work.py")
        self._write_policy()
        before = self.policy_path.read_bytes()
        depth = sys.getrecursionlimit() * 2
        raw_output = "[" * depth + "0" + "]" * depth
        decoder_recursion = _json_decoder_raises_recursion(raw_output)
        result = subprocess.CompletedProcess(("ruff",), 1, raw_output, "tool stderr\n")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(gate, "run_ruff", return_value=result) as runner,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(gate.main(("--root", str(self.root))), 2)
        runner.assert_called_once_with(self.root, ("work.py",))
        self.assertEqual(stdout.getvalue(), raw_output + "\n")
        if decoder_recursion:
            self.assertTrue(stderr.getvalue().startswith("tool stderr\nComplexity gate invalid: Ruff C901 output: "))
            self.assertIn("recursion", stderr.getvalue().lower())
        else:
            self.assertEqual(stderr.getvalue(), "tool stderr\nComplexity gate invalid: diagnostic must be an object\n")
        self.assertNotIn("Complexity gate passed", stdout.getvalue())
        self.assertEqual(self.policy_path.read_bytes(), before)

    def test_typed_validation_recursion_returns_contextual_invalid_exit(self) -> None:
        self._source(_function_source(complexity=15))
        self._track("work.py")
        self._write_policy()
        before = self.policy_path.read_bytes()
        payload: JsonObject = {"schema_version": 1, "max_complexity": 15, "exceptions": []}
        for stage in ("policy", "tool"):
            failure = RecursionError("typed validation recursion sentinel")
            validation_results = (failure,) if stage == "policy" else (payload, failure)
            result = subprocess.CompletedProcess(("ruff",), 0, "[]", "")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                self.subTest(stage=stage),
                mock.patch.object(gate, "validate_json_value", side_effect=validation_results),
                mock.patch.object(gate, "run_ruff", return_value=result) as runner,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(gate.main(("--root", str(self.root))), 2)
            if stage == "policy":
                runner.assert_not_called()
                self.assertEqual(stdout.getvalue(), "")
                context = str(self.policy_path)
            else:
                runner.assert_called_once_with(self.root, ("work.py",))
                self.assertEqual(stdout.getvalue(), "[]\n")
                context = "Ruff C901 output"
            self.assertEqual(stderr.getvalue(), f"Complexity gate invalid: {context}: {failure}\n")
            self.assertEqual(self.policy_path.read_bytes(), before)

    def test_main_rejects_oversized_tool_decimals_and_retains_raw_output(self) -> None:
        limit = sys.get_int_max_str_digits()
        if limit == 0:
            self.skipTest("CPython decimal-int conversion limit is disabled.")
        self._source(_function_source())
        self._track("work.py")
        self._write_policy()
        before = self.policy_path.read_bytes()
        oversized = "9" * (limit + 1)
        for field in ("score", "threshold"):
            diagnostic = self._diagnostic()
            score = oversized if field == "score" else "16"
            threshold = oversized if field == "threshold" else "15"
            diagnostic["message"] = f"`work` is too complex ({score} > {threshold})"
            result = self._tool_output(diagnostic)
            result.stderr = "retained tool stderr\n"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                self.subTest(field=field),
                mock.patch.object(gate, "run_ruff", return_value=result) as runner,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(gate.main(("--root", str(self.root))), 2)
            runner.assert_called_once_with(self.root, ("work.py",))
            self.assertEqual(stdout.getvalue(), result.stdout + "\n")
            self.assertEqual(
                stderr.getvalue(),
                "retained tool stderr\n"
                "Complexity gate invalid: invalid tool complexity values at work.py:1\n",
            )
            self.assertNotIn("Complexity gate passed", stdout.getvalue())
            self.assertEqual(self.policy_path.read_bytes(), before)

    def test_json_decoder_recursion_returns_contextual_invalid_exit(self) -> None:
        self._source(_function_source(complexity=15))
        self._track("work.py")
        self._write_policy()
        before = self.policy_path.read_bytes()
        payload: JsonObject = {"schema_version": 1, "max_complexity": 15, "exceptions": []}
        for stage in ("policy", "tool"):
            failure = RecursionError("decoder recursion sentinel")
            decoding_results = (failure,) if stage == "policy" else (payload, failure)
            result = subprocess.CompletedProcess(("ruff",), 0, "[]", "decoder stderr\n")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                self.subTest(stage=stage),
                mock.patch.object(gate.json, "loads", side_effect=decoding_results),
                mock.patch.object(gate, "run_ruff", return_value=result) as runner,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(gate.main(("--root", str(self.root))), 2)
            if stage == "policy":
                runner.assert_not_called()
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(stderr.getvalue(), f"Complexity gate invalid: {self.policy_path}: {failure}\n")
            else:
                runner.assert_called_once_with(self.root, ("work.py",))
                self.assertEqual(stdout.getvalue(), "[]\n")
                self.assertEqual(stderr.getvalue(), f"decoder stderr\nComplexity gate invalid: Ruff C901 output: {failure}\n")
            self.assertEqual(self.policy_path.read_bytes(), before)
            with mock.patch.object(gate.json, "loads", side_effect=failure):
                with self.assertRaises(gate.ComplexityError) as caught:
                    if stage == "policy":
                        gate.load_policy(self.policy_path)
                    else:
                        gate.parse_findings(
                            result, self.root, ("work.py",), gate.index_functions(self.root, ("work.py",)),
                        )
            self.assertIs(caught.exception.__cause__, failure)

    def test_named_removal_section_changes_fail_with_the_same_policy_and_scores(self) -> None:
        self._source(_function_source())
        self._track("work.py", "docs/complexity-removal.md")
        self._write_policy((self._record(),))
        before = self.policy_path.read_bytes()
        plan = self.root / "docs/complexity-removal.md"
        result = self._tool_output(self._diagnostic())
        with (
            mock.patch.object(gate, "run_ruff", return_value=result) as runner,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(gate.main(("--root", str(self.root))), 0)
        runner.assert_called_once()
        for content in ("# Renamed Work\nKeep the same responsibility.\n", "# Other\nThe named section was deleted.\n"):
            plan.write_text(content, encoding="utf-8")
            stderr = io.StringIO()
            with (
                self.subTest(content=content),
                mock.patch.object(gate, "run_ruff", return_value=result) as runner,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(gate.main(("--root", str(self.root))), 2)
            runner.assert_not_called()
            self.assertIn("local removal-plan fragment must name an existing anchor", stderr.getvalue())
            self.assertEqual(self.policy_path.read_bytes(), before)

    def test_local_plan_anchors_are_real_outside_fenced_indented_and_comment_code(self) -> None:
        self._source(_function_source())
        self._track("work.py", "docs/complexity-removal.md")
        self._write_policy((self._record(),))
        before = self.policy_path.read_bytes()
        plan = self.root / "docs/complexity-removal.md"
        result = self._tool_output(self._diagnostic())
        valid = ("<a id=\"work\"></a>\n", "<a name='work'></a>\n", "## Work ##\n")
        invalid = (
            "```markdown\n<a id=\"work\"></a>\n# Work\n```\n",
            "~~~markdown\n<a name='work'></a>\n# Work\n~~~\n",
            "    <a id=\"work\"></a>\n\t# Work\n",
            "<!--\n<a id=\"work\"></a>\n# Work\n-->\n",
        )
        for content in (*valid, *invalid):
            plan.write_text(content, encoding="utf-8")
            stderr = io.StringIO()
            with (
                self.subTest(content=content),
                mock.patch.object(gate, "run_ruff", return_value=result) as runner,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(gate.main(("--root", str(self.root))), 0 if content in valid else 2)
            if content in valid:
                runner.assert_called_once()
            else:
                runner.assert_not_called()
                self.assertIn("local removal-plan fragment must name an existing anchor", stderr.getvalue())
            self.assertEqual(self.policy_path.read_bytes(), before)

    def test_tracked_removal_plan_must_remain_readable_utf8(self) -> None:
        self._source(_function_source())
        self._track("work.py", "docs/complexity-removal.md")
        self._write_policy((self._record(),))
        before = self.policy_path.read_bytes()
        plan = self.root / "docs/complexity-removal.md"
        for failure in ("invalid_utf8", "missing", "directory"):
            if plan.is_dir():
                plan.rmdir()
            elif plan.exists():
                plan.unlink()
            if failure == "invalid_utf8":
                plan.write_bytes(b"# Work\n\xff")
            elif failure == "directory":
                plan.mkdir()
            stderr = io.StringIO()
            with (
                self.subTest(failure=failure),
                mock.patch.object(gate, "run_ruff") as runner,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(gate.main(("--root", str(self.root))), 2)
            runner.assert_not_called()
            self.assertIn("local removal plan docs/complexity-removal.md", stderr.getvalue())
            self.assertEqual(self.policy_path.read_bytes(), before)

    def test_ast_parse_and_definition_recursion_return_contextual_invalid_exit(self) -> None:
        self._source(_function_source(complexity=15))
        self._track("work.py")
        self._write_policy()
        before = self.policy_path.read_bytes()
        for stage in ("parse", "index"):
            failure = RecursionError(f"{stage} recursion sentinel")
            target = "scripts.check_complexity.ast.parse" if stage == "parse" else "scripts.check_complexity._definitions"
            stderr = io.StringIO()
            with (
                self.subTest(stage=stage),
                mock.patch(target, side_effect=failure),
                mock.patch.object(gate, "run_ruff") as runner,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(gate.main(("--root", str(self.root))), 2)
            runner.assert_not_called()
            self.assertEqual(stderr.getvalue(), f"Complexity gate invalid: cannot {stage} tracked Python source work.py: {failure}\n")
            with mock.patch(target, side_effect=failure):
                with self.assertRaises(gate.ComplexityError) as caught:
                    gate.index_functions(self.root, ("work.py",))
            self.assertIs(caught.exception.__cause__, failure)
            self.assertEqual(self.policy_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
