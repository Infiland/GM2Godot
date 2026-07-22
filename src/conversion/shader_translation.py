from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


ShaderStage: TypeAlias = Literal["vertex", "fragment"]

_STORAGE_QUALIFIERS = frozenset(
    {"attribute", "const", "in", "out", "uniform", "varying"}
)
_PRECISION_QUALIFIERS = frozenset({"lowp", "mediump", "highp"})
_SUPPORTED_TYPES = frozenset(
    {
        "bool",
        "bvec2",
        "bvec3",
        "bvec4",
        "float",
        "int",
        "ivec2",
        "ivec3",
        "ivec4",
        "mat2",
        "mat3",
        "mat4",
        "sampler2D",
        "samplerCube",
        "uint",
        "uvec2",
        "uvec3",
        "uvec4",
        "vec2",
        "vec3",
        "vec4",
    }
)
_MATRIX_REPLACEMENTS = {
    "MATRIX_WORLD": "MODEL_MATRIX",
    "MATRIX_VIEW": "CANVAS_MATRIX",
    "MATRIX_PROJECTION": "SCREEN_MATRIX",
    "MATRIX_WORLD_VIEW": "(CANVAS_MATRIX * MODEL_MATRIX)",
    "MATRIX_WORLD_VIEW_PROJECTION": (
        "(SCREEN_MATRIX * CANVAS_MATRIX * MODEL_MATRIX)"
    ),
}
_GODOT_RESERVED_GLOBAL_NAMES = frozenset(
    {
        "AT_LIGHT_PASS",
        "CANVAS_MATRIX",
        "COLOR",
        "CUSTOM0",
        "CUSTOM1",
        "E",
        "FRAGCOORD",
        "INSTANCE_CUSTOM",
        "INSTANCE_ID",
        "MODEL_MATRIX",
        "NORMAL",
        "NORMAL_TEXTURE",
        "PI",
        "POINT_COORD",
        "POINT_SIZE",
        "REGION_RECT",
        "SCREEN_MATRIX",
        "SCREEN_PIXEL_SIZE",
        "SCREEN_UV",
        "TAU",
        "TEXTURE",
        "TEXTURE_PIXEL_SIZE",
        "TIME",
        "UV",
        "VERTEX",
        "VERTEX_ID",
    }
)


@dataclass(frozen=True)
class ShaderStageSource:
    stage: ShaderStage
    source: str


@dataclass(frozen=True)
class ShaderTranslationIssue:
    code: str
    message: str
    stage: ShaderStage
    line: int
    column: int
    construct: str
    workaround: str


@dataclass(frozen=True)
class ShaderTranslationResult:
    source: str | None
    issues: tuple[ShaderTranslationIssue, ...]


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    start: int
    end: int
    line: int
    column: int


@dataclass(frozen=True)
class _Edit:
    start: int
    end: int
    replacement: str


@dataclass(frozen=True)
class _Declarator:
    name: str
    array_suffix: str
    initializer: str | None
    name_token: _Token


@dataclass(frozen=True)
class _Declaration:
    qualifier: str
    precision: str | None
    type_name: str
    declarator: _Declarator
    stage: ShaderStage

    @property
    def name(self) -> str:
        return self.declarator.name

    @property
    def signature(self) -> tuple[str, str | None, str, str, str | None]:
        return (
            self.qualifier,
            self.precision,
            self.type_name,
            self.declarator.array_suffix,
            _normalized_code(self.declarator.initializer),
        )

    def render(self) -> str:
        parts = [self.qualifier]
        if self.precision is not None:
            parts.append(self.precision)
        parts.extend((self.type_name, self.name + self.declarator.array_suffix))
        rendered = " ".join(parts)
        if self.declarator.initializer is not None:
            rendered += " = " + self.declarator.initializer.strip()
        return rendered + ";"


@dataclass(frozen=True)
class _Function:
    name: str
    signature: str
    name_token: _Token
    body_start: int
    body_end: int
    stage: ShaderStage


@dataclass(frozen=True)
class _StageTranslation:
    stage: ShaderStage
    body: str
    declarations: tuple[_Declaration, ...]
    functions: tuple[_Function, ...]
    varying_references: frozenset[str]
    issues: tuple[ShaderTranslationIssue, ...]


def translate_gamemaker_shader(
    stages: tuple[ShaderStageSource, ...],
) -> ShaderTranslationResult:
    """Translate a bounded GLSL ES shader pair into one Godot CanvasItem shader."""
    if not stages:
        return ShaderTranslationResult(source=None, issues=())

    seen_stages: set[ShaderStage] = set()
    translated_stages: list[_StageTranslation] = []
    duplicate_issues: list[ShaderTranslationIssue] = []
    for stage_source in stages:
        if stage_source.stage in seen_stages:
            duplicate_issues.append(
                ShaderTranslationIssue(
                    code="GM2GD-SHADER-STAGE-CONFLICT",
                    message=(
                        f"Unsupported duplicate GameMaker {stage_source.stage} "
                        "shader stage prevents deterministic selection."
                    ),
                    stage=stage_source.stage,
                    line=1,
                    column=1,
                    construct="duplicate stage",
                    workaround=(
                        "Keep exactly one .vsh and one .fsh file for each "
                        "GameMaker shader resource."
                    ),
                )
            )
            continue
        seen_stages.add(stage_source.stage)
        translated_stages.append(
            _StageTranslator(stage_source.stage, stage_source.source).translate()
        )

    issues = [
        *duplicate_issues,
        *(
            issue
            for translated_stage in translated_stages
            for issue in translated_stage.issues
        ),
    ]
    declarations, declaration_issues = _merge_declarations(translated_stages)
    issues.extend(declaration_issues)
    issues.extend(_validate_varying_links(translated_stages))
    issues.extend(_validate_function_links(translated_stages))
    if issues:
        return ShaderTranslationResult(
            source=None,
            issues=tuple(_deduplicated_issues(issues)),
        )

    bodies = [
        translated_stage.body.strip()
        for translated_stage in translated_stages
        if translated_stage.body.strip()
    ]
    sections = [
        "shader_type canvas_item;",
        *(declaration.render() for declaration in declarations),
        *bodies,
    ]
    return ShaderTranslationResult(
        source="\n\n".join(sections).rstrip() + "\n",
        issues=(),
    )


