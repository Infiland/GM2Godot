from __future__ import annotations

from collections.abc import Iterable

from src.conversion.conversion_outcome import ConversionStepLedger
from src.conversion.conversion_plan import CONVERSION_STEPS, build_conversion_plan


def completed_conversion_step_ledger(
    enabled_keys: Iterable[str] | None = None,
) -> ConversionStepLedger:
    """Return a fully completed ledger in the real conversion-plan order."""
    plan = build_conversion_plan(
        (step.key for step in CONVERSION_STEPS)
        if enabled_keys is None
        else enabled_keys
    )
    ledger = ConversionStepLedger.from_requested(step.key for step in plan)
    for step in plan:
        ledger = ledger.start(step.key).complete(step.key)
    return ledger
