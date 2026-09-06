"""Finite fixture and real-consumer probes for script source contracts."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from src.conversion.asset_registry import AssetRegistryConverter, AssetRegistryEntry
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.json_values import JsonObject
from src.conversion.project_source_discovery import project_gml_source_paths
from src.conversion.resource_models import parse_gamemaker_resource_models
from src.conversion.script_model import ScriptModel
from src.conversion.script_sources import registry_script_source
from src.conversion.scripts import ScriptConverter
from tests.test_scripts import ScriptSourceProbe


class RegistrySourceProbe(AssetRegistryConverter):
    def discovery_spy(self) -> Mock:
        return Mock(wraps=self._resolve_discovered_project_source)

    def source_call(self, name: str, source_path: str) -> Callable[[], str | None]:
        resource = replace(
            self._ordered_project_resources()[0], name=name, source_path=source_path,
        )
        model = ScriptModel(
            name=resource.name, kind="scripts", resource_type="GMScript",
            yy_path=resource.yy_path, yyp_path=resource.source_path, order=0,
            raw_data=resource.raw_data,
        )
        return lambda: registry_script_source(
            model,
            resolve=lambda path, owner, field: self._resolve_project_source(
                path, owner_source_path=owner, resource=name, resource_type="script", field=field,
            ),
            discover=lambda path, owner, field: self._resolve_discovered_project_source(
                path, owner_source_path=owner, resource=name, resource_type="script", field=field,
            ),
            report=lambda path, error, owner, field: self._report_source_path_rejection(
                path, error, owner_source_path=owner, resource=name, resource_type="script", field=field,
            ),
        ).gml_path

    def names_call(self, name: str | None = None) -> Callable[[], tuple[str, ...]]:
        resource = self._ordered_project_resources()[0]
        if name is not None:
            resource = replace(resource, name=name)
        return lambda: self._script_model_and_function_names(resource)[1]

    def build(self) -> tuple[tuple[AssetRegistryEntry, ...], JsonObject]:
        resources = self._ordered_project_resources()
        self.raw_source = resources[0].raw_data
        entries, _ = self._build_entries_from_resources(resources)
        return entries, self.raw_source



class RereadingConverter(ScriptConverter):
    planned_entries: tuple[AssetRegistryEntry, ...] = ()
    replacement_path: Path
    replacement_source: str

    def _registry_entries(self) -> tuple[AssetRegistryEntry, ...]:
        self.planned_entries = super()._registry_entries()
        self.replacement_path.write_text(self.replacement_source, encoding="utf-8")
        return self.planned_entries


class ScriptReadProbe(ScriptSourceProbe):
    def discovery_spy(self) -> Mock:
        return Mock(wraps=self._resolve_discovered_project_source)

    def write_source(self, entry: AssetRegistryEntry) -> int:
        return len(self._write_script(
            entry, asset_names={entry.name}, script_entries_by_name={entry.name: entry},
            extension_functions={}, extension_function_mappings={}, enum_values={}, macro_values={},
        ))


class ScriptFixture(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name)
        self.root = self.parent / "project"
        self.output = self.parent / "output"
        self.root.mkdir()
        self.output.mkdir()
        self.owner = "scripts/container/owner.yy"
        self.directory = self.root / "scripts/container"
        self.directory.mkdir(parents=True)
        self.logs: list[str] = []
        self.diagnostics = DiagnosticCollector()
        self.raw: JsonObject = {
            "%Name": "percent", "name": "raw", "resourceType": "GMScript",
        }
        self.write_project()

    def write_json(self, path: Path, value: JsonObject) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def write_project(self, name: str = "manifest") -> None:
        self.write_json(self.root / self.owner, self.raw)
        self.write_json(self.root / "project.yyp", {
            "resourceType": "GMProject", "RoomOrderNodes": [],
            "resources": [{"id": {"name": name, "path": self.owner}}],
        })

    def write_gml(self, name: str, source: str = "return 1;") -> Path:
        path = self.directory / name
        path.write_text(source, encoding="utf-8")
        return path

    def entry(self, name: str, source_path: str) -> AssetRegistryEntry:
        return AssetRegistryEntry(
            id=1, name=name, kind="scripts", asset_type="script", type_name="Script",
            source_path=source_path, godot_path="res://scripts/probe.gd",
            legacy_id=source_path,
        )

    def selectors(
        self, name: str = "manifest", source_path: str | None = None,
        report: Callable[[str], None] | None = None,
    ) -> tuple[tuple[str, Callable[[], str | None]], ...]:
        owner = self.owner if source_path is None else source_path
        callback = self.logs.append if report is None else report
        converter = ScriptSourceProbe(
            self.root, self.output, log_callback=callback,
            progress_callback=lambda _: None, conversion_running=lambda: True,
            diagnostics=self.diagnostics,
        )
        registry = RegistrySourceProbe(
            self.root, self.output, log_callback=callback,
            progress_callback=lambda _: None, conversion_running=lambda: True,
            diagnostics=self.diagnostics,
        )
        registry_call = registry.source_call(name, owner)
        entry = self.entry(name, owner)
        return (("conversion", lambda: converter.source_gml_path(entry)),
                ("registry", registry_call))

    def registry(self) -> RegistrySourceProbe:
        return RegistrySourceProbe(
            self.root, self.output, log_callback=self.logs.append,
            progress_callback=lambda _: None, conversion_running=lambda: True,
            diagnostics=self.diagnostics,
        )

    def converter(self) -> ScriptReadProbe:
        return ScriptReadProbe(
            self.root, self.output, log_callback=self.logs.append,
            progress_callback=lambda _: None, conversion_running=lambda: True,
            diagnostics=self.diagnostics,
        )

    def aggregate_source(self) -> str | None:
        models = parse_gamemaker_resource_models(str(self.root))
        self.assertEqual(len(models.scripts), 1)
        return models.scripts[0].gml_path

    def dependency_sources(self) -> tuple[str, ...]:
        return tuple(item.source_path for item in project_gml_source_paths(self.root))

    def assert_policy_sources(self, preferred: str, dependency: str | None, aggregate: str) -> None:
        for label, select in self.selectors():
            with self.subTest(policy=label):
                self.assertEqual(select(), str(self.directory / preferred))
        expected = () if dependency is None else (f"scripts/container/{dependency}",)
        self.assertEqual(self.dependency_sources(), expected)
        self.assertEqual(self.aggregate_source(), str(self.directory / aggregate))

    def link(self, path: Path, target: Path) -> None:
        try:
            path.symlink_to(target)
        except (NotImplementedError, OSError) as error:
            self.fail(f"Script source characterization requires working symlinks: {error}")

    def open_records(self, observed: Mock) -> list[dict[str, str]]:
        return [{
            "path": str(call.args[0]),
            "mode": str(call.args[1]) if len(call.args) > 1 else "r",
            "encoding": str(call.kwargs.get("encoding")),
        } for call in observed.call_args_list]


