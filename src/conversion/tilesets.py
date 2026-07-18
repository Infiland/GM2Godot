from __future__ import annotations

import os
import re
import json
import shutil
import posixpath
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict, cast

from src.localization import get_localized
from src.conversion.asset_output_paths import (
    build_asset_output_paths,
    resource_filesystem_path,
    resource_sibling_path,
)
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.generated_paths import (
    generated_nested_resource_path,
)
from src.conversion.project_manifest import load_gamemaker_project_manifest
from src.conversion.project_source_paths import (
    is_safe_project_source_component,
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
    validate_project_resource_source_path,
)
from src.conversion.type_defs import ConversionRunning, JsonDict, LogCallback, ProgressCallback, StrPath


class TilesetData(TypedDict):
    source_path: str
    sprite_name: str
    sprite_path: str
    sprite_reference_field: str
    tileWidth: int
    tileHeight: int
    tilehsep: int
    tilevsep: int
    tilexoff: int
    tileyoff: int
    tile_count: int
    out_columns: int
    tileAnimationFrames: list[JsonDict]
    tileAnimationSpeed: float
    brushes: list[JsonDict]
    autoTileSets: list[JsonDict]
    tileSetCollisions: list[JsonDict]
    out_tilehborder: int
    out_tilevborder: int


class TilesetSuccess(TypedDict):
    success: Literal[True]
    name: str
    tileset_data: TilesetData


class TilesetFailure(TypedDict):
    success: Literal[False]
    name: str
    error: str
    sprite_name: NotRequired[str]


TilesetResult = TilesetSuccess | TilesetFailure


@dataclass(frozen=True)
class _DeclaredTilesetResource:
    name: str
    source_path: str | None
    owner_source_path: str
    manifest_field: str


class TileSetConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath, log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None, conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback,
                         progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers,
                         diagnostics=diagnostics)
        self.godot_tilesets_path = os.path.join(self.godot_project_path, 'tilesets')
        self._tileset_output_paths: dict[str, str] = {}
        self._tileset_source_paths: dict[str, str] = {}
        self._yyp_declared_tilesets: dict[str, _DeclaredTilesetResource] = {}

    def _get_valid_tileset_names(self) -> dict[str, str] | None:
        """Parse the .yyp project file and return a dict of tileset name -> subfolder.

        Returns None if the .yyp file cannot be found or parsed, allowing
        the caller to fall back to converting all tilesets on disk.
        """
        self._tileset_source_paths = {}
        self._yyp_declared_tilesets = {}
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        manifest_rejected_fields = self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="tileset",
            include_project_sources=True,
        )
        if manifest.yyp_path is None or any(
            diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
            for diagnostic in manifest.diagnostics
        ):
            return None
        yyp_source = self._resolve_discovered_project_source(
            manifest.yyp_path,
            resource_type="project",
            field="projectFile",
        )
        if yyp_source is None:
            return None

        valid_tilesets: dict[str, str] = {}
        resources = manifest.raw_data.get('resources', [])
        if not isinstance(resources, list):
            return valid_tilesets
        for index, resource in enumerate(cast(list[object], resources)):
            if not isinstance(resource, dict):
                continue
            resource_data = cast(JsonDict, resource)
            raw_id = resource_data.get('id', {})
            if not isinstance(raw_id, dict):
                continue
            res_id = cast(JsonDict, raw_id)
            raw_path = res_id.get('path', '')
            path = raw_path.replace('\\', '/') if isinstance(raw_path, str) else ""
            resource_type = resource_data.get('resourceType')
            id_resource_type = res_id.get('resourceType')
            is_tileset = (
                path.partition('/')[0].casefold() == 'tilesets'
                or resource_type == "GMTileSet"
                or id_resource_type == "GMTileSet"
            )
            if not is_tileset:
                continue

            raw_name = res_id.get('name', '')
            name = (
                raw_name
                if isinstance(raw_name, str) and raw_name
                else os.path.splitext(os.path.basename(path))[0]
            )
            if not name:
                continue
            field = f"resources[{index}].id.path"
            self._yyp_declared_tilesets.setdefault(
                name,
                _DeclaredTilesetResource(
                    name=name,
                    source_path=raw_path if isinstance(raw_path, str) else None,
                    owner_source_path=yyp_source.source_path,
                    manifest_field=field,
                ),
            )
            if not isinstance(raw_path, str) or not raw_path:
                continue
            if field in manifest_rejected_fields:
                continue
            resolved_path = self._resolve_project_source(
                path,
                owner_source_path=yyp_source.source_path,
                resource=name,
                resource_type="tileset",
                field=field,
            )
            if resolved_path is None or not self._source_has_resource_kind(
                resolved_path,
                "tilesets",
                rejected_path=path,
                owner_source_path=yyp_source.source_path,
                resource=name,
                field=field,
            ):
                continue
            yy_path = resolved_path.filesystem_path
            if not os.path.isfile(yy_path):
                continue
            self._tileset_source_paths[name] = resolved_path.source_path
            valid_tilesets[name] = self._get_subfolder_from_yy(yy_path)

        return valid_tilesets

    def _report_unavailable_declared_tileset(
        self,
        resource: _DeclaredTilesetResource,
        *,
        reason: str,
    ) -> None:
        message = (
            "Warning: Skipping manifest-declared GameMaker tileset "
            f"{resource.name!r} because {reason}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-TILESET-SOURCE-UNAVAILABLE",
                message,
                source_path=self._diagnostic_source_path(
                    resource.owner_source_path
                ),
                resource=resource.name,
                resource_type="tileset",
                manifest_entry=resource.manifest_field,
                workaround=(
                    "Restore the declared GameMaker tileset .yy metadata inside "
                    "the project root or remove the stale YYP declaration."
                ),
            )
        self._safe_log(message)

    def _source_has_resource_kind(
        self,
        resolved: ResolvedProjectSourcePath,
        resource_kind: str,
        *,
        rejected_path: str,
        owner_source_path: StrPath,
        resource: str,
        field: str,
    ) -> bool:
        try:
            validate_project_resource_source_path(resolved, resource_kind)
            return True
        except ProjectSourcePathError as error:
            self._report_source_path_rejection(
                rejected_path,
                error,
                owner_source_path=owner_source_path,
                resource=resource,
                resource_type="tileset",
                field=field,
            )
            return False

    def _resolve_tileset_yy_source(
        self,
        tileset_name: str,
        source_path: str | None = None,
    ) -> ResolvedProjectSourcePath | None:
        declared_source_path = source_path or self._tileset_source_paths.get(
            tileset_name
        )
        if declared_source_path is not None:
            rejected_path = declared_source_path
            owner_source_path = os.path.dirname(declared_source_path)
            resolved = self._resolve_project_source(
                declared_source_path,
                resource=tileset_name,
                resource_type="tileset",
                field="tileset .yy",
            )
        else:
            candidate = os.path.join(
                self.gm_project_path,
                'tilesets',
                tileset_name,
                tileset_name + '.yy',
            )
            rejected_path = candidate
            owner_source_path = os.path.dirname(candidate)
            resolved = self._resolve_discovered_project_source(
                candidate,
                owner_source_path=os.path.dirname(candidate),
                resource=tileset_name,
                resource_type="tileset",
                field="tileset .yy",
            )
        if resolved is None:
            return None
        if not self._source_has_resource_kind(
            resolved,
            "tilesets",
            rejected_path=rejected_path,
            owner_source_path=owner_source_path,
            resource=tileset_name,
            field="tileset .yy",
        ):
            return None
        self._tileset_source_paths[tileset_name] = resolved.source_path
        return resolved

    def _parse_tileset_yy(
        self,
        tileset_name: str,
        source_path: str | None = None,
    ) -> TilesetData | None:
        """Read and parse a tileset .yy file.

        Returns a dict with tileset properties, or None on failure.
        """
        resolved_tileset = self._resolve_tileset_yy_source(
            tileset_name,
            source_path,
        )
        if resolved_tileset is None:
            return None
        yy_path = resolved_tileset.filesystem_path
        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = cast(JsonDict, json.loads(cleaned))

            sprite_reference = self._resolve_sprite_reference(
                tileset_name,
                resolved_tileset.source_path,
                data.get('spriteId'),
            )
            sprite_name = ""
            sprite_path = ""
            sprite_reference_field = "spriteId"
            if sprite_reference is not None:
                sprite_name, sprite_path, sprite_reference_field = sprite_reference
            return {
                "source_path": resolved_tileset.source_path,
                "sprite_name": sprite_name,
                "sprite_path": sprite_path,
                "sprite_reference_field": sprite_reference_field,
                "tileWidth": int(data.get('tileWidth', 16)),
                "tileHeight": int(data.get('tileHeight', 16)),
                "tilehsep": int(data.get('tilehsep', 0)),
                "tilevsep": int(data.get('tilevsep', 0)),
                "tilexoff": int(data.get('tilexoff', 0)),
                "tileyoff": int(data.get('tileyoff', 0)),
                "tile_count": int(data.get('tile_count', 0)),
                "out_columns": int(data.get('out_columns', 0)),
                "tileAnimationFrames": _json_dict_list(data.get("tileAnimationFrames")),
                "tileAnimationSpeed": _float(data.get("tileAnimationSpeed"), 15.0),
                "brushes": _json_dict_list(data.get("brushes")),
                "autoTileSets": _json_dict_list(data.get("autoTileSets")),
                "tileSetCollisions": _json_dict_list(data.get("tileSetCollisions")),
                "out_tilehborder": int(data.get("out_tilehborder", 0)),
                "out_tilevborder": int(data.get("out_tilevborder", 0)),
            }
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _resolve_sprite_reference(
        self,
        tileset_name: str,
        tileset_source_path: str,
        raw_sprite_id: object,
    ) -> tuple[str, str, str] | None:
        if raw_sprite_id is None:
            return None
        if not isinstance(raw_sprite_id, dict):
            self._reject_sprite_reference(
                tileset_name,
                tileset_source_path,
                repr(raw_sprite_id),
                "spriteId",
                "GameMaker tileset spriteId must be an object",
            )
            return None

        sprite_id = cast(JsonDict, raw_sprite_id)
        if "path" in sprite_id:
            raw_path = sprite_id.get("path")
            if not isinstance(raw_path, str) or not raw_path:
                self._reject_sprite_reference(
                    tileset_name,
                    tileset_source_path,
                    raw_path if isinstance(raw_path, str) else repr(raw_path),
                    "spriteId.path",
                    "GameMaker tileset spriteId.path must be a non-empty string",
                )
                return None
            resolved = self._resolve_project_source(
                raw_path,
                owner_source_path=tileset_source_path,
                resource=tileset_name,
                resource_type="tileset",
                field="spriteId.path",
            )
            if resolved is None or not self._source_has_resource_kind(
                resolved,
                "sprites",
                rejected_path=raw_path,
                owner_source_path=tileset_source_path,
                resource=tileset_name,
                field="spriteId.path",
            ):
                return None
            sprite_name = posixpath.splitext(
                posixpath.basename(resolved.source_path)
            )[0]
            return sprite_name, resolved.source_path, "spriteId.path"

        raw_name = sprite_id.get("name")
        if not isinstance(raw_name, str) or not self._valid_reference_component(
            raw_name
        ):
            self._reject_sprite_reference(
                tileset_name,
                tileset_source_path,
                raw_name if isinstance(raw_name, str) else repr(raw_name),
                "spriteId.name",
                "Legacy GameMaker tileset spriteId.name must be a safe resource name",
            )
            return None

        legacy_path = f"sprites/{raw_name}/{raw_name}.yy"
        resolved = self._resolve_project_source(
            legacy_path,
            owner_source_path=tileset_source_path,
            resource=tileset_name,
            resource_type="tileset",
            field="spriteId.name",
        )
        if resolved is None or not self._source_has_resource_kind(
            resolved,
            "sprites",
            rejected_path=legacy_path,
            owner_source_path=tileset_source_path,
            resource=tileset_name,
            field="spriteId.name",
        ):
            return None
        return raw_name, resolved.source_path, "spriteId.name"

    def _reject_sprite_reference(
        self,
        tileset_name: str,
        tileset_source_path: str,
        rejected_path: str,
        field: str,
        message: str,
    ) -> None:
        self._report_source_path_rejection(
            rejected_path,
            ProjectSourcePathError(f"{message}: {rejected_path!r}"),
            owner_source_path=tileset_source_path,
            resource=tileset_name,
            resource_type="tileset",
            field=field,
        )

    @staticmethod
    def _valid_reference_component(value: str) -> bool:
        return is_safe_project_source_component(value)

    def _find_sprite_image(
        self,
        sprite_name: str,
        sprite_source_path: str | None = None,
        *,
        tileset_name: str | None = None,
        tileset_source_path: str | None = None,
        sprite_reference_field: str = "spriteId.path",
    ) -> tuple[ResolvedProjectSourcePath, str] | None:
        """Find the primary layer image for a sprite referenced by a tileset.

        Parses the sprite's .yy to identify the first visible layer, then
        locates the corresponding PNG under layers/{frame_guid}/{layer_guid}.png.
        Returns the contained image source and owning sprite field, or None.
        """
        resource_name = tileset_name or sprite_name
        if sprite_source_path is None:
            if not self._valid_reference_component(sprite_name):
                return None
            sprite_source_path = f"sprites/{sprite_name}/{sprite_name}.yy"
            sprite_reference_field = "spriteId.name"

        resolved_sprite = self._resolve_project_source(
            sprite_source_path,
            owner_source_path=tileset_source_path,
            resource=resource_name,
            resource_type="tileset",
            field=sprite_reference_field,
        )
        if resolved_sprite is None or not self._source_has_resource_kind(
            resolved_sprite,
            "sprites",
            rejected_path=sprite_source_path,
            owner_source_path=tileset_source_path or resolved_sprite.source_path,
            resource=resource_name,
            field=sprite_reference_field,
        ):
            return None

        sprite_dir = os.path.dirname(resolved_sprite.filesystem_path)
        yy_path = resolved_sprite.filesystem_path

        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = cast(JsonDict, json.loads(cleaned))

            # Get the first frame GUID
            raw_frames = data.get('frames', [])
            if not isinstance(raw_frames, list) or not raw_frames:
                return None
            raw_frame = cast(list[object], raw_frames)[0]
            if not isinstance(raw_frame, dict):
                self._reject_sprite_reference(
                    resource_name,
                    resolved_sprite.source_path,
                    repr(raw_frame),
                    "frames[0]",
                    "GameMaker sprite frame reference must be an object",
                )
                return None
            frame_value = cast(JsonDict, raw_frame).get('name', '')
            if not isinstance(frame_value, str) or not self._valid_reference_component(
                frame_value
            ):
                self._reject_sprite_reference(
                    resource_name,
                    resolved_sprite.source_path,
                    frame_value if isinstance(frame_value, str) else repr(frame_value),
                    "frames[0].name",
                    "GameMaker sprite frame name must be a safe path component",
                )
                return None
            frame_guid = frame_value

            # Get the primary visible layer GUID
            raw_layers = data.get('layers', [])
            if not isinstance(raw_layers, list) or not raw_layers:
                return None
            layers: list[tuple[int, JsonDict]] = []
            for index, raw_layer in enumerate(cast(list[object], raw_layers)):
                if not isinstance(raw_layer, dict):
                    continue
                layers.append((index, cast(JsonDict, raw_layer)))
            if not layers:
                return None

            primary_layer: tuple[int, JsonDict] | None = None
            for index, layer in layers:
                if layer.get('visible', True):
                    primary_layer = (index, layer)
                    break
            if primary_layer is None:
                primary_layer = layers[0]

            layer_index, layer = primary_layer
            layer_value = layer.get('name', '')
            if not isinstance(layer_value, str) or not self._valid_reference_component(
                layer_value
            ):
                self._reject_sprite_reference(
                    resource_name,
                    resolved_sprite.source_path,
                    layer_value if isinstance(layer_value, str) else repr(layer_value),
                    f"layers[{layer_index}].name",
                    "GameMaker sprite layer name must be a safe path component",
                )
                return None
            primary_layer_guid = layer_value

            # Look for the image at layers/{frame_guid}/{layer_guid}.png
            layers_path = os.path.join(sprite_dir, 'layers')
            resolved_layers = self._resolve_discovered_project_source(
                layers_path,
                owner_source_path=resolved_sprite.source_path,
                resource=resource_name,
                resource_type="tileset",
                field="layers",
            )
            if resolved_layers is None:
                return None

            frame_path = os.path.join(
                resolved_layers.filesystem_path,
                frame_guid,
            )
            resolved_frame = self._resolve_discovered_project_source(
                frame_path,
                owner_source_path=resolved_sprite.source_path,
                resource=resource_name,
                resource_type="tileset",
                field="frames[0].name",
            )
            if resolved_frame is None:
                return None

            image_path = os.path.join(
                resolved_frame.filesystem_path,
                primary_layer_guid + '.png',
            )
            resolved_image = self._resolve_discovered_project_source(
                image_path,
                owner_source_path=resolved_sprite.source_path,
                resource=resource_name,
                resource_type="tileset",
                field=f"layers[{layer_index}].name",
            )
            if resolved_image is None:
                return None
            if os.path.isfile(resolved_image.filesystem_path):
                return resolved_image, f"layers[{layer_index}].name"

        except (OSError, json.JSONDecodeError, KeyError, TypeError, IndexError, ValueError):
            pass

        # Fallback: look for any PNG in the layers directory
        layers_dir = os.path.join(sprite_dir, 'layers')
        return self._find_fallback_sprite_png(
            layers_dir,
            tileset_name=resource_name,
            sprite_source_path=resolved_sprite.source_path,
            field="layers",
        )

    def _find_fallback_sprite_png(
        self,
        directory: str,
        *,
        tileset_name: str,
        sprite_source_path: str,
        field: str,
    ) -> tuple[ResolvedProjectSourcePath, str] | None:
        resolved_directory = self._resolve_discovered_project_source(
            directory,
            owner_source_path=sprite_source_path,
            resource=tileset_name,
            resource_type="tileset",
            field=field,
        )
        if resolved_directory is None or not os.path.isdir(
            resolved_directory.filesystem_path
        ):
            return None

        try:
            entries = os.listdir(resolved_directory.filesystem_path)
        except OSError:
            return None

        resolved_entries: list[tuple[str, ResolvedProjectSourcePath]] = []
        for entry in entries:
            candidate = os.path.join(resolved_directory.filesystem_path, entry)
            resolved_candidate = self._resolve_discovered_project_source(
                candidate,
                owner_source_path=sprite_source_path,
                resource=tileset_name,
                resource_type="tileset",
                field=field,
            )
            if resolved_candidate is not None:
                resolved_entries.append((entry, resolved_candidate))

        for entry, resolved_candidate in resolved_entries:
            if entry.lower().endswith('.png') and os.path.isfile(
                resolved_candidate.filesystem_path
            ):
                return resolved_candidate, field

        for _entry, resolved_candidate in resolved_entries:
            if (
                not os.path.isdir(resolved_candidate.filesystem_path)
                or os.path.islink(resolved_candidate.filesystem_path)
            ):
                continue
            image_path = self._find_fallback_sprite_png(
                resolved_candidate.filesystem_path,
                tileset_name=tileset_name,
                sprite_source_path=sprite_source_path,
                field=field,
            )
            if image_path is not None:
                return image_path
        return None

    def _generate_tileset_tres(
        self,
        tileset_name: str,
        tileset_data: TilesetData,
        subfolder: str = "",
        resource_path: str | None = None,
    ) -> str:
        """Generate a Godot TileSet .tres resource string."""
        tile_w = tileset_data["tileWidth"]
        tile_h = tileset_data["tileHeight"]
        tilehsep = tileset_data["tilehsep"]
        tilevsep = tileset_data["tilevsep"]
        tilexoff = tileset_data["tilexoff"]
        tileyoff = tileset_data["tileyoff"]

        tres_resource_path = resource_path or generated_nested_resource_path(
            "tilesets", subfolder, tileset_name, ".tres"
        )
        res_path = resource_sibling_path(tres_resource_path, ".png")

        lines: list[str] = []
        lines.append('[gd_resource type="TileSet" format=3]')
        lines.append('')
        lines.append(f'[ext_resource type="Texture2D" path="{res_path}" id="1"]')
        lines.append('')
        lines.append('[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_1"]')
        lines.append('texture = ExtResource("1")')
        lines.append(f'texture_region_size = Vector2i({tile_w}, {tile_h})')

        if tilehsep or tilevsep:
            lines.append(f'separation = Vector2i({tilehsep}, {tilevsep})')
        if tilexoff or tileyoff:
            lines.append(f'margins = Vector2i({tilexoff}, {tileyoff})')

        for atlas_x, atlas_y in self._tileset_atlas_coordinates(tileset_data):
            lines.append(f'{atlas_x}:{atlas_y}/0 = 0')

        lines.append('')
        lines.append('[resource]')
        lines.append(f'tile_size = Vector2i({tile_w}, {tile_h})')
        lines.append('sources/0 = SubResource("TileSetAtlasSource_1")')
        lines.append(f"metadata/gamemaker_tileset_tile_count = {tileset_data['tile_count']}")
        lines.append(f"metadata/gamemaker_tileset_out_columns = {tileset_data['out_columns']}")
        lines.append(f"metadata/gamemaker_tileset_animation_speed = {_format_number(tileset_data['tileAnimationSpeed'])}")
        lines.append(
            "metadata/gamemaker_tileset_animation_frames = "
            + json.dumps(tileset_data["tileAnimationFrames"])
        )
        lines.append("metadata/gamemaker_tileset_brushes = " + json.dumps(tileset_data["brushes"]))
        lines.append("metadata/gamemaker_tileset_auto_tile_sets = " + json.dumps(tileset_data["autoTileSets"]))
        lines.append(
            "metadata/gamemaker_tileset_collisions = "
            + json.dumps(tileset_data["tileSetCollisions"])
        )
        lines.append(f"metadata/gamemaker_tileset_out_tilehborder = {tileset_data['out_tilehborder']}")
        lines.append(f"metadata/gamemaker_tileset_out_tilevborder = {tileset_data['out_tilevborder']}")
        lines.append('')

        return '\n'.join(lines)

    def _tileset_atlas_coordinates(self, tileset_data: TilesetData) -> list[tuple[int, int]]:
        tile_count = max(0, tileset_data["tile_count"])
        columns = tileset_data["out_columns"] if tileset_data["out_columns"] > 0 else tile_count
        columns = max(1, columns)
        return [(index % columns, index // columns) for index in range(tile_count)]

    def _process_tileset(
        self,
        tileset_name: str,
        subfolder: str = "",
        tileset_source_path: str | None = None,
    ) -> TilesetResult | None:
        """Process a single tileset: parse, copy image, generate .tres.

        Returns a dict with conversion results, or None if stopped.
        """
        if not self.conversion_running():
            return None

        tileset_data = self._parse_tileset_yy(
            tileset_name,
            tileset_source_path,
        )
        if tileset_data is None:
            return {"success": False, "name": tileset_name, "error": "parse_failed"}

        sprite_name = tileset_data["sprite_name"]
        sprite_path = tileset_data["sprite_path"]
        image_match = (
            self._find_sprite_image(
                sprite_name,
                sprite_path,
                tileset_name=tileset_name,
                tileset_source_path=tileset_data["source_path"],
                sprite_reference_field=tileset_data["sprite_reference_field"],
            )
            if sprite_path
            else None
        )
        if image_match is None:
            self._safe_log(get_localized("Console_Convertor_Tilesets_SpriteNotFound").format(
                name=tileset_name, sprite_name=sprite_name))
            return {"success": False, "name": tileset_name, "error": "sprite_not_found",
                    "sprite_name": sprite_name}

        # Create output directory
        tres_resource_path = self._tileset_output_paths.get(
            tileset_name,
            generated_nested_resource_path(
                "tilesets", subfolder, tileset_name, ".tres"
            ),
        )
        tres_path = resource_filesystem_path(
            self.godot_project_path,
            tres_resource_path,
        )
        output_dir = os.path.dirname(tres_path)
        os.makedirs(output_dir, exist_ok=True)

        # Copy the sprite image as the tileset texture
        tileset_stem = os.path.splitext(os.path.basename(tres_path))[0]
        dest_image = os.path.join(output_dir, tileset_stem + '.png')
        image_source, image_field = image_match
        resolved_image = self._resolve_discovered_project_source(
            image_source.filesystem_path,
            owner_source_path=sprite_path,
            resource=tileset_name,
            resource_type="tileset",
            field=image_field,
        )
        if resolved_image is None or not os.path.isfile(
            resolved_image.filesystem_path
        ):
            return {
                "success": False,
                "name": tileset_name,
                "error": "sprite_not_found",
                "sprite_name": sprite_name,
            }
        shutil.copy2(resolved_image.filesystem_path, dest_image)

        # Generate and write the .tres file
        tres_content = self._generate_tileset_tres(
            tileset_name,
            tileset_data,
            subfolder,
            tres_resource_path,
        )
        with open(tres_path, 'w', encoding='utf-8') as f:
            f.write(tres_content)
        self._warn_preserved_metadata(tileset_name, tileset_data)

        return {"success": True, "name": tileset_name, "tileset_data": tileset_data}

    def _process_tileset_with_outcome(
        self,
        tileset_name: str,
        subfolder: str = "",
        tileset_source_path: str | None = None,
    ) -> TilesetResult | None:
        if not self.conversion_running():
            return None
        self._resource_started(tileset_name)
        try:
            result = self._process_tileset(
                tileset_name,
                subfolder,
                tileset_source_path,
            )
        except Exception:
            self._resource_failed(tileset_name)
            raise
        if result is None:
            self._resource_skipped(tileset_name)
        elif result["success"]:
            self._resource_completed(tileset_name)
        else:
            self._resource_failed(tileset_name)
        return result

    def _warn_preserved_metadata(self, tileset_name: str, tileset_data: TilesetData) -> None:
        preserved_features: list[str] = []
        if tileset_data["tileAnimationFrames"]:
            preserved_features.append("animation frames")
        if tileset_data["tileSetCollisions"]:
            preserved_features.append("collision data")
        if tileset_data["autoTileSets"]:
            preserved_features.append("auto-tile metadata")
        if tileset_data["brushes"]:
            preserved_features.append("brush metadata")
        if not preserved_features:
            return
        self._safe_log(
            "Warning: GameMaker tileset {name} preserves {features} as Godot metadata; "
            "native TileSet behavior may require follow-up runtime/editor support.".format(
                name=tileset_name,
                features=", ".join(preserved_features),
            )
        )

    def convert_tilesets(self) -> None:
        """Main tileset conversion method."""
        os.makedirs(self.godot_project_path, exist_ok=True)
        os.makedirs(self.godot_tilesets_path, exist_ok=True)

        tileset_names: list[str] = []
        tileset_subfolders: dict[str, str] = {}
        valid_names = self._get_valid_tileset_names()
        if valid_names is not None:
            declared_names = set(self._yyp_declared_tilesets) | set(valid_names)
            for name in sorted(declared_names):
                self._resource_requested(name)

            unavailable_names = declared_names - set(valid_names)
            for name in sorted(unavailable_names):
                resource = self._yyp_declared_tilesets.get(
                    name,
                    _DeclaredTilesetResource(
                        name=name,
                        source_path=None,
                        owner_source_path=self.gm_project_path,
                        manifest_field="resources[].id.path",
                    ),
                )
                reason = (
                    f"metadata is missing or unavailable at {resource.source_path!r}"
                    if resource.source_path
                    else "its manifest source path was rejected or is unavailable"
                )
                self._report_unavailable_declared_tileset(
                    resource,
                    reason=reason,
                )
                self._resource_skipped(name)

            for name, subfolder in valid_names.items():
                source_path = self._tileset_source_paths.get(name)
                resolved = self._resolve_tileset_yy_source(name, source_path)
                if resolved is None or not os.path.isfile(resolved.filesystem_path):
                    resource = self._yyp_declared_tilesets.get(
                        name,
                        _DeclaredTilesetResource(
                            name=name,
                            source_path=source_path,
                            owner_source_path=self.gm_project_path,
                            manifest_field="resources[].id.path",
                        ),
                    )
                    self._report_unavailable_declared_tileset(
                        resource,
                        reason=(
                            "its metadata became unavailable before conversion"
                        ),
                    )
                    self._resource_skipped(name)
                    continue
                tileset_names.append(name)
                tileset_subfolders[name] = subfolder
        else:
            resolved_tilesets_root = self._resolve_discovered_project_source(
                os.path.join(self.gm_project_path, 'tilesets'),
                resource_type="tileset",
                field="tilesets directory",
            )
            if (
                resolved_tilesets_root is None
                or not os.path.isdir(resolved_tilesets_root.filesystem_path)
            ):
                self.log_callback(get_localized("Console_Convertor_Tilesets_Error_NotFound").format(
                    gm_project_path=self.gm_project_path))
                return
            for entry in os.listdir(resolved_tilesets_root.filesystem_path):
                entry_path = os.path.join(
                    resolved_tilesets_root.filesystem_path,
                    entry,
                )
                resolved_directory = self._resolve_discovered_project_source(
                    entry_path,
                    owner_source_path=resolved_tilesets_root.source_path,
                    resource=entry,
                    resource_type="tileset",
                    field="tileset directory",
                )
                if resolved_directory is None or not os.path.isdir(
                    resolved_directory.filesystem_path
                ):
                    continue

                yy_path = os.path.join(
                    resolved_directory.filesystem_path,
                    entry + '.yy',
                )
                resolved_yy = self._resolve_discovered_project_source(
                    yy_path,
                    owner_source_path=resolved_directory.source_path,
                    resource=entry,
                    resource_type="tileset",
                    field="tileset .yy",
                )
                if (
                    resolved_yy is None
                    or not self._source_has_resource_kind(
                        resolved_yy,
                        "tilesets",
                        rejected_path=yy_path,
                        owner_source_path=resolved_directory.source_path,
                        resource=entry,
                        field="tileset .yy",
                    )
                    or not os.path.isfile(resolved_yy.filesystem_path)
                ):
                    continue
                self._tileset_source_paths[entry] = resolved_yy.source_path
                tileset_names.append(entry)
                tileset_subfolders[entry] = self._get_subfolder_from_yy(
                    resolved_yy.filesystem_path
                )
            for tileset_name in tileset_names:
                self._resource_requested(tileset_name)

        if not tileset_names:
            self.log_callback(get_localized("Console_Convertor_Tilesets_Complete"))
            return

        self._tileset_output_paths = build_asset_output_paths(
            self.gm_project_path,
            self.godot_project_path,
            conversion_running=self.conversion_running,
        ).get("tilesets", {})

        total_tilesets = len(tileset_names)
        processed_tilesets = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map: dict[Future[TilesetResult | None], str] = {
                executor.submit(
                    self._process_tileset_with_outcome,
                    name,
                    tileset_subfolders.get(name, ""),
                    self._tileset_source_paths.get(name),
                ): name
                for name in tileset_names
            }
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_Tilesets_Stopped"))
                    return

                processed_tilesets += 1

                if result["success"]:
                    success_result = cast(TilesetSuccess, result)
                    td = success_result["tileset_data"]
                    if self.compact_logging:
                        self._safe_log_progress(success_result["name"], processed_tilesets, total_tilesets)
                    else:
                        self._safe_log(get_localized("Console_Convertor_Tilesets_Converted").format(
                            name=success_result["name"],
                            tile_count=td["tile_count"],
                            tileWidth=td["tileWidth"],
                            tileHeight=td["tileHeight"]))

                self._safe_progress(int(processed_tilesets / total_tilesets * 100))

        self.log_callback(get_localized("Console_Convertor_Tilesets_Complete"))

    def convert_all(self) -> None:
        self._reset_resource_outcomes()
        self.convert_tilesets()


def _json_dict_list(value: object) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    items: list[JsonDict] = []
    for item in cast(list[object], value):
        if isinstance(item, dict):
            items.append(cast(JsonDict, item))
    return items


def _float(value: object, default: float) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    return default


def _format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return ("{:.6f}".format(value)).rstrip("0").rstrip(".")
