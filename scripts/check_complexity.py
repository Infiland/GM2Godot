"""Enforce C901 findings against explicitly reviewed, ratcheting allowances."""

from __future__ import annotations

import argparse
import ast
import json
import keyword
import re
import subprocess
import sys
import tokenize
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TextIO
from urllib.parse import urlsplit

from src.conversion.json_values import JsonObject, JsonValue, validate_json_value

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_COMPLEXITY = 15
LINT_PATTERNS = ("*.py", "*.pyi", "*.pyw", "*.ipynb", "*.md")
PYTHON_SUFFIXES = frozenset((".py", ".pyi", ".pyw"))
_MESSAGE = re.compile(r"`([^`]+)` is too complex \(([1-9]\d*) > ([1-9]\d*)\)\Z")
_EXCEPTION_FIELDS = frozenset((
    "path", "function", "measured_complexity", "ceiling", "reason", "removal_action", "tracking_url",
))
_REQUIRED_DIAGNOSTIC_FIELDS = frozenset(("code", "filename", "location", "message"))
_OPTIONAL_DIAGNOSTIC_FIELDS = frozenset((
    "cell", "end_location", "fix", "name", "noqa_row", "severity", "url",
))
_PLAN_FENCE = re.compile(r" {0,3}(?P<marker>`{3,}|~{3,})(?P<tail>.*)\Z")
_PLAN_ANCHOR = re.compile(
    r""" {0,3}<a[ \t]+(?:id|name)=(?P<quote>["'])(?P<anchor>[^"' \t<>]+)(?P=quote)></a>[ \t]*\Z"""
)
_PLAN_HEADING = re.compile(
    r" {0,3}#{1,6}[ \t]+(?P<text>[\w-]+(?:[ \t]+[\w-]+)*)(?:[ \t]+#+)?[ \t]*\Z"
)


class ComplexityError(ValueError):
    """Invalid policy, source, input enumeration or Ruff output."""


class ComplexityArguments(argparse.Namespace):
    root: Path = PROJECT_ROOT
    policy: Path | None = None


@dataclass(frozen=True, order=True)
class FunctionKey:
    path: str
    function: str

    def display(self) -> str:
        return f"{self.path}::{self.function}"


@dataclass(frozen=True)
class ComplexityException:
    key: FunctionKey
    measured_complexity: int
    ceiling: int
    reason: str
    removal_action: str
    tracking_url: str


@dataclass(frozen=True)
class ComplexityPolicy:
    exceptions: tuple[ComplexityException, ...]


@dataclass(frozen=True)
class FunctionDefinition:
    key: FunctionKey
    name: str
    row: int


@dataclass(frozen=True)
class FunctionIndex:
    by_location: dict[tuple[str, int], FunctionDefinition]
    by_key: dict[FunctionKey, tuple[FunctionDefinition, ...]]


@dataclass(frozen=True)
class ComplexityFinding:
    key: FunctionKey
    complexity: int
    row: int


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    # This is confined to decoding; the complete result is validated below.
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ComplexityError(f"duplicate JSON object key: {name!r}")
        result[name] = value
    return result


def _decode_json(text: str, context: str) -> JsonValue:
    try:
        raw_value: object = json.loads(text, object_pairs_hook=_unique_json_object)
        return validate_json_value(raw_value, source_path=context)
    except (ValueError, RecursionError) as error:
        raise ComplexityError(f"{context}: {error}") from error


