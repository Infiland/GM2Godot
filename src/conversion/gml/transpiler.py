from src.conversion.gml.ast import GMLTranspileError
from src.conversion.gml.expression_parser import transpile_expression
from src.conversion.gml.lexer import tokenize
from src.conversion.gml.source import strip_comments
from src.conversion.gml.statement_parser import StatementParser


def transpile_gml_expression(source, local_names=None):
    """Transpile a single GML expression to a GDScript expression."""
    return transpile_expression(source, local_names)


def transpile_gml_code(source, indent="\t"):
    """Transpile supported GML statements to GDScript."""
    parser = StatementParser(tokenize(strip_comments(source)))
    lines = parser.parse()

    if not lines:
        return f"{indent}pass"

    return "\n".join(f"{indent}{line}" if line else "" for line in lines)
