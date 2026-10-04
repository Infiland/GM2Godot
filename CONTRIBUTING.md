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
     | macOS x64 (Intel) | CPython 3.12.10 | `constraints/requirements-macos-py312.lock` |
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
   - On macOS arm64 or x64 (Intel), use CPython 3.12.10 and substitute `constraints/requirements-macos-py312.lock` in the preflight and every install command below. Keep `PIP_CONFIG_FILE=/dev/null`.
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

Use the native [dependency-lock workflow](.github/workflows/dependency-locks.yml), which runs the exact pair declared in `requirements-bootstrap.txt` on the Linux x64, macOS arm64, macOS x64 (Intel), and Windows x64 baselines. Pull-request and push runs always use `refresh=locked`: each committed lock preference-seeds a candidate without requesting upgrades. Manual `workflow_dispatch` runs expose these policies:

| Selection | Behavior |
| --- | --- |
| `refresh=locked` | Recreate the preference-seeded graph without requesting an upgrade. |
| `refresh=all` | Request upgrades for the complete graph. |
| `refresh=package` | Request an upgrade only for the normalized distribution named by `refresh_package`. |

Leave `refresh_package` empty for `refresh=locked` and `refresh=all`. It is required for `refresh=package` and must already be normalized, such as `pyside6`. `pip` and `pip-tools` are rejected in package-refresh mode because their reviewed pair is changed only through `requirements-bootstrap.txt`.

Every native job first accepts only a stable source/lock pair or one explicit source transition where all three committed locks agree on the same old pair. The old committed generator compiles a bootstrap-only probe; the proposed pair must install, pass environment verification and `pip check`, and reproduce its parsed bootstrap graph before full lock generation begins. The candidate then regenerates a self-hosted complete constraint, performs two clean complete-graph installs, and compares their normalized receipts. Bootstrap probe, candidate, self-hosted output, receipts, dependency snapshot, and manifest are uploaded before the final gates run. When an intentional refresh changes pins, the committed-equality gate is expected to fail: review all four native artifacts, commit the three approved version constraints, and rerun until `locked` generation is clean.

For a pip-family security proposal, use the source-only Dependabot pull request as a review starting point; do not merge it or copy generated locks from the bot. Continue on a maintainer branch, run the native workflow, review the Linux, both Mac architectures, and Windows probe/candidate/self-host/clean-install evidence, and commit all three approved `.lock` artifacts. Security proposals for other direct dependencies may update their own authored requirements file, but they follow the same native artifact review and never supply generated locks. If the full candidate differs from the proposed generator's self-hosted result, commit the uploaded self-hosted lock first and rerun so the new committed generator proves stable output. No dependency workflow auto-merges. Do not compile a Linux or Windows constraint on macOS, or any other cross-platform combination: environment markers and native transitive dependencies are part of the graph.

Treat `pip` and `pip-tools` as one compatibility unit: review the two exact source pins together and commit all three native locks in the same maintainer pull request. Live consumers derive the expected pip version from that source after a fail-closed preflight rather than duplicating numeric literals. Successful main-branch native runs submit the four verified dependency graphs under stable platform correlators so transitive Dependabot alerts remain available even though generated `.lock` files are not editable manifests. Current install and compile commands reject source distributions with `--only-binary=:all:` and disable pip's cache with `--no-cache-dir`, so pip 26.2's isolated-build and index-cache changes do not alter the locked graph. If a future path permits a source distribution, it must also pass an explicit reviewed `--build-constraint` for the isolated build environment; do not assume the runtime constraint governs build dependencies under pip 26.2 or later.

Compatibility work continues to target GameMaker LTS 2026 source projects and exact Godot 4.7.2 validation.


### Native wheel proposals