class _StageTranslator:
    def __init__(self, stage: ShaderStage, source: str) -> None:
        self.stage: ShaderStage = stage
        self.source = source
        self.tokens, lexer_issues = _lex_shader(source, stage)
        self.significant = [
            token
            for token in self.tokens
            if token.kind not in {"whitespace", "comment"}
        ]
        self.issues: list[ShaderTranslationIssue] = list(lexer_issues)
        self.edits: list[_Edit] = []
        self.declarations: list[_Declaration] = []
        self.attributes: list[_Declaration] = []
        self.global_declarations: dict[str, _Declaration] = {}
        self.declaration_ranges: list[tuple[int, int]] = []
        self.functions: list[_Function] = []
        self.varying_references: set[str] = set()

    def translate(self) -> _StageTranslation:
        self._parse_top_level()
        self._validate_and_translate_functions()
        body = _apply_edits(self.source, self.edits)
        return _StageTranslation(
            stage=self.stage,
            body=body,
            declarations=tuple(self.declarations),
            functions=tuple(self.functions),
            varying_references=frozenset(self.varying_references),
            issues=tuple(_deduplicated_issues(self.issues)),
        )

    def _parse_top_level(self) -> None:
        index = 0
        main_count = 0
        while index < len(self.significant):
            token = self.significant[index]
            if token.kind == "directive":
                self._issue(
                    token,
                    "GM2GD-SHADER-CONSTRUCT-UNSUPPORTED",
                    "preprocessor directive",
                    "GameMaker shader preprocessor directives are not yet "
                    "merged safely across vertex and fragment stages.",
                    "Inline the directive for this shader or port the pair to "
                    "one reviewed .gdshader file.",
                )
                index += 1
                continue

            if token.text == "precision":
                end_index = self._statement_end(index)
                if end_index is None:
                    index += 1
                    continue
                statement = self.significant[index : end_index + 1]
                if not self._valid_precision_statement(statement):
                    self._issue(
                        token,
                        "GM2GD-SHADER-DECLARATION-UNSUPPORTED",
                        "precision declaration",
                        "GameMaker precision declaration is malformed or uses "
                        "an unsupported type.",
                        "Use `precision lowp|mediump|highp float|int;` or move "
                        "precision qualifiers onto individual declarations.",
                    )
                self._remove_statement(statement)
                index = end_index + 1
                continue

            if token.text in _STORAGE_QUALIFIERS:
                end_index = self._statement_end(index)
                if end_index is None:
                    index += 1
                    continue
                statement = self.significant[index : end_index + 1]
                self._parse_declaration(statement)
                self._remove_statement(statement)
                index = end_index + 1
                continue

            function_end = self._parse_function(index)
            if function_end is not None:
                function = self.functions[-1]
                if function.name == "main":
                    main_count += 1
                    self.edits.append(
                        _Edit(
                            function.name_token.start,
                            function.name_token.end,
                            self.stage,
                        )
                    )
                index = function_end + 1
                continue

            self._issue(
                token,
                "GM2GD-SHADER-CONSTRUCT-UNSUPPORTED",
                "top-level construct",
                f"Unsupported GameMaker shader top-level construct starts with "
                f"{token.text!r}.",
                "Keep global declarations to attributes, varyings, uniforms, "
                "constants, precision declarations, and function definitions.",
            )
            index = self._skip_unknown_top_level(index)

        if main_count != 1:
            token = self.significant[0] if self.significant else _origin_token()
            self._issue(
                token,
                "GM2GD-SHADER-ENTRYPOINT-UNSUPPORTED",
                "main entry point",
                f"GameMaker {self.stage} stage must contain exactly one "
                f"`void main()` entry point; found {main_count}.",
                "Provide one parameterless `void main()` function in each "
                "authored stage.",
            )

    def _statement_end(self, start_index: int) -> int | None:
        paren_depth = 0
        bracket_depth = 0
        for index in range(start_index, len(self.significant)):
            token = self.significant[index]
            if token.text == "(":
                paren_depth += 1
            elif token.text == ")":
                paren_depth -= 1
            elif token.text == "[":
                bracket_depth += 1
            elif token.text == "]":
                bracket_depth -= 1
            elif token.text == "{" and paren_depth == 0 and bracket_depth == 0:
                break
            elif token.text == ";" and paren_depth == 0 and bracket_depth == 0:
                return index
            if paren_depth < 0 or bracket_depth < 0:
                break
        self._issue(
            self.significant[start_index],
            "GM2GD-SHADER-DECLARATION-UNSUPPORTED",
            "unterminated declaration",
            "GameMaker shader declaration has no unambiguous terminating semicolon.",
            "Terminate the declaration with `;` and balance all parentheses and "
            "array brackets.",
        )
        return None

    @staticmethod
    def _valid_precision_statement(statement: list[_Token]) -> bool:
        return (
            len(statement) == 4
            and statement[1].text in _PRECISION_QUALIFIERS
            and statement[2].text in {"float", "int"}
            and statement[3].text == ";"
        )

    def _parse_declaration(self, statement: list[_Token]) -> None:
        qualifier = statement[0].text
        cursor = 1
        precision: str | None = None
        if cursor < len(statement) and statement[cursor].text in _PRECISION_QUALIFIERS:
            precision = statement[cursor].text
            cursor += 1
        if cursor >= len(statement) - 1 or statement[cursor].kind != "identifier":
            self._declaration_issue(
                statement[0],
                "Declaration has no supported type name.",
            )
            return
        type_name = statement[cursor].text
        cursor += 1
        if type_name not in _SUPPORTED_TYPES:
            self._declaration_issue(
                statement[cursor - 1],
                f"Shader type {type_name!r} is outside the supported GLSL ES "
                "to Godot declaration subset.",
            )
            return
        declarator_tokens = statement[cursor:-1]
        segments = _split_top_level(declarator_tokens, ",")
        if not segments or any(not segment for segment in segments):
            self._declaration_issue(
                statement[0],
                "Declaration contains an empty comma-separated declarator.",
            )
            return

        parsed: list[_Declarator] = []
        for segment in segments:
            declarator = self._parse_declarator(segment)
            if declarator is None:
                return
            parsed.append(declarator)

        for declarator in parsed:
            declaration = _Declaration(
                qualifier=qualifier,
                precision=precision,
                type_name=type_name,
                declarator=declarator,
                stage=self.stage,
            )
            if not self._validate_declaration(declaration):
                continue
            previous = self.global_declarations.get(declaration.name)
            if previous is not None:
                token = declaration.declarator.name_token
                self._issue(
                    token,
                    "GM2GD-SHADER-DECLARATION-UNSUPPORTED",
                    declaration.name,
                    f"Unsupported duplicate {self.stage} shader global "
                    f"{declaration.name!r} has more than one declaration.",
                    "Declare each attribute, varying, uniform, constant, or "
                    "GameMaker built-in at most once per stage.",
                )
                continue
            self.global_declarations[declaration.name] = declaration
            if declaration.qualifier == "attribute":
                self.attributes.append(declaration)
            elif not self._is_gamemaker_builtin_declaration(declaration):
                self.declarations.append(declaration)

    def _parse_declarator(self, tokens: list[_Token]) -> _Declarator | None:
        if not tokens or tokens[0].kind != "identifier":
            token = tokens[0] if tokens else _origin_token()
            self._declaration_issue(
                token,
                "Each declaration must start with an identifier.",
            )
            return None
        name_token = tokens[0]
        cursor = 1
        array_suffix = ""
        if cursor < len(tokens) and tokens[cursor].text == "[":
            end = _matching_token(tokens, cursor, "[", "]")
            if end is None or end == cursor + 1:
                self._declaration_issue(
                    tokens[cursor],
                    "Array declaration has no fixed size or closing bracket.",
                )
                return None
            array_suffix = "".join(token.text for token in tokens[cursor : end + 1])
            cursor = end + 1
            if cursor < len(tokens) and tokens[cursor].text == "[":
                self._declaration_issue(
                    tokens[cursor],
                    "Multi-dimensional shader arrays are not in the supported subset.",
                )
                return None

        initializer: str | None = None
        if cursor < len(tokens):
            if tokens[cursor].text != "=" or cursor + 1 >= len(tokens):
                self._declaration_issue(
                    tokens[cursor],
                    "Unexpected tokens follow the shader declarator.",
                )
                return None
            initializer_tokens = tokens[cursor + 1 :]
            initializer = _render_tokens(initializer_tokens)
            cursor = len(tokens)
        if cursor != len(tokens):
            self._declaration_issue(
                tokens[cursor],
                "Shader declarator could not be parsed unambiguously.",
            )
            return None
        return _Declarator(
            name=name_token.text,
            array_suffix=array_suffix,
            initializer=initializer,
            name_token=name_token,
        )

    def _validate_declaration(self, declaration: _Declaration) -> bool:
        token = declaration.declarator.name_token
        if declaration.qualifier in {"in", "out"}:
            self._issue(
                token,
                "GM2GD-SHADER-DECLARATION-UNSUPPORTED",
                f"{declaration.qualifier} interface declaration",
                "Modern GLSL stage `in`/`out` declarations cannot be merged "
                "unambiguously into a Godot CanvasItem shader.",
                "Use GameMaker LTS `attribute` and `varying` declarations for "
                "the supported 2D shader subset.",
            )
            return False
        if declaration.qualifier == "attribute" and self.stage != "vertex":
            self._declaration_issue(
                token,
                "Attributes are only valid in the GameMaker vertex stage.",
            )
            return False
        if declaration.qualifier != "const" and declaration.declarator.initializer is not None:
            self._declaration_issue(
                token,
                "Only global `const` declarations may have initializers in the "
                "supported subset.",
            )
            return False
        if declaration.qualifier == "const" and declaration.declarator.initializer is None:
            self._declaration_issue(
                token,
                "Global `const` declaration has no initializer.",
            )
            return False
        if (
            declaration.qualifier in {"attribute", "varying"}
            and declaration.type_name.startswith("sampler")
        ):
            self._declaration_issue(
                token,
                "Samplers cannot be vertex attributes or varyings.",
            )
            return False
        if declaration.name == "gm_BaseTexture":
            if (
                declaration.qualifier != "uniform"
                or declaration.type_name != "sampler2D"
                or declaration.declarator.array_suffix
                or self.stage != "fragment"
            ):
                self._declaration_issue(
                    token,
                    "`gm_BaseTexture` must be a non-array `uniform sampler2D` "
                    "in the fragment stage.",
                )
                return False
        if declaration.name == "gm_Matrices":
            if (
                declaration.qualifier != "uniform"
                or declaration.type_name != "mat4"
                or not declaration.declarator.array_suffix
                or self.stage != "vertex"
            ):
                self._declaration_issue(
                    token,
                    "`gm_Matrices` must be a vertex-stage `uniform mat4` array.",
                )
                return False
        if declaration.name in _GODOT_RESERVED_GLOBAL_NAMES:
            self._issue(
                token,
                "GM2GD-SHADER-DECLARATION-UNSUPPORTED",
                declaration.name,
                f"GameMaker global {declaration.name!r} collides with a Godot "
                "CanvasItem built-in and cannot share the generated scope.",
                "Rename the GameMaker global or port the shader manually while "
                "preserving any runtime uniform name contract.",
            )
            return False
        if (
            declaration.declarator.initializer is not None
            and _uses_scalar_matrix_constructor(
                declaration.type_name,
                declaration.declarator.initializer,
                self.stage,
            )
        ):
            self._issue(
                token,
                "GM2GD-SHADER-CONSTRUCTOR-UNSUPPORTED",
                declaration.name,
                f"GameMaker {declaration.type_name} scalar-list constructor "
                "for {declaration.name!r} is not accepted by Godot's matrix "
                "constructor grammar.",
                "Construct the matrix from column vectors in GameMaker or port "
                "this declaration manually.",
            )
            return False
        return True

    @staticmethod
    def _is_gamemaker_builtin_declaration(declaration: _Declaration) -> bool:
        return declaration.qualifier == "attribute" or declaration.name in {
            "gm_BaseTexture",
            "gm_Matrices",
        }

    def _parse_function(self, start_index: int) -> int | None:
        open_paren_index: int | None = None
        for index in range(start_index, len(self.significant)):
            text = self.significant[index].text
            if text == "(":
                open_paren_index = index
                break
            if text in {";", "{", "}"}:
                return None
        if open_paren_index is None or open_paren_index - start_index < 2:
            return None
        name_token = self.significant[open_paren_index - 1]
        return_tokens = self.significant[start_index : open_paren_index - 1]
        if (
            name_token.kind != "identifier"
            or not return_tokens
            or any(
                token.kind != "identifier"
                or (
                    token.text not in _PRECISION_QUALIFIERS
                    and token.text != "void"
                    and token.text not in _SUPPORTED_TYPES
                )
                for token in return_tokens
            )
        ):
            return None
        close_paren_index = _matching_token(
            self.significant,
            open_paren_index,
            "(",
            ")",
        )
        if close_paren_index is None:
            self._issue(
                name_token,
                "GM2GD-SHADER-FUNCTION-UNSUPPORTED",
                "function declaration",
                f"Shader function {name_token.text!r} has an unterminated "
                "parameter list.",
                "Balance the function parameter parentheses.",
            )
            return len(self.significant) - 1
        if close_paren_index + 1 >= len(self.significant):
            return None
        open_brace_index = close_paren_index + 1
        if self.significant[open_brace_index].text != "{":
            return None
        close_brace_index = _matching_token(
            self.significant,
            open_brace_index,
            "{",
            "}",
        )
        if close_brace_index is None:
            self._issue(
                name_token,
                "GM2GD-SHADER-FUNCTION-UNSUPPORTED",
                "function definition",
                f"Shader function {name_token.text!r} has an unterminated body.",
                "Balance the function body braces.",
            )
            return len(self.significant) - 1

        parameters = self.significant[open_paren_index + 1 : close_paren_index]
        return_type = return_tokens[-1].text
        if name_token.text == "main" and (return_type != "void" or parameters):
            self._issue(
                name_token,
                "GM2GD-SHADER-ENTRYPOINT-UNSUPPORTED",
                "main entry point",
                f"GameMaker {self.stage} entry point must be parameterless "
                "`void main()`.",
                "Remove entry-point parameters and return values.",
            )
        signature = (
            return_type
            + " "
            + name_token.text
            + "("
            + "".join(token.text for token in parameters)
            + ")"
        )
        self.functions.append(
            _Function(
                name=name_token.text,
                signature=signature,
                name_token=name_token,
                body_start=self.significant[open_brace_index].end,
                body_end=self.significant[close_brace_index].start,
                stage=self.stage,
            )
        )
        return close_brace_index

    def _validate_and_translate_functions(self) -> None:
        attributes = {
            declaration.name: declaration
            for declaration in self._all_parsed_attribute_declarations()
        }
        varying_names = {
            declaration.name
            for declaration in self.declarations
            if declaration.qualifier == "varying"
        }
        for function in self.functions:
            body_tokens = [
                token
                for token in self.significant
                if function.body_start <= token.start < function.body_end
            ]
            if function.name == "main" and self.stage == "vertex":
                position_ranges = self._translate_position_assignments(body_tokens)
            else:
                position_ranges = []
            self._translate_function_tokens(
                function,
                body_tokens,
                attributes,
                varying_names,
                position_ranges,
            )

    def _all_parsed_attribute_declarations(self) -> tuple[_Declaration, ...]:
        return tuple(self.attributes)

    def _translate_position_assignments(
        self,
        body_tokens: list[_Token],
    ) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        position_tokens = [
            (index, token)
            for index, token in enumerate(body_tokens)
            if token.text == "gl_Position"
        ]
        assignment_count = 0
        for index, token in position_tokens:
            if _inside_ranges(token.start, ranges):
                continue
            if index + 1 >= len(body_tokens) or body_tokens[index + 1].text != "=":
                self._issue(
                    token,
                    "GM2GD-SHADER-POSITION-UNSUPPORTED",
                    "gl_Position access",
                    "`gl_Position` is read or updated with an unsupported "
                    "operation instead of a direct assignment.",
                    "Assign `gl_Position` from a supported GameMaker matrix "
                    "transform and do not read it.",
                )
                continue
            semicolon_index = _expression_semicolon(body_tokens, index + 2)
            if semicolon_index is None:
                self._issue(
                    token,
                    "GM2GD-SHADER-POSITION-UNSUPPORTED",
                    "gl_Position assignment",
                    "`gl_Position` assignment has no unambiguous terminating "
                    "semicolon.",
                    "Terminate the assignment and balance its expression.",
                )
                continue
            expression = body_tokens[index + 2 : semicolon_index]
            local_expression = self._local_position_expression(expression)
            end_token = body_tokens[semicolon_index]
            assignment_range = (token.start, end_token.end)
            ranges.append(assignment_range)
            assignment_count += 1
            if local_expression is None:
                continue
            translated_expression = self._translate_expression(local_expression)
            if translated_expression is None:
                continue
            self.edits.append(
                _Edit(
                    token.start,
                    end_token.end,
                    f"VERTEX = ({translated_expression}).xy;",
                )
            )

        if assignment_count == 0:
            token = next(
                (
                    function.name_token
                    for function in self.functions
                    if function.name == "main"
                ),
                _origin_token(),
            )
            self._issue(
                token,
                "GM2GD-SHADER-POSITION-UNSUPPORTED",
                "missing gl_Position assignment",
                "GameMaker vertex entry point does not assign `gl_Position`.",
                "Assign a 2D position through "
                "`gm_Matrices[MATRIX_WORLD_VIEW_PROJECTION]`.",
            )
        return ranges

    def _local_position_expression(
        self,
        expression: list[_Token],
    ) -> list[_Token] | None:
        expression = _strip_outer_parentheses(expression)
        first_matrix = _matrix_access_at(expression, 0)
        if first_matrix is None:
            self._position_expression_issue(expression)
            return None
        matrix_name, cursor = first_matrix
        if cursor >= len(expression) or expression[cursor].text != "*":
            self._position_expression_issue(expression)
            return None
        cursor += 1

        if matrix_name == "MATRIX_WORLD_VIEW_PROJECTION":
            local_expression = expression[cursor:]
        elif matrix_name == "MATRIX_PROJECTION":
            second_matrix = _matrix_access_at(expression, cursor)
            if second_matrix is None:
                self._position_expression_issue(expression)
                return None
            second_name, cursor = second_matrix
            if cursor >= len(expression) or expression[cursor].text != "*":
                self._position_expression_issue(expression)
                return None
            cursor += 1
            if second_name == "MATRIX_WORLD_VIEW":
                local_expression = expression[cursor:]
            elif second_name == "MATRIX_VIEW":
                third_matrix = _matrix_access_at(expression, cursor)
                if third_matrix is None:
                    self._position_expression_issue(expression)
                    return None
                third_name, cursor = third_matrix
                if (
                    third_name != "MATRIX_WORLD"
                    or cursor >= len(expression)
                    or expression[cursor].text != "*"
                ):
                    self._position_expression_issue(expression)
                    return None
                local_expression = expression[cursor + 1 :]
            else:
                self._position_expression_issue(expression)
                return None
        else:
            self._position_expression_issue(expression)
            return None

        local_expression = _strip_outer_parentheses(local_expression)
        if not local_expression:
            self._position_expression_issue(expression)
            return None
        return local_expression

    def _position_expression_issue(self, expression: list[_Token]) -> None:
        token = expression[0] if expression else _origin_token()
        self._issue(
            token,
            "GM2GD-SHADER-POSITION-UNSUPPORTED",
            "gl_Position transform",
            "GameMaker clip-space position is not a supported 2D "
            "world/view/projection transform.",
            "Use `MATRIX_WORLD_VIEW_PROJECTION * local_position`, "
            "`MATRIX_PROJECTION * MATRIX_WORLD_VIEW * local_position`, or "
            "`MATRIX_PROJECTION * MATRIX_VIEW * MATRIX_WORLD * local_position`; "
            "port perspective, custom clip-space, and 3D transforms manually.",
        )

    def _translate_expression(self, tokens: list[_Token]) -> str | None:
        parts: list[str] = []
        index = 0
        valid = True
        attributes = {
            declaration.name: declaration
            for declaration in self._all_parsed_attribute_declarations()
        }
        while index < len(tokens):
            token = tokens[index]
            matrix_access = (
                _matrix_access_at(tokens, index)
                if token.text == "gm_Matrices"
                else None
            )
            if matrix_access is not None:
                matrix_name, index = matrix_access
                replacement = _MATRIX_REPLACEMENTS.get(matrix_name)
                if replacement is None:
                    self._matrix_issue(token, matrix_name)
                    valid = False
                else:
                    parts.append(replacement)
                continue
            replacement = self._identifier_replacement(
                token,
                attributes,
            )
            if replacement is None:
                if self._is_unsupported_special_identifier(token):
                    valid = False
                parts.append(token.text)
            else:
                parts.append(replacement)
            index += 1
        return " ".join(parts) if valid else None

    def _translate_function_tokens(
        self,
        function: _Function,
        tokens: list[_Token],
        attributes: dict[str, _Declaration],
        varying_names: set[str],
        excluded_ranges: list[tuple[int, int]],
    ) -> None:
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if _inside_ranges(token.start, excluded_ranges):
                index += 1
                continue
            if token.text in varying_names:
                self.varying_references.add(token.text)
                if (
                    function.name != "main"
                    and index + 1 < len(tokens)
                    and tokens[index + 1].text
                    in {"=", "+=", "-=", "*=", "/=", "++", "--"}
                ):
                    self._issue(
                        token,
                        "GM2GD-SHADER-VARYING-WRITE-UNSUPPORTED",
                        f"{function.name}:{token.text}",
                        f"Helper function {function.name!r} assigns varying "
                        f"{token.text!r}, which Godot only permits in a "
                        "processing function.",
                        "Return the value from the helper and assign the varying "
                        "inside `main()`.",
                    )
            if _scalar_matrix_constructor_end(tokens, index) is not None:
                self._issue(
                    token,
                    "GM2GD-SHADER-CONSTRUCTOR-UNSUPPORTED",
                    f"{token.text} scalar-list constructor",
                    f"GameMaker {token.text} scalar-list constructor is not "
                    "accepted by Godot's matrix constructor grammar.",
                    "Construct the matrix from column vectors in GameMaker or "
                    "port this expression manually.",
                )
            if token.text == "gm_Matrices":
                matrix_access = _matrix_access_at(tokens, index)
                if matrix_access is None:
                    self._matrix_issue(token, "dynamic or malformed index")
                    index += 1
                    continue
                matrix_name, next_index = matrix_access
                replacement = _MATRIX_REPLACEMENTS.get(matrix_name)
                if function.name != "main":
                    self._helper_builtin_issue(token, function, "gm_Matrices")
                elif replacement is None:
                    self._matrix_issue(token, matrix_name)
                else:
                    self.edits.append(
                        _Edit(
                            token.start,
                            tokens[next_index - 1].end,
                            replacement,
                        )
                    )
                index = next_index
                continue

            if function.name != "main" and (
                token.text in attributes
                or token.text in {"gm_BaseTexture", "gl_FragColor"}
            ):
                self._helper_builtin_issue(token, function, token.text)
                index += 1
                continue
            replacement = self._identifier_replacement(
                token,
                attributes,
            )
            if replacement is not None:
                self.edits.append(_Edit(token.start, token.end, replacement))
            else:
                self._is_unsupported_special_identifier(token)
            index += 1

    def _identifier_replacement(
        self,
        token: _Token,
        attributes: dict[str, _Declaration],
    ) -> str | None:
        if token.text in attributes:
            declaration = attributes[token.text]
            return self._attribute_replacement(declaration, token)
        if token.text in {
            "in_Position",
            "in_Normal",
            "in_Colour",
            "in_Colour0",
            "in_TextureCoord",
        }:
            self._issue(
                token,
                "GM2GD-SHADER-ATTRIBUTE-UNSUPPORTED",
                token.text,
                f"GameMaker built-in attribute {token.text!r} is used without "
                "a matching parsed vertex declaration.",
                "Declare the attribute once with its documented GameMaker type.",
            )
            return None
        if token.text == "gm_BaseTexture":
            if self.stage != "fragment":
                self._issue(
                    token,
                    "GM2GD-SHADER-BUILTIN-UNSUPPORTED",
                    "gm_BaseTexture",
                    "`gm_BaseTexture` can only map to Godot `TEXTURE` in the "
                    "fragment stage.",
                    "Sample the base texture from the fragment stage.",
                )
                return None
            return "TEXTURE"
        if token.text == "texture2D":
            return "texture"
        if token.text == "gl_FragColor":
            if self.stage != "fragment":
                self._issue(
                    token,
                    "GM2GD-SHADER-BUILTIN-UNSUPPORTED",
                    "gl_FragColor",
                    "`gl_FragColor` can only map to Godot `COLOR` in the "
                    "fragment stage.",
                    "Write the fragment result from the fragment stage.",
                )
                return None
            return "COLOR"
        return None

    def _attribute_replacement(
        self,
        declaration: _Declaration,
        token: _Token,
    ) -> str | None:
        if self.stage != "vertex":
            self._attribute_issue(token, declaration.name)
            return None
        if declaration.name == "in_Position":
            if declaration.type_name == "vec2":
                return "VERTEX"
            if declaration.type_name == "vec3":
                return "vec3(VERTEX, 0.0)"
        elif (
            declaration.name in {"in_Colour", "in_Colour0"}
            and declaration.type_name == "vec4"
        ):
            return "COLOR"
        elif (
            declaration.name == "in_TextureCoord"
            and declaration.type_name == "vec2"
        ):
            return "UV"
        self._attribute_issue(token, declaration.name)
        return None

    def _attribute_issue(self, token: _Token, attribute_name: str) -> None:
        if attribute_name == "in_Normal":
            detail = (
                "GameMaker normal attributes have no CanvasItem vertex input "
                "equivalent."
            )
        elif attribute_name.startswith("in_Colour") and attribute_name not in {
            "in_Colour",
            "in_Colour0",
        }:
            detail = (
                "Additional GameMaker colour attributes have no CanvasItem "
                "vertex input equivalent."
            )
        else:
            detail = (
                "Custom GameMaker vertex-format attributes cannot be bound to "
                "Godot CanvasItem inputs."
            )
        self._issue(
            token,
            "GM2GD-SHADER-ATTRIBUTE-UNSUPPORTED",
            attribute_name,
            f"{detail} Attribute {attribute_name!r} was not converted.",
            "Use the supported in_Position, in_Colour/in_Colour0, and "
            "in_TextureCoord attributes, or port the custom vertex-buffer "
            "pipeline manually.",
        )

    def _is_unsupported_special_identifier(self, token: _Token) -> bool:
        if token.text == "gl_Position":
            self._issue(
                token,
                "GM2GD-SHADER-POSITION-UNSUPPORTED",
                "gl_Position access",
                "Unconverted `gl_Position` access remains in the shader.",
                "Use a direct supported matrix assignment in the vertex entry point.",
            )
            return True
        if token.text.startswith("gl_"):
            self._issue(
                token,
                "GM2GD-SHADER-BUILTIN-UNSUPPORTED",
                token.text,
                f"GLSL ES built-in {token.text!r} has no defined mapping in "
                "the supported CanvasItem subset.",
                "Replace it with a documented Godot 4.7 CanvasItem built-in or "
                "port the shader manually.",
            )
            return True
        if token.text == "gm_Matrices" or token.text.startswith("MATRIX_"):
            self._matrix_issue(token, token.text)
            return True
        return False

    def _matrix_issue(self, token: _Token, matrix_name: str) -> None:
        self._issue(
            token,
            "GM2GD-SHADER-MATRIX-UNSUPPORTED",
            f"gm_Matrices[{matrix_name}]",
            f"GameMaker matrix access {matrix_name!r} is dynamic, malformed, "
            "or outside the supported world/view/projection constants.",
            "Use MATRIX_WORLD, MATRIX_VIEW, MATRIX_PROJECTION, "
            "MATRIX_WORLD_VIEW, or MATRIX_WORLD_VIEW_PROJECTION with a fixed "
            "index.",
        )

    def _helper_builtin_issue(
        self,
        token: _Token,
        function: _Function,
        builtin_name: str,
    ) -> None:
        self._issue(
            token,
            "GM2GD-SHADER-HELPER-UNSUPPORTED",
            f"{function.name}:{builtin_name}",
            f"GameMaker helper function {function.name!r} reads or writes "
            f"stage built-in {builtin_name!r}, which Godot exposes only in "
            "the processing entry point.",
            "Pass the built-in value into the helper as a parameter, return "
            "the result, and read or write the built-in inside `main()`.",
        )

    def _remove_statement(self, statement: list[_Token]) -> None:
        start = statement[0].start
        end = statement[-1].end
        self.declaration_ranges.append((start, end))
        self.edits.append(_Edit(start, end, ""))

    def _declaration_issue(self, token: _Token, detail: str) -> None:
        self._issue(
            token,
            "GM2GD-SHADER-DECLARATION-UNSUPPORTED",
            "global declaration",
            detail,
            "Split the declaration into supported GLSL ES attribute, varying, "
            "uniform, or const declarators with fixed one-dimensional arrays.",
        )

    def _issue(
        self,
        token: _Token,
        code: str,
        construct: str,
        message: str,
        workaround: str,
    ) -> None:
        self.issues.append(
            ShaderTranslationIssue(
                code=code,
                message=message,
                stage=self.stage,
                line=token.line,
                column=token.column,
                construct=construct,
                workaround=workaround,
            )
        )

    def _skip_unknown_top_level(self, index: int) -> int:
        depth = 0
        while index < len(self.significant):
            text = self.significant[index].text
            if text in {"(", "[", "{"}:
                depth += 1
            elif text in {")", "]", "}"}:
                depth = max(0, depth - 1)
            index += 1
            if depth == 0 and text in {";", "}"}:
                break
        return index


