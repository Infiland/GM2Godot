from __future__ import annotations

import ast
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re
import runpy
import shutil
import sys
import tempfile
from typing import Protocol, cast
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "packaging" / "macos" / "bundle_metadata.py"
SPEC_PATH = PROJECT_ROOT / "packaging" / "macos" / "GM2Godot.spec"

EXPECTED_METADATA_KEYS = {
    "CFBundleIdentifier",
    "CFBundleShortVersionString",
    "CFBundleVersion",
}
EXPECTED_DATA_FILES = [
    (PROJECT_ROOT / "img", "img"),
    (PROJECT_ROOT / "src", "src"),
    (PROJECT_ROOT / "Languages", "Languages"),
    (PROJECT_ROOT / "Current Language", "."),
]
EXPECTED_HIDDEN_IMPORTS = [
    "markdown2",
    "PIL",
    "PySide6.QtWidgets",
    "PySide6.QtCore",
    "PySide6.QtGui",
]


class _BundleMetadataPolicy(Protocol):
    __all__: tuple[str, ...]
    BUNDLE_IDENTIFIER: str

    def load_release_version(self, source_root: Path) -> str: ...

    def load_bundle_metadata(self, source_root: Path) -> dict[str, str]: ...


def _load_policy(path: Path = POLICY_PATH) -> _BundleMetadataPolicy:
    module_spec = spec_from_file_location("_gm2godot_test_macos_bundle_metadata", path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"Cannot load bundle metadata policy from {path}.")
    module = module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return cast(_BundleMetadataPolicy, module)


POLICY = _load_policy()


def canonical_version_source(version: str) -> str:
    return f'VERSION = "{version}"\n\n\ndef get_version():\n    return VERSION\n'


def write_version_source(source_root: Path, source: str) -> Path:
    version_path = source_root / "src" / "version.py"
    version_path.parent.mkdir(parents=True, exist_ok=True)
    version_path.write_text(source, encoding="utf-8")
    return version_path


class _FakeTarget:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs


class _FakeAnalysis(_FakeTarget):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.pure = ("analysis-pure",)
        self.scripts = ("analysis-scripts",)
        self.binaries = ("analysis-binaries",)
        self.datas = ("analysis-datas",)


def _run_spec(spec_path: Path) -> dict[str, object]:
    namespace = runpy.run_path(
        str(spec_path),
        init_globals={
            "SPEC": str(spec_path),
            "Analysis": _FakeAnalysis,
            "PYZ": _FakeTarget,
            "EXE": _FakeTarget,
            "COLLECT": _FakeTarget,
            "BUNDLE": _FakeTarget,
        },
    )
    return cast(dict[str, object], namespace)


