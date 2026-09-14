"""Credentials belong in the OS keyring, never in project artifacts."""
from __future__ import annotations

import importlib
import os
from typing import Protocol, cast

_ENV_NAMES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google": "GEMINI_API_KEY", "opencode": "OPENCODE_API_KEY", "openrouter": "OPENROUTER_API_KEY"}


class CredentialBackend(Protocol):
    def set_password(self, service_name: str, username: str, password: str) -> None: ...
    def get_password(self, service_name: str, username: str) -> str | None: ...
    def delete_password(self, service_name: str, username: str) -> None: ...


def _backend() -> CredentialBackend:
    try:
        return cast(CredentialBackend, importlib.import_module("keyring"))
    except ImportError as error:
        raise RuntimeError("OS credential storage requires the keyring package. Install GM2Godot's dependencies or use your agent's existing sign-in.") from error


def save_credential(provider: str, secret: str) -> None:
    if provider not in _ENV_NAMES:
        raise ValueError("Key storage is supported for Anthropic, OpenAI, Google, OpenRouter and OpenCode")
    backend = _backend()
    if secret:
        backend.set_password("GM2Godot Deep", provider, secret)
    elif backend.get_password("GM2Godot Deep", provider) is not None:
        backend.delete_password("GM2Godot Deep", provider)


def credential_environment(provider: str) -> dict[str, str]:
    variable = _ENV_NAMES.get(provider)
    if variable is None:
        return {}
    if os.environ.get(variable):
        return {variable: os.environ[variable]}
    try:
        backend = _backend()
        secret = backend.get_password("GM2Godot Deep", provider)
    except Exception:
        # Headless machines may have no keyring service; existing agent login/environment remains usable.
        return {}
    return {variable: secret} if secret else {}