def _object(value: JsonValue, context: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ComplexityError(f"{context} must be an object")
    return value


def _text(value: JsonValue, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ComplexityError(f"{context} must be a nonempty string")
    return value


def _integer(value: JsonValue, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ComplexityError(f"{context} must be a positive integer")
    return value


def _relative_path(value: JsonValue, context: str) -> str:
    name = _text(value, context)
    path = PurePosixPath(name)
    if "\\" in name or path.is_absolute() or path.as_posix() != name or any(part in (".", "..") for part in path.parts):
        raise ComplexityError(f"{context} must be a normalized repository-relative POSIX path")
    return name


def _function_name(value: JsonValue) -> str:
    name = _text(value, "exception.function")
    if not all(part.isidentifier() and not keyword.iskeyword(part) for part in name.split(".")):
        raise ComplexityError("exception.function must be a lexical qualified function name")
    return name


def _tracking_link(value: JsonValue) -> str:
    link = _text(value, "exception.tracking_url")
    if any(character.isspace() for character in link):
        raise ComplexityError("exception.tracking_url must not contain whitespace")
    try:
        parsed = urlsplit(link)
        _port = parsed.port
    except ValueError as error:
        raise ComplexityError("exception.tracking_url is malformed") from error
    if parsed.scheme:
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or not parsed.path:
            raise ComplexityError("exception.tracking_url must be an HTTPS plan/issue link")
    else:
        path = _relative_path(parsed.path, "exception.tracking_url")
        if parsed.netloc or parsed.query or not path.startswith("docs/") or not path.endswith(".md"):
            raise ComplexityError("relative exception.tracking_url must name a repository docs Markdown plan")
    return link


def _exception(value: JsonValue) -> ComplexityException:
    record = _object(value, "exception")
    if frozenset(record) != _EXCEPTION_FIELDS:
        raise ComplexityError("exception must contain exactly the seven documented fields")
    key = FunctionKey(_relative_path(record["path"], "exception.path"), _function_name(record["function"]))
    if PurePosixPath(key.path).suffix not in PYTHON_SUFFIXES:
        raise ComplexityError("exception.path must name an ordinary Python source file")
    measured = _integer(record["measured_complexity"], "exception.measured_complexity")
    ceiling = _integer(record["ceiling"], "exception.ceiling")
    if measured <= MAX_COMPLEXITY or measured != ceiling:
        raise ComplexityError("exception measured_complexity and ceiling must be equal and exceed 15")
    return ComplexityException(
        key, measured, ceiling, _text(record["reason"], "exception.reason"),
        _text(record["removal_action"], "exception.removal_action"), _tracking_link(record["tracking_url"]),
    )


def load_policy(path: Path) -> ComplexityPolicy:
    try:
        payload = _object(_decode_json(path.read_text(encoding="utf-8"), str(path)), "complexity policy")
    except (OSError, UnicodeError) as error:
        raise ComplexityError(f"cannot read complexity policy {path}: {error}") from error
    if set(payload) != {"schema_version", "max_complexity", "exceptions"}:
        raise ComplexityError("complexity policy has missing or unknown fields")
    if _integer(payload["schema_version"], "schema_version") != 1:
        raise ComplexityError("complexity policy schema_version must be 1")
    if _integer(payload["max_complexity"], "max_complexity") != MAX_COMPLEXITY:
        raise ComplexityError("complexity policy max_complexity must remain 15")
    values = payload["exceptions"]
    if not isinstance(values, list):
        raise ComplexityError("complexity policy exceptions must be an array")
    exceptions = tuple(_exception(value) for value in values)
    keys = [exception.key for exception in exceptions]
    if len(set(keys)) != len(keys):
        raise ComplexityError("complexity policy contains duplicate path/function keys")
    return ComplexityPolicy(exceptions)


def _read_local_plan(root: Path, path: str) -> str:
    try:
        canonical_root = root.resolve(strict=True)
        document = (canonical_root / path).resolve(strict=True)
        relative = document.relative_to(canonical_root).as_posix()
    except (OSError, ValueError, RuntimeError) as error:
        # Python 3.12 reports Path.resolve symlink loops as RuntimeError.
        raise ComplexityError(f"cannot resolve local removal plan {path}: {error}") from error
    if relative != path:
        raise ComplexityError(f"local removal plan is not its canonical repository path: {path}")
    try:
        return document.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ComplexityError(f"cannot read local removal plan {path}: {error}") from error


def _plan_fence_closes(fence: re.Match[str] | None, opening: str) -> bool:
    return (
        fence is not None
        and fence.group("marker")[0] == opening[0]
        and len(fence.group("marker")) >= len(opening)
        and not fence.group("tail").strip()
    )


def _local_plan_anchors(text: str) -> set[str]:
    anchors: set[str] = set()
    heading_counts: dict[str, int] = {}
    opening = ""
    in_comment = False
    for line in text.splitlines():
        fence = _PLAN_FENCE.fullmatch(line)
        if opening:
            if _plan_fence_closes(fence, opening):
                opening = ""
            continue
        if in_comment:
            in_comment = "-->" not in line
            continue
        if line.startswith(("    ", "\t")):
            continue
        if fence is not None:
            opening = fence.group("marker")
            continue
        if "<!--" in line:
            in_comment = "-->" not in line.split("<!--", 1)[1]
            continue
        anchor = _PLAN_ANCHOR.fullmatch(line)
        if anchor is not None:
            anchors.add(anchor.group("anchor"))
            continue
        heading = _PLAN_HEADING.fullmatch(line)
        if heading is not None:
            slug = re.sub(r"[ \t]+", "-", heading.group("text").lower())
            count = heading_counts.get(slug, 0)
            anchors.add(slug if count == 0 else f"{slug}-{count}")
            heading_counts[slug] = count + 1
    return anchors


def validate_local_plan_links(root: Path, policy: ComplexityPolicy, inputs: Sequence[str]) -> None:
    for exception in policy.exceptions:
        link = urlsplit(exception.tracking_url)
        if link.scheme:
            continue
        if link.path not in inputs:
            raise ComplexityError(f"removal-plan document must be tracked: {link.path}")
        content = _read_local_plan(root, link.path)
        if link.fragment and link.fragment not in _local_plan_anchors(content):
            raise ComplexityError(f"local removal-plan fragment must name an existing anchor: {exception.tracking_url}")


def tracked_inputs(root: Path) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ("git", "ls-files", "-z", "--", *LINT_PATTERNS), cwd=root,
            capture_output=True, check=False, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ComplexityError(f"cannot enumerate tracked lint inputs: {error}") from error
    if result.returncode != 0:
        raise ComplexityError(f"git ls-files failed ({result.returncode}): {result.stderr.decode(errors='replace')}")
    try:
        output = result.stdout.decode("utf-8")
    except UnicodeError as error:
        raise ComplexityError("tracked lint input names must be UTF-8") from error
    if not output or not output.endswith("\0"):
        raise ComplexityError("tracked lint input enumeration must be nonempty and NUL-terminated")
    names = tuple(_relative_path(name, "tracked input") for name in output[:-1].split("\0"))
    if len(set(names)) != len(names):
        raise ComplexityError("tracked lint inputs contain duplicates")
    return names


def ruff_command(python: str, inputs: Sequence[str]) -> tuple[str, ...]:
    return (
        python, "-m", "ruff", "check", "--isolated", "--target-version", "py312", "--line-length", "120",
        "--select", "C90", "--ignore-noqa", "--no-respect-gitignore", "--no-force-exclude", "--no-cache",
        "--output-format", "json", "--config", "lint.mccabe.max-complexity=15", "--", *inputs,
    )


def _print_retained_output(output: bytes | str | None, stream: TextIO) -> None:
    if output is None:
        return
    text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else output
    if text:
        print(text, file=stream, end="" if text.endswith("\n") else "\n")


def run_ruff(root: Path, inputs: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ruff_command(sys.executable, inputs), cwd=root,
            capture_output=True, text=True, check=False, timeout=120,
        )
    except subprocess.TimeoutExpired as error:
        _print_retained_output(error.stdout, sys.stdout)
        _print_retained_output(error.stderr, sys.stderr)
        raise ComplexityError(f"cannot execute the required complexity command: {error}") from error
    except (OSError, UnicodeError) as error:
        raise ComplexityError(f"cannot execute the required complexity command: {error}") from error


def _definitions(node: ast.AST, path: str, scope: tuple[str, ...]) -> list[FunctionDefinition]:
    definitions: list[FunctionDefinition] = []
    for child in ast.iter_child_nodes(node):
        nested_scope = scope
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nested_scope = (*scope, child.name)
            definitions.append(FunctionDefinition(FunctionKey(path, ".".join(nested_scope)), child.name, child.lineno))
        elif isinstance(child, ast.ClassDef):
            nested_scope = (*scope, child.name)
        definitions.extend(_definitions(child, path, nested_scope))
    return definitions


def index_functions(root: Path, inputs: Sequence[str]) -> FunctionIndex:
    by_location: dict[tuple[str, int], FunctionDefinition] = {}
    by_key: dict[FunctionKey, tuple[FunctionDefinition, ...]] = {}
    for path in inputs:
        if PurePosixPath(path).suffix not in PYTHON_SUFFIXES:
            continue
        try:
            resolved = (root / path).resolve(strict=True)
            if resolved.relative_to(root.resolve(strict=True)).as_posix() != path:
                raise ComplexityError(f"tracked Python source is not its canonical repository path: {path}")
            with tokenize.open(resolved) as source:
                tree = ast.parse(source.read(), filename=path)
        except (OSError, SyntaxError, UnicodeError, ValueError, RecursionError) as error:
            raise ComplexityError(f"cannot parse tracked Python source {path}: {error}") from error
        try:
            definitions = _definitions(tree, path, ())
        except RecursionError as error:
            raise ComplexityError(f"cannot index tracked Python source {path}: {error}") from error
        for definition in definitions:
            location = (path, definition.row)
            if location in by_location:
                raise ComplexityError(f"duplicate function definition location: {location}")
            by_location[location] = definition
            by_key[definition.key] = (*by_key.get(definition.key, ()), definition)
    return FunctionIndex(by_location, by_key)


def _location(value: JsonValue) -> tuple[int, int]:
    location = _object(value, "diagnostic location")
    if set(location) != {"row", "column"}:
        raise ComplexityError("diagnostic location must contain only row and column")
    return _integer(location["row"], "diagnostic row"), _integer(location["column"], "diagnostic column")


def _diagnostic_path(value: JsonValue, root: Path, inputs: Sequence[str]) -> str:
    filename = _text(value, "diagnostic filename")
    candidate = Path(filename)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        path = candidate.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix()
    except (OSError, ValueError) as error:
        raise ComplexityError(f"diagnostic filename is outside the source root or inaccessible: {filename}") from error
    if path not in inputs or PurePosixPath(path).suffix not in PYTHON_SUFFIXES:
        raise ComplexityError(f"diagnostic filename is untracked or not ordinary Python source: {path}")
    return path


def _diagnostic_metadata(record: JsonObject) -> None:
    fields = set(record)
    if not _REQUIRED_DIAGNOSTIC_FIELDS <= fields or fields - (_REQUIRED_DIAGNOSTIC_FIELDS | _OPTIONAL_DIAGNOSTIC_FIELDS):
        raise ComplexityError("Ruff diagnostic has missing or unknown fields")
    if record["code"] != "C901" or record.get("cell") is not None or record.get("fix") is not None:
        raise ComplexityError("only non-notebook, non-fixable C901 diagnostics are supported")
    for field, expected in (
        ("name", "complex-structure"), ("severity", "error"),
        ("url", "https://docs.astral.sh/ruff/rules/complex-structure"),
    ):
        if field in record and record[field] != expected:
            raise ComplexityError(f"unexpected C901 diagnostic {field}")
    if "end_location" in record:
        _location(record["end_location"])
    if "noqa_row" in record:
        _integer(record["noqa_row"], "diagnostic noqa_row")


def _diagnostic(record: JsonObject, root: Path, inputs: Sequence[str], index: FunctionIndex) -> ComplexityFinding:
    _diagnostic_metadata(record)
    path = _diagnostic_path(record["filename"], root, inputs)
    row, _column = _location(record["location"])
    definition = index.by_location.get((path, row))
    if definition is None or len(index.by_key[definition.key]) != 1:
        raise ComplexityError(f"C901 must identify one unique qualified function at {path}:{row}")
    match = _MESSAGE.fullmatch(_text(record["message"], "diagnostic message"))
    if match is None or match[1] != definition.name:
        raise ComplexityError(f"C901 message does not match function/threshold at {path}:{row}")
    try:
        threshold = int(match[3])
    except ValueError as error:
        raise ComplexityError(f"invalid tool complexity values at {path}:{row}") from error
    if threshold != MAX_COMPLEXITY:
        raise ComplexityError(f"C901 message does not match function/threshold at {path}:{row}")
    try:
        score = int(match[2])
    except ValueError as error:
        raise ComplexityError(f"invalid tool complexity values at {path}:{row}") from error
    if score <= MAX_COMPLEXITY:
        raise ComplexityError("C901 score must exceed 15")
    return ComplexityFinding(definition.key, score, row)


def parse_findings(
    output: subprocess.CompletedProcess[str], root: Path, inputs: Sequence[str], index: FunctionIndex,
) -> tuple[ComplexityFinding, ...]:
    if output.returncode not in (0, 1):
        raise ComplexityError(f"Ruff operational failure ({output.returncode})")
    payload = _decode_json(output.stdout, "Ruff C901 output")
    if not isinstance(payload, list):
        raise ComplexityError("Ruff C901 output must be an array")
    if (output.returncode == 0) != (len(payload) == 0):
        raise ComplexityError("Ruff exit status does not match its findings")
    findings = tuple(_diagnostic(_object(value, "diagnostic"), root, inputs, index) for value in payload)
    keys = [finding.key for finding in findings]
    if len(set(keys)) != len(keys):
        raise ComplexityError("Ruff output contains duplicate path/function findings")
    return findings


def evaluate_policy(policy: ComplexityPolicy, findings: Sequence[ComplexityFinding]) -> tuple[str, ...]:
    exceptions = {exception.key: exception for exception in policy.exceptions}
    observed = {finding.key: finding for finding in findings}
    errors: list[str] = []
    for key, finding in sorted(observed.items()):
        exception = exceptions.get(key)
        if exception is None:
            errors.append(f"new complexity debt: {key.display()} ({finding.complexity})")
        elif finding.complexity > exception.ceiling:
            errors.append(f"complexity ceiling exceeded: {key.display()} ({finding.complexity} > {exception.ceiling})")
        elif finding.complexity < exception.measured_complexity:
            errors.append(f"tighten measured score and ceiling: {key.display()} ({exception.measured_complexity} -> {finding.complexity})")
    for key in sorted(exceptions.keys() - observed.keys()):
        errors.append(f"remove stale exception: {key.display()} (absent or complexity <= 15)")
    return tuple(errors)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--policy", type=Path)
    arguments = parser.parse_args(argv, namespace=ComplexityArguments())
    root = arguments.root
    policy_path = arguments.policy if arguments.policy is not None else root / "complexity-exceptions.json"
    try:
        inputs = tracked_inputs(root)
        policy = load_policy(policy_path)
        validate_local_plan_links(root, policy, inputs)
        index = index_functions(root, inputs)
        output = run_ruff(root, inputs)
        if output.stdout:
            print(output.stdout, end="" if output.stdout.endswith("\n") else "\n")
        if output.stderr:
            print(output.stderr, file=sys.stderr, end="" if output.stderr.endswith("\n") else "\n")
        findings = parse_findings(output, root, inputs, index)
        errors = evaluate_policy(policy, findings)
    except ComplexityError as error:
        print(f"Complexity gate invalid: {error}", file=sys.stderr)
        return 2
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    for finding in sorted(findings, key=lambda item: item.key):
        print(f"Reviewed complexity: {finding.key.display()} ({finding.complexity})")
    print(f"Complexity gate passed: {len(inputs)} tracked inputs, {len(findings)} reviewed exceptions, threshold 15.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