class TestMacOSBundleMetadataPolicy(unittest.TestCase):
    def test_repository_metadata_has_exact_public_contract(self) -> None:
        version = POLICY.load_release_version(PROJECT_ROOT)
        metadata = POLICY.load_bundle_metadata(PROJECT_ROOT)

        self.assertEqual(POLICY.BUNDLE_IDENTIFIER, "land.infi.gm2godot")
        self.assertEqual(
            POLICY.__all__,
            ("BUNDLE_IDENTIFIER", "load_release_version", "load_bundle_metadata"),
        )
        self.assertEqual(set(metadata), EXPECTED_METADATA_KEYS)
        self.assertEqual(
            metadata,
            {
                "CFBundleIdentifier": "land.infi.gm2godot",
                "CFBundleShortVersionString": version,
                "CFBundleVersion": version,
            },
        )
        self.assertTrue(all(type(value) is str for value in metadata.values()))

    def test_docstring_future_import_and_annotated_getter_are_accepted(self) -> None:
        source = (
            '"""Canonical application version."""\n'
            "from __future__ import annotations\n\n"
            'VERSION = "2.3.4"\n\n'
            "def get_version() -> str:\n"
            "    return VERSION\n\n"
        )
        with tempfile.TemporaryDirectory() as raw_root:
            source_root = Path(raw_root)
            write_version_source(source_root, source)

            self.assertEqual(POLICY.load_release_version(source_root), "2.3.4")

    def test_version_source_is_never_executed(self) -> None:
        source = canonical_version_source("2.3.4") + 'raise AssertionError("source was executed")\n'
        with tempfile.TemporaryDirectory() as raw_root:
            source_root = Path(raw_root)
            write_version_source(source_root, source)

            with self.assertRaisesRegex(ValueError, "may only contain"):
                POLICY.load_release_version(source_root)

    def test_noncanonical_release_versions_are_rejected(self) -> None:
        invalid_versions = (
            "0.0.0",
            "1.2",
            "1.2.3.4",
            "01.2.3",
            "1.02.3",
            "1.2.03",
            "1.2.3-beta",
            " 1.2.3",
            "1.2.3 ",
        )
        for version in invalid_versions:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as raw_root:
                source_root = Path(raw_root)
                write_version_source(source_root, canonical_version_source(version))

                with self.assertRaisesRegex(ValueError, "non-placeholder, canonical three-integer"):
                    POLICY.load_release_version(source_root)

    def test_missing_dynamic_duplicate_and_rebound_versions_are_rejected(self) -> None:
        invalid_sources = {
            "missing": 'OTHER = "1.2.3"\n',
            "dynamic": 'VERSION = ".".join(("1", "2", "3"))\n\ndef get_version():\n    return VERSION\n',
            "duplicate": canonical_version_source("1.2.3") + 'VERSION = "1.2.4"\n',
            "annotated": 'VERSION: str = "1.2.3"\n\ndef get_version():\n    return VERSION\n',
            "globals-rebind": canonical_version_source("1.2.3") + 'globals()["VERSION"] = "9.9.9"\n',
            "wrong-getter": 'VERSION = "1.2.3"\n\ndef get_version():\n    return "9.9.9"\n',
            "getter-default": 'VERSION = "1.2.3"\n\ndef get_version(value=VERSION):\n    return VERSION\n',
            "getter-decorator": 'VERSION = "1.2.3"\n\n@staticmethod\ndef get_version():\n    return VERSION\n',
        }
        for label, source in invalid_sources.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw_root:
                source_root = Path(raw_root)
                write_version_source(source_root, source)

                with self.assertRaises(ValueError):
                    POLICY.load_release_version(source_root)

    def test_malformed_and_non_utf8_sources_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            source_root = Path(raw_root)
            write_version_source(source_root, "VERSION =\n")
            with self.assertRaisesRegex(ValueError, "not valid Python syntax"):
                POLICY.load_release_version(source_root)

        with tempfile.TemporaryDirectory() as raw_root:
            source_root = Path(raw_root)
            version_path = write_version_source(source_root, 'VERSION = "1.2.3"\n')
            version_path.write_bytes(b'VERSION = "\xff"\n')
            with self.assertRaisesRegex(ValueError, "not valid UTF-8"):
                POLICY.load_release_version(source_root)

    def test_symlinked_version_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            source_root = Path(raw_root)
            source_directory = source_root / "src"
            source_directory.mkdir()
            real_version = source_root / "real_version.py"
            real_version.write_text(canonical_version_source("1.2.3"), encoding="utf-8")
            version_path = source_directory / "version.py"
            try:
                version_path.symlink_to(real_version)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"Symlinks are unavailable: {error}")

            with self.assertRaisesRegex(ValueError, "must not be a symbolic link"):
                POLICY.load_release_version(source_root)

    def test_oversized_version_source_is_rejected_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            source_root = Path(raw_root)
            version_path = write_version_source(source_root, canonical_version_source("1.2.3"))
            version_path.write_bytes(b"#" * (64 * 1024))

            with self.assertRaisesRegex(ValueError, "exceeds the .*byte limit"):
                POLICY.load_release_version(source_root)

    def test_policy_uses_ast_without_dynamic_execution(self) -> None:
        source = POLICY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(POLICY_PATH))
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_roots.add(node.module.partition(".")[0])
        forbidden_calls = {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        } & {"compile", "eval", "exec", "__import__"}

        self.assertTrue({"ast", "pathlib", "re", "stat", "typing"} <= imported_roots)
        self.assertTrue({"importlib", "runpy", "src"}.isdisjoint(imported_roots))
        self.assertEqual(forbidden_calls, set())
        self.assertIn(".lstat()", source)
        self.assertIn('.open("rb")', source)
        self.assertIn("ast.parse(", source)


