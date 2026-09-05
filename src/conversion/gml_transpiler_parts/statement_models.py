from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable, Mapping, MutableMapping, MutableSet

from .shared_models import GMLExtensionFunction, GMLExtensionFunctionMapping, ScopeContext, Token


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


@dataclass(frozen=True)
class GMLStatementResult:
    lines: tuple[str, ...]
    local_names: frozenset[str]
    instance_variables: MutableSet[str] | None
    scope_context: ScopeContext
    enum_values: MutableMapping[str, dict[str, int]]
    enum_names: frozenset[str]
    macro_values: MutableMapping[str, str]


@dataclass(frozen=True)
class StatementLoweringContext:
    local_names: MutableSet[str] | None = None
    declared_local_names: MutableSet[str] | None = None
    instance_variables: MutableSet[str] | None = None
    loop_depth: int = 0
    continue_depth: int = 0
    return_depth: int = 0
    finally_depth: int = 0
    enum_values: MutableMapping[str, dict[str, int]] | None = None
    enum_names: Iterable[str] | None = None
    scope_context: ScopeContext | None = None
    inherited_event_call: str | None = None
    macro_values: Mapping[str, str] | None = None
    generated_counter: list[int] | None = None
    control_flow_capture: ControlFlowCapture | None = None


__all__: Final[tuple[str, ...]] = (
    "ControlFlowCapture",
    "GMLStatementRequest",
    "GMLStatementResult",
    "StatementLoweringContext",
)
