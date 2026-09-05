from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import cast

from scripts import conversion_parity_contract as contract, conversion_parity_snapshot as snapshots


class TestConversionParitySnapshot(unittest.TestCase):
    def test_destination_mismatch_fails_before_field_comparison(self) -> None:
        base = snapshots.FixtureRun(destination="/tmp/base", files={}, snapshot={"stdout": ""})
        head = snapshots.FixtureRun(destination="/tmp/head", files={}, snapshot={"stdout": ""})
        with self.assertRaisesRegex(contract.ParityError, "Destination mismatch"):
            snapshots.compare_fixture_runs(base, head, ("stdout",))

    def test_transaction_provenance_retains_raw_ids_and_normalizes_only_declared_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            destination = Path(temporary_root)
            transaction = destination / ".gm2godot-managed-output"
            transaction.mkdir()
            generation = transaction / ".gm2godot-managed-output-generation-aabb-desired.json"
            generation.write_text(
                json.dumps(
                    {
                        "kind": "gm2godot-managed-output-generation-record",
                        "transaction_id": "aabb",
                        "inventory": {"entries": [{"path": "visible.gd", "sha256": "stable"}]},
                    }
                ),
                encoding="utf-8",
            )
            (destination / ".gm2godot-managed-output.lock").write_text("lock", encoding="utf-8")
            (destination / "visible.gd").write_text("extends Node\n", encoding="utf-8")
            files = snapshots.collect_output_files(destination)
            definition = contract.DestinationDefinition(
                seed_project_godot="",
                same_absolute_path=True,
                reset_between_base_and_head=True,
                transaction_root=".gm2godot-managed-output",
                transaction_lock=".gm2godot-managed-output.lock",
                volatile_transaction_fields=("transaction_id",),
            )
            snapshot = snapshots.output_snapshot(
                files,
                destination=destination,
                definition=definition,
                stdout="",
                stderr="",
                exit_status=0,
                parser_error={},
                runtime_markers={},
            )
            provenance = cast(dict[str, object], snapshot["transaction_provenance"])
            raw = cast(dict[str, object], provenance["raw"])
            self.assertIn(
                ".gm2godot-managed-output/.gm2godot-managed-output-generation-aabb-desired.json",
                raw,
            )
            semantics = provenance["semantics"]
            self.assertIn("volatile_shape", json.dumps(semantics, sort_keys=True))
            self.assertIn("stable", json.dumps(semantics, sort_keys=True))

    def test_transaction_provenance_preserves_unlisted_nested_identity(self) -> None:
        definition = contract.DestinationDefinition(
            seed_project_godot="",
            same_absolute_path=True,
            reset_between_base_and_head=True,
            transaction_root=".gm2godot-managed-output",
            transaction_lock=".gm2godot-managed-output.lock",
            volatile_transaction_fields=("evidence.attempt.identity",),
        )

        def transaction_run(identity: str, attempt_identity: str) -> snapshots.FixtureRun:
            files = {
                ".gm2godot-managed-output/stable-record.json": (
                    0o600,
                    json.dumps(
                        {
                            "identity": identity,
                            "evidence": {"attempt": {"identity": attempt_identity}},
                        }
                    ).encode("utf-8"),
                )
            }
            snapshot = snapshots.output_snapshot(
                files,
                destination=Path("/same-destination"),
                definition=definition,
                stdout="",
                stderr="",
                exit_status=0,
                parser_error={},
                runtime_markers={},
            )
            return snapshots.FixtureRun("/same-destination", files, snapshot)

        base = transaction_run("semantic-A", "volatile-A")
        self.assertEqual(
            snapshots.compare_fixture_runs(
                base,
                transaction_run("semantic-A", "volatile-B"),
                ("transaction_provenance",),
            ),
            {},
        )
        self.assertIn(
            "transaction_provenance",
            snapshots.compare_fixture_runs(
                base,
                transaction_run("semantic-B", "volatile-A"),
                ("transaction_provenance",),
            ),
        )

    def test_converter_snapshot_precedes_post_boot_cache_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            destination = Path(temporary_root)
            (destination / "visible.gd").write_text("extends Node\n", encoding="utf-8")
            definition = contract.DestinationDefinition(
                seed_project_godot="",
                same_absolute_path=True,
                reset_between_base_and_head=True,
                transaction_root=".gm2godot-managed-output",
                transaction_lock=".gm2godot-managed-output.lock",
                volatile_transaction_fields=("transaction_id",),
            )
            converter_files = snapshots.collect_output_files(destination)
            (destination / ".godot").mkdir()
            (destination / ".godot" / "post_boot.cache").write_text("cache", encoding="utf-8")
            snapshot = snapshots.output_snapshot(
                converter_files,
                destination=destination,
                definition=definition,
                stdout="",
                stderr="",
                exit_status=0,
                parser_error={},
                runtime_markers={},
            )
            self.assertEqual(snapshot["relative_paths"], ["visible.gd"])

    def test_transaction_provenance_rejects_stable_record_path_mode_and_content_drift(self) -> None:
        definition = contract.DestinationDefinition(
            seed_project_godot="",
            same_absolute_path=True,
            reset_between_base_and_head=True,
            transaction_root=".gm2godot-managed-output",
            transaction_lock=".gm2godot-managed-output.lock",
            volatile_transaction_fields=("transaction_id",),
        )

        def transaction_run(path: str, mode: int, value: str) -> snapshots.FixtureRun:
            files = {
                path: (
                    mode,
                    json.dumps({"kind": "record", "stable": value}).encode("utf-8"),
                )
            }
            snapshot = snapshots.output_snapshot(
                files,
                destination=Path("/same-destination"),
                definition=definition,
                stdout="",
                stderr="",
                exit_status=0,
                parser_error={},
                runtime_markers={},
            )
            return snapshots.FixtureRun("/same-destination", files, snapshot)

        base = transaction_run(
            ".gm2godot-managed-output/stable-record.json",
            0o600,
            "unchanged",
        )
        changed_runs = {
            "path": transaction_run(
                ".gm2godot-managed-output/renamed-record.json",
                0o600,
                "unchanged",
            ),
            "mode": transaction_run(
                ".gm2godot-managed-output/stable-record.json",
                0o644,
                "unchanged",
            ),
            "content": transaction_run(
                ".gm2godot-managed-output/stable-record.json",
                0o600,
                "changed",
            ),
        }
        for change, head in changed_runs.items():
            with self.subTest(change=change):
                differences = snapshots.compare_fixture_runs(
                    base,
                    head,
                    ("transaction_provenance",),
                )
                self.assertIn("transaction_provenance", differences)


if __name__ == "__main__":
    unittest.main()
