from dataclasses import dataclass


class GMLTranspileError(ValueError):
    """Raised when the small GML subset transpiler cannot parse input."""


@dataclass(frozen=True)
class Token:
    kind: str
    value: str


@dataclass(frozen=True)
class Name:
    value: str


@dataclass(frozen=True)
class Literal:
    value: str


@dataclass(frozen=True)
class Unary:
    operator: str
    operand: object


@dataclass(frozen=True)
class Binary:
    left: object
    operator: str
    right: object


@dataclass(frozen=True)
class Ternary:
    condition: object
    true_expr: object
    false_expr: object


@dataclass(frozen=True)
class Call:
    callee: object
    args: tuple


@dataclass(frozen=True)
class Index:
    target: object
    index: object


@dataclass(frozen=True)
class Member:
    target: object
    member: str


@dataclass(frozen=True)
class Grouped:
    expr: object


EOF = Token("EOF", "")
