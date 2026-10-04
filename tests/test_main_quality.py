from __future__ import annotations

import copy
import unittest
from collections.abc import Callable
from unittest.mock import patch

from scripts import check_main_quality as gate
from src.conversion.json_values import JsonArray, JsonObject

SHA = "a" * 40


class FakeClock:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.pauses: list[float] = []

    def now(self) -> float:
        return self.seconds

    def sleep(self, seconds: float) -> None:
        self.seconds += seconds
        self.pauses.append(seconds)

    def budget(self, seconds: float = 120) -> gate.Budget:
        return gate.Budget(seconds, now=self.now, sleep=self.sleep)


class FakeApi:
    """Original-style API fixtures, with independent run and paginated job bodies."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.round = 0
        self.pending_rounds = 0
        self.missing = False
        self.attempt = 1
        self.mutate: Callable[[str, JsonObject], JsonObject] | None = None
        self.jobs: dict[int, JsonArray] = {
            index: [self.job(index, index * 100 + 1)] for index in range(1, 8)
        }

    @staticmethod
    def job(index: int, job_id: int) -> JsonObject:
        return {
            "id": job_id, "run_id": 900 + index,
            "run_url": f"https://api.github.com{gate.API_ROOT}/runs/{900 + index}",
            "head_sha": SHA, "head_branch": "main", "name": f"quality-{job_id}",
            "run_attempt": 1,
            "status": "completed", "conclusion": "success",
        }

    def run(self, index: int) -> JsonObject:
        pending = self.round <= self.pending_rounds
        return {
            "id": 900 + index, "workflow_id": 200 + index,
            "run_attempt": self.attempt, "path": gate.REQUIRED_WORKFLOWS[index - 1],
            "repository": {"full_name": gate.REPOSITORY},
            "head_sha": SHA, "head_branch": "main", "event": "push",
            "status": "in_progress" if pending else "completed",
            "conclusion": None if pending else "success",
        }

    def get(self, path: str) -> JsonObject:
        self.calls.append(path)
        suffix = path.removeprefix(gate.API_ROOT + "/")
        if suffix.startswith("workflows/"):
            name = suffix.split("/")[1]
            if name.endswith(".yml"):
                workflow_path = ".github/workflows/" + name
                index = gate.REQUIRED_WORKFLOWS.index(workflow_path) + 1
                result: JsonObject = {"id": 200 + index, "path": workflow_path, "state": "active"}
            else:
                index = int(name) - 200
                if index == 1:
                    self.round += 1
                values: JsonArray = [] if self.missing else [self.run(index)]
                result = {"total_count": len(values), "workflow_runs": values}
        elif "/jobs?" in suffix:
            index = int(suffix.split("/")[1]) - 900
            page = int(path.rsplit("=", 1)[1])
            values = self.jobs[index]
            result = {"total_count": len(values), "jobs": copy.deepcopy(values[(page - 1) * 100:page * 100])}
        elif suffix.startswith("runs/"):
            result = self.run(int(suffix.split("/")[1]) - 900)
        else:
            raise AssertionError("unexpected API request: " + path)
        if self.mutate is not None:
            result = self.mutate(path, result)
        return result


class TestMainQuality(unittest.TestCase):
    def test_seven_successes_include_every_added_and_paginated_job(self) -> None:
        self.assertEqual(gate.REQUIRED_WORKFLOWS, (
            ".github/workflows/tests.yml", ".github/workflows/pyright.yml",
            ".github/workflows/code-health.yml", ".github/workflows/godot-smoke.yml",
            ".github/workflows/tcc-conversion-test.yml",
            ".github/workflows/native-wheel-proposals.yml", ".github/workflows/dependency-locks.yml",
        ))
        api = FakeApi()
        api.jobs[1] = [api.job(1, 1000 + index) for index in range(101)]
        receipt = gate.wait_for_main_quality(api, SHA, FakeClock().budget())
        self.assertEqual(receipt["head_sha"], SHA)
        workflows = receipt["workflows"]
        assert isinstance(workflows, list)
        self.assertEqual(len(workflows), 7)
        first = workflows[0]
        assert isinstance(first, dict)
        jobs = first["jobs"]
        assert isinstance(jobs, list)
        self.assertEqual(len(jobs), 101)
        self.assertEqual(first["run_id"], 901)
        self.assertEqual(first["run_attempt"], 1)
        self.assertIn(f"{gate.API_ROOT}/runs/901/jobs?filter=all&per_page=100&page=2", api.calls)
        self.assertFalse(any("release.yml" in call for call in api.calls))
        self.assertEqual(
            [value["path"] for value in workflows if isinstance(value, dict)],
            list(gate.REQUIRED_WORKFLOWS),
        )

    def test_pending_waits_but_missing_runs_exhaust_the_deadline(self) -> None:
        api = FakeApi()
        api.pending_rounds = 1
        clock = FakeClock()
        gate.wait_for_main_quality(api, SHA, clock.budget())
        self.assertEqual(clock.pauses, [30])
        self.assertEqual(api.round, 3)  # pending, completed, fresh final reobservation
        missing = FakeApi()
        missing.missing = True
        clock = FakeClock()
        with self.assertRaisesRegex(gate.QualityGateError, "deadline"):
            gate.wait_for_main_quality(missing, SHA, clock.budget(31))
        self.assertEqual(clock.pauses, [30, 1])
        self.assertFalse(any("/jobs?" in path for path in missing.calls))

    def test_unsuccessful_runs_and_hidden_or_incomplete_jobs_fail_closed(self) -> None:
        for conclusion in ("failure", "cancelled", "skipped", "neutral", "timed_out"):
            with self.subTest(run_conclusion=conclusion):
                api = FakeApi()

                def failed_run(path: str, body: JsonObject) -> JsonObject:
                    if "/workflows/201/runs?" in path:
                        values = body["workflow_runs"]
                        assert isinstance(values, list) and isinstance(values[0], dict)
                        values[0]["conclusion"] = conclusion
                    return body

                api.mutate = failed_run
                with self.assertRaises(gate.QualityGateError):
                    gate.wait_for_main_quality(api, SHA, FakeClock().budget())
            with self.subTest(job_conclusion=conclusion):
                api = FakeApi()
                api.jobs[1].append({**api.job(1, 150), "conclusion": conclusion})
                with self.assertRaisesRegex(gate.QualityGateError, "job"):
                    gate.wait_for_main_quality(api, SHA, FakeClock().budget())
        for mutation in ("truncated", "duplicate", "zero", "pending"):
            with self.subTest(inventory=mutation):
                api = FakeApi()

                def bad_jobs(path: str, body: JsonObject) -> JsonObject:
                    if "/runs/901/jobs?" in path:
                        if mutation == "truncated":
                            body["total_count"] = 2
                        elif mutation == "duplicate":
                            body["jobs"] = [api.job(1, 101), api.job(1, 101)]
                            body["total_count"] = 2
                        elif mutation == "zero":
                            body["jobs"] = []
                            body["total_count"] = 0
                        else:
                            body["jobs"] = [{**api.job(1, 101), "status": "queued", "conclusion": None}]
                    return body

                api.mutate = bad_jobs
                with self.assertRaises(gate.QualityGateError):
                    gate.wait_for_main_quality(api, SHA, FakeClock().budget())

    def test_wrong_source_event_path_repository_or_job_cannot_supply_proof(self) -> None:
        mutations: tuple[tuple[str, JsonObject], ...] = (
            ("run", {"head_sha": "b" * 40}), ("run", {"head_branch": "other"}),
            ("run", {"event": "pull_request"}), ("run", {"event": "workflow_dispatch"}),
            ("run", {"path": ".github/workflows/release.yml"}),
            ("run", {"repository": {"full_name": "other/GM2Godot"}}),
            ("run", {"workflow_id": 299}), ("run", {"run_attempt": True}),
            ("job", {"head_sha": "b" * 40}), ("job", {"run_id": 902}),
            ("job", {"head_branch": "other"}), ("job", {"run_url": "https://example.com/run"}),
            ("definition", {"path": ".github/workflows/release.yml"}),
        )
        for kind, changes in mutations:
            with self.subTest(kind=kind, changes=changes):
                api = FakeApi()

                def wrong_identity(path: str, body: JsonObject) -> JsonObject:
                    if kind == "definition" and path.endswith("/tests.yml"):
                        body.update(changes)
                    elif kind == "run" and "/workflows/201/runs?" in path:
                        values = body["workflow_runs"]
                        assert isinstance(values, list) and isinstance(values[0], dict)
                        values[0].update(changes)
                    elif kind == "job" and "/runs/901/jobs?" in path:
                        values = body["jobs"]
                        assert isinstance(values, list) and isinstance(values[0], dict)
                        values[0].update(changes)
                    return body

                api.mutate = wrong_identity
                with self.assertRaises(gate.QualityGateError):
                    gate.wait_for_main_quality(api, SHA, FakeClock().budget())
        for body in (b"[]", b'{"total_count":1,}', b"null", b"invalid", b"\xff"):
            with self.subTest(body=body), self.assertRaises(gate.QualityGateError):
                gate.parse_api_json(body)

    def test_reruns_attempt_drift_and_bounded_transport_never_reuse_stale_success(self) -> None:
        stable = FakeApi()
        stable.attempt = 2
        for index in range(1, 8):
            stable.jobs[index].append({**stable.job(index, index * 100 + 2),
                                       "name": "rerun-job", "conclusion": "failure"})
            stable.jobs[index].append({**stable.job(index, index * 100 + 3),
                                       "name": "rerun-job", "run_attempt": 2})
        receipt = gate.wait_for_main_quality(stable, SHA, FakeClock().budget())
        proofs = receipt["workflows"]
        assert isinstance(proofs, list) and isinstance(proofs[0], dict)
        jobs = proofs[0]["jobs"]
        assert isinstance(jobs, list)
        self.assertEqual(jobs, [
            {"id": 101, "name": "quality-101", "run_attempt": 1,
             "status": "completed", "conclusion": "success"},
            {"id": 103, "name": "rerun-job", "run_attempt": 2,
             "status": "completed", "conclusion": "success"},
        ])
        # Losing earlier successes or hiding an un-retried failure must not pass.
        for fault in ("missing_first_attempt", "unretried_failure", "future_attempt", "ambiguous_name"):
            with self.subTest(rerun_fault=fault):
                bad = FakeApi()
                bad.attempt = 2
                bad.jobs = copy.deepcopy(stable.jobs)
                if fault == "missing_first_attempt":
                    bad.jobs[1] = [{**bad.job(1, 103), "run_attempt": 2}]
                elif fault == "unretried_failure":
                    bad.jobs[1].append({**bad.job(1, 104), "conclusion": "failure"})
                elif fault == "future_attempt":
                    bad.jobs[1].append({**bad.job(1, 104), "run_attempt": 3})
                else:
                    bad.jobs[1].append({**bad.job(1, 104), "name": "rerun-job", "run_attempt": 2})
                with self.assertRaises(gate.QualityGateError):
                    gate.wait_for_main_quality(bad, SHA, FakeClock().budget())
        for stage in ("waiting", "after_jobs", "final_listing"):
            with self.subTest(stage=stage):
                api = FakeApi()
                api.pending_rounds = 1 if stage == "waiting" else 0

                def rerun(path: str, body: JsonObject) -> JsonObject:
                    if stage == "after_jobs" and path == f"{gate.API_ROOT}/runs/901":
                        body["run_attempt"] = 2
                    elif "/workflows/201/runs?" in path and api.round >= 2:
                        runs = body["workflow_runs"]
                        assert isinstance(runs, list) and isinstance(runs[0], dict)
                        runs[0]["run_attempt"] = 2
                    return body

                api.mutate = rerun
                with self.assertRaisesRegex(gate.QualityGateError, "changed"):
                    gate.wait_for_main_quality(api, SHA, FakeClock().budget())
        clock = FakeClock()
        token = "secret-test-token-never-print"
        with patch("scripts.check_main_quality.HTTPSConnection") as connection:
            connection.return_value.request.side_effect = OSError(token)
            with self.assertRaises(gate.QualityGateError) as result:
                gate.GitHubApi(token, clock.budget()).get(gate.API_ROOT + "/workflows/tests.yml")
            self.assertEqual(connection.call_count, 3)
            self.assertEqual(connection.return_value.close.call_count, 3)
        self.assertEqual(clock.pauses, [5, 5])
        self.assertNotIn(token, str(result.exception))


if __name__ == "__main__":
    unittest.main()
