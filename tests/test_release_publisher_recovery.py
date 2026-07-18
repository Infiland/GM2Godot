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
    }


def _write_release_assets(root: Path) -> None:
    payloads = {
        "GM2Godot-windows.zip": b"PK\x03\x04GM2Godot Windows recovery test\n",
        "GM2Godot-macos.zip": b"PK\x03\x04GM2Godot macOS recovery test\n",
        "GM2Godot-macos.dmg": b"kolyGM2Godot macOS recovery test\n",
        "GM2Godot-linux.zip": b"PK\x03\x04GM2Godot Linux recovery test\n",
    }
    locations = {
        "GM2Godot-windows.zip": root / "GM2Godot-windows/GM2Godot-windows.zip",
        "GM2Godot-macos.zip": root / "GM2Godot-macos/GM2Godot-macos.zip",
        "GM2Godot-macos.dmg": root / "GM2Godot-macos/GM2Godot-macos.dmg",
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
    def test_accepts_only_main_branch_release_events_and_exact_sha(self) -> None:
        for event_name in ("push", "workflow_dispatch"):
            with self.subTest(accepted_event=event_name):
                environment = _publisher_environment()
                environment["GITHUB_EVENT_NAME"] = event_name
                config = publisher_module.PublisherConfig.from_environment(environment)
                self.assertEqual(config.target_sha, TARGET_SHA)
                self.assertEqual(config.release_name, RELEASE_NAME)
                self.assertEqual(
                    config.run_url,
                    f"https://github.com/{REPOSITORY}/actions/runs/12345/attempts/2",
                )

        rejected = (
            ("GITHUB_REF", "refs/tags/v0.7.17", "refs/heads/main"),
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
            45: "publish-owned-release",
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
        self.assertEqual(failure["phase"], "upload-GM2Godot-macos.dmg")
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
            45,
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
            ["accepted"] * 7 + ["pending"],
        )
        pending = intents[-1]
        self.assertEqual(pending["phase"], "publish-owned-release")
        self.assertEqual(pending["method"], "PATCH")
        self.assertEqual(
            pending["endpoint"],
            f"/repos/{REPOSITORY}/releases/{OWNED_RELEASE_ID}",
        )

        publish_snapshot = transport.pre_mutation_receipts[45]
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
            [8, 9, 15, 21, 27, 33, 39, 45],
        )
        self.assertIn(f"releases/{OWNED_RELEASE_ID}", stderr)

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


if __name__ == "__main__":
    unittest.main()
