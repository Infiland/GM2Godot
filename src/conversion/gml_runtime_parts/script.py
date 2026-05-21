from __future__ import annotations

from .manifest import (
    RUNTIME_SEGMENT_DIR,
    assert_runtime_segments_valid,
    runtime_segment_names,
)

_RUNTIME_SEGMENT_NAMES = runtime_segment_names()


def _read_runtime_script() -> str:
    assert_runtime_segments_valid()
    return "".join(
        (RUNTIME_SEGMENT_DIR / segment_name).read_text(encoding="utf-8")
        for segment_name in _RUNTIME_SEGMENT_NAMES
    )


GML_RUNTIME_SCRIPT = _read_runtime_script()
