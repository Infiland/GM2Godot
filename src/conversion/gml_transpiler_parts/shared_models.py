from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, TypeAlias


AssignmentOperator: TypeAlias = Literal[
    "??=",
    "<<=",
    ">>=",
    ":=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "=",
]

IncrementDelta: TypeAlias = Literal[-1, 1]
IncrementMode: TypeAlias = Literal["prefix", "postfix"]


class GMLTranspileError(ValueError):
    """Raised when the small GML subset transpiler cannot parse input."""

    def __init__(
        self,
        message: str,
        *,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column

    def with_location(self, line: int, column: int) -> GMLTranspileError:
        if self.line is not None and self.column is not None:
            return self
        return GMLTranspileError(self.message, line=line, column=column)

    def __str__(self) -> str:
        if self.line is None or self.column is None:
            return self.message
        return f"{self.message} at line {self.line}, column {self.column}"


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int = 1
    column: int = 1
    index: int = 0


@dataclass(frozen=True)
class BuiltinVariableMetadata:
    scope: str
    default: str
    mutable: bool
    is_array: bool
    subsystem: str


@dataclass(frozen=True)
class GMLExtensionFunction:
    name: str
    extension_name: str = ""
    min_args: int | None = None
    max_args: int | None = None


@dataclass(frozen=True)
class GMLExtensionFunctionMapping:
    function_name: str
    target: str
    min_args: int | None = None
    max_args: int | None = None


def _empty_extension_functions() -> Mapping[str, GMLExtensionFunction]:
    return {}


def _empty_extension_function_mappings() -> Mapping[str, GMLExtensionFunctionMapping]:
    return {}


@dataclass(frozen=True)
class ScopeContext:
    self_expression: str = "self"
    other_expression: str = "other"
    instance_target: str | None = None
    global_scope: bool = False
    global_names: frozenset[str] = frozenset()
    asset_names: frozenset[str] = frozenset()
    direct_instance_names: frozenset[str] = frozenset()
    dynamic_instance_names: frozenset[str] = frozenset()
    static_scope: str | None = None
    static_names: frozenset[str] = frozenset()
    static_prefix: str = "gml_static"
    extension_functions: Mapping[str, GMLExtensionFunction] = field(
        default_factory=_empty_extension_functions
    )
    extension_function_mappings: Mapping[str, GMLExtensionFunctionMapping] = field(
        default_factory=_empty_extension_function_mappings
    )


DEFAULT_SCOPE_CONTEXT = ScopeContext()


@dataclass(frozen=True)
class StaticDeclaration:
    name: str
    value_source: str


__all__ = [
    "AssignmentOperator",
    "BuiltinVariableMetadata",
    "DEFAULT_SCOPE_CONTEXT",
    "GMLExtensionFunction",
    "GMLExtensionFunctionMapping",
    "GMLTranspileError",
    "IncrementDelta",
    "IncrementMode",
    "ScopeContext",
    "StaticDeclaration",
    "Token",
]
