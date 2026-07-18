from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
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
RELEASE_PREFLIGHT_TEST_TAG = "v999.123.456"
RELEASE_SMOKE_ARTIFACT = "release-action-smoke"
RELEASE_SMOKE_SENTINEL = "release-action-sentinel.txt"
RELEASE_SMOKE_PAYLOAD = b"GM2Godot release action smoke\n"
RELEASE_SMOKE_PAYLOAD_SHA256 = (
    "f1efea0ac477ea11ec0fe4d13d9bfdcc2908ed8a6e2c71b91952388c1aaf48e6"
)
RELEASE_PAYLOADS = (
    ("artifacts/GM2Godot-linux/GM2Godot-linux.zip", b"linux payload\n"),
    ("artifacts/GM2Godot-macos/GM2Godot-macos.dmg", b"macOS DMG payload\n"),
    ("artifacts/GM2Godot-macos/GM2Godot-macos.zip", b"macOS ZIP payload\n"),
    ("artifacts/GM2Godot-windows/GM2Godot-windows.zip", b"windows payload\n"),
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


def _run_release_state_preflight(
    content: str,
    root: Path,
    response_text: str | tuple[str, ...],
    *,
    gh_exit: int = 0,
    token: str | None = "test-token",
    install_gh: bool = True,
    install_python: bool = True,
) -> subprocess.CompletedProcess[str]:
    script = _workflow_run_script(content, "Check for incomplete release state")
    tools_dir = root / "tools"
    tools_dir.mkdir()
    response_texts = (response_text,) if isinstance(response_text, str) else response_text
    if not response_texts:
        raise ValueError("Release-preflight response sequence cannot be empty")
    response_paths: list[Path] = []
    for index, current_response in enumerate(response_texts, start=1):
        response_path = root / f"release-pages-{index}.json"
        response_path.write_text(current_response, encoding="utf-8")
        response_paths.append(response_path)
    call_log = root / "gh-calls.txt"

    if install_gh:
        fake_gh = tools_dir / "gh"
        fake_gh.write_text(
            f"#!{sys.executable}\n"
            """from pathlib import Path
import os
import sys

expected = [
    "api",
    "--paginate",
    "--slurp",
    "-H",
    "Accept: application/vnd.github+json",
    "-H",
    "X-GitHub-Api-Version: 2026-03-10",
    "repos/Infiland/GM2Godot/releases?per_page=100",
]
if sys.argv[1:] != expected:
    print(f"unexpected gh arguments: {sys.argv[1:]!r}", file=sys.stderr)
    raise SystemExit(97)
if os.environ.get("GH_TOKEN") != "test-token":
    print("fake gh did not receive the expected GH_TOKEN", file=sys.stderr)
    raise SystemExit(98)
call_log = Path(os.environ["FAKE_GH_CALL_LOG"])
call_number = 0
if call_log.exists():
    call_number = len(call_log.read_text(encoding="utf-8").splitlines())
response_paths = os.environ["FAKE_GH_RESPONSES"].split(os.pathsep)
response_path = response_paths[min(call_number, len(response_paths) - 1)]
with call_log.open("a", encoding="utf-8") as handle:
    handle.write("call\\n")
sys.stdout.write(
    Path(response_path).read_text(encoding="utf-8")
)
raise SystemExit(int(os.environ["FAKE_GH_EXIT"]))
""",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)

    fake_sleep = tools_dir / "sleep"
    fake_sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_sleep.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_GH_CALL_LOG": str(call_log),
            "FAKE_GH_EXIT": str(gh_exit),
            "FAKE_GH_RESPONSES": os.pathsep.join(map(str, response_paths)),
            "GITHUB_REPOSITORY": "Infiland/GM2Godot",
            "RELEASE_PREFLIGHT_RETRY_DELAY_SECONDS": "0",
            "RELEASE_TAG": RELEASE_PREFLIGHT_TEST_TAG,
        }
    )
    if token is None:
        environment.pop("GH_TOKEN", None)
    else:
        environment["GH_TOKEN"] = token
    if install_gh and install_python:
        environment["PATH"] = os.pathsep.join(
            (
                str(tools_dir),
                str(Path(sys.executable).parent),
                environment.get("PATH", ""),
            )
        )
    else:
        environment["PATH"] = str(tools_dir)

    return subprocess.run(
        ["/bin/bash", "-c", script],
        cwd=root,
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


def _write_release_payloads(root: Path) -> None:
    for relative_path, payload in RELEASE_PAYLOADS:
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)