def _merge_declarations(
    stages: list[_StageTranslation],
) -> tuple[list[_Declaration], list[ShaderTranslationIssue]]:
    merged: list[_Declaration] = []
    by_name: dict[str, _Declaration] = {}
    issues: list[ShaderTranslationIssue] = []
    for stage in stages:
        for declaration in stage.declarations:
            previous = by_name.get(declaration.name)
            if previous is None:
                by_name[declaration.name] = declaration
                merged.append(declaration)
                continue
            if previous.signature == declaration.signature:
                continue
            token = declaration.declarator.name_token
            issues.append(
                ShaderTranslationIssue(
                    code="GM2GD-SHADER-DECLARATION-CONFLICT",
                    message=(
                        f"Unsupported cross-stage shader global "
                        f"{declaration.name!r} has incompatible {previous.stage} "
                        f"and {declaration.stage} declarations."
                    ),
                    stage=declaration.stage,
                    line=token.line,
                    column=token.column,
                    construct=declaration.name,
                    workaround=(
                        "Use the same qualifier, precision, type, array size, "
                        "and initializer in both stages."
                    ),
                )
            )
    return merged, issues


def _validate_varying_links(
    stages: list[_StageTranslation],
) -> list[ShaderTranslationIssue]:
    vertex = next((stage for stage in stages if stage.stage == "vertex"), None)
    fragment = next((stage for stage in stages if stage.stage == "fragment"), None)
    if fragment is None:
        return []
    vertex_varyings: set[str] = set()
    if vertex is not None:
        vertex_varyings = {
            declaration.name
            for declaration in vertex.declarations
            if declaration.qualifier == "varying"
        }
    fragment_varyings = {
        declaration.name: declaration
        for declaration in fragment.declarations
        if declaration.qualifier == "varying"
    }
    issues: list[ShaderTranslationIssue] = []
    for name in sorted(fragment.varying_references):
        if name in vertex_varyings:
            continue
        declaration = fragment_varyings.get(name)
        token = (
            declaration.declarator.name_token
            if declaration is not None
            else _origin_token()
        )
        issues.append(
            ShaderTranslationIssue(
                code="GM2GD-SHADER-VARYING-UNLINKED",
                message=(
                    f"Unsupported fragment varying {name!r} has no matching "
                    "vertex-stage declaration, so its interpolated value is "
                    "undefined."
                ),
                stage="fragment",
                line=token.line,
                column=token.column,
                construct=name,
                workaround=(
                    "Declare the same varying type and array size in both stages "
                    "and assign it from the vertex entry point."
                ),
            )
        )
    return issues


