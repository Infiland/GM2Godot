from __future__ import annotations

import threading
import unittest
from typing import Literal, cast

from src.conversion.conversion_outcome import (
    ConversionCounts,
    ConversionOutcome,
    ConversionStepLedger,
    ConversionTerminalState,
    ResourceOutcomeTracker,
)


class ConversionCountsTests(unittest.TestCase):
    def test_counts_require_terminal_partition(self) -> None:
        with self.assertRaises(ValueError):
            ConversionCounts(requested=2, executed=1, completed=1)

    def test_counts_require_completed_and_failed_work_to_be_executed(self) -> None:
        with self.assertRaises(ValueError):
            ConversionCounts(requested=1, completed=1)

    def test_counts_reject_negative_and_boolean_values(self) -> None:
        with self.assertRaises(ValueError):
            ConversionCounts(requested=-1, skipped=-1)
        with self.assertRaises(TypeError):
            ConversionCounts(requested=True, executed=True, completed=True)

    def test_counts_add_and_serialize(self) -> None:
        counts = ConversionCounts(
            requested=2,
            executed=2,
            completed=1,
            skipped=1,
        ) + ConversionCounts(requested=1, executed=1, failed=1)

        self.assertEqual(
            counts.to_dict(),
            {
                "requested": 3,
                "executed": 3,
                "completed": 1,
                "skipped": 1,
                "failed": 1,
            },
        )


class ConversionOutcomeTests(unittest.TestCase):
    def test_success_requires_fully_completed_partitions(self) -> None:
        incomplete_partitions = (
            (
                ConversionStepLedger.from_requested(("sprites",)),
                ConversionCounts(),
            ),
            (
                ConversionStepLedger(),
                ConversionCounts(requested=1, executed=1, failed=1),
            ),
        )

        for steps, resources in incomplete_partitions:
            with self.subTest(steps=steps, resources=resources):
                with self.assertRaises(ValueError) as context:
                    ConversionOutcome(
                        state="success",
                        steps=steps,
                        resources=resources,
                    )

                self.assertEqual(
                    str(context.exception),
                    "Successful conversion outcomes require every requested "
                    "converter and resource to be completed.",
                )

    def test_success_rejects_failure_context(self) -> None:
        completed = ConversionStepLedger.from_requested(("sprites",))
        completed = completed.start("sprites").complete("sprites")
        completed_resources = ConversionCounts(
            requested=1,
            executed=1,
            completed=1,
        )

        for context_fields in (
            {"failed_step": "objects"},
            {"failure_phase": "runtime"},
        ):
            with self.subTest(context_fields=context_fields):
                with self.assertRaises(ValueError) as context:
                    ConversionOutcome(
                        state="success",
                        steps=completed,
                        resources=completed_resources,
                        **context_fields,
                    )

                self.assertEqual(
                    str(context.exception),
                    "Successful conversion outcomes cannot include failure context.",
                )

    def test_success_accepts_fully_completed_partitions_without_failure_context(
        self,
    ) -> None:
        steps = ConversionStepLedger.from_requested(("sprites", "objects"))
        steps = steps.start("sprites").complete("sprites")
        steps = steps.start("objects").complete("objects")
        outcome = ConversionOutcome(
            state="success",
            steps=steps,
            resources=ConversionCounts(requested=3, executed=3, completed=3),
        )

        self.assertEqual(outcome.state, "success")

    def test_rejects_unknown_terminal_state_at_runtime(self) -> None:
        unknown_state = cast(ConversionTerminalState, "unknown")

        with self.assertRaises(ValueError) as context:
            ConversionOutcome(state=unknown_state)

        self.assertEqual(
            str(context.exception),
            "Conversion outcome state must be 'success', 'partial', 'failed', "
            "or 'cancelled'.",
        )

    def test_partial_requires_skipped_or_failed_work(self) -> None:
        fully_completed = ConversionCounts(
            requested=1,
            executed=1,
            completed=1,
        )

        completed_steps = ConversionStepLedger.from_requested(("sprites",))
        completed_steps = completed_steps.start("sprites").complete("sprites")

        for steps, resources in (
            (ConversionStepLedger(), ConversionCounts()),
            (completed_steps, fully_completed),
        ):
            with self.subTest(steps=steps, resources=resources):
                with self.assertRaises(ValueError) as context:
                    ConversionOutcome(
                        state="partial",
                        steps=steps,
                        resources=resources,
                    )

                self.assertEqual(
                    str(context.exception),
                    "Partial conversion outcomes require skipped or failed work.",
                )

    def test_partial_rejects_an_active_executed_step(self) -> None:
        active_steps = ConversionStepLedger.from_requested(("sprites",))
        active_steps = active_steps.start("sprites")

        with self.assertRaisesRegex(
            ValueError,
            "Partial conversion outcomes cannot include an active step",
        ):
            ConversionOutcome(state="partial", steps=active_steps)

    def test_partial_requires_every_requested_converter_step_to_complete(
        self,
    ) -> None:
        steps = ConversionStepLedger.from_requested(("sprites", "objects"))
        steps = steps.start("sprites").complete("sprites")

        with self.assertRaisesRegex(
            ValueError,
            "every requested converter step",
        ):
            ConversionOutcome(
                state="partial",
                steps=steps,
                resources=ConversionCounts(requested=1, skipped=1),
            )

    def test_non_success_states_allow_legitimate_terminal_shapes(self) -> None:
        requested_steps = ConversionStepLedger.from_requested(("sprites",))
        completed_steps = requested_steps.start("sprites").complete("sprites")
        outcomes = (
            ConversionOutcome(
                state="failed",
                steps=requested_steps,
                failed_step="preflight",
                failure_phase="preflight",
            ),
            ConversionOutcome(
                state="cancelled",
                steps=completed_steps,
                resources=ConversionCounts(requested=1, skipped=1),
            ),
            ConversionOutcome(
                state="partial",
                steps=completed_steps,
                resources=ConversionCounts(requested=1, executed=1, failed=1),
                failed_step="sprites",
                failure_phase="runtime",
            ),
        )

        self.assertEqual(
            tuple(outcome.state for outcome in outcomes),
            ("failed", "cancelled", "partial"),
        )

    def test_outcome_serializes_and_renders_deterministically(self) -> None:
        steps = ConversionStepLedger.from_requested(("sprites",))
        steps = steps.start("sprites").complete("sprites")
        outcome = ConversionOutcome(
            state="partial",
            steps=steps,
            resources=ConversionCounts(
                requested=2,
                executed=2,
                completed=1,
                skipped=1,
            ),
        )

        self.assertEqual(outcome.to_dict()["state"], "partial")
        self.assertEqual(
            outcome.to_dict()["steps"],
            {
                "requested": ["sprites"],
                "executed": ["sprites"],
                "completed": ["sprites"],
                "skipped": [],
                "failed": [],
            },
        )
        self.assertEqual(
            outcome.summary_line(),
            "GM2Godot conversion outcome: partial; "
            "converters[requested=1, executed=1, completed=1, skipped=0, failed=0]; "
            "resources[requested=2, executed=2, completed=1, skipped=1, failed=0]",
        )


