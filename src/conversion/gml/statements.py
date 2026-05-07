from src.conversion.gml.ast import GMLTranspileError
from src.conversion.gml.expression_parser import transpile_expression
from src.conversion.gml.operators import ASSIGNMENT_OPERATORS


def transpile_simple_statement(statement, local_names=None):
    if not statement:
        return []

    if local_names is None:
        local_names = set()

    if statement.startswith("var "):
        return _transpile_var_statement(statement[4:].strip(), local_names)

    increment = _parse_increment_statement(statement)
    if increment is not None:
        target, delta = increment
        return [f"{transpile_expression(target, local_names)} {'+=' if delta > 0 else '-='} 1"]

    assignment = _split_assignment(statement)
    if assignment is not None:
        target, operator, value = assignment
        target = transpile_expression(target, local_names)
        value = transpile_expression(value, local_names)
        if operator == "??=":
            return [f"if {target} == null:", f"\t{target} = {value}"]
        return [f"{target} {operator} {value}"]

    return [transpile_expression(statement, local_names)]


def _transpile_var_statement(statement, local_names=None):
    lines = []
    if local_names is None:
        local_names = set()
    for declaration in _split_top_level(statement, ","):
        declaration = declaration.strip()
        if not declaration:
            continue
        assignment = _split_assignment(declaration)
        if assignment is None:
            name = declaration.strip()
            lines.append(f"var {name}")
            local_names.add(name)
            continue
        name, operator, value = assignment
        if operator != "=":
            raise GMLTranspileError("Variable declarations only support '=' assignments")
        name = name.strip()
        lines.append(f"var {name} = {transpile_expression(value, local_names)}")
        local_names.add(name)
    return lines


def _parse_increment_statement(statement):
    stripped = statement.strip()
    if stripped.endswith("++"):
        return stripped[:-2].strip(), 1
    if stripped.endswith("--"):
        return stripped[:-2].strip(), -1
    if stripped.startswith("++"):
        return stripped[2:].strip(), 1
    if stripped.startswith("--"):
        return stripped[2:].strip(), -1
    return None


def _split_assignment(statement):
    depth = 0
    in_string = None
    escaped = False
    index = 0

    while index < len(statement):
        char = statement[index]
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            index += 1
            continue

        if char == '"' or char == "'":
            in_string = char
            index += 1
            continue
        if char in "([{":
            depth += 1
            index += 1
            continue
        if char in ")]}" and depth > 0:
            depth -= 1
            index += 1
            continue

        if depth == 0:
            for operator in ASSIGNMENT_OPERATORS:
                if statement.startswith(operator, index):
                    if operator == "=" and _is_comparison_assignment_false_positive(statement, index):
                        continue
                    left = statement[:index].strip()
                    right = statement[index + len(operator):].strip()
                    if left and right:
                        return left, operator, right
        index += 1
    return None


def _is_comparison_assignment_false_positive(statement, index):
    previous_char = statement[index - 1] if index > 0 else ""
    next_char = statement[index + 1] if index + 1 < len(statement) else ""
    return previous_char in "!<>=?" or next_char == "="


def _split_top_level(source, separator):
    parts = []
    start = 0
    depth = 0
    in_string = None
    escaped = False

    for index, char in enumerate(source):
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue

        if char == '"' or char == "'":
            in_string = char
            continue
        if char in "([{":
            depth += 1
            continue
        if char in ")]}" and depth > 0:
            depth -= 1
            continue
        if char == separator and depth == 0:
            parts.append(source[start:index])
            start = index + 1

    parts.append(source[start:])
    return parts
