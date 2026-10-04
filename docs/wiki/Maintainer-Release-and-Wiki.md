# Release and Wiki Maintenance

> **Applies to:** GM2Godot 0.8.39 · GameMaker LTS 2026 · Godot 4.7.2
>
> **Last reviewed:** 2026-10-04

This page documents the current maintainer path for a versioned release and for publishing the reviewed Wiki sources. It does not replace branch protection or repository settings.

## Release model

`src/version.py` is the source version and build trigger. A pull request that changes it starts cross-platform artifact builds; the merged change starts the `Build and Release` workflow on `main`. Source `0.8.39` uses six payloads—Linux and Windows archives plus separate native macOS arm64 and x86_64 ZIP/DMG pairs—and `SHA256SUMS` as the seventh asset. Aggregation and publication follow the successful native build gates on `main`. Every new release must use a new version.

The publisher and integrity procedure below describes the current seven-asset contract. Its checksum manifest has exactly six payload rows in lexical filename order. [Release 0.8.17](https://github.com/Infiland/GM2Godot/releases/tag/v0.8.17) published this seven-asset contract. Preserve its exact release audit and the older `0.8.15` five-asset audit as separate historical evidence; each new version needs its own main build and publication checks.

Publication-capable push and manual-dispatch runs share one concurrency group across refs, covering the exact remote-tag check, builds, and publication. Pull-request validation remains independent. The active publisher is not cancelled and one additional publisher may remain pending; GitHub's default concurrency behavior can replace that pending run if a third publisher arrives, and it does not guarantee FIFO ordering. When the surviving waiter starts, it rechecks the exact remote tag. An absent tag after a clean prepublication failure lets it try the normal build and publication path. A present tag keeps builds and publication skipped, but the run succeeds only after the existing release passes the integrity audit described below.

When the exact remote tag is absent, the workflow uses an authenticated, paginated release query before any platform build and repeats the negative check to reduce listing-consistency risk. GitHub returns drafts only to a push-capable token, so this check runs in a separate non-PR job with `contents: write`; that job does not check out or execute repository code. Any exact-tag release object observed by those checks—including a draft, partial, or unexpectedly published release—fails closed with identifying details rather than being reused or changed automatically. An API, authentication, pagination, or response-validation failure also stops publication. Record the diagnostic and run URL, inspect the tag, release, and expected asset inventory, then have a maintainer clean up the inconsistent state explicitly before dispatching a new run.

After the platform payloads and canonical manifest are ready, the create-only publisher requires the event ref to be exactly `refs/heads/main`, binds `RELEASE_TARGET_SHA` to that event's 40-hex commit, seals the seven fixed regular files by identity, size, SHA-256 digest, and content type, and verifies the checksum manifest bytes. It then verifies the current `main` ref and takes three fresh draft-aware tag/release-absence snapshots immediately before mutation. The publisher creates the exact tag ref first and accepts only its validated `201 Created` receipt. It next creates a draft for that claimed exact tag while sending the exact target SHA, and accepts only the validated draft-creation `201`; the returned positive release ID is the only release ID the run may ever mutate.

Before each of the seven uploads and immediately before finalization, the publisher verifies the exact tag target, the run-owned draft by ID, the exact already-uploaded asset prefix, the absence of a published exact-tag release, and one sole exact-tag release ID in the authenticated draft-aware listing. A temporarily empty exact-tag match set in an otherwise well-formed authenticated listing is the only retryable state: the publisher repeats the entire five-read gate up to seven times with 1, 2, 4, 8, 16, and 32-second delays, persisting every decision before it waits. Any foreign or duplicate ID, malformed response, or other drift stops immediately. Uploads use fixed names, MIME types, content lengths, and streamed bytes, and each must return a unique validated `201` size/digest receipt. The one publication `PATCH` targets only the run-owned numeric ID. Final verification independently checks release by ID, published release by tag, direct tag target, the exact seven assets, and the sole exact-tag listing.

Mutation requests are never retried: a timeout, malformed accepted-status body, collision, authorization failure, `502` starter possibility, or other ambiguous response may have changed remote state. The publisher never adopts a lookup ID, updates a ref, skips or replaces an asset, deletes partial state, or automatically rolls back. An atomic Actions artifact records every mutation intent, accepted ownership receipt, uploaded prefix, request ID, observation, and failure phase. Follow its ID-first manual-recovery links and prove ownership before changing anything or rerunning.

When the exact remote tag is present, a separate non-PR integrity job also uses a push-capable token so GitHub includes draft releases, but every API operation is an explicit GET. The job does not check out repository code or run a publisher. It requires exactly one exact-tag release that is published and not a prerelease, then independently paginates that release's assets and requires the seven unique uploaded files named in the post-merge checklist. Every positive size and `sha256:` digest is validated before any download. The job downloads each asset by numeric asset ID into a private temporary directory, verifies all seven local sizes and hashes against GitHub metadata, requires the canonical six-line `SHA256SUMS` bytes and three-way payload digest equality, and runs GNU `sha256sum --check --strict`. It snapshots the exact tag object plus stable release and asset fields before and after downloads; a moved tag or concurrent critical-state change fails the audit. Volatile download counters are deliberately excluded. This is a point-in-time consistency check, not a lock against an external UI/API publisher after the final snapshot. A failure is read-only and requires manual recovery; the workflow never repairs, replaces, republishes, or retags existing state automatically.

Preserve a completed release and its asset IDs and digests. The concurrency group serializes this workflow's publishers, not an external UI/API publisher.

The release workflow is canonical at [`.github/workflows/release.yml`](https://github.com/Infiland/GM2Godot/blob/main/.github/workflows/release.yml).

Pull requests that change the release workflow, create-only publisher, or dedicated smoke workflow run [`.github/workflows/release-action-smoke.yml`](https://github.com/Infiland/GM2Godot/blob/main/.github/workflows/release-action-smoke.yml). The smoke is independent of the project version and remote tag state. It verifies a deterministic cross-job artifact round-trip through the exact production upload/download pins, loads the checked-out local publisher with an unusable token, and proves a guaranteed-missing local asset stops it before any API request while producing a failure receipt with zero mutation intents.

## macOS bundle identity and native gate

The checked-in `packaging/macos/GM2Godot.spec` is the only supported macOS build definition. It loads the strict policy in `packaging/macos/bundle_metadata.py` and stamps `GM2Godot.app` with the stable reverse-domain identifier `land.infi.gm2godot`. Both `CFBundleShortVersionString` and `CFBundleVersion` equal the exact three-component numeric source version in `src/version.py` in both native architecture lanes; do not substitute a workflow run number, timestamp, or mutable counter.

Before artifact upload, `scripts/verify_macos_bundle_metadata.py` checks each source app, its matching `GM2Godot-macos-<architecture>.zip`, and its matching `GM2Godot-macos-<architecture>.dmg` mounted read-only. All three copies must have the exact policy values and byte-identical `Info.plist` contents, including `LSMinimumSystemVersion` exactly `15.0`. The verifier reads native headers and load commands and requires a non-empty Mach-O inventory containing the main executable. Every native member must use the expected thin architecture and declare a macOS deployment target no higher than 15.0; the relative native paths, architectures, and deployment targets must agree across all three forms. Malformed or universal native members, unsafe archive paths or links, inconsistent inventories, and invalid metadata fail the build.

The native CI lanes use matching CPython 3.12.10 interpreters and invoke this gate with `--expected-architecture arm64` or `--expected-architecture x86_64`. They produce `GM2Godot-macos-arm64.zip`/`.dmg` and `GM2Godot-macos-x86_64.zip`/`.dmg`. The GUI gate launches only a fresh private extraction of the exact final ZIP on the matching native host, verifies its extracted content, and requires GUI readiness followed by a bounded clean exit before upload. The historical `0.8.15` Mac downloads remain arm64. Developer ID signing and notarization remain tracked in issue #737; these gates do not establish Gatekeeper trust or promise an optional Deep component build for Intel.

## Linux packaged-GUI gate

The packaged Linux baseline is Ubuntu 24.04 x86_64. The Linux build installs the exact Qt GUI/XCB runtime-package inventory in `packaging/linux/qt-xcb-runtime-packages.txt` before PyInstaller analysis, including Ubuntu's `libegl1` and `libgl1` providers required directly by QtGui, and uses the reviewed hook under `packaging/linux/hooks/` to exclude only Qt's unused TIFF plugin. Any `Library not found` warning fails the build. Before upload, the workflow inspects the one-file archive for the `qxcb` plugin and all required XCB SONAMEs, rejects the TIFF plugin, and runs `scripts/verify_linux_gui_artifact.py` against the extracted final ZIP under Xvfb with `QT_QPA_PLATFORM=xcb`. Success requires the main window to reach the Qt event loop and write the exact one-use readiness receipt before a bounded clean exit; missing loaders, platform-plugin failures, unsafe archive metadata, an immediate crash, a timeout, or unresolved captured diagnostics fail the matrix job.

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
- [ ] Confirm all pull-request checks pass, including exact Godot 4.7.2 smoke and GameMaker LTS 2026 conversion gates.
- [ ] Confirm Linux, Windows, macOS arm64, and macOS x86_64 build jobs produce non-empty artifacts.
- [ ] Confirm the Linux build reports no unresolved shared libraries and its extracted-ZIP `qxcb` GUI smoke passes with the required Qt GUI/XCB runtime inventory and excluded TIFF plugin.
- [ ] Confirm both native macOS builds verify bundle identity, source version, the exact macOS 15.0 minimum, and matching thin-arm64 or thin-x86_64 native inventories in each `.app`, ZIP, and DMG, then pass the GUI gate from a fresh final-ZIP extraction before upload.
- [ ] Confirm aggregation, publisher sealing, and existing-release integrity checks all require the same six canonical payload names and `SHA256SUMS`; generic Mac names cannot substitute for either native pair.
- [ ] Confirm the pull request references the intended issue, uses the correct closure timing, and does not absorb unrelated work.

After merging:

- [ ] Confirm post-merge tests, exact-LTS conversions, Godot smoke, and all four build jobs pass, followed by successful release aggregation and publication for the intended source SHA.
- [ ] Confirm the tag points to the intended `main` commit.
- [ ] Confirm the release is neither draft nor prerelease and has exactly seven unique, non-empty assets: the six payloads named below and `SHA256SUMS`.
- [ ] Download the run's `release-publisher-receipt` Actions artifact and confirm it ends at `verified`, contains one accepted tag claim, one accepted draft creation, seven accepted asset receipts, and one accepted finalization for the same release ID.
- [ ] Download all seven assets, run `sha256sum --check --strict SHA256SUMS`, and confirm each payload digest also matches the hexadecimal value after the `sha256:` prefix in GitHub's `assets[].digest` field.
- [ ] Inspect each downloaded macOS ZIP and its matching read-only mounted DMG and confirm their bundle metadata, `Info.plist` digests, and native inventories match each other, their architecture, and the release policy.
- [ ] If `docs/wiki/` changed, publish the exact merged pages and verify the live Wiki before closing the documentation issue. Record the merged source SHA and published Wiki SHA on the issue before closing it.

The canonical `SHA256SUMS` payload order is:

```text
GM2Godot-linux.zip
GM2Godot-macos-arm64.dmg
GM2Godot-macos-arm64.zip
GM2Godot-macos-x86_64.dmg
GM2Godot-macos-x86_64.zip
GM2Godot-windows.zip
```

Historical `0.8.15` has Linux and Windows ZIPs, generic `GM2Godot-macos.zip`/`.dmg` arm64 payloads, and `SHA256SUMS`: four payloads and five assets. Preserve its four-row manifest, five-upload receipt, and dated download evidence; the current seven-asset audit must not silently accept the legacy inventory.

## Canonical Wiki sources

The reviewable source is [`docs/wiki/`](https://github.com/Infiland/GM2Godot/tree/main/docs/wiki) in the main repository. The rendered GitHub Wiki is a separate Git repository at:

```text
https://github.com/Infiland/GM2Godot.wiki.git
```

Do not edit version-sensitive Wiki prose only in the browser. A browser-only correction will drift from the reviewed source and can be overwritten by the next publication.

## First publication

GitHub requires the first Wiki page to be created through the repository Wiki interface before the Wiki Git repository can be cloned.

1. Merge the reviewed main-repository pull request and select its full merged source SHA. Keep issue #712 open until live verification is complete.
2. Create the initial `Home` page in the GitHub Wiki using the exact merged `docs/wiki/Home.md` bytes. The initialization commit may contain only this reviewed page.
3. With Git 2.54 or later, clone the canonical Wiki into a disposable directory. Inspect every live path and its bytes before replacement. Stop and reconcile extra or browser-only changes into `docs/wiki/` through a normal source pull request. Later publications require the full nine-page canonical inventory; arbitrary partial page sets are rejected.
4. From the main-repository root, use the reviewed helper below. Choose an evidence path outside both checkouts; do not put receipts in the Wiki root.

```bash
SOURCE_REPO="$PWD"
SOURCE_SHA="PASTE_FULL_MERGED_SHA"
WIKI_DIR="/absolute/path/to/disposable-wiki"
EVIDENCE="/absolute/path/outside-both-checkouts/wiki-publication.json"
git clone https://github.com/Infiland/GM2Godot.wiki.git "$WIKI_DIR"
python scripts/wiki_publication.py stage --source-repository "$SOURCE_REPO" \
  --source-sha "$SOURCE_SHA" --wiki-repository "$WIKI_DIR" --evidence "$EVIDENCE"
git -C "$WIKI_DIR" diff --cached --check
git -C "$WIKI_DIR" diff --cached --name-status
git -C "$WIKI_DIR" diff --cached
git -C "$WIKI_DIR" commit -m "Publish reviewed Wiki source $SOURCE_SHA"
PUBLISHED_WIKI_SHA=$(git -C "$WIKI_DIR" rev-parse HEAD)
python scripts/wiki_publication.py publish --wiki-repository "$WIKI_DIR" \
  --published-sha "$PUBLISHED_WIKI_SHA" --evidence "$EVIDENCE"
```

Review the complete staged diff before the normal commit. `stage` fetches `refs/heads/main` from `https://github.com/Infiland/GM2Godot.git` into a fresh private ref and requires `SOURCE_SHA` to be a canonical-main ancestor. It resolves `SOURCE_TREE` from `SOURCE_SHA:docs/wiki`, not the full main-repository root tree. The source, staged index (`git add --all`, then `git write-tree == SOURCE_TREE`), and committed Wiki root must contain exactly nine `100644 blob` entries: `Home.md`, `Installation.md`, `Quick-Start-Conversion.md`, `Compatibility-and-Limitations.md`, `Diagnostics-and-Troubleshooting.md`, `Generated-Project-and-Runtime.md`, `Contributing-and-Testing.md`, `Maintainer-Release-and-Wiki.md`, and `_Sidebar.md`. Extra `.md`/`.textile` pages, nested or empty trees, symlinks, executable entries, gitlinks, tracked drift, and ordinary or ignored untracked files stop the process. Physical bytes are checked independently of index flags and checkout filters.

The evidence records `SOURCE_SHA`, `SOURCE_TREE`, `WIKI_BRANCH`, `PRE_PUBLICATION_WIKI_SHA`, `PUBLISHED_WIKI_SHA`, `CANONICAL_MAIN_SHA`, and `SOURCE_IS_CURRENT_MAIN`. The last boolean says whether the source matched main at the recorded canonical fetch; an older merged source remains explicitly disclosed. The helper rejects URL rewrites, replacement-object interpretation, legacy history grafts, and repository/index override variables while retaining normal user configuration.

Push URL checks read effective configuration and conservatively reject any applicable `pushInsteadOf` prefix, or alternate/multiple URLs on a remote named exactly as the canonical Wiki URL. Unrelated rewrite rules are allowed; no persistent remote or hook configuration is changed.

`publish` requires exactly one direct parent equal to `PRE_PUBLICATION_WIKI_SHA`, an exact subtree match, and a clean checkout. It discovers the symbolic Wiki default branch instead of assuming `main` or `master`. A positive `git hook list --show-scope pre-push` check proves the fresh command-scoped guard is enabled. All configured/traditional hooks and custom `core.hooksPath` remain active. The guard requires both remote arguments to equal the canonical Wiki URL and stdin to contain exactly one literal published-SHA ref row with the recorded advertised old SHA.

The ordinary push uses the immutable `PUBLISHED_WIKI_SHA`, the explicitly recorded branch, the canonical Wiki URL, and `--no-follow-tags`. Never force-push, use a `+` refspec, bypass hooks, or substitute mutable `HEAD`/`origin` in this gate. A preconnection rewind is rejected by the advertised-old-SHA guard; a concurrent change after advertisement is rejected by Git's ordinary server update. Movement away from and back to the identical SHA cannot be distinguished from no movement. If a push is interrupted, the durable evidence remains in `prepared` state: reconcile the remote, then use `verify` if that exact commit arrived. Start a new reviewed checkout and evidence file for a new publication attempt.

## Post-publication verification

Check more than an HTTP success code: an uninitialized Wiki redirects to the repository root.

- Open `https://github.com/Infiland/GM2Godot/wiki` and confirm the final page remains under `/GM2Godot/wiki`.
- Open every sidebar page and confirm headings, code blocks, and local navigation render.
- Verify release, issue-template, manual, and versioned Godot-documentation links.
- `publish` verifies that symbolic remote `HEAD` targets `WIKI_BRANCH`, and both `HEAD` and that named branch equal `PUBLISHED_WIKI_SHA`. It makes a fresh explicit-branch clone and requires the exact commit, `SOURCE_TREE`, all nine physical source blobs, and a clean checkout, then rechecks the remote.
- Repeat the checks after any interruption with `python scripts/wiki_publication.py verify --wiki-repository "$WIKI_DIR" --evidence "$EVIDENCE"`.
- After the live page/link review above, run the completion gate immediately before recording the result:

```bash
python scripts/wiki_publication.py complete --wiki-repository "$WIKI_DIR" \
  --evidence "$EVIDENCE" --live-review "Reviewed all eight rendered pages, sidebar navigation, and external links"
```

`complete` performs a fresh clone and remote-state recheck again; a moved branch or retargeted symbolic `HEAD` stops completion. Record all seven binding values, the durable evidence, and the live review result on the documentation issue; only then close it. A successful HTTP response or successful `ls-remote` alone is insufficient.

## Rollback and ownership

Repository maintainers own the Wiki source and publication check. Wiki changes are Git commits, so revert the offending publication commit on the recorded Wiki branch and push the revert normally when a publication is wrong. Do not reset or force-push. Verify the restored live pages, then fix the canonical source through a main-repository pull request so the next sync does not reintroduce the problem.

Never place credentials, private fixture data, or generated failure artifacts in Wiki history.
