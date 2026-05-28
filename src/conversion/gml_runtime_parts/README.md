# GML Runtime Segments

`manifest.py` owns the generated runtime segment order, dependency declarations, provided-symbol index, and API-to-segment index. Keep the `.gd` segment files focused on Godot runtime behavior; put ownership metadata in the manifest so tests can validate it without changing the emitted `gml_runtime.gd` body.

Segment rules:
- Declare every new `.gd` segment in `RUNTIME_SEGMENTS`.
- Add dependencies for earlier segments that initialize state or constants the segment assumes are present.
- Add at least one focused test module in `test_modules`.
- Split a segment when it starts owning a separate GameMaker manual area, needs independent Godot smoke tests, or exposes a lifecycle/state registry that can be validated on its own.
- Do not add duplicate `class`, `const`, `static var`, or `static func` providers across segments; `tests/test_gml_runtime_segments.py` fails on duplicates.

## Ownership

Each segment owns one GameMaker runtime domain and should keep public `gml_*`
helpers close to the state they mutate. The manifest description is the public
owner note for that segment. If a helper crosses domains, keep the call-site
facade in the API's owner segment and call a smaller helper in the dependency
segment rather than duplicating state.

Runtime segment ownership is indexed by:
- `runtime_segment_names()` for stable concatenation order.
- `runtime_symbol_index()` for public symbol-to-segment lookup.
- `runtime_api_index()` for manifest API entries linked to runtime symbols,
  test modules, docs URLs, and issue numbers.

## Adding Runtime API Coverage

1. Add or update the GML API manifest entry.
2. Add dispatch metadata in the transpiler when the API can be lowered from GML.
3. Implement the `gml_*` helper in the owning segment.
4. Declare or update the segment's dependency and test metadata in `manifest.py`.
5. Add a focused unit test and a Godot smoke test when behavior depends on
   Godot nodes, resources, input, draw order, audio, networking, or physics.

## Runtime State

Prefer segment-owned dictionaries, typed handle records, or generated manager
state buckets for mutable state. Keep `GMRuntime.gml_*` names stable because
generated scripts call them directly. When state needs to outlive a room, record
the persistence rule in `src/conversion/runtime_managers.md` and add tests that
cover room transitions or restart behavior.
