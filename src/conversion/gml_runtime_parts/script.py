from __future__ import annotations

from pathlib import Path

_RUNTIME_SEGMENT_NAMES = (
    "00_prelude.gd",
    "15_asset_registry.gd",
    "10_handles_and_instances.gd",
    "20_methods_and_exceptions.gd",
    "30_numeric_arithmetic.gd",
    "40_arrays_structs_variables.gd",
    "45_collision_queries.gd",
    "46_motion_helpers.gd",
    "47_paths_motion_planning.gd",
    "48_drawing_basic_forms.gd",
    "49_drawing_surfaces.gd",
    "52_cameras_display.gd",
    "50_static_types_and_clone.gd",
    "60_conversion_helpers.gd",
    "70_handle_string_helpers.gd",
    "80_static_hash_clone_error.gd",
)
_RUNTIME_SEGMENT_DIR = Path(__file__).with_name("segments")


def _read_runtime_script() -> str:
    return "".join(
        (_RUNTIME_SEGMENT_DIR / segment_name).read_text(encoding="utf-8")
        for segment_name in _RUNTIME_SEGMENT_NAMES
    )


GML_RUNTIME_SCRIPT = _read_runtime_script()
