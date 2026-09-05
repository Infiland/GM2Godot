from __future__ import annotations

import ast
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import check_maintainability as checker, maintainability_metrics as metrics
from scripts.maintainability_imports import build_graphs, elementary_cycles


class TestMaintainabilityMeasurements(unittest.TestCase):
    def test_module_thresholds_and_declarative_classification(self) -> None:
        cases = (
            ("src/example.py", "application", "module_lines", "executable"),
            ("scripts/example.py", "tooling", "module_lines", "executable"),
            ("tests/example.py", "tests", "test_module_lines", "executable"),
            ("src/conversion/gml_transpiler_parts/gml_api_manifest.py", "application", "module_lines", "declarative"),
            ("src/conversion/gml_transpiler_parts/constants.py", "application", "module_lines", "mixed"),
        )
        for path, group, limit_name, kind in cases:
            with self.subTest(path=path):
                limit = metrics.THRESHOLDS[limit_name]
                self.assertEqual(metrics.size_debt(path, "# line\n" * limit, []), {})
                self.assertEqual(
                    metrics.size_debt(path, "# line\n" * (limit + 1), []),
                    {metrics.metric_key(group, f"module_lines.{kind}", path): limit + 1},
                )

    def test_nested_async_qualified_symbols_and_duplicate_names(self) -> None:
        source = "class Owner:\n    async def process(self):\n        def inner():\n            pass\n        def inner():\n            pass\n"
        found = metrics.symbols(ast.parse(source))
        self.assertEqual(
            [symbol.name for symbol in found], ["Owner", "Owner.process", "Owner.process.inner", "Owner.process.inner"]
        )
        debt = metrics.size_debt("src/example.py", source, found)
        self.assertEqual(debt, {"application|duplicate_symbol|src/example.py::Owner.process.inner": 2})
        self.assertEqual(metrics.owner_at(found, 4), "Owner.process.inner")

    def test_function_length_parameters_and_nesting(self) -> None:
        for path, group, limit_name in (
            ("src/example.py", "application", "function_lines"),
            ("tests/example.py", "tests", "test_function_lines"),
        ):
            with self.subTest(path=path):
                limit = metrics.THRESHOLDS[limit_name]
                source = "async def process(a, b, /, c, d, *args, e, f, g, **kwargs):\n" + "    pass\n" * limit
                debt = metrics.size_debt(path, source, metrics.symbols(ast.parse(source)))
                self.assertEqual(debt[metrics.metric_key(group, "function_lines", path, "process")], limit + 1)
                self.assertEqual(debt[metrics.metric_key(group, "parameters", path, "process")], 9)
        source = (
            "def process():\n"
            + "".join("    " * level + "if True:\n" for level in range(1, 6))
            + "                        pass\n"
        )
        debt = metrics.size_debt("src/example.py", source, metrics.symbols(ast.parse(source)))
        self.assertEqual(debt, {"application|nesting|src/example.py::process": 5})

    def test_comments_track_exact_suppressions_but_not_literals(self) -> None:
        source = 'text = "# noqa"\n# pyright: reportPrivateUsage=false\ndef process():\n    pass  # noqa: B001\n'
        found = metrics.symbols(ast.parse(source))
        self.assertEqual(
            metrics.suppression_debt("src/example.py", source, found),
            {
                "application|suppression|src/example.py::<module>|# pyright: reportPrivateUsage=false": 1,
                "application|suppression|src/example.py::process|# noqa: B001": 1,
            },
        )
        broader = source.replace("# noqa: B001", "# noqa")
        violations = checker.violations(
            metrics.suppression_debt("src/example.py", broader, found),
            metrics.suppression_debt("src/example.py", source, found),
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("expected limit 0", violations[0])

    def test_pinned_ruff_measures_all_rules_despite_ignores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "requirements-tooling.txt").write_text(
                f"ruff=={metrics.ruff_version(checker.PROJECT_ROOT)}\n", encoding="utf-8"
            )
            (root / "pyproject.toml").write_text('[tool.ruff.lint]\nignore = ["ALL"]\n', encoding="utf-8")
            (root / ".gitignore").write_text("src/\n", encoding="utf-8")
            source = (
                "import sys\nimport os\n\n\ndef process(value: int) -> int:\n"
                + "".join(f"    if value == {value}:\n        return {value}\n" for value in range(15))
                + "    return value  # noqa\n\n\ndef defaults(values=[]):\n    return values\n\n\nimport math  # noqa\n"
                + "handler = lambda: 1\nfor l in ():\n    pass\n"
            )
            (root / "src" / "example.py").write_text(source, encoding="utf-8")
            paths = ["src/example.py"]
            debt = metrics.measure(root, paths)
            for metric in ("complexity", "lint.I001", "lint.B006", "lint.E402", "lint.E731", "lint.E741"):
                with self.subTest(metric=metric):
                    self.assertTrue(any(f"|{metric}|" in key for key in debt), debt)
            (root / "src" / "empty.py").write_text("", encoding="utf-8")
            self.assertEqual(
                metrics.measure(root, [*paths, "src/empty.py"]), metrics.measure(root, ["src/empty.py", *paths])
            )
            (root / "requirements-tooling.txt").write_text("ruff==0.0.0\n", encoding="utf-8")
            with self.assertRaisesRegex(metrics.MaintainabilityError, "Ruff version: expected ruff 0.0.0"):
                metrics.measure(root, paths)

    def test_project_config_enforces_complete_e4_e7_families(self) -> None:
        source = (
            "import sys, os\nprint(sys.version, os.name)\nimport math\n"
            "handler = lambda: math.pi\nif handler(): result = 1\nfor l in (): print(l)\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-m", "ruff", "check", "--config", str(checker.PROJECT_ROOT / "pyproject.toml"),
                 "--output-format", "concise", "--stdin-filename", "contract_input.py", "-"],
                input=source, text=True, capture_output=True, cwd=directory,
            )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(set(re.findall(r": (E\d{3}) ", result.stdout)), {"E401", "E402", "E701", "E731", "E741"})

    def test_embedded_suppressions_are_tracked_without_matching_strings(self) -> None:
        for directive in ("noqa: F401", "ruff: noqa: F401", "pyright: ignore[reportUnusedImport]", "type: ignore"):
            with self.subTest(directive=directive):
                source = f'import os  # justification # {directive}\ntext = "# {directive}"\n'
                found = metrics.symbols(ast.parse(source))
                debt = metrics.suppression_debt("src/example.py", source, found)
                self.assertTrue(debt, directive)
                self.assertEqual(sum(debt.values()), 1)
                self.assertIn(directive, next(iter(debt)))

    def test_packed_literals_and_calls_keep_structural_size_debt(self) -> None:
        for expression in ("[{items}]", "consume({items})", "({items},)", "{{{pairs}}}"):
            with self.subTest(expression=expression):
                expanded = expression.format(
                    items=",\n        ".join(str(value) for value in range(160)),
                    pairs=",\n        ".join(f"{value}: {value}" for value in range(160)),
                )
                source = f"def process():\n    return {expanded}\n"
                packed = source.replace("\n        ", " ")
                self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(packed)))
                key = "application|function_structure|src/example.py::process"
                before = metrics.size_debt("src/example.py", source, metrics.symbols(ast.parse(source)))
                after = metrics.size_debt("src/example.py", packed, metrics.symbols(ast.parse(packed)))
                self.assertGreater(before.get(key, 0), metrics.THRESHOLDS["function_lines"])
                self.assertEqual(after.get(key), before[key])

    def test_new_packed_destination_still_has_module_debt(self) -> None:
        source = "values = [" + ", ".join(str(value) for value in range(810)) + "]\n"
        for path, group in (("src/moved.py", "application"), ("scripts/moved.py", "tooling")):
            with self.subTest(path=path):
                debt = metrics.size_debt(path, source, metrics.symbols(ast.parse(source)))
                self.assertGreater(
                    debt.get(metrics.metric_key(group, "module_structure.executable", path), 0),
                    metrics.THRESHOLDS["module_lines"],
                )

    def test_packed_expression_operations_keep_destination_size_debt(self) -> None:
        expressions = (
            " + ".join(["value"] * 175),
            " and ".join(["value"] * 175),
            " < ".join(["value"] * 175),
            "value" + ".field" * 175,
            "value" + "[0]" * 175,
            "[value " + "for value in values " * 175 + "]",
        )
        for expression in expressions:
            with self.subTest(expression=expression[:40]):
                source = f"def process(value, values):\n    return {expression}\n"
                path = "src/destination.py"
                debt = metrics.size_debt(path, source, metrics.symbols(ast.parse(source)))
                self.assertGreater(debt.get(metrics.metric_key("application", "function_structure", path, "process"), 0), 150)

    def test_escaped_multiline_payload_keeps_destination_size_debt(self) -> None:
        for payload in ("generated text\n" * 175, b"generated bytes\n" * 175):
            with self.subTest(payload_type=type(payload).__name__):
                packed = f"def render():\n    return {payload!r}\n"
                path = "src/destination.py"
                debt = metrics.size_debt(path, packed, metrics.symbols(ast.parse(packed)))
                self.assertGreater(debt.get(metrics.metric_key("application", "function_structure", path, "render"), 0), 150)

    def test_ruff_failure_does_not_appear_as_debt_reduction(self) -> None:
        with patch.object(metrics.subprocess, "run") as run:
            run.return_value.returncode = 2
            run.return_value.stdout = f"ruff {metrics.ruff_version(checker.PROJECT_ROOT)}"
            run.return_value.stderr = "measurement failure"
            with self.assertRaisesRegex(metrics.MaintainabilityError, "Ruff measurement failed"):
                metrics.run_ruff(checker.PROJECT_ROOT, ["main.py"])


