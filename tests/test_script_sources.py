"""Script source policy, callback timing and canonical consumer contracts."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from unittest.mock import patch

from src.conversion.asset_registry import AssetRegistryEntry
from src.conversion.gamemaker_json import GameMakerJsonDocument
from src.conversion.json_values import JsonObject
from src.conversion.project_source_paths import ResolvedProjectSourcePath, resolve_project_source_path
from src.conversion.resource_models import parse_gamemaker_resource_models
from src.conversion.script_model import ScriptModel
from src.conversion.script_sources import ScriptPathResolver, ScriptRejectionReporter
from src.conversion.scripts import SCRIPT_REGISTRY_RELATIVE_PATH
from tests.script_source_support import RereadingConverter, ScriptFixture, ScriptReadProbe


class TestScriptSources(ScriptFixture):
    def test_four_path_policies_keep_distinct_name_precedence(self) -> None:
        for filename in ("manifest.gml", "percent.gml", "raw.gml", "owner.gml", "a.gml", "B.GML"):
            self.write_gml(filename)
        self.assert_policy_sources("manifest.gml", "manifest.gml", "owner.gml")
        (self.directory / "manifest.gml").unlink()
        self.assert_policy_sources("a.gml", "percent.gml", "owner.gml")
        (self.directory / "percent.gml").unlink()
        self.assert_policy_sources("a.gml", "raw.gml", "owner.gml")
        (self.directory / "raw.gml").unlink()
        self.assert_policy_sources("a.gml", "owner.gml", "owner.gml")
        (self.directory / "owner.gml").unlink()
        self.assert_policy_sources("a.gml", None, "B.GML")

    def test_preferred_success_and_directory_errors_keep_policy_order(self) -> None:
        preferred = self.write_gml("manifest.gml")
        self.write_gml("owner.gml")
        selectors = self.selectors()
        real_listdir = os.listdir
        calls: list[str] = []

        def listdir(path: str) -> list[str]:
            if os.path.abspath(path) == str(self.directory):
                calls.append(str(path))
                raise OSError("R14 directory enumeration denied")
            return real_listdir(path)

        with patch("os.listdir", side_effect=listdir):
            for label, select in selectors:
                with self.subTest(policy=label):
                    self.assertEqual(select(), str(preferred))
            self.assertEqual(self.dependency_sources(), ("scripts/container/manifest.gml",))
            self.assertEqual(calls, [])
            self.assertIsNone(self.aggregate_source())
            self.assertEqual(calls, [str(self.directory)])
            preferred.unlink()
            self.assertIsNone(selectors[0][1]())
            self.assertIsNone(selectors[1][1]())
            self.assertEqual(len(calls), 3)
            (self.root / self.owner).unlink()
            self.assertIsNone(selectors[0][1]())
            self.assertIsNone(selectors[1][1]())
            self.assertEqual(len(calls), 3)

    def test_suffix_order_and_unsafe_preferred_exclusions(self) -> None:
        self.write_gml("upper.GML")
        fallback = self.write_gml("a.gml")
        self.write_gml("wanted.gml")
        self.write_gml("z.gml")
        for name in ("../wanted", "nested/wanted", "nested\\wanted", "wanted"):
            for label, select in self.selectors(name):
                with self.subTest(name=name, policy=label):
                    self.logs.clear()
                    expected = self.directory / ("wanted.gml" if name == "wanted" else "a.gml")
                    self.assertEqual(select(), str(expected))
                    if name != "wanted":
                        phrase = "must be exactly one safe path component" if label == "conversion" else "must identify exactly one path component"
                        self.assertEqual(len(self.logs), 1)
                        self.assertIn(phrase, self.logs[0])
                        self.assertIn("field preferred script source", self.logs[0])
        fallback.unlink()
        for label, select in self.selectors("../wanted"):
            with self.subTest(policy=label, phase="excluded normalized preferred"):
                self.assertEqual(select(), str(self.directory / "z.gml"))

    def test_source_guards_and_symlink_diagnostics(self) -> None:
        outside = self.parent / "outside.gml"
        outside.write_text("return 99;", encoding="utf-8")
        self.link(self.directory / "manifest.gml", outside)
        contained = self.write_gml("z.gml", "return 7;")
        for label, select in self.selectors():
            with self.subTest(policy=label):
                self.logs.clear()
                self.assertEqual(select(), str(contained))
                self.assertEqual(len(self.logs), 1)
                self.assertIn("symbolic link", self.logs[0])
        self.assertEqual(self.dependency_sources(), ())
        aggregate = parse_gamemaker_resource_models(str(self.root))
        self.assertEqual(aggregate.scripts[0].gml_path, str(contained))
        self.assertEqual(len(aggregate.diagnostics), 1)
        (self.directory / "manifest.gml").unlink()
        self.link(self.directory / "manifest.gml", contained)
        for label, select in self.selectors():
            with self.subTest(policy=label, phase="contained link"):
                self.assertEqual(select(), str(self.directory / "manifest.gml"))
        cross = self.root / "objects/container/owner.yy"
        self.write_json(cross, self.raw)
        (cross.parent / "manifest.gml").write_text("return 8;", encoding="utf-8")
        conversion, registry = self.selectors(source_path="objects/container/owner.yy")
        self.assertIsNone(conversion[1]())
        self.assertEqual(registry[1](), str(cross.parent / "manifest.gml"))
        # Declared-kind validation, including escaping YY links, remains covered
        # by the exact retained public registry/manifest/path tests in selection.json.

    def assert_callback_exception(self, phase: str, label: str) -> None:
        name = "../wanted" if phase == "preferred" else "manifest"
        outside = self.parent / f"outside-{label}.gml"
        outside.write_text("return 99;", encoding="utf-8")
        if phase == "fallback":
            self.link(self.directory / "a.gml", outside)
        self.write_gml("b.gml")
        raised = RuntimeError(f"R14 report {phase} {label}")
        report_counts: list[int] = []

        def report(message: str) -> None:
            self.assertIn("Rejected GameMaker source path", message)
            self.assertEqual(self.diagnostics.diagnostics()[-1].message, message)
            report_counts.append(len(self.diagnostics.diagnostics()))
            raise raised

        selectors = dict(self.selectors(name, report=report))
        with (
            patch("os.listdir", wraps=os.listdir) as enumeration,
            patch("os.path.isfile", wraps=os.path.isfile) as file_checks,
        ):
            with self.assertRaises(RuntimeError) as caught:
                selectors[label]()
        self.assertIs(caught.exception, raised)
        self.assertEqual(len(report_counts), 1)
        self.assertGreater(report_counts[0], 0)
        owner_enumerations = [call for call in enumeration.call_args_list if call.args == (str(self.directory),)]
        self.assertEqual(len(owner_enumerations), 0 if phase == "preferred" else 1)
        self.assertNotIn(str(self.directory / "b.gml"), [str(call.args[0]) for call in file_checks.call_args_list])
        print("\nR14_CALLBACK_EXCEPTION=" + json.dumps({
            "phase": phase, "policy": label, "same_exception": caught.exception is raised,
            "diagnostic_present_at_callback": True, "owner_enumerations": len(owner_enumerations),
        }, sort_keys=True))
        if phase == "fallback":
            (self.directory / "a.gml").unlink()

    def test_report_callback_exception_stops_before_next_candidate(self) -> None:
        for phase in ("preferred", "fallback"):
            for label in ("conversion", "registry"):
                with self.subTest(phase=phase, policy=label):
                    self.assert_callback_exception(phase, label)

    def assert_callback_mutation(self, phase: str, label: str) -> None:
        name = "../wanted" if phase == "preferred" else "manifest"
        outside = self.parent / "outside.gml"
        outside.write_text("return 99;", encoding="utf-8")
        if phase == "fallback":
            self.link(self.directory / "a.gml", outside)
        self.write_gml("b.gml")
        self.write_gml("c.gml")
        actions: list[str] = []
        real_isfile = os.path.isfile

        def isfile(path: str) -> bool:
            actions.append(f"isfile:{os.path.basename(path)}")
            return real_isfile(path)

        def report(message: str) -> None:
            self.assertIn("Rejected GameMaker source path", message)
            self.assertEqual(self.diagnostics.diagnostics()[-1].message, message)
            actions.append("report")
            if phase == "preferred":
                self.write_gml("a.gml")
            else:
                (self.directory / "b.gml").unlink()

        select = dict(self.selectors(name, report=report))[label]
        with patch("os.path.isfile", side_effect=isfile):
            result = select()
        expected = "a.gml" if phase == "preferred" else "c.gml"
        self.assertEqual(result, str(self.directory / expected))
        self.assertEqual(actions.count("report"), 1)
        self.assertLess(actions.index("report"), actions.index(f"isfile:{expected}"))
        if phase == "fallback":
            self.assertLess(actions.index("report"), actions.index("isfile:b.gml"))
            self.assertLess(actions.index("isfile:b.gml"), actions.index("isfile:c.gml"))
        print("\nR14_CALLBACK_MUTATION=" + json.dumps({
            "phase": phase, "policy": label, "actions": actions, "selected": expected,
        }, sort_keys=True))
        for filename in ("a.gml", "b.gml", "c.gml"):
            (self.directory / filename).unlink(missing_ok=True)

    def test_report_callback_mutation_affects_next_candidate(self) -> None:
        for phase in ("preferred", "fallback"):
            for label in ("conversion", "registry"):
                with self.subTest(phase=phase, policy=label):
                    self.assert_callback_mutation(phase, label)
        for label in ("conversion", "registry"):
            with self.subTest(policy=label, mutation="next discovered method"):
                self.assert_fresh_discovered_method(label)

    def assert_fresh_discovered_method(self, label: str) -> None:
        fallback = self.write_gml("a.gml", "function alias() { return 1; }")
        converter = ScriptReadProbe(self.root, self.output, log_callback=self.logs.append,
                                      progress_callback=lambda _: None, conversion_running=lambda: True)
        registry = self.registry()
        context = converter if label == "conversion" else registry
        replacement = context.discovery_spy()
        patcher = patch.object(context, "_resolve_discovered_project_source", replacement)

        def report(message: str) -> None:
            self.assertIn("preferred script source", message)
            patcher.start()
            self.addCleanup(patcher.stop)

        context.log_callback = report
        if label == "conversion":
            self.assertEqual(converter.source_gml_path(self.entry("../wanted", self.owner)), str(fallback))
        else:
            self.assertEqual(registry.names_call("../wanted")(), ("alias",))
        replacement.assert_called_once_with(
            str(fallback), owner_source_path=self.owner, resource="../wanted", resource_type="script",
            field="discovered script source",
        )
        patcher.stop()
        fallback.unlink()

    def test_registry_and_conversion_reread_changed_source(self) -> None:
        source = self.write_gml("manifest.gml", "function before() { return 1; }\n")
        converter = RereadingConverter(
            self.root, self.output, log_callback=self.logs.append,
            progress_callback=lambda _: None, conversion_running=lambda: True,
        )
        converter.replacement_path = source
        converter.replacement_source = "function after() { return 2; }\n"
        with (
            patch("src.conversion.gamemaker_json.open", wraps=open, create=True) as metadata_reads,
            patch("src.conversion.asset_registry.open", wraps=open, create=True) as registry_reads,
            patch("src.conversion.scripts.open", wraps=open, create=True) as script_opens,
        ):
            registry_path = converter.convert_all()
        print("\nR14_REREAD_IO=" + json.dumps({
            "project_root": str(self.root), "output_root": str(self.output),
            "metadata_opens": self.open_records(metadata_reads),
            "registry_opens": self.open_records(registry_reads),
            "script_opens": self.open_records(script_opens),
        }, sort_keys=True))
        self.assertEqual(tuple(entry.name for entry in converter.planned_entries), ("manifest", "before"))
        self.assertEqual(registry_path, str(self.output / SCRIPT_REGISTRY_RELATIVE_PATH))
        generated = (self.output / "scripts/manifest.gd").read_text(encoding="utf-8")
        self.assertIn("return 2", generated)
        self.assertNotIn("return 1", generated)
        self.assertIn("after", generated)
        source_map = json.loads((self.output / "scripts/manifest.gd.gmlmap.json").read_text(encoding="utf-8"))
        self.assertEqual(source_map["event"], "script:manifest")
        self.assertTrue(source_map["entries"])
        self.assertTrue(all(row["source_path"] == str(source) for row in source_map["entries"]))
        published = (self.output / SCRIPT_REGISTRY_RELATIVE_PATH).read_text(encoding="utf-8")
        self.assertIn('"after"', published)
        self.assertNotIn('"before"', published)

    def assert_read_failure(self, case: str) -> None:
        source = self.write_gml("manifest.gml", "function valid() { return 1; }\n")
        names = self.registry().names_call()
        converter = self.converter()
        entry = self.entry("manifest", self.owner)
        if case == "unreadable":
            with patch("src.conversion.asset_registry.open", side_effect=OSError("R14 read denied"), create=True):
                self.assertEqual(names(), ())
            with patch("src.conversion.scripts.open", side_effect=OSError("R14 read denied"), create=True):
                self.assertEqual(converter.write_source(entry), 0)
            self.assertFalse((self.output / "scripts/probe.gd").exists())
            self.assertTrue(any(item.code == "GM2GD-SCRIPT-READ" for item in self.diagnostics.diagnostics()))
            return
        if case == "transpile":
            source.write_text("function bad(argument += 1) {}\n", encoding="utf-8")
        elif case == "conditional":
            source.write_text("#endif\n", encoding="utf-8")
        else:
            source.write_bytes(b"\xff")
        if case == "utf8":
            with self.assertRaises(UnicodeDecodeError):
                names()
            with self.assertRaises(UnicodeDecodeError):
                converter.write_source(entry)
            return
        self.assertEqual(names(), ())
        self.assertEqual(converter.write_source(entry), 0)
        self.assertFalse((self.output / "scripts/probe.gd").exists())
        self.assertTrue(any(item.code == "GM2GD-GML-TRANSPILE" for item in self.diagnostics.diagnostics()))

    def test_read_failures_preserve_exception_boundaries(self) -> None:
        for case in ("unreadable", "conditional", "transpile", "utf8"):
            with self.subTest(case=case):
                self.assert_read_failure(case)

    def test_discovery_revalidates_and_deduplicates_manifest_order(self) -> None:
        first = self.write_gml("manifest.gml")
        alias_dir = self.root / "scripts/alias"
        alias_dir.mkdir()
        self.write_json(alias_dir / "alias.yy", {"resourceType": "GMScript"})
        self.link(alias_dir / "alias.gml", first)
        second_dir = self.root / "scripts/second"
        self.write_json(second_dir / "second.yy", {"resourceType": "GMScript"})
        (second_dir / "second.gml").write_text("return 2;", encoding="utf-8")
        self.write_json(self.root / "project.yyp", {
            "resourceType": "GMProject", "RoomOrderNodes": [], "resources": [
                {"id": {"name": "second", "path": "scripts/second/second.yy"}},
                {"id": {"name": "manifest", "path": self.owner}},
                {"id": {"name": "alias", "path": "scripts/alias/alias.yy"}},
            ],
        })
        resolutions: list[str] = []

        def resolve(root: str, path: str) -> ResolvedProjectSourcePath:
            resolutions.append(path)
            return resolve_project_source_path(root, path)

        with patch("src.conversion.project_source_discovery.resolve_project_source_path", side_effect=resolve):
            result = self.dependency_sources()
        self.assertEqual(result, ("scripts/second/second.gml", "scripts/container/manifest.gml"))
        self.assertEqual(resolutions, [
            "scripts/second/second.yy", "scripts/second/second.gml",
            self.owner, "scripts/container/manifest.gml",
            "scripts/alias/alias.yy", "scripts/alias/alias.gml",
        ])
        # Actual second containment/isfile check: remove after inner resolution.
        def remove_before_revalidation(root: str, path: str) -> ResolvedProjectSourcePath:
            if path == "scripts/second/second.gml":
                (second_dir / "second.gml").unlink()
            return resolve_project_source_path(root, path)

        with patch("src.conversion.project_source_discovery.resolve_project_source_path", side_effect=remove_before_revalidation):
            self.assertEqual(self.dependency_sources(), ("scripts/container/manifest.gml",))
        self.assert_dependency_model_authority()

    def assert_dependency_model_authority(self) -> None:
        self.write_project()
        alternate = self.write_gml("alternate.gml")
        document = GameMakerJsonDocument(str(self.root / self.owner), "raw script", self.raw)

        def names(model: ScriptModel) -> tuple[str, ...]:
            self.assertIs(model.raw_data, document.value)
            self.assertEqual((model.name, model.kind, model.resource_type, model.yy_path, model.yyp_path, model.order), (
                "manifest", "scripts", "GMScript", str(self.root / self.owner), self.owner, 0,
            ))
            return ("alternate",)

        with (
            patch("src.conversion.project_source_discovery.read_gamemaker_json", return_value=document) as reader,
            patch("src.conversion.script_sources.dependency_script_names", side_effect=names) as query,
        ):
            self.assertEqual(self.dependency_sources(), (alternate.relative_to(self.root).as_posix(),))
        reader.assert_called_once_with(str(self.root / self.owner))
        query.assert_called_once()

    def assert_registry_model_input(self, model: ScriptModel, raw: JsonObject) -> None:
        self.assertIs(type(model), ScriptModel)
        self.assertIs(model.raw_data, raw)
        self.assertEqual((model.name, model.kind, model.resource_type, model.yy_path, model.yyp_path, model.order,
                          model.subfolder, model.gml_path), (
            "manifest", "scripts", "GMScript", str(self.root / self.owner), self.owner, 0, "", None,
        ))

    def assert_registry_model_aliases(self, entries: tuple[AssetRegistryEntry, ...]) -> None:
        self.assertEqual(tuple(entry.name for entry in entries), ("manifest", "returned_alias"))
        base, alias = entries
        assert alias.metadata is not None
        self.assertEqual((base.source_path, base.legacy_id, base.tags), (self.owner, self.owner, ("keep",)))
        self.assertEqual((alias.source_path, alias.metadata["script_source_path"], alias.metadata["script_asset"]), (
            "scripts/alternate/alternate.yy", "scripts/alternate/alternate.yy", "returned_owner",
        ))
        self.assertEqual(alias.legacy_id, f"{base.legacy_id}#function:returned_alias")
        self.assertEqual(alias.tags, base.tags)
        self.assertEqual(alias.godot_path, base.godot_path)
        self.assertTrue(alias.metadata["script_function"])

    def test_registry_uses_model_source_and_identity(self) -> None:
        self.raw["tags"] = ["keep"]
        self.write_project()
        self.write_gml("manifest.gml", "function wrong_source() { return 0; }")
        alternate = self.root / "scripts/alternate/alternate.gml"
        self.write_json(alternate.with_suffix(".yy"), {"resourceType": "GMScript"})
        alternate.write_text("function returned_owner() { return 1; }\nfunction returned_alias() { return 2; }",
                             encoding="utf-8")
        registry = self.registry()

        def resolve_model(
            model: ScriptModel, *, resolve: ScriptPathResolver,
            discover: ScriptPathResolver, report: ScriptRejectionReporter,
        ) -> ScriptModel:
            self.assert_registry_model_input(model, registry.raw_source)
            return replace(model, name="returned_owner", yyp_path="scripts/alternate/alternate.yy",
                           gml_path=str(alternate))

        with patch("src.conversion.asset_registry.registry_script_source", side_effect=resolve_model) as select:
            entries, raw = registry.build()
        select.assert_called_once()
        self.assertIs(raw, registry.raw_source)
        self.assert_registry_model_aliases(entries)
