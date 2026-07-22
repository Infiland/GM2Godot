# Diagnostics and Troubleshooting

> **Applies to:** GM2Godot 0.7.47 · GameMaker LTS 2026 · Godot 4.7.1
>
> **Last reviewed:** 2026-07-22

[Home](Home) · [Quick Start Conversion](Quick-Start-Conversion) · [Compatibility and Limitations](Compatibility-and-Limitations)

When a conversion surprises you, preserve the console output and inspect the latest attempt ledger before opening the generated project. Then read the structured diagnostics and run Godot validation. These files distinguish a usable partial migration from a failed or stale output directory.

## Report files

Paths below are relative to the generated Godot project unless a report directory is stated.

| File | What it tells you | When it is written |
| --- | --- | --- |
| `gm2godot/conversion_attempt.json` | The terminal state of the latest conversion attempt and whether that publication updated, preserved, or found no canonical manifest. | After destination preflight, for every terminal conversion attempt. A rejected preflight does not write into the destination. |
| `gm2godot/conversion_manifest.json` | Format-v2 canonical record of a trustworthy successful or partial conversion, including enabled converters, source metadata, resources, a complete format-v1 managed-generation inventory, generated-file hashes, source maps, architecture policy, and path diagnostics. | Only when GM2Godot has a trustworthy completed-output candidate. Failed or cancelled work can preserve an older file. |
| `gm2godot/conversion_diagnostics.json` | Machine-readable diagnostic summary, sorted diagnostic entries, and the canonical generation's terminal `outcome` object. | Committed with a successful or partial managed generation; failed/cancelled reruns preserve the prior canonical file. Also written under an explicit external report directory. |
| `gm2godot/conversion_diagnostics.md` | Human-readable view of the same canonical diagnostics. | Committed with the JSON report in the managed generation. |
| `gm2godot/godot_validation_report.json` | Godot binary used, resources checked, import/boot return codes and output, detected warnings/errors, and `passed`, `failed`, or `skipped` status. | By `validate` when headless Godot validation runs or is attempted. |
| `gm2godot/architecture_policy.json` | Generated runtime-manager, room, layer/depth, renderer, collision, audio, file/buffer/network, and signal-queue policy choices. | As part of a conversion. |
| `gm2godot/gml_manual_scope.md`, `gml_api_compatibility.md`, `platform_capability_report.md`, `platform_capability_report.json` | Current global compatibility and target-capability inventory. | Under `--report-dir` for static reporting, analysis, or conversion. |
| `gm2godot/extension_compatibility_report.json` and `group_compatibility_report.json` | Project extension/native-binding findings and texture/audio group compatibility details. | When the corresponding converters inspect those resources. |

The JSON diagnostic entries can include `source_path`, line and column, resource and event/API context, a manifest entry, tracking issue, and workaround. Start with the first `error`, then unsupported warnings, then other warnings.

For authored sequences and timelines, `GM2GD-SEQUENCE-TRACK-UNSUPPORTED`, `GM2GD-SEQUENCE-KEY-UNSUPPORTED`, `GM2GD-SEQUENCE-EFFECT-UNSUPPORTED`, and `GM2GD-TIMELINE-ACTION-UNSUPPORTED` identify the exact `.yy` track/key/effect/action path that was deliberately omitted. The affected sequence or timeline is recorded as skipped in an otherwise usable partial conversion; supported sibling tracks remain in its descriptor. Do not hand-edit the generated descriptor to remove the warning—change the authored asset or add a tested converter/runtime mapping.

The JSON/Markdown pair uses one verified report-directory binding for capture, staging, ordered replacement, rollback, invalidation and cleanup. POSIX hosts use descriptor-relative no-follow operations; Windows retains reparse-checked, no-delete-share handles and write-through moves. When an explicit external report root is missing, GM2Godot creates and durability-syncs each parent entry before descending. Ordinary failures restore the complete prior pair, but a hard crash between the two file commits is not yet pair-atomic, so keep the reports with the latest attempt evidence rather than treating either filename alone as a generation marker.

