from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from PIL import Image
from collections import defaultdict
from dataclasses import dataclass
from typing import TypedDict, cast

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter
from src.conversion.diagnostics import DiagnosticCollector
from src.conversion.generated_paths import generated_nested_resource_path, generated_resource_directory, generated_resource_stem
from src.conversion.project_manifest import load_gamemaker_project_manifest
from src.conversion.project_source_paths import (
    ProjectSourcePathError,
    ResolvedProjectSourcePath,
    validate_project_resource_source_path,
)
from src.conversion.type_defs import ConversionRunning, JsonDict, LogCallback, ProgressCallback, StrPath


class CollisionData(TypedDict):
    collisionKind: int
    bboxMode: int
    bbox_left: int
    bbox_right: int
    bbox_top: int
    bbox_bottom: int
    width: int
    height: int
    origin: int
    xorigin: int
    yorigin: int


class AnimationData(TypedDict):
    playbackSpeed: float
    playbackSpeedType: int
    loop: bool
    frame_durations: list[float]


SpriteParseResult = tuple[list[str], list[str]]
SpriteProcessResult = tuple[str, int, int, str, str]


@dataclass(frozen=True)
class _DeclaredSpriteResource:
    name: str
    source_path: str | None
    owner_source_path: str | None
    manifest_field: str | None


class SpriteConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath, log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None, conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None,
                 diagnostics: DiagnosticCollector | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers,
                         diagnostics=diagnostics)
        self.godot_sprites_path = os.path.join(self.godot_project_path, 'sprites')
        self._sprite_path_suffixes: dict[str, str] = {}
        self._yyp_sprite_yy_paths: dict[str, str] = {}
        self._sprite_yy_paths: dict[str, str] = {}
        self._sprite_owner_yy_paths: dict[str, str] = {}
        self._sprites_without_yy: set[str] = set()
        self._yyp_declared_sprites: dict[str, _DeclaredSpriteResource] = {}

    def _get_valid_sprite_names(
        self,
        *,
        request_declared_resources: bool = False,
    ) -> dict[str, str] | None:
        """Parse the .yyp project file and return a dict of sprite name -> subfolder.

        Returns None if the .yyp file cannot be found or parsed, allowing
        the caller to fall back to converting all sprites on disk. Conversion
        planning can request each declaration before its metadata is filtered.
        """
        self._yyp_sprite_yy_paths = {}
        self._sprite_yy_paths = {}
        self._sprite_owner_yy_paths = {}
        self._sprites_without_yy = set()
        self._yyp_declared_sprites = {}
        manifest = load_gamemaker_project_manifest(self.gm_project_path)
        manifest_rejected_fields = self._record_project_manifest_source_path_diagnostics(
            manifest,
            resource_type="sprite",
            include_project_sources=True,
        )
        try:
            if manifest.yyp_path is None:
                return None
            resolved_yyp = self._resolve_discovered_project_source(
                manifest.yyp_path,
                owner_source_path=manifest.yyp_path,
                resource_type="sprite",
                field="project .yyp",
            )
            if resolved_yyp is None:
                return None
            if any(
                diagnostic.code == "GM2GD-PROJECT-YYP-MALFORMED"
                for diagnostic in manifest.diagnostics
            ):
                raise TypeError("GameMaker project root must be an object")
            data = manifest.raw_data

            valid_sprites: dict[str, str] = {}
            raw_resources = data.get('resources', [])
            if not isinstance(raw_resources, list):
                raise TypeError("GameMaker project resources must be an array")
            for resource_index, raw_resource in enumerate(cast(list[object], raw_resources)):
                if not isinstance(raw_resource, dict):
                    continue
                resource = cast(JsonDict, raw_resource)
                raw_res_id = resource.get('id', {})
                if not isinstance(raw_res_id, dict):
                    continue
                res_id = cast(JsonDict, raw_res_id)
                raw_path_value = res_id.get('path', '')
                resource_type = resource.get('resourceType')
                id_resource_type = res_id.get('resourceType')
                is_sprite = (
                    (
                        isinstance(raw_path_value, str)
                        and raw_path_value.replace('\\', '/').casefold().startswith('sprites/')
                    )
                    or resource_type == "GMSprite"
                    or id_resource_type == "GMSprite"
                )
                if is_sprite:
                    raw_name = res_id.get('name', '')
                    name = (
                        raw_name
                        if isinstance(raw_name, str) and raw_name
                        else (
                            os.path.splitext(os.path.basename(raw_path_value))[0]
                            if isinstance(raw_path_value, str)
                            else ""
                        )
                    )
                    if not name:
                        continue
                    manifest_field = f"resources[{resource_index}].id.path"
                    self._yyp_declared_sprites.setdefault(
                        name,
                        _DeclaredSpriteResource(
                            name=name,
                            source_path=(
                                raw_path_value
                                if isinstance(raw_path_value, str)
                                else None
                            ),
                            owner_source_path=resolved_yyp.source_path,
                            manifest_field=manifest_field,
                        ),
                    )
                    if request_declared_resources:
                        self._resource_requested(name)
                    if not isinstance(raw_path_value, str):
                        continue
                    if manifest_field in manifest_rejected_fields:
                        continue
                    path = raw_path_value.replace('\\', '/')
                    resolved_path = self._resolve_project_source(
                        path,
                        owner_source_path=resolved_yyp.source_path,
                        resource=name,
                        resource_type="sprite",
                        field=manifest_field,
                    )
                    if resolved_path is None:
                        continue
                    try:
                        validate_project_resource_source_path(
                            resolved_path,
                            "sprites",
                        )
                    except ProjectSourcePathError as exc:
                        self._report_source_path_rejection(
                            path,
                            exc,
                            owner_source_path=resolved_yyp.source_path,
                            resource=name,
                            resource_type="sprite",
                            field=manifest_field,
                        )
                        continue
                    yy_path = resolved_path.filesystem_path
                    self._yyp_sprite_yy_paths[name] = yy_path
                    self._sprite_yy_paths[name] = yy_path
                    self._sprite_owner_yy_paths[name] = yy_path
                    validated_yy_path = self._sprite_yy_path(name)
                    valid_sprites[name] = (
                        self._get_subfolder_from_yy(validated_yy_path)
                        if validated_yy_path is not None
                        else ""
                    )

            return valid_sprites
        except (OSError, KeyError, TypeError, ValueError):
            self._yyp_declared_sprites = {}
            self._safe_log(get_localized("Console_Convertor_Sprites_YYPFilterWarning"))
            return None

    def _report_unavailable_declared_sprite(
        self,
        resource: _DeclaredSpriteResource,
        *,
        reason: str,
    ) -> None:
        message = (
            "Warning: Skipping manifest-declared GameMaker sprite "
            f"{resource.name!r} because {reason}."
        )
        if self.diagnostics is not None:
            self.diagnostics.add(
                "warning",
                "GM2GD-SPRITE-SOURCE-UNAVAILABLE",
                message,
                source_path=self._diagnostic_source_path(
                    resource.owner_source_path
                ),
                resource=resource.name,
                resource_type="sprite",
                manifest_entry=resource.manifest_field,
                workaround=(
                    "Restore the declared GameMaker sprite .yy metadata inside "
                    "the project root or remove the stale YYP declaration."
                ),
            )
        self._safe_log(message)

    def _sprite_res_path(self, subfolder: str, sprite_name: str) -> str:
        """Build a res://sprites/... path, avoiding double slashes."""
        scene_path = generated_nested_resource_path(
            "sprites",
            subfolder,
            sprite_name,
            ".tscn",
            suffix=self._sprite_path_suffixes.get(sprite_name, ""),
        )
        return scene_path.rsplit("/", 1)[0]

    @staticmethod
    def _stable_sprite_path_suffixes(
        sprite_subfolders: dict[str, str],
        indexed_sprite_names: set[str] | None = None,
        source_paths: dict[str, str] | None = None,
    ) -> dict[str, str]:
        suffixes: dict[str, str] = {}
        used_paths: set[str] = set()
        indexed_names = indexed_sprite_names if indexed_sprite_names is not None else set(sprite_subfolders)
        order_paths = source_paths or {}
        for sprite_name in sorted(
            sprite_subfolders,
            key=lambda name: (
                name not in indexed_names,
                name.lower(),
                order_paths.get(name, name).replace("\\", "/"),
            ),
        ):
            suffix_index = 0
            while True:
                suffix = "" if suffix_index == 0 else f"_{suffix_index + 1}"
                scene_path = generated_nested_resource_path(
                    "sprites",
                    sprite_subfolders[sprite_name],
                    sprite_name,
                    ".tscn",
                    suffix=suffix,
                )
                folded_path = scene_path.casefold()
                if folded_path not in used_paths:
                    break
                suffix_index += 1
            used_paths.add(folded_path)
            suffixes[sprite_name] = suffix
        return suffixes

    def _disk_sprite_directories(self) -> dict[str, str]:
        sprite_root = self._resolve_discovered_project_source(
            os.path.join(self.gm_project_path, 'sprites'),
            resource_type="sprite",
            field="sprites directory",
        )
        if sprite_root is None or not os.path.isdir(sprite_root.filesystem_path):
            return {}
        try:
            sprite_names = sorted(os.listdir(sprite_root.filesystem_path))
        except OSError:
            return {}

        sprite_directories: dict[str, str] = {}
        for sprite_name in sprite_names:
            sprite_dir = os.path.join(sprite_root.filesystem_path, sprite_name)
            resolved_dir = self._resolve_discovered_project_source(
                sprite_dir,
                owner_source_path=sprite_root.source_path,
                resource=sprite_name,
                resource_type="sprite",
                field="discovered sprite directory",
            )
            if resolved_dir is not None and os.path.isdir(resolved_dir.filesystem_path):
                sprite_directories[sprite_name] = resolved_dir.filesystem_path
                # Until a real .yy has been validated, use the containing
                # directory as provenance. A malicious .yy symlink must never
                # become its own diagnostic owner.
                self._sprite_owner_yy_paths.setdefault(
                    sprite_name,
                    resolved_dir.source_path,
                )
        return sprite_directories

    def _disk_sprite_yy_paths(
        self,
        sprite_directories: dict[str, str] | None = None,
    ) -> dict[str, str]:
        directories = (
            sprite_directories
            if sprite_directories is not None
            else self._disk_sprite_directories()
        )
        yy_paths: dict[str, str] = {}
        for sprite_name, sprite_dir in directories.items():
            yy_path = os.path.join(sprite_dir, sprite_name + '.yy')
            resolved_yy = self._resolve_discovered_project_source(
                yy_path,
                owner_source_path=self._sprite_owner_yy_paths.get(
                    sprite_name,
                    sprite_dir,
                ),
                resource=sprite_name,
                resource_type="sprite",
                field="discovered sprite .yy",
            )
            if (
                resolved_yy is not None
                and self._source_has_resource_kind(
                    resolved_yy,
                    rejected_path=yy_path,
                    owner_source_path=self._sprite_owner_yy_paths.get(
                        sprite_name,
                        sprite_dir,
                    ),
                    resource=sprite_name,
                    field="discovered sprite .yy",
                )
                and os.path.isfile(resolved_yy.filesystem_path)
            ):
                yy_paths[sprite_name] = resolved_yy.filesystem_path
                self._sprite_owner_yy_paths[sprite_name] = (
                    resolved_yy.source_path
                )
        return yy_paths

    def _source_has_resource_kind(
        self,
        resolved: ResolvedProjectSourcePath,
        *,
        rejected_path: str,
        owner_source_path: StrPath,
        resource: str,
        field: str,
    ) -> bool:
        try:
            validate_project_resource_source_path(resolved, "sprites")
            return True
        except ProjectSourcePathError as error:
            self._report_source_path_rejection(
                rejected_path,
                error,
                owner_source_path=owner_source_path,
                resource=resource,
                resource_type="sprite",
                field=field,
            )
            return False

    def _sprite_output_stem(self, sprite_name: str) -> str:
        return generated_resource_stem(sprite_name) + self._sprite_path_suffixes.get(sprite_name, "")

    def _sprite_output_directory(self, subfolder: str, sprite_name: str) -> str:
        return generated_resource_directory(
            self.godot_sprites_path,
            subfolder,
            sprite_name,
            suffix=self._sprite_path_suffixes.get(sprite_name, ""),
        )

    def _find_all_sprite_images(
        self,
        sprite_directories: dict[str, str] | None = None,
        owner_yy_paths: dict[str, str] | None = None,
    ) -> defaultdict[str, list[str]]:
        directories = (
            sprite_directories
            if sprite_directories is not None
            else self._disk_sprite_directories()
        )
        owners = owner_yy_paths or {}
        image_files: defaultdict[str, list[str]] = defaultdict(list)
        for sprite_name, sprite_directory in directories.items():
            owner_yy = owners.get(
                sprite_name,
                self._sprite_owner_yy_paths.get(
                    sprite_name,
                    sprite_directory,
                ),
            )
            self._sprite_owner_yy_paths.setdefault(sprite_name, owner_yy)
            image_files[sprite_name].extend(
                self._find_sprite_images(
                    sprite_name,
                    sprite_directory,
                    owner_yy,
                )
            )
            if not image_files[sprite_name]:
                del image_files[sprite_name]
        return image_files

    def _find_sprite_images(
        self,
        sprite_name: str,
        sprite_directory: str,
        owner_yy_path: str,
    ) -> list[str]:
        resolved_sprite_directory = self._resolve_discovered_project_source(
            sprite_directory,
            owner_source_path=owner_yy_path,
            resource=sprite_name,
            resource_type="sprite",
            field="sprite resource directory",
        )
        if (
            resolved_sprite_directory is None
            or not os.path.isdir(resolved_sprite_directory.filesystem_path)
        ):
            return []

        layers_directory = self._resolve_discovered_project_source(
            os.path.join(resolved_sprite_directory.filesystem_path, 'layers'),
            owner_source_path=owner_yy_path,
            resource=sprite_name,
            resource_type="sprite",
            field="layers directory",
        )
        if layers_directory is None or not os.path.isdir(layers_directory.filesystem_path):
            return []

        image_paths: list[str] = []
        pending_directories = [layers_directory.filesystem_path]
        while pending_directories:
            root = pending_directories.pop()
            resolved_root = self._resolve_discovered_project_source(
                root,
                owner_source_path=owner_yy_path,
                resource=sprite_name,
                resource_type="sprite",
                field="frames[].name",
            )
            if resolved_root is None or not os.path.isdir(
                resolved_root.filesystem_path
            ):
                continue
            try:
                entries = sorted(
                    os.listdir(resolved_root.filesystem_path),
                    reverse=True,
                )
            except OSError:
                continue
            for entry in entries:
                candidate = os.path.join(resolved_root.filesystem_path, entry)
                is_image = entry.lower().endswith(('.png', '.jpg', '.jpeg'))
                resolved_candidate = self._resolve_discovered_project_source(
                    candidate,
                    owner_source_path=owner_yy_path,
                    resource=sprite_name,
                    resource_type="sprite",
                    field=(
                        "frames[].name/layers[].name"
                        if is_image
                        else "frames[].name"
                    ),
                )
                if resolved_candidate is None:
                    continue
                if is_image and os.path.isfile(resolved_candidate.filesystem_path):
                    image_paths.append(resolved_candidate.filesystem_path)
                elif (
                    not os.path.islink(candidate)
                    and os.path.isdir(resolved_candidate.filesystem_path)
                ):
                    pending_directories.append(resolved_candidate.filesystem_path)
        return image_paths

    def _sprite_yy_path(self, sprite_name: str) -> str | None:
        if sprite_name in self._sprites_without_yy:
            return None
        candidate = self._sprite_yy_paths.get(sprite_name)
        if candidate is None:
            candidate = os.path.join(
                self.gm_project_path,
                'sprites',
                sprite_name,
                sprite_name + '.yy',
            )
        owner_yy = self._sprite_owner_yy_paths.get(
            sprite_name,
            os.path.dirname(candidate),
        )
        resolved_yy = self._resolve_discovered_project_source(
            candidate,
            owner_source_path=owner_yy,
            resource=sprite_name,
            resource_type="sprite",
            field="sprite .yy",
        )
        if resolved_yy is None or not self._source_has_resource_kind(
            resolved_yy,
            rejected_path=candidate,
            owner_source_path=owner_yy,
            resource=sprite_name,
            field="sprite .yy",
        ):
            return None
        self._sprite_owner_yy_paths[sprite_name] = resolved_yy.source_path
        return resolved_yy.filesystem_path

    def _parse_collision_data(self, sprite_name: str) -> CollisionData | None:
        """Parse collision mask properties from a sprite .yy file.

        Returns a dict with collision fields or None if parsing fails.
        """
        yy_path = self._sprite_yy_path(sprite_name)
        if yy_path is None:
            return None
        data = self._read_yy_file(yy_path)
        if data is None:
            return None
        try:
            return {
                "collisionKind": int(data.get("collisionKind", 1)),
                "bboxMode": int(data.get("bboxMode", 0)),
                "bbox_left": int(data.get("bbox_left", 0)),
                "bbox_right": int(data.get("bbox_right", 0)),
                "bbox_top": int(data.get("bbox_top", 0)),
                "bbox_bottom": int(data.get("bbox_bottom", 0)),
                "width": int(data.get("width", 0)),
                "height": int(data.get("height", 0)),
                "origin": int(data.get("origin", 0)),
                "xorigin": int(data.get("xorigin", 0)),
                "yorigin": int(data.get("yorigin", 0)),
            }
        except (KeyError, TypeError, ValueError):
            return None

    def _parse_animation_data(self, sprite_name: str) -> AnimationData | None:
        """Parse animation metadata from a sprite .yy file's sequence object.

        Returns a dict with animation fields or None if parsing fails.
        """
        yy_path = self._sprite_yy_path(sprite_name)
        if yy_path is None:
            return None
        data = self._read_yy_file(yy_path)
        if data is None:
            return None
        try:
            sequence = data.get("sequence")
            if not isinstance(sequence, dict):
                return None
            sequence_data = cast(JsonDict, sequence)

            playback_speed = float(sequence_data.get("playbackSpeed", 30.0))
            playback_speed_type = int(sequence_data.get("playbackSpeedType", 0))
            loop = int(sequence_data.get("playback", 1)) == 1

            frame_durations: list[float] = []
            tracks = cast(list[JsonDict], sequence_data.get("tracks", []))
            if tracks:
                keyframes_store = cast(JsonDict, tracks[0].get("keyframes", {}))
                keyframes = cast(list[JsonDict], keyframes_store.get("Keyframes", []))
                sorted_kf = sorted(keyframes, key=lambda kf: float(kf.get("Key", 0)))
                frame_durations = [float(kf.get("Length", 1.0)) for kf in sorted_kf]

            return {
                "playbackSpeed": playback_speed,
                "playbackSpeedType": playback_speed_type,
                "loop": loop,
                "frame_durations": frame_durations,
            }
        except (KeyError, TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _compute_godot_fps(animation_data: AnimationData) -> float:
        """Convert GameMaker playback speed to Godot FPS.

        Type 0 (FPS): use value directly.
        Type 1 (frames per game frame): multiply by 60 (standard GM step rate).
        """
        speed = animation_data["playbackSpeed"]
        if animation_data["playbackSpeedType"] == 1:
            return speed * 60.0
        return speed

    @staticmethod
    def _fallback_animation_data(frame_count: int) -> AnimationData:
        """Keep every discovered frame usable when sequence metadata is absent."""
        return {
            "playbackSpeed": 30.0,
            "playbackSpeedType": 0,
            "loop": True,
            "frame_durations": [1.0] * frame_count,
        }

    def _compute_origin_offset(self, collision_data: CollisionData) -> tuple[float, float] | tuple[int, int]:
        """Compute the sprite origin position in pixels.

        Returns (origin_x, origin_y) based on the origin preset or custom values.
        """
        w = collision_data["width"]
        h = collision_data["height"]
        origin = collision_data["origin"]

        origin_map: dict[int, tuple[float, float] | tuple[int, int]] = {
            0: (0, 0),
            1: (w / 2, 0),
            2: (w, 0),
            3: (0, h / 2),
            4: (w / 2, h / 2),
            5: (w, h / 2),
            6: (0, h),
            7: (w / 2, h),
            8: (w, h),
        }

        if origin == 9:
            return (collision_data["xorigin"], collision_data["yorigin"])
        return origin_map.get(origin, (0, 0))

    def _build_collision_block(self, collision_data: CollisionData | None) -> tuple[str | None, str | None, str | None]:
        """Build collision sub_resource text, shape id, and node text from collision data.

        Returns (sub_resource_text, shape_id, node_text) or (None, None, None)
        if collision_data is None.
        """
        if collision_data is None:
            return (None, None, None)

        bbox_left = collision_data["bbox_left"]
        bbox_right = collision_data["bbox_right"]
        bbox_top = collision_data["bbox_top"]
        bbox_bottom = collision_data["bbox_bottom"]

        bbox_w = bbox_right - bbox_left + 1
        bbox_h = bbox_bottom - bbox_top + 1
        # GM bbox values are inclusive pixel indices; add 1 for continuous center
        bbox_center_x = (bbox_left + bbox_right + 1) / 2
        bbox_center_y = (bbox_top + bbox_bottom + 1) / 2

        # Godot Sprite2D defaults to centered=true, so visual center (w/2, h/2)
        # is at position (0,0). Collision offset must be relative to that center.
        sprite_center_x = collision_data["width"] / 2
        sprite_center_y = collision_data["height"] / 2
        offset_x = bbox_center_x - sprite_center_x
        offset_y = bbox_center_y - sprite_center_y

        collision_kind = collision_data["collisionKind"]

        # Build shape resource and node based on collision kind
        if collision_kind == 2:
            # Ellipse
            if abs(bbox_w - bbox_h) < 2:
                shape_type = "CircleShape2D"
                shape_id = "CircleShape2D_1"
                shape_props = f"radius = {bbox_w / 2}"
            else:
                shape_type = "CapsuleShape2D"
                shape_id = "CapsuleShape2D_1"
                radius = min(bbox_w, bbox_h) / 2
                height = max(bbox_w, bbox_h)
                shape_props = f"radius = {radius}\nheight = {height}"
        elif collision_kind == 3:
            # Diamond - ConvexPolygonShape2D
            mid_x = (bbox_left + bbox_right) / 2 - sprite_center_x
            mid_y = (bbox_top + bbox_bottom) / 2 - sprite_center_y
            top = bbox_top - sprite_center_y
            bottom = bbox_bottom - sprite_center_y
            left = bbox_left - sprite_center_x
            right = bbox_right - sprite_center_x

            shape_type = "ConvexPolygonShape2D"
            shape_id = "ConvexPolygonShape2D_1"
            shape_props = f"points = PackedVector2Array({mid_x}, {top}, {right}, {mid_y}, {mid_x}, {bottom}, {left}, {mid_y})"
        else:
            # Rectangle (collisionKind 1) or Precise fallback (0, 4)
            shape_type = "RectangleShape2D"
            shape_id = "RectangleShape2D_1"
            shape_props = f"size = Vector2({bbox_w}, {bbox_h})"

        # Diamond uses position on the node differently: offset already baked into points
        if collision_kind == 3:
            position_line = ""
        else:
            position_line = f'\nposition = Vector2({offset_x}, {offset_y})'

        sub_resource_text = (
            f'[sub_resource type="{shape_type}" id="{shape_id}"]\n'
            f'{shape_props}\n'
        )

        node_text = (
            f'[node name="CollisionShape2D" type="CollisionShape2D" parent="."]\n'
            f'shape = SubResource("{shape_id}"){position_line}\n'
        )

        return (sub_resource_text, shape_id, node_text)

    def _sprite_metadata_lines(self, collision_data: CollisionData | None) -> list[str]:
        if collision_data is None:
            return []
        origin_x, origin_y = self._compute_origin_offset(collision_data)
        return [
            f"metadata/gamemaker_width = {collision_data['width']}\n",
            f"metadata/gamemaker_height = {collision_data['height']}\n",
            f"metadata/gamemaker_origin_x = {origin_x}\n",
            f"metadata/gamemaker_origin_y = {origin_y}\n",
        ]

    def _write_static_scene(self, sprite_name: str, collision_data: CollisionData | None,
                            collision_sub: str | None, collision_node: str | None,
                            subfolder: str = "") -> None:
        """Generate a Sprite2D .tscn scene file.

        Creates the file at godot_sprites_path/{subfolder}/{sprite_name}/{sprite_name}.tscn.
        """
        has_collision = collision_sub is not None
        load_steps = 2 if has_collision else 1
        res_prefix = self._sprite_res_path(subfolder, sprite_name)
        sprite_stem = self._sprite_output_stem(sprite_name)

        parts: list[str] = [f'[gd_scene format=3 load_steps={load_steps}]\n']
        parts.append(f'\n[ext_resource type="Texture2D" path="{res_prefix}/{sprite_stem}.png" id="1"]\n')

        if has_collision:
            parts.append(f'\n{collision_sub}')

        parts.append(f'\n[node name="{sprite_name}" type="Area2D"]\n')
        parts.extend(self._sprite_metadata_lines(collision_data))
        parts.append(f'\n[node name="Sprite2D" type="Sprite2D" parent="."]\n')
        parts.append(f'texture = ExtResource("1")\n')

        if has_collision:
            parts.append(f'\n{collision_node}')

        tscn_content = ''.join(parts)

        tscn_dir = self._sprite_output_directory(subfolder, sprite_name)
        os.makedirs(tscn_dir, exist_ok=True)
        tscn_path = os.path.join(tscn_dir, f"{sprite_stem}.tscn")
        with open(tscn_path, 'w', encoding='utf-8') as f:
            f.write(tscn_content)

    def _write_animated_scene(self, sprite_name: str, frame_count: int, animation_data: AnimationData,
                              collision_data: CollisionData | None, collision_sub: str | None,
                              collision_node: str | None, subfolder: str = "") -> None:
        """Generate an AnimatedSprite2D .tscn scene file with embedded SpriteFrames.

        Creates the file at godot_sprites_path/{subfolder}/{sprite_name}/{sprite_name}.tscn.
        """
        has_collision = collision_sub is not None
        # ext_resources (one per frame) + SpriteFrames sub_resource + optional collision sub_resource
        load_steps = frame_count + 1 + (1 if has_collision else 0)
        res_prefix = self._sprite_res_path(subfolder, sprite_name)
        sprite_stem = self._sprite_output_stem(sprite_name)

        parts = [f'[gd_scene format=3 load_steps={load_steps}]\n']

        # One ext_resource per frame
        for i in range(1, frame_count + 1):
            parts.append(f'\n[ext_resource type="Texture2D" path="{res_prefix}/{sprite_stem}_{i}.png" id="{i}"]\n')

        # Build frame entries for the SpriteFrames animation array
        durations = animation_data.get("frame_durations", [])
        frame_entries: list[str] = []
        for i in range(1, frame_count + 1):
            duration = durations[i - 1] if i - 1 < len(durations) else 1.0
            frame_entries.append(
                f'{{\n"duration": {duration},\n"texture": ExtResource("{i}")\n}}'
            )
        frames_str = ', '.join(frame_entries)

        godot_fps = self._compute_godot_fps(animation_data)
        loop_str = "true" if animation_data["loop"] else "false"

        parts.append(f'\n[sub_resource type="SpriteFrames" id="SpriteFrames_1"]\n')
        parts.append(f'animations = [{{\n"frames": [{frames_str}],\n"loop": {loop_str},\n"name": &"default",\n"speed": {godot_fps}\n}}]\n')

        if has_collision:
            parts.append(f'\n{collision_sub}')

        parts.append(f'\n[node name="{sprite_name}" type="Area2D"]\n')
        parts.extend(self._sprite_metadata_lines(collision_data))

        parts.append(f'\n[node name="AnimatedSprite2D" type="AnimatedSprite2D" parent="."]\n')
        parts.append(f'sprite_frames = SubResource("SpriteFrames_1")\n')
        parts.append(f'animation = &"default"\n')
        parts.append(f'autoplay = "default"\n')

        if has_collision:
            parts.append(f'\n{collision_node}')

        tscn_content = ''.join(parts)

        tscn_dir = self._sprite_output_directory(subfolder, sprite_name)
        os.makedirs(tscn_dir, exist_ok=True)
        tscn_path = os.path.join(tscn_dir, f"{sprite_stem}.tscn")
        with open(tscn_path, 'w', encoding='utf-8') as f:
            f.write(tscn_content)

    def _generate_sprite_scene(self, sprite_name: str, collision_data: CollisionData | None, frame_count: int,
                               animation_data: AnimationData | None = None, subfolder: str = "") -> None:
        """Generate a .tscn scene file for a sprite.

        Creates an AnimatedSprite2D scene for every multi-frame sprite and a
        Sprite2D scene for a single frame. Missing animation metadata uses a
        deterministic fallback so the scene never references a nonexistent
        unnumbered texture.

        Creates the file at godot_sprites_path/{subfolder}/{sprite_name}/{sprite_name}.tscn.
        """
        collision_sub, _, collision_node = self._build_collision_block(collision_data)

        if frame_count > 1:
            effective_animation = (
                animation_data
                if animation_data is not None
                else self._fallback_animation_data(frame_count)
            )
            self._write_animated_scene(sprite_name, frame_count, effective_animation, collision_data, collision_sub, collision_node, subfolder)
        else:
            self._write_static_scene(sprite_name, collision_data, collision_sub, collision_node, subfolder)

    def _parse_sprite_yy(self, sprite_name: str) -> SpriteParseResult | None:
        yy_path = self._sprite_yy_path(sprite_name)
        data = self._read_yy_file(yy_path) if yy_path is not None else None
        try:
            if data is None:
                raise TypeError("Sprite metadata must be an object")

            frames = cast(list[JsonDict], data['frames'])
            frame_guids = [str(frame['name']) for frame in frames]

            layers = cast(list[JsonDict], data.get('layers', []))
            visible_layer_guids = [
                str(layer['name'])
                for layer in layers
                if layer.get('visible', True)
            ]
            if not visible_layer_guids and layers:
                visible_layer_guids = [str(layers[0]['name'])]

            return (frame_guids, visible_layer_guids)
        except (KeyError, TypeError, IndexError):
            diagnostic_path = yy_path or self._sprite_owner_yy_paths.get(
                sprite_name,
                os.path.join(
                    self.gm_project_path,
                    'sprites',
                    sprite_name,
                    sprite_name + '.yy',
                ),
            )
            self._safe_log(get_localized("Console_Convertor_Sprites_YYParseFailed").format(
                yy_path=diagnostic_path, sprite_name=sprite_name))
            return None

    def _build_ordered_frame_list(self, sprite_name: str, all_image_paths: list[str]) -> list[list[str]]:
        result = self._parse_sprite_yy(sprite_name)
        if result is None:
            return [[path] for path in sorted(all_image_paths)]

        frame_guids, layer_guids = result

        path_index: dict[str, dict[str, str]] = {}
        for path in all_image_paths:
            parts = path.replace('\\', '/').split('/')
            frame_guid = parts[-2]
            filename = parts[-1]
            path_index.setdefault(frame_guid, {})[filename] = path

        ordered: list[list[str]] = []
        for guid in frame_guids:
            frame_files = path_index.get(guid, {})
            if not frame_files:
                continue
            frame_layers = [
                frame_files[layer_guid + '.png']
                for layer_guid in layer_guids
                if layer_guid + '.png' in frame_files
            ]
            if frame_layers:
                ordered.append(frame_layers)
            else:
                ordered.append([next(iter(frame_files.values()))])

        return ordered if ordered else [[path] for path in sorted(all_image_paths)]

    def _process_sprite(self, sprite_name: str, index: int, gm_sprite_paths: list[str], images_count: int,
                        subfolder: str = "") -> SpriteProcessResult | None:
        if not self.conversion_running():
            return None

        owner_yy_path = self._sprite_owner_yy_paths.get(
            sprite_name,
            os.path.join(
                self.gm_project_path,
                'sprites',
                sprite_name,
                sprite_name + '.yy',
            ),
        )
        resolved_sprite_paths: list[str] = []
        for gm_sprite_path in gm_sprite_paths:
            resolved_image = self._resolve_discovered_project_source(
                gm_sprite_path,
                owner_source_path=owner_yy_path,
                resource=sprite_name,
                resource_type="sprite",
                field="frames[].name/layers[].name",
            )
            if resolved_image is None or not os.path.isfile(
                resolved_image.filesystem_path
            ):
                return (sprite_name, index, images_count, gm_sprite_paths[0], "")
            resolved_sprite_paths.append(resolved_image.filesystem_path)

        sprite_stem = self._sprite_output_stem(sprite_name)
        new_filename = f"{sprite_stem}_{index}.png" if images_count > 1 else f"{sprite_stem}.png"
        sprite_dir = self._sprite_output_directory(subfolder, sprite_name)
        godot_sprite_path = os.path.join(sprite_dir, new_filename)

        if len(resolved_sprite_paths) == 1:
            with Image.open(resolved_sprite_paths[0]) as img:
                img.save(godot_sprite_path, 'PNG')
        else:
            composed = None
            for gm_sprite_path in resolved_sprite_paths:
                with Image.open(gm_sprite_path) as img:
                    layer = img.convert('RGBA')
                if composed is None:
                    composed = Image.new('RGBA', layer.size, (0, 0, 0, 0))
                composed.alpha_composite(layer)
            assert composed is not None
            composed.save(godot_sprite_path, 'PNG')

        return (sprite_name, index, images_count, resolved_sprite_paths[0], new_filename)

    def _process_requested_sprite(
        self,
        sprite_name: str,
        index: int,
        gm_sprite_paths: list[str],
        images_count: int,
        subfolder: str = "",
    ) -> SpriteProcessResult | None:
        """Process one frame while tracking its logical parent sprite once."""
        if not self.conversion_running():
            return None
        self._resource_started(sprite_name)
        return self._process_sprite(
            sprite_name,
            index,
            gm_sprite_paths,
            images_count,
            subfolder,
        )

    def convert_sprites(self) -> None:
        os.makedirs(self.godot_sprites_path, exist_ok=True)

        valid_names = self._get_valid_sprite_names(
            request_declared_resources=True,
        )
        sprite_subfolders: dict[str, str] = {}
        path_subfolders: dict[str, str]
        indexed_sprite_names: set[str]
        source_paths: dict[str, str]
        if valid_names is not None:
            declared_sprite_names = set(self._yyp_declared_sprites) | set(
                valid_names
            )

            source_paths = {}
            for name in self._yyp_sprite_yy_paths:
                validated_yy_path = self._sprite_yy_path(name)
                if validated_yy_path is not None and os.path.isfile(
                    validated_yy_path
                ):
                    source_paths[name] = validated_yy_path
            declared_directories = {
                name: os.path.dirname(yy_path)
                for name, yy_path in source_paths.items()
            }
            sprite_images = self._find_all_sprite_images(
                declared_directories,
                source_paths,
            )
            indexed_sprite_names = set(source_paths)
            sprite_subfolders = {
                name: valid_names[name]
                for name in sprite_images
            }

            declared_directory_keys = {
                os.path.normcase(
                    os.path.realpath(os.path.dirname(yy_path))
                )
                for yy_path in self._yyp_sprite_yy_paths.values()
            }
            disk_directories = self._disk_sprite_directories()
            orphan_directories = {
                name: directory
                for name, directory in disk_directories.items()
                if os.path.normcase(os.path.realpath(directory))
                not in declared_directory_keys
            }
            orphan_images = self._find_all_sprite_images(orphan_directories)
            for name in orphan_images:
                self._safe_log(get_localized("Console_Convertor_Sprites_Skipped").format(
                    sprite_name=name))

            path_subfolders = {
                name: subfolder
                for name, subfolder in valid_names.items()
                if name in indexed_sprite_names or name in sprite_images
            }

            unavailable_sprite_names = declared_sprite_names - indexed_sprite_names
            for sprite_name in sorted(unavailable_sprite_names):
                resource = self._yyp_declared_sprites.get(
                    sprite_name,
                    _DeclaredSpriteResource(
                        name=sprite_name,
                        source_path=None,
                        owner_source_path=None,
                        manifest_field=None,
                    ),
                )
                candidate = self._yyp_sprite_yy_paths.get(sprite_name)
                reason = (
                    f"metadata is missing at {candidate!r}"
                    if candidate is not None
                    else (
                        "its manifest source path was rejected or is unavailable: "
                        f"{resource.source_path!r}"
                    )
                )
                self._report_unavailable_declared_sprite(
                    resource,
                    reason=reason,
                )
                self._resource_skipped(sprite_name)
        else:
            disk_directories = self._disk_sprite_directories()
            discovered_yy_paths = self._disk_sprite_yy_paths(disk_directories)
            self._sprite_yy_paths = dict(discovered_yy_paths)
            self._sprites_without_yy = set(disk_directories) - set(
                discovered_yy_paths
            )
            owner_yy_paths = {
                name: self._sprite_owner_yy_paths.get(
                    name,
                    discovered_yy_paths.get(name, directory),
                )
                for name, directory in disk_directories.items()
            }
            self._sprite_owner_yy_paths.update(owner_yy_paths)
            sprite_images = self._find_all_sprite_images(
                disk_directories,
                owner_yy_paths,
            )
            indexed_sprite_names = set(discovered_yy_paths)
            path_subfolders = {}
            for name in discovered_yy_paths:
                validated_yy_path = self._sprite_yy_path(name)
                path_subfolders[name] = (
                    self._get_subfolder_from_yy(validated_yy_path)
                    if validated_yy_path is not None
                    else ""
                )
            for name in sprite_images:
                sprite_subfolders[name] = path_subfolders.get(name, "")
                path_subfolders.setdefault(name, sprite_subfolders[name])
            source_paths = {
                name: owner_yy_paths[name]
                for name in path_subfolders
            }

        logical_sprite_names = set(sprite_images) | indexed_sprite_names
        if valid_names is None:
            for sprite_name in sorted(logical_sprite_names):
                self._resource_requested(sprite_name)

        empty_sprite_names = indexed_sprite_names - set(sprite_images)
        for sprite_name in sorted(empty_sprite_names):
            self._safe_log(
                f"Warning: Sprite {sprite_name} has no discoverable frame images and was skipped."
            )
            self._resource_skipped(sprite_name)

        if not sprite_images:
            self.log_callback(get_localized("Console_Convertor_Sprites_Error_NotFound"))
            return

        self._sprite_path_suffixes = self._stable_sprite_path_suffixes(
            path_subfolders,
            indexed_sprite_names,
            source_paths,
        )

        # Pre-create all sprite directories
        for sprite_name in sprite_images:
            subfolder = sprite_subfolders.get(sprite_name, "")
            sprite_dir = self._sprite_output_directory(subfolder, sprite_name)
            os.makedirs(sprite_dir, exist_ok=True)

        # Flatten all work items
        work_items: list[tuple[str, int, list[str], int, str]] = []
        for sprite_name, images in sprite_images.items():
            ordered_images = self._build_ordered_frame_list(sprite_name, images)
            subfolder = sprite_subfolders.get(sprite_name, "")
            for index, gm_sprite_path in enumerate(ordered_images, start=1):
                work_items.append((sprite_name, index, gm_sprite_path, len(ordered_images), subfolder))

        total_images = len(work_items)
        processed_images = 0
        cancelled = False
        failed_sprites: set[str] = set()
        first_error: Exception | None = None

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map: dict[Future[SpriteProcessResult | None], tuple[str, int, list[str], int, str]] = {
                executor.submit(self._process_requested_sprite, name, idx, path, count, sub):
                    (name, idx, path, count, sub)
                for name, idx, path, count, sub in work_items
            }
            for future in as_completed(futures_map):
                try:
                    result = future.result()
                except Exception as error:
                    failed_sprites.add(futures_map[future][0])
                    if first_error is None:
                        first_error = error
                    continue
                if result is None:
                    cancelled = True
                    continue

                sprite_name, _index, _images_count, gm_sprite_path, new_filename = result
                processed_images += 1

                if not new_filename:
                    failed_sprites.add(sprite_name)
                    self._safe_progress(int(processed_images / total_images * 100))
                    continue

                if self.compact_logging:
                    self._safe_log_progress(sprite_name, processed_images, total_images)
                else:
                    self._safe_log(get_localized("Console_Convertor_Sprites_Converted").format(
                        relative_path=os.path.relpath(gm_sprite_path, self.gm_project_path),
                        sprite_name=sprite_name, new_filename=new_filename))

                self._safe_progress(int(processed_images / total_images * 100))

        for sprite_name in sorted(failed_sprites):
            self._resource_failed(sprite_name)

        if cancelled:
            self.log_callback(get_localized("Console_Convertor_Sprites_Stopped"))
            if first_error is not None:
                raise first_error
            return

        # Second pass: generate scenes for all sprites
        for sprite_name, images in sprite_images.items():
            if not self.conversion_running():
                cancelled = True
                break
            if sprite_name in failed_sprites:
                continue
            try:
                frame_count = len(self._build_ordered_frame_list(sprite_name, images))
                collision_data = self._parse_collision_data(sprite_name)
                animation_data = self._parse_animation_data(sprite_name)
                if frame_count > 1 and animation_data is None:
                    animation_data = self._fallback_animation_data(frame_count)
                    self._safe_log(
                        f"Warning: Sprite {sprite_name} has multiple frames but no "
                        "readable animation metadata; using a looping 30 FPS fallback."
                    )
                subfolder = sprite_subfolders.get(sprite_name, "")

                self._generate_sprite_scene(sprite_name, collision_data, frame_count, animation_data, subfolder)

                self._safe_log(get_localized("Console_Convertor_Sprites_SceneGenerated").format(name=sprite_name))
                if frame_count > 1 and animation_data is not None:
                    godot_fps = self._compute_godot_fps(animation_data)
                    self._safe_log(get_localized("Console_Convertor_Sprites_SceneAnimated").format(
                        frame_count=frame_count, fps=godot_fps, loop=animation_data["loop"]))
                    if animation_data["playbackSpeedType"] == 1:
                        self._safe_log(
                            get_localized("Console_Convertor_Sprites_SpeedTypeWarning").format(name=sprite_name)
                        )
                if collision_data is not None and collision_data["collisionKind"] in (0, 4):
                    self._safe_log(
                        get_localized("Console_Convertor_Sprites_CollisionPreciseWarning").format(name=sprite_name)
                    )
            except Exception as error:
                self._resource_failed(sprite_name)
                if first_error is None:
                    first_error = error
                continue
            self._resource_completed(sprite_name)

        if first_error is not None:
            raise first_error
        if cancelled:
            self.log_callback(get_localized("Console_Convertor_Sprites_Stopped"))
            return

        self.log_callback(get_localized("Console_Convertor_Sprites_Complete"))

    def convert_all(self) -> None:
        self._reset_resource_outcomes()
        self.convert_sprites()
