from __future__ import annotations


def _after_included_transaction_phase(_phase: str) -> None:
    """Narrow subprocess-test seam after one durable publication boundary."""


after_included_transaction_phase = _after_included_transaction_phase
