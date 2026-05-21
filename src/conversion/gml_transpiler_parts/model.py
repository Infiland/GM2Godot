# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Literal, TypeAlias


_AssignmentOperator: TypeAlias = Literal[
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

_IncrementDelta: TypeAlias = Literal[-1, 1]
_IncrementMode: TypeAlias = Literal["prefix", "postfix"]


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

    def with_location(self, line: int, column: int) -> "GMLTranspileError":
        if self.line is not None and self.column is not None:
            return self
        return GMLTranspileError(self.message, line=line, column=column)

    def __str__(self) -> str:
        if self.line is None or self.column is None:
            return self.message
        return f"{self.message} at line {self.line}, column {self.column}"


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    line: int = 1
    column: int = 1
    index: int = 0


@dataclass(frozen=True)
class _BuiltinVariableMetadata:
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
class _ScopeContext:
    self_expression: str = "self"
    other_expression: str = "other"
    instance_target: str | None = None
    global_scope: bool = False
    global_names: frozenset[str] = frozenset()
    asset_names: frozenset[str] = frozenset()
    static_scope: str | None = None
    static_names: frozenset[str] = frozenset()
    static_prefix: str = "gml_static"
    extension_functions: Mapping[str, GMLExtensionFunction] = field(default_factory=_empty_extension_functions)
    extension_function_mappings: Mapping[str, GMLExtensionFunctionMapping] = field(default_factory=_empty_extension_function_mappings)


_DEFAULT_SCOPE_CONTEXT = _ScopeContext()


@dataclass(frozen=True)
class _Name:
    value: str


@dataclass(frozen=True)
class _NameOf:
    value: str


@dataclass(frozen=True)
class _Literal:
    value: str


@dataclass(frozen=True)
class _StringLiteral:
    value: str


@dataclass(frozen=True)
class _NumberLiteral:
    value: str
    is_float_like: bool


@dataclass(frozen=True)
class _Unary:
    operator: str
    operand: _Expression


@dataclass(frozen=True)
class _Binary:
    left: _Expression
    operator: str
    right: _Expression


@dataclass(frozen=True)
class _Ternary:
    condition: _Expression
    true_expr: _Expression
    false_expr: _Expression


@dataclass(frozen=True)
class _Call:
    callee: _Expression
    args: tuple[_Expression, ...]


@dataclass(frozen=True)
class _ArrayLiteral:
    elements: tuple[_Expression, ...]


@dataclass(frozen=True)
class _FunctionParameter:
    name: str
    default: _Expression | None


@dataclass(frozen=True)
class _StaticDeclaration:
    name: str
    value_source: str


@dataclass(frozen=True)
class _FunctionLiteral:
    name: str | None
    parameters: tuple[_FunctionParameter, ...]
    body_lines: tuple[str, ...]
    is_constructor: bool = False
    static_scope_id: str | None = None


@dataclass(frozen=True)
class _NewCall:
    constructor: _Expression
    args: tuple[_Expression, ...]


@dataclass(frozen=True)
class _StructLiteral:
    fields: tuple[tuple[str, _Expression], ...]


@dataclass(frozen=True)
class _Index:
    target: _Expression
    index: _Expression


@dataclass(frozen=True)
class _StructAccess:
    target: _Expression
    key: _Expression


@dataclass(frozen=True)
class _DSMapAccess:
    target: _Expression
    key: _Expression


@dataclass(frozen=True)
class _DSListAccess:
    target: _Expression
    index: _Expression


@dataclass(frozen=True)
class _DSGridAccess:
    target: _Expression
    x_index: _Expression
    y_index: _Expression


@dataclass(frozen=True)
class _ArrayRefAccess:
    target: _Expression
    index: _Expression


@dataclass(frozen=True)
class _Member:
    target: _Expression
    member: str


@dataclass(frozen=True)
class _Grouped:
    expr: _Expression


_Expression: TypeAlias = (
    _Name
    | _NameOf
    | _Literal
    | _StringLiteral
    | _NumberLiteral
    | _Unary
    | _Binary
    | _Ternary
    | _Call
    | _ArrayLiteral
    | _FunctionLiteral
    | _NewCall
    | _StructLiteral
    | _Index
    | _StructAccess
    | _DSMapAccess
    | _DSListAccess
    | _DSGridAccess
    | _ArrayRefAccess
    | _Member
    | _Grouped
)
