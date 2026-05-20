# GM2Godot Full Transpilation Todo List

This folder tracks what GM2Godot already has and what still needs to be added to fully transpile GMS2+ GameMaker projects into Godot projects.

Scope rule: target current GMS2+ / modern GameMaker compatibility only. GMS 1.4 or GML 1.4-only behavior is out of scope.

Research inputs used for this first pass:

- GameMaker manual monthly GML index: https://manual.gamemaker.io/monthly/en/index.htm#t=GameMaker_Language%2FGameMaker_Language_Index.htm
- Official GameMaker manual source indexed through Context7: `/yoyogames/gamemaker-manual`
- Godot stable documentation: https://docs.godotengine.org/en/stable/
- Official Godot docs indexed through Context7: `/websites/godotengine_en_stable` and `/godotengine/godot-docs`
- Current GM2Godot codebase and tests under `src/` and `tests/`

Status rules:

- `[x]` means GM2Godot currently has an implementation with code and/or tests in this repository.
- `[ ]` means the item is missing, incomplete, partial, approximate, or not yet proven by tests.
- Items labeled `Partial:` are intentionally left unchecked until full GameMaker-compatible behavior exists.
- This is a planning document, not a guarantee of exact runtime parity.

Current summary:

- `[x]` GM2Godot already has broad resource conversion for sprites, sounds, fonts, notes, included files, objects, scripts, rooms, tilesets, shaders, asset registries, path registries, and project settings.
- `[x]` GM2Godot already has a substantial GML parser/transpiler and generated Godot runtime compatibility layer.
- `[x]` GM2Godot already has many unit tests and Godot smoke tests for generated runtime areas.
- `[ ]` Full compatibility is not complete. The largest gaps are exact event scheduling, full input/collision/draw phase dispatch, full GameMaker runtime API coverage, full shader conversion, platform services, native extensions, sequences/timelines, texture groups, advanced surfaces/GPU state, and real Godot CI validation.

## Documentation Index

- `00-priority-index.md`: P0 through P3 implementation roadmap.
- `01-current-coverage.md`: Current checked and unchecked coverage by code area.
- `02-gml-language.md`: GML syntax, semantic, preprocessor, and API dispatch checklist.
- `03-events.md`: GameMaker event matrix and dispatch gaps.
- `04-runtime-api.md`: Runtime API domains and missing manual categories.
- `05-assets-project-import.md`: GameMaker project/resource import checklist.
- `06-godot-architecture.md`: Godot-side generation, runtime, and best-practice roadmap.
- `07-testing-codebase-improvements.md`: Test, CI, diagnostics, architecture, and maintainability roadmap.
- `08-gms2-manual-scope.md`: GMS2+ manual-scope checklist covering every GML Code Overview and GML Reference category from the current manual.

## Immediate Interpretation

GM2Godot should not mark a feature as done only because it can parse a file or generate a placeholder. Mark it done when the converter preserves behavior enough for a real GameMaker project and has a test path that would catch regressions.

Partial features should stay unchecked until they support the behavior users expect from the official GameMaker manual. Examples include shader conversion, tilemap conversion, sequence/timeline behavior, platform services, collision events, input events, and draw subevents.
