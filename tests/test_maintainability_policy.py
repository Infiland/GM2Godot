from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import check_maintainability as checker, maintainability_metrics as metrics


class TestMaintainabilityPolicy(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        (self.root / "src").mkdir()
        (self.root / "requirements-tooling.txt").write_text(
            f"ruff=={metrics.ruff_version(checker.PROJECT_ROOT)}\n", encoding="utf-8"
        )
        self.source = self.root / "src" / "example.py"
        self.baseline = self.root / checker.BASELINE_PATH
        self.write_function(18)
        self.parent = metrics.measure(self.root, ["src/example.py"])
        self.parent_sizes: dict[str, metrics.SizeEvidence] = {}
        self.key = "application|complexity|src/example.py::process"
        self.assertEqual(self.parent, {self.key: 19})
        self.write_baseline(self.parent)

    def write_function(self, branches: int, name: str = "process") -> None:
        body = "".join(f"    if value == {value}:\n        return {value}\n" for value in range(branches))
        self.source.write_text(f"def {name}(value: int) -> int:\n{body}    return value\n", encoding="utf-8")

    def write_baseline(self, debt: metrics.Debt) -> None:
        self.baseline.write_text(checker.serialize(self.root, debt, self.parent_sizes), encoding="utf-8")

    def invoke(self, *, update: bool = False) -> tuple[int, str]:
        output = io.StringIO()
        arguments = ["--baseline", str(self.baseline), "--base-ref", "fixture-parent"]
        if update:
            arguments.append("--update")
        with (
            patch.object(checker, "PROJECT_ROOT", self.root),
            patch.object(checker, "parent_debt", return_value=checker.Baseline(self.parent, self.parent_sizes)),
            redirect_stdout(output),
            redirect_stderr(output),
        ):
            status = checker.main(arguments)
        return status, output.getvalue()

    def test_exact_accepted_baseline_passes_without_writing(self) -> None:
        before = self.baseline.read_bytes()
        status, output = self.invoke()
        self.assertEqual(status, 0, output)
        self.assertIn("1 exact entries", output)
        self.assertEqual(self.baseline.read_bytes(), before)

    def test_increase_fails_even_when_update_requested(self) -> None:
        self.write_function(19)
        before = self.baseline.read_bytes()
        for update in (False, True):
            with self.subTest(update=update):
                status, output = self.invoke(update=update)
                self.assertEqual(status, 1, output)
                self.assertIn(f"{self.key}: measured 20, expected limit 19", output)
                self.assertEqual(self.baseline.read_bytes(), before)

    def test_new_symbol_and_rename_cannot_reuse_an_allowance(self) -> None:
        for keep_old in (True, False):
            with self.subTest(keep_old=keep_old):
                self.write_function(18, "renamed")
                if keep_old:
                    renamed = self.source.read_text(encoding="utf-8")
                    self.write_function(18)
                    self.source.write_text(self.source.read_text(encoding="utf-8") + "\n\n" + renamed, encoding="utf-8")
                status, output = self.invoke(update=True)
                self.assertEqual(status, 1, output)
                self.assertIn("::renamed: measured 19, expected limit 0", output)

    def test_raised_baseline_cannot_bless_growth(self) -> None:
        self.write_function(19)
        self.write_baseline({self.key: 20})
        status, output = self.invoke(update=True)
        self.assertEqual(status, 1, output)
        self.assertIn("measured 20, expected limit 19", output)

    def test_reduction_requires_update_and_cannot_grow_back(self) -> None:
        self.write_function(17)
        status, output = self.invoke()
        self.assertEqual(status, 1, output)
        self.assertIn("recorded limit 19, expected 18; lower/remove with --update", output)
        status, output = self.invoke(update=True)
        self.assertEqual(status, 0, output)
        lowered = checker.load_baseline(self.baseline.read_text(encoding="utf-8"), checker.policy(self.root)).debt
        self.assertEqual(lowered, {self.key: 18})
        self.assertEqual(self.invoke()[0], 0)
        self.write_function(18)
        status, output = self.invoke(update=True)
        self.assertEqual(status, 1, output)
        self.assertIn("measured 19, expected limit 18", output)
        # The next change reads the lowered value from its parent, even if the
        # candidate rewrites its own baseline back to the old allowance.
        self.parent = lowered
        self.write_baseline({self.key: 19})
        self.assertEqual(self.invoke()[0], 1)

    def test_deletion_requires_removal_and_recreation_fails(self) -> None:
        self.source.unlink()
        status, output = self.invoke()
        self.assertEqual(status, 1, output)
        self.assertIn("recorded limit 19, expected 0", output)
        self.assertEqual(self.invoke(update=True)[0], 0)
        self.parent = {}
        self.write_function(18)
        status, output = self.invoke(update=True)
        self.assertEqual(status, 1, output)
        self.assertIn("measured 19, expected limit 0", output)

    def test_reaching_threshold_removes_the_exception(self) -> None:
        self.write_function(metrics.THRESHOLDS["complexity"] - 1)
        self.assertEqual(self.invoke(update=True)[0], 0)
        self.assertEqual(
            checker.load_baseline(self.baseline.read_text(encoding="utf-8"), checker.policy(self.root)).debt, {}
        )
        self.write_function(metrics.THRESHOLDS["complexity"])
        status, output = self.invoke()
        self.assertEqual(status, 1, output)
        self.assertIn("measured 16, expected limit 0", output)

    def test_missing_baseline_needs_deliberate_initialization(self) -> None:
        self.baseline.unlink()
        status, output = self.invoke()
        self.assertEqual(status, 2, output)
        self.assertIn("missing baseline", output)
        self.assertEqual(self.invoke(update=True)[0], 0)

    def test_noncanonical_json_requires_update(self) -> None:
        self.baseline.write_text(json.dumps(json.loads(self.baseline.read_text(encoding="utf-8"))), encoding="utf-8")
        status, output = self.invoke()
        self.assertEqual(status, 1, output)
        self.assertIn("canonical sorted JSON", output)
        self.assertEqual(self.invoke(update=True)[0], 0)

    def test_unknown_python_path_fails_closed(self) -> None:
        (self.root / "unclassified.py").write_text("value = 1\n", encoding="utf-8")
        status, output = self.invoke()
        self.assertEqual(status, 2, output)
        self.assertIn("unknown Python classification: unclassified.py", output)

    def test_working_inventory_includes_tracked_ignored_and_new_python(self) -> None:
        ignored = self.root / "src" / "ignored.py"
        ignored.write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "src/ignored.py"], check=True)
        (self.root / ".gitignore").write_text("src/ignored.py\n", encoding="utf-8")
        self.assertEqual(checker.working_paths(self.root), ["src/example.py", "src/ignored.py"])

    def test_malformed_baseline_and_policy_changes_fail_closed(self) -> None:
        valid = {"schema_version": checker.SCHEMA_VERSION, "policy": checker.policy(self.root), "debt": self.parent, "size_evidence": {}}
        malformed: list[object] = [
            [],
            {},
            {**valid, "extra": 1},
            {**valid, "schema_version": True},
            {**valid, "schema_version": 99},
            {**valid, "policy": {}},
            {**valid, "debt": []},
        ]
        malformed.extend({**valid, "debt": {self.key: value}} for value in (0, -1, True, 1.5, "19"))
        for name, value in (("line_length", 88), ("combine_as_imports", False), ("split_on_trailing_comma", True)):
            changed = {**checker.policy(self.root), "import_layout": {**metrics.IMPORT_LAYOUT, name: value}}
            malformed.append({**valid, "policy": changed})
        for payload in malformed:
            with self.subTest(payload=payload):
                with self.assertRaises(metrics.MaintainabilityError):
                    checker.load_baseline(json.dumps(payload), checker.policy(self.root))
        for raw in ("{", '{"debt": {}, "debt": {}}'):
            with self.subTest(raw=raw):
                self.baseline.write_text(raw, encoding="utf-8")
                status, output = self.invoke()
                self.assertEqual(status, 2, output)

    def test_policy_records_the_executed_rules_and_thresholds(self) -> None:
        policy = checker.policy(self.root)
        self.assertEqual(policy["lint_rules"], list(metrics.LINT_RULES))
        self.assertEqual(policy["thresholds"], metrics.THRESHOLDS)
        self.assertEqual(
            policy["import_layout"], {"line_length": 120, "combine_as_imports": True, "split_on_trailing_comma": False}
        )
        with patch.object(checker, "LINT_RULES", ("C901",)):
            status, output = self.invoke(update=True)
        self.assertEqual(status, 2, output)
        self.assertIn("policy/version mismatch", output)

    def test_real_ruff_import_layout_preserves_wide_and_combined_imports(self) -> None:
        for source in (
            "from package_name import first_export_with_a_lengthy_name, second_export_with_a_lengthy_name\n",
            "from module import first as first, second as second\n",
        ):
            with self.subTest(source=source):
                self.source.write_text(source, encoding="utf-8")
                self.assertEqual(metrics.run_ruff(self.root, ["src/example.py"]), [])
        self.source.write_text("from module import (\n    first,\n    second,\n)\n", encoding="utf-8")
        findings = metrics.run_ruff(self.root, ["src/example.py"])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["code"], "I001")
        self.source.write_text("from module import first, second\n", encoding="utf-8")
        self.assertEqual(metrics.run_ruff(self.root, ["src/example.py"]), [])

    def size_parent(self, source: str) -> None:
        self.source.write_text(source, encoding="utf-8")
        measured = checker.measured_baseline(self.root, ["src/example.py"])
        self.parent, self.parent_sizes = measured.debt, measured.sizes
        self.write_baseline(self.parent)

    def test_same_ast_packing_cannot_lower_or_remove_physical_allowances(self) -> None:
        cases = (
            "def process():\n    return [\n" + "        1,\n" * 160 + "    ]\n",
            "def process():\n    return consume(\n" + "        1,\n" * 160 + "    )\n",
            "values = [\n" + "    1,\n" * 810 + "]\n",
            "# explanation\n" * 810 + "value = 1\n",
        )
        for source in cases:
            with self.subTest(source=source[:30]):
                self.size_parent(source)
                packed = source.replace("\n        ", " ").replace("\n    ", " ").replace("# explanation\n", "")
                self.source.write_text(packed, encoding="utf-8")
                self.assertEqual(self.invoke()[0], 1)
                status, output = self.invoke(update=True)
                self.assertEqual(status, 0, output)
                accepted = checker.load_baseline(self.baseline.read_text(encoding="utf-8"), checker.policy(self.root))
                for key in checker.physical_size_keys(self.parent):
                    self.assertEqual(accepted.debt[key], self.parent[key])
                    self.assertLess(accepted.sizes[key].lines, self.parent_sizes[key].lines)
                # A real next commit loads the packed physical count along with
                # the retained allowance; the second transition must retain it.
                self.parent, self.parent_sizes = accepted.debt, accepted.sizes
                self.assertEqual(self.invoke()[0], 0)
                self.assertEqual(self.invoke(update=True)[0], 0)
                self.assertEqual(
                    checker.load_baseline(self.baseline.read_text(encoding="utf-8"), checker.policy(self.root)).debt,
                    accepted.debt,
                )

    def test_ast_change_without_structural_reduction_does_not_bless_packing(self) -> None:
        self.size_parent("def process():\n    return [\n" + "        1,\n" * 160 + "    ]\n")
        self.source.write_text("def process():\n    pass\n    return [" + "1, " * 160 + "]\n", encoding="utf-8")
        status, output = self.invoke(update=True)
        self.assertEqual(status, 1, output)
        self.assertIn("function_structure", output)

    def test_real_size_reduction_updates_evidence_and_cannot_regrow(self) -> None:
        self.size_parent("def process():\n    return [\n" + "        1,\n" * 160 + "    ]\n")
        smaller = "def process():\n    return [\n" + "        1,\n" * 155 + "    ]\n"
        self.source.write_text(smaller, encoding="utf-8")
        status, output = self.invoke(update=True)
        self.assertEqual(status, 0, output)
        self.assertEqual(self.invoke()[0], 0)
        accepted = checker.load_baseline(self.baseline.read_text(encoding="utf-8"), checker.policy(self.root))
        self.parent, self.parent_sizes = accepted.debt, accepted.sizes
        self.source.write_text(smaller.replace("    ]", "        1,\n    ]"), encoding="utf-8")
        status, output = self.invoke(update=True)
        self.assertEqual(status, 1, output)
        self.assertIn("expected limit", output)

    def test_forged_candidate_size_evidence_cannot_override_parent(self) -> None:
        self.size_parent("def process():\n    return [\n" + "        1,\n" * 160 + "    ]\n")
        self.source.write_text("def process():\n    return [" + "1, " * 160 + "]\n", encoding="utf-8")
        packed = checker.measured_baseline(self.root, ["src/example.py"])
        self.baseline.write_text(checker.serialize(self.root, packed.debt, packed.sizes), encoding="utf-8")
        status, output = self.invoke(update=True)
        self.assertEqual(status, 1, output)
        self.assertIn("function_lines", output)
        self.assertIn("expected limit 0", output)

    def test_suppression_removal_keeps_honest_physical_and_retained_line_counts(self) -> None:
        source = "# pyright: reportPrivateUsage=false\n" + "# documentation\n" * 888 + "value = 1\n"
        self.size_parent(source)
        self.source.write_text(source.split("\n", 1)[1], encoding="utf-8")
        status, output = self.invoke(update=True)
        self.assertEqual(status, 0, output)
        accepted = checker.load_baseline(self.baseline.read_text(encoding="utf-8"), checker.policy(self.root))
        key = "application|module_lines.executable|src/example.py::<module>"
        self.assertEqual(accepted.debt, {key: 890})
        self.assertEqual(accepted.sizes[key].lines, 889)
        self.parent, self.parent_sizes = accepted.debt, accepted.sizes
        self.assertEqual(self.invoke()[0], 0)
        self.source.unlink()
        self.assertEqual(self.invoke(update=True)[0], 0)
        self.assertEqual(
            checker.load_baseline(self.baseline.read_text(encoding="utf-8"), checker.policy(self.root)).debt, {}
        )

    def test_packed_relocation_cannot_use_removed_owner_allowance(self) -> None:
        self.size_parent("def process():\n    return [\n" + "        1,\n" * 160 + "    ]\n")
        self.source.unlink()
        (self.root / "src" / "destination.py").write_text(
            "def process():\n    return [" + "1, " * 160 + "]\n", encoding="utf-8"
        )
        status, output = self.invoke(update=True)
        self.assertEqual(status, 1, output)
        self.assertIn("function_structure|src/destination.py::process", output)
        self.assertIn("expected limit 0", output)

    def test_size_evidence_is_strictly_validated(self) -> None:
        self.size_parent("def process():\n    return [\n" + "        1,\n" * 160 + "    ]\n")
        valid = json.loads(self.baseline.read_text(encoding="utf-8"))
        key = next(iter(valid["size_evidence"]))
        for field, value in (("lines", True), ("lines", -1), ("structure", -1), ("structure", True), ("ast_sha256", "x")):
            with self.subTest(field=field, value=value):
                changed = json.loads(json.dumps(valid))
                changed["size_evidence"][key][field] = value
                with self.assertRaises(metrics.MaintainabilityError):
                    checker.load_baseline(json.dumps(changed), checker.policy(self.root))
        malformed_evidence: tuple[object, ...] = ({}, {**valid["size_evidence"], "unknown": {}})
        for evidence in malformed_evidence:
            with self.subTest(evidence=evidence), self.assertRaises(metrics.MaintainabilityError):
                checker.load_baseline(json.dumps({**valid, "size_evidence": evidence}), checker.policy(self.root))

    def test_one_removed_statement_cannot_retire_a_packed_allowance(self) -> None:
        source = "def process():\n    pass\n    return [\n" + "        1,\n\n" * 80 + "    ]\n"
        self.size_parent(source)
        self.source.write_text("def process():\n    return [" + "1, " * 80 + "]\n", encoding="utf-8")
        status, output = self.invoke(update=True)
        self.assertEqual(status, 0, output)
        accepted = checker.load_baseline(self.baseline.read_text(encoding="utf-8"), checker.policy(self.root))
        key = "application|function_lines|src/example.py::process"
        self.assertEqual(accepted.debt[key], 163)
        self.assertEqual(accepted.sizes[key].lines, 2)
        self.parent, self.parent_sizes = accepted.debt, accepted.sizes
        self.assertEqual(self.invoke()[0], 0)
        self.source.write_text("def process():\n    pass\n    return [" + "1, " * 80 + "]\n", encoding="utf-8")
        before = self.baseline.read_bytes()
        status, output = self.invoke(update=True)
        self.assertEqual(status, 1, output)
        self.assertIn("expected limit 163", output)
        self.assertEqual(self.baseline.read_bytes(), before)
