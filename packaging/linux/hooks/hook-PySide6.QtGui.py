from collections.abc import Callable
from pathlib import Path
from typing import cast

from PyInstaller.utils.hooks.qt import add_qt6_dependencies  # pyright: ignore[reportMissingImports, reportUnknownVariableType]


QtBinary = tuple[str, str]
QtData = tuple[str, str]
AddQtDependencies = Callable[[str], tuple[list[str], list[QtBinary], list[QtData]]]


def _is_unsupported_tiff_plugin(binary: QtBinary) -> bool:
    source, destination = binary
    normalized_destination = destination.replace("\\", "/").rstrip("/")
    return (
        Path(source).name == "libqtiff.so"
        and normalized_destination.endswith("/plugins/imageformats")
    )


typed_add_qt6_dependencies = cast(AddQtDependencies, add_qt6_dependencies)
hiddenimports, binaries, datas = typed_add_qt6_dependencies(__file__)

unsupported_tiff_plugins = [
    binary for binary in binaries if _is_unsupported_tiff_plugin(binary)
]
if len(unsupported_tiff_plugins) != 1:
    raise RuntimeError(
        "Expected exactly one PySide6 Qt TIFF image-format plugin; "
        f"found {len(unsupported_tiff_plugins)}."
    )

binaries = [
    binary for binary in binaries if not _is_unsupported_tiff_plugin(binary)
]
