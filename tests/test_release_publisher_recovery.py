from __future__ import annotations

from collections.abc import Mapping
from contextlib import redirect_stderr
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
from typing import cast
import unittest
from unittest.mock import patch

from scripts import release_publisher as publisher_module
from tests.test_release_publisher import (
    API_ORIGIN,
    ASSET_ORDER,
    FaultKind,
    FOREIGN_RELEASE_ID,
    OWNED_RELEASE_ID,
    PAYLOAD_ORDER,
    RELEASE_NAME,
    REPOSITORY,
    ScriptedTransport,
    TAG,
    TARGET_SHA,
    UPLOAD_ORIGIN,
    VisibilityScriptedTransport,
)


def _publisher_environment(
    *,
    receipt_path: str = "release-receipt/release-publisher.json",
    asset_root: str = "artifacts",
) -> dict[str, str]:
    return {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_TOKEN": "unit-test-token",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REF_TYPE": "branch",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_SHA": TARGET_SHA,
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_API_URL": API_ORIGIN,
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_ATTEMPT": "2",
        "RELEASE_TARGET_SHA": TARGET_SHA,
        "RELEASE_TAG": TAG,
        "RELEASE_NAME": RELEASE_NAME,
        "RELEASE_RECEIPT_PATH": receipt_path,
        "RELEASE_ASSET_ROOT": asset_root,
        "RELEASE_PREFLIGHT_RETRY_DELAY_SECONDS": "0",
        "RELEASE_OWNERSHIP_RETRY_DELAY_SECONDS": "0",
    }


def _write_release_assets(root: Path) -> None:
    payloads = {
        "GM2Godot-windows.zip": b"PK\x03\x04GM2Godot Windows recovery test\n",
        "GM2Godot-macos-arm64.zip": b"PK\x03\x04GM2Godot macOS arm64 recovery test\n",
        "GM2Godot-macos-arm64.dmg": b"kolyGM2Godot macOS arm64 recovery test\n",
        "GM2Godot-macos-x86_64.zip": b"PK\x03\x04GM2Godot macOS x86_64 recovery test\n",
        "GM2Godot-macos-x86_64.dmg": b"kolyGM2Godot macOS x86_64 recovery test\n",
        "GM2Godot-linux.zip": b"PK\x03\x04GM2Godot Linux recovery test\n",
    }
    locations = {
        "GM2Godot-windows.zip": root / "GM2Godot-windows/GM2Godot-windows.zip",
        "GM2Godot-macos-arm64.zip": root / "GM2Godot-macos-arm64/GM2Godot-macos-arm64.zip",
        "GM2Godot-macos-arm64.dmg": root / "GM2Godot-macos-arm64/GM2Godot-macos-arm64.dmg",
        "GM2Godot-macos-x86_64.zip": root / "GM2Godot-macos-x86_64/GM2Godot-macos-x86_64.zip",
        "GM2Godot-macos-x86_64.dmg": root / "GM2Godot-macos-x86_64/GM2Godot-macos-x86_64.dmg",
        "GM2Godot-linux.zip": root / "GM2Godot-linux/GM2Godot-linux.zip",
    }
    for name, destination in locations.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payloads[name])
    manifest = "".join(f"{hashlib.sha256(payloads[name]).hexdigest()}  {name}\n" for name in PAYLOAD_ORDER)
    (root / "SHA256SUMS").write_text(manifest, encoding="ascii", newline="\n")


class SnapshottingTransport(ScriptedTransport):
    def __init__(
        self,
        receipt_path: Path,
        faults: Mapping[int, FaultKind],
        *,
        response_loss_ordinal: int | None = None,
    ) -> None:
        super().__init__(faults)
        self.receipt_path = receipt_path
        self.response_loss_ordinal = response_loss_ordinal
        self.pre_mutation_receipts: dict[int, dict[str, object]] = {}

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        *,
        json_body: bytes | None = None,
        file_body: publisher_module.FileSeal | None = None,
    ) -> publisher_module.TransportResult:
        ordinal = len(self.calls) + 1
        if method != "GET":
            document = json.loads(self.receipt_path.read_text(encoding="utf-8"))
            self.pre_mutation_receipts[ordinal] = cast(dict[str, object], document)
        result = super().request(
            method,
            url,
            headers,
            json_body=json_body,
            file_body=file_body,
        )
        if ordinal == self.response_loss_ordinal:
            raise publisher_module.TransportError("simulated mutation response loss")
        return result


