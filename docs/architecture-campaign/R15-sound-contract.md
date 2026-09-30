# R15 canonical sound model and characterization entry

Status: PLAN ACCEPTED; old-characterization preparation only after the root parent/worktree binding. Production edits and every launch remain gated on separate review.

The production source basis is verified R14 merge `b45399259c2af24a914fdfefc161ba20c44348ba`, followed by its independently reviewed three-file documentation commit `db5f13dedde019ee93520b3bb5966ffe25fb0a51`. Root and independent reviews accept the refreshed design at `R15/source-refresh-M-b453992`, index SHA256 `ba89ccc3adc655b195f8439e2f2ede2ba6962ec338c8e525872d9be7ada3fef2`. The independent review has SHA256 `f1ab42746b7ca805a15c38072e4f7e87b330e00e450a7a542e4e65b3dd082c35`; root refresh review has SHA256 `45f39d7eee0ae80850e11d1ab7529bfb99081610901d46a52e2f0098c7434ba3`.

Sole preparation and future implementation owner: `resume_main_reconciliation`, branch `codex/080-sound-model`, managed worktree `/Users/infi/.codex/worktrees/r15-sound-model/GM2Godot`. `r14_broad_binding` reviews independently; root owns actual-source review, acceptance, baseline/workflow/campaign metadata and integration. No other writer may edit the eight implementation paths below.

Root will record the exact immutable commit containing this entry and fast-forward the isolated branch to it before executable preparation. That binding must preserve the 22 selected source records, 19 module AST inventories, 550 definitions, 15 protected owners, all 24 retained methods, runtime/Godot/fixture origins and the actual 1033-entry baseline, with only these reviewed campaign-document changes. Reuse saved static metrics; a documentation entry does not require Pyright or tests.

Preparation is limited to a fresh external old-characterization package: the exact 24 retained methods and 12 new observable methods with 49 fixed arms, including the two resolver/group causal arms. Keep candidate-only authority bodies separate. Freeze literal bodies, fixtures, source/full modes, outcomes, read/effect capture, normalization and launcher before independent and root pre-use review. No app/test/Godot invocation, production edit or performance run is authorized by this entry. Successful accepted old results precede implementation.

The current source-only sizes and effective legacy budgets are recorded in the accepted refresh. Registry measures 4036 physical lines while its existing proportional physical allowance is 4054; its structural measurement/allowance is 6739. This is the existing policy, not permission to inflate debt. The import generator already contains no YY parser and stays byte/AST unchanged; the former renderer-parser claim is corrected.

This is one existing task under #797 within the unchanged 54-task roadmap. Campaign completion remains 19/54 (35.2%); design/preparation creates no verification, main or release credit.

## Concrete ownership and API

`src/conversion/sound_model.py` owns the frozen, class-only `SoundModel`, in this exact field order:

| Field | Type | Default |
|---|---|---|
| name | str | required |
| kind | str | required |
| resource_type | str | required |
| yy_path | str | required |
| yyp_path | str | required |
| order | int | required |
| subfolder | str | empty string |
| raw_data | JsonDict | fresh dictionary factory |
| sound_file | str | empty string |
| audio_group | str | empty string |

Keep the existing `JsonDict` raw contract. The supplied dictionary and all nested objects retain identity; no copying, recursive validation or replacement of unknown values. Freeze prevents field reassignment, not mutation of the referenced raw dictionary. The owner imports only standard-library dataclass/typing support and the existing JSON type owner. It must not import converters, registry, aggregate, path planning or file readers.

Explicit approval exceptions: defining module changes; `SoundModel` stops inheriting `ResourceModel`; `resource_models.SoundModel` becomes the same canonical imported class; the finite `ParsedResourceModel` alias gains `SoundModel`. Field order, constructor defaults, equality between equivalent SoundModels and aggregate output stay intact. Compatibility with unknown external `isinstance(sound, ResourceModel)` or old pickled defining-module identities is not claimed.

Use these finite functions, not a mode-switch parser or general context object:

* `sound_file_value(value: object) -> str`: retain any string, otherwise empty string. The worker keeps its existing diagnostic validation before entering the strict parser.
* `sound_audio_group(value: object) -> str`: retain a dictionary's string `name`, otherwise empty string. Empty stays empty. Registry adds its default at its existing consumers; aggregate stores empty. The strict worker deliberately does not use this tolerant rule.
* `parse_sound_worker(data: JsonDict, sound_file: str, *, yy_path: str) -> tuple[SoundModel, SoundWorkerSettings]`: perform the exact strict worker evaluation below. `SoundWorkerSettings` is one eight-key TypedDict containing `volume`, `type`, `bitDepth`, `bitRate`, `sampleRate`, `compression`, `preload`, `duration`, with the same scalar types as old `SoundData`. It is not a second model or an independently populated parser. Construct both returned values only after every ordered conversion succeeds.
* `sound_registry_metadata(model: SoundModel) -> JsonDict`: use `model.audio_group` and `model.sound_file` for the first two fields, then interpret only the five remaining metadata values from `model.raw_data`, in the old order. Two small private float/int helpers retain the registry sound policy exactly. Existing registry helpers remain for other families and audio-group aggregation; this does not generalize or migrate their callers. No second sound YY/settings parser is retained.

No file-reader API, callback injection, normalization policy framework, dictionary-shaped universal model, lazy cache or cross-phase memoization is needed.

## Exact caller projections

1. `SoundConverter._parse_sound_yy(yy_path)` keeps its single YY read, read-failure log, invalid-soundFile diagnostic and `except (KeyError, TypeError, ValueError)` boundary. Replace only the successful dictionary construction with `parse_sound_worker(data, raw_sound_file, yy_path=yy_path)`. The private return becomes `tuple[SoundModel, SoundWorkerSettings] | None`; its parameters stay the same. Remove `SoundData` after its sole production consumer and the sole direct parse test migrate. Do not keep a test-only adapter.
2. `_process_sound` consumes `model.name`, `model.sound_file`, `model.audio_group`, and `settings['volume']` after unpacking. All remaining settings are still coerced and available to characterization even though conversion does not currently read them. Worker model metadata is explicit: kind `sounds`, resource_type `GMSound`, actual YY filesystem path, empty yyp_path/subfolder, order zero, and the exact raw dictionary. These are worker context values, not invented manifest information. Do not compute parent/subfolder or resourceType from raw YY to populate unused fields. Public constructor/convert/result signatures remain unchanged.
3. Add one small registry `_sound_model(resource, sound_file, audio_group)` helper, used by the two actual registry sound consumers. It constructs the canonical class with manifest/resource `name`, kind `sounds`, resource_type `GMSound`, existing YY/source paths, order zero, empty subfolder and identical raw dictionary. It performs no parsing or I/O.
4. `_sound_godot_path` samples `soundFile` through `sound_file_value` at its current start and rejects empty before resolving. Retain the resolver and resolved basename. Only after successful resolution, and only if organizing sounds by group, sample `audioGroupId` through `sound_audio_group`. Construct the phase-local model with those sampled values; use its name/group for the stem/group path. Keep the existing subfolder read after group sampling. Do not move a group read ahead of a resolver callback or add a file-existence test. The ungrouped branch must not sample group data merely to fill the model.
5. The sounds arm of `_metadata` samples group first and soundFile second, constructs `_sound_model`, then calls `sound_registry_metadata`. Stable IDs, entry name/source path, suffix selection, tags and entry ordering continue using the existing manifest resource. No eager model is cached on `_ProjectResource` or shared between stable-path planning and metadata emission.
6. The aggregate sounds arm retains `**base` construction at the same position, replacing its two local field expressions with the canonical `sound_file_value` and `sound_audio_group`. `_base_kwargs` continues owning manifest name/kind/resource_type/paths/order/subfolder and raw identity. Remove only the aggregate SoundModel declaration and extend the existing union/import. Keep shared `_named_reference`/`_string_value` helpers for other families, and preserve the R14 script and shader paths exactly.

The new model is therefore consumed by real copy/name/group selection, real registry path and metadata emission, and the aggregate tuple. The eight settings preserve the rest of the old worker's acceptance boundary without inflating the canonical ten-field model.

## Ordered and differing value policies