The four static compatibility reports use the same retained binding as one deterministic ordered transaction. Rendering completes before publication; the transaction then snapshots and backs up every target, commits and durability-syncs each new report, and validates the complete result. An ordinary failure restores the prior bytes and modes or reports a verified recovery artifact when rollback cannot safely finish; it no longer deletes the prior set.

## Terminal outcomes

Every valid `convert` command prints exactly one terminal line beginning `GM2Godot conversion outcome:`. When the current JSON diagnostic report is published successfully, it carries the same state and ledgers.

| State | Meaning |
| --- | --- |
| `success` | Every requested converter step and every tracked resource completed. This is not a claim of perfect GameMaker behavior; review compatibility diagnostics and validate in Godot. |
| `partial` | Every requested converter step completed, but at least one tracked resource was skipped or failed. The output can be useful, but the missing work must be understood. |
| `failed` | The latest invocation terminated as a failure, so its filesystem output must not be assumed usable from that state alone. `failed_step` and `failure_phase` identify preflight, runtime, report, or finalizer context when available. A digest-verified prior canonical generation can remain, or a separate managed-output recovery artifact can report that the durable decision selected the desired generation before cleanup failed. |
| `cancelled` | A user stop request or `SIGINT` was observed before the final cooperative cancellation check that precedes managed-generation publication. The prior public generation is preserved and verified. |

The GUI uses the same terminal outcome instead of inferring success from the worker thread returning. Full success is green, partial output is amber, failure is red, and cancellation is blue. Every state prints the exact resource counts. A usable partial result also prints the absolute path to `gm2godot/conversion_diagnostics.md`; it never receives the green full-success message.

The managed-generation commit point is the final cooperative cancellation check immediately before recoverable publication. GUI stop, direct-library cancellation, and CLI `SIGINT` agree before that point: recovery finishes safely, the prior generation remains verified, and the attempt is `cancelled` (`SIGINT` exits `130`). After publication begins, the old-or-new decision must finish; a late stop cannot claim rollback or relabel committed public output.

For converters and resources, `requested = completed + skipped + failed`. Completed and failed work was executed. A resource or converter interrupted after it started can be recorded as both executed and skipped, so `executed` and `skipped` are intentionally not disjoint. The named `steps` ledger follows conversion-plan order and is usually the clearest place to find where work stopped.

## Exit codes and CI thresholds

| Result | Exit code |
| --- | ---: |
| Success, with thresholds passing | `0` |
| Partial output | `2` |
| Partial output with `--allow-partial`, with thresholds passing | `0` |
| Any diagnostic threshold violation, including with `--allow-partial` | `2` |
| Destination preflight rejection | `2` |
| Failed conversion or runtime/report/finalizer exception | `1` |
| Cancelled conversion | `130` |

`--allow-partial` applies only to `convert`. It changes the exit-code treatment of a usable `partial` outcome; it does not turn the state into `success` and does not override any diagnostic threshold.

Available thresholds are:

- `--fail-on-unsupported`: fail when any diagnostic is identified as unsupported.
- `--max-unsupported N`: fail when unsupported diagnostics exceed `N`.
- `--max-warnings N`: fail when warnings exceed `N`.
- `--max-errors N`: fail when errors exceed `N`; the default is `0`.

Use `--allow-partial` in CI only after the skipped/failed resources are intentional and covered by an explicit migration plan. A zero exit code with that flag still represents a `partial` artifact.

## Attempt ledger versus trusted manifest

`conversion_attempt.json` is format v1 and answers “what happened in the latest invocation?” `conversion_manifest.json` is format v2 and answers “what trustworthy successful/partial output was canonically recorded?” Managed files and canonical evidence are committed and recovered as one destination-wide generation. Failed or cancelled work before the generation decision publishes only a new attempt after verifying the preserved prior inventory; its staged diagnostics and architecture report never replace the prior canonical files.

