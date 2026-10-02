from __future__ import annotations

import json
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from typing import cast

from src.conversion.project_godot import MANAGED_OUTPUT_DIRECTORIES
from src.version import get_version


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WIKI_SOURCE_DIR = PROJECT_ROOT / "docs" / "wiki"
WORKFLOW_DIR = PROJECT_ROOT / ".github" / "workflows"
WIKI_PAGES = {
    "Home.md",
    "Installation.md",
    "Quick-Start-Conversion.md",
    "Compatibility-and-Limitations.md",
    "Diagnostics-and-Troubleshooting.md",
    "Generated-Project-and-Runtime.md",
    "Contributing-and-Testing.md",
    "Maintainer-Release-and-Wiki.md",
}
WORKFLOW_USES_PATTERN = re.compile(
    r"^\s*(?:-\s*)?(?P<key_quote>['\"]?)uses(?P=key_quote)\s*:"
    r"\s*(?P<value>.*?)\s*$"
)
YAML_BLOCK_SCALAR_PATTERN = re.compile(
    r"^(?P<indent> *)(?:-\s*)?[^#\n]+:\s*[>|][1-9+-]*"
    r"\s*(?:#.*)?$"
)
FLOW_STYLE_USES_PATTERN = re.compile(
    r"\{[^{}]*?(?:['\"]uses['\"]|uses)\s*:"
    r"\s*(?P<value>[^,}]+)"
)
PINNED_EXTERNAL_ACTION_PATTERN = re.compile(
    r"^(?P<quote>['\"]?)"
    r"(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
    r"(?:/[A-Za-z0-9_.-]+)*)"
    r"@(?P<sha>[0-9a-fA-F]{40})(?P=quote)"
    r"\s+#\s*"
    r"(?P<version>v(?P<major>0|[1-9]\d*)"
    r"\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)"
    r"\s*$"
)
APPROVED_NODE24_ACTION_MAJORS = {
    "actions/checkout": 7,
    "actions/setup-python": 7,
    "actions/setup-node": 7,
    "actions/cache": 5,
    "actions/upload-artifact": 7,
    "actions/download-artifact": 8,
    "softprops/action-gh-release": 3,
}
EXPECTED_RUFF_CONFIG: dict[str, object] = {
    "target-version": "py312",
    "line-length": 120,
    "extend-exclude": ["build", "dist", "release", "venv"],
    "lint": {"select": ["E7", "E9", "F"]},
}
EXPECTED_RUFF_LINT_STEPS = """\
      - name: Run Ruff
        run: python -m ruff check .

      - name: Run Ruff on every tracked lint input
        run: |
          git ls-files -z -- '*.py' '*.pyi' '*.pyw' '*.ipynb' '*.md' |
            xargs -0 -- python -m ruff check --isolated --target-version py312 \\
              --select E7,E9,F --ignore-noqa --no-respect-gitignore --no-force-exclude --
"""


