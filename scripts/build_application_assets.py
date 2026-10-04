"""Copy canonical root GUI assets into wheel build output, never into source.

This build-only command is loaded through tool.setuptools.cmdclass. The runtime
wheel does not contain scripts or depend on setuptools.
"""

from __future__ import annotations

from pathlib import Path
from shutil import copyfile
from typing import override

from setuptools.command.build_py import build_py

REQUIRED_APPLICATION_ASSETS = (
    "Current Language",
    "img/Gamemaker.png",
    "img/Godot.png",
    "img/Logo.png",
    "img/icon_language.png",
    "Languages/eng.json",
    "Languages/de.json",
)


def application_asset_inputs(source_root: Path) -> tuple[Path, ...]:
    for relative in REQUIRED_APPLICATION_ASSETS:
        if not (source_root / relative).is_file():
            raise FileNotFoundError(source_root / relative)
    return (
        Path("Current Language"),
        *(path.relative_to(source_root) for path in sorted((source_root / "img").glob("*.png"))),
        *(path.relative_to(source_root) for path in sorted((source_root / "Languages").glob("*.json"))),
    )


def copy_application_assets(source_root: Path, build_lib: Path) -> tuple[Path, ...]:
    inputs = application_asset_inputs(source_root)
    destination = build_lib / "src" / "application_assets"
    outputs: list[Path] = []
    for relative in inputs:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        copyfile(source_root / relative, target)
        outputs.append(target)
    return tuple(outputs)


class BuildApplicationAssets(build_py):
    # These are real command options. Annotations add no runtime assignments and
    # retain setuptools' inherited option initialization/finalization and flags.
    build_lib: str | None
    dry_run: bool

    def application_output_mapping(self) -> dict[str, str]:
        if self.build_lib is None:
            raise RuntimeError("build_py must be finalized before application output lookup")
        source_root = Path(__file__).resolve().parents[1]
        destination = Path(self.build_lib) / "src" / "application_assets"
        return {
            str(destination / relative): relative.as_posix()
            for relative in application_asset_inputs(source_root)
        }

    @override
    def run(self) -> None:
        super().run()
        if self.editable_mode or self.dry_run:
            return
        if self.build_lib is None:
            raise RuntimeError("build_py must be finalized before copying application assets")
        copy_application_assets(Path(__file__).resolve().parents[1], Path(self.build_lib))

    @override
    def get_outputs(self, include_bytecode: bool = True) -> list[str]:
        outputs = super().get_outputs(include_bytecode)
        if self.editable_mode:
            return outputs
        return list(dict.fromkeys((*outputs, *self.application_output_mapping())))

    @override
    def get_output_mapping(self) -> dict[str, str]:
        mapping = super().get_output_mapping()
        if not self.editable_mode:
            mapping.update(self.application_output_mapping())
        return mapping
