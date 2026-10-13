from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from src.conversion.gml_transpiler import GMLTranspileError
from src.conversion.gml_transpiler_parts.lexical_api import (
    is_verbatim_string_start,
    preprocess_gml_source_preserving_layout,
    read_template_string,
    read_verbatim_string,
    validate_gml_identifier,
)
from src.conversion.gml_transpiler_parts.utils import (
    split_assignment,
    split_top_level,
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
    kind: Literal["global_constructor_assignment", "constructor_call", "statements"]
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
        if is_verbatim_string_start(source, index):
            index += len(read_verbatim_string(source, index))
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
    for raw_param in split_top_level(params_text, ","):
        raw_param = raw_param.strip()
        if not raw_param:
            continue
        assignment = split_assignment(raw_param)
        if assignment is None:
            name = raw_param
            default = None
        else:
            name, operator, default = assignment
            if operator != "=":
                raise GMLTranspileError("Script function parameters only support simple defaults")
        name = name.strip()
        validate_gml_identifier(name)
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
        if is_verbatim_string_start(source, index):
            index += len(read_verbatim_string(source, index))
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
        if is_verbatim_string_start(source, index):
            index += len(read_verbatim_string(source, index))
            continue
        if source.startswith('$"', index):
            index += len(read_template_string(source, index))
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
        rendered[statement.start:statement.end] = statement.source
    return "".join(rendered)


_ENUM_DECLARATION_RE = re.compile(r"enum\s+[A-Za-z_][A-Za-z0-9_]*\s*\{")
_FUNCTION_DECLARATION_RE = re.compile(r"function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_IDENTIFIER_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
)
# Words after which a value is expected, so that a function that follows them
# is a function expression, not a declaration.
_WORDS_BEFORE_A_VALUE = frozenset({
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


def _read_function_declaration(
    candidate: str,
    source: str,
    index: int,
) -> tuple[ScriptFunctionDeclaration, int] | None:
    """The function declared at ``index`` and where its body ends."""
    match = _FUNCTION_DECLARATION_RE.match(candidate, index)
    if match is None:
        return None
    params_start = match.end() - 1
    params_end = find_matching_delimiter(candidate, params_start, "(", ")")
    if params_end is None:
        return None
    body_start = _find_function_body_start(candidate, params_end + 1)
    if body_start is None:
        return None
    parsed_qualifier = _parse_function_qualifier(candidate[params_end + 1:body_start])
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
    declaration = ScriptFunctionDeclaration(
        name=match.group(1),
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
    return declaration, body_end + 1


def _skip_string_literal(text: str, index: int) -> int | None:
    """The end of the string literal that starts at ``index``, if one does."""
    if is_verbatim_string_start(text, index):
        return index + len(read_verbatim_string(text, index))
    if text.startswith('$"', index):
        return index + len(read_template_string(text, index))
    quote = text[index]
    if quote not in ("'", '"'):
        return None
    cursor = index + 1
    while cursor < len(text):
        if text[cursor] == "\\":
            cursor += 2
            continue
        if text[cursor] == quote:
            return cursor + 1
        cursor += 1
    return len(text)


def _blank_layout_span(characters: list[str], start: int, end: int) -> None:
    for position in range(start, end):
        if characters[position] not in "\r\n":
            characters[position] = " "


class _TopLevelScan:
    """Walks the code of a script, taking out its functions, enums and macros."""

    def __init__(self, source: str, candidate: str) -> None:
        self.source = source
        self.candidate = candidate
        self.initialization = list(candidate)
        self.declarations: list[ScriptFunctionDeclaration] = []
        self.depth = 0
        self.index = 0
        # What the code before the index ended in, to tell whether a function
        # that follows is a declaration or an expression.
        self.previous = ""
        self.previous_word = ""
        self.after_line_break = False

    def run(self) -> bool:
        """Scan the whole script; False when an enum is not closed."""
        while self.index < len(self.candidate):
            if not self._step():
                return False
        return True

    def _advance(self, end: int, previous: str, previous_word: str) -> None:
        self.index = end
        self.previous = previous
        self.previous_word = previous_word
        self.after_line_break = False

    def _step(self) -> bool:
        character = self.candidate[self.index]
        if character.isspace():
            self.after_line_break = self.after_line_break or character == "\n"
            self.index += 1
            return True
        string_end = _skip_string_literal(self.candidate, self.index)
        if string_end is not None:
            self._advance(string_end, '"', "")
            return True
        if character == "#" and self._skip_preprocessor():
            return True
        if character in _IDENTIFIER_CHARACTERS:
            return self._read_word()
        if character in "([{":
            self.depth += 1
        elif character in ")]}":
            self.depth = max(0, self.depth - 1)
        self._advance(self.index + 1, character, "")
        return True

    def _skip_preprocessor(self) -> bool:
        end = _skip_top_level_preprocessor_declaration(self.candidate, self.index)
        if end is None:
            return False
        _blank_layout_span(self.initialization, self.index, end)
        self.index = end
        return True

    def _read_word(self) -> bool:
        word_end = self.index
        while word_end < len(self.candidate) and self.candidate[word_end] in _IDENTIFIER_CHARACTERS:
            word_end += 1
        word = self.candidate[self.index:word_end]
        if self.depth == 0 and _starts_statement(
            self.previous,
            self.previous_word,
            self.after_line_break,
        ):
            if word == "function" and self._take_function():
                return True
            if word == "enum":
                taken = self._take_enum()
                if taken is None:
                    return False
                if taken:
                    return True
        self._advance(word_end, word[-1], word)
        return True

    def _take_span(self, end: int) -> None:
        _blank_layout_span(self.initialization, self.index, end)
        self._advance(end, "}", "")

    def _take_function(self) -> bool:
        read = _read_function_declaration(self.candidate, self.source, self.index)
        if read is None:
            return False
        declaration, end = read
        self.declarations.append(declaration)
        self._take_span(end)
        return True

    def _take_enum(self) -> bool | None:
        enum_match = _ENUM_DECLARATION_RE.match(self.candidate, self.index)
        if enum_match is None:
            return False
        body_end = find_matching_delimiter(self.candidate, enum_match.end() - 1, "{", "}")
        if body_end is None:
            return None
        self._take_span(body_end + 1)
        return True


def _initialization_statements(initialization: str) -> tuple[ScriptTopLevelStatement, ...]:
    """The code left outside the functions, as one statement run in place."""
    if not initialization.strip().strip(";"):
        return ()
    start = len(initialization) - len(initialization.lstrip())
    end = len(initialization.rstrip())
    return (
        ScriptTopLevelStatement(
            source=initialization[start:end],
            kind="statements",
            start=start,
            end=end,
        ),
    )


def _declarations_and_global_initialization(
    source: str,
    candidate: str,
) -> ModernScriptStructure | None:
    """A script with functions and any other code outside them.

    GameMaker 2.3+ compiles every function declared at the top level of a
    script asset as a global script function, and the rest of the script is
    global initialization: it runs once, before the first room starts, and
    its variables are global (manual: GML Overview > Script Functions And
    Variables, "Script Scope"). The code outside the functions is kept in
    place, with the functions, enums and macros blanked out, as the
    initialization to transpile.
    """
    scan = _TopLevelScan(source, candidate)
    if not scan.run() or not scan.declarations:
        return None
    return ModernScriptStructure(
        declarations=tuple(scan.declarations),
        top_level_statements=_initialization_statements("".join(scan.initialization)),
    )


def _global_initialization_only(candidate: str, source: str) -> ModernScriptStructure | None:
    """A script with no functions, whose code is all global initialization.

    GameMaker 2.3+ runs the code of a script asset that is not a compatibility
    script once, before the first room starts, whether or not the script
    declares functions; only a compatibility script (saved with
    "isCompatibility": true, a pre-2.3 script) is a body that runs when it is
    called.
    """
    scan = _TopLevelScan(source, candidate)
    if not scan.run() or scan.declarations:
        return None
    statements = _initialization_statements("".join(scan.initialization))
    if not statements:
        return None
    return ModernScriptStructure(declarations=(), top_level_statements=statements)


def _starts_statement(previous: str, previous_word: str, after_line_break: bool) -> bool:
    """Whether a statement can start after the code that ends in ``previous``."""
    if not previous or previous in ";}":
        return True
    if not after_line_break:
        return False
    # Line breaks are white space, but a declaration cannot continue an
    # expression: it starts a statement after anything that can end one.
    if previous in _IDENTIFIER_CHARACTERS:
        return previous_word not in _WORDS_BEFORE_A_VALUE
    return previous in ")]\"'"


def modern_script_structure(
    source: str,
    *,
    macro_configuration: str | None = None,
    legacy_callable: bool = True,
) -> ModernScriptStructure | None:
    """The functions and global initialization of a script, if it has either.

    A script that declares no function is a legacy callable (None) unless
    ``legacy_callable`` is False, as it is for a script that is not saved as a
    compatibility script: its code is then the global initialization.
    """
    preprocessed = preprocess_gml_source_preserving_layout(
        source,
        macro_configuration=macro_configuration,
    )
    candidate = _mask_comments_preserving_layout(preprocessed.source)
    if not candidate.strip():
        return None
    structure = _declarations_and_constructor_initializers(source, candidate)
    if structure is not None:
        return structure
    structure = _declarations_and_global_initialization(source, candidate)
    if structure is not None or legacy_callable:
        return structure
    return _global_initialization_only(candidate, source)


def _declarations_and_constructor_initializers(
    source: str,
    candidate: str,
) -> ModernScriptStructure | None:
    """A script made only of functions and constructor initialization."""
    declarations: list[ScriptFunctionDeclaration] = []
    top_level_statements: list[ScriptTopLevelStatement] = []
    index = 0
    while index < len(candidate):
        while index < len(candidate) and (candidate[index].isspace() or candidate[index] == ";"):
            index += 1
        if index >= len(candidate):
            break

        enum_match = _ENUM_DECLARATION_RE.match(candidate, index)
        if enum_match is not None:
            body_start = enum_match.end() - 1
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

        read = _read_function_declaration(candidate, source, index)
        if read is None:
            return None
        declaration, index = read
        declarations.append(declaration)

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
