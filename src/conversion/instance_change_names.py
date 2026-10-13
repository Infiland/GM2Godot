"""The project's script functions and macros that run instance_change.

instance_change inside a script function is not compiled with the rest of the
event as its continuation (see the runtime's 76_instance_change.gd): the
converted game changes the instance's object once the event that called the
function returns. So a call of such a function, or a use of a macro that
expands to one, is a site where the code after it may meet the old object, the
same as an instance_change call that stays deferred. The sites are found here
by name, for the project's whole source: a function that calls one of them is
one too.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from src.conversion.gml_transpiler_parts.lexical_api import (
    preprocess_gml_source,
    tokenize_gml_source,
)
from src.conversion.gml_transpiler_parts.shared_models import GMLTranspileError, Token
from src.conversion.project_source_paths import project_gml_source_paths
from src.conversion.script_functions import modern_script_function_declarations
from src.conversion.type_defs import StrPath

_INSTANCE_CHANGE = "instance_change"


@dataclass(frozen=True)
class InstanceChangeNames:
    """Names of the project's script functions and macros that run instance_change."""

    functions: frozenset[str] = frozenset()
    macros: frozenset[str] = frozenset()

    @property
    def all(self) -> frozenset[str]:
        return self.functions | self.macros


@dataclass(frozen=True)
class _Unit:
    """The names a script function or macro uses, outside the functions it declares."""

    name: str
    calls: frozenset[str]
    identifiers: frozenset[str]

    def runs_instance_change(self, names: InstanceChangeNames) -> bool:
        return (
            _INSTANCE_CHANGE in self.calls
            or not self.calls.isdisjoint(names.functions)
            or not self.identifiers.isdisjoint(names.macros)
        )


def collect_instance_change_names(
    gm_project_path: StrPath,
    *,
    macro_configuration: str | None = None,
    macro_values: Mapping[str, str] | None = None,
) -> InstanceChangeNames:
    """Find the script functions and macros of the project that run instance_change."""
    functions = _script_function_units(gm_project_path, macro_configuration)
    macros = [
        unit
        for name, value in (macro_values or {}).items()
        if (unit := _unit_of_source(name, value)) is not None
    ]
    names = InstanceChangeNames()
    while True:
        found = InstanceChangeNames(
            functions=frozenset(unit.name for unit in functions if unit.runs_instance_change(names)),
            macros=frozenset(unit.name for unit in macros if unit.runs_instance_change(names)),
        )
        if found == names:
            return names
        names = InstanceChangeNames(
            functions=names.functions | found.functions,
            macros=names.macros | found.macros,
        )


def _script_function_units(gm_project_path: StrPath, macro_configuration: str | None) -> list[_Unit]:
    units: list[_Unit] = []
    for source_path in project_gml_source_paths(gm_project_path):
        parts = source_path.source_path.split("/")
        if len(parts) < 2 or parts[0].casefold() != "scripts":
            continue
        try:
            with open(source_path.filesystem_path, "r", encoding="utf-8") as source_file:
                source = source_file.read()
            declarations = modern_script_function_declarations(
                source,
                macro_configuration=macro_configuration,
            )
        except (OSError, GMLTranspileError):
            continue
        if declarations is None:
            # (A script without function declarations is one function of the script's name.)
            sources = [(parts[1] if len(parts) > 2 else posixpath.splitext(parts[-1])[0], source)]
        else:
            sources = [(declaration.name, declaration.body) for declaration in declarations]
        units.extend(
            unit
            for name, text in sources
            if (unit := _unit_of_source(name, text, macro_configuration=macro_configuration)) is not None
        )
    return units


def _unit_of_source(name: str, source: str, *, macro_configuration: str | None = None) -> _Unit | None:
    try:
        tokens = tokenize_gml_source(preprocess_gml_source(source, macro_configuration=macro_configuration).source)
    except GMLTranspileError:
        return None
    calls: set[str] = set()
    identifiers: set[str] = set()
    for index in _own_token_indices(tokens):
        token = tokens[index]
        if token.kind != "IDENT" or (index > 0 and tokens[index - 1].value == "."):
            continue
        identifiers.add(token.value)
        if index + 1 < len(tokens) and tokens[index + 1].value == "(":
            calls.add(token.value)
    return _Unit(name=name, calls=frozenset(calls), identifiers=frozenset(identifiers))


def _own_token_indices(tokens: Sequence[Token]) -> Iterable[int]:
    """Yield the tokens that run with the code: not a function's body, not a preprocessor line.

    (Defining a function does not run what is in its body, nor does the
    definition of a macro run what it expands to.)
    """
    index = 0
    in_directive = False
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "DIRECTIVE":
            in_directive = True
        elif token.kind == "NEWLINE":
            in_directive = False
        if token.kind == "IDENT" and token.value == "function" and not in_directive:
            index = _function_body_end(tokens, index) + 1
            continue
        if not in_directive:
            yield index
        index += 1


def _function_body_end(tokens: Sequence[Token], index: int) -> int:
    """Return the index of the closing brace of the function that starts at index."""
    while index < len(tokens) and tokens[index].value != "{":
        index += 1
    depth = 0
    while index < len(tokens):
        if tokens[index].kind == "OP":
            if tokens[index].value == "{":
                depth += 1
            elif tokens[index].value == "}":
                depth -= 1
                if depth == 0:
                    return index
        index += 1
    return len(tokens) - 1
