# Sprite Scene Generation with Animation Data

## Context

GM2Godot currently extracts individual PNG frames from GameMaker sprites and generates `.tscn` scenes containing a `Sprite2D` with a collision shape. However, only the first frame is referenced by the scene, and no animation data (speed, looping, frame durations) is preserved. Multi-frame sprites lose their animation entirely.

This enhancement makes every sprite produce a complete Godot scene:
- **Single-frame sprites**: `Area2D` with `Sprite2D` + `CollisionShape2D` (current behavior, unchanged)
- **Multi-frame sprites**: `Area2D` with `AnimatedSprite2D` (embedded `SpriteFrames` sub-resource) + `CollisionShape2D`

## GameMaker Source Data

Each sprite `.yy` file contains a `sequence` object with animation metadata:

```
sequence.playbackSpeed      float   Animation speed value (e.g., 30.0, 60.0, 1.0)
sequence.playbackSpeedType  int     0 = frames per second, 1 = frames per game frame
sequence.playback           int     1 = looping
sequence.length             float   Total frame count
sequence.tracks[0].keyframes.Keyframes[].Key      float   Frame index (0.0, 1.0, ...)
sequence.tracks[0].keyframes.Keyframes[].Length    float   Relative frame duration (default 1.0)
sequence.tracks[0].keyframes.Keyframes[].Channels["0"].Id.name   string   Frame GUID
```

Existing collision mask fields (`bboxMode`, `collisionKind`, `bbox_*`, `origin`, etc.) are already parsed by the current implementation.

## Godot Target Format

### Multi-frame sprite scene (.tscn)

```
[gd_scene format=3 load_steps={ext_count + sub_count + 1}]

[ext_resource type="Texture2D" path="res://sprites/{name}/{name}_1.png" id="1"]
[ext_resource type="Texture2D" path="res://sprites/{name}/{name}_2.png" id="2"]
...

[sub_resource type="SpriteFrames" id="SpriteFrames_1"]
animations = [{
"frames": [{
"duration": 1.0,
"texture": ExtResource("1")
}, {
"duration": 1.0,
"texture": ExtResource("2")
}],
"loop": true,
"name": &"default",
"speed": 30.0
}]

[sub_resource type="{ShapeType}" id="{ShapeId}"]
{shape_properties}

[node name="{name}" type="Area2D"]

[node name="AnimatedSprite2D" type="AnimatedSprite2D" parent="."]
sprite_frames = SubResource("SpriteFrames_1")
animation = &"default"
autoplay = "default"

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("{ShapeId}")
position = Vector2({offset_x}, {offset_y})
```

### Single-frame sprite scene (.tscn)

```
[gd_scene format=3 load_steps=3]

[ext_resource type="Texture2D" path="res://sprites/{name}/{name}.png" id="1"]

[sub_resource type="{ShapeType}" id="{ShapeId}"]
{shape_properties}

[node name="{name}" type="Area2D"]

[node name="Sprite2D" type="Sprite2D" parent="."]
texture = ExtResource("1")

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("{ShapeId}")
position = Vector2({offset_x}, {offset_y})
```

## Speed Conversion

| GM playbackSpeedType | GM playbackSpeed | Godot SpriteFrames speed | Rationale |
|---|---|---|---|
| 0 (FPS) | Any value | Same value | Direct mapping |
| 1 (per game frame) | > 0 | `value * 60` | Assumes 60fps game step rate (GM default) |
| 1 (per game frame) | 0.0 | 0.0 | Static sprite, no auto-play |

When `playbackSpeedType` is 1, a log note is emitted telling the user to adjust speed if their game doesn't target 60fps.

## Per-Frame Duration

GameMaker keyframes can have non-uniform `Length` values (e.g., one frame held for 2x as long). The Godot SpriteFrames `duration` field supports this directly - it's a relative multiplier where 1.0 = normal speed.

Mapping: `godot_duration = keyframe.Length` (direct, same semantics).

## Implementation

### Files to modify

- `src/conversion/sprites.py` - Refactor scene generation, add animation parsing
- `tests/test_sprites.py` - Add tests for animated scene generation
- `Languages/eng.json` - New localization keys
- `Languages/de.json` - German translations

### New methods in SpriteConverter

**`_parse_animation_data(sprite_name)`**
Reads the `.yy` file and extracts from the `sequence` object:
```python
{
    "playbackSpeed": float,
    "playbackSpeedType": int,   # 0=FPS, 1=per game frame
    "loop": bool,               # from sequence.playback == 1
    "frame_durations": [float], # per-frame Length values from keyframes
}
```
Returns `None` on parse failure. Reuses existing JSON trailing-comma cleanup.

**`_compute_godot_fps(animation_data)`**
Converts GM speed to Godot FPS:
- Type 0: return `playbackSpeed`
- Type 1: return `playbackSpeed * 60`

**`_build_collision_block(collision_data)`**
Extracted from current `_generate_sprite_scene`. Returns a tuple of `(shape_sub_resource_text, shape_id, collision_node_text)` for the collision shape. Used by both static and animated scene generators.

**`_generate_sprite_scene(sprite_name, collision_data, frame_count, animation_data)`** (refactored)
Replaces the current method. Dispatches to either static or animated path based on `frame_count`:
- `frame_count == 1`: Generates Sprite2D scene
- `frame_count > 1`: Generates AnimatedSprite2D scene with embedded SpriteFrames

### Scene generation always runs

Currently, scene generation is a "second pass" that only runs if collision data is found. The new behavior:
- Scene generation runs for ALL sprites after image extraction
- If collision data is available, include CollisionShape2D in the scene
- If collision data is unavailable (parse failure), generate scene WITHOUT collision (just Sprite2D or AnimatedSprite2D)

### Localization keys

```
Console_Convertor_Sprites_SceneGenerated       "Generated scene: sprites/{name}/{name}.tscn"
Console_Convertor_Sprites_SceneAnimated         "  Animation: {frame_count} frames at {fps} FPS (loop: {loop})"
Console_Convertor_Sprites_SpeedTypeWarning      "  Note: {name} uses per-game-frame speed. Converted assuming 60fps game rate."
```

The existing collision-related keys remain unchanged.

## Testing

### New test cases

- `TestParseAnimationData` - Verify extraction of playbackSpeed, playbackSpeedType, loop, frame_durations from .yy
- `TestComputeGodotFps` - Type 0 passthrough, type 1 multiplication, zero speed
- `TestGenerateAnimatedScene` - Multi-frame: verify .tscn has AnimatedSprite2D, SpriteFrames with correct frame count and speed
- `TestGenerateAnimatedSceneWithDurations` - Non-uniform keyframe lengths -> per-frame durations
- `TestGenerateStaticScene` - Single-frame: verify .tscn has Sprite2D (not AnimatedSprite2D)
- `TestSceneWithoutCollision` - Verify scene generates even when collision parsing fails
- `TestSceneAlwaysGenerated` - Verify every sprite gets a .tscn, not just those with collision data

### Test helper

`_make_yy_content_with_sequence()` - Builds a .yy string with both collision and sequence data, configurable frame count, speed, and speed type.

## Verification

1. `python -m pytest tests/` - All tests pass
2. Run converter against AsteroidsPLUSPLUS project:
   - Verify multi-frame sprites (s_bouncyorbs, s_blackhole) get AnimatedSprite2D scenes with correct FPS
   - Verify single-frame sprites (s_amaltheaBIG) get Sprite2D scenes
   - Verify collision shapes still present on all scenes
3. Open generated .tscn files in Godot editor - animations should play correctly
