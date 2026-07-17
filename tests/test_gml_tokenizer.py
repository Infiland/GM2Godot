# pyright: reportPrivateUsage=false
from __future__ import annotations

import unittest

from src.conversion.gml_transpiler_parts.tokens import (
    _line_column,
    _line_column_from_newline_positions,
    _tokenize,
)
from src.conversion.gml_transpiler_parts.model import GMLTranspileError


def _legacy_line_column(source: str, index: int) -> tuple[int, int]:
    line = source.count("\n", 0, index) + 1
    line_start = source.rfind("\n", 0, index)
    if line_start == -1:
        return line, index + 1
    return line, index - line_start


class TestGMLTokenizerLineColumns(unittest.TestCase):
    def test_precomputed_line_columns_match_legacy_semantics_at_every_position(
        self,
    ) -> None:
        cases = {
            "empty": "",
            "lf": "\nalpha\n\nomega\n",
            "crlf": "\r\nalpha\r\n\r\nomega\r\n",
            "cr_only": "\ralpha\r\romega\r",
            "mixed": "first\r\nsecond\nthird\rfourth",
            "unicode": "naïve 🙂\n漢字\r\n👩‍💻 é\n",
        }

        for case_name, source in cases.items():
            newline_positions = tuple(
                index for index, char in enumerate(source) if char == "\n"
            )
            for index in range(len(source) + 1):
                with self.subTest(case=case_name, index=index):
                    expected = _legacy_line_column(source, index)
                    self.assertEqual(_line_column(source, index), expected)
                    self.assertEqual(
                        _line_column_from_newline_positions(
                            newline_positions,
                            index,
                        ),
                        expected,
                    )

    def test_tokenizes_both_verbatim_delimiters_as_single_multiline_tokens(
        self,
    ) -> None:
        source = '@"first\r\nsecond"\r\n+ @\'double " quote\''

        tokens = _tokenize(source)

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
        tokens = _tokenize(r'@"a\" + suffix')

        self.assertEqual(tokens[0].kind, "VERBATIM_STRING")
        self.assertEqual(tokens[0].value, r'@"a\"')
        self.assertEqual(tokens[1].value, "+")
        self.assertEqual(tokens[2].value, "suffix")

    def test_rejects_unterminated_verbatim_string_at_prefix_location(self) -> None:
        with self.assertRaises(GMLTranspileError) as raised:
            _tokenize('value + @"unterminated')

        self.assertEqual(raised.exception.line, 1)
        self.assertEqual(raised.exception.column, 9)
        self.assertIn("Unterminated verbatim string literal", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
