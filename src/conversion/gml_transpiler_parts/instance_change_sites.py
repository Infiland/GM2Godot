"""Where a piece of GML source runs instance_change, directly or through a name.

The statement parser decides which instance_change statements it compiles with
the rest of the event as their continuation, and the diagnostics report the
ones it did not. They read the same source through different token streams (the
parser's has comments joined away and macros spliced in), so a site is named by
its place in the order of the source's site tokens: the identifiers in the
source text, outside preprocessor lines, that are instance_change or one of the
names that run it (a project script function or macro).
"""
from __future__ import annotations

from collections.abc import Collection, Sequence

from .shared_models import Token

INSTANCE_CHANGE_NAME = "instance_change"


def instance_change_site_indices(tokens: Sequence[Token], names: Collection[str] = ()) -> list[int]:
    """Return the index of each site token, in source order."""
    indices: list[int] = []
    in_directive = False
    for index, token in enumerate(tokens):
        if token.kind == "DIRECTIVE":
            in_directive = True
        elif token.kind == "NEWLINE":
            in_directive = False
        if in_directive or token.kind != "IDENT":
            continue
        if token.value != INSTANCE_CHANGE_NAME and token.value not in names:
            continue
        if index > 0 and tokens[index - 1].value == ".":
            # (A member of something else.)
            continue
        indices.append(index)
    return indices


def instance_change_site_ordinals(
    tokens: Sequence[Token],
    names: Collection[str] = (),
) -> dict[tuple[int, int], int]:
    """Return the ordinal of each site token, by the line and column it stands at."""
    return {
        (tokens[index].line, tokens[index].column): ordinal
        for ordinal, index in enumerate(instance_change_site_indices(tokens, names))
    }