class TestMacOSPyInstallerSpec(unittest.TestCase):
    def test_spec_is_the_only_tracked_spec_exception(self) -> None:
        ignore_lines = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        spec_exceptions = [line for line in ignore_lines if line.startswith("!") and line.endswith(".spec")]

        self.assertEqual(spec_exceptions, ["!packaging/macos/GM2Godot.spec"])
        self.assertLess(
            ignore_lines.index("*.spec"),
            ignore_lines.index("!packaging/macos/GM2Godot.spec"),
        )

    def test_spec_anchors_from_exact_spec_and_avoids_module_search_paths(self) -> None:
        source = SPEC_PATH.read_text(encoding="utf-8")
        ast.parse(source, filename=str(SPEC_PATH))

        self.assertIn("Path(SPEC).resolve(strict=True)", source)
        self.assertIn('_POLICY_FILE = _SPEC_FILE.with_name("bundle_metadata.py")', source)
        self.assertIn("spec_from_file_location(", source)
        self.assertNotIn("SPECPATH", source)
        self.assertNotIn("sys.path", source)
        self.assertIsNone(re.search(r"[\"'](?:0|[1-9][0-9]*)\.[0-9]+\.[0-9]+[\"']", source))

    def test_spec_preserves_onedir_inputs_and_routes_metadata_to_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            source_root = Path(raw_root) / "checkout"
            macos_directory = source_root / "packaging" / "macos"
            macos_directory.mkdir(parents=True)
            copied_policy = macos_directory / POLICY_PATH.name
            copied_spec = macos_directory / SPEC_PATH.name
            shutil.copyfile(POLICY_PATH, copied_policy)
            shutil.copyfile(SPEC_PATH, copied_spec)
            write_version_source(source_root, canonical_version_source("9.8.7"))

            shadow_directory = Path(raw_root) / "shadow"
            shadow_directory.mkdir()
            (shadow_directory / "bundle_metadata.py").write_text(
                "raise RuntimeError('module-search shadow was imported')\n",
                encoding="utf-8",
            )
            with mock.patch.object(sys, "path", [str(shadow_directory), *sys.path]):
                namespace = _run_spec(copied_spec)

            resolved_source_root = source_root.resolve()

        self.assertEqual(cast(Path, namespace["_SOURCE_ROOT"]), resolved_source_root)

        analysis = cast(_FakeAnalysis, namespace["a"])
        self.assertEqual(analysis.args, ([str(resolved_source_root / "main.py")],))
        self.assertEqual(analysis.kwargs["pathex"], [])
        self.assertEqual(analysis.kwargs["binaries"], [])
        self.assertEqual(
            analysis.kwargs["datas"],
            [
                (
                    str(resolved_source_root / path.relative_to(PROJECT_ROOT)),
                    destination,
                )
                for path, destination in EXPECTED_DATA_FILES
            ],
        )
        self.assertEqual(analysis.kwargs["hiddenimports"], EXPECTED_HIDDEN_IMPORTS)
        self.assertEqual(analysis.kwargs["hookspath"], [])
        self.assertEqual(analysis.kwargs["hooksconfig"], {})
        self.assertEqual(analysis.kwargs["runtime_hooks"], [])
        self.assertEqual(analysis.kwargs["excludes"], [])
        self.assertIs(analysis.kwargs["noarchive"], False)
        self.assertEqual(analysis.kwargs["optimize"], 0)

        executable = cast(_FakeTarget, namespace["exe"])
        self.assertEqual(executable.args[1:], (("analysis-scripts",), []))
        self.assertIs(executable.kwargs["exclude_binaries"], True)
        self.assertEqual(executable.kwargs["name"], "GM2Godot")
        self.assertIs(executable.kwargs["console"], False)
        self.assertIs(executable.kwargs["argv_emulation"], False)
        self.assertIsNone(executable.kwargs["target_arch"])
        self.assertIsNone(executable.kwargs["codesign_identity"])
        self.assertIsNone(executable.kwargs["entitlements_file"])

        collection = cast(_FakeTarget, namespace["coll"])
        self.assertEqual(
            collection.args,
            (executable, ("analysis-binaries",), ("analysis-datas",)),
        )
        self.assertEqual(collection.kwargs["name"], "GM2Godot")

        bundle = cast(_FakeTarget, namespace["app"])
        self.assertEqual(bundle.args, (collection,))
        self.assertEqual(bundle.kwargs["name"], "GM2Godot.app")
        self.assertEqual(
            bundle.kwargs["icon"],
            str(resolved_source_root / "img" / "Logo.png"),
        )
        self.assertEqual(bundle.kwargs["bundle_identifier"], "land.infi.gm2godot")
        self.assertEqual(bundle.kwargs["version"], "9.8.7")
        self.assertEqual(bundle.kwargs["info_plist"], {"CFBundleVersion": "9.8.7"})


if __name__ == "__main__":
    unittest.main()
