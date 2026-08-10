from __future__ import annotations

import os
import sys
import unittest
from typing import TextIO


EXACT_TEST_NAME = (
    "tests.test_included_files.TestIncludedFilesManagedRootTransaction."
    "test_ten_thousand_entry_compact_records_publish_and_recover_below_cap"
)
REQUIRE_ENVIRONMENT_VARIABLE = (
    "GM2GODOT_REQUIRE_WINDOWS_INCLUDED_FILES_SCALE_GATE"
)
SKIP_ENVIRONMENT_VARIABLE = "GM2GODOT_SKIP_WINDOWS_INCLUDED_FILES_SCALE_GATE"


def run_exact_suite(
    suite: unittest.TestSuite,
    *,
    stream: TextIO,
) -> int:
    collected = suite.countTestCases()
    if collected != 1:
        print(
            "The native Windows Included Files scale gate must collect exactly "
            f"one test; collected {collected}.",
            file=stream,
        )
        return 2

    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    invalid_outcomes = (
        result.testsRun != 1
        or bool(result.skipped)
        or bool(result.failures)
        or bool(result.errors)
        or bool(result.expectedFailures)
        or bool(result.unexpectedSuccesses)
        or not result.wasSuccessful()
    )
    if invalid_outcomes:
        print(
            "The native Windows Included Files scale gate requires exactly one "
            "executed passing test with zero skips, failures, errors, expected "
            "failures, or unexpected successes.",
            file=stream,
        )
        return 1
    return 0


def main() -> int:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        print(
            "The native Windows Included Files scale gate runner may only run "
            "in GitHub Actions.",
            file=sys.stderr,
        )
        return 2
    if os.environ.get(REQUIRE_ENVIRONMENT_VARIABLE) != "1":
        print(
            f"{REQUIRE_ENVIRONMENT_VARIABLE}=1 is required.",
            file=sys.stderr,
        )
        return 2
    if os.environ.get(SKIP_ENVIRONMENT_VARIABLE) == "1":
        print(
            f"{SKIP_ENVIRONMENT_VARIABLE}=1 conflicts with the required gate.",
            file=sys.stderr,
        )
        return 2

    try:
        suite = unittest.defaultTestLoader.loadTestsFromName(EXACT_TEST_NAME)
        return run_exact_suite(suite, stream=sys.stderr)
    except SystemExit as error:
        print(
            "The native Windows Included Files scale gate raised an unexpected "
            f"SystemExit({error.code!r}); refusing a successful process exit.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