The [native wheel workflow](.github/workflows/native-wheel-proposals.yml) proves Linux x64, macOS arm64, macOS x64 (Intel), and Windows x64 separately. Native discovery proved that both Mac candidate and self-hosted version-lock bytes match `constraints/requirements-macos-py312.lock`. The repository therefore retains three unique version locks and four architecture-specific wheel hash locks:

| Host | Complete wheel hash requirements |
| --- | --- |
| Linux x64 | `constraints/requirements-linux-x64-py312.wheels.lock` |
| macOS arm64 | `constraints/requirements-macos-arm64-py312.wheels.lock` |
| macOS x64 (Intel) | `constraints/requirements-macos-x64-py312.wheels.lock` |
| Windows x64 | `constraints/requirements-windows-x64-py312.wheels.lock` |

The fixed `require-committed` phase runs on pull requests to main and pushes to main or `codex/native-intel-wheel-locks`. Each native job observes two independent wheel downloads, reproduces the candidate and self-hosted version graph, and performs two clean offline complete-graph installs with equal normalized receipts. The aggregate checker reads the four original archives from the exact source commit, run, and attempt without extracting or executing their contents; it requires the observed hash requirements to match their committed companions.

For a complete hash-enforced development install on Intel macOS, first use the exact CPython 3.12.10 interpreter, bootstrap preflight, environment creation, and constrained pip setup above. Then use a fresh private wheel directory:

```bash
native_wheelhouse="$(mktemp -d)"
python -m pip --isolated --disable-pip-version-check --no-input download \
  --no-cache-dir --only-binary=:all: --require-hashes \
  -r constraints/requirements-macos-x64-py312.wheels.lock \
  --dest "$native_wheelhouse"
python -m pip --isolated --disable-pip-version-check --no-input install \
  --no-cache-dir --only-binary=:all: --require-hashes --force-reinstall --no-index \
  --find-links "$native_wheelhouse" \
  -r constraints/requirements-macos-x64-py312.wheels.lock
python -m pip check
```

Use the matching companion from the table for another host, with its exact interpreter and version-lock preflight. These companions include the complete runtime, bootstrap, and development graph. Ordinary runtime source installs and existing Tests/Release installs continue using version constraints. A recorded wheel hash does not authenticate those version-only installs. Refresh version graphs and their wheel companions together through native evidence review before changing pins; neither dependency workflow auto-merges. Published releases starting with 0.8.17 provide separate native arm64 and x86_64 Mac ZIP/DMG pairs. Select the download matching the host architecture; the wheel hash locks verify source dependency installs separately.

## Development Guidelines

### Code Style
- Follow PEP 8 guidelines for Python code
- Use meaningful variable and function names
- Add comments for complex logic
- Keep functions focused and concise
- Use type hints where appropriate
- Keep linting and type checking clean for code changes. Run `./venv/bin/pyright --warnings` before submitting Python or generated-code logic changes and fix every reported error or warning.
- Run `./venv/bin/python -m ruff check .` before submitting Python code. CI enforces Ruff's complete `E7` and Pyflakes (`F`) rule families, plus `E9` fatal-error checks. `E7` includes the `E731` assigned-lambda and `E741` ambiguous-variable rules. Do not disable `F` or individual `F`-numbered rules globally or per file. Ruff also enforces import placement through the `E4` rule family. Keep repository-path setup in explicit conditional guards and preserve discovery before dependent imports; do not hide placement failures with new `E4` ignores. Ruff also enforces import sorting through the `I` rule family. Keep aliased imports together with `combine-as-imports = true`, including deliberate local cycle gateways. Preserve bootstrap and environment setup before dependent imports; keep intentional local imports local. Do not add `I` ignores or sorting skips. The local configuration excludes generated `build/`, `dist/`, and `release/` output and the local `venv/` environment; CI also checks every tracked lint input without suppression or exclusion bypasses. Ruff also enforces the focused stable bug-risk selectors `B002`, `B003`, `B004`, `B005`, `B006`, `B008`, `B011`, `B012`, `B014`, `B015`, `B016`, `B017`, `B018`, `B019`, `B020`, `B021`, `B022`, `B025`, `B029`, `B030`, `B031`, `B032`, `B033`, `B035`, `B039`, `B905`. This focused B gate does not enable the entire B family. B009/B010 attribute style, B023 callback lifetimes and B904 exception causes remain separate source reviews. Function complexity has a separate required gate: `./venv/bin/python -m scripts.check_complexity`.

