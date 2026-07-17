from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_GODOT_ENV_LINES = (
    "GODOT_VERSION: 4.7.1-stable",
    "GODOT_ARCHIVE: Godot_v4.7.1-stable_linux.x86_64.zip",
    "GODOT_BINARY: Godot_v4.7.1-stable_linux.x86_64",
    "GODOT_ARCHIVE_SHA256: c7ff14fd28472c8d4f193043de30278dcf7e5241a1dcf7566b02e27addaa33ba",
)
GODOT_ENV_PREFIXES = tuple(line.partition(":")[0] + ":" for line in EXPECTED_GODOT_ENV_LINES)
LIVE_GODOT_MODULES_OUTSIDE_DISCOVERY = (
    "tests.test_godot_validation",
    "tests.test_golden_conversion",
    "tests.test_project_settings",
)
EXTERNAL_CONVERSION_MODULES = (
    "tests.test_simple_topdown_conversion",
    "tests.test_tcc_conversion",
    "tests.test_monophobia_conversion",
)
CONVERSION_BOOT_MODULES = (
    "tests.test_simple_topdown_conversion",
    "tests.test_monophobia_conversion",
)
EXTERNAL_FIXTURE_REPOSITORIES = (
    (
        "SIMPLE_TOPDOWN_REF",
        "https://github.com/Infiland/GM2GodotGameTest_SimpleTopDown.git",
    ),
    (
        "TCC_REF",
        "https://github.com/Infiland/TheColorfulCreature.git",
    ),
    (
        "MONOPHOBIA_REF",
        "https://github.com/Infiland/Monophobia.git",
    ),
)


def _godot_env_lines(content: str) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith(GODOT_ENV_PREFIXES)
    )


