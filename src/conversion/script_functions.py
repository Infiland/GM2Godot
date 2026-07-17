# pyright: reportPrivateUsage=false
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from src.conversion.gml_transpiler import GMLTranspileError
from src.conversion.gml_transpiler_parts.identifiers import _validate_gml_identifier
from src.conversion.gml_transpiler_parts.lexical import (
    _is_verbatim_string_start,
    _read_verbatim_string,
)
from src.conversion.gml_transpiler_parts.preprocessor import (
    preprocess_gml_source_preserving_layout,
)
from src.conversion.gml_transpiler_parts.tokens import _read_template_string
from src.conversion.gml_transpiler_parts.utils import (
    _split_assignment,
    _split_top_level,
)


@dataclass(frozen=True)
class ScriptFunctionParameter:
    name: str
    default: str | None


@dataclass(frozen=True)
class ScriptFunctionDeclaration:
    name: str
    parameters: tuple[ScriptFunctionParameter, ...]
    body: str
    is_constructor: bool = False
    parent_constructor: str | None = None
    body_line_offset: int = 0
    body_column_offset: int = 0


@dataclass(frozen=True)
class ScriptTopLevelStatement:
    source: str
    kind: Literal["global_constructor_assignment", "constructor_call"]
    start: int
    end: int
    constructor_name: str | None = None


@dataclass(frozen=True)
class ModernScriptStructure:
    declarations: tuple[ScriptFunctionDeclaration, ...]
    top_level_statements: tuple[ScriptTopLevelStatement, ...]