class TestPublisherConfiguration(unittest.TestCase):
    def test_windows_publisher_fails_before_receipt_or_api_mutations(self) -> None:
        workspace = Path.cwd()
        with tempfile.TemporaryDirectory(prefix=".publisher-platform-", dir=workspace) as directory:
            root = Path(directory)
            destination = root / "uncreated-receipts" / "publisher.json"
            environment = _publisher_environment(receipt_path=str(destination.relative_to(workspace)))
            stderr = StringIO()
            with (
                patch.object(publisher_module.sys, "platform", "win32"),
                patch.object(publisher_module.tempfile, "mkstemp", side_effect=AssertionError("receipt created")) as mkstemp,
                patch.object(publisher_module, "HttpsTransport", side_effect=AssertionError("API created")) as transport,
                redirect_stderr(stderr),
            ):
                result = publisher_module.main(environment)
            self.assertEqual(result, 1)
            self.assertIn("Release publishing requires POSIX file permissions", stderr.getvalue())
            mkstemp.assert_not_called()
            transport.assert_not_called()
            self.assertFalse(destination.parent.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_accepts_only_main_branch_release_events_and_exact_sha(self) -> None:
        for event_name in ("push", "workflow_dispatch"):
            with self.subTest(accepted_event=event_name):
                environment = _publisher_environment()
                environment["GITHUB_EVENT_NAME"] = event_name
                config = publisher_module.PublisherConfig.from_environment(environment)
                self.assertEqual(config.target_sha, TARGET_SHA)
                self.assertEqual(config.release_name, RELEASE_NAME)
                self.assertEqual(config.ownership_retry_delay_seconds, 0)
                self.assertEqual(
                    config.run_url,
                    f"https://github.com/{REPOSITORY}/actions/runs/12345/attempts/2",
                )

        rejected = (
            ("GITHUB_REF", "refs/tags/v0.7.18", "refs/heads/main"),
            ("GITHUB_REF_TYPE", "tag", "branch event ref"),
            ("GITHUB_EVENT_NAME", "pull_request", "not allowed"),
            ("RELEASE_TARGET_SHA", "b" * 40, "must equal"),
            ("GITHUB_SHA", "A" * 40, "must equal"),
        )
        for variable, value, message in rejected:
            with self.subTest(rejected_variable=variable, value=value):
                environment = _publisher_environment()
                environment[variable] = value
                with self.assertRaisesRegex(ValueError, message):
                    publisher_module.PublisherConfig.from_environment(environment)

    def test_requires_canonical_origins_relative_paths_and_fixed_name(self) -> None:
        environment = _publisher_environment(
            receipt_path="nested/receipts/publisher.json",
            asset_root="nested/artifacts",
        )
        environment["GITHUB_SERVER_URL"] = "https://github.com/"
        environment["GITHUB_API_URL"] = "https://api.github.com/"
        config = publisher_module.PublisherConfig.from_environment(environment)
        self.assertEqual(config.api_origin, API_ORIGIN)
        self.assertEqual(config.upload_origin, UPLOAD_ORIGIN)
        self.assertEqual(config.receipt_path, Path("nested/receipts/publisher.json"))
        self.assertEqual(config.asset_root, Path("nested/artifacts"))

        rejected = (
            ("GITHUB_SERVER_URL", "https://github.example", "canonical GitHub.com"),
            ("GITHUB_API_URL", "https://api.github.example", "canonical GitHub.com"),
            ("RELEASE_RECEIPT_PATH", "/tmp/publisher.json", "stay relative"),
            ("RELEASE_RECEIPT_PATH", "../publisher.json", "stay relative"),
            ("RELEASE_ASSET_ROOT", "/tmp/artifacts", "stay relative"),
            ("RELEASE_ASSET_ROOT", "artifacts/../elsewhere", "stay relative"),
            ("RELEASE_NAME", f"Release {TAG}", "fixed GM2Godot tag title"),
            (
                "RELEASE_OWNERSHIP_RETRY_DELAY_SECONDS",
                "1.1",
                "between 0 and 1 second",
            ),
            (
                "RELEASE_OWNERSHIP_RETRY_DELAY_SECONDS",
                "not-a-number",
                "Invalid release ownership retry delay",
            ),
        )
        for variable, value, message in rejected:
            with self.subTest(rejected_variable=variable, value=value):
                candidate = _publisher_environment()
                candidate[variable] = value
                with self.assertRaisesRegex(ValueError, message):
                    publisher_module.PublisherConfig.from_environment(candidate)


class TestPublisherRecoveryReceipt(unittest.TestCase):
    def _run_main_with_fault(
        self,
        ordinal: int,
        fault: FaultKind | None,
        *,
        response_loss: bool = False,
    ) -> tuple[
        dict[str, object],
        str,
        SnapshottingTransport,
    ]:
        workspace = Path.cwd()
        with tempfile.TemporaryDirectory(
            prefix=".release-publisher-recovery-",
            dir=workspace,
        ) as temporary_directory:
            temporary_root = Path(temporary_directory)
            relative_root = temporary_root.relative_to(workspace)
            relative_asset_root = relative_root / "artifacts"
            relative_receipt_path = relative_root / "receipt/publisher.json"
            _write_release_assets(workspace / relative_asset_root)
            transport = SnapshottingTransport(
                workspace / relative_receipt_path,
                {} if fault is None else {ordinal: fault},
                response_loss_ordinal=ordinal if response_loss else None,
            )
            environment = _publisher_environment(
                receipt_path=str(relative_receipt_path),
                asset_root=str(relative_asset_root),
            )
            stderr = StringIO()
            with (
                patch.object(
                    publisher_module,
                    "HttpsTransport",
                    return_value=transport,
                ),
                redirect_stderr(stderr),
            ):
                result = publisher_module.main(environment)
            self.assertEqual(result, 1)
            receipt = cast(
                dict[str, object],
                json.loads((workspace / relative_receipt_path).read_text(encoding="utf-8")),
            )
            return receipt, stderr.getvalue(), transport

    def _assert_pending_snapshots_match_requests(
        self,
        transport: SnapshottingTransport,
        expected_ordinals: list[int],
    ) -> None:
        phases = {
            8: "create-tag-ref",
            9: "create-draft-release",
            15: f"upload-{ASSET_ORDER[0]}",
            21: f"upload-{ASSET_ORDER[1]}",
            27: f"upload-{ASSET_ORDER[2]}",
            33: f"upload-{ASSET_ORDER[3]}",
            39: f"upload-{ASSET_ORDER[4]}",
            45: f"upload-{ASSET_ORDER[5]}",
            51: f"upload-{ASSET_ORDER[6]}",
            57: "publish-owned-release",
        }
        self.assertEqual(
            sorted(transport.pre_mutation_receipts),
            expected_ordinals,
        )
        calls_by_ordinal = {call.ordinal: call for call in transport.calls}
        for mutation_index, ordinal in enumerate(expected_ordinals):
            with self.subTest(mutation_ordinal=ordinal):
                snapshot = transport.pre_mutation_receipts[ordinal]
                snapshot_intents = cast(
                    list[dict[str, object]],
                    snapshot["mutation_intents"],
                )
                self.assertEqual(len(snapshot_intents), mutation_index + 1)
                self.assertEqual(
                    [intent["state"] for intent in snapshot_intents],
                    ["accepted"] * mutation_index + ["pending"],
                )
                pending = snapshot_intents[-1]
                self.assertEqual(pending["phase"], phases[ordinal])
                self.assertEqual(snapshot["stage"], phases[ordinal])
                call = calls_by_ordinal[ordinal]
                self.assertEqual(pending["method"], call.method)
                endpoint = cast(str, pending["endpoint"])
                expected_url = endpoint if endpoint.startswith("https://") else API_ORIGIN + endpoint
                self.assertEqual(expected_url, call.url)

    def _run_main_with_persistent_missing_owned_match(
        self,
        gate_index: int,
    ) -> tuple[dict[str, object], str, VisibilityScriptedTransport]:
        workspace = Path.cwd()
        with tempfile.TemporaryDirectory(
            prefix=".release-publisher-visibility-",
            dir=workspace,
        ) as temporary_directory:
            temporary_root = Path(temporary_directory)
            relative_root = temporary_root.relative_to(workspace)
            relative_asset_root = relative_root / "artifacts"
            relative_receipt_path = relative_root / "receipt/publisher.json"
            _write_release_assets(workspace / relative_asset_root)
            transport = VisibilityScriptedTransport(
                gate_index,
                ("missing-owned",) * publisher_module.OWNED_DRAFT_VISIBILITY_SNAPSHOTS,
            )
            environment = _publisher_environment(
                receipt_path=str(relative_receipt_path),
                asset_root=str(relative_asset_root),
            )
            stderr = StringIO()
            with (
                patch.object(
                    publisher_module,
                    "HttpsTransport",
                    return_value=transport,
                ),
                redirect_stderr(stderr),
            ):
                result = publisher_module.main(environment)
            self.assertEqual(result, 1)
            receipt = cast(
                dict[str, object],
                json.loads((workspace / relative_receipt_path).read_text(encoding="utf-8")),
            )
            return receipt, stderr.getvalue(), transport

    def test_post_mutation_failure_persists_id_first_recovery_receipt(self) -> None:
        receipt, stderr, transport = self._run_main_with_fault(
            27,
            "upload-server-error",
        )

        self.assertEqual(receipt["stage"], "failed")
        self.assertEqual(receipt["tag"], TAG)
        self.assertEqual(receipt["target_sha"], TARGET_SHA)
        self.assertEqual(
            receipt["run"],
            {
                "id": "12345",
                "attempt": "2",
                "url": (f"https://github.com/{REPOSITORY}/actions/runs/12345/attempts/2"),
            },
        )

        failure = cast(dict[str, object], receipt["failure"])
        self.assertEqual(failure["phase"], "upload-GM2Godot-macos-arm64.dmg")
        self.assertEqual(failure["status"], 500)
        self.assertEqual(failure["request_id"], "request-027")
        self.assertIs(failure["ambiguous"], True)
        self.assertEqual(failure["owned_release_id"], OWNED_RELEASE_ID)
        self.assertEqual(failure["completed_asset_names"], list(ASSET_ORDER[:2]))

        release_receipt = cast(dict[str, object], receipt["release_receipt"])
        self.assertEqual(release_receipt["id"], OWNED_RELEASE_ID)
        tag_receipt = cast(dict[str, object], receipt["tag_receipt"])
        self.assertEqual(tag_receipt["ref"], f"refs/tags/{TAG}")
        self.assertEqual(tag_receipt["target_sha"], TARGET_SHA)
        asset_receipts = cast(list[dict[str, object]], receipt["asset_receipts"])
        self.assertEqual(
            [asset["name"] for asset in asset_receipts],
            list(ASSET_ORDER[:2]),
        )

        intents = cast(list[dict[str, object]], receipt["mutation_intents"])
        self.assertEqual(
            [intent["phase"] for intent in intents],
            [
                "create-tag-ref",
                "create-draft-release",
                f"upload-{ASSET_ORDER[0]}",
                f"upload-{ASSET_ORDER[1]}",
                f"upload-{ASSET_ORDER[2]}",
            ],
        )
        self.assertEqual(
            [intent["state"] for intent in intents],
            ["accepted", "accepted", "accepted", "accepted", "pending"],
        )
        pending = intents[-1]
        self.assertEqual(pending["owned_release_id"], OWNED_RELEASE_ID)
        self.assertEqual(pending["asset"], ASSET_ORDER[2])
        self.assertNotIn("status", pending)
        self.assertNotIn("request_id", pending)

        self.assertIn(str(OWNED_RELEASE_ID), stderr)
        self.assertIn(f"tags/{TAG}", stderr)
        run = cast(dict[str, object], receipt["run"])
        self.assertIn(str(run["url"]), stderr)
        self.assertIn("do not rerun, adopt, delete, or roll back", stderr)

        self._assert_pending_snapshots_match_requests(
            transport,
            [8, 9, 15, 21, 27],
        )

    def test_ambiguous_draft_creation_retains_tag_without_claiming_release(self) -> None:
        receipt, stderr, transport = self._run_main_with_fault(
            9,
            "release-transport-error",
        )

        failure = cast(dict[str, object], receipt["failure"])
        self.assertEqual(failure["phase"], "create-draft-release")
        self.assertIsNone(failure["status"])
        self.assertIsNone(failure["request_id"])
        self.assertIs(failure["ambiguous"], True)
        self.assertIsNone(failure["owned_release_id"])
        self.assertEqual(failure["completed_asset_names"], [])
        self.assertIsNone(receipt["release_receipt"])
        self.assertEqual(receipt["asset_receipts"], [])
        tag_receipt = cast(dict[str, object], receipt["tag_receipt"])
        self.assertEqual(tag_receipt["ref"], f"refs/tags/{TAG}")
        self.assertEqual(tag_receipt["target_sha"], TARGET_SHA)

        intents = cast(list[dict[str, object]], receipt["mutation_intents"])
        self.assertEqual(
            [intent["state"] for intent in intents],
            ["accepted", "pending"],
        )
        self._assert_pending_snapshots_match_requests(transport, [8, 9])

        self.assertIn(
            "Owned release ID: no validated 201 receipt; creation outcome may be unknown.",
            stderr,
        )
        self.assertIn(
            f"{API_ORIGIN}/repos/{REPOSITORY}/releases?per_page=100",
            stderr,
        )
        self.assertNotIn(f"releases/{OWNED_RELEASE_ID}", stderr)

    def test_ambiguous_publish_persists_full_owned_prefix_and_pending_patch(
        self,
    ) -> None:
        receipt, stderr, transport = self._run_main_with_fault(
            57,
            None,
            response_loss=True,
        )

        failure = cast(dict[str, object], receipt["failure"])
        self.assertEqual(failure["phase"], "publish-owned-release")
        self.assertIsNone(failure["status"])
        self.assertIsNone(failure["request_id"])
        self.assertIs(failure["ambiguous"], True)
        self.assertEqual(failure["owned_release_id"], OWNED_RELEASE_ID)
        self.assertEqual(failure["completed_asset_names"], list(ASSET_ORDER))

        release_receipt = cast(dict[str, object], receipt["release_receipt"])
        self.assertEqual(release_receipt["id"], OWNED_RELEASE_ID)
        asset_receipts = cast(list[dict[str, object]], receipt["asset_receipts"])
        self.assertEqual(
            [asset["name"] for asset in asset_receipts],
            list(ASSET_ORDER),
        )
        intents = cast(list[dict[str, object]], receipt["mutation_intents"])
        self.assertEqual(
            [intent["state"] for intent in intents],
            ["accepted"] * 9 + ["pending"],
        )
        pending = intents[-1]
        self.assertEqual(pending["phase"], "publish-owned-release")
        self.assertEqual(pending["method"], "PATCH")
        self.assertEqual(
            pending["endpoint"],
            f"/repos/{REPOSITORY}/releases/{OWNED_RELEASE_ID}",
        )

        publish_snapshot = transport.pre_mutation_receipts[57]
        snapshot_assets = cast(
            list[dict[str, object]],
            publish_snapshot["asset_receipts"],
        )
        self.assertEqual(
            [asset["name"] for asset in snapshot_assets],
            list(ASSET_ORDER),
        )
        self._assert_pending_snapshots_match_requests(
            transport,
            [8, 9, 15, 21, 27, 33, 39, 45, 51, 57],
        )
        self.assertIn(f"releases/{OWNED_RELEASE_ID}", stderr)

    def test_intel_upload_failure_records_exact_pending_asset_and_owned_prefix(self) -> None:
        for ordinal, asset_name, prefix_count, expected_ordinals in (
            (33, "GM2Godot-macos-x86_64.zip", 3, [8, 9, 15, 21, 27, 33]),
            (39, "GM2Godot-macos-x86_64.dmg", 4, [8, 9, 15, 21, 27, 33, 39]),
        ):
            with self.subTest(asset=asset_name):
                receipt, stderr, transport = self._run_main_with_fault(ordinal, "upload-server-error")
                failure = cast(dict[str, object], receipt["failure"])
                self.assertEqual(receipt["schema_version"], 1)
                self.assertEqual(receipt["stage"], "failed")
                self.assertEqual(failure["phase"], f"upload-{asset_name}")
                self.assertEqual(failure["status"], 500)
                self.assertIs(failure["ambiguous"], True)
                self.assertEqual(failure["owned_release_id"], OWNED_RELEASE_ID)
                self.assertEqual(failure["completed_asset_names"], list(ASSET_ORDER[:prefix_count]))
                intents = cast(list[dict[str, object]], receipt["mutation_intents"])
                self.assertEqual([item["state"] for item in intents], ["accepted"] * (prefix_count + 2) + ["pending"])
                self.assertEqual(intents[-1]["asset"], asset_name)
                self.assertEqual(intents[-1]["owned_release_id"], OWNED_RELEASE_ID)
                self.assertNotIn("status", intents[-1])
                self.assertEqual(len(transport.calls), ordinal)
                self.assertFalse(transport.published)
                self._assert_pending_snapshots_match_requests(transport, expected_ordinals)
                self.assertIn(f"releases/{OWNED_RELEASE_ID}", stderr)
                self.assertIn("do not rerun, adopt, delete, or roll back", stderr)

    def test_intel_upload_control_exceptions_leave_persisted_pending_intent(self) -> None:
        workspace = Path.cwd()
        for ordinal, asset_name, prefix_count, expected_ordinals in (
            (33, "GM2Godot-macos-x86_64.zip", 3, [8, 9, 15, 21, 27, 33]),
            (39, "GM2Godot-macos-x86_64.dmg", 4, [8, 9, 15, 21, 27, 33, 39]),
        ):
            for control in (KeyboardInterrupt("interrupted upload"), SystemExit(0), SystemExit(2)):
                with self.subTest(asset=asset_name, control=type(control).__name__, code=str(control)), tempfile.TemporaryDirectory(
                    prefix=".release-publisher-control-", dir=workspace
                ) as temporary_directory:
                    temporary_root = Path(temporary_directory)
                    relative_root = temporary_root.relative_to(workspace)
                    receipt_path = temporary_root / "receipt/publisher.json"
                    _write_release_assets(temporary_root / "artifacts")
                    transport = SnapshottingTransport(receipt_path, {})
                    original_request = transport.request

                    def controlled_request(
                        method: str,
                        url: str,
                        headers: Mapping[str, str],
                        *,
                        json_body: bytes | None = None,
                        file_body: publisher_module.FileSeal | None = None,
                    ) -> publisher_module.TransportResult:
                        result = original_request(method, url, headers, json_body=json_body, file_body=file_body)
                        if len(transport.calls) == ordinal:
                            raise control
                        return result

                    environment = _publisher_environment(
                        receipt_path=str(relative_root / "receipt/publisher.json"),
                        asset_root=str(relative_root / "artifacts"),
                    )
                    with (
                        patch.object(publisher_module, "HttpsTransport", return_value=transport),
                        patch.object(transport, "request", side_effect=controlled_request),
                        self.assertRaises(type(control)) as caught,
                    ):
                        publisher_module.main(environment)
                    self.assertIs(caught.exception, control)
                    receipt = cast(dict[str, object], json.loads(receipt_path.read_text(encoding="utf-8")))
                    self.assertEqual(receipt["schema_version"], 1)
                    self.assertEqual(receipt["stage"], f"upload-{asset_name}")
                    self.assertIsNone(receipt["failure"])
                    assets = cast(list[dict[str, object]], receipt["asset_receipts"])
                    self.assertEqual([item["name"] for item in assets], list(ASSET_ORDER[:prefix_count]))
                    intents = cast(list[dict[str, object]], receipt["mutation_intents"])
                    self.assertEqual([item["state"] for item in intents], ["accepted"] * (prefix_count + 2) + ["pending"])
                    self.assertEqual(intents[-1]["asset"], asset_name)
                    self.assertEqual(len(transport.calls), ordinal)
                    self.assertEqual(len(transport.uploaded), prefix_count + 1)
                    self.assertFalse(transport.published)
                    self._assert_pending_snapshots_match_requests(transport, expected_ordinals)

    def test_foreign_collision_diagnostics_name_owned_and_foreign_ids(self) -> None:
        receipt, stderr, _ = self._run_main_with_fault(
            13,
            "foreign-published-release",
        )

        failure = cast(dict[str, object], receipt["failure"])
        failure_message = cast(str, failure["message"])
        self.assertEqual(failure["phase"], "ownership-gate-0")
        self.assertEqual(failure["status"], 200)
        self.assertEqual(failure["request_id"], "request-013")
        self.assertIs(failure["ambiguous"], False)
        self.assertEqual(failure["owned_release_id"], OWNED_RELEASE_ID)
        self.assertEqual(failure["completed_asset_names"], [])
        self.assertEqual(receipt["asset_receipts"], [])
        self.assertIn(f"owned draft id={OWNED_RELEASE_ID}", failure_message)
        self.assertIn(f"published id={FOREIGN_RELEASE_ID}", failure_message)
        self.assertIn(f"owned draft id={OWNED_RELEASE_ID}", stderr)
        self.assertIn(f"published id={FOREIGN_RELEASE_ID}", stderr)
        self.assertIn(f"releases/{OWNED_RELEASE_ID}", stderr)
        self.assertNotIn(f"releases/{FOREIGN_RELEASE_ID}", stderr)

    def test_persistent_missing_owned_match_persists_owned_id_without_upload_intent(
        self,
    ) -> None:
        receipt, stderr, _ = self._run_main_with_persistent_missing_owned_match(0)

        self.assertEqual(receipt["stage"], "failed")
        failure = cast(dict[str, object], receipt["failure"])
        self.assertEqual(failure["phase"], "ownership-gate-0")
        self.assertIs(failure["ambiguous"], False)
        self.assertEqual(failure["owned_release_id"], OWNED_RELEASE_ID)
        self.assertEqual(failure["completed_asset_names"], [])
        intents = cast(list[dict[str, object]], receipt["mutation_intents"])
        self.assertEqual(
            [(intent["phase"], intent["state"]) for intent in intents],
            [
                ("create-tag-ref", "accepted"),
                ("create-draft-release", "accepted"),
            ],
        )
        self.assertEqual(receipt["asset_receipts"], [])
        observations = cast(list[dict[str, object]], receipt["observations"])
        visibility = [
            observation
            for observation in observations
            if str(observation["phase"]).startswith("ownership-gate-0-snapshot-")
        ]
        self.assertEqual(
            [observation["decision"] for observation in visibility],
            ["retry-empty"] * 6 + ["fail-empty-exhausted"],
        )
        self.assertEqual(
            [observation["listed_release_count"] for observation in visibility],
            [1] * publisher_module.OWNED_DRAFT_VISIBILITY_SNAPSHOTS,
        )
        self.assertIn("visibility did not converge", str(failure["message"]))
        self.assertIn(f"releases/{OWNED_RELEASE_ID}", stderr)
        self.assertNotIn(f"releases/{FOREIGN_RELEASE_ID}", stderr)

    def test_later_persistent_missing_owned_match_persists_completed_prefix(
        self,
    ) -> None:
        receipt, stderr, _ = self._run_main_with_persistent_missing_owned_match(3)

        self.assertEqual(receipt["stage"], "failed")
        failure = cast(dict[str, object], receipt["failure"])
        self.assertEqual(failure["phase"], "ownership-gate-3")
        self.assertIs(failure["ambiguous"], False)
        self.assertEqual(failure["owned_release_id"], OWNED_RELEASE_ID)
        self.assertEqual(
            failure["completed_asset_names"],
            list(ASSET_ORDER[:3]),
        )

        asset_receipts = cast(list[dict[str, object]], receipt["asset_receipts"])
        self.assertEqual(
            [asset["name"] for asset in asset_receipts],
            list(ASSET_ORDER[:3]),
        )
        intents = cast(list[dict[str, object]], receipt["mutation_intents"])
        self.assertEqual(
            [intent["phase"] for intent in intents],
            [
                "create-tag-ref",
                "create-draft-release",
                *(f"upload-{asset_name}" for asset_name in ASSET_ORDER[:3]),
            ],
        )
        self.assertEqual(
            [intent["state"] for intent in intents],
            ["accepted"] * 5,
        )

        observations = cast(list[dict[str, object]], receipt["observations"])
        visibility = [
            observation
            for observation in observations
            if str(observation["phase"]).startswith("ownership-gate-3-snapshot-")
        ]
        self.assertEqual(
            [observation["decision"] for observation in visibility],
            ["retry-empty"] * 6 + ["fail-empty-exhausted"],
        )
        for observation in visibility:
            self.assertEqual(observation["listed_release_count"], 1)
            self.assertEqual(
                observation["uploaded_asset_names"],
                list(ASSET_ORDER[:3]),
            )
        self.assertIn(f"releases/{OWNED_RELEASE_ID}", stderr)
        self.assertNotIn(f"releases/{FOREIGN_RELEASE_ID}", stderr)


if __name__ == "__main__":
    unittest.main()
