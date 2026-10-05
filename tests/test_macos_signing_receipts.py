"""UNEXECUTED credentialless gate fixtures; no fixture establishes Apple trust."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts.verify_macos_signing_receipts import (
    PublicationContext,
    ReceiptInput,
    ReceiptVerificationError,
    main,
    verify_publication_receipts,
)
from src.conversion.json_values import JsonObject, JsonValue, validate_json_value


@unittest.skipUnless(os.name == "posix", "publication gate uses real POSIX no-follow file bindings")
class TestMacSigningReceiptGate(unittest.TestCase):
    context: PublicationContext
    root: Path
    inputs: list[ReceiptInput]
    receipts: dict[str, JsonObject]

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.context = PublicationContext("a" * 40, "b" * 40, "1.2.3", 100, 2, 900, 100, 2, "ABCDEFGHIJ", "C" * 40, "push")
        self.inputs = []
        self.receipts = {}
        for architecture in ("arm64", "x86_64"):
            directory = self.root / architecture
            directory.mkdir()
            payloads: list[JsonValue] = []
            for extension in ("zip", "dmg"):
                name = f"GM2Godot-macos-{architecture}.{extension}"
                body = (f"fixture signed final {architecture} {extension}\n").encode()
                (directory / name).write_bytes(body)
                payloads.append(self.file_seal(directory / name))
            metadata: JsonObject = {
                "identifier": "land.infi.gm2godot", "short_version": "1.2.3", "build_version": "1.2.3",
                "minimum_system_version": "15.0", "plist_sha256": "d" * 64,
            }
            notary: JsonObject = {}
            prefixes = (("app", "1"), ("dmg", "2")) if architecture == "arm64" else (("app", "3"), ("dmg", "4"))
            for label, prefix in prefixes:
                identifier = f"{prefix * 8}-{prefix * 4}-{prefix * 4}-{prefix * 4}-{prefix * 12}"
                submitted_name = "app-notarization.zip" if label == "app" else f"GM2Godot-macos-{architecture}.dmg"
                submitted_body = (f"fixture pre-staple submitted {architecture} {label}\n").encode()
                submission: JsonObject = {"name": submitted_name, "size": len(submitted_body),
                                          "sha256": hashlib.sha256(submitted_body).hexdigest()}
                log: JsonObject = {"jobId": identifier, "status": "Accepted", "issues": None,
                                   "archiveFilename": submitted_name,
                                   "logFormatVersion": 1, "unrelatedAppleField": "forward service metadata"}
                path = directory / f"{label}-notary-log.json"
                self.write_json(path, log)
                notary[label] = {"id": identifier, "status": "Accepted", "submission": submission,
                                "log": self.file_seal(path)}
            gui: JsonObject = {
                "returncode": 0, "cleanup_successful": True, "exact_receipt": True,
                "receipt_mode": 0o600, "receipt_nlink": 1,
                "receipt_sha256": hashlib.sha256(b"GM2Godot packaged GUI ready\n").hexdigest(),
            }
            native: list[JsonValue] = [
                {"path": path, "architecture": architecture, "minimum_macos": [15, 0, 0], "filetype": filetype,
                 "mode": 0o755}
                for path, filetype in (("Contents/MacOS/GM2Godot", 2), ("Contents/Frameworks/library.dylib", 6))
            ]
            first = payloads[0]
            assert isinstance(first, dict)
            zip_hash = first["sha256"]
            report: JsonObject = {
                "schema_version": 1, "successful": True, "zip_sha256": zip_hash,
                "runtime": {"implementation": "CPython", "python_version": "3.12.10", "platform": "darwin",
                            "system": "Darwin", "machine": architecture, "translated": False},
                "bundle": {"metadata": metadata, "mach_o_files": native,
                           "symlinks": [{"path": "Contents/Frameworks/current", "target": "library.dylib"}]},
                "gui": gui, "source_app_gui_tested": False, "dmg_gui_tested": False,
            }
            self.write_json(directory / "signed-gui.json", report)
            code: list[JsonValue] = [
                {"path": path, "certificate_sha1": "C" * 40, "team_id": "ABCDEFGHIJ",
                 "authority": "Developer ID Application: Fixture (ABCDEFGHIJ)", "timestamp": "Oct 5, 2026 at 01:00:00",
                 "runtime": True, "signature_verified": True, "entitlements_verified_empty": True}
                for path in (".", "Contents/MacOS/GM2Godot", "Contents/Frameworks/library.dylib")
            ]
            assessment: JsonObject = {"accepted": True, "source": "Notarized Developer ID",
                                      "signature_verified": True, "ticket_valid": True}
            receipt: JsonObject = {
                "schema_version": 1, "successful": True, "purpose": "publication", "release_eligible": True,
                "repository": "Infiland/GM2Godot", "source": {"sha": "a" * 40, "tree": "b" * 40},
                "producer": {"run_id": 100, "run_attempt": 2, "workflow_id": 900, "event": "push", "branch": "main",
                             "head_sha": "a" * 40},
                "signing": {"run_id": 100, "run_attempt": 2, "event": "push", "branch": "main", "head_sha": "a" * 40},
                "architecture": architecture, "version": "1.2.3", "unsigned_payloads": payloads,
                "final_payloads": payloads,
                "metadata": {"metadata": metadata, "architecture": architecture, "macho_count": 2, "symlink_count": 1,
                             "maximum_macos": [15, 0, 0]},
                "developer_id": {"team_id": "ABCDEFGHIJ", "identity_sha1": "C" * 40, "nested_code": code},
                "notarization": notary, "assessments": {"zip_app": assessment, "dmg_app": assessment, "dmg": assessment},
                "signed_gui": {"successful": True, "architecture": architecture, "zip_sha256": zip_hash,
                               "report": self.file_seal(directory / "signed-gui.json"),
                               "gui": {"returncode": 0, "cleanup_successful": True, "exact_receipt": True},
                               "source_app_gui_tested": False, "dmg_gui_tested": False},
                "cleanup": {"keychain_deleted": True, "private_files_removed": True, "owned_mounts_detached": True},
            }
            self.receipts[architecture] = receipt
            path = directory / "signing.json"
            self.write_json(path, receipt)
            self.inputs.append(ReceiptInput(architecture, path, directory))

    @staticmethod
    def file_seal(path: Path) -> JsonObject:
        body = path.read_bytes()
        return {"name": path.name, "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}

    @staticmethod
    def write_json(path: Path, value: JsonObject) -> None:
        path.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding="utf-8")

    @staticmethod
    def fixture_json(body: bytes) -> JsonObject:
        raw: object = json.loads(body)
        value = validate_json_value(raw, source_path="credentialless test fixture")
        assert isinstance(value, dict)
        return value

    @staticmethod
    def fixture_child(row: JsonValue, key: str | int) -> JsonValue:
        if isinstance(key, int):
            assert isinstance(row, list)
            return row[key]
        assert isinstance(row, dict)
        return row[key]

    def changed(self, path: tuple[str | int, ...], value: JsonValue) -> None:
        row: JsonValue = self.receipts["arm64"]
        for key in path[:-1]:
            row = self.fixture_child(row, key)
        last = path[-1]
        if isinstance(last, int):
            assert isinstance(row, list)
            row[last] = value
        else:
            assert isinstance(row, dict)
            row[last] = value
        self.write_json(self.inputs[0].receipt, self.receipts["arm64"])

    def test_two_architecture_same_run_rerun_attestations_join_all_four_real_bodies(self) -> None:
        seals = verify_publication_receipts(tuple(reversed(self.inputs)), self.context)
        self.assertEqual(seals, verify_publication_receipts(
            self.inputs, replace(self.context, identity_sha1=self.context.identity_sha1.lower())
        ))
        self.assertEqual([seal.name for seal in seals], sorted(
            f"GM2Godot-macos-{architecture}.{extension}"
            for architecture in ("arm64", "x86_64") for extension in ("zip", "dmg")
        ))
        for seal in seals:
            architecture = "arm64" if "arm64" in seal.name else "x86_64"
            actual = (self.root / architecture / seal.name).read_bytes()
            self.assertEqual((seal.size, seal.sha256), (len(actual), hashlib.sha256(actual).hexdigest()))
        reused = self.root / "x86_64" / "app-notary-log.json"
        identifier = "11111111-1111-1111-1111-111111111111"
        self.write_json(reused, {"jobId": identifier, "status": "Accepted", "archiveFilename": "app-notarization.zip",
                                "issues": None})
        notarization = self.receipts["x86_64"]["notarization"]
        assert isinstance(notarization, dict)
        app = notarization["app"]
        assert isinstance(app, dict)
        app["id"] = identifier
        app["log"] = self.file_seal(reused)
        self.write_json(self.inputs[1].receipt, self.receipts["x86_64"])
        with self.assertRaisesRegex(ReceiptVerificationError, "reused across architectures"):
            verify_publication_receipts(self.inputs, self.context)

    def test_verification_only_and_wrong_source_attempt_or_publisher_context_reject_before_payload_access(self) -> None:
        original = self.inputs[0].receipt.read_bytes()
        cases: list[tuple[tuple[str | int, ...], JsonValue]] = [
            (("purpose",), "verification_only"), (("release_eligible",), False),
            (("source", "sha"), "e" * 40), (("producer", "run_attempt"), 1),
            (("signing", "event"), "workflow_dispatch"), (("signing", "run_id"), 101),
            (("producer", "workflow_id"), 901), (("successful",), 1),
        ]
        inaccessible = [replace(self.inputs[0], payload_directory=self.root / "absent"), self.inputs[1]]
        for path, value in cases:
            with self.subTest(path=path, value=value):
                self.changed(path, value)
                with self.assertRaises(ReceiptVerificationError):
                    verify_publication_receipts(inaccessible, self.context)
                self.inputs[0].receipt.write_bytes(original)
                self.receipts["arm64"] = self.fixture_json(original)
        with self.assertRaises(ReceiptVerificationError):
            verify_publication_receipts(self.inputs, replace(self.context, signing_run_attempt=3))

    def test_closed_schema_duplicate_json_native_types_and_proof_filename_collisions_fail(self) -> None:
        original = self.inputs[0].receipt.read_bytes()
        cases: list[tuple[tuple[str | int, ...], JsonValue]] = [
            (("extra",), "unused"), (("cleanup", "extra"), True), (("schema_version",), True),
            (("final_payloads", 0, "name"), "../GM2Godot-macos-arm64.zip"),
            (("notarization", "app", "log", "name"), "signed-gui.json"),
            (("notarization", "dmg", "log", "name"), "APP-NOTARY-LOG.json"),
        ]
        for path, value in cases:
            with self.subTest(path=path):
                self.changed(path, value)
                with self.assertRaises((ReceiptVerificationError, OSError)):
                    verify_publication_receipts(self.inputs, self.context)
                self.inputs[0].receipt.write_bytes(original)
                self.receipts["arm64"] = self.fixture_json(original)
        for content in (b'{"schema_version":1,"schema_version":1}', b'{"x":{"a":1,"a":2}}'):
            self.inputs[0].receipt.write_bytes(content)
            with self.assertRaisesRegex(ReceiptVerificationError, "duplicate JSON"):
                verify_publication_receipts(self.inputs, self.context)
        self.inputs[0].receipt.write_bytes(original)
        del self.receipts["arm64"]["cleanup"]
        self.write_json(self.inputs[0].receipt, self.receipts["arm64"])
        with self.assertRaisesRegex(ReceiptVerificationError, "missing or extra"):
            verify_publication_receipts(self.inputs, self.context)

    def test_final_full_body_change_truncation_and_symlink_substitution_block(self) -> None:
        path = self.root / "arm64" / "GM2Godot-macos-arm64.zip"
        original = path.read_bytes()
        for changed in (original[:-1], original[:-1] + b"X", original + b"tail"):
            with self.subTest(bytes=len(changed)):
                path.write_bytes(changed)
                with self.assertRaises(ReceiptVerificationError):
                    verify_publication_receipts(self.inputs, self.context)
        target = self.root / "outside.zip"
        target.write_bytes(original)
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(OSError):
            verify_publication_receipts(self.inputs, self.context)
        path.unlink()
        path.write_bytes(original)
        with self.assertRaises(ReceiptVerificationError):
            verify_publication_receipts([self.inputs[0], self.inputs[0]], self.context)

    def test_native_coverage_developer_id_tickets_and_cleanup_are_mandatory(self) -> None:
        original = self.inputs[0].receipt.read_bytes()
        cases: list[tuple[tuple[str | int, ...], JsonValue]] = [
            (("developer_id", "nested_code", 1, "authority"), "Apple Development: Fixture (ABCDEFGHIJ)"),
            (("developer_id", "nested_code", 1, "certificate_sha1"), "D" * 40),
            (("developer_id", "nested_code", 1, "team_id"), "OTHERTEAM1"),
            (("developer_id", "nested_code", 1, "timestamp"), "none"),
            (("developer_id", "nested_code", 1, "runtime"), False),
            (("developer_id", "nested_code", 1, "entitlements_verified_empty"), False),
            (("developer_id", "nested_code", 2, "path"), "Contents/Frameworks/other.dylib"),
            (("assessments", "zip_app", "ticket_valid"), False),
            (("assessments", "dmg", "accepted"), False),
            (("cleanup", "owned_mounts_detached"), False),
            (("metadata", "maximum_macos"), [16, 0, 0]),
            (("metadata", "macho_count"), 1),
        ]
        for path, value in cases:
            with self.subTest(path=path):
                self.changed(path, value)
                with self.assertRaises(ReceiptVerificationError):
                    verify_publication_receipts(self.inputs, self.context)
                self.inputs[0].receipt.write_bytes(original)
                self.receipts["arm64"] = self.fixture_json(original)

    def test_retained_notary_and_post_staple_gui_raws_must_hash_join_and_agree(self) -> None:
        directory = self.root / "arm64"
        app_log = directory / "app-notary-log.json"
        self.write_json(app_log, {"jobId": "1" * 8 + "-" + "1" * 4 + "-" + "1" * 4 + "-" + "1" * 4 + "-" + "1" * 12,
                                  "status": "Accepted", "archiveFilename": "app-notarization.zip",
                                  "issues": [{"message": "rejected nested code"}]})
        with self.assertRaisesRegex(ReceiptVerificationError, "full size/hash mismatch"):
            verify_publication_receipts(self.inputs, self.context)
        self.changed(("notarization", "app", "log"), self.file_seal(app_log))
        with self.assertRaisesRegex(ReceiptVerificationError, "reports issues"):
            verify_publication_receipts(self.inputs, self.context)
        report = directory / "signed-gui.json"
        original_log: JsonObject = {"jobId": "11111111-1111-1111-1111-111111111111", "status": "Accepted",
                                   "archiveFilename": "app-notarization.zip", "issues": []}
        self.write_json(app_log, original_log)
        self.changed(("notarization", "app", "log"), self.file_seal(app_log))
        raw = self.fixture_json(report.read_bytes())
        raw["zip_sha256"] = "e" * 64
        self.write_json(report, raw)
        self.changed(("signed_gui", "report"), self.file_seal(report))
        with self.assertRaisesRegex(ReceiptVerificationError, "GUI report zip_sha256"):
            verify_publication_receipts(self.inputs, self.context)
        arm_gui = self.receipts["arm64"]["signed_gui"]
        assert isinstance(arm_gui, dict)
        raw["zip_sha256"] = arm_gui["zip_sha256"]
        runtime = raw["runtime"]
        assert isinstance(runtime, dict)
        runtime["translated"] = True
        self.write_json(report, raw)
        self.changed(("signed_gui", "report"), self.file_seal(report))
        with self.assertRaisesRegex(ReceiptVerificationError, "GUI runtime translated"):
            verify_publication_receipts(self.inputs, self.context)

    def test_official_uppercase_job_id_optional_provider_fields_and_pre_staple_hash_binding(self) -> None:
        app_log = self.root / "arm64" / "app-notary-log.json"
        identifier = "2efe2717-52ef-43a5-96dc-0797e4ca1041"
        official: JsonObject = {
            "jobId": identifier.upper(), "status": "Accepted", "archiveFilename": "app-notarization.zip",
            "issues": [], "logFormatVersion": 1, "statusSummary": "Ready for distribution",
            "ticketContents": [], "uploadDate": "2026-10-05T01:00:00Z",
        }
        self.changed(("notarization", "app", "id"), identifier)
        self.write_json(app_log, official)
        self.changed(("notarization", "app", "log"), self.file_seal(app_log))
        self.assertEqual(len(verify_publication_receipts(self.inputs, self.context)), 4)
        notarization = self.receipts["arm64"]["notarization"]
        assert isinstance(notarization, dict)
        app = notarization["app"]
        assert isinstance(app, dict)
        submission = app["submission"]
        assert isinstance(submission, dict)
        submitted_hash = submission["sha256"]
        assert isinstance(submitted_hash, str)
        finals = self.receipts["arm64"]["final_payloads"]
        assert isinstance(finals, list)
        final_zip = finals[0]
        assert isinstance(final_zip, dict)
        self.assertNotEqual(submitted_hash, final_zip["sha256"])
        official["statusCode"] = 0
        official["sha256"] = submitted_hash.upper()
        self.write_json(app_log, official)
        self.changed(("notarization", "app", "log"), self.file_seal(app_log))
        self.assertEqual(len(verify_publication_receipts(self.inputs, self.context)), 4)
        cases: list[tuple[str, JsonValue, str]] = [
            ("jobId", "55555555-5555-5555-5555-555555555555", "notary log id"),
            ("archiveFilename", "GM2Godot-macos-arm64.zip", "archive filename"),
            ("sha256", final_zip["sha256"], "pre-staple submitted hash"),
            ("statusCode", True, "status code"),
            ("statusCode", 1, "status code"),
            ("issues", {}, "reports issues"),
            ("issues", False, "reports issues"),
            ("issues", "", "reports issues"),
            ("status", "In Progress", "notary log status"),
            ("jobId", 1, "notary log id"),
            ("jobId", "not-a-uuid", "notary log id"),
        ]
        for key, value, error in cases:
            with self.subTest(field=key, value=value):
                bad: JsonObject = dict(official)
                bad[key] = value
                self.write_json(app_log, bad)
                self.changed(("notarization", "app", "log"), self.file_seal(app_log))
                with self.assertRaisesRegex(ReceiptVerificationError, error):
                    verify_publication_receipts(self.inputs, self.context)

    def test_public_cli_malformed_json_normalizes_decoder_errors_without_traceback_or_success(self) -> None:
        context = self.context
        arguments = [
            "--arm64-receipt", str(self.inputs[0].receipt),
            "--arm64-payload-directory", str(self.root / "unavailable-payloads"),
            "--x86-64-receipt", str(self.inputs[1].receipt),
            "--x86-64-payload-directory", str(self.inputs[1].payload_directory),
            "--source-sha", context.source_sha, "--source-tree", context.source_tree,
            "--version", context.version, "--producer-run-id", str(context.producer_run_id),
            "--producer-run-attempt", str(context.producer_run_attempt),
            "--producer-workflow-id", str(context.producer_workflow_id),
            "--signing-run-id", str(context.signing_run_id),
            "--signing-run-attempt", str(context.signing_run_attempt),
            "--team-id", context.team_id, "--identity-sha1", context.identity_sha1,
            "--build-event", context.build_event,
        ]
        cases: list[tuple[bytes, ValueError | RecursionError | None, str]] = [
            (b'{"malformed":', None, "malformed JSON"),
            (b'{"malformed":', ValueError("decoder integer digit limit"), "malformed JSON"),
            (b'{"malformed":', RecursionError("decoder depth limit"), "malformed JSON"),
            (b'{"schema_version":1,"schema_version":1}', None, "duplicate JSON field"),
        ]
        for content, failure, expected in cases:
            with self.subTest(error=expected, decoder_failure=type(failure).__name__):
                self.inputs[0].receipt.write_bytes(content)
                output, errors = io.StringIO(), io.StringIO()
                decoder = (
                    patch("scripts.verify_macos_signing_receipts.json.loads", side_effect=failure)
                    if failure is not None else nullcontext()
                )
                with decoder, redirect_stdout(output), redirect_stderr(errors):
                    code = main(arguments)
                self.assertEqual(code, 1)
                self.assertEqual(output.getvalue(), "")
                lines = errors.getvalue().splitlines()
                self.assertEqual(len(lines), 1)
                self.assertTrue(lines[0].startswith("Mac signing receipt gate failed: "))
                self.assertIn(expected, lines[0])
                self.assertNotIn("Traceback", errors.getvalue())
                self.assertNotIn("PASS", errors.getvalue())


    def test_same_run_manual_dispatch_preserves_actual_event_and_rejects_stamped_push(self) -> None:
        context = replace(self.context, build_event="workflow_dispatch")
        for architecture, receipt in self.receipts.items():
            for role in ("producer", "signing"):
                identity = receipt[role]
                assert isinstance(identity, dict)
                identity["event"] = "workflow_dispatch"
            self.write_json(self.root / architecture / "signing.json", receipt)
        self.assertEqual(len(verify_publication_receipts(self.inputs, context)), 4)
        for role in ("producer", "signing"):
            with self.subTest(stamped_role=role):
                self.changed((role, "event"), "push")
                with self.assertRaisesRegex(ReceiptVerificationError, "event"):
                    verify_publication_receipts(self.inputs, context)
                self.changed((role, "event"), "workflow_dispatch")
        with self.assertRaisesRegex(ReceiptVerificationError, "event"):
            verify_publication_receipts(self.inputs, self.context)

    def test_public_cli_requires_explicit_trusted_build_event(self) -> None:
        context = self.context
        arguments = [
            "--arm64-receipt", str(self.inputs[0].receipt),
            "--arm64-payload-directory", str(self.inputs[0].payload_directory),
            "--x86-64-receipt", str(self.inputs[1].receipt),
            "--x86-64-payload-directory", str(self.inputs[1].payload_directory),
            "--source-sha", context.source_sha, "--source-tree", context.source_tree,
            "--version", context.version, "--producer-run-id", str(context.producer_run_id),
            "--producer-run-attempt", str(context.producer_run_attempt),
            "--producer-workflow-id", str(context.producer_workflow_id),
            "--signing-run-id", str(context.signing_run_id),
            "--signing-run-attempt", str(context.signing_run_attempt),
            "--team-id", context.team_id, "--identity-sha1", context.identity_sha1,
        ]
        for tail in ([], ["--build-event", "pull_request"]):
            with self.subTest(arguments=tail), redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as failed:
                    main([*arguments, *tail])
                self.assertEqual(failed.exception.code, 2)
                self.assertNotIn("Traceback", errors.getvalue())
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([*arguments, "--build-event", "push"]), 0)
        raw = self.fixture_json(output.getvalue().encode())
        self.assertEqual(raw["build_event"], "push")


if __name__ == "__main__":
    unittest.main()
