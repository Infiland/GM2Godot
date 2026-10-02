# Wiki source and publication

The reviewed GitHub Wiki source lives in [`docs/wiki/`](wiki/). The live Wiki is a separate Git repository and must be published only from a merged main-repository revision. A source pull request preparing live publication must reference—but must not auto-close—the live documentation issue (#712); close that issue only after the merged pages are published and verified live. A pull request fixing the publication process can close its own process issue after its checks pass and it merges.

The canonical page set is:

- `Home.md`
- `Installation.md`
- `Quick-Start-Conversion.md`
- `Compatibility-and-Limitations.md`
- `Diagnostics-and-Troubleshooting.md`
- `Generated-Project-and-Runtime.md`
- `Contributing-and-Testing.md`
- `Maintainer-Release-and-Wiki.md`
- `_Sidebar.md`

Follow the complete, user-visible procedure in [`Maintainer-Release-and-Wiki.md`](wiki/Maintainer-Release-and-Wiki.md). Use `python scripts/wiki_publication.py stage`, `publish`, `verify`, and `complete`; the public commands use only the canonical source and Wiki URLs. Git 2.54 or later is required, together with a positive `git hook list --show-scope pre-push` capability check.

The helper fetches canonical `main` into a fresh private ref with replacement objects disabled, requires the full `SOURCE_SHA` to be its ancestor, and resolves `SOURCE_TREE` from `SOURCE_SHA:docs/wiki`. This is the Wiki subtree, not the main repository's root tree. `CANONICAL_MAIN_SHA` and `SOURCE_IS_CURRENT_MAIN` disclose whether the selected merged main-repository SHA matched main at the recorded fetch; an older merged source remains explicitly visible. Git URL rewrites, legacy history grafts, and repository/index override environment variables stop the operation.

The complete source, staged index, publication commit, and fresh clone must contain exactly the nine root `100644 blob` entries above. Extra Markdown or Textile pages, nested trees (including empty trees), symlinks, executables, gitlinks, and ordinary or ignored untracked files stop publication. Review live pages before staging and reconcile every browser-only change through a source pull request. The initial Wiki may contain only the exact reviewed `Home.md`; arbitrary partial inventories are rejected. Staging uses `git add --all` and requires `git write-tree == SOURCE_TREE`. Direct physical-byte checks also detect tracked drift hidden by index flags or checkout filters.

Commit normally after inspecting the entire staged diff. The publication commit must have exactly one direct parent, `PRE_PUBLICATION_WIKI_SHA`, and root tree `SOURCE_TREE`. The helper discovers the actual symbolic `WIKI_BRANCH`; it never assumes `main` or `master`. Its ordinary push submits the literal `PUBLISHED_WIKI_SHA` to that explicit branch at the canonical Wiki URL, with `--no-follow-tags`. It uses no force option, `+` refspec, or hook bypass.

A fresh command-scoped configured pre-push hook verifies the immutable source, destination, URL arguments, exactly one stdin ref row, and the advertised old SHA. Existing configured/traditional hooks and custom `core.hooksPath` remain active, without persistent configuration changes. A rewind before connection is rejected by the guard; movement after advertisement is rejected by Git's ordinary expected-old-SHA update. Movement away from and back to the identical SHA is indistinguishable from no movement.

The URL gate conservatively rejects every applicable `pushInsteadOf` prefix and alternate or multiple URLs on a remote named exactly as the canonical Wiki URL. Unrelated rewrite rules remain allowed; the helper only reads configuration.

Keep the durable JSON evidence outside both checkouts. It records `SOURCE_SHA`, `SOURCE_TREE`, `CANONICAL_MAIN_SHA`, `SOURCE_IS_CURRENT_MAIN`, `WIKI_BRANCH`, `PRE_PUBLICATION_WIKI_SHA`, and `PUBLISHED_WIKI_SHA`. Publication verifies symbolic remote `HEAD`, its named branch, and the exact published SHA, then makes an explicit-branch fresh clone and checks its complete tree, physical bytes, and clean checkout. After reviewing live rendering and links, `complete` repeats these checks immediately before recording completion. Attach the evidence and live review result to the documentation issue before closing it. A stale remote state or failed verification requires reconciliation and fresh evidence.
