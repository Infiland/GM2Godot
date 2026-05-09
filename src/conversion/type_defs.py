from __future__ import annotations

from os import PathLike
from typing import Any, Callable, Protocol, TypeAlias


JsonDict: TypeAlias = dict[str, Any]
JsonList: TypeAlias = list[Any]
JsonValue: TypeAlias = Any
StrPath: TypeAlias = str | PathLike[str]

LogCallback: TypeAlias = Callable[[str], None]
ProgressCallback: TypeAlias = Callable[[int | float], None]
ConversionRunning: TypeAlias = Callable[[], bool]


class BoolSetting(Protocol):
    def get(self) -> bool: ...
