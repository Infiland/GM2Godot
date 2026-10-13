from __future__ import annotations

from typing import Final, Sequence

from .lexical_api import preprocess_gml_source, tokenize_gml_source
from .shared_models import EventFunctionSplit, Token
from .statement_boundaries import scan_statement_end, skip_newline_tokens

# A named function declaration (function name(...) {...}) in event, method,
# constructor or script-function code is a method variable of the instance or
# struct running that code, bound to it, as if it were written name =
# function(...) {...} (manual: GML Overview > Script Functions And Variables,
# Method Variables: "Defining a function in an Object's event using either
# syntax will make the function only available in the context of its
# instance"). GameMaker has the function available throughout the body, even
# before its line runs, so the declarations at the top of a body are moved to
# its start.
_EXPRESSION_KEYWORDS = frozenset({
    "and",
    "case",
    "delete",
    "div",
    "do",
    "else",
    "in",
    "mod",
    "new",
    "not",
    "or",
    "return",
    "then",
    "throw",
    "xor",
})
_OPENING_BRACKETS = frozenset({"(", "[", "{"})
_CLOSING_BRACKETS = frozenset({")", "]", "}"})


def named_function_declaration_name(tokens: Sequence[Token], index: int) -> str | None:
    if index >= len(tokens) or tokens[index].kind != "IDENT" or tokens[index].value != "function":
        return None
    name_index = skip_newline_tokens(tokens, index + 1)
    if (
        name_index >= len(tokens)
        or tokens[name_index].kind != "IDENT"
        or tokens[name_index].value == "constructor"
    ):
        return None
    parameters_index = skip_newline_tokens(tokens, name_index + 1)
    if parameters_index >= len(tokens) or tokens[parameters_index].value != "(":
        return None
    return tokens[name_index].value


def function_declaration_as_assignment(name: str, statement_tokens: list[Token]) -> list[Token]:
    first = statement_tokens[0]
    return [
        Token("IDENT", name, line=first.line, column=first.column, index=first.index),
        Token("OP", "=", line=first.line, column=first.column, index=first.index),
        *statement_tokens,
    ]


def _starts_statement(tokens: Sequence[Token], index: int) -> bool:
    previous = index - 1
    crossed_line_break = False
    while previous >= 0 and tokens[previous].kind == "NEWLINE":
        previous -= 1
        crossed_line_break = True
    if previous < 0:
        return True
    token = tokens[previous]
    if token.value in (";", "}"):
        return True
    if not crossed_line_break:
        return False
    # Line breaks are white space, but a function declaration cannot continue
    # an expression: after anything that can end one, it starts a statement.
    if token.kind == "IDENT":
        return token.value not in _EXPRESSION_KEYWORDS
    return token.kind in ("NUMBER", "STRING", "VERBATIM_STRING", "TEMPLATE_STRING") or token.value in (")", "]")


def function_declaration_spans(tokens: Sequence[Token]) -> list[tuple[int, int]]:
    """Return the token ranges of the named function declarations that start statements."""
    spans: list[tuple[int, int]] = []
    depth = 0
    in_directive = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "EOF":
            break
        if token.kind == "DIRECTIVE":
            in_directive = True
        elif token.kind == "NEWLINE":
            in_directive = False
        elif token.kind == "OP" and token.value in _OPENING_BRACKETS:
            depth += 1
        elif token.kind == "OP" and token.value in _CLOSING_BRACKETS:
            depth = max(0, depth - 1)
        elif (
            depth == 0
            and not in_directive
            and named_function_declaration_name(tokens, index) is not None
            and _starts_statement(tokens, index)
        ):
            end = scan_statement_end(tokens, index)
            if end is not None and end > index:
                spans.append((index, end))
                index = end
                continue
        index += 1
    return spans


def hoist_function_declarations(tokens: list[Token]) -> list[Token]:
    spans = function_declaration_spans(tokens)
    if not spans:
        return tokens
    hoisted: list[Token] = []
    remaining: list[Token] = []
    cursor = 0
    for start, end in spans:
        remaining.extend(tokens[cursor:start])
        hoisted.extend(tokens[start:end])
        hoisted.append(Token("OP", ";", line=tokens[end - 1].line, column=tokens[end - 1].column, index=tokens[end - 1].index))
        cursor = end
    remaining.extend(tokens[cursor:])
    return [*hoisted, *remaining]


# The named functions declared at the top of an object's event code
# (manual: GML Overview > Method Variables: "A function defined in an Object's
# event using the script function syntax will be available to its instances
# throughout their lifetime, even when the event has not run yet. For example,
# defining a script function in the Alarm 0 event will make the function
# available to call in the Create event, regardless of when that alarm event
# runs (or whether it runs at all)"). The converter binds them when the
# instance is built, from code of their own, and keeps them out of the event
# that holds them.
def declared_function_names(tokens: Sequence[Token]) -> tuple[str, ...]:
    names: dict[str, None] = {}
    for start, _end in function_declaration_spans(tokens):
        name = named_function_declaration_name(tokens, start)
        if name is not None:
            names[name] = None
    return tuple(names)


def event_function_names(source: str, *, macro_configuration: str | None = None) -> tuple[str, ...]:
    """Return the names of the functions declared at the top of an event's code."""
    if "function" not in source:
        return ()
    return declared_function_names(
        tokenize_gml_source(
            preprocess_gml_source(source, macro_configuration=macro_configuration).source
        )
    )


