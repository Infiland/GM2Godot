from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
import zipfile
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
    "tests.test_lts_2026_conversion",
)
CONVERSION_BOOT_MODULES = (
    "tests.test_simple_topdown_conversion",
    "tests.test_monophobia_conversion",
    "tests.test_lts_2026_conversion",
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
    (
        "SNAP_REF",
        "https://github.com/JujuAdams/SNAP.git",
    ),
    (
        "ADDING_REF",
        "https://github.com/WuffMakesGames/Adding.git",
    ),
)


def _godot_env_lines(content: str) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith(GODOT_ENV_PREFIXES)
    )


def _workflow_run_script(content: str, step_name: str) -> str:
    marker = f"      - name: {step_name}\n"
    _, separator, remainder = content.partition(marker)
    if not separator:
        raise AssertionError(f"Workflow step not found: {step_name}")

    metadata, separator, remainder = remainder.partition("        run: |\n")
    if not separator or "\n      - " in metadata:
        raise AssertionError(f"Workflow run script not found: {step_name}")

    script_lines: list[str] = []
    for line in remainder.splitlines():
        if line and not line.startswith("          "):
            break
        script_lines.append(line[10:] if line else "")
    return "\n".join(script_lines).strip() + "\n"


def _run_git(
    cwd: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    environment = _isolated_git_environment()
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env=environment,
    )


def _isolated_git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_"):
            del environment[name]
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_ALLOW_PROTOCOL"] = "file"
    return environment


def _make_shallow_no_tags_checkout(
    root: Path,
    tags: tuple[str, ...],
) -> Path:
    source = root / "source"
    remote = root / "remote.git"
    checkout = root / "checkout"

    _run_git(root, "init", "--initial-branch=main", str(source))
    _run_git(
        source,
        "-c",
        "user.name=GM2Godot CI",
        "-c",
        "user.email=ci@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "tagged commit",
    )
    for tag in tags:
        _run_git(source, "tag", tag)
    _run_git(
        source,
        "-c",
        "user.name=GM2Godot CI",
        "-c",
        "user.email=ci@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "current main",
    )
    _run_git(root, "clone", "--bare", str(source), str(remote))
    _run_git(
        root,
        "clone",
        "--depth=1",
        "--no-tags",
        "--branch",
        "main",
        remote.resolve().as_uri(),
        str(checkout),
    )

    shallow = _run_git(
        checkout,
        "rev-parse",
        "--is-shallow-repository",
    ).stdout.strip()
    if shallow != "true":
        raise AssertionError("Tag-check fixture must be a shallow checkout")
    if _run_git(checkout, "tag", "--list").stdout:
        raise AssertionError("Tag-check fixture unexpectedly fetched local tags")
    tag_option = _run_git(
        checkout,
        "config",
        "--get",
        "remote.origin.tagOpt",
    ).stdout.strip()
    if tag_option != "--no-tags":
        raise AssertionError("Tag-check fixture must keep remote tag fetching disabled")
    return checkout