def _validate_function_links(
    stages: list[_StageTranslation],
) -> list[ShaderTranslationIssue]:
    seen: dict[str, _Function] = {}
    issues: list[ShaderTranslationIssue] = []
    for stage in stages:
        for function in stage.functions:
            if function.name == "main":
                continue
            previous = seen.get(function.signature)
            if previous is None:
                seen[function.signature] = function
                continue
            token = function.name_token
            issues.append(
                ShaderTranslationIssue(
                    code="GM2GD-SHADER-FUNCTION-CONFLICT",
                    message=(
                        f"Unsupported helper function {function.signature!r} is "
                        "defined in both shader stages and cannot share one "
                        "Godot scope."
                    ),
                    stage=function.stage,
                    line=token.line,
                    column=token.column,
                    construct=function.signature,
                    workaround=(
                        "Keep one shared helper definition or give stage-specific "
                        "helpers distinct signatures."
                    ),
                )
            )
    return issues


def _lex_shader(
    source: str,
    stage: ShaderStage,
) -> tuple[list[_Token], list[ShaderTranslationIssue]]:
    tokens: list[_Token] = []
    issues: list[ShaderTranslationIssue] = []
    index = 0
    line = 1
    column = 1
    line_has_code = False

    def consume(text: str) -> None:
        nonlocal line, column, line_has_code
        for character in text:
            if character == "\n":
                line += 1
                column = 1
                line_has_code = False
            else:
                column += 1

    def add(kind: str, end: int) -> None:
        nonlocal index, line_has_code
        text = source[index:end]
        tokens.append(
            _Token(
                kind=kind,
                text=text,
                start=index,
                end=end,
                line=line,
                column=column,
            )
        )
        consume(text)
        if kind not in {"whitespace", "comment"}:
            line_has_code = not text.endswith(("\n", "\r"))
        index = end

    while index < len(source):
        character = source[index]
        if character.isspace():
            end = index + 1
            while end < len(source) and source[end].isspace():
                end += 1
            add("whitespace", end)
            continue
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            add("comment", len(source) if end < 0 else end)
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                token = _Token(
                    kind="comment",
                    text=source[index:],
                    start=index,
                    end=len(source),
                    line=line,
                    column=column,
                )
                tokens.append(token)
                issues.append(
                    ShaderTranslationIssue(
                        code="GM2GD-SHADER-LEX-UNSUPPORTED",
                        message="GameMaker shader contains an unterminated block comment.",
                        stage=stage,
                        line=line,
                        column=column,
                        construct="block comment",
                        workaround="Close the comment with `*/`.",
                    )
                )
                break
            add("comment", end + 2)
            continue
        if character == "#" and not line_has_code:
            end = index
            while end < len(source):
                newline = source.find("\n", end)
                if newline < 0:
                    end = len(source)
                    break
                backslash = newline - 1
                while backslash >= index and source[backslash] in {" ", "\t", "\r"}:
                    backslash -= 1
                end = newline + 1
                if backslash < index or source[backslash] != "\\":
                    break
            add("directive", end)
            continue
        if character.isalpha() or character == "_":
            end = index + 1
            while end < len(source) and (
                source[end].isalnum() or source[end] == "_"
            ):
                end += 1
            add("identifier", end)
            continue
        if character.isdigit() or (
            character == "."
            and index + 1 < len(source)
            and source[index + 1].isdigit()
        ):
            end = index + 1
            while end < len(source):
                if source[end].isalnum() or source[end] in {".", "_"}:
                    end += 1
                    continue
                if (
                    source[end] in {"+", "-"}
                    and end > index
                    and source[end - 1] in {"e", "E"}
                ):
                    end += 1
                    continue
                break
            add("number", end)
            continue
        if character in {'"', "'"}:
            quote = character
            end = index + 1
            escaped = False
            while end < len(source):
                current = source[end]
                end += 1
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    break
            add("string", end)
            continue
        matched_operator = next(
            (
                operator
                for operator in (
                    "<<=",
                    ">>=",
                    "++",
                    "--",
                    "+=",
                    "-=",
                    "*=",
                    "/=",
                    "%=",
                    "==",
                    "!=",
                    "<=",
                    ">=",
                    "&&",
                    "||",
                    "<<",
                    ">>",
                )
                if source.startswith(operator, index)
            ),
            None,
        )
        add("symbol", index + len(matched_operator or character))
    return tokens, issues


