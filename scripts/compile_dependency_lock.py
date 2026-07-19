from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
import subprocess
import sys


def _is_inherited_python_or_pip_setting(name: str) -> bool:
    normalized = name.upper()
    return normalized.startswith("PYTHON") or normalized.startswith(("PIP_", "PIP_TOOLS_"))


def build_isolated_environment(source: Mapping[str, str]) -> dict[str, str]:
    environment = {
        name: value
        for name, value in source.items()
        if not _is_inherited_python_or_pip_setting(name)
    }
    environment["PIP_CONFIG_FILE"] = os.devnull
    return environment


def normalize_child_returncode(returncode: int, platform_name: str) -> int:
    if returncode >= 0:
        return returncode
    if platform_name == "posix":
        return 128 - returncode
    return 1


def main(arguments: Sequence[str] | None = None) -> int:
    compile_arguments = tuple(sys.argv[1:] if arguments is None else arguments)
    command = [sys.executable, "-I", "-m", "piptools", "compile", *compile_arguments]
    try:
        completed = subprocess.run(
            command,
            check=False,
            env=build_isolated_environment(os.environ),
            shell=False,
            stdin=subprocess.DEVNULL,
        )
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        print(
            f"Unable to start the isolated pip-tools compiler with {sys.executable!r}: {error}",
            file=sys.stderr,
        )
        return 127
    return normalize_child_returncode(completed.returncode, os.name)


if __name__ == "__main__":
    raise SystemExit(main())
