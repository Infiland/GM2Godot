from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.conversion import anchored_artifacts as anchored_artifacts_module
from src.conversion.anchored_artifacts import VerifiedDirectory
from src.conversion.conversion_outcome import ConversionCounts, ConversionOutcome
from src.conversion.diagnostics import (
    DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
    DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
    DiagnosticCollector,
    capture_conversion_diagnostic_reports,
    invalidate_conversion_diagnostic_reports,
    publish_conversion_diagnostic_reports,
    restore_conversion_diagnostic_reports,
)
from tests.conversion_outcome_helpers import completed_conversion_step_ledger


def _directory_snapshot(path: Path) -> dict[str, tuple[int, int, int, bytes]]:
    snapshot: dict[str, tuple[int, int, int, bytes]] = {}
    for child in path.iterdir():
        child_stat = child.lstat()
        snapshot[child.name] = (
            child_stat.st_dev,
            child_stat.st_ino,
            stat.S_IMODE(child_stat.st_mode),
            child.read_bytes(),
        )
    return snapshot


def _write_report_pair(root: Path, json_content: bytes, markdown_content: bytes) -> None:
    json_path = root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
    markdown_path = root / DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_bytes(json_content)
    markdown_path.write_bytes(markdown_content)


def _replacement_report_directory(path: Path) -> dict[str, tuple[int, int, int, bytes]]:
    path.mkdir()
    (path / "conversion_diagnostics.json").write_bytes(b"replacement json\n")
    (path / "conversion_diagnostics.md").write_bytes(b"replacement markdown\n")
    (path / "sentinel.txt").write_bytes(b"unrelated sentinel\n")
    return _directory_snapshot(path)