Inside the format-v2 manifest, `generation_inventory` is an additive format-v1 object. Its sorted `entries` are the complete desired managed generation, including unchanged disabled-converter carry-forward and jointly managed `project.godot`. Each entry records `path`, `kind`, `owner`, `byte_count`, `sha256`, and `mode`. Existing consumers may continue reading `generated_files`; it is now the path/kind/digest projection of the same frozen inventory, with the existing canonical-manifest `sha256: "self"` row. The inventory excludes the manifest itself, latest attempt, `.godot/`, locks, recovery records, private stages/backups, and unrelated paths.

For a 0.7.43 `partial` commit, selected object, room, sprite, shader, and timeline-action outputs that were unavailable, blocked, skipped, or removed are intentionally absent from the inventory. The generated asset registry omits missing object/room/sprite/shader rows, and timeline metadata omits missing action-script paths; the canonical manifest is reconciled against that same frozen inventory. A failed or cancelled pre-decision attempt is different: it preserves the complete prior generation, so use the attempt state and `canonical_manifest.current_output` before interpreting old resource files.

From 0.7.47, sequence descriptors are also required asset-registry-owned outputs. A supported sequence with an unsupported sibling track/key remains present as a freshly generated partial descriptor; a missing or rejected sequence output is omitted rather than retaining a stale `.tres`.

Read `canonical_manifest` in the attempt ledger:

| `status` | `updated` | `current_output` | How to interpret it |
| --- | ---: | --- | --- |
| `updated` | `true` | `verified` | This generation committed a new canonical manifest with the attempt ledger. Verify the file's raw-byte SHA-256 against the ledger before consuming it. |
| `preserved` | `false` | `verified` | The destination-wide transaction verified or restored the complete prior managed generation and its digest-matching canonical manifest before publishing this attempt. |
| `preserved` | `false` | `unverified` | A regular canonical file already existed and was left untouched. Its recorded digest identifies those bytes, but preservation does not prove that its schema or contents describe the current destination or latest attempt. |
| `absent` | `false` | `unavailable` | No canonical manifest exists; `sha256` is `null`. |

The digest string is `sha256:` followed by the lowercase hash of the raw `conversion_manifest.json` bytes. Before either public file changes, GM2Godot durably records the complete previous and desired pair in `.gm2godot-conversion-transaction.json`. It publishes the attempt first and canonical manifest second through one verified directory binding, then atomically switches `.gm2godot-conversion-generation.json`. Recovery under the project-local operating-system lock restores the prior pair before that switch or verifies the new pair after it. POSIX uses descriptor-relative no-follow operations and directory `fsync()`; Windows retains a reparse-checked handle, nonblocking byte-range lock, and write-through moves.

The generation pointer persists; the transaction journal is removed only after the selected pair and cleanup are verified. A hard exit during journal staging, either public replacement, the pointer switch, rollback, or cleanup therefore recovers to one complete pair. Continue checking the digest as defense in depth, but a mismatch is no longer a normal interrupted-publication state after migration. The first 0.7.32 publication migrates only a digest-consistent legacy pair (or a fully absent pair); pre-existing mismatch and malformed, redirected, mounted, hard-linked, replaced, oversized, or unknown reserved state are preserved and rejected instead of guessed at or deleted.

Even when the digest matches, inspect both records:

1. Read the latest attempt's `attempt.state`, `failed_step`, and `failure_phase`.
2. Require `canonical_manifest.current_output` to be `verified` when consuming either a newly committed or transactionally preserved generation.
3. Compare the recorded digest with the canonical file bytes.
4. Read the canonical manifest's own `conversion.state`; only `success` and `partial` are canonical states.
5. For `partial`, inspect resource counts and diagnostics before using the output.

After `failed` or `cancelled`, never assume that an existing manifest describes the latest filesystem merely because the file is present. Keep the attempt ledger with any diagnostic bundle you attach to an issue.

Malformed, oversized, absolute, escaping, case-colliding, redirected, mounted, cross-device, non-regular, or multiply-linked inventory state is rejected before a new canonical publication. Preserve the named paths and error instead of editing the manifest to force migration. Inventory records are capped at 32 MiB and 100,000 entries. A digest mismatch after a same-size edit remains a mismatch even if timestamps were restored.

