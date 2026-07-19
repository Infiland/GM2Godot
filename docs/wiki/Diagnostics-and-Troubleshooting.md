# Diagnostics and Troubleshooting

> **Applies to:** GM2Godot 0.7.25 · GameMaker LTS 2026 · Godot 4.7.1
>
> **Last reviewed:** 2026-07-19

[Home](Home) · [Quick Start Conversion](Quick-Start-Conversion) · [Compatibility and Limitations](Compatibility-and-Limitations)

When a conversion surprises you, preserve the console output and inspect the latest attempt ledger before opening the generated project. Then read the structured diagnostics and run Godot validation. These files distinguish a usable partial migration from a failed or stale output directory.

## Report files

Paths below are relative to the generated Godot project unless a report directory is stated.

| File | What it tells you | When it is written |
| --- | --- | --- |
| `gm2godot/conversion_attempt.json` | The terminal state of the latest conversion attempt and whether that publication updated, preserved, or found no canonical manifest. | After destination preflight, for every terminal conversion attempt. A rejected preflight does not write into the destination. |
| `gm2godot/conversion_manifest.json` | Format-v2 canonical record of a trustworthy successful or partial conversion, including enabled converters, source metadata, resources, generated-file hashes, source maps, architecture policy, and path diagnostics. | Only when GM2Godot has a trustworthy completed-output candidate. Failed or cancelled work can preserve an older file. |
| `gm2godot/conversion_diagnostics.json` | Machine-readable diagnostic summary, sorted diagnostic entries, and the terminal `outcome` object. | During conversion; also under an explicit report directory for `report`, `analyze`, or `convert --report-dir`. |
| `gm2godot/conversion_diagnostics.md` | Human-readable view of the same diagnostics and outcome. | Published as a pair with the JSON report. |
| `gm2godot/godot_validation_report.json` | Godot binary used, resources checked, import/boot return codes and output, detected warnings/errors, and `passed`, `failed`, or `skipped` status. | By `validate` when headless Godot validation runs or is attempted. |
| `gm2godot/architecture_policy.json` | Generated runtime-manager, room, layer/depth, renderer, collision, audio, file/buffer/network, and signal-queue policy choices. | As part of a conversion. |
| `gm2godot/gml_manual_scope.md`, `gml_api_compatibility.md`, `platform_capability_report.md`, `platform_capability_report.json` | Current global compatibility and target-capability inventory. | Under `--report-dir` for static reporting, analysis, or conversion. |
| `gm2godot/extension_compatibility_report.json` and `group_compatibility_report.json` | Project extension/native-binding findings and texture/audio group compatibility details. | When the corresponding converters inspect those resources. |

The JSON diagnostic entries can include `source_path`, line and column, resource and event/API context, a manifest entry, tracking issue, and workaround. Start with the first `error`, then unsupported warnings, then other warnings.

## Terminal outcomes

Every valid `convert` command prints exactly one terminal line beginning `GM2Godot conversion outcome:`. When the current JSON diagnostic report is published successfully, it carries the same state and ledgers.

| State | Meaning |
| --- | --- |
| `success` | Every requested converter step and every tracked resource completed. This is not a claim of perfect GameMaker behavior; review compatibility diagnostics and validate in Godot. |
| `partial` | Every requested converter step completed, but at least one tracked resource was skipped or failed. The output can be useful, but the missing work must be understood. |
| `failed` | The latest invocation terminated as a failure, so its filesystem output must not be assumed usable. `failed_step` and `failure_phase` identify preflight, runtime, report, or finalizer context when available. A separately digest-verified canonical candidate can still exist from an earlier phase or attempt. |
| `cancelled` | A user stop request or `SIGINT` was observed before the CLI's terminal-summary commit point. Generated output may be incomplete, although a late cancellation can coexist with a separately digest-verified canonical candidate. |

The GUI uses the same terminal outcome instead of inferring success from the worker thread returning. Full success is green, partial output is amber, failure is red, and cancellation is blue. Every state prints the exact resource counts. A usable partial result also prints the absolute path to `gm2godot/conversion_diagnostics.md`; it never receives the green full-success message.

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

`conversion_attempt.json` is format v1 and answers “what happened in the latest invocation?” `conversion_manifest.json` is format v2 and answers “what trustworthy successful/partial output was canonically recorded?” These are independent questions: a late report failure or cancellation can happen after a valid canonical candidate was committed, while another failed attempt can leave an older canonical file in place.

Read `canonical_manifest` in the attempt ledger:

