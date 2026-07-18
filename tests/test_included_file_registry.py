from __future__ import annotations

import os
import tempfile
import unittest

from src.conversion.included_file_paths import plan_included_file_paths
from src.conversion.included_file_registry import (
    INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
    build_included_file_registry_entries,
    render_included_file_registry_script,
    write_included_file_registry,
)


class TestIncludedFileRegistry(unittest.TestCase):
    def test_entries_preserve_planned_assignments_and_emission_state(self) -> None:
        assignments = plan_included_file_paths(
            (
                "read_me_2.txt",
                "Read Me.txt",
                "read_me.txt",
                "foo_bar",
                "Foo Bar/item.txt",
            )
        )
        emitted = {
            "Read Me.txt",
            "read_me.txt",
            "read_me_2.txt",
            "Foo Bar/item.txt",
        }

        entries = build_included_file_registry_entries(assignments, emitted)

        self.assertEqual(
            {
                entry.logical_path: (
                    entry.canonical_path,
                    entry.assigned_path,
                    entry.emitted,
                )
                for entry in entries
            },
            {
                "Foo Bar/item.txt": (
                    "foo_bar/item.txt",
                    "foo_bar/item.txt",
                    True,
                ),
                "Read Me.txt": ("read_me.txt", "read_me_3.txt", True),
                "foo_bar": ("foo_bar", "foo_bar_2", False),
                "read_me.txt": ("read_me.txt", "read_me.txt", True),
                "read_me_2.txt": (
                    "read_me_2.txt",
                    "read_me_2.txt",
                    True,
                ),
            },
        )

    def test_registry_rendering_is_independent_of_input_order(self) -> None:
        assignments = plan_included_file_paths(
            ("Read Me.txt", "read_me.txt", "read_me_2.txt")
        )
        entries = build_included_file_registry_entries(
            assignments,
            {assignment.original_logical_path for assignment in assignments},
        )

        forward = render_included_file_registry_script(entries)
        reverse = render_included_file_registry_script(reversed(entries))

        self.assertEqual(forward, reverse)
        self.assertIn("const FORMAT_VERSION = 1", forward)
        self.assertIn(
            "static func gml_included_file_registry_entries():",
            forward,
        )
        self.assertIn('"assigned_path": "read_me_3.txt"', forward)

    def test_writer_publishes_empty_authoritative_registry(self) -> None:
        with tempfile.TemporaryDirectory() as godot_project_path:
            registry_path = write_included_file_registry(
                godot_project_path,
                (),
                (),
            )

            self.assertEqual(
                registry_path,
                os.path.join(
                    godot_project_path,
                    INCLUDED_FILE_REGISTRY_RELATIVE_PATH,
                ),
            )
            with open(registry_path, encoding="utf-8") as registry_file:
                content = registry_file.read()
            self.assertIn("const INCLUDED_FILES = []", content)

    def test_writer_rejects_redirected_registry_directory(self) -> None:
        with (
            tempfile.TemporaryDirectory() as godot_project_path,
            tempfile.TemporaryDirectory() as outside_path,
        ):
            try:
                os.symlink(
                    outside_path,
                    os.path.join(godot_project_path, "gm2godot"),
                )
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Symbolic links are unavailable: {error}")

            with self.assertRaises(OSError):
                write_included_file_registry(
                    godot_project_path,
                    (),
                    (),
                )

            self.assertFalse(
                os.path.exists(
                    os.path.join(
                        outside_path,
                        "gml_included_file_registry.gd",
                    )
                )
            )


if __name__ == "__main__":
    unittest.main()
