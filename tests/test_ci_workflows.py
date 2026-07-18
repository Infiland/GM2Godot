from __future__ import annotations

from collections.abc import Sequence
import copy
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
import zlib
from pathlib import Path
from typing import cast


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
EXISTING_RELEASE_TEST_TAG = "v999.123.457"
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
RELEASE_ARCHIVE_MEMBERS = {
    "GM2Godot-windows": (("GM2Godot-windows.zip", b"windows"),),
    "GM2Godot-macos": (
        ("GM2Godot-macos.dmg", b"macos-dmg"),
        ("GM2Godot-macos.zip", b"macos-zip"),
    ),
    "GM2Godot-linux": (("GM2Godot-linux.zip", b"linux"),),
}
EXISTING_RELEASE_PAYLOAD_NAMES = (
    "GM2Godot-linux.zip",
    "GM2Godot-macos.dmg",
    "GM2Godot-macos.zip",
    "GM2Godot-windows.zip",
)
EXISTING_RELEASE_ASSET_NAMES = EXISTING_RELEASE_PAYLOAD_NAMES + ("SHA256SUMS",)
EXISTING_RELEASE_BASE_PAYLOADS = {
    "GM2Godot-linux.zip": b"existing Linux payload\n",
    "GM2Godot-macos.dmg": b"existing macOS DMG payload\n",
    "GM2Godot-macos.zip": b"existing macOS ZIP payload\n",
    "GM2Godot-windows.zip": b"existing Windows payload\n",
}


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


def _existing_release_fixture() -> tuple[
    list[list[dict[str, object]]],
    list[list[dict[str, object]]],
    dict[str, object],
    dict[int, bytes],
]:
    payloads = dict(EXISTING_RELEASE_BASE_PAYLOADS)
    manifest = "".join(
        f"{hashlib.sha256(payloads[name]).hexdigest()}  {name}\n"
        for name in EXISTING_RELEASE_PAYLOAD_NAMES
    ).encode("ascii")
    payloads["SHA256SUMS"] = manifest

    assets: list[dict[str, object]] = []
    payloads_by_id: dict[int, bytes] = {}
    for offset, name in enumerate(EXISTING_RELEASE_ASSET_NAMES, start=1):
        asset_id = 740_000 + offset
        payload = payloads[name]
        assets.append(
            {
                "digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                "download_count": offset,
                "id": asset_id,
                "name": name,
                "size": len(payload),
                "state": "uploaded",
            }
        )
        payloads_by_id[asset_id] = payload

    exact_release: dict[str, object] = {
        "assets": [],
        "draft": False,
        "html_url": "https://github.com/Infiland/GM2Godot/releases/tag/"
        f"{EXISTING_RELEASE_TEST_TAG}",
        "id": 740,
        "prerelease": False,
        "published_at": "2026-07-18T21:00:41Z",
        "tag_name": EXISTING_RELEASE_TEST_TAG,
    }
    prefix_release: dict[str, object] = {
        "draft": False,
        "html_url": "https://example.invalid/prefix",
        "id": 741,
        "prerelease": False,
        "published_at": "2026-07-18T20:00:00Z",
        "tag_name": f"{EXISTING_RELEASE_TEST_TAG}0",
    }
    release_pages = [[prefix_release], [exact_release]]
    asset_pages = [[assets[2], assets[0]], [assets[4], assets[1], assets[3]]]
    tag_response: dict[str, object] = {
        "object": {
            "sha": "9" * 40,
            "type": "commit",
            "url": "https://api.github.com/repos/Infiland/GM2Godot/git/commits/"
            + "9" * 40,
        },
        "ref": f"refs/tags/{EXISTING_RELEASE_TEST_TAG}",
    }
    return release_pages, asset_pages, tag_response, payloads_by_id


