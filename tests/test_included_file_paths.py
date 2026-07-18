from __future__ import annotations

import unittest

from src.conversion.included_file_paths import (
    canonical_included_file_lookup_path,
    plan_included_file_paths,
)
from src.conversion.project_source_paths import ProjectSourcePathError


class TestIncludedFilePaths(unittest.TestCase):
    def assertAssignedPathsArePrefixFree(self, logical_paths: list[str]) -> None:
        output_paths = [
            assignment.assigned_output_path
            for assignment in plan_included_file_paths(logical_paths)
        ]
        for possible_parent in output_paths:
            for possible_child in output_paths:
                if possible_parent == possible_child:
                    continue
                self.assertFalse(
                    possible_child.startswith(possible_parent + "/"),
                    f"{possible_parent!r} blocks {possible_child!r}",
                )

    def test_canonicalizes_nested_portable_paths_and_ascii_lookup_names(
        self,
    ) -> None:
        assignment = plan_included_file_paths(
            [r"Languages\UI Files\English Guide.TXT"]
        )[0]

        self.assertEqual(
            assignment.original_logical_path,
            "Languages/UI Files/English Guide.TXT",
        )
        self.assertEqual(
            assignment.canonical_lookup_path,
            "languages/ui_files/english_guide.txt",
        )
        self.assertEqual(
            assignment.assigned_output_path,
            "languages/ui_files/english_guide.txt",
        )
        self.assertEqual(
            assignment.collision_group,
            ("Languages/UI Files/English Guide.TXT",),
        )
        self.assertFalse(assignment.has_collision)

    def test_lookup_normalization_is_ascii_only(self) -> None:
        self.assertEqual(
            canonical_included_file_lookup_path("Données/Ä FILE.TXT"),
            "données/Ä_file.txt",
        )

    def test_case_and_space_collisions_receive_suffixes_before_extension(
        self,
    ) -> None:
        assignments = {
            assignment.original_logical_path: assignment
            for assignment in plan_included_file_paths(
                ["read_me.txt", "READ ME.TXT", "Read Me.txt"]
            )
        }

        self.assertEqual(
            assignments["read_me.txt"].assigned_output_path,
            "read_me.txt",
        )
        self.assertEqual(
            assignments["READ ME.TXT"].assigned_output_path,
            "read_me_2.txt",
        )
        self.assertEqual(
            assignments["Read Me.txt"].assigned_output_path,
            "read_me_3.txt",
        )
        for assignment in assignments.values():
            self.assertEqual(assignment.canonical_lookup_path, "read_me.txt")
            self.assertEqual(
                assignment.collision_group,
                ("read_me.txt", "READ ME.TXT", "Read Me.txt"),
            )
            self.assertTrue(assignment.has_collision)

    def test_assignments_are_independent_of_input_order(self) -> None:
        paths = [
            "nested/File.txt",
            "NESTED/FILE.TXT",
            "Nested/file.txt",
            "nested/file_2.txt",
        ]

        forward = plan_included_file_paths(paths)
        reverse = plan_included_file_paths(reversed(paths))

        self.assertEqual(forward, reverse)

    def test_natural_canonical_suffix_paths_are_reserved(self) -> None:
        assignments = {
            assignment.original_logical_path: assignment.assigned_output_path
            for assignment in plan_included_file_paths(
                ["File.txt", "file.txt", "file_2.txt"]
            )
        }

        self.assertEqual(assignments["file.txt"], "file.txt")
        self.assertEqual(assignments["file_2.txt"], "file_2.txt")
        self.assertEqual(assignments["File.txt"], "file_3.txt")

    def test_nested_directories_have_independent_collision_groups(self) -> None:
        assignments = {
            assignment.original_logical_path: assignment.assigned_output_path
            for assignment in plan_included_file_paths(
                [
                    "Alpha/File.txt",
                    "alpha/file.txt",
                    "Beta/File.txt",
                    "beta/file.txt",
                ]
            )
        }

        self.assertEqual(assignments["alpha/file.txt"], "alpha/file.txt")
        self.assertEqual(assignments["Alpha/File.txt"], "alpha/file_2.txt")
        self.assertEqual(assignments["beta/file.txt"], "beta/file.txt")
        self.assertEqual(assignments["Beta/File.txt"], "beta/file_2.txt")

    def test_normalized_file_prefix_is_relocated_away_from_directory(
        self,
    ) -> None:
        cases = (
            ("foo_bar", "Foo Bar/item.txt"),
            ("Foo Bar", "foo_bar/item.txt"),
        )
        for file_path, nested_path in cases:
            with self.subTest(file_path=file_path, nested_path=nested_path):
                paths = [file_path, nested_path, "unrelated.txt"]
                assignments = {
                    assignment.original_logical_path: assignment
                    for assignment in plan_included_file_paths(paths)
                }

                self.assertEqual(
                    assignments[file_path].assigned_output_path,
                    "foo_bar_2",
                )
                self.assertEqual(
                    assignments[nested_path].assigned_output_path,
                    "foo_bar/item.txt",
                )
                self.assertEqual(
                    assignments["unrelated.txt"].assigned_output_path,
                    "unrelated.txt",
                )
                self.assertEqual(
                    assignments[file_path].collision_group,
                    (file_path, nested_path),
                )
                self.assertEqual(
                    assignments[nested_path].collision_group,
                    (file_path, nested_path),
                )
                self.assertTrue(assignments[file_path].has_collision)
                self.assertFalse(assignments[nested_path].has_collision)
                self.assertAssignedPathsArePrefixFree(paths)

    def test_nested_file_prefixes_relocate_each_blocking_file(self) -> None:
        paths = [
            "tree",
            "tree/branch.txt",
            "tree/branch.txt/leaf.bin",
        ]
        assignments = {
            assignment.original_logical_path: assignment
            for assignment in plan_included_file_paths(paths)
        }

        self.assertEqual(assignments["tree"].assigned_output_path, "tree_2")
        self.assertEqual(
            assignments["tree/branch.txt"].assigned_output_path,
            "tree/branch_2.txt",
        )
        self.assertEqual(
            assignments["tree/branch.txt/leaf.bin"].assigned_output_path,
            "tree/branch.txt/leaf.bin",
        )
        expected_group = tuple(paths)
        for assignment in assignments.values():
            self.assertEqual(assignment.collision_group, expected_group)
        reporting_assignments = [
            assignment.original_logical_path
            for assignment in assignments.values()
            if assignment.has_collision
        ]
        self.assertEqual(reporting_assignments, ["tree"])
        self.assertAssignedPathsArePrefixFree(paths)

    def test_prefix_relocation_reserves_natural_files_and_directories(
        self,
    ) -> None:
        paths = [
            "foo",
            "foo/bar.txt",
            "foo_2",
            "foo_3/item.txt",
        ]
        assignments = {
            assignment.original_logical_path: assignment.assigned_output_path
            for assignment in plan_included_file_paths(paths)
        }

        self.assertEqual(assignments["foo"], "foo_4")
        self.assertEqual(assignments["foo/bar.txt"], "foo/bar.txt")
        self.assertEqual(assignments["foo_2"], "foo_2")
        self.assertEqual(assignments["foo_3/item.txt"], "foo_3/item.txt")
        self.assertAssignedPathsArePrefixFree(paths)

    def test_prefix_collision_assignments_are_input_order_independent(
        self,
    ) -> None:
        paths = [
            "root",
            "ROOT/Child File.txt",
            "root/child_file.txt/grandchild.bin",
            "root_2",
            "sibling.txt",
        ]

        self.assertEqual(
            plan_included_file_paths(paths),
            plan_included_file_paths(reversed(paths)),
        )
        self.assertAssignedPathsArePrefixFree(paths)

    def test_duplicate_normalized_logical_paths_are_coalesced(self) -> None:
        assignments = plan_included_file_paths(
            ["nested/unused/../file.txt", "nested/file.txt"]
        )

        self.assertEqual(len(assignments), 1)
        self.assertEqual(
            assignments[0].original_logical_path,
            "nested/file.txt",
        )
        self.assertFalse(assignments[0].has_collision)

    def test_unsafe_absolute_and_traversal_paths_are_rejected(self) -> None:
        unsafe_paths = (
            "",
            ".",
            "folder/..",
            "../outside.txt",
            "safe/../../outside.txt",
            "/absolute.txt",
            r"C:\absolute.txt",
            "C:drive-relative.txt",
            r"\\server\share\payload.txt",
            "invalid\0name.txt",
        )

        for logical_path in unsafe_paths:
            with self.subTest(logical_path=logical_path):
                with self.assertRaises(ProjectSourcePathError):
                    plan_included_file_paths([logical_path])


if __name__ == "__main__":
    unittest.main()
