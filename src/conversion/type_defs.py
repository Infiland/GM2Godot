from __future__ import annotations

from os import PathLike
from typing import Any, Callable, Protocol, TypeAlias

# Transitional family/report/event types, retained until their R11–R26 migrations.
# New GameMaker decoding uses validated recursive values from json_values instead.
JsonDict: TypeAlias = dict[str, Any]
JsonList: TypeAlias = list[Any]
JsonValue: TypeAlias = Any
StrPath: TypeAlias = str | PathLike[str]

LogCallback: TypeAlias = Callable[[str], None]
ProgressCallback: TypeAlias = Callable[[int | float], None]
ConversionRunning: TypeAlias = Callable[[], bool]


class BoolSetting(Protocol):
    def get(self) -> bool: ...