class TestMaintainabilityImports(unittest.TestCase):
    @staticmethod
    def graphs(sources: dict[str, str]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        return build_graphs({path: ast.parse(source) for path, source in sources.items()})

    def test_static_graph_includes_deferred_and_type_only_imports(self) -> None:
        sources = {
            "src/a.py": "from typing import TYPE_CHECKING as TC\nif TC:\n    from . import b\nasync def call():\n    import c\n",
            "src/b.py": "from . import a\n",
            "src/c.py": "from . import a\n",
        }
        static, eager = self.graphs(sources)
        self.assertEqual(elementary_cycles(static), [("src/a.py", "src/b.py"), ("src/a.py", "src/c.py")])
        self.assertEqual(elementary_cycles(eager), [])

    def test_unrelated_type_checking_attribute_is_eager(self) -> None:
        sources = {"src/a.py": "if settings.TYPE_CHECKING:\n    import b\n", "src/b.py": "import a\n"}
        static, eager = self.graphs(sources)
        self.assertEqual(static, eager)
        self.assertEqual(elementary_cycles(eager), [("src/a.py", "src/b.py")])

    def test_typing_alias_negation_only_defers_the_type_branch(self) -> None:
        static, eager = self.graphs(
            {
                "src/a.py": "import typing as t\nif not t.TYPE_CHECKING:\n    import b\nelse:\n    import c\n",
                "src/b.py": "",
                "src/c.py": "",
            }
        )
        self.assertEqual(static["src/a.py"], {"src/b.py", "src/c.py"})
        self.assertEqual(eager["src/a.py"], {"src/b.py"})

    def test_dotted_import_executes_package_initializers(self) -> None:
        static, eager = self.graphs(
            {
                "src/pkg/__init__.py": "from .. import other\n",
                "src/pkg/child.py": "",
                "src/other.py": "import pkg.child\n",
            }
        )
        self.assertEqual(static, eager)
        self.assertEqual(elementary_cycles(eager), [("src/other.py", "src/pkg/__init__.py")])

    def test_literal_dynamic_imports_aliases_and_reexports_are_included(self) -> None:
        static, eager = self.graphs(
            {
                "src/a.py": "from importlib import import_module as load\nload('.b', 'src')\n",
                "src/b.py": "import importlib as loader\nloader.import_module(name='c')\n",
                "src/c.py": "__import__('a')\n",
            }
        )
        self.assertEqual(static, eager)
        self.assertEqual(elementary_cycles(static), [("src/a.py", "src/b.py", "src/c.py")])

    def test_cycle_growth_inside_existing_component_changes_identity(self) -> None:
        before = {"a": {"b"}, "b": {"c"}, "c": {"a"}}
        after = {**before, "b": {"a", "c"}}
        self.assertEqual(elementary_cycles(before), [("a", "b", "c")])
        self.assertEqual(elementary_cycles(after), [("a", "b"), ("a", "b", "c")])
        reversed_graph = dict(reversed(list(after.items())))
        self.assertEqual(elementary_cycles(after), elementary_cycles(reversed_graph))

    def test_function_defaults_execute_but_body_is_deferred(self) -> None:
        static, eager = self.graphs(
            {
                "src/a.py": "def call(value=__import__('b')):\n    __import__('c')\n",
                "src/b.py": "",
                "src/c.py": "",
            }
        )
        self.assertEqual(static["src/a.py"], {"src/b.py", "src/c.py"})
        self.assertEqual(eager["src/a.py"], {"src/b.py"})


class TestMaintainabilityParent(unittest.TestCase):
    def test_packed_allowance_survives_next_real_git_parent_then_owner_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / "src").mkdir()
            (root / "requirements-tooling.txt").write_text(
                f"ruff=={metrics.ruff_version(checker.PROJECT_ROOT)}\n", encoding="utf-8"
            )
            source = root / "src/example.py"
            source.write_text("def process():\n    return [\n" + "        1,\n" * 160 + "    ]\n", encoding="utf-8")
            measured = checker.measured_baseline(root, ["src/example.py"])
            baseline = root / checker.BASELINE_PATH
            baseline.write_text(checker.serialize(root, measured.debt, measured.sizes), encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            commit = ["git", "-C", str(root), "-c", "user.name=Policy test", "-c", "user.email=policy@example.invalid"]
            subprocess.run([*commit, "commit", "--quiet", "-m", "Original size debt"], check=True)
            source.write_text("def process():\n    return [" + "1, " * 160 + "]\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(checker.check(root, baseline, "HEAD", True), 0, output.getvalue())
                subprocess.run(["git", "-C", str(root), "add", "."], check=True)
                subprocess.run([*commit, "commit", "--quiet", "-m", "Pack without retiring debt"], check=True)
                parent = checker.parent_debt(root, "HEAD")
                key = "application|function_lines|src/example.py::process"
                self.assertEqual(parent.debt[key], 163)
                self.assertEqual(parent.sizes[key].lines, 2)
                self.assertEqual(checker.check(root, baseline, "HEAD", False), 0, output.getvalue())
                self.assertEqual(checker.check(root, baseline, "HEAD", True), 0, output.getvalue())
                source.unlink()
                self.assertEqual(checker.check(root, baseline, "HEAD", True), 0, output.getvalue())
            self.assertEqual(checker.load_baseline(baseline.read_text(encoding="utf-8"), checker.policy(root)).debt, {})

    def test_parent_baseline_is_loaded_from_resolved_git_revision(self) -> None:
        root = checker.PROJECT_ROOT
        revision = "a" * 40
        debt = {"application|complexity|src/example.py::process": 19}
        with patch.object(
            checker,
            "git",
            side_effect=[
                revision.encode(),
                b"",
                checker.BASELINE_PATH.encode(),
                checker.serialize(root, debt).encode(),
            ],
        ) as git_call:
            self.assertEqual(checker.parent_debt(root, "parent").debt, debt)
        self.assertEqual(git_call.call_args_list[-1].args, (root, "show", f"{revision}:{checker.BASELINE_PATH}"))

    def test_legacy_import_layout_candidates_and_git_parents_are_rejected(self) -> None:
        root = checker.PROJECT_ROOT
        revision = "a" * 40
        legacy_policy = checker.policy(root)
        legacy_policy.pop("import_layout")
        raw = json.dumps({"schema_version": 2, "policy": legacy_policy, "debt": {}, "size_evidence": {}}).encode()
        with self.assertRaisesRegex(metrics.MaintainabilityError, "policy/version mismatch"):
            checker.load_baseline(raw.decode(), checker.policy(root))
        with (
            patch.object(checker, "git", side_effect=[revision.encode(), b"", checker.BASELINE_PATH.encode(), raw]),
            self.assertRaisesRegex(metrics.MaintainabilityError, "policy/version mismatch"),
        ):
            checker.parent_debt(root, "parent")

    def test_missing_parent_baseline_only_bootstraps_one_fixed_commit(self) -> None:
        for revision in (checker.BOOTSTRAP_REF, "a" * 40):
            with (
                self.subTest(revision=revision),
                patch.object(checker, "git", side_effect=[revision.encode(), b"", b""]),
                patch.object(checker, "bootstrap_debt", return_value=checker.Baseline({}, {})) as bootstrap,
            ):
                if revision == checker.BOOTSTRAP_REF:
                    self.assertEqual(checker.parent_debt(checker.PROJECT_ROOT, "parent").debt, {})
                    bootstrap.assert_called_once_with(checker.PROJECT_ROOT, revision)
                else:
                    with self.assertRaisesRegex(metrics.MaintainabilityError, "missing maintainability-baseline"):
                        checker.parent_debt(checker.PROJECT_ROOT, "parent")
                    bootstrap.assert_not_called()

    def test_nonancestor_and_unknown_git_revisions_fail_closed(self) -> None:
        for responses in (
            [metrics.MaintainabilityError("unknown revision")],
            [b"a" * 40, metrics.MaintainabilityError("not ancestor")],
        ):
            with self.subTest(responses=responses), patch.object(checker, "git", side_effect=responses):
                with self.assertRaises(metrics.MaintainabilityError):
                    checker.parent_debt(checker.PROJECT_ROOT, "parent")

    def test_bootstrap_measures_archived_sources_without_executing_them(self) -> None:
        archive = io.BytesIO()
        sources = {
            "src/example.py": b'raise RuntimeError("never import me")\n',
            "requirements-tooling.txt": f"ruff=={metrics.ruff_version(checker.PROJECT_ROOT)}\n".encode(),
        }
        with tarfile.open(fileobj=archive, mode="w") as contents:
            for name, source in sources.items():
                member = tarfile.TarInfo(name)
                member.size = len(source)
                contents.addfile(member, io.BytesIO(source))
        with patch.object(checker, "git", side_effect=[b"src/example.py\0", archive.getvalue()]):
            self.assertEqual(checker.bootstrap_debt(checker.PROJECT_ROOT, "fixture").debt, {})

    def test_python_inventory_sorts_deduplicates_and_rejects_unsafe_paths(self) -> None:
        self.assertEqual(checker.python_paths(b"src/b.py\0src/a.py\0src/b.py\0README.md\0"), ["src/a.py", "src/b.py"])
        for raw in (b"/absolute.py\0", b"../escape.py\0"):
            with self.subTest(raw=raw), self.assertRaises(metrics.MaintainabilityError):
                checker.python_paths(raw)


class TestMaintainabilityWorkflow(unittest.TestCase):
    def test_ci_compares_with_event_parent_and_keeps_existing_lint_checks(self) -> None:
        workflow = (checker.PROJECT_ROOT / ".github/workflows/code-health.yml").read_text(encoding="utf-8")
        for required in (
            "fetch-depth: 0",
            "github.event.pull_request.base.sha",
            "github.event.pull_request.head.sha",
            "github.event.before",
            'git merge-base "$PR_BASE_SHA" "$PR_HEAD_SHA"',
            'base_ref="$PUSH_BASE_SHA"',
            '--baseline maintainability-baseline.json --base-ref "$base_ref"',
            "python -m unittest tests.test_maintainability_policy",
            "python -m ruff check .",
            "--line-length 120",
            "--config lint.isort.combine-as-imports=true",
            "--config lint.isort.split-on-trailing-comma=false",
            "--select E4,E7,E9,F,I --ignore-noqa --no-respect-gitignore --no-force-exclude",
        ):
            with self.subTest(required=required):
                self.assertIn(required, workflow)