After the existing invalid-soundFile check, the worker evaluates exactly:

1. `str(data['name'])` — missing is KeyError; null becomes `None`; empty and non-string values retain current string coercion.
2. The already validated raw soundFile string.
3. `float(volume default 1.0)`.
4. `int(type default 0)`.
5. `int(bitDepth default 16)`.
6. `int(bitRate default 128)`.
7. `int(sampleRate default 44100)`.
8. `int(compression default 0)`.
9. `bool(preload default True)`.
10. `str(data.get('audioGroupId', {}).get('name', 'audiogroup_default'))`, retaining the existing typing-only cast if needed.
11. `float(duration default 0.0)`.

Do not group numeric conversions into a preliminary pass or construct model fields early. The worker catches only the existing three exceptions at the caller: AttributeError from null/non-dictionary group and OverflowError from an infinite integer conversion escape. Invalid soundFile precedes missing name or bad numeric/group values and uses the existing raw-name-or-YY-basename diagnostic authority. Preserve rejected-value repr/string selection, localization, diagnostic identity and logging order.

Registry metadata order is audio_group, sound_file, volume, duration, preload, compression, type. Float/int accept str/int/float (including bool); unsupported types and TypeError/ValueError default independently. OverflowError escapes. Preserve nan/inf where currently accepted; add no finite check or extra catch. Registry group defaults to `audiogroup_default`; aggregate group defaults to empty; strict worker group missing defaults, null/list raises, non-string name is stringified, empty name stays empty until `_process_sound` applies its fallback. Registry/aggregate keep manifest name even when raw name disagrees. These policies must not be unified.

## Read, diagnostic and publication boundaries

Keep acquisition in callers. Registry first reads resource metadata and plans stable paths; `_get_subfolder_from_resource` still delegates to `_get_subfolder_from_yy` and rereads YY. Its returned subfolder must not be replaced by a model snapshot. `build_asset_output_paths` completes before thread submission. Workers independently resolve and family-check YY, read it, parse, resolve the audio file, check `isfile`, then choose the existing planned path or fallback. Fallback still rereads YY through `_get_subfolder_from_yy`. Aggregate reads once and derives subfolder from that same raw object. No new shared cache may erase an intervening file mutation.

Within a worker, preserve mkdir, copy2, import generation, optional import write, converted/volume/bus logs, result return. **`_generate_import_file` does not parse YY or dictionaries**: it selects import text from filename extension and subfolder. It remains byte/AST unchanged, including WAV/MP3/OGG text and unsupported-extension behavior (copy still occurs). Preserve mapping lookup before fallback, collision names, group organization and escaped import paths.

`_process_sound_with_outcome` still marks exceptions failed and reraises. `convert_sounds` still collects worker outcomes, emits progress, checks cancellation, publishes the sorted audio-group map, then credits successful resources in sorted order and logs completion. Copy/import/map failures and cancellation must not gain completion credit. Do not extract or reorder orchestration to obtain metric headroom.

## Allowed implementation paths and measurable target

Exactly eight proposed implementation paths:

1. `src/conversion/sound_model.py` (new owner).
2. `src/conversion/sounds.py` (parse wrapper and actual worker model consumption).
3. `src/conversion/asset_registry.py` (two sound arms and common-context helper).
4. `src/conversion/resource_models.py` (class import/union and two sound field calls).
5. `tests/test_sound_model.py` (new focused old/candidate characterization owner).
6. `tests/test_sounds.py` (existing private parse assertion translation only).
7. `tests/test_asset_registry.py` (only necessary sound assertion/canonical-binding adjustments; otherwise unchanged).
8. `tests/test_conversion_architecture.py` (only necessary aggregate sound identity/assertion adjustments; otherwise unchanged).

Root separately owns contract/ledger/selection/baseline metadata. No baseline edit is authorized by this proposal. All remaining retained-test modules are read-only reuse. No asset-output planner, base converter, script owner, runtime, audio-bus renderer, snapshots, workflow, release, version or fixture-tree edits. No optional ninth path is preapproved.

