# Contributing and Testing

> **Applies to:** GM2Godot 0.7.30 · GameMaker LTS 2026 · Godot 4.7.1
>
> **Last reviewed:** 2026-07-19

This page is the short contributor route map. The repository's [CONTRIBUTING.md](https://github.com/Infiland/GM2Godot/blob/main/CONTRIBUTING.md) and `AGENTS.md` remain authoritative for development rules.

## Set up a development checkout

Use the matching procedure on [Installation](Installation). The reviewed dependency baselines are Linux x64 with CPython 3.12.13, macOS arm64 with CPython 3.12.10, and Windows x64 with CPython 3.12.10. Each has a complete native constraint under `constraints/`.

For example, the Linux x64 baseline is:

```bash
git clone https://github.com/YOUR_USERNAME/GM2Godot.git
cd GM2Godot
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
python -m pip --isolated --disable-pip-version-check --no-input install \
  --no-cache-dir --only-binary=:all: \
  --constraint constraints/requirements-linux-py312.txt -r requirements-tooling.txt
```

On macOS arm64, use CPython 3.12.10 and `constraints/requirements-macos-py312.txt`, retaining `PIP_CONFIG_FILE=/dev/null`. On Windows x64, use CPython 3.12.10 and `constraints/requirements-windows-py312.txt`, and set `$env:PIP_CONFIG_FILE = "nul"` in PowerShell. The null config file and `--isolated` prevent local pip settings from changing the reviewed install behavior. The installation page has complete commands for both hosts. Install Godot 4.7.1 and set `GODOT_BIN` when a change needs generated-resource or runtime validation. GameMaker source compatibility targets GameMaker LTS 2026.

### Refresh dependency constraints

`requirements.txt` and `requirements-tooling.txt` contain the reviewed direct dependencies, while `requirements-lock.in` is the combined compile input. The repository's [native dependency-lock workflow](https://github.com/Infiland/GM2Godot/blob/main/.github/workflows/dependency-locks.yml) resolves that input on the exact Linux, macOS, and Windows baselines with the committed generator pin, currently `pip-tools==7.6.0`.

Pull requests and pushes use `refresh=locked`, which preference-seeds generation with the committed constraint and requests no upgrades. A manual `workflow_dispatch` run accepts:

| Selection | Behavior |
| --- | --- |
| `refresh=locked` | Recreate the preference-seeded graph without requesting an upgrade. |
| `refresh=all` | Request upgrades for the complete graph. |
| `refresh=package` | Upgrade only the normalized distribution supplied as `refresh_package`. |

`refresh_package` must be empty for `refresh=locked` and `refresh=all`; for `refresh=package`, it is required and must already be normalized, such as `pip-tools` or `pyside6`.

Each native job installs the candidate's own pip and pip-tools pins, regenerates a self-hosted constraint, and compares it with the candidate. It also performs two clean complete-graph installs and compares their normalized receipts. The candidate, self-hosted output, receipts, and evidence manifest are uploaded before the final equality gates.

An intentional refresh that changes pins is expected to fail the committed-equality gate. Review the artifacts for all three platforms, commit the approved native constraints, and rerun until `refresh=locked` is clean. If a pip or pip-tools upgrade makes the candidate differ from its self-hosted output, review and commit the self-hosted result first, then rerun with the new generator pins. Do not generate a constraint for a different platform locally; native environment markers and platform-specific transitive dependencies must be resolved on the platform they describe.

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

Included Files transaction changes must retain the subprocess hard-exit recovery test, not only exception-path tests:

```bash
./venv/bin/python -m unittest \
  tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_subprocess_interruption_recovers_every_publication_boundary \
  tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_committed_cleanup_recovery_is_idempotent_at_every_owned_boundary \
  tests.test_included_files.TestIncludedFilesManagedRootTransaction.test_temporary_record_cleanup_tombstones_resume_after_hard_exit
```

The publication test stops the child process at every forward transaction phase from the staged journal through commit-marker retirement, then requires recovery to select one complete generation. The two cleanup tests independently hard-exit after quarantine or removal for owned backup, staging, stable-record, and temporary-record state. Run the native Windows Included Files workflow when changing lock, move, junction, read-only, or cleanup behavior; modeled `os.name` tests are not a substitute for NTFS and Win32 coverage. Preserve the public `res://included_files/` and registry paths, reject unknown reserved-path state, and keep the documented prohibition on conversion alongside a live game or non-cooperating writer.

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