## Validate with Godot 4.7.1

Run validation after conversion:

```bash
python main.py validate \
  --godot-project path/to/GodotProject \
  --godot-bin path/to/Godot-4.7.1 \
  --fail-on-unsupported
```

Godot binary discovery uses the first existing file in this order:

1. `--godot-bin`
2. the `GODOT_BIN` environment variable
3. `godot` on `PATH`
4. `/Applications/Godot.app/Contents/MacOS/Godot` on macOS

An explicit or environment path that is not a file is skipped and discovery continues. The selected file must still be executable. Check it directly with `path/to/godot --version`; the pinned CI baseline is the official `4.7.1.stable.official.a13da4feb` build.

If no Godot binary is found, validation records `status: "skipped"` and an informational diagnostic. It does **not** prove the project is valid and is not a hard failure by itself. Set `GODOT_BIN` or pass `--godot-bin` to get real parser/resource validation.

With a binary available, validation asks Godot to import supported asset types and loads every `.gd`, `.gdshader`, `.tscn`, and `.tres` resource under the destination project (excluding `.godot/`), not only GM2Godot-managed files. It records Godot warning/error output as validation issues. `--godot-boot-frames N` additionally boots the configured main scene headlessly for `N` frames after resource validation; it is disabled by default. Use `--skip-godot-validation` only when intentionally limiting `validate` to existing reports and project-presence checks.

## Common failures

