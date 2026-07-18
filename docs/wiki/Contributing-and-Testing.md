# Contributing and Testing

> **Applies to:** GM2Godot 0.7.6 · GameMaker LTS 2026 · Godot 4.7.1
>
> **Last reviewed:** 2026-07-18

This page is the short contributor route map. The repository's [CONTRIBUTING.md](https://github.com/Infiland/GM2Godot/blob/main/CONTRIBUTING.md) and `AGENTS.md` remain authoritative for development rules.

## Set up a development checkout

```bash
git clone https://github.com/YOUR_USERNAME/GM2Godot.git
cd GM2Godot
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

GM2Godot requires Python 3.12 or later. Install Godot 4.7.1 and set `GODOT_BIN` when a change needs generated-resource or runtime validation.

## Choose the right extension point

- **GML syntax or lowering:** work under `src/conversion/gml_transpiler_parts/` and add focused parser/lowering tests.
- **GML API or generated runtime behavior:** update the API manifest/dispatch metadata and the owning segment under `src/conversion/gml_runtime_parts/segments/`. Add Python coverage and a `*_godot.py` test when behavior depends on Godot.
- **GameMaker resource conversion:** add parse-only models and fixtures before renderer/writer behavior. Keep generated paths deterministic and route compatibility gaps through diagnostics.
- **Object events:** update the event mapping registry and add scheduler/runtime coverage for ordering-sensitive behavior.
- **Conversion orchestration:** use `conversion_plan.py` and `conversion_context.py`; do not add a parallel execution path around the plan.
- **Documentation:** update the canonical repository source. Wiki pages are reviewed under `docs/wiki/` and published after merge.

The deeper architecture references are:

- [Conversion architecture](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/conversion_architecture.md)
- [Runtime segment ownership](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/gml_runtime_parts/README.md)
- [Generated runtime managers](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/runtime_managers.md)
- [Godot architecture policy](https://github.com/Infiland/GM2Godot/blob/main/src/conversion/godot_architecture_policy.md)

## Fixtures

A useful fixture is the smallest legal or intentionally malformed GameMaker project that proves one behavior. Include the `.yyp`, required `.yy` resources, and a short coverage note. Avoid adding third-party projects without a reviewed license and immutable source reference.

Use the repository's fixture manifests and existing test families as the pattern:

- focused parser/converter fixtures under `tests/fixtures/`;
- deterministic golden snapshots for generated output;
- exact Godot 4.7.1 tests for parse/load/runtime behavior; and
- pinned external-project CI only when the source revision, license, runtime cost, and failure artifacts are bounded.

## Required checks

For Python or generated-code logic changes:

```bash
./venv/bin/pyright --warnings
./venv/bin/ruff check .
./venv/bin/python -m unittest
```

Fix every Pyright error and warning in changed code. Run the relevant focused test while iterating; use the full suite for broad behavior changes. For Godot-dependent changes, run with the exact binary:

```bash
GODOT_BIN=/path/to/Godot-4.7.1 \
  ./venv/bin/python -m unittest discover -s tests -p 'test_*_godot.py'
```

Documentation-only changes do not require Pyright or the Python suite unless the change also touches tests/code or verification was explicitly requested. Link and page-source checks should still pass.

## Pull requests and issues

Keep each branch and pull request focused on one issue. Describe the behavior, validation evidence, user-visible limitations, and any follow-up that was deliberately left out. Do not make a compatibility claim solely because conversion completed; include diagnostics and exact-Godot evidence where relevant.

Use the issue templates for unsupported APIs, invalid generated GDScript, resource mismatches, and fixture contributions. Minimal source projects and complete version details make regressions much easier to reproduce.

## Documentation changes

When changing a version-sensitive page:

1. Update its **Applies to** and **Last reviewed** banner.
2. Prefer links to generated reports or canonical source over copied compatibility totals.
3. Update `_Sidebar.md` when adding or renaming a page.
4. Include Wiki review in the release checklist.
5. After the main-repository change merges, publish the exact merged `docs/wiki/` files to the Wiki and verify the live links.

See [Release and Wiki Maintenance](Maintainer-Release-and-Wiki) for the publication procedure.
