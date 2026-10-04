"""Disposable, file-only actual Git fixtures for Wiki publication tests."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from scripts.wiki_publication import GitRunner, PublicationEndpoints

PAGES = (
    "Compatibility-and-Limitations.md", "Contributing-and-Testing.md",
    "Diagnostics-and-Troubleshooting.md", "Generated-Project-and-Runtime.md",
    "Home.md", "Installation.md", "Maintainer-Release-and-Wiki.md",
    "Quick-Start-Conversion.md", "_Sidebar.md",
)
WIKI_BRANCH = "reviewed-wiki-pages"
CommandAction = Callable[[Path | None, Sequence[str]], None]
CompletedAction = Callable[[Path | None, Sequence[str], subprocess.CompletedProcess[bytes]], None]


@dataclass(frozen=True)
class ControlledGitRunner(GitRunner):
    """Inject deterministic changes around a real Git operation, without sleeps."""

    before_command: CommandAction | None = None
    after_command: CompletedAction | None = None

    def run(
        self, repository: Path | None, arguments: Sequence[str], *,
        input_bytes: bytes | None = None, check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        before = self.before_command
        if before is not None:
            before(repository, arguments)
        result = super().run(repository, arguments, input_bytes=input_bytes, check=check)
        after = self.after_command
        if after is not None:
            after(repository, arguments, result)
        return result


class WikiFixture:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        binary = shutil.which("git")
        if binary is None:
            raise AssertionError("Wiki behavior tests require Git 2.54+ with configured hooks")
        self.binary = binary
        self.source = self.root / "source checkout"
        self.canonical = self.root / "canonical source.git"
        self.fork = self.root / "fork source.git"
        self.wiki = self.root / "wiki checkout"
        self.remote = self.root / "wiki remote.git"
        self.evidence = self.root / "evidence.json"
        self.global_config = self.root / "isolated global.gitconfig"
        self.global_config.write_text("", encoding="utf-8")
        self.hook_log = self.root / "hook-events.jsonl"
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_") and not key.startswith("WIKI_TEST_")
        }
        self.environment.update({
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": str(self.global_config), "GIT_ALLOW_PROTOCOL": "file",
            "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_DATE": "2026-10-02T12:00:00+0000",
            "GIT_COMMITTER_DATE": "2026-10-02T12:00:00+0000",
            "WIKI_TEST_HOOK_LOG": str(self.hook_log), "LC_ALL": "C",
        })
        self.git = GitRunner(binary=self.binary, environment=self.environment, timeout_seconds=10)
        self.endpoints = PublicationEndpoints(self.canonical.as_uri(), self.remote.as_uri())
        for path, bare, branch in (
            (self.source, False, "main"), (self.canonical, True, "main"),
            (self.fork, True, "main"), (self.wiki, False, WIKI_BRANCH),
            (self.remote, True, WIKI_BRANCH),
        ):
            path.mkdir()
            args = ["init", "--quiet", "--object-format=sha1", "--initial-branch=" + branch]
            if bare:
                args.append("--bare")
            self.run(path, args)
            if not bare:
                self.configure_identity(path)
        self.source_pages = self.source / "docs/wiki"
        self.source_pages.mkdir(parents=True)
        self.write_source_pages("first")
        (self.source / "outside.txt").write_text("outside the Wiki subtree\n", encoding="utf-8")
        self.source_ancestor = self.commit(self.source, "First canonical source")
        self.write_source_pages("second")
        self.source_sha = self.commit(self.source, "Current canonical source")
        self.canonical_sha = self.source_sha
        self.push_source()
        self.run(self.source, ["remote", "add", "origin", self.endpoints.source_url])
        self.source_tree = self.text(self.source, ["rev-parse", self.source_sha + ":docs/wiki"])
        (self.wiki / "Home.md").write_text("# Reviewed initial Home\n", encoding="utf-8")
        self.wiki_ancestor = self.commit(self.wiki, "Reviewed initial Home")
        (self.wiki / "Home.md").write_bytes((self.source_pages / "Home.md").read_bytes())
        self.old_wiki_sha = self.commit(self.wiki, "Reviewed current Home")
        self.run(self.wiki, ["remote", "add", "origin", self.endpoints.wiki_url])
        self.push_wiki(self.old_wiki_sha)

    def run(
        self, repository: Path, arguments: Sequence[str], *, input_bytes: bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            [self.binary, "-C", str(repository), *arguments], cwd=self.root,
            env=self.environment, input=input_bytes, capture_output=True, timeout=10,
        )
        if check and result.returncode:
            raise AssertionError((list(arguments), result.returncode, result.stderr.decode(errors="replace")))
        return result

    def text(self, repository: Path, arguments: Sequence[str], *, input_bytes: bytes | None = None) -> str:
        return self.run(repository, arguments, input_bytes=input_bytes).stdout.decode().strip()

    def configure_identity(self, repository: Path) -> None:
        self.run(repository, ["config", "user.name", "Wiki Publication Fixture"])
        self.run(repository, ["config", "user.email", "fixture@example.invalid"])
        self.run(repository, ["config", "commit.gpgsign", "false"])

    def write_source_pages(self, revision: str) -> None:
        for name in PAGES:
            (self.source_pages / name).write_text(f"# {name}\n\nCanonical {revision} bytes.\n", encoding="utf-8")

    def commit(self, repository: Path, message: str) -> str:
        self.run(repository, ["add", "--all"])
        self.run(repository, ["commit", "--quiet", "-m", message])
        return self.text(repository, ["rev-parse", "HEAD"])

    def push_source(self) -> None:
        self.run(self.source, ["push", "--no-follow-tags", self.endpoints.source_url,
                               self.source_sha + ":refs/heads/main"])

    def push_wiki(self, sha: str) -> None:
        self.run(self.wiki, ["push", "--no-follow-tags", self.endpoints.wiki_url,
                             sha + ":refs/heads/" + WIKI_BRANCH])

    def remote_tip(self) -> str:
        return self.text(self.remote, ["rev-parse", "refs/heads/" + WIKI_BRANCH])

    def tree_entries(self, repository: Path, tree: str) -> dict[str, tuple[str, str, str]]:
        entries: dict[str, tuple[str, str, str]] = {}
        for row in self.run(repository, ["ls-tree", "-z", tree]).stdout.split(b"\x00"):
            if row:
                metadata, name = row.decode().split("\t", 1)
                mode, kind, oid = metadata.split(" ")
                entries[name] = (mode, kind, oid)
        return entries

    def make_tree(self, repository: Path, entries: Mapping[str, tuple[str, str, str]]) -> str:
        payload = b"".join(
            f"{mode} {kind} {oid}\t{name}\x00".encode()
            for name, (mode, kind, oid) in sorted(entries.items())
        )
        return self.text(repository, ["mktree", "-z"], input_bytes=payload)

    def blob(self, repository: Path, contents: bytes) -> str:
        return self.text(repository, ["hash-object", "-w", "--stdin"], input_bytes=contents)

    def commit_tree(self, repository: Path, tree: str, parents: Sequence[str]) -> str:
        arguments = ["commit-tree", tree]
        for parent in parents:
            arguments.extend(["-p", parent])
        return self.text(repository, [*arguments, "-m", "Fixture object commit"])

    def install_source_subtree(self, subtree: str) -> str:
        entries = self.tree_entries(self.source, "HEAD")
        entries["docs"] = ("040000", "tree", self.make_tree(self.source, {
            "wiki": ("040000", "tree", subtree),
        }))
        tree = self.make_tree(self.source, entries)
        sha = self.commit_tree(self.source, tree, (self.source_sha,))
        self.run(self.source, ["update-ref", "refs/heads/main", sha, self.source_sha])
        self.source_sha = sha
        self.canonical_sha = sha
        self.push_source()
        return sha

    def install_wiki_tree(self, tree: str) -> str:
        parent = self.text(self.wiki, ["rev-parse", "HEAD"])
        sha = self.commit_tree(self.wiki, tree, (parent,))
        self.run(self.wiki, ["update-ref", "HEAD", sha, parent])
        self.run(self.wiki, ["reset", "--hard", sha])
        self.run(self.wiki, ["clean", "-fdx"])
        self.push_wiki(sha)
        self.old_wiki_sha = sha
        return sha

    def full_live_wiki(self) -> None:
        for name in PAGES:
            (self.wiki / name).write_bytes((self.source_pages / name).read_bytes())
        self.old_wiki_sha = self.commit(self.wiki, "Previously reviewed complete Wiki")
        self.push_wiki(self.old_wiki_sha)

    def read_evidence(self) -> dict[str, object]:
        raw: object = json.loads(self.evidence.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise AssertionError("Fixture evidence must be an object")
        return cast(dict[str, object], raw)

    def write_evidence(self, record: Mapping[str, object]) -> None:
        self.evidence.write_text(json.dumps(dict(record), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def controlled_git(
        self, *, before: CommandAction | None = None, after: CompletedAction | None = None,
    ) -> ControlledGitRunner:
        return ControlledGitRunner(
            binary=self.binary, environment=self.environment, timeout_seconds=10,
            before_command=before, after_command=after,
        )

    def hook_command(self, role: str, action: Mapping[str, object] | None = None) -> str:
        directory = self.root / "hook helpers ' with spaces"
        directory.mkdir(exist_ok=True)
        script = directory / "record hook.py"
        script.write_text(_HOOK_SOURCE, encoding="utf-8")
        return shlex.join([sys.executable, str(script), role, json.dumps(dict(action or {}))])

    def configured_hook(self, role: str, *, global_scope: bool = False,
                        action: Mapping[str, object] | None = None) -> None:
        scope = "--global" if global_scope else "--local"
        self.run(self.wiki, ["config", scope, f"hook.{role}.event", "pre-push"])
        self.run(self.wiki, ["config", scope, f"hook.{role}.command", self.hook_command(role, action)])

    def traditional_hook(self, role: str, *, custom: bool = False,
                         action: Mapping[str, object] | None = None) -> Path:
        directory = self.root / "custom hooks ' directory" if custom else self.wiki / ".git/hooks"
        directory.mkdir(exist_ok=True)
        if custom:
            self.run(self.wiki, ["config", "core.hooksPath", str(directory)])
        hook = directory / "pre-push"
        hook.write_text('#!/bin/sh\nexec ' + self.hook_command(role, action) + ' "$@"\n', encoding="utf-8")
        hook.chmod(0o755)
        return hook

    def hook_events(self) -> list[dict[str, object]]:
        if not self.hook_log.exists():
            return []
        events: list[dict[str, object]] = []
        for line in self.hook_log.read_text(encoding="utf-8").splitlines():
            raw: object = json.loads(line)
            if not isinstance(raw, dict):
                raise AssertionError("Hook event must be an object")
            events.append(cast(dict[str, object], raw))
        return events

    def install_checkout_filter(self) -> None:
        """A real reversible smudge filter makes status clean but bytes unequal."""
        attributes = self.root / "external attributes"
        attributes.write_text("Home.md filter=fixture-bytes\n", encoding="utf-8")
        script = self.root / "reversible checkout filter.py"
        script.write_text(
            "import sys\n"
            "data = sys.stdin.buffer.read()\n"
            "suffix = b'physical smudge drift\\n'\n"
            "sys.stdout.buffer.write(data + suffix if sys.argv[1] == 'smudge' else data.removesuffix(suffix))\n",
            encoding="utf-8",
        )
        self.run(self.wiki, ["config", "--global", "core.attributesFile", str(attributes)])
        for operation in ("clean", "smudge"):
            self.run(self.wiki, ["config", "--global", "filter.fixture-bytes." + operation,
                                 shlex.join([sys.executable, str(script), operation])])


_HOOK_SOURCE = '''import json, os, subprocess, sys
from pathlib import Path
role, action = sys.argv[1], json.loads(sys.argv[2])
payload = sys.stdin.buffer.read(65537)
if len(payload) > 65536:
    raise SystemExit(99)
event = {"role": role, "arguments": sys.argv[3:], "stdin": payload.decode(),
         "git_dir": os.environ.get("GIT_DIR")}
with Path(os.environ["WIKI_TEST_HOOK_LOG"]).open("a") as stream:
    stream.write(json.dumps(event, sort_keys=True) + "\\n")
if "git_dir" in action:
    completed = subprocess.run([action["binary"], "--no-replace-objects", "--git-dir=" + action["git_dir"],
        "update-ref", action["ref"], action["new"], action["old"]], capture_output=True, timeout=10)
    if completed.returncode:
        sys.stderr.buffer.write(completed.stderr)
        raise SystemExit(completed.returncode)
raise SystemExit(7 if action.get("reject") else 0)
'''
