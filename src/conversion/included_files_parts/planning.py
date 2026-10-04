"""Included Files planning ownership."""

from __future__ import annotations

import os
import posixpath

from src.conversion.included_files_parts.converter_ports import IncludedPlanningPort
from src.conversion.included_files_parts.models import (
    DeclaredIncludedFile as _DeclaredIncludedFile,
    IncludedFileConversionPlan as _IncludedFileConversionPlan,
    IncludedFileSource as _IncludedFileSource,
)
from src.conversion.project_manifest import (
    GameMakerProjectManifest,
    ProjectManifestDiagnostic,
    load_gamemaker_project_manifest,
)
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
)


class IncludedPlanningOperations(IncludedPlanningPort):
    def _included_file_conversion_plan(self: IncludedPlanningPort) -> _IncludedFileConversionPlan:
        """Plan logical included files before filtering unavailable sources."""
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="included_file",
        )
        malformed = any(
            diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
            for diagnostic in manifest.diagnostics
        )
        manifest_declares_included_files = (
            "IncludedFiles" in manifest.raw_data
            or "includedFiles" in manifest.raw_data
            or any(
                resource.kind.casefold() == "datafiles"
                or resource.resource_type.casefold() == "gmincludedfile"
                for resource in manifest.resources
            )
            or any(
                self._manifest_diagnostic_is_included_file(diagnostic)
                for diagnostic in manifest.diagnostics
            )
        )
        if (
            manifest.yyp_path is not None
            and not malformed
            and manifest_declares_included_files
        ):
            declared_plan = self._plan_manifest_included_files(manifest)
            # Included Files are directory-backed rather than ordinary Asset
            # Browser resources: current GameMaker automatically reflects
            # contained files added under datafiles even before their YYP
            # metadata is refreshed. Preserve those files while still
            # accounting for stale manifest declarations.
            requested_keys = list(declared_plan.requested_keys)
            available_files = list(declared_plan.available_files)
            seen_keys = set(requested_keys)
            for source in self._discovered_included_files():
                if source.relative_path in seen_keys:
                    continue
                seen_keys.add(source.relative_path)
                requested_keys.append(source.relative_path)
                available_files.append(source)
            return _IncludedFileConversionPlan(
                requested_keys=tuple(requested_keys),
                available_files=tuple(available_files),
                skipped_keys=declared_plan.skipped_keys,
            )

        available_files = self._discovered_included_files()
        return _IncludedFileConversionPlan(
            requested_keys=tuple(
                source.relative_path for source in available_files
            ),
            available_files=available_files,
            skipped_keys=(),
        )

    def _plan_manifest_included_files(
        self: IncludedPlanningPort,
        manifest: GameMakerProjectManifest,
    ) -> _IncludedFileConversionPlan:
        requested_keys: list[str] = []
        available_files: list[_IncludedFileSource] = []
        skipped_keys: list[str] = []
        seen_keys: set[str] = set()

        for declaration in self._declared_included_files(manifest):
            resolved: ResolvedProjectSourcePath | None = None
            unavailable_reason = "its manifest source path was rejected"
            if declaration.source_path is not None:
                resolved = self._resolve_project_source(
                    declaration.source_path,
                    owner_source_path=declaration.owner_source_path,
                    resource=declaration.name,
                    resource_type="included_file",
                    field=declaration.manifest_field,
                )
                if resolved is None:
                    unavailable_reason = "its manifest source path was rejected"

            relative_path = self._declared_relative_path(declaration, resolved)
            if relative_path in seen_keys:
                continue
            seen_keys.add(relative_path)
            requested_keys.append(relative_path)

            if resolved is not None:
                source_root, separator, source_relative = (
                    resolved.source_path.partition("/")
                )
                if (
                    not separator
                    or source_root.casefold() != "datafiles"
                    or not source_relative
                ):
                    self._report_source_path_rejection(
                        declaration.source_path or resolved.source_path,
                        ProjectSourcePathError(
                            "Resolved included-file source must remain under "
                            "the GameMaker 'datafiles' directory"
                        ),
                        owner_source_path=declaration.owner_source_path,
                        resource=declaration.name,
                        resource_type="included_file",
                        field=declaration.manifest_field,
                    )
                    resolved = None
                    unavailable_reason = (
                        "its manifest source path was rejected outside the "
                        "datafiles resource family"
                    )
                elif not os.path.isfile(resolved.filesystem_path):
                    unavailable_reason = (
                        f"the source file is missing at {resolved.source_path!r}"
                    )
                    resolved = None

            if resolved is None:
                skipped_keys.append(relative_path)
                self._report_unavailable_declared_included_file(
                    declaration,
                    reason=unavailable_reason,
                )
                continue

            available_files.append(
                _IncludedFileSource(
                    filesystem_path=resolved.filesystem_path,
                    relative_path=relative_path,
                    owner_source_path=declaration.owner_source_path,
                )
            )

        return _IncludedFileConversionPlan(
            requested_keys=tuple(requested_keys),
            available_files=tuple(available_files),
            skipped_keys=tuple(skipped_keys),
        )

    def _declared_included_files(
        self: IncludedPlanningPort,
        manifest: GameMakerProjectManifest,
    ) -> tuple[_DeclaredIncludedFile, ...]:
        """Return unique included-file declarations from a valid YYP."""
        declared: dict[str, _DeclaredIncludedFile] = {}

        def add(resource: _DeclaredIncludedFile, identity: str) -> None:
            normalized_identity = self._normalized_declaration_path(identity)
            if not normalized_identity:
                normalized_identity = resource.name
            if not normalized_identity:
                return
            declared.setdefault(normalized_identity, resource)

        for included_file in manifest.included_files:
            source = included_file.source
            field = source.field_path if source is not None else None
            raw_field = next(
                (
                    key
                    for key in ("path", "filePath", "filename")
                    if key in included_file.raw_data
                ),
                "path",
            )
            manifest_field = f"{field}.{raw_field}" if field else raw_field
            source_path = included_file.path
            if (
                raw_field == "filePath"
                and included_file.name
                and posixpath.basename(source_path) != included_file.name
            ):
                # Current GameMaker YYP files store the containing directory in
                # ``filePath`` and the payload filename separately in ``name``.
                source_path = posixpath.join(source_path, included_file.name)
            add(
                _DeclaredIncludedFile(
                    name=included_file.name or included_file.path,
                    source_path=source_path,
                    owner_source_path=manifest.yyp_path or "",
                    manifest_field=manifest_field,
                ),
                source_path or included_file.name,
            )

        for resource in manifest.resources:
            if (
                resource.kind.casefold() != "datafiles"
                and resource.resource_type.casefold() != "gmincludedfile"
            ):
                continue
            field = (
                f"{resource.source.field_path}.id.path"
                if resource.source is not None and resource.source.field_path
                else "resources[].id.path"
            )
            add(
                _DeclaredIncludedFile(
                    name=resource.name,
                    source_path=resource.path,
                    owner_source_path=manifest.yyp_path or "",
                    manifest_field=field,
                ),
                resource.path,
            )

        for diagnostic in manifest.diagnostics:
            if (
                diagnostic.code != "GM2GD-SOURCE-PATH-REJECTED"
                or not diagnostic.resource
                or not self._manifest_diagnostic_is_included_file(diagnostic)
            ):
                continue
            source = diagnostic.source
            field = source.field_path if source is not None else None
            add(
                _DeclaredIncludedFile(
                    name=diagnostic.resource,
                    source_path=None,
                    owner_source_path=(
                        source.path
                        if source is not None
                        else manifest.yyp_path or ""
                    ),
                    manifest_field=field,
                ),
                f"rejected:{diagnostic.resource}",
            )

        return tuple(declared.values())

    @staticmethod
    def _manifest_diagnostic_is_included_file(
        diagnostic: ProjectManifestDiagnostic,
    ) -> bool:
        resource_kind = diagnostic.resource_kind
        resource_type = diagnostic.resource_type
        return (
            isinstance(resource_kind, str)
            and resource_kind.casefold() == "datafiles"
        ) or (
            isinstance(resource_type, str)
            and resource_type.casefold()
            in {"included_file", "includedfile", "gmincludedfile"}
        )

    @staticmethod
    def _normalized_declaration_path(path: str) -> str:
        normalized = posixpath.normpath(path.replace("\\", "/").strip())
        return "" if normalized in {"", "."} else normalized

    def _declared_relative_path(
        self: IncludedPlanningPort,
        declaration: _DeclaredIncludedFile,
        resolved: ResolvedProjectSourcePath | None,
    ) -> str:
        if resolved is not None:
            source_root, separator, source_relative = (
                resolved.source_path.partition("/")
            )
            if (
                separator
                and source_root.casefold() == "datafiles"
                and source_relative
            ):
                return source_relative

        fallback = self._normalized_declaration_path(
            declaration.source_path or declaration.name
        )
        source_root, separator, source_relative = fallback.partition("/")
        if (
            separator
            and source_root.casefold() == "datafiles"
            and source_relative
        ):
            return source_relative
        return fallback or declaration.name

    included_file_conversion_plan = _included_file_conversion_plan
    plan_manifest_included_files = _plan_manifest_included_files
    declared_included_files = _declared_included_files
    manifest_diagnostic_is_included_file = _manifest_diagnostic_is_included_file
    normalized_declaration_path = _normalized_declaration_path
    declared_relative_path = _declared_relative_path













_included_file_conversion_plan = IncludedPlanningOperations.included_file_conversion_plan
included_file_conversion_plan = _included_file_conversion_plan
_plan_manifest_included_files = IncludedPlanningOperations.plan_manifest_included_files
plan_manifest_included_files = _plan_manifest_included_files
_declared_included_files = IncludedPlanningOperations.declared_included_files
declared_included_files = _declared_included_files
_manifest_diagnostic_is_included_file = IncludedPlanningOperations.manifest_diagnostic_is_included_file
manifest_diagnostic_is_included_file = _manifest_diagnostic_is_included_file
_normalized_declaration_path = IncludedPlanningOperations.normalized_declaration_path
normalized_declaration_path = _normalized_declaration_path
_declared_relative_path = IncludedPlanningOperations.declared_relative_path
declared_relative_path = _declared_relative_path
