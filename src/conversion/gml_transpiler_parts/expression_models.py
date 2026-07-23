from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class Name:
    value: str


@dataclass(frozen=True)
class NameOf:
    value: str


@dataclass(frozen=True)
class Literal:
    value: str


@dataclass(frozen=True)
class StringLiteral:
    value: str


@dataclass(frozen=True)
class TemplateStringLiteral:
    parts: tuple[str | Expression, ...]


@dataclass(frozen=True)
class NumberLiteral:
    value: str
    is_float_like: bool


@dataclass(frozen=True)
class EnumMember:
    enum_name: str
    member: str
    value: int


@dataclass(frozen=True)
class Unary:
    operator: str
    operand: Expression


@dataclass(frozen=True)
class Binary:
    left: Expression
    operator: str
    right: Expression


@dataclass(frozen=True)
class Ternary:
    condition: Expression
    true_expr: Expression
    false_expr: Expression


@dataclass(frozen=True)
class Call:
    callee: Expression
    args: tuple[Expression, ...]


@dataclass(frozen=True)
class ArrayLiteral:
    elements: tuple[Expression, ...]


@dataclass(frozen=True)
class FunctionParameter:
    name: str
    default: Expression | None


@dataclass(frozen=True)
class FunctionLiteral:
    name: str | None
    parameters: tuple[FunctionParameter, ...]
    body_lines: tuple[str, ...]
    is_constructor: bool = False
    static_scope_id: str | None = None


@dataclass(frozen=True)
class NewCall:
    constructor: Expression
    args: tuple[Expression, ...]


@dataclass(frozen=True)
class StructLiteral:
    fields: tuple[tuple[str, Expression], ...]


@dataclass(frozen=True)
class Index:
    target: Expression
    index: Expression


@dataclass(frozen=True)
class StructAccess:
    target: Expression
    key: Expression


@dataclass(frozen=True)
class DSMapAccess:
    target: Expression
    key: Expression


@dataclass(frozen=True)
class DSListAccess:
    target: Expression
    index: Expression


@dataclass(frozen=True)
class DSGridAccess:
    target: Expression
    x_index: Expression
    y_index: Expression


@dataclass(frozen=True)
class ArrayRefAccess:
    target: Expression
    index: Expression


@dataclass(frozen=True)
class Member:
    target: Expression
    member: str


@dataclass(frozen=True)
class Grouped:
    expr: Expression


Expression: TypeAlias = (
    Name
    | NameOf
    | Literal
    | StringLiteral
    | TemplateStringLiteral
    | NumberLiteral
    | EnumMember
    | Unary
    | Binary
    | Ternary
    | Call
    | ArrayLiteral
    | FunctionLiteral
    | NewCall
    | StructLiteral
    | Index
    | StructAccess
    | DSMapAccess
    | DSListAccess
    | DSGridAccess
    | ArrayRefAccess
    | Member
    | Grouped
)


__all__ = [
    "ArrayLiteral",
    "ArrayRefAccess",
    "Binary",
    "Call",
    "DSGridAccess",
    "DSListAccess",
    "DSMapAccess",
    "EnumMember",
    "Expression",
    "FunctionLiteral",
    "FunctionParameter",
    "Grouped",
    "Index",
    "Literal",
    "Member",
    "Name",
    "NameOf",
    "NewCall",
    "NumberLiteral",
    "StringLiteral",
    "StructAccess",
    "StructLiteral",
    "TemplateStringLiteral",
    "Ternary",
    "Unary",
]