class ConversionStepLedgerTests(unittest.TestCase):
    def test_transitions_are_immutable_and_derive_names_and_counts(self) -> None:
        requested = ConversionStepLedger.from_requested(
            ("sprites", "objects", "rooms")
        )
        sprites_active = requested.start("sprites")
        sprites_complete = sprites_active.complete("sprites")
        objects_active = sprites_complete.start("objects")
        objects_failed = objects_active.fail("objects")

        self.assertEqual(requested.executed, ())
        self.assertEqual(sprites_active.active_step, "sprites")
        self.assertEqual(sprites_complete.completed, ("sprites",))
        self.assertEqual(objects_failed.failed, ("objects",))
        self.assertIsNone(objects_failed.active_step)
        self.assertEqual(objects_failed.skipped, ("rooms",))
        self.assertEqual(
            objects_failed.counts,
            ConversionCounts(
                requested=3,
                executed=2,
                completed=1,
                skipped=1,
                failed=1,
            ),
        )

    def test_serializes_names_in_plan_order(self) -> None:
        ledger = ConversionStepLedger.from_requested(("sprites", "objects"))
        ledger = ledger.start("sprites").complete("sprites")

        self.assertEqual(
            ledger.to_dict(),
            {
                "requested": ["sprites", "objects"],
                "executed": ["sprites"],
                "completed": ["sprites"],
                "skipped": ["objects"],
                "failed": [],
            },
        )

    def test_rejects_invalid_names_and_duplicate_plan_entries(self) -> None:
        for invalid_name in ("", cast(str, 1), cast(str, True)):
            with self.subTest(invalid_name=invalid_name):
                with self.assertRaises((TypeError, ValueError)):
                    ConversionStepLedger.from_requested((invalid_name,))

        with self.assertRaises(ValueError):
            ConversionStepLedger.from_requested(("sprites", "sprites"))

    def test_rejects_state_that_violates_plan_invariants(self) -> None:
        invalid_states = (
            {"requested": ("sprites", "objects"), "executed": ("objects",)},
            {
                "requested": ("sprites", "objects"),
                "executed": ("sprites", "objects"),
                "completed": ("objects", "sprites"),
            },
            {
                "requested": ("sprites",),
                "executed": ("sprites",),
                "completed": ("sprites",),
                "failed": ("sprites",),
            },
            {
                "requested": ("sprites", "objects"),
                "executed": ("sprites", "objects"),
            },
            {
                "requested": ("sprites", "objects"),
                "executed": ("sprites", "objects"),
                "completed": ("objects",),
            },
            {
                "requested": ("sprites", "objects"),
                "executed": ("sprites", "objects"),
                "failed": ("sprites",),
            },
            {
                "requested": ("sprites", "objects"),
                "executed": ("sprites", "objects"),
                "failed": ("sprites", "objects"),
            },
        )

        for state in invalid_states:
            with self.subTest(state=state):
                with self.assertRaises(ValueError):
                    ConversionStepLedger(**state)

    def test_start_requires_the_next_plan_step_and_no_active_step(self) -> None:
        ledger = ConversionStepLedger.from_requested(("sprites", "objects"))

        with self.assertRaises(ValueError):
            ledger.start("objects")

        active = ledger.start("sprites")
        with self.assertRaises(ValueError):
            active.start("objects")

    def test_complete_and_fail_require_the_active_step(self) -> None:
        ledger = ConversionStepLedger.from_requested(("sprites",))

        with self.assertRaises(ValueError):
            ledger.complete("sprites")
        with self.assertRaises(ValueError):
            ledger.fail("sprites")

        active = ledger.start("sprites")
        with self.assertRaises(ValueError):
            active.complete("objects")
        with self.assertRaises(ValueError):
            active.fail("objects")

    def test_transitions_are_strictly_non_idempotent(self) -> None:
        completed = (
            ConversionStepLedger.from_requested(("sprites",))
            .start("sprites")
            .complete("sprites")
        )
        failed = (
            ConversionStepLedger.from_requested(("sprites",))
            .start("sprites")
            .fail("sprites")
        )

        with self.assertRaises(ValueError):
            completed.start("sprites")
        with self.assertRaises(ValueError):
            completed.complete("sprites")
        with self.assertRaises(ValueError):
            failed.fail("sprites")


