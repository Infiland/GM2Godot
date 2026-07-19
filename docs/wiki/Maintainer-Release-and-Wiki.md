# Release and Wiki Maintenance

> **Applies to:** GM2Godot 0.7.31 · GameMaker LTS 2026 · Godot 4.7.1
>
> **Last reviewed:** 2026-07-19

This page documents the current maintainer path for a versioned release and for publishing the reviewed Wiki sources. It does not replace branch protection or repository settings.

## Release model

`src/version.py` is the release trigger and source version. A pull request that changes it starts cross-platform artifact builds; the merged change starts the `Build and Release` workflow on `main`. The workflow builds Linux, macOS, and Windows archives, creates the macOS DMG, generates `SHA256SUMS` from those four final payloads, and publishes all five assets with the GitHub release/tag. Every new release must use a new version.

Publication-capable push and manual-dispatch runs share one concurrency group across refs, covering the exact remote-tag check, builds, and publication. Pull-request validation remains independent. The active publisher is not cancelled and one additional publisher may remain pending; GitHub's default concurrency behavior can replace that pending run if a third publisher arrives, and it does not guarantee FIFO ordering. When the surviving waiter starts, it rechecks the exact remote tag. An absent tag after a clean prepublication failure lets it try the normal build and publication path. A present tag keeps builds and publication skipped, but the run succeeds only after the existing release passes the integrity audit described below.

When the exact remote tag is absent, the workflow uses an authenticated, paginated release query before any platform build and repeats the negative check to reduce listing-consistency risk. GitHub returns drafts only to a push-capable token, so this check runs in a separate non-PR job with `contents: write`; that job does not check out or execute repository code. Any exact-tag release object observed by those checks—including a draft, partial, or unexpectedly published release—fails closed with identifying details rather than being reused or changed automatically. An API, authentication, pagination, or response-validation failure also stops publication. Record the diagnostic and run URL, inspect the tag, release, and expected asset inventory, then have a maintainer clean up the inconsistent state explicitly before dispatching a new run.

After the platform payloads and canonical manifest are ready, the create-only publisher requires the event ref to be exactly `refs/heads/main`, binds `RELEASE_TARGET_SHA` to that event's 40-hex commit, seals the five fixed regular files by identity, size, SHA-256 digest, and content type, and verifies the checksum manifest bytes. It then verifies the current `main` ref and takes three fresh draft-aware tag/release-absence snapshots immediately before mutation. The publisher creates the exact tag ref first and accepts only its validated `201 Created` receipt. It next creates a draft for that claimed exact tag while sending the exact target SHA, and accepts only the validated draft-creation `201`; the returned positive release ID is the only release ID the run may ever mutate.

Before each of the five uploads and immediately before finalization, the publisher verifies the exact tag target, the run-owned draft by ID, the exact already-uploaded asset prefix, the absence of a published exact-tag release, and one sole exact-tag release ID in the authenticated draft-aware listing. A temporarily empty exact-tag match set in an otherwise well-formed authenticated listing is the only retryable state: the publisher repeats the entire five-read gate up to seven times with 1, 2, 4, 8, 16, and 32-second delays, persisting every decision before it waits. Any foreign or duplicate ID, malformed response, or other drift stops immediately. Uploads use fixed names, MIME types, content lengths, and streamed bytes, and each must return a unique validated `201` size/digest receipt. The one publication `PATCH` targets only the run-owned numeric ID. Final verification independently checks release by ID, published release by tag, direct tag target, the exact five assets, and the sole exact-tag listing.

Mutation requests are never retried: a timeout, malformed accepted-status body, collision, authorization failure, `502` starter possibility, or other ambiguous response may have changed remote state. The publisher never adopts a lookup ID, updates a ref, skips or replaces an asset, deletes partial state, or automatically rolls back. An atomic Actions artifact records every mutation intent, accepted ownership receipt, uploaded prefix, request ID, observation, and failure phase. Follow its ID-first manual-recovery links and prove ownership before changing anything or rerunning.

