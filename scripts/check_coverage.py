from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import fnmatch
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Sequence, cast


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = PROJECT_ROOT / "coverage-policy.json"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "coverage-reports" / "coverage.json"


class CoveragePolicyError(ValueError):
    """Raised when coverage policy or report data is malformed."""


@dataclass(frozen=True)
class CoverageCounts:
    covered_lines: int
    statements: int
    covered_branches: int
    branches: int

    def add(self, other: CoverageCounts) -> CoverageCounts:
        return CoverageCounts(
            covered_lines=self.covered_lines + other.covered_lines,
            statements=self.statements + other.statements,
            covered_branches=self.covered_branches + other.covered_branches,
            branches=self.branches + other.branches,
        )


@dataclass(frozen=True)
class CoverageScope:
    name: str
    include: tuple[str, ...]
    line_floor: Decimal
    branch_floor: Decimal


@dataclass(frozen=True)
class CoveragePolicy:
    source_files: tuple[str, ...]
    source_directories: tuple[str, ...]
    scopes: tuple[CoverageScope, ...]


def _object_mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CoveragePolicyError(f"{context} must be a JSON object")
    mapping = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        raise CoveragePolicyError(f"{context} keys must be strings")
    return {cast(str, key): item for key, item in mapping.items()}


def _object_sequence(value: object, context: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise CoveragePolicyError(f"{context} must be a JSON array")
    return tuple(cast(list[object], value))


def _required_value(mapping: dict[str, object], key: str, context: str) -> object:
    try:
        return mapping[key]
    except KeyError as error:
        raise CoveragePolicyError(f"{context} is missing {key!r}") from error


def _required_string(mapping: dict[str, object], key: str, context: str) -> str:
    value = _required_value(mapping, key, context)
    if not isinstance(value, str) or not value:
        raise CoveragePolicyError(f"{context}.{key} must be a non-empty string")
    return value


def _required_string_sequence(
    mapping: dict[str, object],
    key: str,
    context: str,
) -> tuple[str, ...]:
    values = _object_sequence(_required_value(mapping, key, context), f"{context}.{key}")
    if not values or not all(isinstance(value, str) and value for value in values):
        raise CoveragePolicyError(f"{context}.{key} must contain non-empty strings")
    strings = cast(tuple[str, ...], values)
    if len(strings) != len(set(strings)):
        raise CoveragePolicyError(f"{context}.{key} must not contain duplicates")
    return strings


def _required_decimal(
    mapping: dict[str, object],
    key: str,
    context: str,
) -> Decimal:
    value = _required_value(mapping, key, context)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise CoveragePolicyError(f"{context}.{key} must be a decimal percentage")
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise CoveragePolicyError(
            f"{context}.{key} must be a decimal percentage"
        ) from error
    if not number.is_finite() or number < 0 or number > 100:
        raise CoveragePolicyError(f"{context}.{key} must be between 0 and 100")
    return number


def _required_nonnegative_integer(
    mapping: dict[str, object],
    key: str,
    context: str,
) -> int:
    value = _required_value(mapping, key, context)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CoveragePolicyError(f"{context}.{key} must be a non-negative integer")
    return value


def _read_json_object(path: Path, context: str) -> dict[str, object]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CoveragePolicyError(f"cannot read {context} {path}: {error}") from error
    try:
        raw_value = cast(object, json.loads(raw_text))
    except json.JSONDecodeError as error:
        raise CoveragePolicyError(f"{context} {path} is not valid JSON: {error}") from error
    return _object_mapping(raw_value, context)


def load_policy(path: Path) -> CoveragePolicy:
    payload = _read_json_object(path, "coverage policy")
    schema_version = _required_value(payload, "schema_version", "coverage policy")
    if schema_version != 1:
        raise CoveragePolicyError(
            f"coverage policy schema_version must be 1, found {schema_version!r}"
        )

    measurement_baseline = _object_mapping(
        _required_value(payload, "baseline", "coverage policy"),
        "coverage policy.baseline",
    )
    baseline_commit = _required_string(
        measurement_baseline,
        "commit",
        "coverage policy.baseline",
    )
    if len(baseline_commit) != 40 or any(
        character not in "0123456789abcdef" for character in baseline_commit
    ):
        raise CoveragePolicyError(
            "coverage policy.baseline.commit must be a full lowercase Git commit"
        )
    for key in ("coverage", "python", "platform", "command"):
        _required_string(
            measurement_baseline,
            key,
            "coverage policy.baseline",
        )

    source = _object_mapping(
        _required_value(payload, "source", "coverage policy"),
        "coverage policy.source",
    )
    source_files = _required_string_sequence(
        source,
        "files",
        "coverage policy.source",
    )
    source_directories = _required_string_sequence(
        source,
        "directories",
        "coverage policy.source",
    )

    raw_scopes = _object_sequence(
        _required_value(payload, "floors", "coverage policy"),
        "coverage policy.floors",
    )
    if not raw_scopes:
        raise CoveragePolicyError("coverage policy.floors must not be empty")

    scopes: list[CoverageScope] = []
    for index, raw_scope in enumerate(raw_scopes):
        context = f"coverage policy.floors[{index}]"
        scope = _object_mapping(raw_scope, context)
        baseline_context = f"{context}.baseline"
        baseline = _object_mapping(
            _required_value(scope, "baseline", context),
            baseline_context,
        )
        baseline_counts = CoverageCounts(
            covered_lines=_required_nonnegative_integer(
                baseline,
                "covered_lines",
                baseline_context,
            ),
            statements=_required_nonnegative_integer(
                baseline,
                "statements",
                baseline_context,
            ),
            covered_branches=_required_nonnegative_integer(
                baseline,
                "covered_branches",
                baseline_context,
            ),
            branches=_required_nonnegative_integer(
                baseline,
                "branches",
                baseline_context,
            ),
        )
        if baseline_counts.statements == 0 or baseline_counts.branches == 0:
            raise CoveragePolicyError(
                f"{baseline_context} must contain line and branch opportunities"
            )
        if baseline_counts.covered_lines > baseline_counts.statements:
            raise CoveragePolicyError(
                f"{baseline_context}.covered_lines exceeds statements"
            )
        if baseline_counts.covered_branches > baseline_counts.branches:
            raise CoveragePolicyError(
                f"{baseline_context}.covered_branches exceeds branches"
            )
        line_floor = _required_decimal(scope, "line", context)
        branch_floor = _required_decimal(scope, "branch", context)
        expected_line_floor = _percentage(
            baseline_counts.covered_lines,
            baseline_counts.statements,
        ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        expected_branch_floor = _percentage(
            baseline_counts.covered_branches,
            baseline_counts.branches,
        ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if line_floor != expected_line_floor:
            raise CoveragePolicyError(
                f"{context}.line must equal the baseline truncated to two "
                f"decimals: {expected_line_floor}"
            )
        if branch_floor != expected_branch_floor:
            raise CoveragePolicyError(
                f"{context}.branch must equal the baseline truncated to two "
                f"decimals: {expected_branch_floor}"
            )
        scopes.append(
            CoverageScope(
                name=_required_string(scope, "name", context),
                include=_required_string_sequence(scope, "include", context),
                line_floor=line_floor,
                branch_floor=branch_floor,
            )
        )
    names = [scope.name for scope in scopes]
    if len(names) != len(set(names)):
        raise CoveragePolicyError("coverage floor names must be unique")

    return CoveragePolicy(
        source_files=source_files,
        source_directories=source_directories,
        scopes=tuple(scopes),
    )


def _normalize_report_path(raw_path: str) -> str:
    if "\\" in raw_path:
        raise CoveragePolicyError(
            f"coverage report path must use forward slashes: {raw_path!r}"
        )
    path = PurePosixPath(raw_path)
    if path.is_absolute() or ".." in path.parts or str(path) != raw_path:
        raise CoveragePolicyError(
            f"coverage report path must be normalized and relative: {raw_path!r}"
        )
    return raw_path


def load_report(path: Path) -> dict[str, CoverageCounts]:
    payload = _read_json_object(path, "coverage report")
    meta = _object_mapping(
        _required_value(payload, "meta", "coverage report"),
        "coverage report.meta",
    )
    if _required_value(meta, "branch_coverage", "coverage report.meta") is not True:
        raise CoveragePolicyError(
            "coverage report must be collected with branch_coverage=true"
        )

    raw_files = _object_mapping(
        _required_value(payload, "files", "coverage report"),
        "coverage report.files",
    )
    if not raw_files:
        raise CoveragePolicyError("coverage report.files must not be empty")

    files: dict[str, CoverageCounts] = {}
    for raw_path, raw_file in raw_files.items():
        normalized_path = _normalize_report_path(raw_path)
        file_payload = _object_mapping(
            raw_file,
            f"coverage report.files[{raw_path!r}]",
        )
        summary = _object_mapping(
            _required_value(
                file_payload,
                "summary",
                f"coverage report.files[{raw_path!r}]",
            ),
            f"coverage report.files[{raw_path!r}].summary",
        )
        context = f"coverage report.files[{raw_path!r}].summary"
        counts = CoverageCounts(
            covered_lines=_required_nonnegative_integer(
                summary,
                "covered_lines",
                context,
            ),
            statements=_required_nonnegative_integer(
                summary,
                "num_statements",
                context,
            ),
            covered_branches=_required_nonnegative_integer(
                summary,
                "covered_branches",
                context,
            ),
            branches=_required_nonnegative_integer(
                summary,
                "num_branches",
                context,
            ),
        )
        if counts.covered_lines > counts.statements:
            raise CoveragePolicyError(
                f"{context}.covered_lines exceeds num_statements"
            )
        if counts.covered_branches > counts.branches:
            raise CoveragePolicyError(
                f"{context}.covered_branches exceeds num_branches"
            )
        files[normalized_path] = counts
    return files


def expected_source_files(policy: CoveragePolicy, source_root: Path) -> set[str]:
    expected = set(policy.source_files)
    for relative_path in policy.source_files:
        if not (source_root / relative_path).is_file():
            raise CoveragePolicyError(
                f"configured coverage source file does not exist: {relative_path}"
            )
    for relative_directory in policy.source_directories:
        directory = source_root / relative_directory
        if not directory.is_dir():
            raise CoveragePolicyError(
                f"configured coverage source directory does not exist: "
                f"{relative_directory}"
            )
        expected.update(
            path.relative_to(source_root).as_posix()
            for path in directory.rglob("*.py")
            if path.is_file()
        )
    return expected


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _percentage(covered: int, total: int) -> Decimal:
    if total == 0:
        return Decimal(100)
    return Decimal(covered) * Decimal(100) / Decimal(total)


def _format_percentage(value: Decimal) -> str:
    return f"{value:.2f}%"


def evaluate_coverage(
    policy: CoveragePolicy,
    files: dict[str, CoverageCounts],
    source_root: Path,
) -> tuple[str, ...]:
    expected = expected_source_files(policy, source_root)
    observed = set(files)
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"missing production files: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected files: {', '.join(unexpected)}")
        raise CoveragePolicyError(
            "coverage report source scope mismatch; " + "; ".join(details)
        )

    failures: list[str] = []
    print(
        "Coverage floors "
        "(line = covered statements / statements; "
        "branch = covered destinations / branch destinations):"
    )
    for scope in policy.scopes:
        selected = [
            counts
            for path, counts in files.items()
            if _matches_any(path, scope.include)
        ]
        if not selected:
            raise CoveragePolicyError(
                f"coverage floor {scope.name!r} matched no production files"
            )
        totals = CoverageCounts(0, 0, 0, 0)
        for counts in selected:
            totals = totals.add(counts)

        line_percentage = _percentage(totals.covered_lines, totals.statements)
        branch_percentage = _percentage(
            totals.covered_branches,
            totals.branches,
        )
        line_passed = line_percentage >= scope.line_floor
        branch_passed = branch_percentage >= scope.branch_floor
        status = "PASS" if line_passed and branch_passed else "FAIL"
        print(
            f"{status} {scope.name}: "
            f"line {_format_percentage(line_percentage)} "
            f"({totals.covered_lines}/{totals.statements}, "
            f"floor {_format_percentage(scope.line_floor)}); "
            f"branch {_format_percentage(branch_percentage)} "
            f"({totals.covered_branches}/{totals.branches}, "
            f"floor {_format_percentage(scope.branch_floor)})"
        )
        if not line_passed:
            failures.append(
                f"{scope.name} line coverage "
                f"{_format_percentage(line_percentage)} is below "
                f"{_format_percentage(scope.line_floor)}"
            )
        if not branch_passed:
            failures.append(
                f"{scope.name} branch coverage "
                f"{_format_percentage(branch_percentage)} is below "
                f"{_format_percentage(scope.branch_floor)}"
            )
    return tuple(failures)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enforce measured line and branch coverage floors.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="coverage.py JSON report path",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_POLICY_PATH,
        help="coverage floor policy path",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=PROJECT_ROOT,
        help="root containing the measured production source",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        policy = load_policy(arguments.policy)
        report = load_report(arguments.report)
        failures = evaluate_coverage(policy, report, arguments.source_root)
    except CoveragePolicyError as error:
        print(f"Coverage configuration error: {error}", file=sys.stderr)
        return 2
    if failures:
        for failure in failures:
            print(f"Coverage floor failure: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