| `status` | `updated` | `current_output` | How to interpret it |
| --- | ---: | --- | --- |
| `updated` | `true` | `verified` | This publication committed a canonical manifest last. Verify the file's raw-byte SHA-256 against the ledger before consuming it. |
| `preserved` | `false` | `unverified` | A regular canonical file already existed and was left untouched. Its recorded digest identifies those bytes, but preservation does not prove that its schema or contents describe the current destination or latest attempt. |
| `absent` | `false` | `unavailable` | No canonical manifest exists; `sha256` is `null`. |

The digest string is `sha256:` followed by the lowercase hash of the raw `conversion_manifest.json` bytes. The attempt and canonical files are each atomically replaced, but they are not one multi-file atomic unit: publication is attempt-first and canonical-last. A missing canonical file or digest mismatch can therefore identify an interrupted pair publication. Do not trust the canonical manifest until the digest matches.

Even when the digest matches, inspect both records:

1. Read the latest attempt's `attempt.state`, `failed_step`, and `failure_phase`.
2. Require `canonical_manifest.current_output` to be `verified` when treating this attempt as a fresh canonical publication.
3. Compare the recorded digest with the canonical file bytes.
4. Read the canonical manifest's own `conversion.state`; only `success` and `partial` are canonical states.
5. For `partial`, inspect resource counts and diagnostics before using the output.

After `failed` or `cancelled`, never assume that an existing manifest describes the latest filesystem merely because the file is present. Keep the attempt ledger with any diagnostic bundle you attach to an issue.

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
| Preflight exits `2` and the destination is unchanged | Use a missing or empty destination, or a valid existing Godot project with a regular `project.godot`. GM2Godot refuses a non-empty non-project directory and unsafe redirected or conflicting managed-output paths. Read the structured stderr diagnostic; a rejected preflight intentionally writes no attempt ledger into that destination. |
| “No `.yyp` found” or the wrong project is analyzed | Pass the GameMaker project root that directly contains the `.yyp`. The GUI rejects multiple `.yyp` files; `analyze` warns about them, while headless project readers select the sorted first valid candidate. Separating projects is safer. |
| Outcome is `partial` | Read `outcome.resources`, the ordered `steps` ledger, and warning/error rows in `conversion_diagnostics.json`. Search the generated compatibility reports for the affected API or resource family before choosing `--allow-partial`. |
| Unsupported GML call or extension | Use the diagnostic's `api`, `manifest_entry`, `issue_number`, and `workaround`. Native extensions and service SDKs need a reviewed Godot addon/GDExtension or explicit local mapping; a generated stub is not a working native integration. |
| Godot validation is `skipped` | Fix `--godot-bin`/`GODOT_BIN`, check executable permissions, and confirm `--version` reports the official 4.7.1 build. |
| Godot reports a parse, load, import, or boot error | Open `godot_validation_report.json` and fix the first retained Godot issue. Correlate generated scripts with adjacent `.gmlmap.json` source maps when present, then rerun validation. Boot warnings also fail boot validation. |
| Converted output runs but differs from GameMaker | Check [Compatibility and Limitations](Compatibility-and-Limitations), `architecture_policy.json`, platform capabilities, and the affected resource/API report. Create the smallest fixture that preserves the mismatch. |
| An old manifest is still present after failure or cancellation | This can be deliberate preservation. Trust the latest attempt ledger's status and digest rules, not the manifest filename alone. |
| Report or artifact publication fails | Preserve stderr and exception detail, do not treat old reports as current, and retry in a writable local destination after checking permissions and filesystem redirection. Attach both ledgers if they exist. |

## Report the right kind of issue

Use the [GitHub issue chooser](https://github.com/Infiland/GM2Godot/issues/new/choose) or its focused templates:

- [Unsupported GML API](https://github.com/Infiland/GM2Godot/issues/new?template=unsupported_gml_api.yml) for a missing function, variable, constant, or language feature.
- [Invalid Generated GDScript](https://github.com/Infiland/GM2Godot/issues/new?template=invalid_generated_gdscript.yml) when Godot cannot parse or load generated code/resources.
- [Resource Conversion Mismatch](https://github.com/Infiland/GM2Godot/issues/new?template=resource_conversion_mismatch.yml) for sprite, sound, room, object, tileset, shader, path, sequence, extension, option, or other resource differences.
- [Fixture Contribution](https://github.com/Infiland/GM2Godot/issues/new?template=fixture_contribution.yml) for a minimal reproducible project or regression case.

Include the smallest legal source/fixture, exact reproduction command, terminal output, `conversion_diagnostics.json`, `conversion_attempt.json`, the digest-matching manifest when applicable, `godot_validation_report.json`, and the GM2Godot/GameMaker/Godot/host/target-platform versions. Remove proprietary assets and secrets before uploading. Contributor expectations and test commands are documented in [Contributing and Testing](Contributing-and-Testing) and the repository's canonical [CONTRIBUTING.md](https://github.com/Infiland/GM2Godot/blob/main/CONTRIBUTING.md).