When the exact remote tag is present, a separate non-PR integrity job also uses a push-capable token so GitHub includes draft releases, but every API operation is an explicit GET. The job does not check out repository code or run a publisher. It requires exactly one exact-tag release that is published and not a prerelease, then independently paginates that release's assets and requires the five unique uploaded files named in the post-merge checklist. Every positive size and `sha256:` digest is validated before any download. The job downloads each asset by numeric asset ID into a private temporary directory, verifies all five local sizes and hashes against GitHub metadata, requires the canonical four-line `SHA256SUMS` bytes and three-way payload digest equality, and runs GNU `sha256sum --check --strict`. It snapshots the exact tag object plus stable release and asset fields before and after downloads; a moved tag or concurrent critical-state change fails the audit. Volatile download counters are deliberately excluded. This is a point-in-time consistency check, not a lock against an external UI/API publisher after the final snapshot. A failure is read-only and requires manual recovery; the workflow never repairs, replaces, republishes, or retags existing state automatically.

Preserve a completed release and its asset IDs and digests. The concurrency group serializes this workflow's publishers, not an external UI/API publisher.

The release workflow is canonical at [`.github/workflows/release.yml`](https://github.com/Infiland/GM2Godot/blob/main/.github/workflows/release.yml).

Pull requests that change the release workflow, create-only publisher, or dedicated smoke workflow run [`.github/workflows/release-action-smoke.yml`](https://github.com/Infiland/GM2Godot/blob/main/.github/workflows/release-action-smoke.yml). The smoke is independent of the project version and remote tag state. It verifies a deterministic cross-job artifact round-trip through the exact production upload/download pins, loads the checked-out local publisher with an unusable token, and proves a guaranteed-missing local asset stops it before any API request while producing a failure receipt with zero mutation intents.

## macOS bundle identity

The checked-in `packaging/macos/GM2Godot.spec` is the only supported macOS release build definition. It loads the strict policy in `packaging/macos/bundle_metadata.py` and stamps `GM2Godot.app` with the stable reverse-domain identifier `land.infi.gm2godot`. Both `CFBundleShortVersionString` and `CFBundleVersion` equal the exact three-component numeric release version in `src/version.py`. GM2Godot produces one production macOS build for each source release version; do not substitute a workflow run number, timestamp, or mutable counter.

Before artifact upload, `scripts/verify_macos_bundle_metadata.py` checks the source app, the app embedded in `GM2Godot-macos.zip`, and the app mounted read-only from `GM2Godot-macos.dmg`. All three copies must have the exact policy values and byte-identical `Info.plist` contents. A missing key, non-string value, placeholder, unsafe app/plist archive layout, malformed plist, or inconsistent digest fails the release.

This policy does not select the macOS architecture tracked in issue #736 and does not sign or notarize the app tracked in issue #737.

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
- [ ] Confirm all pull-request checks pass, including exact Godot 4.7.1 smoke and current GameMaker LTS conversion gates.
- [ ] Confirm Linux, macOS, and Windows build jobs produce non-empty artifacts.
- [ ] Confirm the Linux build reports no unresolved shared libraries and its extracted-ZIP `qxcb` GUI smoke passes with the required Qt GUI/XCB runtime inventory and excluded TIFF plugin.
- [ ] Confirm the macOS build verifies the exact bundle identifier and source release version in the `.app`, ZIP, and DMG before upload.
- [ ] Confirm the pull request references the intended issue, uses the correct closure timing, and does not absorb unrelated work.

After merging:

- [ ] Confirm the tag points to the intended `main` commit.
- [ ] Confirm the release is neither draft nor prerelease and has exactly five unique, non-empty assets: the four platform payloads and `SHA256SUMS`.
- [ ] Download the run's `release-publisher-receipt` Actions artifact and confirm it ends at `verified`, contains one accepted tag claim, one accepted draft creation, five accepted asset receipts, and one accepted finalization for the same release ID.
- [ ] Download all five assets, run `sha256sum --check --strict SHA256SUMS`, and confirm each payload digest also matches the hexadecimal value after the `sha256:` prefix in GitHub's `assets[].digest` field.
- [ ] Inspect the downloaded macOS ZIP and read-only mounted DMG and confirm their app bundle metadata and `Info.plist` digests match each other and the release policy.
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
