# Optional Deep conversion

Deep adds AI research and reviewed candidate conversion to GM2Godot. It is disabled by default. Ordinary conversion needs no AI account, extension download, Node, npm or coding agent.

## Setup

Open **Settings → Deep setup**, download the compatible components, and select a provider and model. The extension includes its own Node runtime. Its source is maintained at [gm2godot-deep](https://github.com/Infiland/gm2godot-deep); users do not clone it.

Choose an existing Codex, Claude Code or OpenCode installation, or an API provider. The setup panel can install a pinned official OpenCode binary privately in GM2Godot's application data. Existing global installations and settings remain untouched. Application-managed API keys use the OS keyring; coding agents can use their existing sign-in.

**Automatic · Free models** checks current OpenCode Zen pricing and evaluates up to five eligible models against four small conversion cases. It selects the best passing result for each role on that evaluation, with no paid fallback. Free availability and data-use terms can change: see [OpenCode Zen](https://opencode.ai/docs/zen/). If pricing or credentials cannot be verified, or no candidate passes, research pauses.

Research defaults to four workers, capped at one for free providers. Both limits are adjustable from 1–32. Token, time and available monetary usage limits are configurable. Native coding agents do not always report cost or support an exact response-token ceiling; reported usage and unknown usage remain distinct.

## Research and review

Enable **Deep conversion**, then start conversion. GM2Godot prepares the ordinary baseline first and asks before sending source to the selected provider. Enabling the option alone does not start remote analysis.

Deep inventories source files, reads relevant text in bounded chunks, tracks binary metadata, and researches resource dependencies using official GameMaker and Godot documentation. Research reports record behavior, lifecycle, state, source citations, documentation provenance, conversion instructions, uncertainties and blockers.

At **Review plan**, inspect the findings and proposed output changes. Starting conversion uses that saved plan and existing research. Candidate changes are staged and validated, then exposed in a fresh sibling such as `MyPort-deep` or a numbered alternative. The source and baseline remain intact.

The report distinguishes files accounted for, conversion results, engine validation and behavioral evidence. Missing Godot permits research but leaves engine validation unavailable. Mock runs are simulations. Candidate staging is not an OS execution sandbox.

## Live progress and controls

**Deep progress** has scrollable Agents, Research and Implementation lists. Search by resource, task or model and filter pending, active, completed or blocked work. Select a row to read its current tool activity, saved findings, attempt, provider/model or failure reason. Research and implementation remain separate; task accounting is not a claim of behavioral correctness.

**Apply limits** changes research concurrency while a job runs. Decreasing the limit lets active agents finish; increasing it dispatches more queued work within the free-provider cap. Implementation integration stays serialized. **Pause and save** keeps completed work, and **Change model…** pauses before opening the discovered-model picker. Rate limits, unavailable credentials and exhausted budgets leave a resumable checkpoint rather than cancelling the conversion. **Open saved progress** opens the job's reports and evidence directory.

Settings remain accessible during conversion. Baseline options are copied when the worker starts; edits apply to future baseline conversions. Deep setup choices apply when research starts. Use the live controls for changes to an existing Deep job. The timer accumulates active baseline, research and implementation time, pauses during review or suspension, and survives reopening a saved job. Progress displays two decimal places.

Setup and resume discover models without sending project files or making inference calls. The picker shows provider names, model names and sign-in status, retains explicit saved choices, and offers advanced custom entry where discovery is unavailable. When a connected OpenCode Go provider advertises **DeepSeek V4.1 Flash**, it is the preferred suggestion for users who have enabled paid providers. An absent model is never invented and free-only jobs never switch to Go. Verified free alternatives can also be selected explicitly.

These controls are capability-negotiated. Old extension packages continue to run with a clear update hint; a saved job always uses its pinned installation.

## Pause, resume and repair

Closing GM2Godot requests a graceful pause. Reopening offers saved jobs; **Deep → Resume saved job** also opens them. Resume can raise cumulative token/cost limits, grant more running time and adjust concurrency. A compatible extension can switch the selected provider/model for future tasks while keeping completed findings and their original model provenance. Free-only jobs keep that policy. Older pinned extensions retain their original model; install updated components for new jobs. Changed source or baseline hashes currently require a new job; selective cross-job reuse is not implemented.

Installations live in the user application-data directory under `GM2Godot/deep`. Downloads are checksum-verified before atomic activation. Repeating setup reuses verified downloads or repairs corrupt installations. Previous versions are retained for saved jobs. Interrupted downloads can be retried; partially downloaded bytes are never activated.

## CLI

Use the packaged executable in place of `python main.py` when installed:

```sh
python main.py deep install
python main.py deep install-opencode
python main.py deep configure --runtime opencode --provider opencode --model automatic-free
python main.py deep models
python main.py deep research --gm-project /games/source --godot-project /games/port --allow-source-upload
python main.py deep status --job /path/printed/by/research
python main.py deep convert --job /path/printed/by/research
python main.py deep resume --job /path/printed/by/research --max-tokens 2000000 --workers 4
```

Research stops for review; inspect `research.md` in the printed job directory before `convert`. `--reuse-baseline` researches an existing baseline. API credentials can be read from standard input using `deep configure --api-key-stdin`; do not put secrets in command arguments or job files.

## Development and release

The public host boundary is a versioned JSONL subprocess protocol plus a GM2Godot-generated source/capability snapshot. Core client modules under `src/deep/` are independent of Qt. GUI presentation and worker lifecycle remain in `src/gui/`; the engine owns research, scheduling, providers, plans and candidates. See the engine's [protocol](https://github.com/Infiland/gm2godot-deep/blob/main/docs/host-protocol.md) and [provider contracts](https://github.com/Infiland/gm2godot-deep/blob/main/docs/providers.md).

`packaging/deep.lock.json` pins the exact public engine commit. The **Build optional Deep extension** workflow builds Windows x64, macOS arm64 and Linux x64 packages with Node 22.19.0, compiled JavaScript, locked production dependencies, schemas and licenses. Each manifest records both source revisions and archive hashes. Packages use an immutable `deep-vX.Y.Z` GM2Godot release; publishing does not replace the latest application release.

Run client Pyright, Ruff, maintainability checks and relevant tests; broad changes require the full unittest suite. Run `npm run build`, `npm test` and packaged smoke tests in Deep. Native CI, live-provider smoke tests and actual Godot checks are separate evidence. A local mock test does not prove provider quality or native-platform installation.
