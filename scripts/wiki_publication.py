"""Bind a reviewed Wiki subtree to an ordinary, hook-preserving Git push."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

CANONICAL_SOURCE_URL = "https://github.com/Infiland/GM2Godot.git"
CANONICAL_WIKI_URL = "https://github.com/Infiland/GM2Godot.wiki.git"
WIKI_PAGES = (
    "Compatibility-and-Limitations.md", "Contributing-and-Testing.md",
    "Diagnostics-and-Troubleshooting.md", "Generated-Project-and-Runtime.md",
    "Home.md", "Installation.md", "Maintainer-Release-and-Wiki.md",
    "Quick-Start-Conversion.md", "_Sidebar.md",
)


class WikiPublicationError(ValueError):
    """A publication gate failed without authorizing a remote update."""


@dataclass(frozen=True)
class PublicationEndpoints:
    """Typed endpoint injection for disposable local tests; CLI endpoints are fixed."""
    source_url: str = CANONICAL_SOURCE_URL
    wiki_url: str = CANONICAL_WIKI_URL


@dataclass(frozen=True)
class GitRunner:
    binary: str = "git"
    environment: Mapping[str, str] | None = None
    timeout_seconds: int = 120

    def run(
        self, repository: Path | None, arguments: Sequence[str], *,
        input_bytes: bytes | None = None, check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        environment = os.environ if self.environment is None else self.environment
        for selector in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                         "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE", "GIT_PREFIX"):
            if selector in environment:
                raise WikiPublicationError(f"Repository override environment is not supported: {selector}")
        command = [self.binary, "--no-replace-objects"]
        if repository is not None:
            command.extend(["-C", str(repository)])
        command.extend(arguments)
        try:
            result = subprocess.run(
                command, input=input_bytes, capture_output=True,
                env=None if self.environment is None else dict(self.environment),
                timeout=self.timeout_seconds, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WikiPublicationError(f"Git command did not complete: {error}") from error
        if check and result.returncode:
            diagnostic = result.stderr.decode("utf-8", errors="replace").strip()
            raise WikiPublicationError(f"Git command failed ({result.returncode}): {diagnostic}")
        return result

    def text(self, repository: Path | None, arguments: Sequence[str]) -> str:
        try:
            return self.run(repository, arguments).stdout.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WikiPublicationError("Git command emitted invalid UTF-8") from error


@dataclass(frozen=True)
class RemoteState:
    branch: str
    sha: str


def _oid(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise WikiPublicationError(f"{label} must be a full lowercase SHA-1 object ID")
    return value


def _string(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value or "\x00" in value or "\n" in value or "\r" in value:
        raise WikiPublicationError(f"Invalid publication evidence field {key}")
    return value


def _resolved_url(git: GitRunner, repository: Path, url: str, *, push: bool = False) -> None:
    if git.text(repository, ["ls-remote", "--get-url", url]).splitlines() != [url]:
        raise WikiPublicationError("Git URL rewrite redirects the explicit canonical URL")
    if push:
        for field in ("url", "pushurl"):
            values = _config_values(git, repository, f"remote.{url}.{field}")
            if values and values != [url.encode("utf-8")]:
                raise WikiPublicationError("A canonical-URL-named remote has alternate or multiple publication URLs")
        result = git.run(repository, ["config", "--null", "--get-regexp", r"^url\..*\.pushinsteadof$"], check=False)
        if result.returncode == 1 and not result.stdout:
            return
        if result.returncode or not result.stdout.endswith(b"\x00"):
            raise WikiPublicationError("Cannot inspect effective Git push URL rewrite policy")
        for row in result.stdout[:-1].split(b"\x00"):
            key, separator, prefix = row.partition(b"\n")
            if not separator or not key.startswith(b"url.") or not key.endswith(b".pushinsteadof"):
                raise WikiPublicationError("Malformed Git push URL rewrite policy")
            if url.encode("utf-8").startswith(prefix):
                raise WikiPublicationError("An applicable Git pushInsteadOf rule prevents canonical publication")


def _config_values(git: GitRunner, repository: Path, key: str) -> list[bytes]:
    result = git.run(repository, ["config", "--null", "--get-all", key], check=False)
    if result.returncode == 1 and not result.stdout:
        return []
    if result.returncode or not result.stdout.endswith(b"\x00"):
        raise WikiPublicationError("Cannot inspect canonical-URL-named remote configuration")
    return result.stdout[:-1].split(b"\x00")


def discover_remote_state(git: GitRunner, repository: Path, wiki_url: str) -> RemoteState:
    _resolved_url(git, repository, wiki_url, push=True)
    advertisement = git.text(repository, ["ls-remote", "--symref", wiki_url, "HEAD", "refs/heads/*"])
    heads: list[str] = []
    symbolic: list[str] = []
    refs: dict[str, list[str]] = {}
    for row in advertisement.splitlines():
        fields = row.split("\t")
        if len(fields) != 2:
            raise WikiPublicationError("Malformed Wiki remote advertisement")
        value, name = fields
        if value.startswith("ref: "):
            if name != "HEAD":
                raise WikiPublicationError("Unexpected symbolic Wiki remote ref")
            symbolic.append(value.removeprefix("ref: "))
        else:
            sha = _oid(value, "Remote SHA")
            if name == "HEAD":
                heads.append(sha)
            else:
                refs.setdefault(name, []).append(sha)
    if len(symbolic) != 1 or not symbolic[0].startswith("refs/heads/") or len(heads) != 1:
        raise WikiPublicationError("Wiki remote HEAD must name one actual symbolic branch")
    branch_ref = symbolic[0]
    git.run(repository, ["check-ref-format", branch_ref])
    if refs.get(branch_ref) != heads:
        raise WikiPublicationError("Wiki HEAD and default branch are missing, duplicate, or inconsistent")
    return RemoteState(branch_ref.removeprefix("refs/heads/"), heads[0])


def _tree_entries(git: GitRunner, repository: Path, tree: str, *, complete: bool) -> dict[str, str]:
    entries: dict[str, str] = {}
    listing = git.run(repository, ["ls-tree", "-z", tree]).stdout
    if listing and not listing.endswith(b"\x00"):
        raise WikiPublicationError("Malformed Wiki tree inventory")
    for raw in listing.split(b"\x00"):
        if not raw:
            continue
        try:
            metadata, raw_name = raw.split(b"\t", 1)
            mode, kind, raw_oid = metadata.decode("ascii").split(" ")
            name = raw_name.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise WikiPublicationError("Malformed Wiki tree entry") from error
        if name in entries or name not in WIKI_PAGES or mode != "100644" or kind != "blob":
            raise WikiPublicationError(f"Unreviewed Wiki tree path, mode, or type: {name!r}")
        entries[name] = _oid(raw_oid, "Wiki blob SHA")
    if complete and set(entries) != set(WIKI_PAGES):
        raise WikiPublicationError("Wiki tree must contain exactly the nine canonical regular Markdown blobs")
    if not entries:
        raise WikiPublicationError("Wiki tree is empty")
    return entries


def _clean(git: GitRunner, repository: Path) -> None:
    if git.text(repository, ["status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"]):
        raise WikiPublicationError("Wiki checkout has tracked drift or ordinary/ignored untracked files")
    git.run(repository, ["diff", "--quiet", "--no-ext-diff", "--no-textconv"])


def _checkout_root(git: GitRunner, repository: Path) -> None:
    actual = git.text(repository, ["rev-parse", "--show-toplevel"]).strip()
    if Path(actual).resolve() != repository.resolve():
        raise WikiPublicationError("The supplied path must be the exact Git checkout root")
    graft_path = Path(git.text(repository, ["rev-parse", "--git-path", "info/grafts"]).strip())
    if not graft_path.is_absolute():
        graft_path = repository / graft_path
    if graft_path.exists() or graft_path.is_symlink():
        raise WikiPublicationError("Legacy Git history grafts cannot establish canonical publication ancestry")


def _physical_tree(git: GitRunner, repository: Path, tree: str, *, complete: bool = True) -> None:
    entries = _tree_entries(git, repository, tree, complete=complete)
    if {path.name for path in repository.iterdir() if path.name != ".git"} != set(entries):
        raise WikiPublicationError("Wiki checkout contains extra physical root paths")
    for name, blob in entries.items():
        path = repository / name
        if (path.is_symlink() or not path.is_file() or (os.name != "nt" and path.stat().st_mode & 0o111)
                or path.read_bytes() != git.run(repository, ["cat-file", "blob", blob]).stdout):
            raise WikiPublicationError(f"Wiki physical bytes or type drifted from the immutable tree: {name}")


def _source_provenance(git: GitRunner, source: Path, source_sha: str, endpoints: PublicationEndpoints) -> tuple[str, str]:
    _oid(source_sha, "SOURCE_SHA")
    _checkout_root(git, source)
    _resolved_url(git, source, endpoints.source_url)
    private_ref = "refs/gm2godot-wiki/" + uuid.uuid4().hex
    try:
        git.run(source, ["fetch", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head", "--refmap=",
                         endpoints.source_url, "refs/heads/main:" + private_ref])
        main_sha = _oid(git.text(source, ["rev-parse", "--verify", private_ref + "^{commit}"]).strip(), "CANONICAL_MAIN_SHA")
    except BaseException as primary_error:
        try:
            git.run(source, ["update-ref", "-d", private_ref])
        except WikiPublicationError as cleanup_error:
            primary_error.add_note("Private canonical-ref cleanup also failed: " + str(cleanup_error)[:1024])
        raise
    else:
        git.run(source, ["update-ref", "-d", private_ref])
    if git.text(source, ["rev-parse", "--verify", source_sha + "^{commit}"]).strip() != source_sha:
        raise WikiPublicationError("SOURCE_SHA does not resolve exactly to a commit")
    if git.run(source, ["merge-base", "--is-ancestor", source_sha, main_sha], check=False).returncode:
        raise WikiPublicationError("SOURCE_SHA is not merged into canonical main")
    tree = _oid(git.text(source, ["rev-parse", "--verify", source_sha + ":docs/wiki"]).strip(), "SOURCE_TREE")
    if git.text(source, ["cat-file", "-t", tree]).strip() != "tree":
        raise WikiPublicationError("SOURCE_SHA:docs/wiki is not a tree")
    _tree_entries(git, source, tree, complete=True)
    return main_sha, tree


def _external_evidence(path: Path, source: Path, wiki: Path) -> Path:
    resolved = path.resolve()
    if any(resolved.is_relative_to(root.resolve()) for root in (source, wiki)):
        raise WikiPublicationError("Publication evidence must remain outside both checkouts")
    return resolved


def _write_evidence(path: Path, record: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".wiki-evidence-", delete=False) as file:
            temporary_path = Path(file.name)
            file.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
            file.flush()
            os.fsync(file.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def stage_publication(
    source_repository: Path, wiki_repository: Path, source_sha: str, evidence_path: Path, *,
    git: GitRunner | None = None, endpoints: PublicationEndpoints | None = None,
) -> dict[str, object]:
    runner, urls = git or GitRunner(), endpoints or PublicationEndpoints()
    source, wiki = source_repository.resolve(), wiki_repository.resolve()
    _checkout_root(runner, wiki)
    evidence = _external_evidence(evidence_path, source, wiki)
    if evidence.exists():
        raise WikiPublicationError("Publication evidence already exists; use a new evidence path")
    main_sha, tree = _source_provenance(runner, source, source_sha, urls)
    remote = discover_remote_state(runner, wiki, urls.wiki_url)
    _clean(runner, wiki)
    if runner.text(wiki, ["symbolic-ref", "HEAD"]).strip() != "refs/heads/" + remote.branch:
        raise WikiPublicationError("Wiki checkout is not on its advertised default branch")
    if runner.text(wiki, ["rev-parse", "HEAD"]).strip() != remote.sha:
        raise WikiPublicationError("Wiki checkout does not match the recorded remote tip")
    source_entries = _tree_entries(runner, source, tree, complete=True)
    live_entries = _tree_entries(runner, wiki, "HEAD", complete=False)
    if set(live_entries) == {"Home.md"}:
        if live_entries["Home.md"] != source_entries["Home.md"]:
            raise WikiPublicationError("The initial Home page differs from the exact reviewed source")
    elif set(live_entries) != set(WIKI_PAGES):
        raise WikiPublicationError("Live Wiki must contain the exact initial Home page or all nine canonical pages")
    _physical_tree(runner, wiki, "HEAD", complete=False)
    for name, blob in source_entries.items():
        target = wiki / name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise WikiPublicationError(f"Wiki working path is not a regular file: {name}")
        target.write_bytes(runner.run(source, ["cat-file", "blob", blob]).stdout)
        target.chmod(0o644)
    runner.run(wiki, ["add", "--all"])
    if runner.text(wiki, ["write-tree"]).strip() != tree:
        raise WikiPublicationError("Staged Wiki tree differs from SOURCE_SHA:docs/wiki")
    _physical_tree(runner, wiki, tree)
    if runner.run(wiki, ["diff", "--quiet", "--no-ext-diff", "--no-textconv"], check=False).returncode:
        raise WikiPublicationError("Wiki working tree drifted after staging")
    if runner.text(wiki, ["ls-files", "--others", "--exclude-standard", "-z"]) or runner.text(wiki, ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"]):
        raise WikiPublicationError("Wiki staging left ordinary or ignored untracked files")
    record: dict[str, object] = {
        "schema_version": 1, "state": "staged", "source_repository": str(source), "wiki_repository": str(wiki),
        "source_url": urls.source_url, "wiki_url": urls.wiki_url, "SOURCE_SHA": source_sha,
        "SOURCE_TREE": tree, "CANONICAL_MAIN_SHA": main_sha, "SOURCE_IS_CURRENT_MAIN": source_sha == main_sha,
        "WIKI_BRANCH": remote.branch, "PRE_PUBLICATION_WIKI_SHA": remote.sha, "PUBLISHED_WIKI_SHA": None,
        "fresh_clone_verified": False, "live_review": None, "remote_verified_sha": None,
    }
    _write_evidence(evidence, record)
    return record


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    record: dict[str, object] = {}
    for key, value in pairs:
        if key in record:
            raise WikiPublicationError(f"Duplicate publication evidence field: {key}")
        record[key] = value
    return record


def _read_evidence(path: Path, wiki: Path, endpoints: PublicationEndpoints) -> dict[str, object]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_fields)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WikiPublicationError(f"Cannot read publication evidence: {error}") from error
    if not isinstance(raw, dict):
        raise WikiPublicationError("Publication evidence must be an object")
    record = cast(dict[str, object], raw)
    if set(record) != {"schema_version", "state", "source_repository", "wiki_repository", "source_url", "wiki_url",
                       "SOURCE_SHA", "SOURCE_TREE", "CANONICAL_MAIN_SHA", "SOURCE_IS_CURRENT_MAIN", "WIKI_BRANCH",
                       "PRE_PUBLICATION_WIKI_SHA", "PUBLISHED_WIKI_SHA", "fresh_clone_verified", "live_review", "remote_verified_sha"}:
        raise WikiPublicationError("Malformed publication evidence fields")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1 or record["state"] not in ("staged", "prepared", "verified", "complete"):
        raise WikiPublicationError("Unsupported publication evidence schema or state")
    for key in ("SOURCE_SHA", "SOURCE_TREE", "CANONICAL_MAIN_SHA", "PRE_PUBLICATION_WIKI_SHA"):
        _oid(record[key], key)
    if type(record["SOURCE_IS_CURRENT_MAIN"]) is not bool or record["SOURCE_IS_CURRENT_MAIN"] is not (record["SOURCE_SHA"] == record["CANONICAL_MAIN_SHA"]):
        raise WikiPublicationError("Inconsistent canonical-main publication evidence")
    if type(record["fresh_clone_verified"]) is not bool:
        raise WikiPublicationError("Malformed fresh-clone evidence")
    if record["PUBLISHED_WIKI_SHA"] is not None:
        _oid(record["PUBLISHED_WIKI_SHA"], "PUBLISHED_WIKI_SHA")
    if record["remote_verified_sha"] is not None:
        _oid(record["remote_verified_sha"], "remote_verified_sha")
    if record["live_review"] is not None:
        _string(record, "live_review")
    source = Path(_string(record, "source_repository"))
    _external_evidence(path, source, wiki)
    if _string(record, "wiki_repository") != str(wiki.resolve()) or _string(record, "source_url") != endpoints.source_url or _string(record, "wiki_url") != endpoints.wiki_url:
        raise WikiPublicationError("Publication evidence belongs to different checkouts or endpoints")
    _string(record, "WIKI_BRANCH")
    return record


def _commit_gate(git: GitRunner, wiki: Path, record: Mapping[str, object], published_sha: str) -> None:
    _oid(published_sha, "PUBLISHED_WIKI_SHA")
    _checkout_root(git, wiki)
    _clean(git, wiki)
    if git.text(wiki, ["rev-parse", "--verify", published_sha + "^{commit}"]).strip() != published_sha:
        raise WikiPublicationError("Published SHA does not resolve exactly to a commit")
    header = git.run(wiki, ["cat-file", "commit", published_sha]).stdout.split(b"\n\n", 1)[0]
    parents = [line.removeprefix(b"parent ") for line in header.splitlines() if line.startswith(b"parent ")]
    if parents != [_string(record, "PRE_PUBLICATION_WIKI_SHA").encode("ascii")]:
        raise WikiPublicationError("Publication commit must have exactly the recorded old Wiki SHA as its direct parent")
    tree = git.text(wiki, ["rev-parse", published_sha + "^{tree}"]).strip()
    _tree_entries(git, wiki, tree, complete=True)
    if tree != record["SOURCE_TREE"] or git.text(wiki, ["write-tree"]).strip() != tree:
        raise WikiPublicationError("Published commit or checkout differs from the exact immutable source subtree")
    _physical_tree(git, wiki, tree)


def _refresh_provenance(
    git: GitRunner, record: dict[str, object], endpoints: PublicationEndpoints, *, update_record: bool = True,
) -> None:
    main_sha, tree = _source_provenance(git, Path(_string(record, "source_repository")), _string(record, "SOURCE_SHA"), endpoints)
    if tree != record["SOURCE_TREE"]:
        raise WikiPublicationError("Evidence SOURCE_TREE is not bound to SOURCE_SHA:docs/wiki")
    if not update_record:
        if git.run(Path(_string(record, "source_repository")), ["merge-base", "--is-ancestor",
                   _string(record, "CANONICAL_MAIN_SHA"), main_sha], check=False).returncode:
            raise WikiPublicationError("The recorded canonical main is no longer in canonical history")
    else:
        record["CANONICAL_MAIN_SHA"] = main_sha
        record["SOURCE_IS_CURRENT_MAIN"] = record["SOURCE_SHA"] == main_sha


def pre_push_guard(
    *, published_sha: str, branch_ref: str, old_sha: str, wiki_url: str,
    remote_args: Sequence[str], stdin: BinaryIO,
) -> None:
    _oid(published_sha, "PUBLISHED_WIKI_SHA")
    _oid(old_sha, "PRE_PUBLICATION_WIKI_SHA")
    if list(remote_args) != [wiki_url, wiki_url] or not branch_ref.startswith("refs/heads/"):
        raise WikiPublicationError("Pre-push remote URL or destination differs from the publication binding")
    expected = f"{published_sha} {published_sha} {branch_ref} {old_sha}\n".encode("utf-8")
    if stdin.read(len(expected) + 1) != expected:
        raise WikiPublicationError("Pre-push advertised old SHA, immutable source, destination, or ref count changed")


def _guard_configuration(git: GitRunner, wiki: Path, record: Mapping[str, object], published_sha: str) -> list[str]:
    version = re.match(r"git version (\d+)\.(\d+)", git.text(wiki, ["--version"]))
    if version is None or tuple(map(int, version.groups())) < (2, 54):
        raise WikiPublicationError("Wiki publication requires Git 2.54 or later with configured hooks")
    name = "gm2godot-" + uuid.uuid4().hex
    command = shlex.join([sys.executable, str(Path(__file__).resolve()), "pre-push", "--published-sha", published_sha,
                          "--branch-ref", "refs/heads/" + _string(record, "WIKI_BRANCH"), "--old-sha",
                          _string(record, "PRE_PUBLICATION_WIKI_SHA"), "--wiki-url", _string(record, "wiki_url")])
    config = ["-c", f"hook.{name}.event=pre-push", "-c", f"hook.{name}.command={command}", "-c", f"hook.{name}.enabled=true"]
    rows = git.text(wiki, [*config, "hook", "list", "--show-scope", "pre-push"]).splitlines()
    expected = "command\t" + name
    if rows.count(expected) != 1 or any(name in row and row != expected for row in rows):
        raise WikiPublicationError("Git did not positively advertise the enabled command-scoped pre-push guard")
    return config


def _remote_gate(git: GitRunner, wiki: Path, record: Mapping[str, object], sha: str) -> None:
    if discover_remote_state(git, wiki, _string(record, "wiki_url")) != RemoteState(_string(record, "WIKI_BRANCH"), sha):
        raise WikiPublicationError("Wiki remote branch, symbolic HEAD, or recorded commit moved")


def verify_fresh_clone(clone_repository: Path, record: Mapping[str, object], *, git: GitRunner) -> None:
    _checkout_root(git, clone_repository)
    if git.text(clone_repository, ["symbolic-ref", "HEAD"]).strip() != "refs/heads/" + _string(record, "WIKI_BRANCH"):
        raise WikiPublicationError("Fresh Wiki clone has the wrong branch")
    if git.text(clone_repository, ["rev-parse", "HEAD"]).strip() != _string(record, "PUBLISHED_WIKI_SHA"):
        raise WikiPublicationError("Fresh Wiki clone has the wrong published commit")
    if git.text(clone_repository, ["rev-parse", "HEAD^{tree}"]).strip() != record["SOURCE_TREE"]:
        raise WikiPublicationError("Fresh Wiki clone tree differs from the immutable source subtree")
    _tree_entries(git, clone_repository, "HEAD", complete=True)
    _clean(git, clone_repository)
    _physical_tree(git, clone_repository, "HEAD")


def verify_publication(
    wiki_repository: Path, evidence_path: Path, *, git: GitRunner | None = None,
    endpoints: PublicationEndpoints | None = None,
) -> dict[str, object]:
    runner, urls = git or GitRunner(), endpoints or PublicationEndpoints()
    wiki = wiki_repository.resolve()
    record = _read_evidence(evidence_path, wiki, urls)
    published = _string(record, "PUBLISHED_WIKI_SHA")
    _refresh_provenance(runner, record, urls, update_record=False)
    _commit_gate(runner, wiki, record, published)
    _remote_gate(runner, wiki, record, published)
    with tempfile.TemporaryDirectory(prefix="gm2godot-wiki-verify-") as temporary:
        clone = Path(temporary) / "wiki"
        runner.run(wiki, ["-c", "core.autocrlf=false", "-c", "core.eol=lf", "clone", "--no-local", "--no-tags", "--single-branch", "--branch", _string(record, "WIKI_BRANCH"), urls.wiki_url, str(clone)])
        verify_fresh_clone(clone, record, git=runner)
    _remote_gate(runner, wiki, record, published)
    record.update(state="verified", fresh_clone_verified=True, remote_verified_sha=published, live_review=None)
    _write_evidence(evidence_path, record)
    return record


def publish_publication(
    wiki_repository: Path, published_sha: str, evidence_path: Path, *,
    git: GitRunner | None = None, endpoints: PublicationEndpoints | None = None,
) -> dict[str, object]:
    runner, urls = git or GitRunner(), endpoints or PublicationEndpoints()
    wiki = wiki_repository.resolve()
    record = _read_evidence(evidence_path, wiki, urls)
    if record["state"] != "staged" or record["PUBLISHED_WIKI_SHA"] is not None:
        raise WikiPublicationError("Publication evidence has already been used")
    _refresh_provenance(runner, record, urls)
    _commit_gate(runner, wiki, record, published_sha)
    config = _guard_configuration(runner, wiki, record, published_sha)
    _remote_gate(runner, wiki, record, _string(record, "PRE_PUBLICATION_WIKI_SHA"))
    record.update(state="prepared", PUBLISHED_WIKI_SHA=published_sha)
    _write_evidence(evidence_path, record)
    runner.run(wiki, [*config, "push", "--no-follow-tags", urls.wiki_url, published_sha + ":refs/heads/" + _string(record, "WIKI_BRANCH")])
    return verify_publication(wiki, evidence_path, git=runner, endpoints=urls)


def complete_publication(
    wiki_repository: Path, evidence_path: Path, *, live_review: str,
    git: GitRunner | None = None, endpoints: PublicationEndpoints | None = None,
) -> dict[str, object]:
    if not live_review.strip() or any(character in live_review for character in ("\x00", "\n", "\r")):
        raise WikiPublicationError("Completion requires an explicit live rendering and link review result")
    runner, urls = git or GitRunner(), endpoints or PublicationEndpoints()
    record = verify_publication(wiki_repository, evidence_path, git=runner, endpoints=urls)
    _remote_gate(runner, wiki_repository.resolve(), record, _string(record, "PUBLISHED_WIKI_SHA"))
    record.update(state="complete", live_review=live_review)
    _write_evidence(evidence_path, record)
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("stage", "publish", "verify", "complete"):
        command = commands.add_parser(name)
        command.add_argument("--wiki-repository", type=Path, required=True)
        command.add_argument("--evidence", type=Path, required=True)
        if name == "stage":
            command.add_argument("--source-repository", type=Path, required=True)
            command.add_argument("--source-sha", required=True)
        if name == "publish":
            command.add_argument("--published-sha", required=True)
        if name == "complete":
            command.add_argument("--live-review", required=True)
    guard = commands.add_parser("pre-push")
    for argument in ("published-sha", "branch-ref", "old-sha", "wiki-url"):
        guard.add_argument("--" + argument, required=True)
    guard.add_argument("remote_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.command == "pre-push":
            pre_push_guard(published_sha=args.published_sha, branch_ref=args.branch_ref, old_sha=args.old_sha,
                           wiki_url=args.wiki_url, remote_args=args.remote_args, stdin=sys.stdin.buffer)
            return 0
        if args.command == "stage":
            record = stage_publication(args.source_repository, args.wiki_repository, args.source_sha, args.evidence)
        elif args.command == "publish":
            record = publish_publication(args.wiki_repository, args.published_sha, args.evidence)
        elif args.command == "verify":
            record = verify_publication(args.wiki_repository, args.evidence)
        else:
            record = complete_publication(args.wiki_repository, args.evidence, live_review=args.live_review)
        print(json.dumps(record, indent=2, sort_keys=True))
    except (WikiPublicationError, OSError) as error:
        print(f"Wiki publication stopped: {error}", file=sys.stderr)
        for note in getattr(error, "__notes__", ()):
            print(note, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
