# Wiki source and publication

The reviewed GitHub Wiki source lives in [`docs/wiki/`](wiki/). The live Wiki is a separate Git repository and must be published only from a merged main-repository revision. A source pull request must reference—but must not auto-close—the documentation issue; close it only after the merged pages are published and verified live.

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

Follow the complete, user-visible procedure in [`Maintainer-Release-and-Wiki.md`](wiki/Maintainer-Release-and-Wiki.md). Record both the merged main-repository SHA and the pre-publication Wiki SHA before pushing so the publication is traceable and can be reverted without rewriting Wiki history.