class TestCIWorkflows(unittest.TestCase):
    def test_unit_workflow_runs_discovery_for_golden_and_threshold_gates(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "tests.yml"
        content = workflow.read_text(encoding="utf-8")

        self.assertIn("pip install -r requirements.txt", content)
        self.assertNotIn("pip install Pillow", content)
        self.assertIn(
            "sudo apt-get install --yes --no-install-recommends libegl1",
            content,
        )
        self.assertIn("python -m unittest discover tests/ -v", content)
        self.assertLess(
            content.index("sudo apt-get install --yes --no-install-recommends libegl1"),
            content.index("python -m unittest discover tests/ -v"),
        )
        self.assertTrue((PROJECT_ROOT / "tests" / "test_golden_conversion.py").is_file())
        self.assertTrue((PROJECT_ROOT / "tests" / "test_cli.py").is_file())

    def test_godot_workflows_pin_exact_supported_version(self) -> None:
        workflow_names = ("godot-smoke.yml", "tcc-conversion-test.yml")

        for workflow_name in workflow_names:
            with self.subTest(workflow=workflow_name):
                workflow = PROJECT_ROOT / ".github" / "workflows" / workflow_name
                content = workflow.read_text(encoding="utf-8")

                self.assertEqual(_godot_env_lines(content), EXPECTED_GODOT_ENV_LINES)
                self.assertNotIn("4.4.1", content)

    def test_godot_workflows_verify_archive_digest_before_unzip(self) -> None:
        workflow_names = ("godot-smoke.yml", "tcc-conversion-test.yml")

        for workflow_name in workflow_names:
            with self.subTest(workflow=workflow_name):
                workflow = PROJECT_ROOT / ".github" / "workflows" / workflow_name
                content = workflow.read_text(encoding="utf-8")
                checksum_command = (
                    'echo "${GODOT_ARCHIVE_SHA256}  '
                    '${RUNNER_TEMP}/${GODOT_ARCHIVE}" | sha256sum --check --strict'
                )

                self.assertIn(checksum_command, content)
                self.assertLess(content.index(checksum_command), content.index('unzip -q "${RUNNER_TEMP}/${GODOT_ARCHIVE}"'))
                self.assertIn(
                    "key: godot-${{ runner.os }}-${{ env.GODOT_VERSION }}-${{ env.GODOT_ARCHIVE_SHA256 }}",
                    content,
                )

    def test_godot_smoke_workflow_covers_discovered_and_nonmatching_live_tests(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "godot-smoke.yml"
        content = workflow.read_text(encoding="utf-8")
        godot_test_files = tuple((PROJECT_ROOT / "tests").glob("test_*_godot.py"))

        self.assertIn("GODOT_BIN=$godot_bin", content)
        self.assertIn("actions/cache@v4", content)
        self.assertGreater(len(godot_test_files), 13)
        self.assertIn(
            "python -m unittest discover -s tests -p 'test_*_godot.py' -v",
            content,
        )
        for module in LIVE_GODOT_MODULES_OUTSIDE_DISCOVERY:
            with self.subTest(module=module):
                test_path = PROJECT_ROOT / f"{module.replace('.', '/')}.py"
                self.assertTrue(test_path.is_file())
                self.assertFalse(test_path.match("test_*_godot.py"))
                self.assertIn(module, content)

    def test_external_game_workflow_installs_godot_before_all_fixture_tests(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "tcc-conversion-test.yml"
        content = workflow.read_text(encoding="utf-8")

        install_index = content.index("- name: Install pinned Godot")
        self.assertIn("GODOT_BIN=$godot_bin", content)
        self.assertLess(install_index, content.index("- name: Run SimpleTopDown conversion and boot-log test"))
        self.assertLess(install_index, content.index("- name: Run TCC conversion test"))
        self.assertLess(install_index, content.index("- name: Run Monophobia conversion and boot-log test"))
        for module in EXTERNAL_CONVERSION_MODULES:
            with self.subTest(module=module):
                self.assertIn(f"python -m unittest {module} -v", content)
        for module in CONVERSION_BOOT_MODULES:
            with self.subTest(boot_module=module):
                test_path = PROJECT_ROOT / f"{module.replace('.', '/')}.py"
                self.assertIn("boot_frames=2", test_path.read_text(encoding="utf-8"))

    def test_external_game_workflow_fetches_pinned_fixture_commits(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "tcc-conversion-test.yml"
        content = workflow.read_text(encoding="utf-8")
        fixture_fetch_lines = tuple(
            line.strip()
            for line in content.splitlines()
            if line.strip().startswith('git -C "$repo_dir" fetch ')
        )

        self.assertNotIn("git clone", content)
        self.assertNotRegex(content, r"(?m)\borigin[ \t]+(?:HEAD|main|master)(?:[ \t]|$)")
        self.assertEqual(
            len(fixture_fetch_lines),
            len(EXTERNAL_FIXTURE_REPOSITORIES),
        )
        self.assertEqual(
            content.count("git -C \"$repo_dir\" checkout --quiet --detach FETCH_HEAD"),
            len(EXTERNAL_FIXTURE_REPOSITORIES),
        )
        for ref_name, repository_url in EXTERNAL_FIXTURE_REPOSITORIES:
            with self.subTest(ref=ref_name):
                ref_match = re.search(
                    rf"(?m)^  {re.escape(ref_name)}: ([0-9a-f]{{40}})$",
                    content,
                )
                self.assertIsNotNone(ref_match)
                assert ref_match is not None
                pinned_ref = ref_match.group(1)
                self.assertRegex(pinned_ref, r"\A[0-9a-f]{40}\Z")
                self.assertIn(f"remote add origin {repository_url}", content)
                self.assertIn(
                    f'git -C "$repo_dir" fetch --quiet --depth 1 --no-tags origin "${{{ref_name}}}"',
                    fixture_fetch_lines,
                )
                self.assertIn(
                    f'rev-parse HEAD)" = "${{{ref_name}}}"',
                    content,
                )


if __name__ == "__main__":
    unittest.main()
