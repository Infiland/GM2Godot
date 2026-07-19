# -*- mode: python ; coding: utf-8 -*-

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_SPEC_FILE = Path(SPEC).resolve(strict=True)
_SOURCE_ROOT = _SPEC_FILE.parents[2]
_POLICY_FILE = _SPEC_FILE.with_name("bundle_metadata.py")
_POLICY_SPEC = spec_from_file_location("_gm2godot_macos_bundle_metadata", _POLICY_FILE)
if _POLICY_SPEC is None or _POLICY_SPEC.loader is None:
    raise RuntimeError(f"Cannot load macOS bundle metadata policy from {_POLICY_FILE}.")
_POLICY_MODULE = module_from_spec(_POLICY_SPEC)
_POLICY_SPEC.loader.exec_module(_POLICY_MODULE)
_BUNDLE_METADATA = _POLICY_MODULE.load_bundle_metadata(_SOURCE_ROOT)


a = Analysis(
    [str(_SOURCE_ROOT / "main.py")],
    pathex=[],
    binaries=[],
    datas=[
        (str(_SOURCE_ROOT / "img"), "img"),
        (str(_SOURCE_ROOT / "src"), "src"),
        (str(_SOURCE_ROOT / "Languages"), "Languages"),
        (str(_SOURCE_ROOT / "Current Language"), "."),
    ],
    hiddenimports=[
        "markdown2",
        "PIL",
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "PySide6.QtGui",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GM2Godot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GM2Godot",
)
app = BUNDLE(
    coll,
    name="GM2Godot.app",
    icon=str(_SOURCE_ROOT / "img" / "Logo.png"),
    bundle_identifier=_BUNDLE_METADATA["CFBundleIdentifier"],
    version=_BUNDLE_METADATA["CFBundleShortVersionString"],
    info_plist={"CFBundleVersion": _BUNDLE_METADATA["CFBundleVersion"]},
)
