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
   - Install Python 3.12 or later
   - Install required packages:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     pip install -r requirements.txt
     ```
   - Install optional local tooling when changing Python code:
     ```bash
     pip install pyright ruff
     ```

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