Run Python tests from the repository root with `./venv/bin/python -m unittest` or module-qualified unittest selectors. The event-mapping test package uses normal package imports and does not add the repository to `sys.path`.

Godot smoke tests can use `tests.godot_test_support` for live binary discovery, UTF-8 fixture writes, and the standard headless scene invocation. The shared runner returns the process result and propagates timeouts; each test owns its assertions and skip policy. Tests requiring different working directories, environments, launch flags or lifecycle handling keep those policies locally.

```bash
./venv/bin/python -m unittest discover -s tests/conversion/events -t . -v
./venv/bin/python -m unittest tests.conversion.events.test_create_event
```

Direct file execution such as `./venv/bin/python tests/conversion/events/test_create_event.py` is unsupported for this package. Use the corresponding module-qualified command. The standalone `tests/test_macos_gui_artifact_verifier.py` retains its existing native Python `-I`, `--native-architecture`, and `--output` invocation and isolated file-loading contract; it is outside this bootstrap refactor and remains covered by the same lint gate.

Use the same explicit tracked-input gate as CI when reviewing exclusions and suppressions:

```bash
git ls-files -z -- '*.py' '*.pyi' '*.pyw' '*.ipynb' '*.md' |
  xargs -0 -- ./venv/bin/python -m ruff check --isolated --target-version py312 --line-length 120 \
    --select E4,E7,E9,F,I,B002,B003,B004,B005,B006,B008,B011,B012,B014,B015,B016,B017,B018,B019,B020,B021,B022,B025,B029,B030,B031,B032,B033,B035,B039,B905 --ignore-noqa --no-respect-gitignore --no-force-exclude --config lint.isort.combine-as-imports=true --
```

This command checks tracked Python source regardless of local ignores or exclusions. Ruff does not lint Python code blocks in the passed Markdown documents.

Run `./venv/bin/python -m scripts.check_complexity` as a separate required gate.
It checks every tracked lint input with isolated Ruff `C90`, ignores `noqa`,
and fixes the threshold at 15. `complexity-exceptions.json` contains only
individually reviewed repository-path and qualified-function ceilings, with a
measured score, responsibility-specific reason, removal action, and link to a real
issue or tracked Markdown removal plan. New or increased debt fails. Improvements
must tighten both measured score and ceiling; deleted, renamed or simplified
functions require removing stale entries. Ordinary Ruff does not read these
per-function ceilings, so its clean result does not replace this command.
Do not add blanket `C901` suppressions or raise the threshold.

Local removal-plan links must name readable UTF-8 Markdown at their canonical
tracked repository path. A supplied fragment must match an existing standalone
`<a id="name"></a>` or `<a name="name"></a>` anchor, or a simple ATX heading of
plain words (letters/numbers/underscores/hyphens separated by spaces or tabs).
Heading fragments use lowercase words joined by hyphens; repeated headings add
`-1`, `-2`, and so on. Explicit anchor names and supplied fragments match
literally and are case-sensitive. Fenced/indented code and HTML comment lines do
not define anchors. Use an explicit standalone anchor for headings with inline
markup or punctuation; this gate is not a general Markdown renderer. HTTPS
tracking links remain source-review obligations and are not fetched by the gate.



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

## Deep extension development

See [Deep conversion](docs/DEEP_CONVERSION.md) for the client/engine boundary, local setup and pinned release workflow. Track implementation and native/live acceptance evidence in [issue #894](https://github.com/Infiland/GM2Godot/issues/894).
