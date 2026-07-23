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
     | Linux x64 | CPython 3.12.13 | `constraints/requirements-linux-py312.txt` |
     | macOS arm64 | CPython 3.12.10 | `constraints/requirements-macos-py312.txt` |
     | Windows x64 | CPython 3.12.10 | `constraints/requirements-windows-py312.txt` |

   - Create and activate a virtual environment with that exact interpreter. Confirm `python --version` reports the required patch version.
   - Bootstrap the pinned pip and install the runtime graph under the matching constraint. For Linux x64:
     ```bash
     python3.12 -m venv venv
     source venv/bin/activate
     python --version  # Python 3.12.13
     export PIP_CONFIG_FILE=/dev/null
     python -m pip --isolated --disable-pip-version-check --no-input install \
       --no-cache-dir --only-binary=:all: \
       --constraint constraints/requirements-linux-py312.txt pip==26.1.2
     python -m pip --isolated --disable-pip-version-check --no-input install \
       --no-cache-dir --only-binary=:all: \
       --constraint constraints/requirements-linux-py312.txt -r requirements.txt
     ```
   - On macOS arm64, use CPython 3.12.10 and substitute `constraints/requirements-macos-py312.txt` in both install commands. Keep `PIP_CONFIG_FILE=/dev/null`.
   - On Windows x64, use CPython 3.12.10, substitute `constraints/requirements-windows-py312.txt`, and set `$env:PIP_CONFIG_FILE = "nul"` in PowerShell before the same isolated install commands.
   - The platform null device disables config-file discovery, while `--isolated` ignores user configuration and environment settings that could change resolution.
   - Install the pinned development tools from `requirements-tooling.txt` under the same constraint when changing Python code. For Linux x64:
     ```bash
     python -m pip --isolated --disable-pip-version-check --no-input install \
       --no-cache-dir --only-binary=:all: \
       --constraint constraints/requirements-linux-py312.txt -r requirements-tooling.txt
     ```

### Refreshing dependency constraints

`requirements.txt` and `requirements-tooling.txt` declare the reviewed direct dependencies; `requirements-lock.in` is the single compile input for their combined graph. Constraint changes must be intentional and reviewed with the input change that caused them.

Use the native [dependency-lock workflow](.github/workflows/dependency-locks.yml), which runs the committed `pip-tools` pin—currently `pip-tools==7.6.0`—on the exact Linux x64, macOS arm64, and Windows x64 baselines. Pull-request and push runs always use `refresh=locked`: each committed constraint preference-seeds a candidate without requesting upgrades. Manual `workflow_dispatch` runs expose these policies:

| Selection | Behavior |
| --- | --- |
| `refresh=locked` | Recreate the preference-seeded graph without requesting an upgrade. |
| `refresh=all` | Request upgrades for the complete graph. |
| `refresh=package` | Request an upgrade only for the normalized distribution named by `refresh_package`. |

Leave `refresh_package` empty for `refresh=locked` and `refresh=all`. It is required for `refresh=package` and must already be normalized, such as `pip-tools` or `pyside6`.

Every native job uses the candidate's own pip and pip-tools pins to regenerate a self-hosted constraint, then performs two clean complete-graph installs and compares their normalized receipts. Candidate, self-hosted output, receipts, and a manifest are uploaded before the final gates run. When an intentional refresh changes pins, the committed-equality gate is expected to fail: review all three native artifacts, commit the approved constraints, and rerun until `locked` generation is clean.

If pip or pip-tools is upgraded, the current generator's candidate can differ from the candidate generator's self-hosted result. Review and commit the uploaded self-hosted constraint, then rerun so the new committed generator proves its own stable output. Do not compile a Linux or Windows constraint on macOS, or any other cross-platform combination: environment markers and native transitive dependencies are part of the graph.

Compatibility work continues to target GameMaker LTS 2026 source projects and exact Godot 4.7.1 validation.

## Development Guidelines

### Code Style
- Follow PEP 8 guidelines for Python code
- Use meaningful variable and function names
- Add comments for complex logic
- Keep functions focused and concise
- Use type hints where appropriate
- Keep linting and type checking clean for code changes. Run `./venv/bin/pyright --warnings` before submitting Python or generated-code logic changes and fix every reported error or warning.
- Run `ruff check .` before submitting Python code. The project currently enables fatal/static Ruff checks in CI; broader style rules should be introduced separately from feature work.

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
- Confirm all required pull-request checks pass, including exact Godot 4.7.1 smoke and the current GameMaker LTS conversion gates.
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
