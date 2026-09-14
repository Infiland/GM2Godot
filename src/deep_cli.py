"""Headless commands for the optional Deep extension; imported only on demand."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from src.deep.credentials import credential_environment, save_credential
from src.deep.host_snapshot import write_host_snapshot
from src.deep.install import DEFAULT_MANIFEST_URL, ExtensionManager, opencode_path
from src.deep.jobs import DeepJob
from src.deep.opencode import install_opencode
from src.deep.session import DeepSession
from src.deep.settings import DeepSettings, load_settings, save_settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="GM2Godot deep", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install", help="Download and verify the optional Deep extension")
    install.add_argument("--manifest-url", default=DEFAULT_MANIFEST_URL)
    commands.add_parser("install-opencode", help="Install the pinned optional OpenCode runtime")
    configure = commands.add_parser("configure", help="Save provider and research preferences")
    configure.add_argument("--runtime", choices=("pi", "codex", "claude", "opencode"))
    configure.add_argument("--provider")
    configure.add_argument("--model")
    configure.add_argument("--workers", type=int)
    configure.add_argument("--allow-paid", action="store_true")
    configure.add_argument("--api-key-stdin", action="store_true", help="Read a key from stdin into the OS keyring")
    commands.add_parser("models", help="Discover installed agent and provider capabilities")
    research = commands.add_parser("research", help="Prepare a baseline and research the source; stops for plan review")
    research.add_argument("--gm-project", required=True)
    research.add_argument("--godot-project", required=True)
    research.add_argument("--reuse-baseline", action="store_true", help="Use an existing converter baseline")
    research.add_argument("--allow-source-upload", action="store_true", help="Allow the selected provider to read project content")
    research.add_argument("--godot-bin")
    for name in ("convert", "resume", "status"):
        command = commands.add_parser(name, help=f"{name.capitalize()} an existing Deep job")
        command.add_argument("--job", type=Path, required=True)
        if name == "resume":
            command.add_argument("--workers", type=int)
            command.add_argument("--free-workers", type=int)
            command.add_argument("--max-tokens", type=int)
            command.add_argument("--max-cost-usd", type=float)
            command.add_argument("--max-seconds", type=int)
    return parser


def _configure(args: argparse.Namespace) -> int:
    settings = load_settings()
    for field in ("runtime", "provider", "model"):
        value = getattr(args, field)
        if value is not None:
            setattr(settings, field, value)
    if args.workers is not None:
        settings.analysisWorkers = args.workers
    if args.allow_paid:
        settings.freeOnly = False
        settings.budgets["maxCostUsd"] = 20
    settings.validate()
    if args.api_key_stdin:
        save_credential(settings.provider, sys.stdin.read().strip())
    save_settings(settings)
    print("Deep preferences saved.")
    return 0


def _environment(settings: DeepSettings) -> dict[str, str]:
    if settings.runtime == "mock":
        return {}
    environment = credential_environment(settings.provider)
    for override in settings.roleOverrides.values():
        provider = override.get("provider")
        if provider:
            environment.update(credential_environment(provider))
    binary = opencode_path()
    if binary:
        environment["PATH"] = str(Path(binary).parent) + os.pathsep + os.environ.get("PATH", "")
    return environment


def _event(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def run_job(job: DeepJob, method: str) -> int:
    manager = ExtensionManager()
    session = DeepSession(manager.command(job.installation), job.root, _event, _environment(job.settings))
    try:
        response = session.request(method, job.params())
        _event(response)
        result: dict[str, Any] = response.get("result", {})
        state = str(result.get("state", result.get("status", "")))
        if method != "status":
            job.phase = state if state in {"review", "complete", "partial", "paused", "cancelled"} else "paused"
            job.save()
        return 1 if result.get("error") or state in {"failed", "blocked", "partial", "paused"} else 0
    except KeyboardInterrupt:
        session.notify("pause", {"jobRoot": str(job.root)})
        job.phase = "paused"
        job.save()
        return 130
    finally:
        session.close()


def _research(args: argparse.Namespace) -> int:
    settings = load_settings()
    if not args.allow_source_upload:
        raise ValueError(f"Research sends source to {settings.provider or settings.runtime}; pass --allow-source-upload")
    settings.allowRemoteSourceUpload = True
    settings.godotBinary = args.godot_bin or settings.godotBinary
    manager = ExtensionManager()
    manager.command()  # Check installation before running the normal converter.
    if not args.reuse_baseline:
        from src.cli import main as convert_main

        result = convert_main(["convert", "--gm-project", args.gm_project, "--godot-project", args.godot_project])
        if result not in {0, 1} or not Path(args.godot_project, "project.godot").is_file():
            return result or 1
    job = DeepJob.create(args.gm_project, args.godot_project, settings, manager)
    write_host_snapshot(job.source, str(job.root / "host-snapshot.json"))
    print(f"Deep job: {job.root}", file=sys.stderr)
    return run_job(job, "research")


def _resume_settings(job: DeepJob, args: argparse.Namespace) -> None:
    for argument, field in (("max_tokens", "maxTokens"), ("max_cost_usd", "maxCostUsd"), ("max_seconds", "maxSeconds")):
        value = getattr(args, argument)
        if value is not None:
            if value < job.settings.budgets.get(field, 0):
                raise ValueError("Resume limits cannot be reduced")
            if field == "maxCostUsd" and job.settings.freeOnly and value != 0:
                raise ValueError("Free-only jobs cannot acquire a paid budget")
            job.settings.budgets[field] = value
    if args.workers is not None:
        job.settings.analysisWorkers = args.workers
    if args.free_workers is not None:
        job.settings.freeProviderConcurrency = args.free_workers
    job.settings.validate()
    job.save()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "install":
            print(ExtensionManager().install(args.manifest_url))
            return 0
        if args.command == "install-opencode":
            print(install_opencode())
            return 0
        if args.command == "configure":
            return _configure(args)
        if args.command == "research":
            return _research(args)
        if args.command == "models":
            manager = ExtensionManager()
            settings = load_settings()
            session = DeepSession(manager.command(), manager.root / "discovery", environment=_environment(settings))
            try:
                _event(session.request("capabilities", {"settings": settings.to_dict()}, timeout=60))
            finally:
                session.close()
            return 0
        job = DeepJob.load(args.job)
        if args.command == "resume":
            _resume_settings(job, args)
        return run_job(job, args.command)
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        print(f"Deep: {error}", file=sys.stderr)
        return 1
