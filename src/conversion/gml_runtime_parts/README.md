# GML Runtime Segments

`manifest.py` owns the generated runtime segment order, dependency declarations, provided-symbol index, and API-to-segment index. Keep the `.gd` segment files focused on Godot runtime behavior; put ownership metadata in the manifest so tests can validate it without changing the emitted `gml_runtime.gd` body.

Segment rules:
- Declare every new `.gd` segment in `RUNTIME_SEGMENTS`.
- Add dependencies for earlier segments that initialize state or constants the segment assumes are present.
- Add at least one focused test module in `test_modules`.
- Split a segment when it starts owning a separate GameMaker manual area, needs independent Godot smoke tests, or exposes a lifecycle/state registry that can be validated on its own.
- Do not add duplicate `class`, `const`, `static var`, or `static func` providers across segments; `tests/test_gml_runtime_segments.py` fails on duplicates.