def _run_existing_release_integrity(
    content: str,
    root: Path,
    release_responses: str | tuple[str, ...],
    asset_responses: str | tuple[str, ...],
    tag_responses: str | tuple[str, ...],
    payloads_by_id: dict[int, bytes],
    *,
    gh_failures: dict[str, int] | None = None,
    token: str | None = "test-token",
    repository: str | None = "Infiland/GM2Godot",
    release_tag: str | None = EXISTING_RELEASE_TEST_TAG,
    missing_tool: str | None = None,
    sha256sum_exit: int = 0,
) -> subprocess.CompletedProcess[str]:
    script = _workflow_run_script(content, "Verify existing tagged release")
    tools_dir = root / "tools"
    tools_dir.mkdir()
    response_dir = root / "responses"
    response_dir.mkdir()
    payload_dir = root / "payloads"
    payload_dir.mkdir()
    call_log = root / "existing-release-gh-calls.jsonl"
    state_path = root / "existing-release-gh-state.json"
    sha_log = root / "existing-release-sha256sum-calls.jsonl"

    def write_responses(
        name: str,
        responses: str | tuple[str, ...],
    ) -> list[Path]:
        response_values = (responses,) if isinstance(responses, str) else responses
        if not response_values:
            raise ValueError(f"{name} response sequence cannot be empty")
        paths: list[Path] = []
        for index, response in enumerate(response_values):
            path = response_dir / f"{name}-{index}.json"
            path.write_text(response, encoding="utf-8")
            paths.append(path)
        return paths

    release_paths = write_responses("releases", release_responses)
    asset_paths = write_responses("assets", asset_responses)
    tag_paths = write_responses("tag", tag_responses)
    expected_asset_release_ids: list[str] = []
    for release_path in release_paths:
        try:
            pages: object = json.loads(release_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            expected_asset_release_ids.append("")
            continue
        matches: list[dict[str, object]] = []
        if isinstance(pages, list):
            for page_value in cast(list[object], pages):
                if not isinstance(page_value, list):
                    continue
                for release_value in cast(list[object], page_value):
                    if not isinstance(release_value, dict):
                        continue
                    release = cast(dict[str, object], release_value)
                    if release.get("tag_name") == (release_tag or ""):
                        matches.append(release)
        release_id = matches[0].get("id") if len(matches) == 1 else None
        expected_asset_release_ids.append(
            str(release_id)
            if type(release_id) is int and release_id > 0
            else ""
        )
    payload_paths: dict[str, str] = {}
    for asset_id, payload in payloads_by_id.items():
        path = payload_dir / str(asset_id)
        path.write_bytes(payload)
        payload_paths[str(asset_id)] = str(path)

    fake_gh = tools_dir / "gh"
    fake_gh.write_text(
        f"#!{sys.executable}\n"
        + r'''from pathlib import Path
import json
import os
import re
import sys

arguments = sys.argv[1:]
call_log = Path(os.environ["FAKE_GH_CALL_LOG"])
with call_log.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(arguments, separators=(",", ":")) + "\n")

if os.environ.get("GH_TOKEN") != "test-token":
    print("fake gh did not receive the expected GH_TOKEN", file=sys.stderr)
    raise SystemExit(98)
if not arguments or arguments[0:3] != ["api", "--method", "GET"]:
    print(f"fake gh rejected non-GET arguments: {arguments!r}", file=sys.stderr)
    raise SystemExit(97)

endpoint = arguments[-1]
json_headers = [
    "-H",
    "Accept: application/vnd.github+json",
    "-H",
    "X-GitHub-Api-Version: 2026-03-10",
]
binary_headers = [
    "-H",
    "Accept: application/octet-stream",
    "-H",
    "X-GitHub-Api-Version: 2026-03-10",
]
release_endpoint = "repos/Infiland/GM2Godot/releases?per_page=100"
asset_list_pattern = re.compile(
    r"repos/Infiland/GM2Godot/releases/([1-9][0-9]*)/assets\?per_page=100\Z"
)
tag_endpoint = (
    "repos/Infiland/GM2Godot/git/ref/tags/" + os.environ["FAKE_RELEASE_TAG"]
)
download_pattern = re.compile(
    r"repos/Infiland/GM2Godot/releases/assets/([1-9][0-9]*)\Z"
)

state_path = Path(os.environ["FAKE_GH_STATE"])
if state_path.exists():
    state = json.loads(state_path.read_text(encoding="utf-8"))
else:
    state = {}

asset_list_match = asset_list_pattern.fullmatch(endpoint)
if endpoint == release_endpoint:
    if arguments[3:-1] != ["--paginate", "--slurp", *json_headers]:
        print(f"unexpected release-list arguments: {arguments!r}", file=sys.stderr)
        raise SystemExit(96)
    kind = "release"
elif asset_list_match is not None:
    if arguments[3:-1] != ["--paginate", "--slurp", *json_headers]:
        print(f"unexpected asset-list arguments: {arguments!r}", file=sys.stderr)
        raise SystemExit(95)
    kind = "assets"
elif endpoint == tag_endpoint:
    if arguments[3:-1] != json_headers:
        print(f"unexpected tag-ref arguments: {arguments!r}", file=sys.stderr)
        raise SystemExit(94)
    kind = "tag"
else:
    download_match = download_pattern.fullmatch(endpoint)
    if download_match is None:
        print(f"unexpected endpoint: {endpoint!r}", file=sys.stderr)
        raise SystemExit(93)
    if arguments[3:-1] != binary_headers:
        print(f"unexpected download arguments: {arguments!r}", file=sys.stderr)
        raise SystemExit(92)
    asset_id = download_match.group(1)
    kind = f"download:{asset_id}"

index = int(state.get(kind, 0))
state[kind] = index + 1
state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
if kind == "assets":
    expected_ids = json.loads(os.environ["FAKE_ASSET_RELEASE_IDS"])
    expected_id = expected_ids[min(index, len(expected_ids) - 1)]
    requested_id = asset_list_match.group(1)
    if requested_id != expected_id:
        print(
            f"asset-list release id mismatch: requested={requested_id} "
            f"expected={expected_id}",
            file=sys.stderr,
        )
        raise SystemExit(90)
failures = json.loads(os.environ["FAKE_GH_FAILURES"])
exit_status = int(failures.get(f"{kind}:{index}", failures.get(kind, 0)))

if kind.startswith("download:"):
    asset_id = kind.partition(":")[2]
    payload_paths = json.loads(os.environ["FAKE_ASSET_PAYLOADS"])
    payload_path = payload_paths.get(asset_id)
    if payload_path is None:
        print(f"missing fake asset payload for id {asset_id}", file=sys.stderr)
        raise SystemExit(91)
    sys.stdout.buffer.write(Path(payload_path).read_bytes())
else:
    response_key = {
        "release": "FAKE_RELEASE_RESPONSES",
        "assets": "FAKE_ASSET_RESPONSES",
        "tag": "FAKE_TAG_RESPONSES",
    }[kind]
    response_paths = json.loads(os.environ[response_key])
    response_path = response_paths[min(index, len(response_paths) - 1)]
    sys.stdout.write(Path(response_path).read_text(encoding="utf-8"))

raise SystemExit(exit_status)
''',
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    fake_sha256sum = tools_dir / "sha256sum"
    fake_sha256sum.write_text(
        f"#!{sys.executable}\n"
        + r'''from pathlib import Path
import hashlib
import json
import os
import re
import sys

arguments = sys.argv[1:]
call_log = Path(sys.argv[0]).resolve().parent.parent / (
    "existing-release-sha256sum-calls.jsonl"
)
with call_log.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(arguments, separators=(",", ":")) + "\n")
if arguments != ["--check", "--strict", "SHA256SUMS"]:
    print(f"unexpected sha256sum arguments: {arguments!r}", file=sys.stderr)
    raise SystemExit(89)
manifest = Path("SHA256SUMS").read_text(encoding="ascii")
pattern = re.compile(r"([0-9a-f]{64})  ([^/\\\n]+)\n")
offset = 0
for match in pattern.finditer(manifest):
    if match.start() != offset:
        raise SystemExit(1)
    expected, name = match.groups()
    actual = hashlib.sha256(Path(name).read_bytes()).hexdigest()
    if actual != expected:
        print(f"{name}: FAILED")
        raise SystemExit(1)
    print(f"{name}: OK")
    offset = match.end()
if offset != len(manifest):
    raise SystemExit(1)
raise SystemExit(int(os.environ["FAKE_SHA256SUM_EXIT"]))
''',
        encoding="utf-8",
    )
    fake_sha256sum.chmod(0o755)

    required_external_tools = (
        "cmp",
        "find",
        "mkdir",
        "mktemp",
        "python",
        "sed",
    )
    for tool in required_external_tools:
        if tool == missing_tool:
            continue
        source = Path(sys.executable) if tool == "python" else Path(
            shutil.which(tool) or f"/__missing__/{tool}"
        )
        if not source.exists():
            raise AssertionError(f"Test host is missing required tool: {tool}")
        (tools_dir / tool).symlink_to(source)
    if missing_tool == "gh":
        fake_gh.unlink()
    if missing_tool == "sha256sum":
        fake_sha256sum.unlink()

    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_ASSET_PAYLOADS": json.dumps(payload_paths, sort_keys=True),
            "FAKE_ASSET_RELEASE_IDS": json.dumps(expected_asset_release_ids),
            "FAKE_ASSET_RESPONSES": json.dumps([str(path) for path in asset_paths]),
            "FAKE_GH_CALL_LOG": str(call_log),
            "FAKE_GH_FAILURES": json.dumps(gh_failures or {}, sort_keys=True),
            "FAKE_GH_STATE": str(state_path),
            "FAKE_RELEASE_RESPONSES": json.dumps(
                [str(path) for path in release_paths]
            ),
            "FAKE_RELEASE_TAG": release_tag or "",
            "FAKE_SHA256SUM_EXIT": str(sha256sum_exit),
            "FAKE_TAG_RESPONSES": json.dumps([str(path) for path in tag_paths]),
            "PATH": str(tools_dir),
        }
    )
    if token is None:
        environment.pop("GH_TOKEN", None)
    else:
        environment["GH_TOKEN"] = token
    if repository is None:
        environment.pop("GITHUB_REPOSITORY", None)
    else:
        environment["GITHUB_REPOSITORY"] = repository
    if release_tag is None:
        environment.pop("RELEASE_TAG", None)
    else:
        environment["RELEASE_TAG"] = release_tag

    result = subprocess.run(
        ["/bin/bash", "-c", script],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if sha_log.exists() and sha_log != root / "existing-release-sha256sum-calls.jsonl":
        raise AssertionError("Fake sha256sum wrote its call log to an unexpected path")
    return result


def _write_raw_artifact_archive(
    root: Path,
    artifact_name: str,
    members: Sequence[tuple[str | zipfile.ZipInfo, bytes]],
) -> None:
    artifact_dir = root / "raw-artifacts" / artifact_name
    artifact_dir.mkdir(parents=True)
    with zipfile.ZipFile(
        artifact_dir / f"{artifact_name}.zip",
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for member_name, payload in members:
            if isinstance(member_name, str):
                member = zipfile.ZipInfo(member_name)
                member.create_system = 3
                member.external_attr = (stat.S_IFREG | 0o644) << 16
                member.compress_type = zipfile.ZIP_DEFLATED
            else:
                member = member_name
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"Duplicate name: .*",
                    category=UserWarning,
                )
                archive.writestr(member, payload)


def _strip_central_extra_field(archive_path: Path) -> None:
    data = bytearray(archive_path.read_bytes())
    central_offset = data.index(b"PK\x01\x02")
    name_length = int.from_bytes(data[central_offset + 28 : central_offset + 30], "little")
    extra_length = int.from_bytes(data[central_offset + 30 : central_offset + 32], "little")
    if extra_length == 0:
        raise AssertionError("test archive has no central extra field to strip")

    extra_offset = central_offset + 46 + name_length
    del data[extra_offset : extra_offset + extra_length]
    data[central_offset + 30 : central_offset + 32] = b"\0\0"
    end_offset = data.index(b"PK\x05\x06", central_offset)
    central_size = int.from_bytes(data[end_offset + 12 : end_offset + 16], "little")
    data[end_offset + 12 : end_offset + 16] = (central_size - extra_length).to_bytes(
        4,
        "little",
    )
    archive_path.write_bytes(data)


def _fake_unzip_environment(root: Path) -> tuple[dict[str, str], Path]:
    tools_dir = root / "tools"
    tools_dir.mkdir()
    call_log = root / "unzip-calls.log"
    fake_unzip = tools_dir / "unzip"
    fake_unzip.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$FAKE_UNZIP_CALL_LOG"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_unzip.chmod(0o755)

    environment = os.environ.copy()
    environment["FAKE_UNZIP_CALL_LOG"] = str(call_log)
    environment["PATH"] = os.pathsep.join(
        (str(tools_dir), environment.get("PATH", ""))
    )
    return environment, call_log


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
            "      - '.github/workflows/release-action-smoke.yml'\n"
            "      - 'scripts/release_publisher.py'\n",
            content,
        )
        self.assertEqual(content.count("permissions:"), 2)
        self.assertIn("\npermissions: {}\n", content)
        self.assertEqual(content.count("permissions: {}"), 1)
        self.assertIn("permissions:\n      contents: read", content)
        self.assertEqual(content.count("actions/checkout@"), 1)
        self.assertEqual(content.count("actions/setup-python@"), 1)
        self.assertIn("persist-credentials: false", content)
        self.assertIn("python-version: '3.12'", content)
        for forbidden in (
            "pull_request_target:",
            "workflow_dispatch:",
            "schedule:",
            "\n  push:",
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
            "softprops/action-gh-release",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, content)
        self.assertIn(
            "SMOKE_ASSET_ROOT: __gm2godot_release_smoke_missing__/"
            "${{ github.run_id }}-${{ github.run_attempt }}",
            content,
        )
        self.assertIn('"RELEASE_TAG": "v0.0.0"', content)

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
            "actions/checkout",
            "actions/setup-python",
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

        self.assertEqual(len(locations), 5, locations)

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
                ((RELEASE_SMOKE_SENTINEL, RELEASE_SMOKE_PAYLOAD),),
                None,
                0,
                "",
            ),
            (
                "wrong archive digest",
                ((RELEASE_SMOKE_SENTINEL, RELEASE_SMOKE_PAYLOAD),),
                "0" * 64,
                1,
                "Downloaded archive differs from the uploaded artifact",
            ),
            (
                "altered sentinel bytes",
                ((RELEASE_SMOKE_SENTINEL, b"altered\n"),),
                None,
                1,
                "",
            ),
            (
                "nested sentinel",
                ((f"nested/{RELEASE_SMOKE_SENTINEL}", RELEASE_SMOKE_PAYLOAD),),
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
        publisher_step = content[
            content.index(
                "      - name: Reject invalid local assets before GitHub API access\n"
            ):
        ]

        for required in (
            "SMOKE_TARGET_SHA: ${{ github.sha }}",
            "SMOKE_ASSET_ROOT: __gm2godot_release_smoke_missing__/",
            "from scripts import release_publisher",
            '"GITHUB_REF": "refs/heads/main"',
            '"GITHUB_REF_TYPE": "branch"',
            '"GITHUB_EVENT_NAME": "push"',
            '"GITHUB_TOKEN": "gm2godot-release-smoke-invalid-token"',
            '"RELEASE_TARGET_SHA": os.environ["SMOKE_TARGET_SHA"]',
            '"RELEASE_ASSET_ROOT": os.environ["SMOKE_ASSET_ROOT"]',
            "release_publisher.main(synthetic_environment)",
            'publisher_output" != *"Cannot open regular release asset"*',
            'receipt.get("stage") != "failed"',
            'failure.get("phase") != "seal-assets"',
            'receipt.get("mutation_intents") != []',
        ):
            with self.subTest(required=required):
                self.assertIn(required, publisher_step)
        for forbidden in (
            "secrets.",
            "${{ github.token }}",
            "softprops/action-gh-release",
            "continue-on-error:",
            "gh api",
            "python3 scripts/release_publisher.py",
            "\n          GITHUB_TOKEN:",
            "\n          GITHUB_REF:",
            "\n          GITHUB_REF_TYPE:",
            "\n          GITHUB_EVENT_NAME:",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, publisher_step)

    def test_release_action_smoke_executes_publisher_local_boundary(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release-action-smoke.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(
            content,
            "Reject invalid local assets before GitHub API access",
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            script_directory = root / "scripts"
            script_directory.mkdir()
            shutil.copy2(
                PROJECT_ROOT / "scripts" / "release_publisher.py",
                script_directory / "release_publisher.py",
            )
            environment = os.environ.copy()
            for variable in (
                "GITHUB_TOKEN",
                "RELEASE_ASSET_ROOT",
                "RELEASE_NAME",
                "RELEASE_PREFLIGHT_RETRY_DELAY_SECONDS",
                "RELEASE_RECEIPT_PATH",
                "RELEASE_TAG",
                "RELEASE_TARGET_SHA",
            ):
                environment.pop(variable, None)
            environment.update(
                {
                    "GITHUB_API_URL": "https://api.github.com",
                    "GITHUB_EVENT_NAME": "pull_request",
                    "GITHUB_REF": "refs/pull/756/merge",
                    "GITHUB_REF_TYPE": "branch",
                    "GITHUB_REPOSITORY": "Infiland/GM2Godot",
                    "GITHUB_RUN_ATTEMPT": "2",
                    "GITHUB_RUN_ID": "12345",
                    "GITHUB_SERVER_URL": "https://github.com",
                    "GITHUB_SHA": "a" * 40,
                    "SMOKE_ASSET_ROOT": "missing-assets",
                    "SMOKE_TARGET_SHA": "a" * 40,
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
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(
                (root / "release-receipt" / "release-publisher.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(receipt["stage"], "failed")
        self.assertEqual(receipt["failure"]["phase"], "seal-assets")
        self.assertEqual(receipt["mutation_intents"], [])

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
        self.assertIn(
            '[[ ! -f "$archive" || -L "$archive" || ! -s "$archive" ]]',
            content,
        )
        self.assertIn("with zipfile.ZipFile(archive_path) as archive:", content)
        self.assertIn("members = archive.infolist()", content)
        self.assertIn("member_name = member.orig_filename", content)
        self.assertIn("member.create_system != 3", content)
        self.assertIn("not stat.S_ISREG(unix_mode)", content)
        self.assertIn('local_header_struct = struct.Struct("<IHHHHHIIIHH")', content)
        self.assertIn("if local_extra:", content)
        self.assertIn("actual_counts = Counter(", content)
        self.assertIn("[[ -e artifacts || -L artifacts ]]", content)
        self.assertIn('mkdir -- "$destination"', content)
        self.assertIn('unzip -q "$archive" -d "artifacts/$name"', content)
        self.assertNotIn("unzip -Z", content)

        for artifact_name, members in RELEASE_ARCHIVE_MEMBERS.items():
            for member_name, _ in members:
                with self.subTest(release_file=member_name):
                    self.assertIn(
                        f"artifacts/{artifact_name}/{member_name}",
                        content,
                    )

        script = _workflow_run_script(content, "Extract verified artifact archives")
        self.assertLess(script.index("python3 - <<'PY'"), script.index("mkdir -- artifacts"))
        self.assertLess(script.index("members = archive.infolist()"), script.index("unzip -q"))
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            for artifact_name, members in RELEASE_ARCHIVE_MEMBERS.items():
                _write_raw_artifact_archive(root, artifact_name, members)

            result = subprocess.run(
                ["bash", "-c", script],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for artifact_name, members in RELEASE_ARCHIVE_MEMBERS.items():
                for member_name, payload in members:
                    with self.subTest(artifact=artifact_name, member=member_name):
                        extracted = root / "artifacts" / artifact_name / member_name
                        self.assertEqual(extracted.read_bytes(), payload)

    def test_release_rejects_existing_extraction_roots_before_unzip(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Extract verified artifact archives")

        for root_kind in ("directory", "symlink", "broken-symlink"):
            with self.subTest(root_kind=root_kind):
                with (
                    tempfile.TemporaryDirectory() as temp_directory,
                    tempfile.TemporaryDirectory() as outside_directory,
                ):
                    root = Path(temp_directory)
                    outside_root = Path(outside_directory)
                    for artifact_name, members in RELEASE_ARCHIVE_MEMBERS.items():
                        _write_raw_artifact_archive(root, artifact_name, members)

                    extraction_root = root / "artifacts"
                    broken_target = root / "missing-extraction-root"
                    if root_kind == "directory":
                        extraction_root.mkdir()
                    elif root_kind == "symlink":
                        extraction_root.symlink_to(
                            outside_root,
                            target_is_directory=True,
                        )
                    else:
                        extraction_root.symlink_to(
                            broken_target,
                            target_is_directory=True,
                        )
                    environment, unzip_log = _fake_unzip_environment(root)

                    result = subprocess.run(
                        ["bash", "-c", script],
                        cwd=root,
                        check=False,
                        capture_output=True,
                        text=True,
                        env=environment,
                    )

                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertIn(
                        "Release extraction root already exists: artifacts",
                        result.stderr,
                    )
                    self.assertFalse(unzip_log.exists())
                    self.assertEqual(list(outside_root.iterdir()), [])
                    self.assertFalse(broken_target.exists())

    def test_release_rejects_unsafe_or_unexpected_members_before_extraction(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Extract verified artifact archives")
        expected_linux = RELEASE_ARCHIVE_MEMBERS["GM2Godot-linux"][0]

        def typed_member(file_type: int) -> zipfile.ZipInfo:
            member = zipfile.ZipInfo("GM2Godot-linux.zip")
            member.create_system = 3
            member.external_attr = (file_type | 0o755) << 16
            return member

        def alternate_path_member() -> zipfile.ZipInfo:
            member = typed_member(stat.S_IFREG)
            encoded_member_name = b"GM2Godot-linux.zip"
            unicode_path_payload = (
                b"\x01"
                + zlib.crc32(encoded_member_name).to_bytes(4, "little")
                + b"../escape.bin"
            )
            member.extra = (
                b"\x75\x70"
                + len(unicode_path_payload).to_bytes(2, "little")
                + unicode_path_payload
            )
            return member

        dos_member = zipfile.ZipInfo("GM2Godot-linux.zip")
        dos_member.create_system = 0
        dos_member.external_attr = 0
        dos_directory_member = typed_member(stat.S_IFREG)
        dos_directory_member.external_attr |= 0x10

        cases = (
            (
                "traversal",
                (expected_linux, ("../escape.bin", b"escape")),
                "Unsafe archive member",
            ),
            (
                "posix-absolute",
                (),
                "Unsafe archive member",
            ),
            (
                "windows-drive-absolute",
                (expected_linux, ("C:/escape.bin", b"escape")),
                "Unsafe archive member",
            ),
            (
                "backslash-traversal",
                (expected_linux, ("..\\escape.bin", b"escape")),
                "Unsafe archive member",
            ),
            (
                "duplicate",
                (expected_linux, expected_linux),
                "Unexpected archive members",
            ),
            (
                "unexpected-extra",
                (expected_linux, ("unexpected.bin", b"extra")),
                "Unexpected archive members",
            ),
            (
                "newline-name",
                (expected_linux, ("unexpected\nmember.bin", b"extra")),
                "Unexpected archive members",
            ),
            (
                "missing-expected",
                (),
                "Unexpected archive members",
            ),
            (
                "symlink",
                ((typed_member(stat.S_IFLNK), b"target"),),
                "Non-regular archive member",
            ),
            (
                "directory",
                ((typed_member(stat.S_IFDIR), b""),),
                "Non-regular archive member",
            ),
            (
                "special-file",
                ((typed_member(stat.S_IFIFO), b""),),
                "Non-regular archive member",
            ),
            (
                "unsupported-origin-system",
                ((dos_member, b"linux"),),
                "Non-regular archive member",
            ),
            (
                "dos-directory-attribute",
                ((dos_directory_member, b"linux"),),
                "Non-regular archive member",
            ),
            (
                "alternate-path-extra-field",
                ((alternate_path_member(), b"linux"),),
                "Unsupported archive member metadata",
            ),
            (
                "local-only-alternate-path-extra-field",
                ((alternate_path_member(), b"linux"),),
                "Unsupported archive member metadata",
            ),
        )

        for case_name, invalid_members, error_fragment in cases:
            with self.subTest(case=case_name):
                with tempfile.TemporaryDirectory() as temp_directory:
                    root = Path(temp_directory)
                    absolute_escape = root.parent / f"{root.name}-absolute-escape.bin"
                    self.assertFalse(absolute_escape.exists())
                    members = (
                        (expected_linux, (str(absolute_escape), b"escape"))
                        if case_name == "posix-absolute"
                        else invalid_members
                    )
                    for artifact_name in ("GM2Godot-windows", "GM2Godot-macos"):
                        _write_raw_artifact_archive(
                            root,
                            artifact_name,
                            RELEASE_ARCHIVE_MEMBERS[artifact_name],
                        )
                    _write_raw_artifact_archive(root, "GM2Godot-linux", members)
                    if case_name == "local-only-alternate-path-extra-field":
                        _strip_central_extra_field(
                            root
                            / "raw-artifacts"
                            / "GM2Godot-linux"
                            / "GM2Godot-linux.zip"
                        )

                    if case_name == "duplicate":
                        archive_path = (
                            root
                            / "raw-artifacts"
                            / "GM2Godot-linux"
                            / "GM2Godot-linux.zip"
                        )
                        with zipfile.ZipFile(archive_path) as archive:
                            self.assertEqual(
                                [member.filename for member in archive.infolist()],
                                ["GM2Godot-linux.zip", "GM2Godot-linux.zip"],
                            )

                    environment, unzip_log = _fake_unzip_environment(root)

                    result = subprocess.run(
                        ["bash", "-c", script],
                        cwd=root,
                        check=False,
                        capture_output=True,
                        text=True,
                        env=environment,
                    )

                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertIn(error_fragment, result.stderr)
                    self.assertFalse(unzip_log.exists())
                    self.assertFalse((root / "artifacts").exists())
                    self.assertFalse(absolute_escape.exists())

    def test_release_rejects_inconsistent_local_metadata_before_extraction(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Extract verified artifact archives")
        mutations = (
            ("flags", 6, (0x800).to_bytes(2, "little")),
            ("compression", 8, (0).to_bytes(2, "little")),
            ("raw-name", 30, b"XM2Godot-linux.zip"),
        )

        for case_name, offset, replacement in mutations:
            with self.subTest(case=case_name):
                with tempfile.TemporaryDirectory() as temp_directory:
                    root = Path(temp_directory)
                    for artifact_name, members in RELEASE_ARCHIVE_MEMBERS.items():
                        _write_raw_artifact_archive(root, artifact_name, members)
                    linux_archive = (
                        root
                        / "raw-artifacts"
                        / "GM2Godot-linux"
                        / "GM2Godot-linux.zip"
                    )
                    archive_bytes = bytearray(linux_archive.read_bytes())
                    archive_bytes[offset : offset + len(replacement)] = replacement
                    linux_archive.write_bytes(archive_bytes)
                    environment, unzip_log = _fake_unzip_environment(root)

                    result = subprocess.run(
                        ["bash", "-c", script],
                        cwd=root,
                        check=False,
                        capture_output=True,
                        text=True,
                        env=environment,
                    )

                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertIn("Inconsistent local member metadata", result.stderr)
                    self.assertFalse(unzip_log.exists())
                    self.assertFalse((root / "artifacts").exists())

    def test_release_rejects_unreadable_zip_metadata_before_extraction(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Extract verified artifact archives")

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            for artifact_name, members in RELEASE_ARCHIVE_MEMBERS.items():
                _write_raw_artifact_archive(root, artifact_name, members)
            linux_archive = (
                root
                / "raw-artifacts"
                / "GM2Godot-linux"
                / "GM2Godot-linux.zip"
            )
            linux_archive.write_bytes(b"PK\x03\x04truncated")

            environment, unzip_log = _fake_unzip_environment(root)

            result = subprocess.run(
                ["bash", "-c", script],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertIn("Cannot read verified archive metadata", result.stderr)
            self.assertFalse(unzip_log.exists())
            self.assertFalse((root / "artifacts").exists())

    def test_release_extraction_fails_when_verified_archive_is_missing(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Extract verified artifact archives")

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            _write_raw_artifact_archive(
                root,
                "GM2Godot-windows",
                (("GM2Godot-windows.zip", b"windows"),),
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
            "Missing, non-regular, symlinked, or empty verified archive: "
            "raw-artifacts/GM2Godot-macos/GM2Godot-macos.zip",
            result.stderr,
        )

    def test_release_generates_portable_sha256_manifest(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        script = _workflow_run_script(content, "Generate SHA256SUMS")
        publisher_source = (
            PROJECT_ROOT / "scripts" / "release_publisher.py"
        ).read_text(encoding="utf-8")

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
            content.index("      - name: Publish run-owned release\n"),
        )
        for relative_path in (
            "GM2Godot-windows/GM2Godot-windows.zip",
            "GM2Godot-macos/GM2Godot-macos.zip",
            "GM2Godot-macos/GM2Godot-macos.dmg",
            "GM2Godot-linux/GM2Godot-linux.zip",
            "SHA256SUMS",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertIn(f'"{relative_path}"', publisher_source)

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

    def test_existing_release_integrity_accepts_canonical_reordered_state(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )
        final_release_pages = copy.deepcopy(release_pages)
        final_release_pages.reverse()
        for page in final_release_pages:
            for release in page:
                release["volatile_field"] = "changed"
        final_asset_pages = copy.deepcopy(asset_pages)
        flattened_assets = [asset for page in final_asset_pages for asset in page]
        for asset in flattened_assets:
            asset["download_count"] = 999_999
        final_asset_pages = [list(reversed(flattened_assets))]

        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            result = _run_existing_release_integrity(
                content,
                root,
                (
                    json.dumps(release_pages),
                    json.dumps(final_release_pages),
                ),
                (
                    json.dumps(asset_pages),
                    json.dumps(final_asset_pages),
                ),
                (json.dumps(tag_response), json.dumps(tag_response)),
                payloads_by_id,
            )
            calls = [
                json.loads(line)
                for line in (
                    root / "existing-release-gh-calls.jsonl"
                ).read_text(encoding="utf-8").splitlines()
            ]
            sha_calls = [
                json.loads(line)
                for line in (
                    root / "existing-release-sha256sum-calls.jsonl"
                ).read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 11)
        self.assertTrue(all(call[:3] == ["api", "--method", "GET"] for call in calls))
        self.assertEqual(
            [call[-1] for call in calls],
            [
                "repos/Infiland/GM2Godot/releases?per_page=100",
                "repos/Infiland/GM2Godot/releases/740/assets?per_page=100",
                f"repos/Infiland/GM2Godot/git/ref/tags/{EXISTING_RELEASE_TEST_TAG}",
                *[
                    f"repos/Infiland/GM2Godot/releases/assets/{740_000 + index}"
                    for index in range(1, 6)
                ],
                "repos/Infiland/GM2Godot/releases?per_page=100",
                "repos/Infiland/GM2Godot/releases/740/assets?per_page=100",
                f"repos/Infiland/GM2Godot/git/ref/tags/{EXISTING_RELEASE_TEST_TAG}",
            ],
        )
        forbidden_arguments = {
            "DELETE",
            "PATCH",
            "POST",
            "PUT",
            "--field",
            "--input",
            "--raw-field",
        }
        self.assertFalse(
            forbidden_arguments.intersection(argument for call in calls for argument in call)
        )
        download_endpoints = [
            call[-1]
            for call in calls
            if "/releases/assets/" in call[-1]
        ]
        self.assertEqual(
            download_endpoints,
            [
                f"repos/Infiland/GM2Godot/releases/assets/{740_000 + index}"
                for index in range(1, 6)
            ],
        )
        asset_list_endpoints = [
            call[-1]
            for call in calls
            if "/releases/740/assets?per_page=100" in call[-1]
        ]
        self.assertEqual(
            asset_list_endpoints,
            ["repos/Infiland/GM2Godot/releases/740/assets?per_page=100"] * 2,
        )
        self.assertEqual(sha_calls, [["--check", "--strict", "SHA256SUMS"]])
        self.assertEqual(result.stdout.count("Existing release snapshot:"), 2)
        self.assertIn(
            f"Existing release integrity verified for {EXISTING_RELEASE_TEST_TAG}",
            result.stdout,
        )

    def test_existing_release_integrity_rejects_release_identity_and_state(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )
        exact_release = release_pages[1][0]
        cases: dict[str, tuple[list[list[dict[str, object]]], str]] = {}

        prefix_only = copy.deepcopy(release_pages)
        prefix_only.pop()
        cases["prefix only"] = (prefix_only, "found 0")

        duplicate = copy.deepcopy(release_pages)
        duplicate[0].append(copy.deepcopy(exact_release))
        cases["duplicate exact"] = (duplicate, "found 2")

        mutations: tuple[tuple[str, str, object], ...] = (
            ("draft", "draft", True),
            ("prerelease", "prerelease", True),
            ("unpublished", "not published", None),
            ("malformed published timestamp", "malformed published_at", "not-a-time"),
            ("timezone-free published timestamp", "timezone-free", "2026-07-18T21:00:41"),
            ("boolean release id", "invalid id", True),
            ("invalid URL", "invalid URL", "javascript:invalid"),
        )
        for case, expected_error, value in mutations:
            mutated = copy.deepcopy(release_pages)
            release = mutated[1][0]
            if case == "prerelease":
                release["prerelease"] = value
            elif case in {
                "unpublished",
                "malformed published timestamp",
                "timezone-free published timestamp",
            }:
                release["published_at"] = value
            elif case == "boolean release id":
                release["id"] = value
            elif case == "invalid URL":
                release["html_url"] = value
            else:
                release["draft"] = value
            cases[case] = (mutated, expected_error)

        for case, (current_release_pages, expected_error) in cases.items():
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as temp_directory:
                    root = Path(temp_directory)
                    result = _run_existing_release_integrity(
                        content,
                        root,
                        json.dumps(current_release_pages),
                        json.dumps(asset_pages),
                        json.dumps(tag_response),
                        payloads_by_id,
                    )
                    calls = (
                        root / "existing-release-gh-calls.jsonl"
                    ).read_text(encoding="utf-8")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)
                self.assertNotIn("/releases/assets/740001", calls)

    def test_existing_release_harness_binds_assets_to_selected_release_id(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        expected_endpoint = (
            '"repos/${GITHUB_REPOSITORY}/releases/'
            '${release_id}/assets?per_page=100"'
        )
        wrong_endpoint = (
            '"repos/${GITHUB_REPOSITORY}/releases/741/assets?per_page=100"'
        )
        self.assertEqual(content.count(expected_endpoint), 1)
        mutated_content = content.replace(expected_endpoint, wrong_endpoint, 1)
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )

        with tempfile.TemporaryDirectory() as temp_directory:
            result = _run_existing_release_integrity(
                mutated_content,
                Path(temp_directory),
                json.dumps(release_pages),
                json.dumps(asset_pages),
                json.dumps(tag_response),
                payloads_by_id,
            )

        self.assertEqual(result.returncode, 90)
        self.assertIn(
            "asset-list release id mismatch: requested=741 expected=740",
            result.stderr,
        )

    def test_existing_release_integrity_rejects_asset_inventory_and_metadata(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )
        base_assets = [asset for page in asset_pages for asset in page]
        cases: dict[str, tuple[Sequence[object], str]] = {}

        cases["missing asset"] = (base_assets[:-1], "invalid asset inventory")
        cases["missing checksum asset"] = (
            [asset for asset in base_assets if asset.get("name") != "SHA256SUMS"],
            "invalid asset inventory",
        )
        extra_assets = copy.deepcopy(base_assets)
        extra_assets.append(
            {
                "digest": "sha256:" + "1" * 64,
                "id": 999_001,
                "name": "unexpected.zip",
                "size": 1,
                "state": "uploaded",
            }
        )
        cases["extra asset"] = (extra_assets, "invalid asset inventory")
        duplicate_name = copy.deepcopy(base_assets)
        duplicate_name[-1]["name"] = duplicate_name[0]["name"]
        cases["duplicate name"] = (duplicate_name, "invalid asset inventory")
        duplicate_checksum = copy.deepcopy(base_assets)
        duplicate_checksum[-1]["name"] = "SHA256SUMS"
        cases["duplicate checksum asset"] = (
            duplicate_checksum,
            "invalid asset inventory",
        )

        metadata_mutations: tuple[tuple[str, str, object], ...] = (
            ("duplicate id", "Duplicate asset id", base_assets[0]["id"]),
            ("starter state", "not uploaded", "starter"),
            ("empty size", "empty or has invalid size", 0),
            ("boolean size", "empty or has invalid size", True),
            ("string size", "empty or has invalid size", "1"),
            ("boolean id", "Invalid asset id", True),
            ("string id", "Invalid asset id", "740002"),
            ("missing state", "not uploaded", None),
            ("uppercase digest", "invalid SHA-256 digest", "sha256:" + "A" * 64),
            ("missing digest", "invalid SHA-256 digest", None),
            ("wrong digest algorithm", "invalid SHA-256 digest", "sha512:" + "a" * 64),
            ("short digest", "invalid SHA-256 digest", "sha256:" + "a" * 63),
            ("missing digest prefix", "invalid SHA-256 digest", "a" * 64),
        )
        for case, expected_error, value in metadata_mutations:
            mutated = copy.deepcopy(base_assets)
            target = mutated[1]
            if case == "duplicate id":
                target["id"] = value
            elif case in {"empty size", "boolean size", "string size"}:
                target["size"] = value
            elif case in {"boolean id", "string id"}:
                target["id"] = value
            elif case in {"starter state", "missing state"}:
                target["state"] = value
            else:
                target["digest"] = value
            cases[case] = (mutated, expected_error)
        cases["non-object asset"] = ([*copy.deepcopy(base_assets[:-1]), 42], "non-object")

        for case, (assets, expected_error) in cases.items():
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as temp_directory:
                    root = Path(temp_directory)
                    result = _run_existing_release_integrity(
                        content,
                        root,
                        json.dumps(release_pages),
                        json.dumps([assets]),
                        json.dumps(tag_response),
                        payloads_by_id,
                    )
                    calls = (
                        root / "existing-release-gh-calls.jsonl"
                    ).read_text(encoding="utf-8")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)
                self.assertIn("id=740", result.stderr)
                self.assertIn(
                    "https://github.com/Infiland/GM2Godot/releases/tag/"
                    f"{EXISTING_RELEASE_TEST_TAG}",
                    result.stderr,
                )
                self.assertNotIn("/releases/assets/740001", calls)

    def test_existing_release_integrity_fails_closed_on_every_api_boundary(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )
        cases = (
            ("initial release list", "release:0", 41, "release-list query failed"),
            ("initial asset list", "assets:0", 42, "release-asset query failed"),
            ("initial tag", "tag:0", 43, "tag-ref query failed"),
            ("final release list", "release:1", 44, "release-list query failed"),
            ("final asset list", "assets:1", 45, "release-asset query failed"),
            ("final tag", "tag:1", 46, "tag-ref query failed"),
        )

        for case, failure_key, exit_status, expected_error in cases:
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as temp_directory:
                    result = _run_existing_release_integrity(
                        content,
                        Path(temp_directory),
                        json.dumps(release_pages),
                        json.dumps(asset_pages),
                        json.dumps(tag_response),
                        payloads_by_id,
                        gh_failures={failure_key: exit_status},
                    )

                self.assertEqual(result.returncode, exit_status)
                self.assertIn(expected_error, result.stderr)
                self.assertIn(f"gh exit {exit_status}", result.stderr)
                if failure_key.startswith(("assets:", "tag:")):
                    self.assertIn("Existing release candidate: id=740 url=", result.stderr)

    def test_existing_release_integrity_rejects_malformed_api_responses(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )
        malformed_release_cases = {
            "invalid JSON": "{not-json",
            "top-level object": "{}",
            "page object": "[{}]",
            "non-object release": "[[42]]",
            "missing tag name": "[[{}]]",
            "empty tag name": '[[{"tag_name": ""}]]',
        }
        for case, response in malformed_release_cases.items():
            with self.subTest(scope="release", case=case):
                with tempfile.TemporaryDirectory() as temp_directory:
                    result = _run_existing_release_integrity(
                        content,
                        Path(temp_directory),
                        response,
                        json.dumps(asset_pages),
                        json.dumps(tag_response),
                        payloads_by_id,
                    )
                self.assertNotEqual(result.returncode, 0)

        malformed_asset_cases = {
            "invalid JSON": "{not-json",
            "top-level object": "{}",
            "page object": "[{}]",
            "non-object asset": "[[42]]",
        }
        for case, response in malformed_asset_cases.items():
            with self.subTest(scope="assets", case=case):
                with tempfile.TemporaryDirectory() as temp_directory:
                    result = _run_existing_release_integrity(
                        content,
                        Path(temp_directory),
                        json.dumps(release_pages),
                        response,
                        json.dumps(tag_response),
                        payloads_by_id,
                    )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("release asset", result.stderr.lower())

        malformed_tag_cases: dict[str, object] = {
            "array": [],
            "wrong ref": {
                **tag_response,
                "ref": f"refs/tags/{EXISTING_RELEASE_TEST_TAG}0",
            },
            "missing object": {
                "ref": f"refs/tags/{EXISTING_RELEASE_TEST_TAG}",
            },
            "wrong object type": {
                **tag_response,
                "object": {"sha": "9" * 40, "type": "blob"},
            },
            "malformed SHA": {
                **tag_response,
                "object": {"sha": "not-a-sha", "type": "commit"},
            },
        }
        for case, response in malformed_tag_cases.items():
            with self.subTest(scope="tag", case=case):
                with tempfile.TemporaryDirectory() as temp_directory:
                    result = _run_existing_release_integrity(
                        content,
                        Path(temp_directory),
                        json.dumps(release_pages),
                        json.dumps(asset_pages),
                        json.dumps(response),
                        payloads_by_id,
                    )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("tag", result.stderr.lower())

    def test_existing_release_integrity_rejects_each_failed_asset_download(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )

        for asset_id in sorted(payloads_by_id):
            with self.subTest(asset_id=asset_id):
                with tempfile.TemporaryDirectory() as temp_directory:
                    result = _run_existing_release_integrity(
                        content,
                        Path(temp_directory),
                        json.dumps(release_pages),
                        json.dumps(asset_pages),
                        json.dumps(tag_response),
                        payloads_by_id,
                        gh_failures={f"download:{asset_id}": 52},
                    )

                self.assertEqual(result.returncode, 52)
                self.assertIn("Failed to download existing release asset", result.stderr)
                self.assertIn(f"id={asset_id}", result.stderr)
                self.assertIn("release_id=740", result.stderr)
                self.assertIn(
                    "https://github.com/Infiland/GM2Godot/releases/tag/"
                    f"{EXISTING_RELEASE_TEST_TAG}",
                    result.stderr,
                )

    def test_existing_release_integrity_rejects_download_size_and_digest_mismatch(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )
        asset_id = 740_001
        cases = {
            "empty": (b"", "size mismatch"),
            "truncated": (payloads_by_id[asset_id][:-1], "size mismatch"),
            "oversized": (payloads_by_id[asset_id] + b"X", "size mismatch"),
            "same-size wrong bytes": (
                b"X" * len(payloads_by_id[asset_id]),
                "digest mismatch",
            ),
        }

        for case, (replacement, expected_error) in cases.items():
            with self.subTest(case=case):
                mutated_payloads = dict(payloads_by_id)
                mutated_payloads[asset_id] = replacement
                with tempfile.TemporaryDirectory() as temp_directory:
                    result = _run_existing_release_integrity(
                        content,
                        Path(temp_directory),
                        json.dumps(release_pages),
                        json.dumps(asset_pages),
                        json.dumps(tag_response),
                        mutated_payloads,
                    )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)
                self.assertIn("release_id=740", result.stderr)
                self.assertIn(
                    "https://github.com/Infiland/GM2Godot/releases/tag/"
                    f"{EXISTING_RELEASE_TEST_TAG}",
                    result.stderr,
                )

    def test_existing_release_integrity_rejects_noncanonical_manifests(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )
        manifest_id = 740_005
        canonical = payloads_by_id[manifest_id]
        lines = canonical.splitlines(keepends=True)
        variants = {
            "CRLF": canonical.replace(b"\n", b"\r\n"),
            "missing final newline": canonical[:-1],
            "missing entry": b"".join(lines[:-1]),
            "duplicate entry": canonical + lines[-1],
            "reordered": b"".join(reversed(lines)),
            "extra blank line": canonical + b"\n",
            "extra valid entry": canonical
            + b"0" * 64
            + b"  GM2Godot-linux.dmg\n",
            "star marker": canonical.replace(b"  GM2Godot", b" *GM2Godot", 1),
            "wrong payload digest": b"0" * 64 + lines[0][64:] + b"".join(lines[1:]),
        }

        for case, manifest in variants.items():
            with self.subTest(case=case):
                mutated_payloads = dict(payloads_by_id)
                mutated_payloads[manifest_id] = manifest
                mutated_assets = copy.deepcopy(asset_pages)
                manifest_asset = next(
                    asset
                    for page in mutated_assets
                    for asset in page
                    if asset.get("id") == manifest_id
                )
                manifest_asset["size"] = len(manifest)
                manifest_asset["digest"] = (
                    f"sha256:{hashlib.sha256(manifest).hexdigest()}"
                )
                with tempfile.TemporaryDirectory() as temp_directory:
                    result = _run_existing_release_integrity(
                        content,
                        Path(temp_directory),
                        json.dumps(release_pages),
                        json.dumps(mutated_assets),
                        json.dumps(tag_response),
                        mutated_payloads,
                    )
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(
                    "SHA256SUMS is not canonical" in result.stderr
                    or "SHA256SUMS must contain exactly" in result.stderr
                    or "SHA256SUMS digest mismatch" in result.stderr,
                    result.stderr,
                )
                self.assertIn("release_id=740", result.stderr)
                self.assertIn(
                    "https://github.com/Infiland/GM2Godot/releases/tag/"
                    f"{EXISTING_RELEASE_TEST_TAG}",
                    result.stderr,
                )

    def test_existing_release_integrity_rejects_metadata_and_manifest_triangle(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )
        mutated_assets = copy.deepcopy(asset_pages)
        linux_asset = next(
            asset
            for page in mutated_assets
            for asset in page
            if asset.get("name") == "GM2Godot-linux.zip"
        )
        linux_asset["digest"] = "sha256:" + "0" * 64

        with tempfile.TemporaryDirectory() as temp_directory:
            result = _run_existing_release_integrity(
                content,
                Path(temp_directory),
                json.dumps(release_pages),
                json.dumps(mutated_assets),
                json.dumps(tag_response),
                payloads_by_id,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Downloaded asset digest mismatch", result.stderr)
        self.assertIn("release_id=740", result.stderr)
        self.assertIn(
            "https://github.com/Infiland/GM2Godot/releases/tag/"
            f"{EXISTING_RELEASE_TEST_TAG}",
            result.stderr,
        )

    def test_existing_release_integrity_propagates_strict_checksum_failure(
        self,
    ) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )

        with tempfile.TemporaryDirectory() as temp_directory:
            result = _run_existing_release_integrity(
                content,
                Path(temp_directory),
                json.dumps(release_pages),
                json.dumps(asset_pages),
                json.dumps(tag_response),
                payloads_by_id,
                sha256sum_exit=63,
            )

        self.assertEqual(result.returncode, 63)
        self.assertIn("Strict SHA256SUMS verification failed", result.stderr)
        self.assertIn("release_id=740", result.stderr)
        self.assertIn(f"release_url=https://github.com/Infiland/GM2Godot/releases/tag/{EXISTING_RELEASE_TEST_TAG}", result.stderr)

    def test_existing_release_integrity_rejects_snapshot_mutation(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )

        changed_release = copy.deepcopy(release_pages)
        changed_release[1][0]["published_at"] = "2026-07-18T21:00:42Z"
        changed_release_id = copy.deepcopy(release_pages)
        changed_release_id[1][0]["id"] = 742
        changed_assets = copy.deepcopy(asset_pages)
        changed_assets[0][0]["id"] = 999_999
        changed_asset_size = copy.deepcopy(asset_pages)
        changed_asset_size[0][0]["size"] = 999_999
        changed_asset_digest = copy.deepcopy(asset_pages)
        changed_asset_digest[0][0]["digest"] = "sha256:" + "7" * 64
        changed_tag = copy.deepcopy(tag_response)
        tag_object = changed_tag["object"]
        if not isinstance(tag_object, dict):
            raise AssertionError("Tag fixture object must be a dictionary")
        tag_object["sha"] = "8" * 40
        changed_tag_type = copy.deepcopy(tag_response)
        changed_type_object = changed_tag_type["object"]
        if not isinstance(changed_type_object, dict):
            raise AssertionError("Tag fixture object must be a dictionary")
        changed_type_object["type"] = "tag"
        cases = (
            (
                "release",
                (json.dumps(release_pages), json.dumps(changed_release)),
                json.dumps(asset_pages),
                json.dumps(tag_response),
            ),
            (
                "release id",
                (json.dumps(release_pages), json.dumps(changed_release_id)),
                json.dumps(asset_pages),
                json.dumps(tag_response),
            ),
            (
                "asset",
                json.dumps(release_pages),
                (json.dumps(asset_pages), json.dumps(changed_assets)),
                json.dumps(tag_response),
            ),
            (
                "asset size",
                json.dumps(release_pages),
                (json.dumps(asset_pages), json.dumps(changed_asset_size)),
                json.dumps(tag_response),
            ),
            (
                "asset digest",
                json.dumps(release_pages),
                (json.dumps(asset_pages), json.dumps(changed_asset_digest)),
                json.dumps(tag_response),
            ),
            (
                "tag",
                json.dumps(release_pages),
                json.dumps(asset_pages),
                (json.dumps(tag_response), json.dumps(changed_tag)),
            ),
            (
                "tag type",
                json.dumps(release_pages),
                json.dumps(asset_pages),
                (json.dumps(tag_response), json.dumps(changed_tag_type)),
            ),
        )
        for case, current_releases, current_assets, current_tags in cases:
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as temp_directory:
                    result = _run_existing_release_integrity(
                        content,
                        Path(temp_directory),
                        current_releases,
                        current_assets,
                        current_tags,
                        payloads_by_id,
                    )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("state changed during the read-only audit", result.stderr)

    def test_existing_release_integrity_requires_environment_and_tools(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "release.yml"
        content = workflow.read_text(encoding="utf-8")
        release_pages, asset_pages, tag_response, payloads_by_id = (
            _existing_release_fixture()
        )

        missing_environment_results: list[
            tuple[str, subprocess.CompletedProcess[str]]
        ] = []
        with tempfile.TemporaryDirectory() as temp_directory:
            missing_environment_results.append(
                (
                    "GH_TOKEN",
                    _run_existing_release_integrity(
                        content,
                        Path(temp_directory),
                        json.dumps(release_pages),
                        json.dumps(asset_pages),
                        json.dumps(tag_response),
                        payloads_by_id,
                        token=None,
                    ),
                )
            )
        with tempfile.TemporaryDirectory() as temp_directory:
            missing_environment_results.append(
                (
                    "GITHUB_REPOSITORY",
                    _run_existing_release_integrity(
                        content,
                        Path(temp_directory),
                        json.dumps(release_pages),
                        json.dumps(asset_pages),
                        json.dumps(tag_response),
                        payloads_by_id,
                        repository=None,
                    ),
                )
            )
        with tempfile.TemporaryDirectory() as temp_directory:
            missing_environment_results.append(
                (
                    "RELEASE_TAG",
                    _run_existing_release_integrity(
                        content,
                        Path(temp_directory),
                        json.dumps(release_pages),
                        json.dumps(asset_pages),
                        json.dumps(tag_response),
                        payloads_by_id,
                        release_tag=None,
                    ),
                )
            )
        for variable, result in missing_environment_results:
            with self.subTest(missing_variable=variable):
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Existing-release audit is missing", result.stderr)

        for tool in ("gh", "python", "sha256sum", "cmp"):
            with self.subTest(missing_tool=tool):
                with tempfile.TemporaryDirectory() as temp_directory:
                    result = _run_existing_release_integrity(
                        content,
                        Path(temp_directory),
                        json.dumps(release_pages),
                        json.dumps(asset_pages),
                        json.dumps(tag_response),
                        payloads_by_id,
                        missing_tool=tool,
                    )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"Required existing-release audit tool is unavailable: {tool}",
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
        build_guard = (
            "${{ !cancelled() && needs.get-version.result == 'success' && "
            f"{absence_guard} && (github.event_name == 'pull_request' || "
            "needs.release-state-preflight.result == 'success') }}"
        )
        release_guard = (
            "${{ !cancelled() && github.event_name != 'pull_request' && "
            "github.ref == 'refs/heads/main' && "
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
        integrity_marker = "      - name: Verify existing tagged release\n"
        preflight_marker = "      - name: Check for incomplete release state\n"
        build_marker = "\n  build:\n"
        get_version_job = content[
            content.index("  get-version:"):content.index(
                "  existing-release-integrity:"
            )
        ]
        integrity_job = content[
            content.index("  existing-release-integrity:"):content.index(
                "  release-state-preflight:"
            )
        ]
        preflight_job = content[
            content.index("  release-state-preflight:"):content.index(build_marker)
        ]
        integrity_metadata = content[
            content.index(integrity_marker):content.index(
                "        run: |\n",
                content.index(integrity_marker),
            )
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
        integrity_script = _workflow_run_script(
            content,
            "Verify existing tagged release",
        )
        integrity_job_conditions = [
            line.strip()
            for line in integrity_job.splitlines()
            if line.startswith("    if: ")
        ]
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
        publish_release_step = release_job[
            release_job.index("      - name: Publish run-owned release\n"):
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
        self.assertLess(content.index(tag_check_marker), content.index(integrity_marker))
        self.assertLess(content.index(integrity_marker), content.index(preflight_marker))
        self.assertLess(content.index(tag_check_marker), content.index(preflight_marker))
        self.assertLess(content.index(preflight_marker), content.index(build_marker))
        self.assertNotIn("    permissions:", get_version_job)
        self.assertNotIn("write-all", get_version_job)
        self.assertNotIn("gh api", get_version_job)
        self.assertIn("permissions:\n      contents: write", integrity_job)
        self.assertNotIn("actions/checkout", integrity_job)
        self.assertNotIn("      - uses:", integrity_job)
        self.assertNotIn("pip install", integrity_job)
        self.assertNotIn("continue-on-error:", integrity_job)
        self.assertEqual(
            integrity_job_conditions,
            [
                "if: github.event_name != 'pull_request' && "
                "needs.get-version.outputs.tag_exists == 'true'"
            ],
        )
        self.assertIn("GH_TOKEN: ${{ github.token }}", integrity_metadata)
        self.assertIn(
            "RELEASE_TAG: v${{ needs.get-version.outputs.version }}",
            integrity_metadata,
        )
        self.assertEqual(integrity_script.count("gh api --method GET"), 3)
        self.assertEqual(integrity_script.count("gh api"), 3)
        self.assertEqual(
            len(re.findall(r"(?m)^\s*gh\s+api\b", integrity_script)),
            3,
        )
        for mutation in (
            "--method DELETE",
            "--method PATCH",
            "--method POST",
            "--method PUT",
            "gh release",
            "git push",
            "gh api -X",
            "gh api --method=",
            "gh graphql",
            "curl ",
            "wget ",
            "urllib.request",
            "http.client",
            "requests.",
        ):
            self.assertNotIn(mutation, integrity_script)
        self.assertIn("Accept: application/octet-stream", integrity_script)
        self.assertIn("sha256sum --check --strict SHA256SUMS", integrity_script)
        self.assertIn("capture_snapshot initial", integrity_script)
        self.assertIn("capture_snapshot final", integrity_script)
        self.assertEqual(
            [
                line.strip()
                for line in integrity_metadata.splitlines()
                if line.strip().startswith("if: ")
            ],
            [],
        )
        self.assertIn("permissions:\n      contents: write", preflight_job)
        self.assertNotIn("actions/checkout", preflight_job)
        self.assertNotIn("      - uses:", preflight_job)
        self.assertNotIn("pip install", preflight_job)
        self.assertEqual(content.count("contents: write"), 3)
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
        self.assertNotIn("existing-release-integrity", build_job)
        self.assertNotIn("always()", build_job)
        self.assertIn(
            "needs: [get-version, release-state-preflight, build]",
            release_job,
        )
        self.assertNotIn("existing-release-integrity", release_job)
        self.assertEqual(release_job.count("if: ${{ always() }}"), 1)
        self.assertEqual(release_job.count("actions/checkout@"), 1)
        self.assertIn(
            "      - uses: actions/checkout@"
            "93cb6efe18208431cddfb8368fd83d5badbf9bfd # v5.0.1\n"
            "        with:\n"
            "          ref: ${{ github.sha }}\n"
            "          fetch-depth: 1\n"
            "          persist-credentials: false\n",
            release_job,
        )
        self.assertEqual(release_job.count("actions/setup-python@"), 1)
        self.assertIn(
            "      - uses: actions/setup-python@"
            "ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0\n"
            "        with:\n"
            "          python-version: '3.12'\n",
            release_job,
        )
        self.assertLess(
            release_job.index("actions/setup-python@"),
            release_job.index("      - name: Publish run-owned release\n"),
        )
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
        for required in (
            "GITHUB_TOKEN: ${{ github.token }}",
            "RELEASE_TARGET_SHA: ${{ github.sha }}",
            "RELEASE_RECEIPT_PATH: release-receipt/release-publisher.json",
            "run: python3 scripts/release_publisher.py",
            "name: Preserve release ownership receipt",
            "if-no-files-found: ignore",
            "retention-days: 30",
        ):
            with self.subTest(required=required):
                self.assertIn(required, publish_release_step)
        for forbidden in (
            "softprops/action-gh-release",
            "overwrite_files:",
            "gh release",
            "git push",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, release_job)

    def test_pyright_targets_supported_python_3_12(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "pyrightconfig.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["pythonVersion"], "3.12")

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
