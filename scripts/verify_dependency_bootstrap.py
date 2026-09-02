#!/usr/bin/env python3
"""Verify the reviewed pip/pip-tools source against native dependency locks."""

from __future__ import annotations

if __package__:
    from .verify_dependency_environment import bootstrap_preflight_main
else:
    from verify_dependency_environment import bootstrap_preflight_main


if __name__ == "__main__":
    raise SystemExit(bootstrap_preflight_main())
