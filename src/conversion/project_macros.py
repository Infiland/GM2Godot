# pyright: reportPrivateUsage=false
from __future__ import annotations

from collections.abc import Iterable, Sequence

from src.conversion.gml_transpiler_parts.model import GMLTranspileError, _Token
from src.conversion.gml_transpiler_parts.preprocessor import preprocess_gml_source
from src.conversion.gml_transpiler_parts.tokens import _tokenize
from src.conversion.gml_transpiler_parts.utils import (
    _macro_configuration_matches,
    _tokens_to_source,
)
from src.conversion.project_source_paths import project_gml_source_paths
from src.conversion.type_defs import StrPath


def collect_project_macro_values(
    gm_project_path: StrPath,
    *,
    macro_configuration: str | None = None,
) -> dict[str, str]:
    """Collect GameMaker's project-global macro expressions.

    Sources and declarations are visited in a stable order. A declaration for
    the selected configuration always takes precedence over an unqualified
    declaration, matching GameMaker's configuration override semantics.
    """
    token_streams: list[list[_Token]] = []
    for source_path in project_gml_source_paths(gm_project_path):
        try:
            with open(source_path.filesystem_path, "r", encoding="utf-8") as source_file:
                source = source_file.read()
            preprocessed = preprocess_gml_source(
                source,
                macro_configuration=macro_configuration,
            )
            token_streams.append(_tokenize(preprocessed.source))
        except (OSError, GMLTranspileError):
            # The owning resource converter reports malformed/unsupported GML.
            # Discovery should not prevent unrelated resources from converting.
            continue

    return _collect_macro_values(
        token_streams,
        macro_configuration=macro_configuration,
    )
def _collect_macro_values(
    token_streams: Iterable[Sequence[_Token]],
    *,
    macro_configuration: str | None,
) -> dict[str, str]:
    values: dict[str, str] = {}
    priorities: dict[str, int] = {}
    for tokens in token_streams:
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.kind != "DIRECTIVE" or token.value != "#macro":
                index += 1
                continue
            index += 1
            if index >= len(tokens) or tokens[index].kind != "IDENT":
                continue

            configuration_or_name = tokens[index].value
            index += 1
            configuration: str | None = None
            name = configuration_or_name
            if index < len(tokens) and tokens[index].value == ":":
                configuration = configuration_or_name
                index += 1
                if index >= len(tokens) or tokens[index].kind != "IDENT":
                    continue
                name = tokens[index].value
                index += 1

            value_tokens: list[_Token] = []
            while index < len(tokens) and tokens[index].kind not in {"NEWLINE", "EOF"}:
                value_tokens.append(tokens[index])
                index += 1
            if not value_tokens:
                continue
            if configuration is not None and not _macro_configuration_matches(
                configuration,
                macro_configuration,
            ):
                continue

            priority = 1 if configuration is not None else 0
            if priority >= priorities.get(name, -1):
                values[name] = _tokens_to_source(value_tokens)
                priorities[name] = priority
    return values


__all__ = ["collect_project_macro_values"]