def _split_top_level(tokens: list[_Token], separator: str) -> list[list[_Token]]:
    result: list[list[_Token]] = []
    current: list[_Token] = []
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    for token in tokens:
        if token.text == "(":
            paren_depth += 1
        elif token.text == ")":
            paren_depth -= 1
        elif token.text == "[":
            bracket_depth += 1
        elif token.text == "]":
            bracket_depth -= 1
        elif token.text == "{":
            brace_depth += 1
        elif token.text == "}":
            brace_depth -= 1
        if (
            token.text == separator
            and paren_depth == 0
            and bracket_depth == 0
            and brace_depth == 0
        ):
            result.append(current)
            current = []
        else:
            current.append(token)
    result.append(current)
    return result


def _matching_token(
    tokens: list[_Token],
    start_index: int,
    opening: str,
    closing: str,
) -> int | None:
    if start_index >= len(tokens) or tokens[start_index].text != opening:
        return None
    depth = 0
    for index in range(start_index, len(tokens)):
        if tokens[index].text == opening:
            depth += 1
        elif tokens[index].text == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _matrix_access_at(
    tokens: list[_Token],
    index: int,
) -> tuple[str, int] | None:
    if index >= len(tokens):
        return None
    if tokens[index].text == "(":
        close = _matching_token(tokens, index, "(", ")")
        if close is not None:
            inner = _matrix_access_at(tokens[index + 1 : close], 0)
            if inner is not None and inner[1] == close - index - 1:
                return inner[0], close + 1
    if (
        index + 3 < len(tokens)
        and tokens[index].text == "gm_Matrices"
        and tokens[index + 1].text == "["
        and tokens[index + 2].kind == "identifier"
        and tokens[index + 3].text == "]"
    ):
        return tokens[index + 2].text, index + 4
    return None


