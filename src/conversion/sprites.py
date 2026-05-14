from __future__ import annotations

import os
import re
import json
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from PIL import Image
from collections import defaultdict
from typing import TypedDict, cast

from src.localization import get_localized
from src.conversion.base_converter import BaseConverter
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


class SpriteConverter(BaseConverter):
    def __init__(self, gm_project_path: StrPath, godot_project_path: StrPath, log_callback: LogCallback = print,
                 progress_callback: ProgressCallback | None = None, conversion_running: ConversionRunning | None = None,
                 update_log_callback: LogCallback | None = None, compact_logging: bool = False,
                 max_workers: int | None = None) -> None:
        super().__init__(gm_project_path, godot_project_path, log_callback, progress_callback, conversion_running,
                         update_log_callback, compact_logging, max_workers=max_workers)
        self.godot_sprites_path = os.path.join(self.godot_project_path, 'sprites')

    def _get_valid_sprite_names(self) -> dict[str, str] | None:
        """Parse the .yyp project file and return a dict of sprite name -> subfolder.

        Returns None if the .yyp file cannot be found or parsed, allowing
        the caller to fall back to converting all sprites on disk.
        """
        try:
            yyp_files = [f for f in os.listdir(self.gm_project_path) if f.endswith('.yyp')]
            if not yyp_files:
                return None

            yyp_path = os.path.join(self.gm_project_path, yyp_files[0])
            with open(yyp_path, 'r', encoding='utf-8') as f:
                content = f.read()

            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = cast(JsonDict, json.loads(cleaned))

            valid_sprites: dict[str, str] = {}
            for resource in cast(list[JsonDict], data.get('resources', [])):
                res_id = cast(JsonDict, resource.get('id', {}))
                path = str(res_id.get('path', ''))
                if path.startswith('sprites/'):
                    name = str(res_id.get('name', ''))
                    yy_path = os.path.join(self.gm_project_path, 'sprites', name, name + '.yy')
                    valid_sprites[name] = self._get_subfolder_from_yy(yy_path)

            return valid_sprites
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._safe_log(get_localized("Console_Convertor_Sprites_YYPFilterWarning"))
            return None

    @staticmethod
    def _sprite_res_path(subfolder: str, sprite_name: str) -> str:
        """Build a res://sprites/... path, avoiding double slashes."""
        if subfolder:
            return f"res://sprites/{subfolder}/{sprite_name}"
        return f"res://sprites/{sprite_name}"

    def _find_all_sprite_images(self) -> defaultdict[str, list[str]]:
        sprite_folder = os.path.join(self.gm_project_path, 'sprites')
        image_files: defaultdict[str, list[str]] = defaultdict(list)
        for root, _, files in os.walk(sprite_folder):
            if 'layers' in root.split(os.path.sep):
                sprite_name = root.split(os.path.sep)[-3]
                image_files[sprite_name].extend(
                    os.path.join(root, file)
                    for file in files
                    if file.lower().endswith(('.png', '.jpg', '.jpeg'))
                )
        return image_files

    def _parse_collision_data(self, sprite_name: str) -> CollisionData | None:
        """Parse collision mask properties from a sprite .yy file.

        Returns a dict with collision fields or None if parsing fails.
        """
        yy_path = os.path.join(self.gm_project_path, 'sprites', sprite_name, sprite_name + '.yy')
        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = cast(JsonDict, json.loads(cleaned))

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
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _parse_animation_data(self, sprite_name: str) -> AnimationData | None:
        """Parse animation metadata from a sprite .yy file's sequence object.

        Returns a dict with animation fields or None if parsing fails.
        """
        yy_path = os.path.join(self.gm_project_path, 'sprites', sprite_name, sprite_name + '.yy')
        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = cast(JsonDict, json.loads(cleaned))

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
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, IndexError):
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

        parts: list[str] = [f'[gd_scene format=3 load_steps={load_steps}]\n']
        parts.append(f'\n[ext_resource type="Texture2D" path="{res_prefix}/{sprite_name}.png" id="1"]\n')

        if has_collision:
            parts.append(f'\n{collision_sub}')

        parts.append(f'\n[node name="{sprite_name}" type="Area2D"]\n')
        parts.extend(self._sprite_metadata_lines(collision_data))
        parts.append(f'\n[node name="Sprite2D" type="Sprite2D" parent="."]\n')
        parts.append(f'texture = ExtResource("1")\n')

        if has_collision:
            parts.append(f'\n{collision_node}')

        tscn_content = ''.join(parts)

        tscn_dir = os.path.join(self.godot_sprites_path, subfolder, sprite_name) if subfolder else os.path.join(self.godot_sprites_path, sprite_name)
        os.makedirs(tscn_dir, exist_ok=True)
        tscn_path = os.path.join(tscn_dir, f"{sprite_name}.tscn")
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

        parts = [f'[gd_scene format=3 load_steps={load_steps}]\n']

        # One ext_resource per frame
        for i in range(1, frame_count + 1):
            parts.append(f'\n[ext_resource type="Texture2D" path="{res_prefix}/{sprite_name}_{i}.png" id="{i}"]\n')

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

        tscn_dir = os.path.join(self.godot_sprites_path, subfolder, sprite_name) if subfolder else os.path.join(self.godot_sprites_path, sprite_name)
        os.makedirs(tscn_dir, exist_ok=True)
        tscn_path = os.path.join(tscn_dir, f"{sprite_name}.tscn")
        with open(tscn_path, 'w', encoding='utf-8') as f:
            f.write(tscn_content)

    def _generate_sprite_scene(self, sprite_name: str, collision_data: CollisionData | None, frame_count: int,
                               animation_data: AnimationData | None = None, subfolder: str = "") -> None:
        """Generate a .tscn scene file for a sprite.

        Creates either an AnimatedSprite2D scene (multi-frame with animation data)
        or a Sprite2D scene (single-frame or no animation data).

        Creates the file at godot_sprites_path/{subfolder}/{sprite_name}/{sprite_name}.tscn.
        """
        collision_sub, _, collision_node = self._build_collision_block(collision_data)

        if frame_count > 1 and animation_data is not None:
            self._write_animated_scene(sprite_name, frame_count, animation_data, collision_data, collision_sub, collision_node, subfolder)
        else:
            self._write_static_scene(sprite_name, collision_data, collision_sub, collision_node, subfolder)

    def _parse_sprite_yy(self, sprite_name: str) -> SpriteParseResult | None:
        yy_path = os.path.join(self.gm_project_path, 'sprites', sprite_name, sprite_name + '.yy')
        try:
            with open(yy_path, 'r', encoding='utf-8') as f:
                content = f.read()
            cleaned = re.sub(r',\s*([}\]])', r'\1', content)
            data = cast(JsonDict, json.loads(cleaned))

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
        except (OSError, json.JSONDecodeError, KeyError, TypeError, IndexError):
            self._safe_log(get_localized("Console_Convertor_Sprites_YYParseFailed").format(
                yy_path=yy_path, sprite_name=sprite_name))
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

        new_filename = f"{sprite_name}_{index}.png" if images_count > 1 else f"{sprite_name}.png"
        sprite_dir = os.path.join(self.godot_sprites_path, subfolder, sprite_name) if subfolder else os.path.join(self.godot_sprites_path, sprite_name)
        godot_sprite_path = os.path.join(sprite_dir, new_filename)

        if len(gm_sprite_paths) == 1:
            with Image.open(gm_sprite_paths[0]) as img:
                img.save(godot_sprite_path, 'PNG')
        else:
            composed = None
            for gm_sprite_path in gm_sprite_paths:
                with Image.open(gm_sprite_path) as img:
                    layer = img.convert('RGBA')
                if composed is None:
                    composed = Image.new('RGBA', layer.size, (0, 0, 0, 0))
                composed.alpha_composite(layer)
            assert composed is not None
            composed.save(godot_sprite_path, 'PNG')

        return (sprite_name, index, images_count, gm_sprite_paths[0], new_filename)

    def convert_sprites(self) -> None:
        os.makedirs(self.godot_sprites_path, exist_ok=True)

        sprite_images = self._find_all_sprite_images()

        valid_names = self._get_valid_sprite_names()
        sprite_subfolders: dict[str, str] = {}
        if valid_names is not None:
            filtered: defaultdict[str, list[str]] = defaultdict(list)
            for name, images in sprite_images.items():
                if name in valid_names:
                    filtered[name] = images
                    sprite_subfolders[name] = valid_names[name]
                else:
                    self._safe_log(get_localized("Console_Convertor_Sprites_Skipped").format(
                        sprite_name=name))
            sprite_images = filtered
        else:
            for name in sprite_images:
                yy_path = os.path.join(self.gm_project_path, 'sprites', name, name + '.yy')
                sprite_subfolders[name] = self._get_subfolder_from_yy(yy_path)

        if not sprite_images:
            self.log_callback(get_localized("Console_Convertor_Sprites_Error_NotFound"))
            return

        # Pre-create all sprite directories
        for sprite_name in sprite_images:
            subfolder = sprite_subfolders.get(sprite_name, "")
            sprite_dir = os.path.join(self.godot_sprites_path, subfolder, sprite_name) if subfolder else os.path.join(self.godot_sprites_path, sprite_name)
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

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures_map: dict[Future[SpriteProcessResult | None], tuple[str, int, list[str], int, str]] = {
                executor.submit(self._process_sprite, name, idx, path, count, sub): (name, idx, path, count, sub)
                for name, idx, path, count, sub in work_items
            }
            for future in as_completed(futures_map):
                result = future.result()
                if result is None:
                    self.log_callback(get_localized("Console_Convertor_Sprites_Stopped"))
                    return

                sprite_name, _index, _images_count, gm_sprite_path, new_filename = result
                processed_images += 1

                if self.compact_logging:
                    self._safe_log_progress(sprite_name, processed_images, total_images)
                else:
                    self._safe_log(get_localized("Console_Convertor_Sprites_Converted").format(
                        relative_path=os.path.relpath(gm_sprite_path, self.gm_project_path),
                        sprite_name=sprite_name, new_filename=new_filename))

                self._safe_progress(int(processed_images / total_images * 100))

        # Second pass: generate scenes for all sprites
        for sprite_name, images in sprite_images.items():
            if not self.conversion_running():
                return
            frame_count = len(self._build_ordered_frame_list(sprite_name, images))
            collision_data = self._parse_collision_data(sprite_name)
            animation_data = self._parse_animation_data(sprite_name)
            subfolder = sprite_subfolders.get(sprite_name, "")

            self._generate_sprite_scene(sprite_name, collision_data, frame_count, animation_data, subfolder)

            self._safe_log(get_localized("Console_Convertor_Sprites_SceneGenerated").format(name=sprite_name))
            if frame_count > 1 and animation_data is not None:
                godot_fps = self._compute_godot_fps(animation_data)
                self._safe_log(get_localized("Console_Convertor_Sprites_SceneAnimated").format(
                    frame_count=frame_count, fps=godot_fps, loop=animation_data["loop"]))
                if animation_data["playbackSpeedType"] == 1:
                    self._safe_log(get_localized("Console_Convertor_Sprites_SpeedTypeWarning").format(name=sprite_name))
            if collision_data is not None and collision_data["collisionKind"] in (0, 4):
                self._safe_log(get_localized("Console_Convertor_Sprites_CollisionPreciseWarning").format(name=sprite_name))

        self.log_callback(get_localized("Console_Convertor_Sprites_Complete"))

    def convert_all(self) -> None:
        self.convert_sprites()