def split_event_functions(tokens: Sequence[Token], split: EventFunctionSplit) -> list[Token]:
    """Return the event's body, or its function declarations, with calls bound to them.

    GameMaker compiles a call to a script function by name straight to that
    function, without looking at the variable of the same name (manual: GML
    Overview > Script Functions vs. Methods, "Overridden Script Functions"): in
    the code that declares it, say_hello() runs the function declared there
    even when a child object assigns another to the variable. Such calls go to
    the member that holds the declared function, unless the name is also a
    parameter or a local variable.
    """
    spans = function_declaration_spans(tokens)
    declared: dict[str, str] = {}
    for start, _end in spans:
        name = named_function_declaration_name(tokens, start)
        if name is not None and name in split.members:
            declared[name] = split.members[name]
    bound = _bind_direct_calls(tokens, declared)
    if split.part == "body":
        return _without_spans(bound, spans)
    return _only_spans(bound, spans, declared)


def _without_spans(tokens: Sequence[Token], spans: Sequence[tuple[int, int]]) -> list[Token]:
    result: list[Token] = []
    cursor = 0
    for start, end in spans:
        result.extend(tokens[cursor:start])
        cursor = end
    result.extend(tokens[cursor:])
    return result


def _only_spans(
    tokens: Sequence[Token],
    spans: Sequence[tuple[int, int]],
    members: dict[str, str],
) -> list[Token]:
    result: list[Token] = []
    for start, end in spans:
        result.extend(tokens[start:end])
        last = tokens[end - 1]
        name = named_function_declaration_name(tokens, start)
        position = {"line": last.line, "column": last.column, "index": last.index}
        result.append(Token("OP", ";", **position))
        member = members.get(name) if name is not None else None
        if member is not None and name is not None:
            result.extend(
                (
                    Token("IDENT", member, **position),
                    Token("OP", "=", **position),
                    Token("IDENT", name, **position),
                    Token("OP", ";", **position),
                )
            )
    if tokens and tokens[-1].kind == "EOF":
        result.append(tokens[-1])
    return result


def _bind_direct_calls(tokens: Sequence[Token], members: dict[str, str]) -> list[Token]:
    shadowed = _shadowing_names(tokens)
    bound = {name: member for name, member in members.items() if name not in shadowed}
    result = list(tokens)
    if not bound:
        return result
    for index, token in enumerate(tokens):
        member = bound.get(token.value) if token.kind == "IDENT" else None
        if member is not None and _is_direct_call(tokens, index):
            result[index] = Token("IDENT", member, line=token.line, column=token.column, index=token.index)
    return result


def _is_direct_call(tokens: Sequence[Token], index: int) -> bool:
    following = skip_newline_tokens(tokens, index + 1)
    if following >= len(tokens) or tokens[following].kind != "OP" or tokens[following].value != "(":
        return False
    previous = index - 1
    while previous >= 0 and tokens[previous].kind == "NEWLINE":
        previous -= 1
    if previous < 0:
        return True
    # A member (a.say_hello()), the declaration itself, or a constructor call.
    return tokens[previous].value not in (".", "function", "new")


def _shadowing_names(tokens: Sequence[Token]) -> set[str]:
    """Names some code in the tokens declares as a local variable, parameter or catch variable."""
    names: set[str] = set()
    for index, token in enumerate(tokens):
        if token.kind != "IDENT":
            continue
        if token.value in ("var", "static"):
            names.update(_declared_variable_names(tokens, index + 1))
        elif token.value == "function":
            names.update(_parameter_names(tokens, index + 1))
        elif token.value == "catch":
            names.update(_parameter_names(tokens, index + 1))
    return names


def _declared_variable_names(tokens: Sequence[Token], start: int) -> list[str]:
    names: list[str] = []
    depth = 0
    expect_name = True
    index = start
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "EOF":
            break
        if token.kind == "OP" and token.value in _OPENING_BRACKETS:
            depth += 1
        elif token.kind == "OP" and token.value in _CLOSING_BRACKETS:
            depth -= 1
            if depth < 0:
                break
        elif depth == 0 and token.kind == "OP" and token.value == ";":
            break
        elif depth == 0 and token.kind == "NEWLINE" and not _continues_variable_list(tokens, index):
            break
        elif depth == 0 and token.kind == "OP" and token.value == ",":
            expect_name = True
        elif depth == 0 and expect_name and token.kind == "IDENT":
            names.append(token.value)
            expect_name = False
        index += 1
    return names


def _continues_variable_list(tokens: Sequence[Token], newline_index: int) -> bool:
    previous = newline_index - 1
    while previous >= 0 and tokens[previous].kind == "NEWLINE":
        previous -= 1
    following = skip_newline_tokens(tokens, newline_index)
    return (previous >= 0 and tokens[previous].value == ",") or (
        following < len(tokens) and tokens[following].value == ","
    )


def _parameter_names(tokens: Sequence[Token], start: int) -> list[str]:
    """Names in the parameter list that follows a function (or catch) keyword, name included."""
    index = skip_newline_tokens(tokens, start)
    if index < len(tokens) and tokens[index].kind == "IDENT" and tokens[index].value != "constructor":
        index = skip_newline_tokens(tokens, index + 1)
    if index >= len(tokens) or tokens[index].value != "(":
        return []
    names: list[str] = []
    depth = 0
    expect_name = True
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "EOF":
            break
        if token.kind == "OP" and token.value in _OPENING_BRACKETS:
            depth += 1
        elif token.kind == "OP" and token.value in _CLOSING_BRACKETS:
            depth -= 1
            if depth == 0:
                break
        elif depth == 1 and token.kind == "OP" and token.value == ",":
            expect_name = True
        elif depth == 1 and expect_name and token.kind == "IDENT":
            names.append(token.value)
            expect_name = False
        index += 1
    return names


__all__: Final[tuple[str, ...]] = (
    "declared_function_names",
    "event_function_names",
    "function_declaration_as_assignment",
    "function_declaration_spans",
    "hoist_function_declarations",
    "named_function_declaration_name",
    "split_event_functions",
)