def _scalar_matrix_constructor_end(
    tokens: list[_Token],
    index: int,
) -> int | None:
    dimensions = {"mat2": 2, "mat3": 3, "mat4": 4}
    dimension = dimensions.get(tokens[index].text) if index < len(tokens) else None
    if (
        dimension is None
        or index + 1 >= len(tokens)
        or tokens[index + 1].text != "("
    ):
        return None
    close = _matching_token(tokens, index + 1, "(", ")")
    if close is None:
        return None
    arguments = _split_top_level(tokens[index + 2 : close], ",")
    if len(arguments) != dimension * dimension or any(
        not argument for argument in arguments
    ):
        return None
    return close + 1


def _uses_scalar_matrix_constructor(
    type_name: str,
    initializer: str,
    stage: ShaderStage,
) -> bool:
    if type_name not in {"mat2", "mat3", "mat4"}:
        return False
    tokens, _issues = _lex_shader(initializer, stage)
    significant = [
        token
        for token in tokens
        if token.kind not in {"whitespace", "comment"}
    ]
    end = _scalar_matrix_constructor_end(significant, 0)
    return end == len(significant)


def _strip_outer_parentheses(tokens: list[_Token]) -> list[_Token]:
    result = tokens
    while result and result[0].text == "(":
        close = _matching_token(result, 0, "(", ")")
        if close != len(result) - 1:
            break
        result = result[1:-1]
    return result


