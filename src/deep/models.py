"""Read-only model discovery and selection policy, independent of Qt."""
from __future__ import annotations

import copy
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from src.deep.credentials import credential_environment
from src.deep.install import ExtensionManager, opencode_path
from src.deep.session import DeepSession
from src.deep.settings import DeepSettings


@dataclass(frozen=True)
class DiscoveredModel:
    id: str
    name: str
    provider: str
    provider_name: str
    authenticated: bool | None = None
    free_eligible: bool = False
    available: bool = True


@dataclass(frozen=True)
class ModelCatalog:
    models: tuple[DiscoveredModel, ...]
    installed: bool
    authenticated: bool | None
    reason: str
    resume_model_selection: bool = False


def parse_catalog(result: dict[str, Any], provider: str) -> ModelCatalog:
    capability = result.get("provider", {})
    if not isinstance(capability, dict):
        raise ValueError("Deep returned an invalid provider catalog")
    capability = cast(dict[str, Any], capability)
    authentication = capability.get("authenticated")
    authenticated = authentication if isinstance(authentication, bool) else None
    models: list[DiscoveredModel] = []
    seen: set[tuple[str, str]] = set()
    entries = capability.get("models", [])
    if not isinstance(entries, list):
        entries = []
    for value in cast(list[Any], entries):
        if not isinstance(value, dict):
            continue
        raw = cast(dict[str, Any], value)
        if not isinstance(raw.get("id"), str) or not raw["id"].strip():
            continue
        owner = raw.get("provider") or provider
        if not isinstance(owner, str):
            continue
        identity = (owner, raw["id"])
        if identity in seen:
            continue
        seen.add(identity)
        auth = raw.get("authenticated", authenticated)
        models.append(DiscoveredModel(
            id=raw["id"], name=str(raw.get("name") or raw["id"]), provider=owner,
            provider_name=str(raw.get("providerName") or owner),
            authenticated=auth if isinstance(auth, bool) else None,
            free_eligible=owner == "opencode" and raw.get("freeEligible") is True,
            available=raw.get("available") is not False and raw.get("toolcall") is not False,
        ))
    return ModelCatalog(tuple(models), capability.get("installed") is True, authenticated, str(capability.get("reason") or ""),
                        isinstance(result.get("features"), dict) and result["features"].get("resumeModelSelection") is True)


def preferred_go_model(catalog: ModelCatalog, free_only: bool) -> DiscoveredModel | None:
    """Recommend the requested exact discovered model; never infer a free tier."""
    if free_only:
        return None
    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())
    return next((model for model in catalog.models if model.available and model.authenticated is True
                 and normalize(model.provider) == "opencodego"
                 and (normalize(model.id) == "deepseekv41flash" or normalize(model.name) == "deepseekv41flash")), None)


def discover_models(settings: DeepSettings, installation: Path | None = None) -> ModelCatalog:
    """Capabilities send no project source and make no inference calls."""
    selection = copy.deepcopy(settings)
    environment = credential_environment(selection.provider)
    binary = opencode_path()
    if binary:
        environment["PATH"] = os.path.dirname(binary) + os.pathsep + os.environ.get("PATH", "")
    with tempfile.TemporaryDirectory(prefix="gm2godot-models-") as temporary:
        session = DeepSession(ExtensionManager().command(installation), Path(temporary), environment=environment)
        try:
            response = session.request("capabilities", {"settings": selection.to_dict()}, timeout=60)
            return parse_catalog(response.get("result", {}), selection.provider)
        finally:
            session.close()
