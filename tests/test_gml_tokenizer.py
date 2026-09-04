from __future__ import annotations

import unittest

from src.conversion.gml_transpiler_parts.lexical_api import tokenize_gml_source
from src.conversion.gml_transpiler_parts.shared_models import GMLTranspileError


def _token_fields(
    source: str,
) -> list[tuple[str, str, int, int, int]]:
    return [
        (token.kind, token.value, token.index, token.line, token.column)
        for token in tokenize_gml_source(source)
    ]


class TestGMLTokenizerLineColumns(unittest.TestCase):
    def test_public_tokens_preserve_exact_lf_crlf_cr_and_mixed_positions(self) -> None:
        cases = {
            "lf": (
                "a\nb",
                [
                    ("IDENT", "a", 0, 1, 1),
                    ("NEWLINE", "\n", 1, 1, 2),
                    ("IDENT", "b", 2, 2, 1),
                    ("EOF", "", 3, 2, 2),
                ],
            ),
            "crlf": (
                "a\r\nb",
                [
                    ("IDENT", "a", 0, 1, 1),
                    ("NEWLINE", "\n", 2, 1, 2),
                    ("IDENT", "b", 3, 2, 1),
                    ("EOF", "", 4, 2, 2),
                ],
            ),
            "cr_only": (
                "a\rb",
                [
                    ("IDENT", "a", 0, 1, 1),
                    ("NEWLINE", "\n", 1, 1, 2),
                    ("IDENT", "b", 2, 1, 3),
                    ("EOF", "", 3, 1, 4),
                ],
            ),
            "mixed": (
                "a\r\nb\nc\rd",
                [
                    ("IDENT", "a", 0, 1, 1),
                    ("NEWLINE", "\n", 2, 1, 2),
                    ("IDENT", "b", 3, 2, 1),
                    ("NEWLINE", "\n", 4, 2, 2),
                    ("IDENT", "c", 5, 3, 1),
                    ("NEWLINE", "\n", 6, 3, 2),
                    ("IDENT", "d", 7, 3, 3),
                    ("EOF", "", 8, 3, 4),
                ],
            ),
        }

        for case_name, (source, expected) in cases.items():
            with self.subTest(case=case_name):
                self.assertEqual(_token_fields(source), expected)

    def test_tokenizes_both_verbatim_delimiters_as_single_multiline_tokens(
        self,
    ) -> None:
        source = '@"first\r\nsecond"\r\n+ @\'double " quote\''

        tokens = tokenize_gml_source(source)

        self.assertEqual(tokens[0].kind, "VERBATIM_STRING")
        self.assertEqual(tokens[0].value, '@"first\r\nsecond"')
        self.assertEqual((tokens[0].line, tokens[0].column), (1, 1))
        self.assertEqual(tokens[1].kind, "NEWLINE")
        self.assertEqual((tokens[1].line, tokens[1].column), (2, 8))
        self.assertEqual(tokens[2].value, "+")
        self.assertEqual((tokens[2].line, tokens[2].column), (3, 1))
        self.assertEqual(tokens[3].kind, "VERBATIM_STRING")
        self.assertEqual(tokens[3].value, '@\'double " quote\'')

    def test_verbatim_backslash_does_not_escape_the_closing_delimiter(self) -> None:
        tokens = tokenize_gml_source(r'@"a\" + suffix')

        self.assertEqual(tokens[0].kind, "VERBATIM_STRING")
        self.assertEqual(tokens[0].value, r'@"a\"')
        self.assertEqual(tokens[1].value, "+")
        self.assertEqual(tokens[2].value, "suffix")

    def test_rejects_unterminated_verbatim_string_at_prefix_location(self) -> None:
        with self.assertRaises(GMLTranspileError) as raised:
            tokenize_gml_source('value + @"unterminated')

        self.assertEqual(raised.exception.line, 1)
        self.assertEqual(raised.exception.column, 9)
        self.assertIn("Unterminated verbatim string literal", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
