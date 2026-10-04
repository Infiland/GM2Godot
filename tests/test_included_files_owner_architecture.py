"""Full Included Files owner graph and orchestration-boundary contract."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tests.test_included_files_state_owners import assert_acyclic, project_dependencies

_PARTS = "src.conversion.included_files_parts"
_OWNER_PROJECT_EDGES: dict[str, frozenset[str]] = {
    "__init__": frozenset[str](),
    "constants": frozenset[str](),
    "converter_ports": frozenset(
        {
            "src.conversion.diagnostics",
            "src.conversion.included_file_paths",
            "models",
            "src.conversion.project_manifest",
            "src.conversion.project_source_paths",
            "src.conversion.type_defs",
        }
    ),
    "copy_worker": frozenset({"converter_ports", "file_publication", "models", "path_validation"}),
    "diagnostics": frozenset(
        {"src.conversion.included_file_paths", "converter_ports", "models", "src.conversion.project_source_paths"}
    ),
    "driver": frozenset(
        {
            "src.conversion.atomic_generated_text",
            "src.conversion.included_file_paths",
            "src.conversion.included_file_registry",
            "constants",
            "converter_ports",
            "file_publication",
            "guarded_mutations",
            "locking",
            "models",
            "publisher",
            "recovery",
            "recovery_codec",
            "source_snapshots",
            "staging",
            "stat_metadata",
            "worker_pool",
            "src.conversion.project_source_paths",
            "src.localization",
        }
    ),
    "file_publication": frozenset(
        {"models", "native_filesystem", "path_validation", "source_snapshots", "stat_metadata"}
    ),
    "filesystem_operations": frozenset({"models"}),
    "generation_matching": frozenset(
        {"src.conversion.included_file_paths", "converter_ports", "models", "source_snapshots", "stat_metadata"}
    ),
    "guarded_mutations": frozenset(
        {
            "filesystem_operations",
            "models",
            "native_filesystem",
            "native_posix",
            "phase_observer",
            "source_snapshots",
            "stat_metadata",
        }
    ),
    "locking": frozenset(
        {
            "constants",
            "guarded_mutations",
            "models",
            "native_filesystem",
            "path_validation",
            "record_io",
            "recorded_cleanup",
            "source_snapshots",
            "stat_metadata",
        }
    ),
    "models": frozenset[str](),
    "native_filesystem": frozenset(
        {"filesystem_operations", "models", "native_posix", "native_windows", "stat_metadata"}
    ),
    "native_posix": frozenset({"models", "stat_metadata"}),
    "native_windows": frozenset({"filesystem_operations", "models", "path_validation", "stat_metadata"}),
    "path_validation": frozenset({"src.conversion.included_file_registry", "constants", "models"}),
    "phase_observer": frozenset[str](),
    "planning": frozenset(
        {"converter_ports", "models", "src.conversion.project_manifest", "src.conversion.project_source_paths"}
    ),
    "publisher": frozenset(
        {
            "constants",
            "guarded_mutations",
            "models",
            "native_filesystem",
            "path_validation",
            "phase_observer",
            "record_io",
            "record_lifecycle",
            "recorded_cleanup",
            "recovery_codec",
            "source_snapshots",
            "staging",
            "transaction_cleanup",
            "transaction_state",
            "src.conversion.type_defs",
        }
    ),
    "record_io": frozenset(
        {
            "constants",
            "models",
            "native_filesystem",
            "path_validation",
            "recovery_codec",
            "source_snapshots",
            "stat_metadata",
        }
    ),
    "record_lifecycle": frozenset(
        {
            "constants",
            "guarded_mutations",
            "models",
            "native_filesystem",
            "phase_observer",
            "record_io",
            "recorded_cleanup",
            "recovery_codec",
            "source_snapshots",
        }
    ),
    "recorded_cleanup": frozenset(
        {
            "filesystem_operations",
            "guarded_mutations",
            "models",
            "native_filesystem",
            "path_validation",
            "phase_observer",
            "source_snapshots",
            "stat_metadata",
        }
    ),
    "recovery": frozenset(
        {
            "constants",
            "guarded_mutations",
            "models",
            "native_filesystem",
            "path_validation",
            "phase_observer",
            "record_io",
            "record_lifecycle",
            "recorded_cleanup",
            "recovery_codec",
            "source_snapshots",
            "transaction_cleanup",
            "transaction_state",
        }
    ),
    "recovery_codec": frozenset({"constants", "models", "path_validation", "stat_metadata"}),
    "source_access": frozenset(
        {
            "src.conversion.included_file_paths",
            "converter_ports",
            "models",
            "native_filesystem",
            "recovery_codec",
            "source_snapshots",
            "stat_metadata",
            "worker_pool",
            "src.conversion.project_source_paths",
        }
    ),
    "source_snapshots": frozenset(
        {"constants", "models", "native_filesystem", "native_posix", "path_validation", "stat_metadata"}
    ),
    "staging": frozenset(
        {
            "constants",
            "guarded_mutations",
            "models",
            "native_filesystem",
            "native_posix",
            "path_validation",
            "record_io",
            "recovery_codec",
            "source_snapshots",
            "stat_metadata",
        }
    ),
    "stat_metadata": frozenset({"src.conversion.included_file_paths", "models"}),
    "transaction_cleanup": frozenset(
        {"constants", "guarded_mutations", "models", "path_validation", "recorded_cleanup", "source_snapshots"}
    ),
    "transaction_state": frozenset({"constants", "models", "record_io", "recovery_codec", "source_snapshots"}),
    "worker_pool": frozenset({"constants", "src.conversion.type_defs"}),
}

_ORCHESTRATION = frozenset({"driver", "planning", "source_access", "copy_worker"})
_MUTATING_CALL_NAMES = frozenset(
    {
        "write",
        "writelines",
        "write_text",
        "write_bytes",
        "unlink",
        "rmdir",
        "rename",
        "replace",
        "link",
        "symlink",
        "truncate",
        "ftruncate",
        "chmod",
        "chown",
        "utime",
        "fdopen",
        "remove",
        "rmtree",
        "copyfile",
        "copy2",
        "copy",
        "move",
        "fsync",
    }
)
_WRITE_OPEN_FLAGS = frozenset({"O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"})


def assert_orchestration_boundary(owner: str, source: str) -> None:
    """Reject new direct publication/platform I/O, including deferred aliases."""
    if owner not in _ORCHESTRATION:
        raise AssertionError("Unknown orchestration owner: " + owner)
    tree = ast.parse(source)
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                bindings[alias.asname or alias.name] = node.module + "." + alias.name

    def target(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return bindings.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            parent = target(node.value)
            return None if parent is None else parent + "." + node.attr
        return None

    for node in ast.walk(tree):
        if owner == "source_access" and isinstance(node, ast.Attribute):
            if target(node) in {"os." + flag for flag in _WRITE_OPEN_FLAGS}:
                raise AssertionError("Source acquisition gained a write-open flag")
        if not isinstance(node, ast.Call):
            continue
        called = target(node.func)
        leaf = (
            node.func.attr
            if isinstance(node.func, ast.Attribute)
            else (node.func.id if isinstance(node.func, ast.Name) else "")
        )
        mutating_library_call = called is not None and (
            called in {"os." + name for name in _MUTATING_CALL_NAMES}
            or called in {"shutil." + name for name in _MUTATING_CALL_NAMES}
        )
        # String.replace and dataclasses.replace remain pure original model/path
        # projections. Filesystem mutators resolve through their real imports.
        if mutating_library_call or leaf in {"write", "writelines", "write_text", "write_bytes"}:
            raise AssertionError("Orchestration bypassed a publication owner: " + leaf)
        if leaf == "open" or called in {"open", "io.open", "os.open"}:
            # Confined read-only directory listing already owns its POSIX FD.
            if owner != "source_access" or called != "os.open":
                raise AssertionError("Orchestration bypassed source/platform acquisition")
        if called in {"os.read", "os.close", "os.lseek", "os.mkdir", "os.makedirs"}:
            # The original driver creates only its owned candidate root. Source
            # acquisition closes its own read-only listing descriptor.
            if not (
                (owner == "driver" and called == "os.mkdir") or (owner == "source_access" and called == "os.close")
            ):
                raise AssertionError("Orchestration bypassed an operation owner: " + called)


class TestIncludedFilesOwnerArchitecture(unittest.TestCase):
    def test_complete_owner_graph_and_orchestration_boundaries(self) -> None:
        directory = Path(__file__).resolve().parents[1] / "src/conversion/included_files_parts"
        actual_names = {path.stem for path in directory.glob("*.py")}
        self.assertEqual(actual_names, set(_OWNER_PROJECT_EDGES))
        self.assertEqual(len(actual_names), 31)
        graph: dict[str, frozenset[str]] = {}
        sources: dict[str, str] = {}
        for owner, short_edges in _OWNER_PROJECT_EDGES.items():
            expected = frozenset(edge if edge.startswith("src.") else _PARTS + "." + edge for edge in short_edges)
            source = (directory / (owner + ".py")).read_text(encoding="utf-8")
            sources[owner] = source
            with self.subTest(owner=owner):
                observed = project_dependencies(source, expected)
                self.assertEqual(observed, expected)
                graph[_PARTS + "." + owner] = observed
                if owner in _ORCHESTRATION:
                    assert_orchestration_boundary(owner, source)
        assert_acyclic(graph)

        for forbidden in (
            "from src.conversion import included_files",
            "def late():\n    from src.conversion.included_files import IncludedFilesConverter\n",
            "from src.conversion.included_files_parts import native_posix",
            "def late():\n    from src.conversion.included_files_parts import record_io\n",
            "from . import publisher",
            "from src.conversion.included_files_parts.models import *",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(AssertionError):
                    project_dependencies(forbidden, graph[_PARTS + ".driver"])

        cycle = dict(graph)
        cycle[_PARTS + ".converter_ports"] |= {_PARTS + ".driver"}
        with self.assertRaisesRegex(AssertionError, "dependency cycle"):
            assert_acyclic(cycle)

        for owner, addition in (
            ("driver", "def late():\n    import os as renamed\n    renamed.replace('candidate', 'public')\n"),
            ("planning", "def late():\n    from os import unlink as erase\n    erase('public')\n"),
            ("copy_worker", "def late():\n    open('public', 'wb')\n"),
            ("source_access", "def late():\n    import os\n    os.open('source', os.O_RDWR)\n"),
        ):
            with self.subTest(owner=owner, addition=addition):
                with self.assertRaises(AssertionError):
                    assert_orchestration_boundary(owner, sources[owner] + "\n" + addition)