def _run_release_tag_check(
    content: str,
    checkout: Path,
    version: str,
    output_path: Path,
) -> subprocess.CompletedProcess[str]:
    version_expression = "${{ steps.version.outputs.version }}"
    script = _workflow_run_script(content, "Check if tag already exists")
    if version_expression not in script:
        raise AssertionError("Release tag-check script lost its version expression")
    script = script.replace(version_expression, version)

    output_path.write_text("", encoding="utf-8")
    environment = _isolated_git_environment()
    environment["GITHUB_OUTPUT"] = str(output_path)
    return subprocess.run(
        ["bash", "-c", script],
        cwd=checkout,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def _write_raw_artifact_archive(
    root: Path,
    artifact_name: str,
    members: dict[str, bytes],
) -> None:
    artifact_dir = root / "raw-artifacts" / artifact_name
    artifact_dir.mkdir(parents=True)
    with zipfile.ZipFile(
        artifact_dir / f"{artifact_name}.zip",
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for member_name, payload in members.items():
            archive.writestr(member_name, payload)


class TestCIWorkflows(unittest.TestCase):
    def test_release_preserves_digest_checks_without_deprecated_extraction(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")

        self.assertIn("contents: write", content)
        self.assertIn("uses: actions/download-artifact@", content)
        self.assertIn("path: raw-artifacts", content)
        self.assertIn("skip-decompress: true", content)
        self.assertIn("digest-mismatch: error", content)
        self.assertIn("Extract verified artifact archives", content)
        self.assertIn(
            "for name in GM2Godot-windows GM2Godot-macos GM2Godot-linux",
            content,
        )
        self.assertIn('archive="raw-artifacts/$name/$name.zip"', content)
        self.assertIn('[[ ! -s "$archive" ]]', content)
        self.assertIn('unzip -q "$archive" -d "artifacts/$name"', content)

        expected_members = {
            "GM2Godot-windows": {"GM2Godot-windows.zip": b"windows"},
            "GM2Godot-macos": {
                "GM2Godot-macos.zip": b"macos-zip",
                "GM2Godot-macos.dmg": b"macos-dmg",
            },
            "GM2Godot-linux": {"GM2Godot-linux.zip": b"linux"},
        }
        for artifact_name, members in expected_members.items():
            for member_name in members:
                with self.subTest(release_file=member_name):
                    self.assertIn(
                        f"artifacts/{artifact_name}/{member_name}",
                        content,
                    )

        script = _workflow_run_script(content, "Extract verified artifact archives")
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            for artifact_name, members in expected_members.items():
                _write_raw_artifact_archive(root, artifact_name, members)

            result = subprocess.run(
                ["bash", "-c", script],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for artifact_name, members in expected_members.items():
                for member_name, payload in members.items():
                    with self.subTest(artifact=artifact_name, member=member_name):
                        extracted = root / "artifacts" / artifact_name / member_name
                        self.assertEqual(extracted.read_bytes(), payload)

    def test_release_extraction_fails_when_verified_archive_is_missing(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Extract verified artifact archives")

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            _write_raw_artifact_archive(
                root,
                "GM2Godot-windows",
                {"GM2Godot-windows.zip": b"windows"},
            )
            result = subprocess.run(
                ["bash", "-c", script],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Missing or empty verified archive: "
            "raw-artifacts/GM2Godot-macos/GM2Godot-macos.zip",
            result.stderr,
        )

    def test_release_tag_check_finds_exact_remote_tag_without_local_tags(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        tag_ref = "refs/tags/v0.7.9"

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            checkout = _make_shallow_no_tags_checkout(
                root,
                ("v0.7.9", "v0.7.90", "v0.7.9-rc1"),
            )
            local_tag = _run_git(
                checkout,
                "rev-parse",
                "--verify",
                tag_ref,
                check=False,
            )
            remote_tag = _run_git(
                checkout,
                "ls-remote",
                "--exit-code",
                "--refs",
                "origin",
                tag_ref,
                check=False,
            )
            output_path = root / "github-output.txt"
            result = _run_release_tag_check(
                content,
                checkout,
                "0.7.9",
                output_path,
            )

            self.assertNotEqual(local_tag.returncode, 0)
            self.assertEqual(remote_tag.returncode, 0, remote_tag.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "exists=true\n")

    def test_release_tag_check_rejects_similarly_prefixed_remote_tags(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        tag_ref = "refs/tags/v0.7.9"

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            checkout = _make_shallow_no_tags_checkout(
                root,
                ("v0.7.90", "v0.7.9-rc1"),
            )
            remote_tag = _run_git(
                checkout,
                "ls-remote",
                "--exit-code",
                "--refs",
                "origin",
                tag_ref,
                check=False,
            )
            output_path = root / "github-output.txt"
            result = _run_release_tag_check(
                content,
                checkout,
                "0.7.9",
                output_path,
            )

            self.assertEqual(remote_tag.returncode, 2, remote_tag.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "exists=false\n")

    def test_release_tag_check_fails_closed_for_broken_origin(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        tag_ref = "refs/tags/v0.7.9"

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            checkout = _make_shallow_no_tags_checkout(root, ("v0.7.9",))
            missing_remote = (root / "missing.git").resolve().as_uri()
            _run_git(checkout, "remote", "set-url", "origin", missing_remote)
            remote_tag = _run_git(
                checkout,
                "ls-remote",
                "--exit-code",
                "--refs",
                "origin",
                tag_ref,
                check=False,
            )
            output_path = root / "github-output.txt"
            result = _run_release_tag_check(
                content,
                checkout,
                "0.7.9",
                output_path,
            )

            self.assertNotIn(remote_tag.returncode, (0, 2))
            self.assertEqual(result.returncode, remote_tag.returncode)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "")
            self.assertIn("::error::Failed to query exact remote tag", result.stderr)
            self.assertIn(tag_ref, result.stderr)
            self.assertIn(
                f"git ls-remote exit {remote_tag.returncode}",
                result.stderr,
            )

    def test_release_jobs_require_authoritative_remote_tag_absence(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Check if tag already exists")
        build_job = content[content.index("  build:"):content.index("  release:")]
        release_job = content[content.index("  release:"):]
        absence_guard = "needs.get-version.outputs.tag_exists == 'false'"
        build_job_conditions = [
            line for line in build_job.splitlines() if line.startswith("    if: ")
        ]
        release_job_conditions = [
            line for line in release_job.splitlines() if line.startswith("    if: ")
        ]

        self.assertIn("set -euo pipefail", script)
        self.assertIn(
            'git ls-remote --exit-code --refs origin "$tag_ref"',
            script,
        )
        self.assertIn('tag_ref="refs/tags/v${{ steps.version.outputs.version }}"', script)
        self.assertNotIn("git rev-parse", script)
        self.assertEqual(build_job_conditions, [f"    if: {absence_guard}"])
        self.assertEqual(
            release_job_conditions,
            [f"    if: github.event_name != 'pull_request' && {absence_guard}"],
        )

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

    def test_unit_workflow_runs_artifact_transactions_on_windows(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "tests.yml"
        content = workflow.read_text(encoding="utf-8")
        windows_job = content[content.index("  windows-artifact-transactions:"):]

        self.assertIn("runs-on: windows-latest", windows_job)
        self.assertIn("python-version: '3.12'", windows_job)
        self.assertIn("pip install -r requirements.txt", windows_job)
        for module in (
            "tests.test_conversion_outcome",
            "tests.test_conversion_manifest",
            "tests.test_diagnostics",
            "tests.test_architecture_policy",
            "tests.test_converter",
            "tests.test_cli",
            "tests.test_included_files.TestIncludedFilesManagedRootTransaction",
            "tests.test_included_files.TestIncludedFilesConverterOutputContainment",
        ):
            with self.subTest(module=module):
                self.assertIn(module, windows_job)

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
        self.assertIn("uses: actions/cache@", content)
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
        self.assertLess(
            install_index,
            content.index("- name: Run current-LTS conversion, validation, and boot tests"),
        )
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

    def test_current_lts_job_verifies_exact_godot_build_and_fixture_projects(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "tcc-conversion-test.yml"
        content = workflow.read_text(encoding="utf-8")
        job_index = content.index("  lts-2026-conversion:")
        lts_job = content[job_index:]
        checksum_command = (
            'echo "${GODOT_ARCHIVE_SHA256}  '
            '${RUNNER_TEMP}/${GODOT_ARCHIVE}" | sha256sum --check --strict'
        )

        self.assertIn('test "$godot_build" = "4.7.1.stable.official.a13da4feb"', lts_job)
        self.assertIn(checksum_command, lts_job)
        self.assertLess(lts_job.index(checksum_command), lts_job.index("unzip -q"))
        self.assertIn('test -f "$repo_dir/snap.yyp"', lts_job)
        self.assertIn('test -f "$repo_dir/Adding.yyp"', lts_job)
        self.assertIn("GM2GODOT_REQUIRE_LTS_FIXTURES: '1'", lts_job)
        self.assertIn("SNAP_PROJECT_PATH: ${{ runner.temp }}/SNAP", lts_job)
        self.assertIn("ADDING_PROJECT_PATH: ${{ runner.temp }}/Adding", lts_job)
        self.assertIn(
            "python -m unittest tests.test_lts_2026_conversion -v",
            lts_job,
        )
        test_step_index = lts_job.index(
            "- name: Run current-LTS conversion, validation, and boot tests"
        )
        upload_step_index = lts_job.index(
            "- name: Upload bounded current-LTS failure reports"
        )
        test_step = lts_job[test_step_index:upload_step_index]
        job_timeout_match = re.search(
            r"(?m)^    timeout-minutes: ([0-9]+)$",
            lts_job,
        )
        step_timeout_match = re.search(
            r"(?m)^        timeout-minutes: ([0-9]+)$",
            test_step,
        )
        self.assertIsNotNone(job_timeout_match)
        self.assertIsNotNone(step_timeout_match)
        assert job_timeout_match is not None
        assert step_timeout_match is not None
        self.assertLess(
            int(step_timeout_match.group(1)),
            int(job_timeout_match.group(1)),
        )
        self.assertLess(
            lts_job.index("- name: Install pinned Godot"),
            test_step_index,
        )

    def test_current_lts_job_uploads_only_bounded_failure_reports(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "tcc-conversion-test.yml"
        content = workflow.read_text(encoding="utf-8")
        upload_index = content.index("- name: Upload bounded current-LTS failure reports")
        upload_step = content[upload_index:]

        self.assertIn("if: failure()", upload_step)
        self.assertIn("uses: actions/upload-artifact@", upload_step)
        self.assertIn("if-no-files-found: ignore", upload_step)
        self.assertIn("retention-days: 7", upload_step)
        for report_name in (
            "lts_fixture_report.json",
            "unittest.log",
            "conversion_diagnostics.json",
            "conversion_diagnostics.md",
            "conversion_manifest.json",
            "godot_validation_report.json",
        ):
            with self.subTest(report=report_name):
                self.assertIn(report_name, upload_step)
        self.assertNotIn("gm2godot-lts-2026-output/*/**", upload_step)
        self.assertNotRegex(upload_step, r"(?m)^\s+path:\s+.*gm2godot-lts-2026-output/?\s*$")


if __name__ == "__main__":
    unittest.main()
