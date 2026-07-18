# Release and Wiki Maintenance

> **Applies to:** GM2Godot 0.7.9 · GameMaker LTS 2026 · Godot 4.7.1
>
> **Last reviewed:** 2026-07-18

This page documents the current maintainer path for a versioned release and for publishing the reviewed Wiki sources. It does not replace branch protection or repository settings.

## Release model

`src/version.py` is the release trigger and source version. A pull request that changes it starts cross-platform artifact builds; the merged change starts the `Build and Release` workflow on `main`. The workflow builds Linux, macOS, and Windows archives, creates the macOS DMG, and publishes the GitHub release/tag. Every new release must use a new version. A rerun or manual dispatch for a version whose exact remote tag already exists is an intentional no-op: the workflow skips build and publication without changing the existing release. If the remote tag lookup fails for any reason other than an absent exact ref, the workflow stops before building.

The release workflow is canonical at [`.github/workflows/release.yml`](https://github.com/Infiland/GM2Godot/blob/main/.github/workflows/release.yml).

## Versioned-change checklist

Before opening the pull request:

- [ ] Update `src/version.py`.
- [ ] Add the dated version entry to `CHANGELOG.md`.
- [ ] Update the current source version in `README.md`.
- [ ] Update version examples in issue templates and version tests.
- [ ] Review all `docs/wiki/` **Applies to** banners and change those whose claims were revalidated.
- [ ] Review Wiki links, navigation, target-version wording, and any user-facing workflow changed by the release.
- [ ] Run the validation required by the changed code and keep Pyright/Ruff clean when Python or generated-code logic changed.
- [ ] If the pull request is preparing the first live Wiki publication, use `Refs #712` (or equivalent prose), not `Closes #712`/`Fixes #712`.

Before merging:

- [ ] Confirm `refs/tags/v<version>` does not already exist on the GitHub remote; do not rely only on a local checkout's tag list.
- [ ] Confirm all pull-request checks pass, including exact Godot 4.7.1 smoke and current GameMaker LTS conversion gates.
- [ ] Confirm Linux, macOS, and Windows build jobs produce non-empty artifacts.
- [ ] Confirm the pull request references the intended issue, uses the correct closure timing, and does not absorb unrelated work.

After merging:

- [ ] Confirm the tag points to the intended `main` commit.
- [ ] Confirm the release is neither draft nor prerelease and all expected assets are present.
- [ ] Confirm post-merge tests, exact-LTS conversions, Godot smoke, and release jobs pass.
- [ ] If `docs/wiki/` changed, publish the exact merged pages and verify the live Wiki before closing the documentation issue. Record the merged source SHA and published Wiki SHA on the issue before closing it.

## Canonical Wiki sources

The reviewable source is [`docs/wiki/`](https://github.com/Infiland/GM2Godot/tree/main/docs/wiki) in the main repository. The rendered GitHub Wiki is a separate Git repository at:

```text
https://github.com/Infiland/GM2Godot.wiki.git
```

Do not edit version-sensitive Wiki prose only in the browser. A browser-only correction will drift from the reviewed source and can be overwritten by the next publication.

## First publication

GitHub requires the first Wiki page to be created through the repository Wiki interface before the Wiki Git repository can be cloned.

1. Merge the reviewed main-repository pull request.
2. Resolve and record the exact merged `main` SHA. Publish from that revision, not from an unmerged branch or a dirty working tree.
3. Create the initial `Home` page in the GitHub Wiki using the exact merged `docs/wiki/Home.md` content. Keep issue #712 open.
4. Clone `https://github.com/Infiland/GM2Godot.wiki.git` into a new temporary directory and confirm the checkout is clean.
5. Record the checked-out branch and `git rev-parse HEAD` as the pre-publication Wiki SHA; do not assume the branch is named `main` or `master`.
6. Copy only the canonical Markdown inventory from the merged `docs/wiki/`, including `_Sidebar.md`. Stop if the Wiki has an extra or browser-only page: reconcile it into the canonical source through review before deleting or overwriting it.
7. Stage the Markdown changes and inspect `git diff --cached --check`, `git diff --cached --name-status`, and the full staged diff. The staged inventory and content must match the merged source exactly.
8. Commit with the merged main-repository SHA in the message.
9. Fetch the Wiki branch again and confirm its remote tip still equals the recorded pre-publication Wiki SHA. If it changed, stop and reconcile the concurrent update; never force-push.
10. Push `HEAD` to the explicitly recorded Wiki branch.

For later publications, begin by pulling the live Wiki and confirming it has no unreviewed browser-only changes. Reconcile any such changes into `docs/wiki/` through a normal pull request before overwriting them.

## Post-publication verification

Check more than an HTTP success code: an uninitialized Wiki redirects to the repository root.

- Open `https://github.com/Infiland/GM2Godot/wiki` and confirm the final page remains under `/GM2Godot/wiki`.
- Open every sidebar page and confirm headings, code blocks, and local navigation render.
- Verify release, issue-template, manual, and versioned Godot-documentation links.
- Confirm `git ls-remote https://github.com/Infiland/GM2Godot.wiki.git HEAD` succeeds.
- Clone the Wiki into a second clean temporary directory and compare its Markdown inventory and bytes with `docs/wiki/` at the recorded merged source SHA.
- Record the merged source SHA, published Wiki SHA, and verification result on the documentation issue; only then close it.

## Rollback and ownership

Repository maintainers own the Wiki source and publication check. Wiki changes are Git commits, so revert the offending publication commit on the recorded Wiki branch and push the revert normally when a publication is wrong. Do not reset or force-push. Verify the restored live pages, then fix the canonical source through a main-repository pull request so the next sync does not reintroduce the problem.

Never place credentials, private fixture data, or generated failure artifacts in Wiki history.
