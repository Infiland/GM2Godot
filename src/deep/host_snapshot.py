"""The supported, read-only converter input contract consumed by Deep.

This module belongs to the client: a downloaded extension never imports Python
from a source checkout. Paths identify the original project and are rebound to
the immutable snapshot by the extension.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from src.conversion.gml_transpiler import iter_gml_api_entries
from src.conversion.project_manifest import load_gamemaker_project_manifest
from src.conversion.resource_index import GameMakerResourceIndex
from src.conversion.resource_models import parse_gamemaker_resource_models
from src.deep.snapshot_resources import inventory_resources
from src.version import get_version


def build_host_snapshot(source_path: str) -> dict[str, object]:
    """Describe source resources and converter capabilities without converting."""
    source = Path(source_path).resolve(strict=True)
    if source.is_file() and source.suffix.casefold() == ".yyp":
        source = source.parent
    if not source.is_dir():
        raise ValueError("Select a GameMaker project directory or .yyp file.")
    manifest = load_gamemaker_project_manifest(str(source))
    if manifest.yyp_path is None:
        raise ValueError("The source does not contain a GameMaker .yyp project.")
    with tempfile.TemporaryDirectory(prefix="gm2godot-inventory-") as temporary:
        index = GameMakerResourceIndex(str(source), temporary, log_callback=lambda _message: None)
        index.build()
    models = parse_gamemaker_resource_models(str(source))
    inventory = inventory_resources(source, manifest, models, index)
    entries: list[dict[str, object]] = [
        {
            "name": entry.name, "category": entry.category, "status": entry.status,
            "issueNumber": entry.issue_number, "ownerModule": entry.owner_module,
            "parserSupport": entry.parser_support, "emitterSupport": entry.emitter_support,
            "runtimeSupport": entry.runtime_support, "smokeCoverage": entry.smoke_coverage,
            "docsUrl": entry.docs_url, "notes": entry.notes,
        }
        for entry in iter_gml_api_entries()
    ]
    return {
        "schemaVersion": 1,
        "gm2godotVersion": get_version(),
        "inventory": inventory,
        "gmlApiEntries": entries,
    }


def write_host_snapshot(source_path: str, destination_path: str) -> None:
    """Atomically write a versioned host snapshot outside the source tree."""
    source = Path(source_path).resolve(strict=True)
    source = source.parent if source.is_file() else source
    destination = Path(destination_path).resolve()
    if destination.is_relative_to(source):
        raise ValueError("Deep's host snapshot must be outside the source project.")
    payload = build_host_snapshot(str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".snapshot-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