| Symptom | What to check |
| --- | --- |
| Preflight exits `2` and no managed generation was published | Use a missing or empty destination, or a valid existing Godot project with a regular `project.godot`. GM2Godot refuses a non-empty non-project directory and unsafe redirected or conflicting managed-output paths. Recovery and lock acquisition precede preflight, so the persistent private lock/workspace parent may be initialized, but no attempt, canonical report, or managed project file is published. |
| “No `.yyp` found” or the wrong project is analyzed | Pass the GameMaker project root that directly contains the `.yyp`. The GUI rejects multiple `.yyp` files; `analyze` warns about them, while headless project readers select the sorted first valid candidate. Separating projects is safer. |
| Outcome is `partial` | Read `outcome.resources`, the ordered `steps` ledger, and warning/error rows in `conversion_diagnostics.json`. Search the generated compatibility reports for the affected API or resource family before choosing `--allow-partial`. |
| Unsupported GML call or extension | Use the diagnostic's `api`, `manifest_entry`, `issue_number`, and `workaround`. Native extensions and service SDKs need a reviewed Godot addon/GDExtension or explicit local mapping; a generated stub is not a working native integration. |
| Runtime says a custom Godot `Callable` lacks explicit receiver metadata | Do not add or remove guessed arguments. Use a transpiled GML function/method or the generated script registry path so GM2Godot can preserve the receiver contract. If converter-generated output reaches this error without hand edits or an extension bridge, report the minimal GML source and generated call site. |
| Godot validation is `skipped` | Fix `--godot-bin`/`GODOT_BIN`, check executable permissions, and confirm `--version` reports the official 4.7.1 build. |
| Godot reports a parse, load, import, or boot error | Open `godot_validation_report.json` and fix the first retained Godot issue. Correlate generated scripts with adjacent `.gmlmap.json` source maps when present, then rerun validation. Boot warnings also fail boot validation. |
| Converted output runs but differs from GameMaker | Check [Compatibility and Limitations](Compatibility-and-Limitations), `architecture_policy.json`, platform capabilities, and the affected resource/API report. Create the smallest fixture that preserves the mismatch. |
| Another GM2Godot conversion is already publishing or recovering Included Files | Let the active converter finish, then retry. A leftover lock file is normal and does not itself mean the lock is held; do not delete it. Close any live game or editor operation using Included Files before retrying. |
| Included Files recovery rejects an invalid journal, commit marker, staging path, or unknown replacement | Preserve the named paths and the full error. GM2Godot intentionally leaves unknown content untouched rather than guessing ownership. Do not delete or rename it until you have backed up the destination and identified whether it is converter-owned; attach the artifacts and diagnostics to a bug report if ownership is unclear. |
| Conversion artifact recovery rejects its journal, generation pointer, lock, public pair, or reserved temporary state | Preserve the complete `gm2godot/` directory and error. Do not edit the digest, pointer, or recovery records to force acceptance. Back up the destination, identify any non-cooperating writer or pre-0.7.32 mismatch, and attach the preserved state to a bug report if ownership is unclear. |
| Destination-wide recovery reports `.gm2godot-managed-output-recovery.json` | Close Godot and all writers. Preserve `.gm2godot-managed-output/`, the named public paths, and the error. Read `selected_generation`: retry recovery for `previous` or `desired`; treat `unknown` as ambiguous and do not use either generation. Fix only the reported permission/device cause, then rerun conversion or call `recover_managed_output_generation(destination_path)`. Never delete or rewrite the journal, pointer, stage, transaction ID, or digest by guesswork. |
| An Included Files recovery record exceeds the 16 MiB canonical size limit | Preserve the generated project and error. A newly generated format-v2 record is byte-preflighted before payload staging, so the previous public generation remains unchanged; an oversized reserved-path record found during recovery is intentionally not parsed or deleted. Report the Included File count and path shape rather than raising the parser-memory ceiling. |
| A hidden `.gm2godot-included-cleanup.*` entry remains after a Windows machine power loss | Do not move it onto either public Included Files path or delete it by guesswork. Windows can replay a completed hidden deletion without replaying the write-through public generation moves; preserve the project and attach the entry plus recovery diagnostics to a bug report so ownership can be verified safely. |
| A packaged Included File exists on disk but generated file APIs treat it as missing | Format-v2 startup prevalidation requires every emitted payload to match its exact recorded byte count and SHA-256 before any packaged entry is exposed. One hand edit, missing file, malformed receipt, incomplete external copy, or concurrent publication rejects the complete generation. Close the live game, restore the source input, and rerun conversion so the root and registry are regenerated together. `GMRuntime.gml_included_file_integrity_status()` can distinguish an unavailable registry from a failed or incomplete prewarm. |
| An old manifest is still present after failure or cancellation | This can be deliberate preservation. Trust the latest attempt ledger's status and digest rules, not the manifest filename alone. |
| Report or artifact publication fails | Preserve stderr and exception detail, do not treat old reports as current, and retry in a writable local destination after checking permissions and filesystem redirection. Attach both ledgers if they exist. |

## Report the right kind of issue

Use the [GitHub issue chooser](https://github.com/Infiland/GM2Godot/issues/new/choose) or its focused templates:

- [Unsupported GML API](https://github.com/Infiland/GM2Godot/issues/new?template=unsupported_gml_api.yml) for a missing function, variable, constant, or language feature.
- [Invalid Generated GDScript](https://github.com/Infiland/GM2Godot/issues/new?template=invalid_generated_gdscript.yml) when Godot cannot parse or load generated code/resources.
- [Resource Conversion Mismatch](https://github.com/Infiland/GM2Godot/issues/new?template=resource_conversion_mismatch.yml) for sprite, sound, room, object, tileset, shader, path, sequence, extension, option, or other resource differences.
- [Fixture Contribution](https://github.com/Infiland/GM2Godot/issues/new?template=fixture_contribution.yml) for a minimal reproducible project or regression case.

Include the smallest legal source/fixture, exact reproduction command, terminal output, `conversion_diagnostics.json`, `conversion_attempt.json`, the digest-matching manifest when applicable, `godot_validation_report.json`, and the GM2Godot/GameMaker/Godot/host/target-platform versions. Remove proprietary assets and secrets before uploading. Contributor expectations and test commands are documented in [Contributing and Testing](Contributing-and-Testing) and the repository's canonical [CONTRIBUTING.md](https://github.com/Infiland/GM2Godot/blob/main/CONTRIBUTING.md).