def _expression_semicolon(tokens: list[_Token], start_index: int) -> int | None:
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    for index in range(start_index, len(tokens)):
        text = tokens[index].text
        if text == "(":
            paren_depth += 1
        elif text == ")":
            paren_depth -= 1
        elif text == "[":
            bracket_depth += 1
        elif text == "]":
            bracket_depth -= 1
        elif text == "{":
            brace_depth += 1
        elif text == "}":
            brace_depth -= 1
        elif (
            text == ";"
            and paren_depth == 0
            and bracket_depth == 0
            and brace_depth == 0
        ):
            return index
        if paren_depth < 0 or bracket_depth < 0 or brace_depth < 0:
            return None
    return None


def _render_tokens(tokens: list[_Token]) -> str:
    return " ".join(token.text for token in tokens)


def _normalized_code(value: str | None) -> str | None:
    if value is None:
        return None
    return "".join(value.split())


def _inside_ranges(offset: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= offset < end for start, end in ranges)


def _apply_edits(source: str, edits: list[_Edit]) -> str:
    if not edits:
        return source.strip()
    ordered = sorted(edits, key=lambda edit: (edit.start, edit.end))
    parts: list[str] = []
    cursor = 0
    for edit in ordered:
        if edit.start < cursor:
            continue
        parts.append(source[cursor : edit.start])
        parts.append(edit.replacement)
        cursor = edit.end
    parts.append(source[cursor:])
    return "".join(parts).strip()


def _deduplicated_issues(
    issues: list[ShaderTranslationIssue],
) -> list[ShaderTranslationIssue]:
    return list(dict.fromkeys(issues))


def _origin_token() -> _Token:
    return _Token(
        kind="origin",
        text="",
        start=0,
        end=0,
        line=1,
        column=1,
    )