class TestDocumentationHealth(unittest.TestCase):
    def test_readme_describes_transpiler_runtime_reports_and_limits(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        required_phrases = (
            "GML-to-GDScript transpiler",
            "Generated Runtime",
            "Diagnostics and Reports",
            "compatibility reports",
            "A perfect 1:1 conversion tool",
            "--fail-on-unsupported",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)

    def test_contributing_documents_extension_points(self) -> None:
        contributing = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

        required_headings = (
            "### Conversion Architecture",
            "### GML API Support",
            "### Runtime Segments",
            "### Resource Converters",
            "### Event Mappings",
            "### Fixtures",
        )
        for heading in required_headings:
            with self.subTest(heading=heading):
                self.assertIn(heading, contributing)

    def test_reviewable_wiki_source_is_complete_and_versioned(self) -> None:
        self.assertEqual(
            {path.name for path in WIKI_SOURCE_DIR.iterdir()},
            WIKI_PAGES | {"_Sidebar.md"},
        )
        for path in WIKI_SOURCE_DIR.iterdir():
            with self.subTest(path=path.name):
                self.assertFalse(path.is_symlink())
                self.assertTrue(stat.S_ISREG(path.stat().st_mode))
                self.assertEqual(path.stat().st_mode & 0o111, 0)

        current_version = get_version()
        applies_to_pattern = re.compile(
            rf"^> \*\*Applies to:\*\* GM2Godot {re.escape(current_version)} · "
            r"GameMaker LTS 2026 · Godot 4\.7\.2\s*$",
            re.MULTILINE,
        )
        reviewed_pattern = re.compile(
            r"^> \*\*Last reviewed:\*\* \d{4}-\d{2}-\d{2}\s*$",
            re.MULTILINE,
        )

        for filename in sorted(WIKI_PAGES):
            with self.subTest(page=filename):
                content = (WIKI_SOURCE_DIR / filename).read_text(encoding="utf-8")
                self.assertRegex(content, applies_to_pattern)
                self.assertRegex(content, reviewed_pattern)
                self.assertEqual(
                    set(re.findall(r"\bGM2Godot (\d+\.\d+\.\d+)\b", content)),
                    {current_version},
                )

    def test_wiki_sidebar_and_local_page_links_resolve(self) -> None:
        sidebar = (WIKI_SOURCE_DIR / "_Sidebar.md").read_text(encoding="utf-8")
        for filename in sorted(WIKI_PAGES):
            with self.subTest(sidebar_page=filename):
                self.assertIn(f"]({filename.removesuffix('.md')})", sidebar)

        markdown_link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
        for source in sorted(WIKI_SOURCE_DIR.glob("*.md")):
            content = source.read_text(encoding="utf-8")
            for target in markdown_link_pattern.findall(content):
                target_without_fragment = target.split("#", 1)[0]
                if (
                    not target_without_fragment
                    or "://" in target_without_fragment
                    or target_without_fragment.startswith("mailto:")
                ):
                    continue
                target_filename = (
                    target_without_fragment
                    if target_without_fragment.endswith(".md")
                    else f"{target_without_fragment}.md"
                )
                with self.subTest(source=source.name, target=target):
                    self.assertIn(target_filename, WIKI_PAGES | {"_Sidebar.md"})
                    self.assertTrue((WIKI_SOURCE_DIR / target_filename).is_file())

    def test_wiki_publication_documents_bind_the_executable_gates(self) -> None:
        maintenance = (PROJECT_ROOT / "docs" / "WIKI_MAINTENANCE.md").read_text(encoding="utf-8")
        procedure = (WIKI_SOURCE_DIR / "Maintainer-Release-and-Wiki.md").read_text(encoding="utf-8")
        self.assertTrue((PROJECT_ROOT / "scripts" / "wiki_publication.py").is_file())
        for label, content in (("maintenance", maintenance), ("procedure", procedure)):
            for field in ("SOURCE_SHA", "SOURCE_TREE", "WIKI_BRANCH", "PRE_PUBLICATION_WIKI_SHA",
                          "PUBLISHED_WIKI_SHA", "CANONICAL_MAIN_SHA", "SOURCE_IS_CURRENT_MAIN"):
                with self.subTest(document=label, field=field):
                    self.assertIn(f"`{field}`", content)
            for phrase in ("SOURCE_SHA:docs/wiki", "Git 2.54", "git hook list --show-scope pre-push",
                           "core.hooksPath", "--no-follow-tags", "100644 blob", "git add --all",
                           "git write-tree == SOURCE_TREE", "outside both checkouts", "fresh", "ordinary"):
                with self.subTest(document=label, phrase=phrase):
                    self.assertIn(phrase, content)
        for command in ("stage", "publish", "verify", "complete"):
            with self.subTest(command=command):
                self.assertIn(f"python scripts/wiki_publication.py {command}", procedure)
        self.assertIn("--source-sha", procedure)
        self.assertIn("--published-sha", procedure)
        self.assertIn("--live-review", procedure)
        self.assertIn("prepared", procedure)
        self.assertIn("both `HEAD` and that named branch equal `PUBLISHED_WIKI_SHA`", procedure)
        self.assertIn("immediately before", procedure)
        self.assertIn("only then close it", procedure)
        self.assertNotIn("Push `HEAD`", procedure)

    def test_wiki_managed_output_roots_match_production(self) -> None:
        generated_project = (
            WIKI_SOURCE_DIR / "Generated-Project-and-Runtime.md"
        ).read_text(encoding="utf-8")
        start_marker = "<!-- managed-output-directories:start -->"
        end_marker = "<!-- managed-output-directories:end -->"
        before, separator, remainder = generated_project.partition(start_marker)
        self.assertTrue(separator, "Managed-output directory start marker is missing")
        managed_roots, separator, after = remainder.partition(end_marker)
        self.assertTrue(separator, "Managed-output directory end marker is missing")
        self.assertNotIn(start_marker, before + after)
        self.assertNotIn(end_marker, before + after)

        expected_roots = "\n" + "\n".join(
            f"- `{Path(directory).as_posix()}/`"
            for directory in MANAGED_OUTPUT_DIRECTORIES
        ) + "\n"
        self.assertEqual(managed_roots, expected_roots)

    def test_user_documentation_links_and_guidance_are_current(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        contributing = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(
            encoding="utf-8"
        )
        installation = (WIKI_SOURCE_DIR / "Installation.md").read_text(
            encoding="utf-8"
        )
        release_maintenance = (
            WIKI_SOURCE_DIR / "Maintainer-Release-and-Wiki.md"
        ).read_text(encoding="utf-8")
        maintenance = (PROJECT_ROOT / "docs" / "WIKI_MAINTENANCE.md").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "[Documentation](https://github.com/Infiland/GM2Godot/wiki) ·",
            readme,
        )
        self.assertIn("missing, empty, or an existing valid Godot project", readme)
        self.assertIn("Languages/template/template.json", contributing)
        self.assertNotIn("Languages/template.json", contributing)
        self.assertNotIn("modern_widgets.py", contributing)
        self.assertNotIn("Add community links", readme + contributing)
        self.assertNotIn("Add link if available", readme + contributing)
        self.assertIn(
            "Releases starting with 0.7.14 include `SHA256SUMS`",
            readme,
        )
        self.assertIn(
            "sha256sum --check --strict SHA256SUMS",
            installation,
        )
        macos_source = installation.partition("### macOS\n")[2].partition(
            "### Linux\n"
        )[0]
        linux_source = installation.partition("### Linux\n")[2].partition(
            "## Verify the source installation\n"
        )[0]
        self.assertNotIn("packaging/linux/qt-xcb-runtime-packages.txt", macos_source)
        self.assertIn("packaging/linux/qt-xcb-runtime-packages.txt", linux_source)
        self.assertIn("sudo apt-get install", linux_source)
        linux_release_readme = readme.partition(
            "The packaged Linux artifact is validated"
        )[2].partition("## Installation")[0]
        linux_release_installation = installation.partition(
            "Ubuntu 24.04 x86_64 is the only validated packaged-Linux baseline"
        )[2].partition("### Verify a release download")[0]
        runtime_packages = tuple(
            line.strip()
            for line in (
                PROJECT_ROOT
                / "packaging"
                / "linux"
                / "qt-xcb-runtime-packages.txt"
            )
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        for runtime_package in runtime_packages:
            with self.subTest(runtime_package=runtime_package):
                self.assertIn(runtime_package, linux_release_readme)
                self.assertIn(runtime_package, linux_release_installation)
        self.assertIn("only validated packaged-Linux baseline", installation)
        self.assertIn("not a signature or proof of publisher identity", installation)
        self.assertIn("exactly five unique, non-empty assets", release_maintenance)
        self.assertIn(
            "after the `sha256:` prefix in GitHub's `assets[].digest` field",
            release_maintenance,
        )
        self.assertIn("docs/wiki/", maintenance)
        self.assertIn("merged main-repository SHA", maintenance)
        self.assertIn("must not auto-close", maintenance)

    def test_runtime_docs_cover_ownership_event_order_and_state(self) -> None:
        segment_readme = (PROJECT_ROOT / "src" / "conversion" / "gml_runtime_parts" / "README.md").read_text(
            encoding="utf-8"
        )
        managers_doc = (PROJECT_ROOT / "src" / "conversion" / "runtime_managers.md").read_text(encoding="utf-8")

        self.assertIn("## Ownership", segment_readme)
        self.assertIn("runtime_api_index()", segment_readme)
        self.assertIn("## Runtime State", segment_readme)
        self.assertIn("## Event Order And Deviations", managers_doc)
        self.assertIn("## State, Globals, And Persistence", managers_doc)

    def test_required_issue_templates_exist(self) -> None:
        template_dir = PROJECT_ROOT / ".github" / "ISSUE_TEMPLATE"
        expected_templates = {
            "unsupported_gml_api.yml": ("Unsupported GML API", "Minimal GameMaker source"),
            "invalid_generated_gdscript.yml": ("Invalid Generated GDScript", "Godot error"),
            "resource_conversion_mismatch.yml": ("Resource Conversion Mismatch", "Resource kind"),
            "fixture_contribution.yml": ("Fixture Contribution", "Fixture checklist"),
        }

        for filename, phrases in expected_templates.items():
            with self.subTest(template=filename):
                content = (template_dir / filename).read_text(encoding="utf-8")
                for phrase in phrases:
                    self.assertIn(phrase, content)

    def test_resource_mismatch_taxonomy_covers_particles(self) -> None:
        template = (
            PROJECT_ROOT
            / ".github"
            / "ISSUE_TEMPLATE"
            / "resource_conversion_mismatch.yml"
        ).read_text(encoding="utf-8")
        diagnostics = (
            WIKI_SOURCE_DIR / "Diagnostics-and-Troubleshooting.md"
        ).read_text(encoding="utf-8")
        particle_kind = "Particle system, type, or emitter"

        description = next(
            line.removeprefix("description: ")
            for line in template.splitlines()
            if line.startswith("description: ")
        )
        self.assertIn("particle resource", description)
        resource_dropdown = template.partition("    id: resource-kind\n")[2].partition(
            "    validations:\n"
        )[0]
        self.assertEqual(
            resource_dropdown.count(f"        - {particle_kind}\n"),
            1,
        )
        self.assertEqual(resource_dropdown.count("        - Other\n"), 1)

        mismatch_guidance = next(
            line
            for line in diagnostics.splitlines()
            if "](" in line and "template=resource_conversion_mismatch.yml" in line
        )
        self.assertIn(particle_kind.lower(), mismatch_guidance.lower())
        self.assertIn("or other resource differences", mismatch_guidance)

    def test_code_health_workflow_runs_complete_pyflakes_suite(self) -> None:
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "code-health.yml").read_text(encoding="utf-8")
        with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
            ruff_config = cast(
                dict[str, object],
                tomllib.load(pyproject_file)["tool"]["ruff"],
            )

        self.assertEqual(ruff_config, EXPECTED_RUFF_CONFIG)
        self.assertTrue(workflow.endswith(EXPECTED_RUFF_LINT_STEPS))

    def test_contributor_docs_describe_complete_pyflakes_gate(self) -> None:
        required_guidance = (
            "CI enforces Ruff's complete `E7` and Pyflakes (`F`) rule families, plus `E9` fatal-error checks. "
            "`E7` includes the `E731` assigned-lambda and `E741` ambiguous-variable rules. "
            "Do not disable `F` or individual "
            "`F`-numbered rules globally or per file."
        )
        for path in (
            PROJECT_ROOT / "CONTRIBUTING.md",
            WIKI_SOURCE_DIR / "Contributing-and-Testing.md",
        ):
            with self.subTest(path=path.relative_to(PROJECT_ROOT)):
                content = path.read_text(encoding="utf-8")
                self.assertIn(required_guidance, content)
                self.assertIn("./venv/bin/python -m ruff check .", content)
                self.assertIn("generated `build/`, `dist/`, and `release/` output", content)
                self.assertIn("local `venv/` environment", content)
                self.assertIn("The `E4`, `I`, `B`, and `C90` families belong to separate reviewed changes.", content)

    def _run_ruff(
        self,
        path: Path,
        flags: tuple[str, ...],
        expected_exit: int,
        *,
        cwd: Path,
    ) -> list[dict[str, object]]:
        result = subprocess.run(
            (sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "json", *flags,
             "--", str(path)),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, expected_exit, result.stderr or result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 8192)
        raw_diagnostics: object = json.loads(result.stdout)
        self.assertIsInstance(raw_diagnostics, list)
        diagnostics: list[dict[str, object]] = []
        for diagnostic in cast(list[object], raw_diagnostics):
            self.assertIsInstance(diagnostic, dict)
            diagnostics.append(cast(dict[str, object], diagnostic))
        return diagnostics

    def test_e741_rule_is_enforced_without_tracked_input_bypasses(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gm2godot-e741-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            ambiguous_path = temporary_path / "ambiguous.py"
            descriptive_path = temporary_path / "descriptive.py"
            bypass_path = temporary_path / "bypass.py"
            ignore_config = temporary_path / "pyproject.toml"
            ambiguous_path.write_text("l = 1\n", encoding="utf-8")
            descriptive_path.write_text("log = 1\n", encoding="utf-8")
            bypass_path.write_text("l = 1  # noqa: E741\n", encoding="utf-8")
            ignore_config.write_text(
                '[tool.ruff.lint]\nselect = ["E741", "E9", "F"]\nignore = ["E741"]\n',
                encoding="utf-8",
            )

            project_flags = ("--config", str(PROJECT_ROOT / "pyproject.toml"))
            project_diagnostics = self._run_ruff(ambiguous_path, project_flags, 1, cwd=temporary_path)
            self.assertEqual([diagnostic["code"] for diagnostic in project_diagnostics], ["E741"])
            self.assertEqual(self._run_ruff(descriptive_path, project_flags, 0, cwd=temporary_path), [])
            self.assertEqual(
                self._run_ruff(bypass_path, ("--config", str(ignore_config)), 0, cwd=temporary_path),
                [],
            )

            tracked_flags = (
                "--isolated", "--target-version", "py312", "--select", "E7,E9,F", "--ignore-noqa",
                "--no-respect-gitignore", "--no-force-exclude",
            )
            tracked_diagnostics = self._run_ruff(bypass_path, tracked_flags, 1, cwd=temporary_path)
            self.assertEqual([diagnostic["code"] for diagnostic in tracked_diagnostics], ["E741"])
            for path, diagnostics in ((ambiguous_path, project_diagnostics), (bypass_path, tracked_diagnostics)):
                diagnostic = diagnostics[0]
                self.assertIsInstance(diagnostic["filename"], str)
                self.assertEqual(Path(cast(str, diagnostic["filename"])).resolve(), path.resolve())
                self.assertEqual(diagnostic["location"], {"row": 1, "column": 1})

    def test_e7_family_enforces_lambda_and_none_comparison_rules(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gm2godot-e7-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            lambda_path = temporary_path / "assigned_lambda.py"
            named_path = temporary_path / "named_function.py"
            comparison_path = temporary_path / "none_comparison.py"
            bypass_path = temporary_path / "bypass.py"
            ignore_config = temporary_path / "pyproject.toml"
            lambda_path.write_text("operation = lambda: 1\n", encoding="utf-8")
            named_path.write_text("def operation() -> int:\n    return 1\n", encoding="utf-8")
            comparison_path.write_text("value = object()\nif value == None:\n    print(value)\n", encoding="utf-8")
            bypass_path.write_text("operation = lambda: 1  # noqa: E731\n", encoding="utf-8")
            ignore_config.write_text(
                '[tool.ruff.lint]\nselect = ["E7", "E9", "F"]\nignore = ["E731"]\n',
                encoding="utf-8",
            )

            project_flags = ("--config", str(PROJECT_ROOT / "pyproject.toml"))
            tracked_flags = (
                "--isolated", "--target-version", "py312", "--select", "E7,E9,F", "--ignore-noqa",
                "--no-respect-gitignore", "--no-force-exclude",
            )
            self.assertEqual(self._run_ruff(named_path, project_flags, 0, cwd=temporary_path), [])
            self.assertEqual(
                self._run_ruff(bypass_path, ("--config", str(ignore_config)), 0, cwd=temporary_path),
                [],
            )
            for path, flags, code, location in (
                (lambda_path, project_flags, "E731", {"row": 1, "column": 1}),
                (comparison_path, project_flags, "E711", {"row": 2, "column": 13}),
                (bypass_path, tracked_flags, "E731", {"row": 1, "column": 1}),
                (comparison_path, tracked_flags, "E711", {"row": 2, "column": 13}),
            ):
                with self.subTest(path=path.name, flags=flags):
                    diagnostics = self._run_ruff(path, flags, 1, cwd=temporary_path)
                    self.assertEqual([diagnostic["code"] for diagnostic in diagnostics], [code])
                    diagnostic = diagnostics[0]
                    self.assertIsInstance(diagnostic["filename"], str)
                    self.assertEqual(Path(cast(str, diagnostic["filename"])).resolve(), path.resolve())
                    self.assertEqual(diagnostic["location"], location)

    def test_dependabot_updates_actions_weekly_and_pip_security_only(self) -> None:
        dependabot = (
            PROJECT_ROOT / ".github" / "dependabot.yml"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            dependabot,
            'version: 2\n'
            'updates:\n'
            '  - package-ecosystem: "github-actions"\n'
            '    directory: "/"\n'
            '    schedule:\n'
            '      interval: "weekly"\n'
            '  - package-ecosystem: "pip"\n'
            '    directory: "/"\n'
            '    schedule:\n'
            '      interval: "weekly"\n'
            '    open-pull-requests-limit: 0\n'
            '    groups:\n'
            '      pip-bootstrap-security:\n'
            '        applies-to: security-updates\n'
            '        patterns:\n'
            '          - "pip"\n'
            '          - "pip-tools"\n',
        )

    def test_external_workflow_actions_are_immutable_and_node24_native(
        self,
    ) -> None:
        workflows = sorted(
            [
                *WORKFLOW_DIR.glob("*.yml"),
                *WORKFLOW_DIR.glob("*.yaml"),
            ]
        )
        self.assertTrue(workflows)

        pins: dict[str, tuple[str, str, str]] = {}
        external_count = 0

        for workflow in workflows:
            lines = workflow.read_text(encoding="utf-8").splitlines()
            block_scalar_indent: int | None = None
            for line_number, line in enumerate(lines, start=1):
                stripped_line = line.strip()
                indentation = len(line) - len(line.lstrip(" "))
                if block_scalar_indent is not None:
                    if (
                        not stripped_line
                        or stripped_line.startswith("#")
                        or indentation > block_scalar_indent
                    ):
                        continue
                    block_scalar_indent = None

                location = (
                    f"{workflow.relative_to(PROJECT_ROOT)}:{line_number}"
                )
                uses_match = WORKFLOW_USES_PATTERN.match(line)
                if uses_match is None:
                    block_scalar_match = YAML_BLOCK_SCALAR_PATTERN.match(line)
                    if block_scalar_match is not None:
                        block_scalar_indent = len(
                            block_scalar_match.group("indent")
                        )
                        continue

                    flow_uses_match = FLOW_STYLE_USES_PATTERN.search(line)
                    if flow_uses_match is None:
                        continue

                    flow_value = flow_uses_match.group("value").strip()
                    unquoted_flow_value = (
                        flow_value[1:]
                        if flow_value[:1] in {'"', "'"}
                        else flow_value
                    )
                    if unquoted_flow_value.startswith(("./", "docker://")):
                        continue

                    external_count += 1
                    with self.subTest(location=location):
                        self.fail(
                            f"{location}: external uses must be on its own "
                            "line so its immutable pin can be verified"
                        )
                    continue

                raw_value = uses_match.group("value").strip()
                unquoted_value = (
                    raw_value[1:]
                    if raw_value[:1] in {'"', "'"}
                    else raw_value
                )
                if unquoted_value.startswith(("./", "docker://")):
                    continue

                external_count += 1
                pin_match = PINNED_EXTERNAL_ACTION_PATTERN.fullmatch(raw_value)

                with self.subTest(location=location):
                    self.assertIsNotNone(
                        pin_match,
                        f"{location}: external uses must be "
                        "<action>@<40-character SHA> # vMAJOR.MINOR.PATCH",
                    )
                if pin_match is None:
                    continue

                action = pin_match.group("action")
                sha = pin_match.group("sha").lower()
                version = pin_match.group("version")
                repository = "/".join(action.split("/")[:2]).casefold()
                approved_major = APPROVED_NODE24_ACTION_MAJORS.get(repository)

                with self.subTest(location=location, action=action):
                    self.assertIsNotNone(
                        approved_major,
                        f"{location}: review this action's runtime and add "
                        "its reviewed Node-24-native major to "
                        "APPROVED_NODE24_ACTION_MAJORS",
                    )
                if approved_major is None:
                    continue

                with self.subTest(location=location, action=action):
                    self.assertEqual(
                        int(pin_match.group("major")),
                        approved_major,
                        f"{location}: use the approved "
                        f"Node-24-native major v{approved_major}",
                    )

                action_key = action.casefold()
                observed_pin = (sha, version)
                previous_pin = pins.get(action_key)
                if previous_pin is None:
                    pins[action_key] = (sha, version, location)
                    continue

                with self.subTest(location=location, action=action):
                    self.assertEqual(
                        observed_pin,
                        previous_pin[:2],
                        f"{location}: {action} differs from "
                        f"{previous_pin[2]}",
                    )

        self.assertGreater(external_count, 0)


if __name__ == "__main__":
    unittest.main()
