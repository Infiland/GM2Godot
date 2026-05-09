import importlib
import pkgutil
from types import ModuleType
from typing import Any, cast

from src.conversion.events import script_features


def get_script_features() -> list[ModuleType]:
    package_info = cast(Any, script_features)
    modules = sorted(pkgutil.iter_modules(package_info.__path__), key=lambda module: module.name)
    return [
        importlib.import_module(f"{package_info.__name__}.{module.name}")
        for module in modules
        if not module.ispkg
    ]
