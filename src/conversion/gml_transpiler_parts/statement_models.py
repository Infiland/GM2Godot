from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping, MutableMapping, MutableSet

from .shared_models import (
    EventFunctionSplit,
    GMLExtensionFunction,
    GMLExtensionFunctionMapping,
    ScopeContext,
    Token,
)


@dataclass(frozen=True)
class ControlFlowCapture:
    variable_name: str
    loop_depth: int
    continue_depth: int
    capture_return: bool = False
    capture_exit: bool = False
    capture_throw: bool = False
    capture_break: bool = False
    capture_continue: bool = False


@dataclass(frozen=True)
class GMLStatementRequest:
    tokens: tuple[Token, ...]
    local_names: frozenset[str] = frozenset()
    instance_variables: MutableSet[str] | None = None
    return_depth: int = 0
    enum_values: MutableMapping[str, dict[str, int]] | None = None
    enum_names: frozenset[str] = frozenset()
    scope_context: ScopeContext | None = None
    inherited_event_call: str | None = None
    macro_values: MutableMapping[str, str] | None = None
    macro_priorities: MutableMapping[str, int] | None = None
    macro_configuration: str | None = None
    top_level_global_scope: bool = False
    global_names: frozenset[str] = frozenset()
    asset_names: frozenset[str] = frozenset()
    static_scope_prefix: str | None = None
    extension_functions: Mapping[str, GMLExtensionFunction] | None = None
    extension_function_mappings: Mapping[str, GMLExtensionFunctionMapping] | None = None
    event_functions: EventFunctionSplit | None = None
    # Compile an instance_change statement of an object event with the rest of
    # the event as its continuation.
    instance_change_continuations: bool = False
    # An ancestor's event of the same name runs the rest of that event after an
    # instance_change, which replaces the instance's script. event_inherited()
    # then ends the event's own code: the rest of the event is compiled as a
    # function that runs after the parent's event.
    inherited_event_continuation: bool = False
    # Project script functions and macros that run instance_change: calls of
    # them are sites of the source along with instance_change itself.
    instance_change_names: frozenset[str] = frozenset()


@dataclass(frozen=True)
class GMLStatementResult:
    lines: tuple[str, ...]
    local_names: frozenset[str]
    instance_variables: MutableSet[str] | None
    scope_context: ScopeContext
    enum_values: MutableMapping[str, dict[str, int]]
    enum_names: frozenset[str]
    macro_values: MutableMapping[str, str]
    # For each instance_change call compiled with a continuation, how many
    # instance_change names precede it in the code.
    continued_instance_changes: tuple[int, ...] = ()


__all__: Final[tuple[str, ...]] = (
    "ControlFlowCapture",
    "GMLStatementRequest",
    "GMLStatementResult",
)
