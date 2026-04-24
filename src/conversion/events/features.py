import importlib
import pkgutil

from src.conversion.events import script_features


def get_script_features():
    modules = sorted(pkgutil.iter_modules(script_features.__path__), key=lambda module: module.name)
    return [
        importlib.import_module(f"{script_features.__name__}.{module.name}")
        for module in modules
        if not module.ispkg
    ]
