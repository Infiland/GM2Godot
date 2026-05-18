# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
from collections.abc import Iterable as IterableABC, Mapping as MappingABC
from typing import Any, Iterable, Mapping, cast

from .model import GMLExtensionFunction, GMLExtensionFunctionMapping


EXTENSION_FUNCTION_MAPPING_FILENAME = "gm2godot_extension_functions.json"


def normalize_extension_functions(value: object) -> dict[str, GMLExtensionFunction]:
    if value is None:
        return {}
    result: dict[str, GMLExtensionFunction] = {}
    if isinstance(value, MappingABC):
        value_mapping = cast(Mapping[Any, Any], value)
        for raw_name, raw_metadata in value_mapping.items():
            name = str(raw_name)
            result[name] = _extension_function_from_value(name, raw_metadata)
        return result
    if isinstance(value, IterableABC) and not isinstance(value, (str, bytes)):
        value_iterable = cast(Iterable[Any], value)
        for raw_item in value_iterable:
            if isinstance(raw_item, GMLExtensionFunction):
                result[raw_item.name] = raw_item
            else:
                name = str(raw_item)
                result[name] = GMLExtensionFunction(name=name)
        return result
    raise TypeError("extension_functions must be a mapping or iterable")


def normalize_extension_function_mappings(value: object) -> dict[str, GMLExtensionFunctionMapping]:
    if value is None:
        return {}
    if not isinstance(value, MappingABC):
        raise TypeError("extension_function_mappings must be a mapping")
    result: dict[str, GMLExtensionFunctionMapping] = {}
    value_mapping = cast(Mapping[Any, Any], value)
    for raw_name, raw_mapping in value_mapping.items():
        name = str(raw_name)
        result[name] = _extension_mapping_from_value(name, raw_mapping)
    return result


def load_gml_extension_function_mappings(path: str) -> dict[str, GMLExtensionFunctionMapping]:
    with open(path, encoding="utf-8") as mapping_file:
        data = json.load(mapping_file)
    if not isinstance(data, MappingABC):
        raise ValueError("extension mapping file must contain a JSON object")
    data_mapping = cast(Mapping[Any, Any], data)
    raw_functions = data_mapping.get("functions", data_mapping)
    if not isinstance(raw_functions, MappingABC):
        raise ValueError("extension mapping file field 'functions' must contain an object")
    return normalize_extension_function_mappings(cast(Mapping[Any, Any], raw_functions))


def diagnostic_for_unmapped_extension_function(function: GMLExtensionFunction) -> str:
    extension = f" from extension '{function.extension_name}'" if function.extension_name else ""
    return (
        f"GML extension function '{function.name}'{extension} has no GM2Godot mapping; "
        f"add it to {EXTENSION_FUNCTION_MAPPING_FILENAME} or provide a Godot addon/GDExtension hook. "
        "Native extension calls are not emitted implicitly because they may require closed SDKs or unsafe platform bindings."
    )


def validate_extension_mapping_arity(
    mapping: GMLExtensionFunctionMapping,
    arg_count: int,
) -> str | None:
    if mapping.min_args is None and mapping.max_args is None:
        return None
    min_args = mapping.min_args if mapping.min_args is not None else 0
    max_args = mapping.max_args
    if arg_count < min_args:
        return _extension_mapping_arity_message(mapping, min_args, max_args, arg_count)
    if max_args is not None and arg_count > max_args:
        return _extension_mapping_arity_message(mapping, min_args, max_args, arg_count)
    return None


def _extension_function_from_value(name: str, value: object) -> GMLExtensionFunction:
    if isinstance(value, GMLExtensionFunction):
        return value if value.name == name else GMLExtensionFunction(
            name=name,
            extension_name=value.extension_name,
            min_args=value.min_args,
            max_args=value.max_args,
        )
    if isinstance(value, str):
        return GMLExtensionFunction(name=name, extension_name=value)
    if isinstance(value, MappingABC):
        value_mapping = cast(Mapping[Any, Any], value)
        extension_name = _optional_string(value_mapping, "extension_name") or _optional_string(value_mapping, "extension") or ""
        return GMLExtensionFunction(
            name=name,
            extension_name=extension_name,
            min_args=_optional_int(value_mapping, "min_args", "minArgs"),
            max_args=_optional_int(value_mapping, "max_args", "maxArgs"),
        )
    return GMLExtensionFunction(name=name)


def _extension_mapping_from_value(name: str, value: object) -> GMLExtensionFunctionMapping:
    if isinstance(value, GMLExtensionFunctionMapping):
        return value if value.function_name == name else GMLExtensionFunctionMapping(
            function_name=name,
            target=value.target,
            min_args=value.min_args,
            max_args=value.max_args,
        )
    if isinstance(value, str):
        target = value.strip()
        if not target:
            raise ValueError(f"extension mapping for {name} must have a non-empty target")
        return GMLExtensionFunctionMapping(function_name=name, target=target)
    if isinstance(value, MappingABC):
        value_mapping = cast(Mapping[Any, Any], value)
        target = _optional_string(value_mapping, "target") or _optional_string(value_mapping, "call")
        if target is None or not target.strip():
            raise ValueError(f"extension mapping for {name} must have a non-empty target")
        return GMLExtensionFunctionMapping(
            function_name=name,
            target=target.strip(),
            min_args=_optional_int(value_mapping, "min_args", "minArgs"),
            max_args=_optional_int(value_mapping, "max_args", "maxArgs"),
        )
    raise ValueError(f"extension mapping for {name} must be a target string or object")


def _optional_string(value: Mapping[Any, Any], *keys: str) -> str | None:
    for key in keys:
        raw_value = value.get(key)
        if raw_value is not None:
            return str(raw_value)
    return None


def _optional_int(value: Mapping[Any, Any], *keys: str) -> int | None:
    for key in keys:
        raw_value = value.get(key)
        if raw_value is None:
            continue
        if isinstance(raw_value, bool):
            raise ValueError(f"{key} must be an integer")
        return int(raw_value)
    return None


def _extension_mapping_arity_message(
    mapping: GMLExtensionFunctionMapping,
    min_args: int,
    max_args: int | None,
    arg_count: int,
) -> str:
    if max_args is None:
        expected = f"at least {min_args}"
    elif min_args == max_args:
        expected = str(min_args)
    else:
        expected = f"{min_args} to {max_args}"
    return (
        f"GML extension function '{mapping.function_name}' mapping to {mapping.target} "
        f"expects {expected} arguments, got {arg_count}."
    )
