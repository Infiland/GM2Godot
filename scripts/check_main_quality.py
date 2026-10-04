"""Require the seven other exact-source main workflows before publication."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException, HTTPSConnection
from pathlib import Path
from typing import Protocol

from src.conversion.json_values import JsonArray, JsonObject, JsonValue, validate_json_value

REPOSITORY = "Infiland/GM2Godot"
REQUIRED_WORKFLOWS = (
    ".github/workflows/tests.yml",
    ".github/workflows/pyright.yml",
    ".github/workflows/code-health.yml",
    ".github/workflows/godot-smoke.yml",
    ".github/workflows/tcc-conversion-test.yml",
    ".github/workflows/native-wheel-proposals.yml",
    ".github/workflows/dependency-locks.yml",
)
PENDING_STATUSES = frozenset(("queued", "in_progress", "waiting", "pending", "requested"))
POLL_SECONDS = 30
DEADLINE_SECONDS = 5400
REQUEST_SECONDS = 15
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_JOBS = 1000
API_ROOT = f"/repos/{REPOSITORY}/actions"


class QualityGateError(RuntimeError):
    """A missing, unsuccessful or inconsistent quality proof cannot publish."""


class ApiReader(Protocol):
    def get(self, path: str) -> JsonObject: ...


class Budget:
    def __init__(
        self,
        seconds: float = DEADLINE_SECONDS,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._now = now
        self._sleep = sleep
        self._deadline = now() + seconds

    def remaining(self) -> float:
        remaining = self._deadline - self._now()
        if remaining <= 0:
            raise QualityGateError("main quality deadline expired")
        return remaining

    def pause(self, seconds: float) -> None:
        self._sleep(min(seconds, self.remaining()))
        self.remaining()


def _object(value: JsonValue, field: str) -> JsonObject:
    if not isinstance(value, dict):
        raise QualityGateError(f"invalid API object: {field}")
    return value


def _text(value: JsonValue, field: str) -> str:
    if not isinstance(value, str):
        raise QualityGateError(f"invalid API text: {field}")
    return value


def _integer(value: JsonValue, field: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise QualityGateError(f"invalid API integer: {field}")
    return value


def _array(value: JsonValue, field: str) -> JsonArray:
    if not isinstance(value, list):
        raise QualityGateError(f"invalid API array: {field}")
    return value


def parse_api_json(body: bytes) -> JsonObject:
    try:
        decoded: object = json.loads(body)
        value = validate_json_value(decoded, source_path="GitHub Actions API")
        return _object(value, "response")
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise QualityGateError("invalid GitHub Actions JSON response") from error


class GitHubApi:
    """GET only, fixed host, no redirects or token-bearing error messages."""

    def __init__(self, token: str, budget: Budget) -> None:
        if not token or any(character in token for character in "\r\n"):
            raise QualityGateError("a valid read-only Actions token is required")
        self._token = token
        self._budget = budget

    def get(self, path: str) -> JsonObject:
        if not path.startswith(API_ROOT + "/"):
            raise QualityGateError("API request escaped the required repository")
        for attempt in range(3):
            connection = HTTPSConnection(
                "api.github.com", timeout=min(REQUEST_SECONDS, self._budget.remaining())
            )
            try:
                connection.request(
                    "GET", path,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {self._token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "GM2Godot-main-quality",
                    },
                )
                response = connection.getresponse()
                if response.status != 200:
                    if response.status not in (408, 429, 500, 502, 503, 504):
                        raise QualityGateError(f"Actions API returned HTTP {response.status}")
                else:
                    chunks: list[bytes] = []
                    size = 0
                    while True:
                        self._budget.remaining()
                        chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - size))
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise QualityGateError("Actions API response exceeded the byte limit")
                        chunks.append(chunk)
                    self._budget.remaining()
                    return parse_api_json(b"".join(chunks))
            except (OSError, HTTPException):
                pass
            finally:
                connection.close()
            if attempt < 2:
                self._budget.pause(5)
        raise QualityGateError("Actions API failed after three bounded GET attempts")


@dataclass(frozen=True)
class RunIdentity:
    workflow_id: int
    run_id: int
    attempt: int
    path: str


@dataclass(frozen=True)
class RunState:
    identity: RunIdentity
    status: str
    conclusion: str | None


def _run(value: JsonObject, *, workflow_id: int, path: str, sha: str) -> RunState:
    repository = _object(value.get("repository"), "repository")
    expected = {
        "head_sha": sha,
        "head_branch": "main",
        "event": "push",
        "path": path,
    }
    if _text(repository.get("full_name"), "repository.full_name") != REPOSITORY:
        raise QualityGateError("run repository does not match")
    for field, wanted in expected.items():
        if _text(value.get(field), field) != wanted:
            raise QualityGateError(f"run {field} does not match the required source")
    if _integer(value.get("workflow_id"), "workflow_id") != workflow_id:
        raise QualityGateError("run workflow ID does not match its path")
    attempt = _integer(value.get("run_attempt"), "run_attempt")
    if attempt > MAX_JOBS:
        raise QualityGateError("run attempts exceeded the bounded job-history capacity")
    status = _text(value.get("status"), "status")
    conclusion = value.get("conclusion")
    if conclusion is not None and not isinstance(conclusion, str):
        raise QualityGateError("invalid API conclusion")
    if status == "completed":
        if conclusion != "success":
            raise QualityGateError(f"required workflow {path} did not succeed")
    elif status not in PENDING_STATUSES or conclusion is not None:
        raise QualityGateError("invalid or unsuccessful workflow state")
    return RunState(
        RunIdentity(
            workflow_id, _integer(value.get("id"), "id"),
            attempt, path,
        ),
        status, conclusion,
    )


def _selected_run(api: ApiReader, *, workflow_id: int, path: str, sha: str) -> RunState | None:
    listing = api.get(
        f"{API_ROOT}/workflows/{workflow_id}/runs"
        f"?head_sha={sha}&branch=main&event=push&per_page=100&page=1"
    )
    count = _integer(listing.get("total_count"), "total_count", minimum=0)
    values = _array(listing.get("workflow_runs"), "workflow_runs")
    # A rerun keeps its run ID. Multiple push runs for one SHA/path are ambiguous.
    if count == 0 and not values:
        return None
    if count != 1 or len(values) != 1:
        raise QualityGateError(f"ambiguous exact-source workflow run: {path}")
    return _run(_object(values[0], "workflow_run"), workflow_id=workflow_id, path=path, sha=sha)


def _successful_jobs(api: ApiReader, identity: RunIdentity, sha: str) -> JsonArray:
    # Failed-job reruns omit earlier successes from attempt-specific lists. Inspect
    # complete history, then require the newest execution of every job name.
    ids: set[int] = set()
    executions: set[tuple[str, int]] = set()
    latest: dict[str, tuple[int, JsonObject]] = {}
    attempts: set[int] = set()
    expected_count: int | None = None
    for page in range(1, MAX_JOBS // 100 + 1):
        payload = api.get(
            f"{API_ROOT}/runs/{identity.run_id}/jobs?filter=all&per_page=100&page={page}"
        )
        count = _integer(payload.get("total_count"), "total_count")
        values = _array(payload.get("jobs"), "jobs")
        if count > MAX_JOBS or len(values) > 100:
            raise QualityGateError("job inventory exceeded its finite bound")
        if expected_count is not None and count != expected_count:
            raise QualityGateError("job inventory changed during pagination")
        expected_count = count
        for value in values:
            job = _object(value, "job")
            job_id = _integer(job.get("id"), "job.id")
            if job_id in ids:
                raise QualityGateError("duplicate job in the attempt inventory")
            ids.add(job_id)
            if (
                _integer(job.get("run_id"), "job.run_id") != identity.run_id
                or _text(job.get("run_url"), "job.run_url")
                != f"https://api.github.com{API_ROOT}/runs/{identity.run_id}"
                or _text(job.get("head_sha"), "job.head_sha") != sha
                or _text(job.get("head_branch"), "job.head_branch") != "main"
            ):
                raise QualityGateError("job source identity does not match the selected attempt")
            attempt = _integer(job.get("run_attempt"), "job.run_attempt")
            name = _text(job.get("name"), "job.name")
            if not name or attempt > identity.attempt:
                raise QualityGateError("invalid or future job execution identity")
            if (name, attempt) in executions:
                raise QualityGateError("ambiguous duplicate job name within an attempt")
            executions.add((name, attempt))
            attempts.add(attempt)
            previous = latest.get(name)
            if previous is None or attempt > previous[0]:
                latest[name] = (attempt, job)
        if len(ids) == count:
            if attempts != set(range(1, identity.attempt + 1)):
                raise QualityGateError("job history does not cover every observed run attempt")
            jobs: JsonArray = []
            for attempt, job in latest.values():
                job_id = _integer(job["id"], "job.id")
                if job.get("status") != "completed" or job.get("conclusion") != "success":
                    raise QualityGateError(f"required job {job_id} did not complete successfully")
                jobs.append({"id": job_id, "name": job["name"], "run_attempt": attempt,
                             "status": "completed", "conclusion": "success"})
            return jobs
        if len(ids) > count or len(values) != 100:
            raise QualityGateError("incomplete or inconsistent job inventory")
    raise QualityGateError("job inventory exceeded its pagination limit")


def wait_for_main_quality(api: ApiReader, sha: str, budget: Budget) -> JsonObject:
    if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise QualityGateError("invalid exact main source SHA")
    workflow_ids: dict[str, int] = {}
    for path in REQUIRED_WORKFLOWS:
        definition = api.get(f"{API_ROOT}/workflows/{path.rsplit('/', 1)[1]}")
        if definition.get("path") != path or definition.get("state") != "active":
            raise QualityGateError(f"required workflow path is missing or inactive: {path}")
        workflow_ids[path] = _integer(definition.get("id"), "workflow.id")
    if len(set(workflow_ids.values())) != len(REQUIRED_WORKFLOWS):
        raise QualityGateError("required workflow identities are not distinct")

    selected: dict[str, RunIdentity] = {}
    while True:
        budget.remaining()
        states: list[RunState] = []
        for path, workflow_id in workflow_ids.items():
            run = _selected_run(api, workflow_id=workflow_id, path=path, sha=sha)
            if run is None:
                if path in selected:
                    raise QualityGateError("a selected workflow run disappeared")
                continue
            previous = selected.setdefault(path, run.identity)
            if previous != run.identity:
                raise QualityGateError("selected run or latest attempt changed; refusing stale success")
            states.append(run)
        if len(states) == len(REQUIRED_WORKFLOWS) and all(
            state.status == "completed" for state in states
        ):
            proofs: JsonArray = []
            for state in states:
                identity = state.identity
                jobs = _successful_jobs(api, identity, sha)
                current = _run(
                    api.get(f"{API_ROOT}/runs/{identity.run_id}"),
                    workflow_id=identity.workflow_id, path=identity.path, sha=sha,
                )
                if current != state:
                    raise QualityGateError("run or attempt changed while inspecting its jobs")
                proofs.append({
                    "path": identity.path, "workflow_id": identity.workflow_id,
                    "run_id": identity.run_id, "run_attempt": identity.attempt, "jobs": jobs,
                    "status": state.status, "conclusion": state.conclusion,
                })
            # Reobserve every path after all seven inventories, including new duplicate runs.
            for state in states:
                current = _selected_run(
                    api, workflow_id=state.identity.workflow_id, path=state.identity.path, sha=sha,
                )
                if current != state:
                    raise QualityGateError("quality identities changed before publication approval")
            budget.remaining()
            return {"schema": 1, "repository": REPOSITORY, "head_sha": sha,
                    "event": "push", "head_branch": "main", "workflows": proofs}
        budget.pause(POLL_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if (
        os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_EVENT_NAME") not in ("push", "workflow_dispatch")
    ):
        print("Main quality gate requires the trusted repository/main release context", file=sys.stderr)
        return 1
    try:
        budget = Budget()
        receipt = wait_for_main_quality(
            GitHubApi(os.environ.get("GH_TOKEN", ""), budget),
            os.environ.get("GITHUB_SHA", ""), budget,
        )
        output: Path = arguments.output
        with output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    except (QualityGateError, OSError) as error:
        print(f"Main quality gate failed: {error}", file=sys.stderr)
        return 1
    print("All seven exact-source main workflows and every selected-attempt job succeeded")
    print(json.dumps(receipt, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