class TestDiagnosticCollector(unittest.TestCase):
    def assertModeEqual(self, actual: int, expected: int) -> None:
        if os.name == "nt":
            self.assertEqual(
                bool(actual & stat.S_IWUSR),
                bool(expected & stat.S_IWUSR),
            )
            return
        self.assertEqual(actual, expected)

    def test_warning_log_wrapper_preserves_log_and_records_diagnostic(self) -> None:
        logs: list[str] = []
        diagnostics = DiagnosticCollector()
        wrapped_log = diagnostics.wrap_log_callback(logs.append)

        wrapped_log("Warning: Unsupported room layer emitted as placeholder.")
        wrapped_log("Converted sprite spr_player.")

        self.assertEqual(
            logs,
            [
                "Warning: Unsupported room layer emitted as placeholder.",
                "Converted sprite spr_player.",
            ],
        )
        recorded = diagnostics.diagnostics()
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].severity, "warning")
        self.assertEqual(recorded[0].code, "GM2GD-WARNING")

    def test_info_log_wrapper_records_informational_diagnostic(self) -> None:
        diagnostics = DiagnosticCollector()
        wrapped_log = diagnostics.wrap_log_callback(lambda _message: None)

        wrapped_log(
            "Info: Missing optional GameMaker metadata file; fallback metadata preserved."
        )

        recorded = diagnostics.diagnostics()
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].severity, "info")

    def test_transpile_failure_extracts_api_and_issue_metadata(self) -> None:
        diagnostics = DiagnosticCollector()

        diagnostic = diagnostics.add_transpile_failure(
            "Warning: Could not transpile GameMaker event code: "
            "GML API 'show_message_async' is unsupported; tracked by #507.",
            source_path="/tmp/project/objects/obj/Create_0.gml",
            resource="obj",
            resource_type="object",
            event="_ready",
        )

        self.assertEqual(diagnostic.api, "show_message_async")
        self.assertEqual(diagnostic.manifest_entry, "show_message_async")
        self.assertEqual(diagnostic.issue_number, 507)
        self.assertEqual(
            diagnostic.source_path,
            "/tmp/project/objects/obj/Create_0.gml",
        )

    def test_exact_structured_duplicates_are_deduped(self) -> None:
        diagnostics = DiagnosticCollector()
        for resource in ("snd_test", "snd_test", "snd_other"):
            diagnostics.add(
                "warning",
                "GM2GD-SOURCE-PATH-REJECTED",
                "Warning: Rejected GameMaker source path '../outside.wav'.",
                source_path="sounds/snd_test/snd_test.yy",
                resource=resource,
                resource_type="sound",
                manifest_entry="soundFile",
            )

        self.assertEqual(len(diagnostics.diagnostics()), 2)

    def test_reports_are_deterministic_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            diagnostics = DiagnosticCollector()
            diagnostics.add(
                "warning",
                "GM2GD-RESOURCE-UNSUPPORTED",
                "Unsupported GameMaker room asset type GMREffectLayer.",
                source_path="/tmp/project/rooms/r_main/r_main.yy",
                resource="r_main",
                resource_type="room",
                issue_number=590,
            )

            json_path, markdown_path = diagnostics.write_reports(tmp_dir)

            self.assertEqual(
                json_path,
                os.path.join(
                    os.path.abspath(tmp_dir),
                    DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
                ),
            )
            data = json.loads(Path(json_path).read_text(encoding="utf-8"))
            markdown = Path(markdown_path).read_text(encoding="utf-8")
            self.assertEqual(data["summary"]["warning"], 1)
            self.assertEqual(
                data["diagnostics"][0]["code"],
                "GM2GD-RESOURCE-UNSUPPORTED",
            )
            self.assertIn("GM2Godot Conversion Diagnostics", markdown)
            self.assertIn("GM2GD-RESOURCE-UNSUPPORTED", markdown)

    def test_report_schema_is_unchanged_without_conversion_outcome(self) -> None:
        self.assertEqual(
            set(DiagnosticCollector().to_json_dict()),
            {"summary", "diagnostics"},
        )

    def test_reports_include_explicit_conversion_outcome_when_set(self) -> None:
        diagnostics = DiagnosticCollector()
        outcome = ConversionOutcome(
            state="partial",
            steps=completed_conversion_step_ledger(("sprites",)),
            resources=ConversionCounts(
                requested=2,
                executed=2,
                completed=1,
                skipped=1,
            ),
        )
        diagnostics.set_outcome(outcome)

        self.assertEqual(diagnostics.to_json_dict()["outcome"], outcome.to_dict())
        self.assertIn(
            "Conversion outcome: `partial`",
            diagnostics.to_markdown(),
        )

    def test_snapshot_captures_absent_pair_and_both_directory_identities(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot = capture_conversion_diagnostic_reports(tmp_dir)

            root_stat = os.stat(tmp_dir, follow_symlinks=False)
            report_directory = Path(tmp_dir) / "gm2godot"
            directory_stat = report_directory.stat()
            self.assertEqual(
                snapshot.root_identity,
                (root_stat.st_dev, root_stat.st_ino),
            )
            self.assertEqual(
                snapshot.directory_identity,
                (directory_stat.st_dev, directory_stat.st_ino),
            )
            self.assertIsNone(snapshot.json_report.content)
            self.assertIsNone(snapshot.json_report.fingerprint)
            self.assertIsNone(snapshot.markdown_report.content)
            self.assertIsNone(snapshot.markdown_report.fingerprint)

    def test_snapshot_captures_exact_bytes_modes_and_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            json_path = root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
            markdown_path = root / DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH
            _write_report_pair(root, b"old json\x00\xff\n", b"old markdown\r\n")
            json_path.chmod(0o640)
            markdown_path.chmod(0o600)

            snapshot = capture_conversion_diagnostic_reports(root)

            for path, content, mode, captured in (
                (json_path, b"old json\x00\xff\n", 0o640, snapshot.json_report),
                (
                    markdown_path,
                    b"old markdown\r\n",
                    0o600,
                    snapshot.markdown_report,
                ),
            ):
                self.assertEqual(captured.content, content)
                self.assertIsNotNone(captured.fingerprint)
                assert captured.fingerprint is not None
                path_stat = path.stat()
                self.assertEqual(
                    captured.fingerprint.identity,
                    (path_stat.st_dev, path_stat.st_ino),
                )
                self.assertEqual(
                    captured.fingerprint.sha256,
                    hashlib.sha256(content).hexdigest(),
                )
                self.assertModeEqual(captured.mode or 0, mode)

    def test_publish_receipt_proves_pair_and_helper_matches_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            diagnostics = DiagnosticCollector()
            diagnostics.add("warning", "GM2GD-TEST", "receipt sentinel")

            receipt = publish_conversion_diagnostic_reports(tmp_dir, diagnostics)

            root_stat = os.stat(tmp_dir, follow_symlinks=False)
            directory_stat = os.stat(
                os.path.join(tmp_dir, "gm2godot"),
                follow_symlinks=False,
            )
            self.assertEqual(
                receipt.root_identity,
                (root_stat.st_dev, root_stat.st_ino),
            )
            self.assertEqual(
                receipt.directory_identity,
                (directory_stat.st_dev, directory_stat.st_ino),
            )
            for path, fingerprint in (
                (receipt.json_path, receipt.json_report),
                (receipt.markdown_path, receipt.markdown_report),
            ):
                content = Path(path).read_bytes()
                path_stat = os.stat(path, follow_symlinks=False)
                self.assertEqual(
                    fingerprint.identity,
                    (path_stat.st_dev, path_stat.st_ino),
                )
                self.assertEqual(
                    fingerprint.sha256,
                    hashlib.sha256(content).hexdigest(),
                )

    def test_restore_reinstates_exact_present_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            json_path = root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
            markdown_path = root / DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH
            _write_report_pair(root, b"trusted json\x00\n", b"trusted markdown\r\n")
            json_path.chmod(0o640)
            markdown_path.chmod(0o600)
            snapshot = capture_conversion_diagnostic_reports(root)
            receipt = DiagnosticCollector().publish_reports(root)

            restore_conversion_diagnostic_reports(root, snapshot, receipt)

            self.assertEqual(json_path.read_bytes(), b"trusted json\x00\n")
            self.assertEqual(markdown_path.read_bytes(), b"trusted markdown\r\n")
            self.assertModeEqual(stat.S_IMODE(json_path.stat().st_mode), 0o640)
            self.assertModeEqual(
                stat.S_IMODE(markdown_path.stat().st_mode),
                0o600,
            )
            self.assertEqual(
                sorted(path.name for path in json_path.parent.iterdir()),
                ["conversion_diagnostics.json", "conversion_diagnostics.md"],
            )

    def test_restore_reinstates_absent_and_mixed_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as absent_dir:
            snapshot = capture_conversion_diagnostic_reports(absent_dir)
            receipt = DiagnosticCollector().publish_reports(absent_dir)
            restore_conversion_diagnostic_reports(absent_dir, snapshot, receipt)
            self.assertFalse(Path(receipt.json_path).exists())
            self.assertFalse(Path(receipt.markdown_path).exists())

        with tempfile.TemporaryDirectory() as mixed_dir:
            root = Path(mixed_dir)
            json_path = root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
            json_path.parent.mkdir()
            json_path.write_bytes(b"trusted json only\n")
            json_path.chmod(0o640)
            snapshot = capture_conversion_diagnostic_reports(root)
            receipt = DiagnosticCollector().publish_reports(root)
            restore_conversion_diagnostic_reports(root, snapshot, receipt)
            self.assertEqual(json_path.read_bytes(), b"trusted json only\n")
            self.assertFalse(Path(receipt.markdown_path).exists())
            self.assertModeEqual(stat.S_IMODE(json_path.stat().st_mode), 0o640)

    def test_old_baseline_can_restore_over_latest_matching_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_report_pair(root, b"trusted json\n", b"trusted markdown\n")
            baseline = capture_conversion_diagnostic_reports(root)
            first = DiagnosticCollector()
            first.add("warning", "GM2GD-FIRST", "first rewrite")
            first.publish_reports(root)
            second = DiagnosticCollector()
            second.add("error", "GM2GD-SECOND", "second rewrite")
            latest_receipt = second.publish_reports(root)

            restore_conversion_diagnostic_reports(root, baseline, latest_receipt)

            self.assertEqual(
                (root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH).read_bytes(),
                b"trusted json\n",
            )
            self.assertEqual(
                (root / DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH).read_bytes(),
                b"trusted markdown\n",
            )

    def test_restore_refuses_changed_or_replaced_receipt_targets(self) -> None:
        for case in ("content", "identity", "mode"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                baseline = capture_conversion_diagnostic_reports(root)
                receipt = DiagnosticCollector().publish_reports(root)
                json_path = Path(receipt.json_path)
                original = json_path.read_bytes()
                if case == "content":
                    json_path.write_bytes(bytes((original[0] ^ 1,)) + original[1:])
                elif case == "identity":
                    replacement_path = json_path.with_suffix(".replacement")
                    replacement_path.write_bytes(original)
                    replacement_path.chmod(receipt.json_report.mode)
                    os.replace(replacement_path, json_path)
                else:
                    if os.name == "nt":
                        self.skipTest("Exact POSIX mode drift is unavailable")
                    json_path.chmod(receipt.json_report.mode ^ stat.S_IXUSR)

                with self.assertRaisesRegex(OSError, "changed"):
                    restore_conversion_diagnostic_reports(root, baseline, receipt)

                self.assertTrue(json_path.exists())
                self.assertTrue(Path(receipt.markdown_path).exists())

    def test_restore_validates_root_and_report_directory_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            baseline = capture_conversion_diagnostic_reports(root)
            receipt = DiagnosticCollector().publish_reports(root)

            for field in ("root_identity", "directory_identity"):
                with self.subTest(field=field):
                    identity = getattr(receipt, field)
                    forged = replace(
                        receipt,
                        **{field: (identity[0], identity[1] + 1)},
                    )
                    with self.assertRaisesRegex(ValueError, "directories do not match"):
                        restore_conversion_diagnostic_reports(
                            root,
                            baseline,
                            forged,
                        )

    def test_restore_refuses_forged_snapshot_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_report_pair(root, b"trusted json\n", b"trusted markdown\n")
            baseline = capture_conversion_diagnostic_reports(root)
            receipt = DiagnosticCollector().publish_reports(root)
            forged = replace(
                baseline,
                json_report=replace(
                    baseline.json_report,
                    content=b"tampered baseline\n",
                ),
            )

            with self.assertRaisesRegex(ValueError, "does not match"):
                restore_conversion_diagnostic_reports(root, forged, receipt)

            self.assertEqual(
                Path(receipt.json_path).read_bytes(),
                json.dumps(
                    DiagnosticCollector().to_json_dict(),
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8")
                + b"\n",
            )

    def test_restore_failure_rolls_back_to_original_receipt_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_report_pair(root, b"trusted json\n", b"trusted markdown\n")
            baseline = capture_conversion_diagnostic_reports(root)
            diagnostics = DiagnosticCollector()
            diagnostics.add("error", "GM2GD-NEW", "new receipt")
            receipt = diagnostics.publish_reports(root)
            published = (
                Path(receipt.json_path).read_bytes(),
                Path(receipt.markdown_path).read_bytes(),
            )
            failures = 0

            def fail_after_first_restore_commit(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal failures
                if (
                    phase == "after_commit"
                    and name == "conversion_diagnostics.md"
                    and failures == 0
                ):
                    failures += 1
                    raise OSError("injected restore failure")

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_after_first_restore_commit,
                ),
                self.assertRaisesRegex(OSError, "injected restore failure"),
            ):
                restore_conversion_diagnostic_reports(root, baseline, receipt)

            self.assertEqual(Path(receipt.json_path).read_bytes(), published[0])
            self.assertEqual(Path(receipt.markdown_path).read_bytes(), published[1])
            restore_conversion_diagnostic_reports(root, baseline, receipt)

    def test_external_report_root_chain_is_synced_before_descent(self) -> None:
        with tempfile.TemporaryDirectory() as container:
            container_path = Path(container)
            report_root = container_path / "one" / "two" / "reports"
            sync_paths: list[str] = []
            real_sync = VerifiedDirectory.sync

            def record_sync(binding: VerifiedDirectory) -> None:
                sync_paths.append(os.path.abspath(binding.path))
                real_sync(binding)

            with patch.object(
                VerifiedDirectory,
                "sync",
                autospec=True,
                side_effect=record_sync,
            ):
                DiagnosticCollector().publish_reports(report_root)

            self.assertEqual(
                sync_paths[:4],
                [
                    os.path.abspath(container),
                    os.path.abspath(container_path / "one"),
                    os.path.abspath(container_path / "one" / "two"),
                    os.path.abspath(report_root),
                ],
            )
            self.assertTrue(
                (report_root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH).is_file()
            )

    def test_external_root_creation_retry_repeats_failed_parent_sync(self) -> None:
        with tempfile.TemporaryDirectory() as container:
            report_parent = Path(container) / "one" / "two"
            report_root = report_parent / "reports"
            real_sync = VerifiedDirectory.sync
            failed = False

            def fail_report_root_parent_sync(binding: VerifiedDirectory) -> None:
                nonlocal failed
                if (
                    not failed
                    and os.path.abspath(binding.path)
                    == os.path.abspath(report_parent)
                ):
                    failed = True
                    raise OSError("injected external parent sync failure")
                real_sync(binding)

            with (
                patch.object(
                    VerifiedDirectory,
                    "sync",
                    autospec=True,
                    side_effect=fail_report_root_parent_sync,
                ),
                self.assertRaisesRegex(OSError, "external parent sync failure"),
            ):
                DiagnosticCollector().publish_reports(report_root)

            self.assertTrue(report_root.is_dir())
            self.assertFalse((report_root / "gm2godot").exists())
            retry_sync_paths: list[str] = []

            def record_retry(binding: VerifiedDirectory) -> None:
                retry_sync_paths.append(os.path.abspath(binding.path))
                real_sync(binding)

            with patch.object(
                VerifiedDirectory,
                "sync",
                autospec=True,
                side_effect=record_retry,
            ):
                DiagnosticCollector().publish_reports(report_root)

            self.assertGreaterEqual(len(retry_sync_paths), 2)
            self.assertEqual(
                retry_sync_paths[:2],
                [
                    os.path.abspath(report_parent),
                    os.path.abspath(report_root),
                ],
            )

    def test_staging_failure_leaves_no_new_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            def fail_json_stage(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                if phase == "before_stage" and name == "conversion_diagnostics.json":
                    raise OSError("injected JSON staging failure")

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_json_stage,
                ),
                self.assertRaisesRegex(OSError, "JSON staging failure"),
            ):
                DiagnosticCollector().publish_reports(root)

            self.assertEqual(list((root / "gm2godot").iterdir()), [])

    def test_pair_commits_markdown_then_json_and_rolls_back_second_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_report_pair(root, b"old json\n", b"old markdown\n")
            commits: list[str] = []

            def fail_json_commit(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                if phase != "before_commit" or name is None:
                    return
                commits.append(name)
                if name == "conversion_diagnostics.json":
                    raise OSError("injected JSON commit failure")

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_json_commit,
                ),
                self.assertRaisesRegex(OSError, "JSON commit failure"),
            ):
                DiagnosticCollector().publish_reports(root)

            self.assertEqual(
                commits,
                [
                    "conversion_diagnostics.md",
                    "conversion_diagnostics.json",
                    "conversion_diagnostics.md",
                ],
            )
            self.assertEqual(
                (root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH).read_bytes(),
                b"old json\n",
            )
            self.assertEqual(
                (root / DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH).read_bytes(),
                b"old markdown\n",
            )

    def test_cleanup_durability_failure_after_commit_keeps_valid_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_report_pair(root, b"old json\n", b"old markdown\n")
            failures = 0

            def fail_cleanup_sync(
                phase: str,
                _directory_path: str,
                _name: str | None,
            ) -> None:
                nonlocal failures
                if phase == "before_cleanup_durability":
                    failures += 1
                    raise OSError("injected cleanup durability failure")

            with patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=fail_cleanup_sync,
            ):
                receipt = DiagnosticCollector().publish_reports(root)

            self.assertEqual(failures, 1)
            self.assertEqual(
                hashlib.sha256(Path(receipt.json_path).read_bytes()).hexdigest(),
                receipt.json_report.sha256,
            )
            self.assertEqual(
                sorted(path.name for path in (root / "gm2godot").iterdir()),
                ["conversion_diagnostics.json", "conversion_diagnostics.md"],
            )

    def test_cleanup_propagates_keyboard_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_report_pair(root, b"old json\n", b"old markdown\n")
            real_unlink = os.unlink

            def interrupt_backup_cleanup(
                path: str | bytes,
                *,
                dir_fd: int | None = None,
            ) -> None:
                if os.fsdecode(path).endswith(".backup"):
                    raise KeyboardInterrupt("injected cleanup interrupt")
                real_unlink(path, dir_fd=dir_fd)

            with (
                patch(
                    "src.conversion.anchored_artifacts.os.unlink",
                    side_effect=interrupt_backup_cleanup,
                ),
                self.assertRaisesRegex(KeyboardInterrupt, "cleanup interrupt"),
            ):
                DiagnosticCollector().publish_reports(root)

    def test_rollback_failure_preserves_verified_previous_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_report_pair(root, b"old json\n", b"old markdown\n")
            rolling_back = False

            def fail_publish_and_rollback(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal rolling_back
                if (
                    phase == "before_commit"
                    and name == "conversion_diagnostics.json"
                    and not rolling_back
                ):
                    rolling_back = True
                    raise OSError("injected JSON publication failure")
                if (
                    rolling_back
                    and phase == "before_commit"
                    and name == "conversion_diagnostics.md"
                ):
                    raise OSError("injected Markdown rollback failure")

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_publish_and_rollback,
                ),
                self.assertRaisesRegex(
                    OSError,
                    "JSON publication failure",
                ) as raised,
            ):
                DiagnosticCollector().publish_reports(root)

            notes = getattr(raised.exception, "__notes__", ())
            self.assertTrue(
                any("verified recovery artifact preserved" in note for note in notes)
            )
            retained = [
                path
                for path in (root / "gm2godot").iterdir()
                if path.name not in {
                    "conversion_diagnostics.json",
                    "conversion_diagnostics.md",
                }
            ]
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0].read_bytes(), b"old markdown\n")

    def test_reports_refuse_redirects_and_nonregular_targets(self) -> None:
        with tempfile.TemporaryDirectory() as container:
            container_path = Path(container)
            outside = container_path / "outside"
            outside.mkdir()
            root_link = container_path / "root-link"
            try:
                root_link.symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")
            with self.assertRaisesRegex(OSError, "redirected"):
                DiagnosticCollector().publish_reports(root_link)
            self.assertEqual(list(outside.iterdir()), [])

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            outside = root / "outside"
            outside.mkdir()
            report_directory = root / "gm2godot"
            report_directory.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(OSError, "redirected"):
                DiagnosticCollector().publish_reports(root)
            self.assertEqual(list(outside.iterdir()), [])

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            report_path = root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
            report_path.parent.mkdir()
            outside_report = root / "outside.json"
            outside_report.write_bytes(b"outside\n")
            report_path.symlink_to(outside_report)
            with self.assertRaisesRegex(OSError, "non-regular"):
                DiagnosticCollector().publish_reports(root)
            self.assertEqual(outside_report.read_bytes(), b"outside\n")

            report_path.unlink()
            if hasattr(os, "mkfifo"):
                os.mkfifo(report_path)
                with self.assertRaisesRegex(OSError, "non-regular"):
                    DiagnosticCollector().publish_reports(root)

    def test_reports_replace_hardlinks_without_mutating_referents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            report_directory = root / "gm2godot"
            report_directory.mkdir()
            external_json = root / "external.json"
            external_markdown = root / "external.md"
            external_json.write_bytes(b"external json\n")
            external_markdown.write_bytes(b"external markdown\n")
            try:
                os.link(
                    external_json,
                    root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH,
                )
                os.link(
                    external_markdown,
                    root / DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH,
                )
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Hard links are unavailable: {error}")

            DiagnosticCollector().publish_reports(root)

            self.assertEqual(external_json.read_bytes(), b"external json\n")
            self.assertEqual(external_markdown.read_bytes(), b"external markdown\n")
            self.assertNotEqual(
                (root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH).stat().st_ino,
                external_json.stat().st_ino,
            )

    def test_new_private_modes_and_existing_exact_modes_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch.object(
                anchored_artifacts_module.os,
                "fchmod",
                side_effect=AssertionError("os.fchmod must not be called"),
                create=True,
            ):
                receipt = DiagnosticCollector().publish_reports(root)
            self.assertTrue(Path(receipt.json_path).is_file())
            self.assertModeEqual(
                stat.S_IMODE(Path(receipt.json_path).stat().st_mode),
                0o600,
            )

        if os.name == "nt" or not callable(getattr(os, "fchmod", None)):
            return
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_report_pair(root, b"old json\n", b"old markdown\n")
            json_path = root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
            markdown_path = root / DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH
            json_path.chmod(0o4750)
            markdown_path.chmod(0o2750)
            if (
                stat.S_IMODE(json_path.stat().st_mode) != 0o4750
                or stat.S_IMODE(markdown_path.stat().st_mode) != 0o2750
            ):
                self.skipTest("Filesystem does not preserve set-ID modes")

            DiagnosticCollector().publish_reports(root)

            self.assertEqual(stat.S_IMODE(json_path.stat().st_mode), 0o4750)
            self.assertEqual(stat.S_IMODE(markdown_path.stat().st_mode), 0o2750)

    def test_modeled_windows_readonly_pair_survives_publish_restore_and_rollback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            json_path = root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
            markdown_path = root / DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH
            _write_report_pair(root, b"readonly json\n", b"readonly markdown\n")
            json_path.chmod(0o444)
            markdown_path.chmod(0o444)

            with patch(
                "src.conversion.anchored_artifacts._is_windows_platform",
                return_value=True,
            ):
                snapshot = capture_conversion_diagnostic_reports(root)
                receipt = DiagnosticCollector().publish_reports(root)
                self.assertFalse(
                    stat.S_IMODE(json_path.stat().st_mode) & stat.S_IWUSR
                )
                self.assertFalse(
                    stat.S_IMODE(markdown_path.stat().st_mode) & stat.S_IWUSR
                )
                restore_conversion_diagnostic_reports(root, snapshot, receipt)

            self.assertEqual(json_path.read_bytes(), b"readonly json\n")
            self.assertEqual(markdown_path.read_bytes(), b"readonly markdown\n")
            self.assertFalse(stat.S_IMODE(json_path.stat().st_mode) & stat.S_IWUSR)
            self.assertFalse(
                stat.S_IMODE(markdown_path.stat().st_mode) & stat.S_IWUSR
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            json_path = root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH
            markdown_path = root / DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH
            _write_report_pair(root, b"readonly json\n", b"readonly markdown\n")
            json_path.chmod(0o444)
            markdown_path.chmod(0o444)

            def fail_json_commit(
                phase: str,
                _directory_path: str,
                name: str | None,
            ) -> None:
                if phase == "before_commit" and name == "conversion_diagnostics.json":
                    raise OSError("injected readonly pair failure")

            with (
                patch(
                    "src.conversion.anchored_artifacts._is_windows_platform",
                    return_value=True,
                ),
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_json_commit,
                ),
                self.assertRaisesRegex(OSError, "readonly pair failure"),
            ):
                DiagnosticCollector().publish_reports(root)

            self.assertEqual(json_path.read_bytes(), b"readonly json\n")
            self.assertEqual(markdown_path.read_bytes(), b"readonly markdown\n")
            self.assertFalse(stat.S_IMODE(json_path.stat().st_mode) & stat.S_IWUSR)
            self.assertFalse(
                stat.S_IMODE(markdown_path.stat().st_mode) & stat.S_IWUSR
            )

    def test_invalidation_is_best_effort_for_both_bound_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_report_pair(root, b"stale json\n", b"stale markdown\n")
            real_unlink = VerifiedDirectory.unlink

            def fail_json_unlink(
                binding: VerifiedDirectory,
                name: str,
                *,
                expected_identity: tuple[int, int],
            ) -> BaseException | None:
                if name == "conversion_diagnostics.json":
                    raise PermissionError("json is locked")
                return real_unlink(
                    binding,
                    name,
                    expected_identity=expected_identity,
                )

            with patch.object(
                VerifiedDirectory,
                "unlink",
                autospec=True,
                side_effect=fail_json_unlink,
            ):
                invalidate_conversion_diagnostic_reports(root)

            self.assertTrue(
                (root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH).exists()
            )
            self.assertFalse(
                (root / DIAGNOSTIC_REPORT_MARKDOWN_RELATIVE_PATH).exists()
            )
            invalidate_conversion_diagnostic_reports(root)
            self.assertFalse(
                (root / DIAGNOSTIC_REPORT_JSON_RELATIVE_PATH).exists()
            )

    @unittest.skipUnless(os.name == "posix", "POSIX relocation semantics required")
    def test_publish_never_mutates_physical_replacement_at_each_pair_phase(
        self,
    ) -> None:
        cases = (
            ("before_stage", "conversion_diagnostics.md"),
            ("before_backup", "conversion_diagnostics.md"),
            ("before_backup", "conversion_diagnostics.json"),
            ("before_commit", "conversion_diagnostics.md"),
            ("before_commit", "conversion_diagnostics.json"),
            ("before_durability", "conversion_diagnostics.md"),
            ("before_durability", "conversion_diagnostics.json"),
            ("before_sync", None),
            ("before_cleanup", None),
        )
        for index, (selected_phase, selected_name) in enumerate(cases):
            with self.subTest(phase=selected_phase, name=selected_name):
                temp_dir = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, temp_dir, True)
                root = temp_dir / f"project-{index}"
                root.mkdir()
                _write_report_pair(root, b"old json\n", b"old markdown\n")
                report_directory = root / "gm2godot"
                parked = root / "gm2godot.parked"
                swapped = False
                replacement_before: dict[str, tuple[int, int, int, bytes]] = {}

                def replace_directory(
                    phase: str,
                    directory_path: str,
                    name: str | None,
                ) -> None:
                    nonlocal swapped, replacement_before
                    if (
                        swapped
                        or phase != selected_phase
                        or name != selected_name
                        or os.path.abspath(directory_path)
                        != os.path.abspath(report_directory)
                    ):
                        return
                    swapped = True
                    os.rename(report_directory, parked)
                    replacement_before = _replacement_report_directory(
                        report_directory
                    )

                with (
                    patch(
                        "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                        side_effect=replace_directory,
                    ),
                    self.assertRaises(OSError),
                ):
                    DiagnosticCollector().publish_reports(root)

                self.assertTrue(swapped)
                self.assertEqual(
                    _directory_snapshot(report_directory),
                    replacement_before,
                )

    @unittest.skipUnless(os.name == "posix", "POSIX relocation semantics required")
    def test_restore_displacement_stays_bound_after_physical_replacement(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_report_pair(root, b"old json\n", b"old markdown\n")
            snapshot = capture_conversion_diagnostic_reports(root)
            receipt = DiagnosticCollector().publish_reports(root)
            report_directory = root / "gm2godot"
            parked = root / "gm2godot.parked"
            replacement_before: dict[str, tuple[int, int, int, bytes]] = {}
            swapped = False

            def replace_before_displacement(
                phase: str,
                directory_path: str,
                _name: str | None,
            ) -> None:
                nonlocal swapped, replacement_before
                if (
                    swapped
                    or phase != "before_replace"
                    or os.path.abspath(directory_path)
                    != os.path.abspath(report_directory)
                ):
                    return
                swapped = True
                os.rename(report_directory, parked)
                replacement_before = _replacement_report_directory(
                    report_directory
                )

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=replace_before_displacement,
                ),
                self.assertRaises(OSError),
            ):
                restore_conversion_diagnostic_reports(root, snapshot, receipt)

            self.assertTrue(swapped)
            self.assertEqual(
                _directory_snapshot(report_directory),
                replacement_before,
            )

    @unittest.skipUnless(os.name == "posix", "POSIX relocation semantics required")
    def test_rollback_and_invalidation_stay_bound_after_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_report_pair(root, b"old json\n", b"old markdown\n")
            report_directory = root / "gm2godot"
            parked = root / "gm2godot.parked"
            replacement_before: dict[str, tuple[int, int, int, bytes]] = {}
            swapped = False

            def fail_then_replace_for_rollback(
                phase: str,
                directory_path: str,
                name: str | None,
            ) -> None:
                nonlocal swapped, replacement_before
                if phase == "after_commit" and name == "conversion_diagnostics.md":
                    raise OSError("injected post-commit failure")
                if (
                    swapped
                    or phase != "before_rollback"
                    or os.path.abspath(directory_path)
                    != os.path.abspath(report_directory)
                ):
                    return
                swapped = True
                os.rename(report_directory, parked)
                replacement_before = _replacement_report_directory(
                    report_directory
                )

            with (
                patch(
                    "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                    side_effect=fail_then_replace_for_rollback,
                ),
                self.assertRaisesRegex(OSError, "post-commit failure"),
            ):
                DiagnosticCollector().publish_reports(root)

            self.assertTrue(swapped)
            self.assertEqual(
                _directory_snapshot(report_directory),
                replacement_before,
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _write_report_pair(root, b"stale json\n", b"stale markdown\n")
            report_directory = root / "gm2godot"
            parked = root / "gm2godot.parked"
            replacement_before = {}
            swapped = False

            def replace_before_invalidation_unlink(
                phase: str,
                directory_path: str,
                _name: str | None,
            ) -> None:
                nonlocal swapped, replacement_before
                if (
                    swapped
                    or phase != "before_unlink"
                    or os.path.abspath(directory_path)
                    != os.path.abspath(report_directory)
                ):
                    return
                swapped = True
                os.rename(report_directory, parked)
                replacement_before = _replacement_report_directory(
                    report_directory
                )

            with patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=replace_before_invalidation_unlink,
            ):
                invalidate_conversion_diagnostic_reports(root)

            self.assertTrue(swapped)
            self.assertEqual(
                _directory_snapshot(report_directory),
                replacement_before,
            )

    @unittest.skipUnless(os.name == "nt", "Native Windows handles required")
    def test_windows_bindings_block_root_and_report_relocation_during_publish(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as container:
            root = Path(container) / "external" / "reports"
            report_directory = root / "gm2godot"
            parked_root = root.with_name("reports.parked")
            parked_reports = root / "gm2godot.parked"
            relocation_checked = False

            def try_relocation(
                phase: str,
                _directory_path: str,
                _name: str | None,
            ) -> None:
                nonlocal relocation_checked
                if phase != "before_stage" or relocation_checked:
                    return
                relocation_checked = True
                with self.assertRaises(OSError):
                    os.rename(report_directory, parked_reports)
                with self.assertRaises(OSError):
                    os.rename(root, parked_root)

            with patch(
                "src.conversion.anchored_artifacts._before_anchored_artifact_phase",
                side_effect=try_relocation,
            ):
                receipt = DiagnosticCollector().publish_reports(root)

            self.assertTrue(relocation_checked)
            self.assertTrue(Path(receipt.json_path).is_file())

    def test_invalidation_refuses_redirected_report_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            outside = root / "outside"
            outside.mkdir()
            external_report = outside / "conversion_diagnostics.json"
            external_report.write_bytes(b"external sentinel\n")
            try:
                (root / "gm2godot").symlink_to(
                    outside,
                    target_is_directory=True,
                )
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")

            invalidate_conversion_diagnostic_reports(root)

            self.assertEqual(
                external_report.read_bytes(),
                b"external sentinel\n",
            )


if __name__ == "__main__":
    unittest.main()
