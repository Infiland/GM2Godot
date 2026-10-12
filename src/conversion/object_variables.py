"""GameMaker Object Variable Definitions as GML pre-creation code.

An object's Variable Definitions (the object .yy ``properties``), a child
object's overrides of the definitions it inherits (``overriddenProperties``)
and a room instance's overrides (the room instance's ``properties``) store
each value as GML source. GameMaker compiles them into assignments that run
before the instance's Create event: the object's Pre-Create event runs
event_inherited() (its parent's definitions), then the object's overrides of
inherited definitions, then its own definitions; a room-placed instance then
runs its pre-creation code, the values overridden for it in the Room Editor
(manual: The_Asset_Editors/Object_Properties/Object_Variables.htm, "Pre-creation
Code"; runner: StartRoom in _GameMaker.js runs EVENT_PRE_CREATE and the
instance's pPreCreateCode before EVENT_CREATE, and instance_create_depth and
instance_create_layer in Function_Layers.js run EVENT_PRE_CREATE first).

The helpers here turn those entries into the GML source the converter
transpiles like event code.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from src.conversion.json_values import JsonValue

# GameMaker's varType values for a Variable Definition.
VAR_TYPE_REAL = 0
VAR_TYPE_INTEGER = 1
VAR_TYPE_STRING = 2
VAR_TYPE_BOOLEAN = 3
VAR_TYPE_EXPRESSION = 4
VAR_TYPE_ASSET = 5
VAR_TYPE_LIST = 6
VAR_TYPE_COLOUR = 7

# The generated method holding an object's Pre-Create assignments.
VARIABLE_DEFINITIONS_FUNCTION = "_gm_variable_definitions"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GML_STRING_LITERAL_PREFIXES = ('"', "'", '@"', "@'")


@dataclass(frozen=True)
class VariableDefinition:
    """One Variable Definition of an object (a GMObjectProperty)."""

    name: str
    var_type: int
    value: str
    multiselect: bool = False


@dataclass(frozen=True)
class VariableOverride:
    """A new value for an inherited definition (a GMOverriddenProperty).

    ``object_name`` is the object that defines the variable.
    """

    object_name: str | None
    name: str
    value: str


def _entry_value(value: JsonValue) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _reference_name(reference: JsonValue) -> str | None:
    if isinstance(reference, dict):
        name = reference.get("name")
        return name if isinstance(name, str) and name else None
    return None


def parse_variable_definitions(entries: JsonValue) -> tuple[VariableDefinition, ...]:
    """Return an object's Variable Definitions in their .yy order."""
    if not isinstance(entries, list):
        return ()
    definitions: list[VariableDefinition] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # GameMaker 2.3+ names the variable "name"; 2.2 used "varName".
        name = entry.get("name") or entry.get("varName")
        value = _entry_value(entry.get("value"))
        var_type = entry.get("varType", VAR_TYPE_EXPRESSION)
        if not isinstance(name, str) or _IDENTIFIER_RE.match(name) is None or value is None:
            continue
        definitions.append(
            VariableDefinition(
                name=name,
                var_type=var_type if isinstance(var_type, int) and not isinstance(var_type, bool) else VAR_TYPE_EXPRESSION,
                value=value,
                multiselect=entry.get("multiselect") is True,
            )
        )
    return tuple(definitions)


def parse_variable_overrides(entries: JsonValue) -> tuple[VariableOverride, ...]:
    """Return overridden definitions (object or room instance) in their .yy order."""
    if not isinstance(entries, list):
        return ()
    overrides: list[VariableOverride] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = _reference_name(entry.get("propertyId"))
        value = _entry_value(entry.get("value"))
        if name is None or _IDENTIFIER_RE.match(name) is None or value is None:
            continue
        overrides.append(VariableOverride(_reference_name(entry.get("objectId")), name, value))
    return tuple(overrides)


def _gml_string_literal(text: str) -> str:
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def variable_value_gml(value: str, definition: VariableDefinition | None) -> str:
    """Return the GML expression GameMaker assigns for a definition's value.

    Values are GML source: a string is stored with its quotes, an asset by
    its name, a colour as a ``$`` literal. A boolean is stored as True or
    False, and a multi-select list as its selected items separated by commas,
    which the variable receives as an array. ``definition`` gives the type
    (for an override, the definition it overrides); without it the value is
    a plain expression.
    """
    var_type = definition.var_type if definition is not None else VAR_TYPE_EXPRESSION
    stripped = value.strip()
    if var_type == VAR_TYPE_BOOLEAN:
        lowered = stripped.lower()
        if lowered in ("true", "1"):
            return "true"
        if lowered in ("false", "0"):
            return "false"
    if var_type == VAR_TYPE_STRING and not stripped.startswith(_GML_STRING_LITERAL_PREFIXES):
        return _gml_string_literal(value)
    if var_type == VAR_TYPE_LIST and definition is not None and definition.multiselect:
        return f"[{value}]"
    return value


def variable_assignments_gml(assignments: Iterable[tuple[str, str]], *, inherited: bool = False) -> str:
    """Return GML assigning each (name, expression) in order.

    With ``inherited`` the source starts with event_inherited(), which runs
    the parent's definitions first.
    """
    lines = ["event_inherited();"] if inherited else []
    lines.extend(f"{name} = {expression};" for name, expression in assignments)
    return "\n".join(lines) + "\n"


def object_pre_create_gml(
    definitions: Iterable[VariableDefinition],
    overrides: Iterable[VariableOverride],
    inherited_definitions: Mapping[str, VariableDefinition],
    *,
    inherited: bool,
) -> str:
    """Return an object's Pre-Create GML.

    The parent's definitions run first (event_inherited), then the object's
    overrides of inherited definitions, then its own definitions.
    ``inherited_definitions`` maps each inherited variable to its definition.
    """
    assignments = [
        (override.name, variable_value_gml(override.value, inherited_definitions.get(override.name)))
        for override in overrides
    ]
    assignments.extend(
        (definition.name, variable_value_gml(definition.value, definition))
        for definition in definitions
    )
    return variable_assignments_gml(assignments, inherited=inherited)


def variable_definition_identifiers(
    definitions: Iterable[VariableDefinition],
    overrides: Iterable[VariableOverride],
) -> set[str]:
    """Return the names an object's definitions assign or read."""
    identifiers: set[str] = set()
    for definition in definitions:
        identifiers.add(definition.name)
        identifiers.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", definition.value))
    for override in overrides:
        identifiers.add(override.name)
        identifiers.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", override.value))
    return identifiers
