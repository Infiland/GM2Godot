"""Exact-build Godot selection for optional runtime tests."""

from __future__ import annotations

import subprocess
import unittest

from src.conversion.godot_validation import find_godot_binary

_EXPECTED_GODOT_VERSION = "4.7.2.stable.official.ed1daf0bf"


def require_exact_godot(godot_binary: str | None = None, *, timeout: int = 10) -> str:
    """Return the selected executable; skip only when optional discovery is absent."""
    if godot_binary is None:
        godot_binary = find_godot_binary()
    if godot_binary is None:
        raise unittest.SkipTest("Godot binary not available")
    result = subprocess.run(
        [godot_binary, "--version"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise AssertionError(f"Godot --version exited with {result.returncode}: {output}")
    if output != _EXPECTED_GODOT_VERSION:
        raise AssertionError(f"Exact Godot {_EXPECTED_GODOT_VERSION} required; found {output!r}")
    return godot_binary
