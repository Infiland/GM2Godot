# Contributing to GM2Godot

Thank you for your interest in contributing to GM2Godot! We aim to make GameMaker to Godot conversion as smooth as possible, and your contributions help make this goal a reality.

## Getting Started

1. **Fork the Repository**
   - Click the "Fork" button at the top right of the [GM2Godot repository](https://github.com/Infiland/GM2Godot)
   - Clone your fork locally:
     ```bash
     git clone https://github.com/YOUR_USERNAME/GM2Godot
     cd GM2Godot
     ```

2. **Set Up Development Environment**
   - Use the reviewed native baseline for your host. Other Python patch versions and architectures are not the reproducible CI/release baseline.

     | Host | Python | Constraint |
     | --- | --- | --- |
     | Linux x64 | CPython 3.12.13 | `constraints/requirements-linux-py312.lock` |
     | macOS arm64 | CPython 3.12.10 | `constraints/requirements-macos-py312.lock` |
     | Windows x64 | CPython 3.12.10 | `constraints/requirements-windows-py312.lock` |

   - Run the bootstrap preflight with that exact interpreter before creating the environment; `venv` invokes `ensurepip`, so policy validation must happen first. Then activate the environment and confirm `python --version` reports the required patch version.
   - Bootstrap the pinned pip and install the runtime graph under the matching constraint. For Linux x64:
     ```bash
     python3.12 scripts/verify_dependency_bootstrap.py \
       --source requirements-bootstrap.txt \
       --policy stable \
       --constraint constraints/requirements-linux-py312.lock \
       --output "${TMPDIR:-/tmp}/gm2godot-bootstrap.json"
     python3.12 -m venv venv
     source venv/bin/activate
     python --version  # Python 3.12.13
     export PIP_CONFIG_FILE=/dev/null
     python -m pip --isolated --disable-pip-version-check --no-input install \
       --no-cache-dir --only-binary=:all: \
       --constraint constraints/requirements-linux-py312.lock pip
     python -m pip --isolated --disable-pip-version-check --no-input install \
       --no-cache-dir --only-binary=:all: \
       --constraint constraints/requirements-linux-py312.lock -r requirements.txt
     ```
   - On macOS arm64, use CPython 3.12.10 and substitute `constraints/requirements-macos-py312.lock` in the preflight and every install command below. Keep `PIP_CONFIG_FILE=/dev/null`.
   - On Windows x64, use CPython 3.12.10, substitute `constraints/requirements-windows-py312.lock` in the preflight and every install command below, and set `$env:PIP_CONFIG_FILE = "nul"` in PowerShell before the isolated install commands.
   - The platform null device disables config-file discovery, while `--isolated` ignores user configuration and environment settings that could change resolution.
   - Install the reviewed bootstrap generator and development tools under the same constraint when changing Python code. For Linux x64:
     ```bash
     python -m pip --isolated --disable-pip-version-check --no-input install \
       --no-cache-dir --only-binary=:all: \
       --constraint constraints/requirements-linux-py312.lock \
       -r requirements-bootstrap.txt -r requirements-tooling.txt
     ```

### Refreshing dependency constraints

`requirements-bootstrap.txt` is the only reviewed source for the exact pip/pip-tools compatibility pair. `requirements.txt` and `requirements-tooling.txt` declare the other runtime and development roots; `requirements-lock.in` includes those three authored files as the single compile input for their combined graph. Generated native locks deliberately use `.lock` rather than a Dependabot-recognized requirements suffix. Constraint changes must be intentional and reviewed with the input change that caused them.

Use the native [dependency-lock workflow](.github/workflows/dependency-locks.yml), which runs the exact pair declared in `requirements-bootstrap.txt` on the Linux x64, macOS arm64, and Windows x64 baselines. Pull-request and push runs always use `refresh=locked`: each committed lock preference-seeds a candidate without requesting upgrades. Manual `workflow_dispatch` runs expose these policies:

| Selection | Behavior |
| --- | --- |
| `refresh=locked` | Recreate the preference-seeded graph without requesting an upgrade. |
| `refresh=all` | Request upgrades for the complete graph. |
| `refresh=package` | Request an upgrade only for the normalized distribution named by `refresh_package`. |

Leave `refresh_package` empty for `refresh=locked` and `refresh=all`. It is required for `refresh=package` and must already be normalized, such as `pyside6`. `pip` and `pip-tools` are rejected in package-refresh mode because their reviewed pair is changed only through `requirements-bootstrap.txt`.

Every native job first accepts only a stable source/lock pair or one explicit source transition where all three committed locks agree on the same old pair. The old committed generator compiles a bootstrap-only probe; the proposed pair must install, pass environment verification and `pip check`, and reproduce its parsed bootstrap graph before full lock generation begins. The candidate then regenerates a self-hosted complete constraint, performs two clean complete-graph installs, and compares their normalized receipts. Bootstrap probe, candidate, self-hosted output, receipts, dependency snapshot, and manifest are uploaded before the final gates run. When an intentional refresh changes pins, the committed-equality gate is expected to fail: review all three native artifacts, commit the approved constraints, and rerun until `locked` generation is clean.

For a pip-family security proposal, use the source-only Dependabot pull request as a review starting point; do not merge it or copy generated locks from the bot. Continue on a maintainer branch, run the native workflow, review the Linux, macOS, and Windows probe/candidate/self-host/clean-install evidence, and commit all three approved `.lock` artifacts. Security proposals for other direct dependencies may update their own authored requirements file, but they follow the same native artifact review and never supply generated locks. If the full candidate differs from the proposed generator's self-hosted result, commit the uploaded self-hosted lock first and rerun so the new committed generator proves stable output. No dependency workflow auto-merges. Do not compile a Linux or Windows constraint on macOS, or any other cross-platform combination: environment markers and native transitive dependencies are part of the graph.

Treat `pip` and `pip-tools` as one compatibility unit: review the two exact source pins together and commit all three native locks in the same maintainer pull request. Live consumers derive the expected pip version from that source after a fail-closed preflight rather than duplicating numeric literals. Successful main-branch native runs submit the three verified dependency graphs under stable platform correlators so transitive Dependabot alerts remain available even though generated `.lock` files are not editable manifests. Current install and compile commands reject source distributions with `--only-binary=:all:` and disable pip's cache with `--no-cache-dir`, so pip 26.2's isolated-build and index-cache changes do not alter the locked graph. If a future path permits a source distribution, it must also pass an explicit reviewed `--build-constraint` for the isolated build environment; do not assume the runtime constraint governs build dependencies under pip 26.2 or later.

Compatibility work continues to target GameMaker LTS 2026 source projects and exact Godot 4.7.2 validation.

## Development Guidelines

### Code Style
- Follow PEP 8 guidelines for Python code
- Use meaningful variable and function names
- Add comments for complex logic
- Keep functions focused and concise
- Use type hints where appropriate
- Keep linting and type checking clean for code changes. Run `./venv/bin/pyright --warnings` before submitting Python or generated-code logic changes and fix every reported error or warning.
- Run `ruff check .` before submitting Python code. CI enforces Ruff's `E9` fatal-error checks and the complete Pyflakes (`F`) rule family. Do not disable `F` or individual `F`-numbered rules globally or per file. Broader style rules should be introduced separately from feature work.

### Shrinking maintainability debt (R02 / #795)

Run the same ratchet as Code Health for uncommitted changes:

```bash
./venv/bin/python scripts/check_maintainability.py --baseline maintainability-baseline.json --base-ref HEAD
```

For committed branch changes, use `--base-ref "$(git merge-base origin/main HEAD)"`.
CI supplies the actual PR merge-base or previous push SHA. A baseline increase
cannot be approved by regenerating the candidate file: the checker also reads
the immutable parent baseline. The one initial bootstrap is main commit
`38b364855f06e971d2676b921fd300e1f40f076a`, measured from its Git archive;
all later parents must contain the baseline. R01's facade cutover is not in
that tree. Its later integration must remove the debt it eliminates. The
original campaign's post-R01 manifest/runner integration remains dependent on
those artifacts becoming available; this gate runs directly in Code Health.

`maintainability-baseline.json` records exact exceptions by path and qualified
symbol, separating application, tooling, and tests. `scripts/maintainability_metrics.py`
owns measurement thresholds, module classifications, and lint rules; the JSON
records that policy to reject accidental changes. Every tracked Python input
(including tracked ignored files) and nonignored untracked Python input is
measured. Unknown classifications fail. Existing E9/F checks remain mandatory;
normal Ruff also enforces the campaign's coarse C90 ceiling of 122. The ratchet
independently measures C901 above 15, function/module length, nesting,
parameters, duplicate symbols, pending I001/B/E4/E7/E9 findings, exact suppression
comments (including directives after explanatory comment prefixes), and static/eager import cycles. Declarative/mixed modules are labeled,
not exempted. Ruff runs at the requirements pin with isolated configuration and
ignores neither files nor `noqa` findings. Source traversal and JSON are sorted;
paths use `/`, symbols omit line numbers, and the AST grammar is Python 3.12.

Schema v2 also records formatting-independent size: statements, collection
entries, call arguments, expression operations, comprehension clauses, and
multiline string/bytes payload breaks count as structural units under the
existing function/module budgets. These conservative units differ from physical
lines; they measure packed expressions and payloads in new or moved destinations
as well as existing owners. Each line-debt entry keeps its
actual physical lines, structural units, and location-free AST digest as size
evidence. When formatting or comment removal shortens an owner without reducing
its structure, its previous effective line allowance remains; the new physical
size is still recorded accurately. For example, removing one comment from an
890-line module records 889 physical lines while retaining its 890-line debt.
The retained allowance survives subsequent commits, including packing below a
threshold. A structural reduction lowers its effective line debt proportionally:
the larger of actual lines and the prior effective debt multiplied by the ratio
of new to prior structural units, rounded up. Removing one statement cannot
retire a large packed function's entire allowance. Structural growth also raises
that effective debt, so restoring removed work fails instead of resetting the
comparison. Zero-structure owners retain their allowance; deleting an owner
removes it. The independent Git parent supplies both allowances and evidence.

After reducing or deleting debt, validation intentionally fails on stale
entries. Deliberately record the reduction, then recheck:

```bash
./venv/bin/python scripts/check_maintainability.py --baseline maintainability-baseline.json --base-ref HEAD --update
./venv/bin/python scripts/check_maintainability.py --baseline maintainability-baseline.json --base-ref HEAD
./venv/bin/python -m unittest tests.test_maintainability_policy tests.test_maintainability_metrics -v
```

Use the same parent reference for both commands. `--update` only lowers or
removes allowances; it cannot introduce or rename debt, increase an accepted
metric, or restore a removed allowance. Include the updated JSON with the code
change. Reaching a threshold through structural reduction removes the exception;
cosmetic packing alone does not. Exit 0 means
exact agreement, 1 identifies violated metric limits or stale entries, and 2
means invalid configuration or unavailable measurement prerequisites. Review
changes to the measurement policy separately; dependency upgrades must also
review any change to the pinned Ruff measurement semantics.

Import graphs are syntax-based and never import application code. They include
relative/absolute imports, package initializers, re-exports, imports in functions
and typing guards, and literal `importlib.import_module`/`__import__` calls with
explicit aliases. Only function/lambda bodies and recognized typing guards are
deferred from the eager graph; other conditional imports are conservative.
Computed import names and arbitrary alias reassignment require code review.
Each directed elementary cycle is an exact exception, so adding a cycle inside
an existing component also fails. This gate prevents debt growth; it does not
perform the refactors assigned to later campaign rows.

### UI Development
- Maintain consistency with the existing dark theme
- Follow the existing panel, dialog, icon, and theme patterns under `src/gui/`
- Keep user-facing controls in the owning `src/gui/panels/` or `src/gui/dialogs/` module
- Test UI changes at different window sizes

### Asset Conversion
When adding new asset conversion features:
1. Create a new converter class in `src/conversion/`
2. Follow the existing converter pattern
3. Add appropriate error handling
4. Include progress reporting
5. Add the new feature to the settings UI

### Conversion Architecture
New conversion work should fit the current staged architecture:
- Add orchestration metadata to `src/conversion/conversion_plan.py` when a converter needs a stable execution slot or dependency.
- Use `src/conversion/conversion_context.py` for shared conversion-run state instead of adding parallel callback/path arguments in the orchestrator.
- Keep parse-only GameMaker metadata in `src/conversion/resource_models.py` or a resource-specific model helper so parsing can be tested without writing Godot files.
- Keep generated output deterministic; update golden or manifest tests only when output changes intentionally.

### GML API Support
When adding or improving a GML API:
- Update the manifest entry in `src/conversion/gml_transpiler_parts/gml_api_manifest.py`.
- Add or update dispatch metadata in `gml_function_dispatch.py` and keep asset-argument rules in `asset_lowering.py`.
- Implement runtime behavior in the owning `src/conversion/gml_runtime_parts/segments/*.gd` segment and declare ownership in `gml_runtime_parts/manifest.py`.
- Add focused Python and, when behavior depends on Godot, `*_godot.py` coverage.
- Update compatibility docs or reports when support status changes.

### Runtime Segments
When adding a runtime segment or moving runtime helpers:
- Declare the segment, dependencies, description, and tests in `src/conversion/gml_runtime_parts/manifest.py`.
- Keep public `gml_*` helper names unique; `tests/test_gml_runtime_segments.py` validates duplicate symbols and API-to-segment ownership.
- Prefer segment-local state buckets or generated managers for mutable runtime state.
- Document user-visible semantic differences in `src/conversion/runtime_managers.md` or `src/conversion/godot_architecture_policy.md`.

### Resource Converters
When adding a converter for a GameMaker resource type:
- Add parse fixtures under `tests/fixtures/part2/` when possible.
- Add parse-only model coverage before renderer/writer coverage.
- Route warnings through diagnostics where they can become reports.
- Add converter tests that check deterministic paths and generated Godot resources.

### Event Mappings
When adding object event support:
- Add event metadata in `src/conversion/events/mappings/` and registry coverage in `tests/conversion/events/`.
- Document event-order differences when GameMaker and Godot callback order cannot match exactly.
- Add runtime scheduler tests for events that depend on frame ordering, input, alarms, async queues, draw phases, or collisions.

### Fixtures
Fixture contributions should include:
- A minimal `.yyp` plus committed `.yy` resources.
- A short note in `tests/fixtures/part2/fixtures.json` or `corpus.json` explaining the coverage target.
- Tests that prove conversion continues when the fixture is malformed, unsupported, or expected to warn.

## Making Changes

1. **Create a Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Your Changes**
   - Write clean, documented code
   - Follow the project's code style
   - Test your changes thoroughly

3. **Commit Your Changes**
   - Use clear, descriptive commit messages
   - Keep commits focused and atomic
   - Example format:
     ```bash
     git commit -m "feat: Add support for converting GameMaker sequences"
     ```

4. **Push to Your Fork**
   ```bash
   git push origin feature/your-feature-name
   ```

5. **Create a Pull Request**
   - Go to the [GM2Godot repository](https://github.com/Infiland/GM2Godot)
   - Click "New Pull Request"
   - Select your fork and branch
   - Describe the focused scope and validation evidence
   - Add screenshots for UI changes

## Testing

### Python line and branch coverage

The required Linux `Tests` job runs the full unittest discovery once under pinned
coverage.py branch instrumentation. The measured production inventory is
`main.py`, every Python file under `src/`, and every maintained Python file under
`scripts/`. The explicit source inventory excludes tests and fixtures, virtual
environments, build/distribution/release output, packaging-only hooks, and
generated non-Python artifacts. `.coveragerc` adds no project-specific
`exclude_lines` or `exclude_also` patterns.

Run the same measurement, human-readable summary, machine-readable reports, and
floor gate locally from the repository root:

```bash
./venv/bin/python -m coverage erase
./venv/bin/python -m coverage run -m unittest discover tests/ -v
mkdir -p coverage-reports
./venv/bin/python -m coverage report
./venv/bin/python -m coverage json
./venv/bin/python -m coverage xml
./venv/bin/python scripts/check_coverage.py \
  --report coverage-reports/coverage.json
```

`coverage-policy.json` defines line coverage as covered executable statements
divided by executable statements and branch coverage as covered branch
destinations divided by all branch destinations. The gate checks those two
percentages independently; it does not use coverage.py's combined `Cover`
column. Separate scopes protect converter orchestration, manifests/diagnostics,
project parsing, and the complete GML transpiler package from being hidden by
unrelated utility coverage.

To raise a floor intentionally, measure a clean `main` checkout with the exact
command above, review the JSON counts and missing-line/branch summary, and update
the corresponding baseline counts and floor in `coverage-policy.json` in the
same test-focused pull request. Floors are the measured percentages truncated
to two decimal places so the committed threshold never rounds above its own
baseline. Update the workflow-policy assertions at the same time. Do not lower a
floor to accommodate untested production paths.

The configuration follows the official coverage.py
[branch](https://coverage.readthedocs.io/en/latest/branch.html),
[configuration](https://coverage.readthedocs.io/en/latest/config.html),
[JSON](https://coverage.readthedocs.io/en/latest/commands/cmd_json.html), and
[XML](https://coverage.readthedocs.io/en/latest/commands/cmd_xml.html)
documentation and Python's
[unittest discovery](https://docs.python.org/3.12/library/unittest.html#test-discovery)
contract. CI retains both machine-readable reports using GitHub Actions
[workflow artifacts](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-what-your-workflow-does/storing-and-sharing-data-from-a-workflow),
including when a floor fails.

Before submitting a PR:
- For Python or generated-code logic changes, run `./venv/bin/pyright --warnings` and fix all lint/type-check diagnostics
- For code behavior changes, run the relevant tests; for broad code changes, run `./venv/bin/python -m unittest`
- For documentation-only changes, do not run Pyright or tests unless explicitly requested
- Test your changes with both GameMaker and Godot projects
- Verify the UI works at different resolutions
- Check that existing features still work
- Test on different platforms if possible

## Maintainer Release Checklist

For every versioned pull request:

- Update `src/version.py`, `CHANGELOG.md`, the current source version in `README.md`, version examples in issue templates, and `tests/test_version.py`.
- Review the version banners and user workflows under `docs/wiki/`; include any required Wiki changes in the same reviewable branch.
- Confirm all required pull-request checks pass, including exact Godot 4.7.2 smoke and GameMaker LTS 2026 conversion gates.
- After merge, confirm the new tag points to the intended `main` commit and that the Linux, macOS zip/DMG, and Windows release assets are present and non-empty.
- If Wiki sources changed, reference the documentation issue without an auto-closing keyword, publish the exact merged `docs/wiki/` pages, and verify live navigation before closing the issue.

The full Wiki publication and rollback procedure is in [`docs/WIKI_MAINTENANCE.md`](docs/WIKI_MAINTENANCE.md).

## Areas for Contribution

We particularly welcome contributions in these areas:
- GML to GDScript conversion
- Additional asset type support
- UI/UX improvements
- Documentation improvements
- Bug fixes
- Performance optimizations

## Localization

To localize GM2Godot into another language, copy `Languages/template/template.json` to the `Languages/` directory and rename the copy to the language's ISO 639-3 code (for example, `eng.json` for English). Refer to [Wikipedia](https://en.wikipedia.org/wiki/List_of_ISO_639-3_codes) for the code list.

The template's embedded `README` field explains the required keys ([GitHub copy](https://raw.githubusercontent.com/Infiland/GM2Godot/refs/heads/main/Languages/template/template.json)).

## Questions or Issues?

- Check existing [issues](https://github.com/Infiland/GM2Godot/issues)
- Create a new issue for bugs or feature requests

## Code of Conduct

- Be respectful and inclusive
- Help others learn and grow
- Focus on constructive feedback
- Follow the project's [Code of Conduct](CODE_OF_CONDUCT.md)

## License

By contributing to GM2Godot, you agree that your contributions will be licensed under the project's [Apache License 2.0](LICENSE).