def find_matching_delimiter(source: str, start: int, opener: str, closer: str) -> int | None:
    if start < 0 or start >= len(source) or source[start] != opener:
        return None
    depth = 0
    index = start
    quote: str | None = None
    while index < len(source):
        char = source[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if _is_verbatim_string_start(source, index):
            index += len(_read_verbatim_string(source, index))
            continue
        if char in ("'", '"'):
            quote = char
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def parse_script_function_parameters(params_text: str) -> tuple[ScriptFunctionParameter, ...]:
    if not params_text.strip():
        return ()
    parameters: list[ScriptFunctionParameter] = []
    for raw_param in _split_top_level(params_text, ","):
        raw_param = raw_param.strip()
        if not raw_param:
            continue
        assignment = _split_assignment(raw_param)
        if assignment is None:
            name = raw_param
            default = None
        else:
            name, operator, default = assignment
            if operator != "=":
                raise GMLTranspileError("Script function parameters only support simple defaults")
        name = name.strip()
        _validate_gml_identifier(name)
        parameters.append(
            ScriptFunctionParameter(
                name=name,
                default=default.strip() if default is not None else None,
            )
        )
    return tuple(parameters)


def _skip_top_level_preprocessor_declaration(source: str, start: int) -> int | None:
    match = re.match(r"#(macro|define)(?:[ \t]+|$)", source[start:])
    if match is None:
        return None

    if match.group(1) == "define":
        line_end = source.find("\n", start)
        return len(source) if line_end == -1 else line_end + 1

    line_start = start
    while True:
        line_end = source.find("\n", line_start)
        if line_end == -1:
            return len(source)
        logical_line = source[line_start:line_end].rstrip()
        line_start = line_end + 1
        if not logical_line.endswith("\\"):
            return line_start


def _read_top_level_global_constructor_assignment(
    source: str,
    start: int,
) -> tuple[int, str] | None:
    match = re.match(
        r"global\s*\.\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*"
        r"function(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*\(",
        source[start:],
    )
    if match is None:
        return None

    params_start = start + match.end() - 1
    params_end = find_matching_delimiter(source, params_start, "(", ")")
    if params_end is None:
        return None
    body_start = _find_function_body_start(source, params_end + 1)
    if body_start is None or not _is_constructor_qualifier(
        source[params_end + 1:body_start]
    ):
        return None
    body_end = find_matching_delimiter(source, body_start, "{", "}")
    if body_end is None:
        return None

    end = body_end + 1
    while end < len(source) and source[end] in " \t\r":
        end += 1
    if end < len(source) and source[end] == ";":
        end += 1
    return end, source[start:end]


def _find_function_body_start(source: str, start: int) -> int | None:
    paren_depth = 0
    bracket_depth = 0
    index = start
    quote: str | None = None
    while index < len(source):
        char = source[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if _is_verbatim_string_start(source, index):
            index += len(_read_verbatim_string(source, index))
            continue
        if char in ("'", '"'):
            quote = char
        elif char == "(":
            paren_depth += 1
        elif char == ")" and paren_depth > 0:
            paren_depth -= 1
        elif char == "[":
            bracket_depth += 1
        elif char == "]" and bracket_depth > 0:
            bracket_depth -= 1
        elif char == "{" and paren_depth == 0 and bracket_depth == 0:
            return index
        index += 1
    return None


def _is_constructor_qualifier(source: str) -> bool:
    qualifier = source.strip()
    if qualifier == "constructor":
        return True
    return re.fullmatch(r":\s*.+?\s+constructor", qualifier, flags=re.DOTALL) is not None


def _parse_function_qualifier(source: str) -> tuple[bool, str | None] | None:
    qualifier = source.strip()
    if not qualifier:
        return False, None
    if qualifier == "constructor":
        return True, None
    inherited = re.fullmatch(
        r":\s*(.+?)\s+constructor",
        qualifier,
        flags=re.DOTALL,
    )
    if inherited is None:
        return None
    parent_constructor = inherited.group(1).strip()
    if not parent_constructor:
        return None
    return True, parent_constructor


def _mask_comments_preserving_layout(source: str) -> str:
    masked = list(source)
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(source):
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if _is_verbatim_string_start(source, index):
            index += len(_read_verbatim_string(source, index))
            continue
        if source.startswith('$"', index):
            index += len(_read_template_string(source, index))
            continue
        if char in ("'", '"'):
            quote = char
            index += 1
            continue
        if source.startswith("//", index):
            while index < len(source) and source[index] not in "\r\n":
                masked[index] = " "
                index += 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = len(source) if end == -1 else end + 2
            while index < end:
                if source[index] not in "\r\n":
                    masked[index] = " "
                index += 1
            continue
        index += 1
    return "".join(masked)


def render_script_top_level_source(
    source: str,
    statements: tuple[ScriptTopLevelStatement, ...],
) -> str:
    rendered = [char if char in "\r\n" else " " for char in source]
    for statement in statements:
        rendered[statement.start:statement.end] = source[statement.start:statement.end]
    return "".join(rendered)


def modern_script_structure(
    source: str,
    *,
    macro_configuration: str | None = None,
) -> ModernScriptStructure | None:
    preprocessed = preprocess_gml_source_preserving_layout(
        source,
        macro_configuration=macro_configuration,
    )
    candidate = _mask_comments_preserving_layout(preprocessed.source)
    if not candidate.strip():
        return None

    declarations: list[ScriptFunctionDeclaration] = []
    top_level_statements: list[ScriptTopLevelStatement] = []
    index = 0
    while index < len(candidate):
        while index < len(candidate) and (candidate[index].isspace() or candidate[index] == ";"):
            index += 1
        if index >= len(candidate):
            break

        enum_match = re.match(
            r"enum\s+[A-Za-z_][A-Za-z0-9_]*\s*\{",
            candidate[index:],
        )
        if enum_match is not None:
            body_start = index + enum_match.end() - 1
            body_end = find_matching_delimiter(candidate, body_start, "{", "}")
            if body_end is None:
                return None
            index = body_end + 1
            continue

        preprocessor_declaration_end = _skip_top_level_preprocessor_declaration(
            candidate,
            index,
        )
        if preprocessor_declaration_end is not None:
            index = preprocessor_declaration_end
            continue

        global_constructor = _read_top_level_global_constructor_assignment(candidate, index)
        if global_constructor is not None:
            statement_start = index
            index, _initializer = global_constructor
            top_level_statements.append(
                ScriptTopLevelStatement(
                    source=source[statement_start:index],
                    kind="global_constructor_assignment",
                    start=statement_start,
                    end=index,
                )
            )
            continue

        initializer_match = re.match(
            r"new\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)\s*;",
            candidate[index:],
        )
        if initializer_match is not None:
            constructor_name = initializer_match.group(1)
            if not any(
                declaration.name == constructor_name and declaration.is_constructor
                for declaration in declarations
            ):
                return None
            statement_end = index + initializer_match.end()
            top_level_statements.append(
                ScriptTopLevelStatement(
                    source=source[index:statement_end],
                    kind="constructor_call",
                    constructor_name=constructor_name,
                    start=index,
                    end=statement_end,
                )
            )
            index = statement_end
            continue

        match = re.match(r"function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", candidate[index:])
        if match is None:
            return None
        name = match.group(1)
        declaration_start = index + match.start()
        params_start = candidate.find("(", declaration_start)
        params_end = find_matching_delimiter(candidate, params_start, "(", ")")
        if params_end is None:
            return None
        body_start = _find_function_body_start(candidate, params_end + 1)
        if body_start is None:
            return None
        qualifier = candidate[params_end + 1:body_start].strip()
        parsed_qualifier = _parse_function_qualifier(qualifier)
        if parsed_qualifier is None:
            return None
        is_constructor, parent_constructor = parsed_qualifier
        body_end = find_matching_delimiter(candidate, body_start, "{", "}")
        if body_end is None:
            return None
        try:
            parameters = parse_script_function_parameters(candidate[params_start + 1:params_end])
        except GMLTranspileError:
            return None
        declarations.append(
            ScriptFunctionDeclaration(
                name=name,
                parameters=parameters,
                body=candidate[body_start + 1:body_end],
                is_constructor=is_constructor,
                parent_constructor=parent_constructor,
                body_line_offset=source.count("\n", 0, body_start + 1),
                body_column_offset=(
                    body_start + 1
                    if (last_newline := source.rfind("\n", 0, body_start + 1)) == -1
                    else body_start - last_newline
                ),
            )
        )
        index = body_end + 1

    if not declarations and not top_level_statements:
        return None
    return ModernScriptStructure(
        declarations=tuple(declarations),
        top_level_statements=tuple(top_level_statements),
    )


def modern_script_function_declarations(
    source: str,
    *,
    macro_configuration: str | None = None,
) -> tuple[ScriptFunctionDeclaration, ...] | None:
    structure = modern_script_structure(
        source,
        macro_configuration=macro_configuration,
    )
    if structure is None:
        return None
    return structure.declarations


def modern_script_function_names(
    source: str,
    *,
    macro_configuration: str | None = None,
) -> tuple[str, ...]:
    declarations = modern_script_function_declarations(
        source,
        macro_configuration=macro_configuration,
    )
    if declarations is None:
        return ()
    return tuple(declaration.name for declaration in declarations)


__all__ = [
    "ScriptFunctionDeclaration",
    "ScriptFunctionParameter",
    "ScriptTopLevelStatement",
    "ModernScriptStructure",
    "find_matching_delimiter",
    "modern_script_function_declarations",
    "modern_script_function_names",
    "modern_script_structure",
    "parse_script_function_parameters",
    "render_script_top_level_source",
]
