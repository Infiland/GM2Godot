from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from collections.abc import Callable, Mapping, Sequence
from io import BytesIO
from pathlib import Path
from typing import cast
from unittest.mock import patch

from scripts import wiki_publication as publication
from tests.wiki_publication_test_support import PAGES, WIKI_BRANCH, WikiFixture


class WikiPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="gm2godot-wiki-test-")
        self.addCleanup(self.temporary.cleanup)
        self.fixture = WikiFixture(Path(self.temporary.name))

    def stage(self, *, sha: str | None = None,
              git: publication.GitRunner | None = None) -> dict[str, object]:
        fixture = self.fixture
        return publication.stage_publication(
            fixture.source, fixture.wiki, sha or fixture.source_sha, fixture.evidence,
            git=git or fixture.git, endpoints=fixture.endpoints,
        )

    def prepare(self) -> str:
        self.stage()
        return self.fixture.commit(self.fixture.wiki, "Publish exact reviewed subtree")

    def publish(self, sha: str, *, git: publication.GitRunner | None = None) -> dict[str, object]:
        fixture = self.fixture
        return publication.publish_publication(
            fixture.wiki, sha, fixture.evidence, git=git or fixture.git, endpoints=fixture.endpoints,
        )

    def verify(self, *, git: publication.GitRunner | None = None) -> dict[str, object]:
        fixture = self.fixture
        return publication.verify_publication(
            fixture.wiki, fixture.evidence, git=git or fixture.git, endpoints=fixture.endpoints,
        )

    def test_nonstandard_default_branch_publishes_only_exact_subtree(self) -> None:
        fixture = self.fixture
        record = self.stage()
        root_tree = fixture.text(fixture.source, ["rev-parse", fixture.source_sha + "^{tree}"])
        self.assertNotEqual(fixture.source_tree, root_tree)
        self.assertEqual(record["SOURCE_TREE"], fixture.source_tree)
        self.assertEqual(record["WIKI_BRANCH"], WIKI_BRANCH)
        self.assertEqual(record["CANONICAL_MAIN_SHA"], fixture.canonical_sha)
        self.assertIs(record["SOURCE_IS_CURRENT_MAIN"], True)
        self.assertEqual(fixture.text(fixture.wiki, ["write-tree"]), fixture.source_tree)
        self.assertEqual(
            {path.name for path in fixture.wiki.iterdir() if path.name != ".git"}, set(PAGES),
        )
        sha = fixture.commit(fixture.wiki, "Reviewed publication")
        pushes: list[tuple[str, ...]] = []

        def record_push(_repository: Path | None, arguments: Sequence[str]) -> None:
            if "push" in arguments:
                pushes.append(tuple(arguments))

        record = self.publish(sha, git=fixture.controlled_git(before=record_push))
        self.assertEqual(len(pushes), 1)
        arguments = pushes[0]
        self.assertEqual(arguments[-4:], (
            "push", "--no-follow-tags", fixture.endpoints.wiki_url, sha + ":refs/heads/" + WIKI_BRANCH,
        ))
        self.assertEqual(arguments[0:6:2], ("-c", "-c", "-c"))
        name = arguments[1].removesuffix(".event=pre-push")
        self.assertRegex(name, r"^hook\.gm2godot-[0-9a-f]{32}$")
        self.assertTrue(arguments[3].startswith(name + ".command="))
        self.assertEqual(arguments[5], name + ".enabled=true")
        self.assertEqual(len(arguments), 10)
        self.assertEqual(fixture.remote_tip(), sha)
        self.assertEqual(fixture.text(fixture.remote, ["rev-parse", sha + "^{tree}"]), fixture.source_tree)
        self.assertEqual(record["PRE_PUBLICATION_WIKI_SHA"], fixture.old_wiki_sha)
        self.assertEqual(record["PUBLISHED_WIKI_SHA"], sha)
        self.assertEqual(record["remote_verified_sha"], sha)
        self.assertIs(record["fresh_clone_verified"], True)
        self.assertEqual(record["state"], "verified")
        completed = publication.complete_publication(
            fixture.wiki, fixture.evidence, live_review="Fixture rendering and links reviewed",
            git=fixture.git, endpoints=fixture.endpoints,
        )
        self.assertEqual(completed["state"], "complete")
        self.assertEqual(completed["PUBLISHED_WIKI_SHA"], sha)

    def test_older_canonical_ancestor_is_explicitly_disclosed(self) -> None:
        fixture = self.fixture
        fixture.full_live_wiki()
        record = self.stage(sha=fixture.source_ancestor)
        expected_tree = fixture.text(fixture.source, ["rev-parse", fixture.source_ancestor + ":docs/wiki"])
        self.assertEqual(record["SOURCE_SHA"], fixture.source_ancestor)
        self.assertEqual(record["SOURCE_TREE"], expected_tree)
        self.assertEqual(record["CANONICAL_MAIN_SHA"], fixture.canonical_sha)
        self.assertIs(record["SOURCE_IS_CURRENT_MAIN"], False)
        sha = fixture.commit(fixture.wiki, "Publish reviewed older source")
        record = self.publish(sha)
        self.assertIs(record["SOURCE_IS_CURRENT_MAIN"], False)
        self.assertEqual(fixture.text(fixture.remote, ["rev-parse", sha + "^{tree}"]), expected_tree)

    def test_fork_only_sha_cannot_use_mutable_origin_as_provenance(self) -> None:
        fixture = self.fixture
        fixture.write_source_pages("fork-only")
        fork_sha = fixture.commit(fixture.source, "Fork-only source")
        fixture.run(fixture.source, ["push", fixture.fork.as_uri(), fork_sha + ":refs/heads/main"])
        fixture.run(fixture.source, ["remote", "set-url", "origin", fixture.fork.as_uri()])
        with self.assertRaises(publication.WikiPublicationError):
            self.stage(sha=fork_sha)
        self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
        self.assertFalse(fixture.evidence.exists())

    def test_source_instead_of_rewrite_is_rejected_before_fetch(self) -> None:
        fixture = self.fixture
        fixture.run(fixture.source, ["config", "url." + fixture.fork.as_uri() + ".insteadOf",
                                     fixture.endpoints.source_url])
        with self.assertRaisesRegex(publication.WikiPublicationError, "rewrite"):
            self.stage()
        self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
        self.assertFalse(fixture.evidence.exists())

    def test_legacy_graft_cannot_forge_canonical_ancestry(self) -> None:
        fixture = self.fixture
        fixture.write_source_pages("unmerged fork")
        fork_sha = fixture.commit(fixture.source, "Unmerged source with valid pages")
        graft = fixture.source / ".git/info/grafts"
        graft.write_text(f"{fixture.canonical_sha} {fork_sha}\n", encoding="ascii")
        self.assertEqual(fixture.run(fixture.source, [
            "--no-replace-objects", "merge-base", "--is-ancestor", fork_sha, fixture.canonical_sha,
        ]).returncode, 0)
        with self.assertRaisesRegex(publication.WikiPublicationError, "graft"):
            self.stage(sha=fork_sha)
        self.assertFalse(fixture.evidence.exists())
        self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)

    def test_full_source_sha_and_exact_checkout_roots_are_required(self) -> None:
        fixture = self.fixture
        for sha in (fixture.source_sha[:12], fixture.source_tree, "0" * 40):
            with self.subTest(sha=sha):
                with self.assertRaises(publication.WikiPublicationError):
                    self.stage(sha=sha)
                self.assertFalse(fixture.evidence.exists())
        for source, wiki in ((fixture.source_pages, fixture.wiki), (fixture.source, fixture.wiki / ".git")):
            with self.subTest(source=source, wiki=wiki):
                with self.assertRaises(publication.WikiPublicationError):
                    publication.stage_publication(
                        source, wiki, fixture.source_sha, fixture.evidence,
                        git=fixture.git, endpoints=fixture.endpoints,
                    )
        for evidence in (fixture.source / "receipt.json", fixture.wiki / "receipt.json"):
            with self.subTest(evidence=evidence):
                with self.assertRaises(publication.WikiPublicationError):
                    publication.stage_publication(
                        fixture.source, fixture.wiki, fixture.source_sha, evidence,
                        git=fixture.git, endpoints=fixture.endpoints,
                    )
                self.assertFalse(evidence.exists())
        self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)

    def test_wiki_fetch_and_push_url_rewrites_are_rejected(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        for key in ("insteadOf", "pushInsteadOf"):
            with self.subTest(key=key):
                name = "url." + fixture.fork.as_uri() + "." + key
                fixture.run(fixture.wiki, ["config", name, fixture.endpoints.wiki_url])
                try:
                    with self.assertRaisesRegex(publication.WikiPublicationError, "rewrite|pushInsteadOf"):
                        self.publish(sha)
                    self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
                finally:
                    fixture.run(fixture.wiki, ["config", "--unset", name])

    def test_unrelated_push_rewrite_preserves_valid_publication(self) -> None:
        fixture = self.fixture
        fixture.run(fixture.wiki, ["config", "url." + fixture.fork.as_uri() + ".pushInsteadOf",
                                  "unrelated-fixture-protocol://"])
        sha = self.prepare()
        self.assertEqual(self.publish(sha)["PUBLISHED_WIKI_SHA"], sha)
        self.assertEqual(fixture.remote_tip(), sha)

    def test_url_named_remote_cannot_redirect_literal_publication_endpoint(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        section = "remote." + fixture.endpoints.wiki_url
        for field, values in (("url", (fixture.fork.as_uri(),)),
                              ("pushurl", (fixture.fork.as_uri(),)),
                              ("url", (fixture.endpoints.wiki_url, fixture.endpoints.wiki_url)),
                              ("pushurl", (fixture.endpoints.wiki_url, fixture.fork.as_uri()))):
            with self.subTest(field=field, values=values):
                for value in values:
                    fixture.run(fixture.wiki, ["config", "--add", section + "." + field, value])
                try:
                    with self.assertRaises(publication.WikiPublicationError):
                        self.publish(sha)
                    self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
                finally:
                    fixture.run(fixture.wiki, ["config", "--remove-section", section])

    def test_source_replace_refs_do_not_change_the_immutable_tree(self) -> None:
        fixture = self.fixture
        original = fixture.source_sha
        fixture.write_source_pages("replacement")
        replacement = fixture.commit(fixture.source, "Replacement interpretation")
        replacement_tree = fixture.text(fixture.source, ["rev-parse", replacement + ":docs/wiki"])
        fixture.run(fixture.source, ["replace", original, replacement])
        self.assertEqual(fixture.text(fixture.source, ["rev-parse", original + ":docs/wiki"]), replacement_tree)
        self.assertNotEqual(replacement_tree, fixture.source_tree)
        record = self.stage(sha=original)
        self.assertEqual(record["SOURCE_TREE"], fixture.source_tree)
        self.assertEqual(record["CANONICAL_MAIN_SHA"], original)

    def test_private_fetch_anchor_preserves_fetch_head_and_leaves_no_refs(self) -> None:
        fixture = self.fixture
        fetch_head = fixture.source / ".git/FETCH_HEAD"
        fetch_head.write_bytes(b"unrelated fetch receipt sentinel\n")
        before = fixture.text(fixture.source, ["for-each-ref", "--format=%(refname)"])
        self.stage()
        self.assertEqual(fetch_head.read_bytes(), b"unrelated fetch receipt sentinel\n")
        self.assertEqual(fixture.text(fixture.source, ["for-each-ref", "--format=%(refname)"]), before)

    def test_private_fetch_cleanup_retains_primary_failure_and_bounded_secondary_note(self) -> None:
        fixture = self.fixture
        for primary in (publication.WikiPublicationError("Primary fetch diagnostic"), KeyboardInterrupt("Primary interruption")):
            with self.subTest(primary=type(primary).__name__):
                private_ref = ""
                cleanup = publication.WikiPublicationError("Secondary cleanup diagnostic " + "x" * 10_000)

                def fail_after_fetch(_repository: Path | None, arguments: Sequence[str],
                                     _result: subprocess.CompletedProcess[bytes]) -> None:
                    nonlocal private_ref
                    if arguments and arguments[0] == "fetch":
                        private_ref = arguments[-1].partition(":")[2]
                        raise primary

                def fail_cleanup(_repository: Path | None, arguments: Sequence[str]) -> None:
                    if private_ref and list(arguments) == ["update-ref", "-d", private_ref]:
                        raise cleanup

                try:
                    with self.assertRaises(type(primary)) as raised:
                        self.stage(git=fixture.controlled_git(before=fail_cleanup, after=fail_after_fetch))
                    self.assertIs(raised.exception, primary)
                    self.assertTrue(private_ref.startswith("refs/gm2godot-wiki/"))
                    notes = getattr(primary, "__notes__", [])
                    self.assertEqual(len(notes), 1)
                    self.assertIn("Secondary cleanup diagnostic", notes[0])
                    self.assertLess(len(notes[0]), 1100)
                    self.assertFalse(fixture.evidence.exists())
                    self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
                finally:
                    if private_ref:
                        fixture.run(fixture.source, ["update-ref", "-d", private_ref])

    def test_remote_advertisement_requires_unique_consistent_symbolic_head(self) -> None:
        fixture = self.fixture
        branch = "refs/heads/" + WIKI_BRANCH
        symbol = f"ref: {branch}\tHEAD\n".encode()
        head = f"{fixture.old_wiki_sha}\tHEAD\n".encode()
        named = f"{fixture.old_wiki_sha}\t{branch}\n".encode()
        payloads = (
            head + named, symbol + named, symbol + head,
            symbol + symbol + head + named, symbol + head + head + named,
            symbol + head + named + named,
            symbol + head + f"{fixture.wiki_ancestor}\t{branch}\n".encode(),
            symbol.replace(branch.encode(), b"refs/tags/invalid") + head + named,
            symbol + head + b"malformed advertisement\n",
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                observed = False

                def alter_advertisement(_repository: Path | None, arguments: Sequence[str],
                                        result: subprocess.CompletedProcess[bytes]) -> None:
                    nonlocal observed
                    if list(arguments[:2]) == ["ls-remote", "--symref"]:
                        observed = True
                        self.assertIn(named, result.stdout)
                        result.stdout = payload

                with self.assertRaises(publication.WikiPublicationError):
                    publication.discover_remote_state(
                        fixture.controlled_git(after=alter_advertisement), fixture.wiki,
                        fixture.endpoints.wiki_url,
                    )
                self.assertTrue(observed)
                self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)

    def test_repository_and_index_environment_overrides_fail_closed(self) -> None:
        fixture = self.fixture
        before = (fixture.wiki / ".git/index").read_bytes()
        overrides = {
            "GIT_DIR": str(fixture.source / ".git"),
            "GIT_WORK_TREE": str(fixture.source),
            "GIT_INDEX_FILE": str(fixture.root / "redirected.index"),
            "GIT_COMMON_DIR": str(fixture.source / ".git"),
            "GIT_OBJECT_DIRECTORY": str(fixture.source / ".git/objects"),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(fixture.source / ".git/objects"),
            "GIT_NAMESPACE": "redirected", "GIT_SHALLOW_FILE": str(fixture.root / "shallow"),
            "GIT_PREFIX": "docs/wiki/",
            "GIT_GRAFT_FILE": str(fixture.root / "redirected-grafts"),
        }
        for name, value in overrides.items():
            with self.subTest(name=name):
                git = publication.GitRunner(
                    binary=fixture.binary, environment={**fixture.environment, name: value}, timeout_seconds=10,
                )
                with self.assertRaisesRegex(publication.WikiPublicationError, "override"):
                    self.stage(git=git)
                self.assertEqual((fixture.wiki / ".git/index").read_bytes(), before)
                self.assertFalse((fixture.root / "redirected.index").exists())
                self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)

    def test_source_inventory_rejects_extra_nested_and_nonregular_entries(self) -> None:
        fixture = self.fixture
        original_entries = fixture.tree_entries(fixture.source, fixture.source_tree)
        extra_blob = fixture.blob(fixture.source, b"unreviewed bytes\n")
        empty_tree = fixture.make_tree(fixture.source, {})
        nested_tree = fixture.make_tree(fixture.source, {"nested.md": ("100644", "blob", extra_blob)})
        cases = (
            ("extra.md", ("100644", "blob", extra_blob)),
            ("alternate.textile", ("100644", "blob", extra_blob)),
            ("nested", ("040000", "tree", nested_tree)),
            ("empty", ("040000", "tree", empty_tree)),
            ("Home.md", ("120000", "blob", extra_blob)),
            ("Home.md", ("100755", "blob", extra_blob)),
            ("Home.md", ("160000", "commit", fixture.source_sha)),
            ("Home.md", None),
        )
        for name, entry in cases:
            with self.subTest(name=name, entry=entry):
                entries = dict(original_entries)
                if entry is None:
                    entries.pop(name)
                else:
                    entries[name] = entry
                fixture.install_source_subtree(fixture.make_tree(fixture.source, entries))
                with self.assertRaises(publication.WikiPublicationError):
                    self.stage()
                self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
                self.assertFalse(fixture.evidence.exists())

    def test_live_inventory_rejects_unchanged_extras_modes_and_empty_trees(self) -> None:
        fixture = self.fixture
        fixture.full_live_wiki()
        original_entries = fixture.tree_entries(fixture.wiki, "HEAD")
        blob = fixture.blob(fixture.wiki, b"unreviewed live bytes\n")
        empty = fixture.make_tree(fixture.wiki, {})
        nested = fixture.make_tree(fixture.wiki, {"page.md": ("100644", "blob", blob)})
        cases = (
            ("unchanged-extra.md", ("100644", "blob", blob)),
            ("alternate.textile", ("100644", "blob", blob)),
            ("nested", ("040000", "tree", nested)),
            ("empty", ("040000", "tree", empty)),
            ("Home.md", ("120000", "blob", blob)),
            ("Home.md", ("100755", "blob", blob)),
            ("Home.md", ("160000", "commit", fixture.old_wiki_sha)),
            ("Installation.md", None),
        )
        for name, entry in cases:
            with self.subTest(name=name, entry=entry):
                entries = dict(original_entries)
                if entry is None:
                    entries.pop(name)
                else:
                    entries[name] = entry
                old = fixture.install_wiki_tree(fixture.make_tree(fixture.wiki, entries))
                self.assertEqual(fixture.text(fixture.wiki, ["status", "--porcelain"]), "")
                with self.assertRaises(publication.WikiPublicationError):
                    self.stage()
                self.assertEqual(fixture.remote_tip(), old)
                self.assertFalse(fixture.evidence.exists())

    def test_arbitrary_partial_initial_inventory_and_unreviewed_home_are_rejected(self) -> None:
        fixture = self.fixture
        for case in ("partial", "home-drift"):
            with self.subTest(case=case):
                if case == "partial":
                    (fixture.wiki / "Installation.md").write_bytes((fixture.source_pages / "Installation.md").read_bytes())
                else:
                    (fixture.wiki / "Installation.md").unlink(missing_ok=True)
                    (fixture.wiki / "Home.md").write_text("unreviewed initial Home\n", encoding="utf-8")
                old = fixture.commit(fixture.wiki, "Unreviewed partial Wiki")
                fixture.push_wiki(old)
                with self.assertRaises(publication.WikiPublicationError):
                    self.stage()
                self.assertEqual(fixture.remote_tip(), old)

    def test_staging_checks_actual_write_tree_after_git_add(self) -> None:
        fixture = self.fixture

        def drift_after_add(repository: Path | None, arguments: Sequence[str],
                            _result: subprocess.CompletedProcess[bytes]) -> None:
            if repository is not None and repository.resolve() == fixture.wiki and list(arguments) == ["add", "--all"]:
                (fixture.wiki / "Home.md").write_text("concurrent staged drift\n", encoding="utf-8")
                fixture.run(fixture.wiki, ["add", "Home.md"])

        with self.assertRaisesRegex(publication.WikiPublicationError, "Staged"):
            self.stage(git=fixture.controlled_git(after=drift_after_add))
        self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
        self.assertFalse(fixture.evidence.exists())

    def test_publication_rejects_later_tracked_staged_mode_and_untracked_drift(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        for kind in ("tracked", "staged", "mode", "ordinary-untracked", "ignored-untracked"):
            with self.subTest(kind=kind):
                if kind in ("tracked", "staged"):
                    (fixture.wiki / "Home.md").write_text("later changed bytes\n", encoding="utf-8")
                    if kind == "staged":
                        fixture.run(fixture.wiki, ["add", "Home.md"])
                elif kind == "mode":
                    fixture.run(fixture.wiki, ["update-index", "--chmod=+x", "Home.md"])
                else:
                    name = "untracked.tmp" if kind == "ordinary-untracked" else "ignored.tmp"
                    if kind == "ignored-untracked":
                        (fixture.wiki / ".git/info/exclude").write_text("ignored.tmp\n", encoding="utf-8")
                    (fixture.wiki / name).write_text("must not publish\n", encoding="utf-8")
                with self.assertRaises(publication.WikiPublicationError):
                    self.publish(sha)
                self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
                fixture.run(fixture.wiki, ["reset", "--hard", sha])
                for name in ("untracked.tmp", "ignored.tmp"):
                    (fixture.wiki / name).unlink(missing_ok=True)

    def test_index_flags_cannot_hide_changed_physical_publication_bytes(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                fixture.run(fixture.wiki, ["update-index", "--" + flag, "Home.md"])
                original = (fixture.wiki / "Home.md").read_bytes()
                (fixture.wiki / "Home.md").write_bytes(b"hidden physical drift\n")
                self.assertEqual(fixture.text(fixture.wiki, ["status", "--porcelain"]), "")
                with self.assertRaisesRegex(publication.WikiPublicationError, "physical"):
                    self.publish(sha)
                self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
                (fixture.wiki / "Home.md").write_bytes(original)
                fixture.run(fixture.wiki, ["update-index", "--no-" + flag, "Home.md"])

    def test_index_flags_cannot_hide_initial_physical_bytes_before_staging(self) -> None:
        fixture = self.fixture
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                fixture.run(fixture.wiki, ["update-index", "--" + flag, "Home.md"])
                original = (fixture.wiki / "Home.md").read_bytes()
                (fixture.wiki / "Home.md").write_bytes(b"hidden initial Home drift\n")
                self.assertEqual(fixture.text(fixture.wiki, ["status", "--porcelain"]), "")
                with self.assertRaisesRegex(publication.WikiPublicationError, "physical"):
                    self.stage()
                self.assertEqual((fixture.wiki / "Home.md").read_bytes(), b"hidden initial Home drift\n")
                self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
                self.assertFalse(fixture.evidence.exists())
                (fixture.wiki / "Home.md").write_bytes(original)
                fixture.run(fixture.wiki, ["update-index", "--no-" + flag, "Home.md"])

    def test_core_filemode_false_does_not_hide_unreviewed_modes(self) -> None:
        fixture = self.fixture
        fixture.run(fixture.wiki, ["config", "core.filemode", "false"])
        home = fixture.wiki / "Home.md"
        if os.name == "nt":
            fixture.run(fixture.wiki, ["update-index", "--chmod=+x", "Home.md"])
        else:
            home.chmod(home.stat().st_mode | 0o111)
            self.assertEqual(fixture.text(fixture.wiki, ["status", "--porcelain"]), "")
        with self.assertRaises(publication.WikiPublicationError):
            self.stage()
        self.assertFalse(fixture.evidence.exists())
        self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
        self.assertEqual(home.read_bytes(), (fixture.source_pages / "Home.md").read_bytes())
        if os.name == "nt":
            fixture.run(fixture.wiki, ["update-index", "--chmod=-x", "Home.md"])
        else:
            home.chmod(home.stat().st_mode & ~0o111)
        sha = self.prepare()
        if os.name == "nt":
            fixture.run(fixture.wiki, ["update-index", "--chmod=+x", "Home.md"])
        else:
            home.chmod(home.stat().st_mode | 0o111)
            self.assertEqual(fixture.text(fixture.wiki, ["status", "--porcelain"]), "")
        with self.assertRaises(publication.WikiPublicationError):
            self.publish(sha)
        self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)

    def test_publication_commit_requires_exact_tree_and_one_recorded_parent(self) -> None:
        fixture = self.fixture
        valid = self.prepare()
        wrong_tree = fixture.text(fixture.wiki, ["rev-parse", fixture.old_wiki_sha + "^{tree}"])
        cases = (
            fixture.commit_tree(fixture.wiki, wrong_tree, (fixture.old_wiki_sha,)),
            fixture.commit_tree(fixture.wiki, fixture.source_tree, (fixture.wiki_ancestor,)),
            fixture.commit_tree(fixture.wiki, fixture.source_tree, (fixture.old_wiki_sha, fixture.wiki_ancestor)),
            fixture.commit_tree(fixture.wiki, fixture.source_tree, ()),
        )
        for sha in cases:
            with self.subTest(sha=sha):
                with self.assertRaises(publication.WikiPublicationError):
                    self.publish(sha)
                self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
                self.assertEqual(fixture.text(fixture.wiki, ["rev-parse", "HEAD"]), valid)

    def test_wrong_direct_parent_cannot_be_hidden_by_legacy_graft(self) -> None:
        fixture = self.fixture
        self.prepare()
        wrong = fixture.commit_tree(fixture.wiki, fixture.source_tree, (fixture.wiki_ancestor,))
        (fixture.wiki / ".git/info/grafts").write_text(
            f"{wrong} {fixture.old_wiki_sha}\n", encoding="ascii",
        )
        self.assertEqual(fixture.text(fixture.wiki, [
            "--no-replace-objects", "rev-list", "--parents", "-n", "1", wrong,
        ]), f"{wrong} {fixture.old_wiki_sha}")
        with self.assertRaises(publication.WikiPublicationError):
            self.publish(wrong)
        self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)

    def test_unsupported_git_and_unproven_hook_capability_never_push(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        for kind in ("old-version", "unknown-version", "unsupported", "missing", "disabled", "duplicate", "malformed"):
            with self.subTest(kind=kind):
                pushed = False
                capability_seen = False

                def reject_push(_repository: Path | None, arguments: Sequence[str]) -> None:
                    nonlocal pushed
                    if "push" in arguments:
                        pushed = True

                def change_capability(_repository: Path | None, arguments: Sequence[str],
                                      result: subprocess.CompletedProcess[bytes]) -> None:
                    nonlocal capability_seen
                    if list(arguments) == ["--version"] and kind in ("old-version", "unknown-version"):
                        result.stdout = b"git version 2.53.9\n" if kind == "old-version" else b"unrecognized version\n"
                    if "--show-scope" in arguments:
                        capability_seen = True
                        rows = result.stdout.splitlines()
                        guard_rows = [row for row in rows if row.startswith(b"command\tgm2godot-")]
                        self.assertEqual(len(guard_rows), 1, "Real Git must first positively support the guard")
                        row = guard_rows[0]
                        if kind == "unsupported":
                            raise publication.WikiPublicationError("Fixture Git does not support hook list")
                        if kind == "missing":
                            result.stdout = b""
                        elif kind == "disabled":
                            result.stdout = row.replace(b"command\t", b"command\tdisabled\t") + b"\n"
                        elif kind == "duplicate":
                            result.stdout = row + b"\n" + row + b"\n"
                        elif kind == "malformed":
                            result.stdout = row.replace(b"command\t", b"unknown-scope\t") + b"\n"

                with self.assertRaises(publication.WikiPublicationError):
                    self.publish(sha, git=fixture.controlled_git(before=reject_push, after=change_capability))
                self.assertFalse(pushed)
                self.assertEqual(capability_seen, kind not in ("old-version", "unknown-version"))
                self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
                self.assertEqual(fixture.read_evidence()["state"], "staged")

    def test_existing_configured_and_traditional_hooks_keep_arguments_stdin_and_config(self) -> None:
        fixture = self.fixture
        fixture.configured_hook("global-hook", global_scope=True)
        fixture.configured_hook("local-hook")
        legacy = fixture.traditional_hook("default-traditional")
        sha = self.prepare()
        local_config = (fixture.wiki / ".git/config").read_bytes()
        global_config = fixture.global_config.read_bytes()
        legacy_bytes = legacy.read_bytes()
        self.publish(sha)
        self.assert_hook_events(["global-hook", "local-hook", "default-traditional"], sha)
        self.assertEqual((fixture.wiki / ".git/config").read_bytes(), local_config)
        self.assertEqual(fixture.global_config.read_bytes(), global_config)
        self.assertEqual(legacy.read_bytes(), legacy_bytes)
        self.assertNotIn("gm2godot-", fixture.text(fixture.wiki, ["hook", "list", "--show-scope", "pre-push"]))

    def test_custom_hooks_path_remains_effective_alongside_configured_hooks(self) -> None:
        fixture = self.fixture
        ignored = fixture.traditional_hook("ignored-default")
        ignored_bytes = ignored.read_bytes()
        fixture.configured_hook("global-hook", global_scope=True)
        fixture.configured_hook("local-hook")
        custom = fixture.traditional_hook("custom-traditional", custom=True)
        sha = self.prepare()
        before = (fixture.wiki / ".git/config").read_bytes()
        self.publish(sha)
        self.assert_hook_events(["global-hook", "local-hook", "custom-traditional"], sha)
        self.assertEqual(fixture.text(fixture.wiki, ["config", "core.hooksPath"]), str(custom.parent))
        self.assertEqual((fixture.wiki / ".git/config").read_bytes(), before)
        self.assertEqual(ignored.read_bytes(), ignored_bytes)

    def assert_hook_events(self, roles: list[str], sha: str) -> None:
        fixture = self.fixture
        events = fixture.hook_events()
        self.assertEqual([event["role"] for event in events], roles)
        payload = f"{sha} {sha} refs/heads/{WIKI_BRANCH} {fixture.old_wiki_sha}\n"
        for event in events:
            self.assertEqual(event["arguments"], [fixture.endpoints.wiki_url, fixture.endpoints.wiki_url])
            self.assertEqual(event["stdin"], payload)

    def test_existing_hook_rejection_never_advances_remote(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        for role in ("global-hook", "local-hook", "default-traditional", "custom-traditional"):
            with self.subTest(role=role):
                if role in ("global-hook", "local-hook"):
                    fixture.configured_hook(role, global_scope=role == "global-hook", action={"reject": True})
                else:
                    fixture.traditional_hook(role, custom=role == "custom-traditional", action={"reject": True})
                try:
                    with self.assertRaises(publication.WikiPublicationError):
                        self.publish(sha)
                    self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
                    self.assertEqual(fixture.read_evidence()["state"], "prepared")
                    self.assertEqual(fixture.read_evidence()["PUBLISHED_WIKI_SHA"], sha)
                finally:
                    record = fixture.read_evidence()
                    record.update(state="staged", PUBLISHED_WIKI_SHA=None)
                    fixture.write_evidence(record)
                    fixture.hook_log.unlink(missing_ok=True)
                    if role in ("global-hook", "local-hook"):
                        scope = "--global" if role == "global-hook" else "--local"
                        fixture.run(fixture.wiki, ["config", scope, "--remove-section", "hook." + role])
                    else:
                        hook_dir = fixture.root / "custom hooks ' directory" if role == "custom-traditional" else fixture.wiki / ".git/hooks"
                        (hook_dir / "pre-push").unlink()
                        if role == "custom-traditional":
                            fixture.run(fixture.wiki, ["config", "--unset", "core.hooksPath"])

    def test_rejected_prepared_receipt_cannot_recover_an_unpublished_commit(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        hook = fixture.traditional_hook("reject-prepared", action={"reject": True})
        with self.assertRaises(publication.WikiPublicationError):
            self.publish(sha)
        prepared = fixture.evidence.read_bytes()
        self.assertEqual(fixture.read_evidence()["state"], "prepared")
        with self.assertRaises(publication.WikiPublicationError):
            self.verify()
        self.assertEqual(fixture.evidence.read_bytes(), prepared)
        self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
        hook.unlink()
        fixture.push_wiki(sha)
        self.assertEqual(self.verify()["PUBLISHED_WIKI_SHA"], sha)

    def test_interrupted_successful_push_retains_exact_prepared_binding_for_recovery(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        interruption = KeyboardInterrupt("Fixture interruption after actual push")

        def interrupt_after_push(_repository: Path | None, arguments: Sequence[str],
                                 _result: subprocess.CompletedProcess[bytes]) -> None:
            if "push" in arguments:
                raise interruption

        with self.assertRaises(KeyboardInterrupt) as raised:
            self.publish(sha, git=fixture.controlled_git(after=interrupt_after_push))
        self.assertIs(raised.exception, interruption)
        self.assertEqual(fixture.remote_tip(), sha)
        self.assertEqual(fixture.read_evidence()["state"], "prepared")
        self.assertEqual(fixture.read_evidence()["PUBLISHED_WIKI_SHA"], sha)
        self.assertEqual(self.verify()["state"], "verified")

    def test_preconnection_rewind_is_rejected_by_advertised_old_sha_guard(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        changed = False

        def rewind_before_push(_repository: Path | None, arguments: Sequence[str]) -> None:
            nonlocal changed
            if "push" in arguments and not changed:
                changed = True
                fixture.run(fixture.remote, ["update-ref", "refs/heads/" + WIKI_BRANCH,
                                            fixture.wiki_ancestor, fixture.old_wiki_sha])

        self.assertEqual(fixture.run(fixture.wiki, ["merge-base", "--is-ancestor", fixture.wiki_ancestor, sha]).returncode, 0)
        with self.assertRaises(publication.WikiPublicationError):
            self.publish(sha, git=fixture.controlled_git(before=rewind_before_push))
        self.assertTrue(changed)
        self.assertEqual(fixture.remote_tip(), fixture.wiki_ancestor)

    def test_server_rejects_rewind_and_advance_after_advertisement(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        advance = fixture.commit_tree(fixture.wiki, fixture.source_tree, (fixture.old_wiki_sha,))
        fixture.run(fixture.wiki, ["push", fixture.endpoints.wiki_url, advance + ":refs/heads/race-target"])
        for target in (fixture.wiki_ancestor, advance):
            with self.subTest(target=target):
                fixture.traditional_hook("remote-mover", action={
                    "binary": fixture.binary, "git_dir": str(fixture.remote),
                    "ref": "refs/heads/" + WIKI_BRANCH, "new": target, "old": fixture.old_wiki_sha,
                })
                with self.assertRaises(publication.WikiPublicationError):
                    self.publish(sha)
                self.assertEqual(fixture.remote_tip(), target)
                self.assert_hook_events(["remote-mover"], sha)
                fixture.run(fixture.remote, ["update-ref", "refs/heads/" + WIKI_BRANCH, fixture.old_wiki_sha, target])
                record = fixture.read_evidence()
                record.update(state="staged", PUBLISHED_WIKI_SHA=None)
                fixture.write_evidence(record)
                fixture.hook_log.unlink()

    def test_hook_moving_local_head_does_not_change_immutable_push_source(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        moved = fixture.commit_tree(fixture.wiki, fixture.source_tree, (sha,))
        fixture.traditional_hook("local-head-mover", action={
            "binary": fixture.binary, "git_dir": str(fixture.wiki / ".git"),
            "ref": "HEAD", "new": moved, "old": sha,
        })
        record = self.publish(sha)
        self.assertEqual(fixture.text(fixture.wiki, ["rev-parse", "HEAD"]), moved)
        self.assertEqual(fixture.remote_tip(), sha)
        self.assertEqual(record["PUBLISHED_WIKI_SHA"], sha)
        self.assert_hook_events(["local-head-mover"], sha)

    def test_postpush_movement_and_remote_head_retargeting_reject_stale_evidence(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        self.publish(sha)
        later = fixture.commit_tree(fixture.wiki, fixture.source_tree, (sha,))
        fixture.run(fixture.wiki, ["push", fixture.endpoints.wiki_url, later + ":refs/heads/" + WIKI_BRANCH])
        with self.assertRaises(publication.WikiPublicationError):
            self.verify()
        fixture.run(fixture.remote, ["update-ref", "refs/heads/" + WIKI_BRANCH, sha, later])
        fixture.run(fixture.remote, ["update-ref", "refs/heads/other-branch", sha])
        fixture.run(fixture.remote, ["symbolic-ref", "HEAD", "refs/heads/other-branch"])
        with self.assertRaises(publication.WikiPublicationError):
            self.verify()

    def test_movement_immediately_after_push_prevents_verified_receipt(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        later = fixture.commit_tree(fixture.wiki, fixture.source_tree, (sha,))
        fixture.run(fixture.wiki, ["push", fixture.endpoints.wiki_url, later + ":refs/heads/race-target"])

        def move_after_push(_repository: Path | None, arguments: Sequence[str],
                            _result: subprocess.CompletedProcess[bytes]) -> None:
            if "push" in arguments:
                fixture.run(fixture.remote, ["update-ref", "refs/heads/" + WIKI_BRANCH, later, sha])

        with self.assertRaises(publication.WikiPublicationError):
            self.publish(sha, git=fixture.controlled_git(after=move_after_push))
        self.assertEqual(fixture.remote_tip(), later)
        self.assertEqual(fixture.read_evidence()["state"], "prepared")
        self.assertIs(fixture.read_evidence()["fresh_clone_verified"], False)

    def test_remote_movement_during_fresh_clone_and_before_completion_is_rejected(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        self.publish(sha)
        actual = publication.verify_fresh_clone

        def move_after_clone(clone: Path, record: Mapping[str, object], *, git: publication.GitRunner) -> None:
            actual(clone, record, git=git)
            fixture.run(fixture.remote, ["update-ref", "refs/heads/" + WIKI_BRANCH, fixture.old_wiki_sha, sha])

        with patch.object(publication, "verify_fresh_clone", side_effect=move_after_clone):
            with self.assertRaises(publication.WikiPublicationError):
                self.verify()
        with self.assertRaises(publication.WikiPublicationError):
            publication.complete_publication(
                fixture.wiki, fixture.evidence, live_review="Reviewed live fixture",
                git=fixture.git, endpoints=fixture.endpoints,
            )
        self.assertNotEqual(fixture.read_evidence()["state"], "complete")

    def test_remote_movement_after_verified_receipt_prevents_completion(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        self.publish(sha)
        actual_write = cast(
            Callable[[Path, Mapping[str, object]], None], getattr(publication, "_write_evidence"),
        )
        written_states: list[object] = []
        moved = False

        def move_after_verified_write(path: Path, record: Mapping[str, object]) -> None:
            nonlocal moved
            actual_write(path, record)
            written_states.append(record["state"])
            if record["state"] == "verified" and not moved:
                moved = True
                fixture.run(fixture.remote, ["update-ref", "refs/heads/" + WIKI_BRANCH,
                                            fixture.old_wiki_sha, sha])

        with patch.object(publication, "_write_evidence", side_effect=move_after_verified_write):
            with self.assertRaises(publication.WikiPublicationError):
                publication.complete_publication(
                    fixture.wiki, fixture.evidence, live_review="Reviewed live fixture",
                    git=fixture.git, endpoints=fixture.endpoints,
                )
        self.assertTrue(moved)
        self.assertEqual(written_states, ["verified"])
        self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
        self.assertEqual(fixture.read_evidence()["state"], "verified")
        self.assertIsNone(fixture.read_evidence()["live_review"])
        self.assertEqual(fixture.read_evidence()["PUBLISHED_WIKI_SHA"], sha)

    def test_fresh_clone_branch_sha_tree_and_hidden_dirty_bytes_are_verified(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        self.publish(sha)
        actual = publication.verify_fresh_clone
        for kind in ("branch", "sha", "tree", "dirty", "hidden-dirty", "untracked"):
            with self.subTest(kind=kind):
                def corrupt_clone(clone: Path, record: Mapping[str, object], *, git: publication.GitRunner) -> None:
                    checked_record = dict(record)
                    if kind == "branch":
                        fixture.run(clone, ["checkout", "--quiet", "-b", "wrong-branch"])
                    elif kind == "sha":
                        fixture.run(clone, ["reset", "--hard", fixture.old_wiki_sha])
                    elif kind == "tree":
                        checked_record["SOURCE_TREE"] = fixture.text(fixture.source, ["rev-parse", fixture.source_sha + "^{tree}"])
                    elif kind == "untracked":
                        (clone / "untracked.tmp").write_bytes(b"extra clone file")
                    else:
                        if kind == "hidden-dirty":
                            fixture.run(clone, ["update-index", "--assume-unchanged", "Home.md"])
                        (clone / "Home.md").write_bytes(b"transformed physical clone bytes\n")
                        if kind == "hidden-dirty":
                            self.assertEqual(fixture.text(clone, ["status", "--porcelain"]), "")
                    actual(clone, checked_record, git=git)

                before = fixture.evidence.read_bytes()
                with patch.object(publication, "verify_fresh_clone", side_effect=corrupt_clone):
                    with self.assertRaises(publication.WikiPublicationError):
                        self.verify()
                self.assertEqual(fixture.evidence.read_bytes(), before)
                self.assertEqual(fixture.remote_tip(), sha)

    def test_reversible_smudge_filter_cannot_hide_fresh_clone_byte_drift(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        self.publish(sha)
        fixture.install_checkout_filter()
        actual = publication.verify_fresh_clone
        inspected = False

        def inspect_filtered_clone(clone: Path, record: Mapping[str, object], *, git: publication.GitRunner) -> None:
            nonlocal inspected
            inspected = True
            self.assertEqual(fixture.text(clone, ["status", "--porcelain"]), "")
            self.assertTrue((clone / "Home.md").read_bytes().endswith(b"physical smudge drift\n"))
            actual(clone, record, git=git)

        before = fixture.evidence.read_bytes()
        with patch.object(publication, "verify_fresh_clone", side_effect=inspect_filtered_clone):
            with self.assertRaisesRegex(publication.WikiPublicationError, "physical"):
                self.verify()
        self.assertTrue(inspected)
        self.assertEqual(fixture.evidence.read_bytes(), before)
        self.assertEqual(fixture.remote_tip(), sha)

    def test_evidence_tampering_cannot_authorize_publication(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        original = fixture.read_evidence()
        changes: tuple[tuple[str, object], ...] = (
            ("SOURCE_TREE", fixture.text(fixture.source, ["rev-parse", fixture.source_sha + "^{tree}"])),
            ("SOURCE_SHA", "0" * 40), ("PRE_PUBLICATION_WIKI_SHA", fixture.wiki_ancestor),
            ("WIKI_BRANCH", "other-branch"), ("SOURCE_IS_CURRENT_MAIN", False),
            ("wiki_url", fixture.fork.as_uri()), ("schema_version", True),
            ("schema_version", 1.0), ("fresh_clone_verified", 1), ("unexpected", "value"),
        )
        for key, value in changes:
            with self.subTest(key=key, value=value):
                record = dict(original)
                record[key] = value
                fixture.write_evidence(record)
                with self.assertRaises(publication.WikiPublicationError):
                    self.publish(sha)
                self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
        fixture.write_evidence(original)
        serialized = fixture.evidence.read_text(encoding="utf-8")
        fixture.evidence.write_text(serialized.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'), encoding="utf-8")
        with self.assertRaises(publication.WikiPublicationError):
            self.publish(sha)
        self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)
        fixture.evidence.write_bytes(b"\xff invalid UTF-8 evidence")
        with self.assertRaises(publication.WikiPublicationError):
            self.publish(sha)
        self.assertEqual(fixture.remote_tip(), fixture.old_wiki_sha)

    def test_guard_requires_exact_urls_one_complete_immutable_row_and_bounded_read(self) -> None:
        fixture = self.fixture
        sha = self.prepare()
        url = fixture.endpoints.wiki_url
        branch = "refs/heads/" + WIKI_BRANCH
        expected = f"{sha} {sha} {branch} {fixture.old_wiki_sha}\n".encode()

        class BoundedInput(BytesIO):
            def read(self, size: int | None = -1) -> bytes:
                if size is None or size < 0 or size > len(expected) + 1:
                    raise AssertionError("Guard input must have a bounded read")
                return super().read(size)

        kwargs = dict(published_sha=sha, branch_ref=branch, old_sha=fixture.old_wiki_sha, wiki_url=url)
        with patch.dict("os.environ", {"GIT_DIR": str(fixture.wiki / ".git")}):
            publication.pre_push_guard(**kwargs, remote_args=(url, url), stdin=BoundedInput(expected))
        payloads = (
            b"", expected[:-1], expected + expected, expected + b"x",
            expected.replace(sha.encode(), b"0" * 40),
            expected.replace(branch.encode(), b"refs/heads/other"),
            expected.replace(fixture.old_wiki_sha.encode(), fixture.wiki_ancestor.encode()),
            expected.replace((sha + " ").encode(), b"(delete) " + b"0" * 40 + b" ", 1),
            b"x" * 100_000,
        )
        for payload in payloads:
            with self.subTest(payload=payload[:100]):
                with self.assertRaises(publication.WikiPublicationError):
                    publication.pre_push_guard(**kwargs, remote_args=(url, url), stdin=BoundedInput(payload))
        for arguments in ((url,), ("origin", url), (url, fixture.fork.as_uri()), (url, url, "extra")):
            with self.subTest(arguments=arguments):
                with self.assertRaises(publication.WikiPublicationError):
                    publication.pre_push_guard(**kwargs, remote_args=arguments, stdin=BoundedInput(expected))


if __name__ == "__main__":
    unittest.main()