class TestCIWorkflows(unittest.TestCase):
    def test_release_action_smoke_is_pr_only_and_credentialless(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release-action-smoke.yml"
        content = workflow.read_text(encoding="utf-8")

        self.assertIn(
            "on:\n"
            "  pull_request:\n"
            "    branches: [main]\n"
            "    paths:\n"
            "      - '.github/workflows/release.yml'\n"
            "      - '.github/workflows/release-action-smoke.yml'\n",
            content,
        )
        self.assertEqual(content.count("permissions:"), 3)
        self.assertIn("\npermissions: {}\n", content)
        self.assertEqual(content.count("permissions: {}"), 2)
        self.assertIn("permissions:\n      actions: read", content)
        for forbidden in (
            "pull_request_target:",
            "workflow_dispatch:",
            "schedule:",
            "\n  push:",
            "actions/checkout@",
            "secrets.",
            "contents: write",
            "write-all",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, content)
        self.assertNotRegex(content, r"(?im)^\s+[a-z0-9_-]+:\s+write\s*$")
        self.assertNotRegex(content, r"\b(?:PAT|PERSONAL_ACCESS_TOKEN)\b")
        self.assertNotRegex(content, r"(?i)\bsecrets\s*(?:\.|\[)")

    def test_release_action_smoke_is_independent_of_release_state(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release-action-smoke.yml"
        content = workflow.read_text(encoding="utf-8")

        for forbidden in (
            "src/version.py",
            "VERSION",
            "get-version",
            "tag_exists",
            "needs.get-version",
            "git ls-remote",
            "refs/tags/",
            "release-state-preflight",
            "gm2godot-release-publisher",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, content)
        self.assertIn(
            "tag_name: gm2godot-release-smoke-"
            "${{ github.run_id }}-${{ github.run_attempt }}",
            content,
        )

    def test_release_action_smoke_reuses_production_action_pins(self) -> None:
        release = (
            PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8")
        smoke = (
            PROJECT_ROOT / ".github" / "workflows" / "release-action-smoke.yml"
        ).read_text(encoding="utf-8")

        for action in (
            "actions/upload-artifact",
            "actions/download-artifact",
            "softprops/action-gh-release",
        ):
            pattern = re.compile(
                rf"uses:\s*{re.escape(action)}@([0-9a-f]{{40}})\s+#\s+(v\S+)"
            )
            release_pins = set(pattern.findall(release))
            smoke_pins = pattern.findall(smoke)
            with self.subTest(action=action):
                self.assertEqual(len(release_pins), 1)
                self.assertEqual(len(smoke_pins), 1)
                self.assertEqual(smoke_pins[0], next(iter(release_pins)))

    def test_upload_artifact_calls_explicitly_preserve_archives(self) -> None:
        uses_pattern = re.compile(
            r"^(?P<indent> *)(?:-\s*)?(?P<key_quote>['\"]?)"
            r"uses(?P=key_quote)\s*:\s*(?P<value>.*?)\s*$"
        )
        flow_uses_pattern = re.compile(
            r"\{[^{}]*?(?:['\"]uses['\"]|uses)\s*:"
            r"\s*(?P<value>[^,}]+)"
        )
        locations: list[str] = []
        workflow_dir = PROJECT_ROOT / ".github" / "workflows"
        workflows = (*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml"))
        for workflow in sorted(workflows):
            lines = workflow.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                for flow_match in flow_uses_pattern.finditer(line):
                    flow_value = flow_match.group("value").strip().strip("'\"")
                    if flow_value.casefold().startswith("actions/upload-artifact@"):
                        self.fail(
                            f"{workflow.name}:{index + 1}: upload-artifact must "
                            "use block style so with.archive can be verified"
                        )

                uses_match = uses_pattern.match(line)
                if uses_match is None:
                    continue
                raw_value = uses_match.group("value").partition("#")[0].strip()
                action_value = raw_value.strip("'\"")
                if not action_value.casefold().startswith("actions/upload-artifact@"):
                    continue

                locations.append(f"{workflow.name}:{index + 1}")
                uses_indent = len(uses_match.group("indent"))
                step_indent = (
                    uses_indent
                    if line[uses_indent:].startswith("-")
                    else uses_indent - 2
                )
                end = index + 1
                while end < len(lines):
                    candidate = lines[end]
                    candidate_indent = len(candidate) - len(candidate.lstrip())
                    if candidate.strip() and candidate_indent <= step_indent:
                        break
                    end += 1

                property_indent = step_indent + 2
                with_pattern = re.compile(
                    rf"^ {{{property_indent}}}(?P<quote>['\"]?)"
                    r"with(?P=quote)\s*:\s*(?:#.*)?$"
                )
                with_index = next(
                    (
                        candidate_index
                        for candidate_index in range(index + 1, end)
                        if with_pattern.match(lines[candidate_index])
                    ),
                    None,
                )
                archive_inputs: list[str] = []
                if with_index is not None:
                    input_indent = property_indent + 2
                    with_end = with_index + 1
                    while with_end < end:
                        candidate = lines[with_end]
                        candidate_indent = len(candidate) - len(candidate.lstrip())
                        if candidate.strip() and candidate_indent <= property_indent:
                            break
                        with_end += 1
                    archive_pattern = re.compile(
                        rf"^ {{{input_indent}}}(?P<quote>['\"]?)"
                        r"archive(?P=quote)\s*:\s*"
                        r"(?P<value>[^#]*?)\s*(?:#.*)?$"
                    )
                    for candidate in lines[with_index + 1:with_end]:
                        archive_match = archive_pattern.match(candidate)
                        if archive_match is not None:
                            archive_inputs.append(
                                archive_match.group("value").strip().strip("'\"").casefold()
                            )
                with self.subTest(location=locations[-1]):
                    self.assertEqual(archive_inputs, ["true"])

        self.assertEqual(len(locations), 4, locations)

    def test_release_action_smoke_verifies_sentinel_archive(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release-action-smoke.yml"
        content = workflow.read_text(encoding="utf-8")
        expected_archive = (
            "raw-artifacts/release-action-smoke/release-action-smoke.zip"
        )

        for required in (
            "id: upload_sentinel",
            f"name: {RELEASE_SMOKE_ARTIFACT}",
            f"path: sentinel/{RELEASE_SMOKE_SENTINEL}",
            "if-no-files-found: error",
            "archive: true",
            "retention-days: 1",
            "needs: upload-sentinel",
            "path: raw-artifacts/release-action-smoke",
            "skip-decompress: true",
            "digest-mismatch: error",
            "${{ needs.upload-sentinel.outputs.artifact_digest }}",
            expected_archive,
            RELEASE_SMOKE_PAYLOAD_SHA256,
        ):
            with self.subTest(required=required):
                self.assertIn(required, content)
        create_script = _workflow_run_script(content, "Create sentinel")
        verify_script = _workflow_run_script(
            content,
            "Verify sentinel archive and bytes",
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            created = subprocess.run(
                ["bash", "-c", create_script],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertEqual(
                (root / "sentinel" / RELEASE_SMOKE_SENTINEL).read_bytes(),
                RELEASE_SMOKE_PAYLOAD,
            )

        cases = (
            (
                "valid",
                {RELEASE_SMOKE_SENTINEL: RELEASE_SMOKE_PAYLOAD},
                None,
                0,
                "",
            ),
            (
                "wrong archive digest",
                {RELEASE_SMOKE_SENTINEL: RELEASE_SMOKE_PAYLOAD},
                "0" * 64,
                1,
                "Downloaded archive differs from the uploaded artifact",
            ),
            (
                "altered sentinel bytes",
                {RELEASE_SMOKE_SENTINEL: b"altered\n"},
                None,
                1,
                "",
            ),
            (
                "nested sentinel",
                {f"nested/{RELEASE_SMOKE_SENTINEL}": RELEASE_SMOKE_PAYLOAD},
                None,
                1,
                "Unexpected sentinel archive layout",
            ),
        )
        for case, members, digest_override, expected_status, expected_error in cases:
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as temp_directory:
                    root = Path(temp_directory)
                    _write_raw_artifact_archive(
                        root,
                        RELEASE_SMOKE_ARTIFACT,
                        members,
                    )
                    archive = root / expected_archive
                    environment = os.environ.copy()
                    environment["EXPECTED_ARCHIVE_SHA256"] = (
                        digest_override
                        or hashlib.sha256(archive.read_bytes()).hexdigest()
                    )
                    result = subprocess.run(
                        ["bash", "-c", verify_script],
                        cwd=root,
                        check=False,
                        capture_output=True,
                        text=True,
                        env=environment,
                    )

                if expected_status == 0:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                if expected_error:
                    self.assertIn(expected_error, result.stderr)

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            direct_archive = root / "raw-artifacts" / f"{RELEASE_SMOKE_ARTIFACT}.zip"
            direct_archive.parent.mkdir(parents=True)
            with zipfile.ZipFile(direct_archive, "w") as archive:
                archive.writestr(RELEASE_SMOKE_SENTINEL, RELEASE_SMOKE_PAYLOAD)
            environment = os.environ.copy()
            environment["EXPECTED_ARCHIVE_SHA256"] = hashlib.sha256(
                direct_archive.read_bytes()
            ).hexdigest()
            result = subprocess.run(
                ["bash", "-c", verify_script],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            f"Missing or empty sentinel archive: {expected_archive}",
            result.stderr,
        )

    def test_release_action_smoke_requires_local_publisher_rejection(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release-action-smoke.yml"
        content = workflow.read_text(encoding="utf-8")
        publisher_marker = (
            "      - name: Load publisher and reject before GitHub API access\n"
        )
        publisher_step = content[
            content.index(publisher_marker):content.index(
                "      - name: Assert the publisher rejected the probe\n"
            )
        ]

        for required in (
            "id: publisher_startup",
            "continue-on-error: true",
            "uses: softprops/action-gh-release@",
            "GITHUB_TOKEN: gm2godot-release-smoke-invalid-token",
            "repository: github/gm2godot-release-smoke-never-create",
            "token: gm2godot-release-smoke-invalid-token",
            "files: __gm2godot_release_smoke_missing__/"
            "${{ github.run_id }}-${{ github.run_attempt }}/must-not-exist",
            "fail_on_unmatched_files: true",
            "overwrite_files: false",
        ):
            with self.subTest(required=required):
                self.assertIn(required, publisher_step)
        for forbidden in ("secrets.", "${{ github.token }}", "draft:"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, publisher_step)
        self.assertEqual(content.count("continue-on-error: true"), 1)
        self.assertIn("if: ${{ always() }}", content)
        self.assertIn(
            "PUBLISHER_OUTCOME: ${{ steps.publisher_startup.outcome }}",
            content,
        )
        self.assertNotIn("publisher_startup.conclusion", content)

        assertion_script = _workflow_run_script(
            content,
            "Assert the publisher rejected the probe",
        )
        for outcome, expected_status in (
            ("failure", 0),
            ("success", 1),
            ("cancelled", 1),
            ("", 1),
        ):
            with self.subTest(outcome=outcome):
                environment = os.environ.copy()
                environment["PUBLISHER_OUTCOME"] = outcome
                result = subprocess.run(
                    ["bash", "-c", assertion_script],
                    cwd=PROJECT_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
                self.assertEqual(
                    result.returncode == 0,
                    expected_status == 0,
                    result.stderr,
                )

    def test_release_action_smoke_proves_publisher_entrypoint_loaded(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release-action-smoke.yml"
        content = workflow.read_text(encoding="utf-8")
        receipt_job = content[content.index("  publisher-startup-receipt:"):]
        expected_pattern = (
            "__gm2godot_release_smoke_missing__/12345-2/must-not-exist"
        )

        for required in (
            "name: publisher-startup-receipt",
            "needs: publisher-startup",
            "permissions:\n      actions: read",
            "GH_TOKEN: ${{ github.token }}",
            "jobs?per_page=100",
            "select(.name == \"publisher-startup\") | .id",
            "for retry in 1 2 3 4 5",
            "actions/jobs/${job_id}/logs",
            "Pattern '$EXPECTED_PATTERN' does not match any files.",
        ):
            with self.subTest(required=required):
                self.assertIn(required, receipt_job)
        for forbidden in ("contents: read", "contents: write", "actions/checkout"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, receipt_job)

        script = _workflow_run_script(
            content,
            "Verify the action-originated publisher rejection",
        )
        for case, job_ids, log_text, expected_status in (
            (
                "action diagnostic",
                "98765\n",
                f"Error: Pattern '{expected_pattern}' does not match any files.\n",
                0,
            ),
            (
                "different failure",
                "98765\n",
                "Error: Unable to resolve action\n",
                1,
            ),
            ("missing publisher job", "", "", 1),
            ("duplicate publisher jobs", "98765\n98766\n", "", 1),
        ):
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as temp_directory:
                    root = Path(temp_directory)
                    tools_dir = root / "tools"
                    tools_dir.mkdir()
                    fake_gh = tools_dir / "gh"
                    fake_gh.write_text(
                        f"#!{sys.executable}\n"
                        """import os
import sys

endpoint = next(
    (argument for argument in sys.argv[1:] if argument.startswith("repos/")),
    "",
)
if endpoint.endswith("jobs?per_page=100"):
    print(os.environ["FAKE_JOB_IDS"], end="")
    raise SystemExit(0)
if endpoint.endswith("actions/jobs/98765/logs"):
    print(os.environ["FAKE_PUBLISHER_LOG"], end="")
    raise SystemExit(0)
print(f"unexpected gh endpoint: {endpoint}", file=sys.stderr)
raise SystemExit(97)
""",
                        encoding="utf-8",
                    )
                    fake_gh.chmod(0o755)
                    environment = os.environ.copy()
                    environment.update(
                        {
                            "EXPECTED_PATTERN": expected_pattern,
                            "FAKE_JOB_IDS": job_ids,
                            "FAKE_PUBLISHER_LOG": log_text,
                            "GH_TOKEN": "read-only-test-token",
                            "PATH": os.pathsep.join(
                                (str(tools_dir), environment.get("PATH", ""))
                            ),
                            "REPOSITORY": "Infiland/GM2Godot",
                            "RUN_ATTEMPT": "2",
                            "RUN_ID": "12345",
                            "RUNNER_TEMP": str(root),
                        }
                    )
                    result = subprocess.run(
                        ["bash", "-c", script],
                        cwd=root,
                        check=False,
                        capture_output=True,
                        text=True,
                        env=environment,
                    )

                self.assertEqual(
                    result.returncode == 0,
                    expected_status == 0,
                    result.stderr,
                )

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

    def test_release_generates_portable_sha256_manifest(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Generate SHA256SUMS")
        create_release_step = content[
            content.index("      - name: Create release\n"):
        ]

        expected_lines = [
            f"{hashlib.sha256(payload).hexdigest()}  {Path(relative_path).name}\n"
            for relative_path, payload in RELEASE_PAYLOADS
        ]
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            _write_release_payloads(root)

            result = subprocess.run(
                ["/bin/bash", "-c", script],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = root / "artifacts" / "SHA256SUMS"
            self.assertEqual(
                manifest.read_bytes(),
                "".join(expected_lines).encode("ascii"),
            )

            verification_root = root / "downloaded-release"
            verification_root.mkdir()
            for relative_path, _ in RELEASE_PAYLOADS:
                source = root / relative_path
                (verification_root / source.name).write_bytes(source.read_bytes())
            (verification_root / manifest.name).write_bytes(manifest.read_bytes())
            verification_commands = {
                "linux": [
                    "sha256sum",
                    "--check",
                    "--strict",
                    manifest.name,
                ],
                "darwin": [
                    "shasum",
                    "-a",
                    "256",
                    "-c",
                    manifest.name,
                ],
            }
            verification_command = verification_commands.get(sys.platform)
            if verification_command is not None:
                verification = subprocess.run(
                    verification_command,
                    cwd=verification_root,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(verification.returncode, 0, verification.stderr)

        self.assertLess(
            content.index("      - name: Generate SHA256SUMS\n"),
            content.index("      - name: Create release\n"),
        )
        files_marker = "          files: |\n"
        _, separator, files_remainder = create_release_step.partition(files_marker)
        self.assertTrue(separator)
        release_files: list[str] = []
        for line in files_remainder.splitlines():
            if not line.startswith("            "):
                break
            release_files.append(line.strip())
        self.assertEqual(
            release_files,
            [
                "artifacts/GM2Godot-windows/GM2Godot-windows.zip",
                "artifacts/GM2Godot-macos/GM2Godot-macos.zip",
                "artifacts/GM2Godot-macos/GM2Godot-macos.dmg",
                "artifacts/GM2Godot-linux/GM2Godot-linux.zip",
                "artifacts/SHA256SUMS",
            ],
        )

    def test_release_checksum_manifest_rejects_invalid_payloads(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Generate SHA256SUMS")
        invalid_cases = [
            (Path(relative_path), invalid_kind)
            for relative_path, _ in RELEASE_PAYLOADS
            for invalid_kind in ("missing", "empty")
        ]
        invalid_cases.extend(
            (
                (Path(RELEASE_PAYLOADS[1][0]), "directory"),
                (Path(RELEASE_PAYLOADS[1][0]), "symlink"),
            )
        )

        for invalid_path, invalid_kind in invalid_cases:
            if invalid_kind == "symlink" and os.name == "nt":
                continue
            with self.subTest(
                invalid_path=invalid_path.as_posix(),
                invalid_kind=invalid_kind,
            ):
                with tempfile.TemporaryDirectory() as temp_directory:
                    root = Path(temp_directory)
                    _write_release_payloads(root)
                    target = root / invalid_path
                    target.unlink()
                    if invalid_kind == "empty":
                        target.touch()
                    elif invalid_kind == "directory":
                        target.mkdir()
                    elif invalid_kind == "symlink":
                        referent = root / "symlink-referent"
                        referent.write_bytes(b"not an accepted direct payload\n")
                        target.symlink_to(referent)

                    result = subprocess.run(
                        ["/bin/bash", "-c", script],
                        cwd=root,
                        check=False,
                        capture_output=True,
                        text=True,
                    )

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        "Missing, non-regular, symlinked, or empty release "
                        f"payload: {invalid_path.as_posix()}",
                        result.stderr,
                    )
                    self.assertFalse((root / "artifacts" / "SHA256SUMS").exists())

    def test_release_checksum_manifest_rejects_existing_destination(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Generate SHA256SUMS")

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            _write_release_payloads(root)
            manifest = root / "artifacts" / "SHA256SUMS"
            manifest.write_bytes(b"preserve this unexpected file\n")

            result = subprocess.run(
                ["/bin/bash", "-c", script],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "Checksum manifest path already exists: artifacts/SHA256SUMS",
                result.stderr,
            )
            self.assertEqual(
                manifest.read_bytes(),
                b"preserve this unexpected file\n",
            )

    def test_release_checksum_manifest_rejects_malformed_digest_output(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Generate SHA256SUMS")

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            _write_release_payloads(root)
            tools_dir = root / "tools"
            tools_dir.mkdir()
            fake_sha256sum = tools_dir / "sha256sum"
            fake_sha256sum.write_text(
                "#!/bin/sh\nprintf 'not-a-digest  %s\\n' \"$2\"\n",
                encoding="utf-8",
            )
            fake_sha256sum.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = os.pathsep.join(
                (str(tools_dir), environment.get("PATH", ""))
            )

            result = subprocess.run(
                ["/bin/bash", "-c", script],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "sha256sum returned an invalid digest for "
                "artifacts/GM2Godot-linux/GM2Godot-linux.zip",
                result.stderr,
            )
            self.assertFalse((root / "artifacts" / "SHA256SUMS").exists())

    def test_release_checksum_manifest_cleans_up_after_hash_failure(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Generate SHA256SUMS")

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            _write_release_payloads(root)
            tools_dir = root / "tools"
            tools_dir.mkdir()
            fake_sha256sum = tools_dir / "sha256sum"
            fake_sha256sum.write_text(
                "#!/bin/sh\n"
                "count=0\n"
                "if [ -f \"$FAKE_SHA256SUM_CALLS\" ]; then\n"
                "  read -r count < \"$FAKE_SHA256SUM_CALLS\" || true\n"
                "fi\n"
                "count=$((count + 1))\n"
                "printf '%s\\n' \"$count\" > \"$FAKE_SHA256SUM_CALLS\"\n"
                "printf '%064d  %s\\n' 0 \"$2\"\n"
                "if [ \"$count\" -eq 2 ]; then\n"
                "  exit 73\n"
                "fi\n",
                encoding="utf-8",
            )
            fake_sha256sum.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "FAKE_SHA256SUM_CALLS": str(root / "sha256sum-calls"),
                    "PATH": os.pathsep.join(
                        (str(tools_dir), environment.get("PATH", ""))
                    ),
                }
            )

            result = subprocess.run(
                ["/bin/bash", "-c", script],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 73, result.stderr)
            self.assertFalse((root / "artifacts" / "SHA256SUMS").exists())
            self.assertEqual(
                list((root / "artifacts").glob(".SHA256SUMS.*")),
                [],
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

    def test_release_state_preflight_allows_only_prefixed_tags_across_pages(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages: list[list[dict[str, object]]] = [
            [
                {
                    "id": 1,
                    "tag_name": f"{RELEASE_PREFLIGHT_TEST_TAG}0",
                    "draft": True,
                    "prerelease": False,
                    "assets": [],
                    "html_url": "https://example.invalid/prefix",
                }
            ],
            [
                {
                    "id": 2,
                    "tag_name": f"{RELEASE_PREFLIGHT_TEST_TAG}-rc1",
                    "draft": False,
                    "prerelease": True,
                    "assets": [],
                    "html_url": "https://example.invalid/prerelease",
                }
            ],
        ]

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            result = _run_release_state_preflight(
                content,
                root,
                json.dumps(release_pages),
            )
            calls = (root / "gh-calls.txt").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, "call\ncall\ncall\n")
        self.assertNotIn("Exact release state already exists", result.stderr)

    def test_release_state_preflight_rejects_exact_partial_draft_on_later_page(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages: list[list[dict[str, object]]] = [
            [
                {
                    "id": 1,
                    "tag_name": f"{RELEASE_PREFLIGHT_TEST_TAG}0",
                    "draft": False,
                    "prerelease": False,
                    "assets": [],
                    "html_url": "https://example.invalid/prefix",
                }
            ],
            [
                {
                    "id": 726,
                    "tag_name": RELEASE_PREFLIGHT_TEST_TAG,
                    "draft": True,
                    "prerelease": False,
                    "assets": [{"id": 9, "name": "GM2Godot-linux.zip"}],
                    "html_url": "https://example.invalid/partial-draft",
                }
            ],
        ]

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            result = _run_release_state_preflight(
                content,
                root,
                json.dumps(release_pages),
            )
            calls = (root / "gh-calls.txt").read_text(encoding="utf-8")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, "call\n")
        self.assertIn(
            f"Exact release state already exists for {RELEASE_PREFLIGHT_TEST_TAG}",
            result.stderr,
        )
        self.assertIn("while its tag ref is absent", result.stderr)
        self.assertIn(
            "id=726 draft=True prerelease=False assets=1 "
            "url=https://example.invalid/partial-draft",
            result.stderr,
        )

    def test_release_state_preflight_rechecks_after_initial_absence(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        responses = (
            json.dumps([[]]),
            json.dumps(
                [
                    [
                        {
                            "id": 727,
                            "tag_name": RELEASE_PREFLIGHT_TEST_TAG,
                            "draft": True,
                            "prerelease": False,
                            "assets": [],
                            "html_url": "https://example.invalid/delayed-draft",
                        }
                    ]
                ]
            ),
        )

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            result = _run_release_state_preflight(
                content,
                root,
                responses,
            )
            calls = (root / "gh-calls.txt").read_text(encoding="utf-8")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, "call\ncall\n")
        self.assertIn(
            f"Exact release state already exists for {RELEASE_PREFLIGHT_TEST_TAG}",
            result.stderr,
        )
        self.assertIn("id=727 draft=True", result.stderr)

    def test_release_state_preflight_fails_closed_on_api_error(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            result = _run_release_state_preflight(
                content,
                root,
                json.dumps([[{"tag_name": RELEASE_PREFLIGHT_TEST_TAG}]]),
                gh_exit=42,
            )
            calls = (root / "gh-calls.txt").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 42)
        self.assertEqual(calls, "call\n")
        self.assertIn(
            "Authenticated release-state query failed for "
            f"{RELEASE_PREFLIGHT_TEST_TAG} (gh exit 42)",
            result.stderr,
        )
        self.assertNotIn("Exact release state already exists", result.stderr)

    def test_release_state_preflight_fails_closed_on_malformed_json(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            result = _run_release_state_preflight(content, root, "{not-json")
            calls = (root / "gh-calls.txt").read_text(encoding="utf-8")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, "call\n")
        self.assertIn("Unable to parse release listing", result.stderr)
        self.assertIn(
            "Release-state response could not be validated",
            result.stderr,
        )

    def test_release_state_preflight_fails_closed_on_invalid_schema(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        invalid_responses = {
            "top-level object": "{}",
            "page object": "[{}]",
            "non-object release": "[[42]]",
            "missing tag name": "[[{}]]",
            "empty tag name": '[[{"tag_name": ""}]]',
            "non-string tag name": '[[{"tag_name": 123}]]',
        }

        for case, response_text in invalid_responses.items():
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as temp_directory:
                    root = Path(temp_directory)
                    result = _run_release_state_preflight(
                        content,
                        root,
                        response_text,
                    )
                    calls = (root / "gh-calls.txt").read_text(encoding="utf-8")

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, "call\n")
                self.assertIn(
                    "Release-state response could not be validated",
                    result.stderr,
                )

    def test_release_state_preflight_requires_token_and_gh(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_directory:
            missing_token = _run_release_state_preflight(
                content,
                Path(temp_directory),
                "[]",
                token=None,
            )
        with tempfile.TemporaryDirectory() as temp_directory:
            missing_gh = _run_release_state_preflight(
                content,
                Path(temp_directory),
                "[]",
                install_gh=False,
            )
        with tempfile.TemporaryDirectory() as temp_directory:
            missing_python = _run_release_state_preflight(
                content,
                Path(temp_directory),
                "[]",
                install_python=False,
            )

        self.assertNotEqual(missing_token.returncode, 0)
        self.assertIn("Release preflight is missing GH_TOKEN", missing_token.stderr)
        self.assertNotEqual(missing_gh.returncode, 0)
        self.assertIn(
            "Required release-preflight tool is unavailable: gh",
            missing_gh.stderr,
        )
        self.assertNotEqual(missing_python.returncode, 0)
        self.assertIn(
            "Required release-preflight tool is unavailable: python",
            missing_python.stderr,
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
        build_guard = (
            "${{ !cancelled() && needs.get-version.result == 'success' && "
            f"{absence_guard} && (github.event_name == 'pull_request' || "
            "needs.release-state-preflight.result == 'success') }}"
        )
        release_guard = (
            "${{ !cancelled() && github.event_name != 'pull_request' && "
            "needs.get-version.result == 'success' && "
            f"{absence_guard} && "
            "needs.release-state-preflight.result == 'success' && "
            "needs.build.result == 'success' }}"
        )

        self.assertIn("set -euo pipefail", script)
        self.assertIn(
            'git ls-remote --exit-code --refs origin "$tag_ref"',
            script,
        )
        self.assertIn('tag_ref="refs/tags/v${{ steps.version.outputs.version }}"', script)
        self.assertNotIn("git rev-parse", script)
        self.assertEqual(build_job_conditions, [f"    if: {build_guard}"])
        self.assertEqual(
            release_job_conditions,
            [f"    if: {release_guard}"],
        )

    def test_release_publication_guards_cover_the_complete_workflow(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        tag_check_marker = "      - name: Check if tag already exists\n"
        preflight_marker = "      - name: Check for incomplete release state\n"
        build_marker = "\n  build:\n"
        get_version_job = content[
            content.index("  get-version:"):content.index(
                "  release-state-preflight:"
            )
        ]
        preflight_job = content[
            content.index("  release-state-preflight:"):content.index(build_marker)
        ]
        preflight_metadata = content[
            content.index(preflight_marker):content.index(
                "        run: |\n",
                content.index(preflight_marker),
            )
        ]
        release_job = content[content.index("  release:"):]
        build_job = content[content.index(build_marker):content.index("  release:")]
        preflight_script = _workflow_run_script(
            content,
            "Check for incomplete release state",
        )
        preflight_job_conditions = [
            line.strip()
            for line in preflight_job.splitlines()
            if line.startswith("    if: ")
        ]
        preflight_step_conditions = [
            line.strip()
            for line in preflight_metadata.splitlines()
            if line.strip().startswith("if: ")
        ]
        create_release_step = release_job[
            release_job.index("      - name: Create release\n"):
        ]

        self.assertIn("permissions:\n  contents: read", content)
        self.assertIn(
            "concurrency:\n"
            "  group: ${{ github.event_name == 'pull_request' && "
            "format('gm2godot-release-pr-{0}', github.run_id) || "
            "'gm2godot-release-publisher' }}\n"
            "  cancel-in-progress: false",
            content,
        )
        self.assertNotIn("\n  queue:", content)
        self.assertLess(content.index(tag_check_marker), content.index(preflight_marker))
        self.assertLess(content.index(preflight_marker), content.index(build_marker))
        self.assertNotIn("    permissions:", get_version_job)
        self.assertNotIn("write-all", get_version_job)
        self.assertNotIn("gh api", get_version_job)
        self.assertIn("permissions:\n      contents: write", preflight_job)
        self.assertNotIn("actions/checkout", preflight_job)
        self.assertNotIn("      - uses:", preflight_job)
        self.assertNotIn("pip install", preflight_job)
        self.assertEqual(content.count("contents: write"), 2)
        self.assertEqual(
            preflight_job_conditions,
            [
                "if: github.event_name != 'pull_request' && "
                "needs.get-version.outputs.tag_exists == 'false'"
            ],
        )
        self.assertEqual(preflight_step_conditions, [])
        self.assertNotIn("continue-on-error:", preflight_metadata)
        self.assertEqual(content.count(preflight_marker), 1)
        self.assertEqual(content.count("gh api --paginate --slurp"), 1)
        self.assertIn(
            "needs: [get-version, release-state-preflight]",
            build_job,
        )
        self.assertNotIn("always()", build_job)
        self.assertIn(
            "needs: [get-version, release-state-preflight, build]",
            release_job,
        )
        self.assertNotIn("always()", release_job)
        self.assertIn("GH_TOKEN: ${{ github.token }}", preflight_metadata)
        self.assertIn(
            "RELEASE_TAG: v${{ needs.get-version.outputs.version }}",
            preflight_metadata,
        )
        self.assertIn(
            "RELEASE_PREFLIGHT_RETRY_DELAY_SECONDS: '1'",
            preflight_metadata,
        )
        self.assertIn("gh api --paginate --slurp", preflight_script)
        self.assertNotIn("jq", preflight_script)
        self.assertIn("permissions:\n      contents: write", release_job)
        self.assertIn(
            "uses: softprops/action-gh-release@"
            "3d0d9888cb7fd7b750713d6e236d1fcb99157228",
            create_release_step,
        )
        self.assertEqual(
            [
                line.strip()
                for line in create_release_step.splitlines()
                if "overwrite_files:" in line
            ],
            ["overwrite_files: false"],
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
        self.assertIn("archive: true", upload_step)
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