class ResourceOutcomeTrackerTests(unittest.TestCase):
    def test_tracks_executed_and_unexecuted_skips(self) -> None:
        tracker = ResourceOutcomeTracker()
        tracker.request("complete")
        tracker.start("complete")
        tracker.complete("complete")
        tracker.request("started-skip")
        tracker.start("started-skip")
        tracker.skip("started-skip")
        tracker.request("not-started-skip")
        tracker.skip("not-started-skip")

        self.assertEqual(
            tracker.counts(),
            ConversionCounts(
                requested=3,
                executed=2,
                completed=1,
                skipped=2,
            ),
        )

    def test_duplicate_calls_are_idempotent(self) -> None:
        tracker = ResourceOutcomeTracker()
        tracker.request("resource")
        tracker.request("resource")
        tracker.start("resource")
        tracker.start("resource")
        tracker.complete("resource")
        tracker.complete("resource")

        self.assertEqual(
            tracker.counts(),
            ConversionCounts(requested=1, executed=1, completed=1),
        )

    def test_conflicting_terminal_transition_is_rejected(self) -> None:
        tracker = ResourceOutcomeTracker()
        tracker.request("resource")
        tracker.skip("resource")

        with self.assertRaises(ValueError):
            tracker.fail("resource")

    def test_unrequested_transition_is_rejected(self) -> None:
        tracker = ResourceOutcomeTracker()
        with self.assertRaises(ValueError):
            tracker.start("missing")

    def test_unfinished_counts_must_be_finalized(self) -> None:
        tracker = ResourceOutcomeTracker()
        tracker.request("resource")
        with self.assertRaises(ValueError):
            tracker.counts()

        self.assertEqual(
            tracker.counts(finalize_unfinished_as="skipped"),
            ConversionCounts(requested=1, skipped=1),
        )

    def test_failed_finalization_fails_started_and_skips_unstarted_work(self) -> None:
        tracker = ResourceOutcomeTracker()
        tracker.request("not-started")
        tracker.request("started")
        tracker.start("started")

        self.assertEqual(
            tracker.counts(finalize_unfinished_as="failed"),
            ConversionCounts(requested=2, executed=1, skipped=1, failed=1),
        )

    def test_unsupported_finalization_is_rejected_without_mutating_tracker(
        self,
    ) -> None:
        tracker = ResourceOutcomeTracker()
        tracker.request("resource")
        unsupported_mode = cast(Literal["skipped", "failed"], "completed")

        with self.assertRaises(ValueError) as context:
            tracker.counts(finalize_unfinished_as=unsupported_mode)

        self.assertEqual(
            str(context.exception),
            "Unfinished resources can only be finalized as 'skipped' or 'failed'.",
        )

        tracker.start("resource")
        tracker.complete("resource")
        self.assertEqual(
            tracker.counts(),
            ConversionCounts(requested=1, executed=1, completed=1),
        )

    def test_thread_safe_lifecycle_tracking(self) -> None:
        tracker = ResourceOutcomeTracker()

        def convert(index: int) -> None:
            key = f"resource:{index}"
            tracker.request(key)
            tracker.start(key)
            tracker.complete(key)

        threads = [threading.Thread(target=convert, args=(index,)) for index in range(50)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(
            tracker.counts(),
            ConversionCounts(requested=50, executed=50, completed=50),
        )


if __name__ == "__main__":
    unittest.main()