Source-only measured sizes at M: sounds 704 physical/1203 structural; parse 49/121; process 104/217; convert 76/180; import generator 71/85. Merged source registry 4036/6739; sound path 23/68; metadata 61/157. Aggregate 562/965, parser 131/253. These are actual source arithmetic; the following are estimates, not a baseline run or candidate result:

| Owner | Expected shape / acceptance bound |
|---|---|
| sound_model module | roughly 140–200 physical, 250–400 structural; under 800 physical |
| strict worker parser | roughly 40–65 physical, 90–140 structural; complexity <=15, nesting <=4, <=8 parameters |
| registry metadata projection | roughly 15–25 physical, 45–80 structural; same fresh caps |
| field/scalar/context helpers | each roughly 2–15 physical, 3–30 structural; same fresh caps |
| sounds parse wrapper | about 32–36 physical/65–85 structural after moving the ordered construction |
| sounds process / convert | no retained growth above 217/180 structural; convert/import bodies stay exact |
| registry metadata | target roughly 110–135 structural, retiring its current 157-unit violation |
| registry sound path | roughly 25–30 physical/70–95 structural; below fresh caps |
| aggregate | class-only ownership/import change and scalar substitutions; no growth above 965 module/253 parser structural |
| focused test owner | target 450–700 physical; every fresh helper/test <=150 physical and structural, <=15 complexity, <=4 nesting, <=8 parameters |

Expected improvement is one sound interpretation owner, deletion of the obsolete aggregate class and legacy worker dictionary declaration/construction, actual model consumption by both production callers, reduced sounds concentration and retirement of registry metadata structure debt. The retained process/convert/aggregate parser debts remain honestly listed. Two tiny sound-metadata scalar helpers duplicate the established coercion form, not a second sound parser; moving generic helpers for unrelated families would enlarge this task. Final candidate measurements and root strict baseline checks must confirm zero new/grown debt; no line wrapping, assertion deletion or opaque comprehension is an acceptable substitute.

## Finite characterization and remaining gates

`characterization-plan.json` lists the exact 24 retained IDs plus 12 proposed old-observable methods (finite arms, no Cartesian product) and two separately planned candidate authority methods. Preserve each retained assertion. For the existing direct parse test, translate the same name/volume/sampleRate/bitDepth/group assertions to the pair; characterize an explicit eleven-value tuple for before/after comparison without a production adapter. New tests belong in the focused owner, not the already oversized sounds/registry modules.

Old cases cover defaults/name authority, invalid soundFile precedence, strict ordered failures, accepted strings/bools/nonfinite values, each numeric failure, distinct group policies, tolerant registry numbers, ten aggregate fields/raw identity, real manifest-versus-worker names, actual planning-to-worker mutation, subfolder rereads/copy/import order, and copy/import failure boundaries. The existing group-policy method includes two additional causal arms: a real successful resolver wrapper changes the raw group before returning, and the grouped path must use that changed group; an ungrouped real path call records zero audioGroupId lookups through a finite delegating raw-get observation. These detect phase-local sampling directly; the later planning-to-worker YY mutation cannot substitute. The new old-observable arm total is 49; the 24 retained IDs, 12 old methods and two candidate-only methods are unchanged. Existing tests retain map failure/cancellation, path containment/diagnostics, collisions/orphans, formats and real generated WAV loading. The injected AudioStreamGenerator smoke remains a runtime regression, not source-sound loading evidence.

No cohort has been collected or run. The future old package must pin verified R14 source, all literal methods/finite arms, approved runtime and origins, exact outcomes and raw event/read records, then receive different-author and root source review. On an applicable exact-Godot host, the proposed old cohort is 36 tests with zero expected skips; the two Godot IDs must remain explicitly outstanding on a host without that engine, never counted as successful zero-skip execution. Candidate adds only its two explicit model-authority tests. Exact totals depend on the reviewed executable preparation, not this source-only list.

R15 implementation requires an accepted amended contract and sole owner after R14 verification. Later gates remain Pyright zero diagnostics, both Ruff gates, full shared-change tests, exact engine/native obligations where applicable, finite public output/diagnostic/map/read-order parity and approved repeated-input timing/peak-memory comparison. This document authorizes none of those launches and claims no speedup, candidate debt result or R15 completion.
