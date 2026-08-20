# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify the IEC 61131-3 Edition 4 language profile."""

import unittest

from stc.compiler import compile_source, normalize_standard_edition


class Edition4Tests(unittest.TestCase):
    def test_standard_aliases_are_normalized(self):
        self.assertEqual(normalize_standard_edition("iec61131-3:ed3"), 3)
        self.assertEqual(normalize_standard_edition("ed4"), 4)
        self.assertEqual(normalize_standard_edition(2025), 4)

    def test_edition4_rejects_octal_and_untyped_trunc(self):
        source = """\
FUNCTION Legacy : INT
VAR Value : REAL := REAL#7.5; END_VAR
Legacy := TRUNC(Value) + 8#7;
END_FUNCTION
"""
        result = compile_source(source, "c", standard="ed4")

        self.assertFalse(result.success)
        self.assertEqual(
            {item.code for item in result.diagnostics},
            {"edition4-octal-literal", "edition4-untyped-trunc"},
        )

    def test_unicode_types_literals_and_assert_generate_for_both_targets(self):
        source = """\
PROGRAM UnicodeDemo
VAR
    Text : USTRING := USTRING#'Grüße ${1F642}';
    Letter : UCHAR := UCHAR#'A';
END_VAR
ASSERT(Letter = UCHAR#'A');
END_PROGRAM
"""
        c_result = compile_source(source, "c", standard="ed4")
        rust_result = compile_source(source, "rust", standard="ed4")

        self.assertTrue(c_result.success, c_result.diagnostics)
        self.assertTrue(rust_result.success, rust_result.diagnostics)
        self.assertIn('const char *Text;', c_result.output)
        self.assertIn('uint32_t Letter;', c_result.output)
        self.assertIn('"Grüße 🙂"', c_result.output)
        self.assertIn("ASSERT(self->Letter == 65);", c_result.output)
        self.assertIn("pub Text: &'static str", rust_result.output)
        self.assertIn("pub Letter: u32", rust_result.output)
        self.assertIn("ASSERT(self.Letter == 65);", rust_result.output)

    def test_edition3_reports_edition4_constructs(self):
        source = """\
PROGRAM P
VAR Text : USTRING; END_VAR
ASSERT(TRUE);
END_PROGRAM
"""
        result = compile_source(source, "c", standard="ed3")

        self.assertFalse(result.success)
        self.assertEqual(
            {item.code for item in result.diagnostics},
            {"edition4-unicode-type", "edition4-assert"},
        )

    def test_invalid_unicode_literals_are_diagnosed(self):
        source = """\
PROGRAM P
VAR Letter : UCHAR := UCHAR#'AB'; END_VAR
Letter := UCHAR#'${110000}';
END_PROGRAM
"""
        result = compile_source(source, "c", standard="ed4")

        self.assertFalse(result.success)
        self.assertEqual(
            {item.code for item in result.diagnostics},
            {"invalid-uchar-literal", "invalid-unicode-scalar"},
        )

    def test_explicit_conversion_is_loaded_from_standard_functions(self):
        source = """\
FUNCTION Convert : BOOL
VAR_INPUT Value : BYTE; END_VAR
Convert := BYTE_TO_BOOL(Value);
END_FUNCTION
"""
        result = compile_source(source, "c", standard="ed4")

        self.assertTrue(result.success, result.diagnostics)
        self.assertIn("bool BYTE_TO_BOOL(uint8_t Value)", result.output)

    def test_typed_truncation_is_lowered_to_target_casts(self):
        source = """\
FUNCTION Convert : DINT
VAR Value : REAL; END_VAR
Convert := REAL_TRUNC_DINT(Value);
END_FUNCTION
"""
        c_result = compile_source(source, "c", standard="ed4")
        rust_result = compile_source(source, "rust", standard="ed4")

        self.assertTrue(c_result.success, c_result.diagnostics)
        self.assertTrue(rust_result.success, rust_result.diagnostics)
        self.assertIn("((int32_t)(Value))", c_result.output)
        self.assertIn("(Value) as i32", rust_result.output)

    def test_edition3_supports_typed_truncation(self):
        source = """\
FUNCTION Convert : DINT
VAR Value : REAL; END_VAR
Convert := REAL_TRUNC_DINT(Value);
END_FUNCTION
"""
        result = compile_source(source, "c", standard="ed3")

        self.assertTrue(result.success, result.diagnostics)
        self.assertNotIn("edition4-typed-trunc", {item.code for item in result.diagnostics})

    def test_edition3_reports_normative_deprecations(self):
        source = """\
FUNCTION Legacy : INT
VAR Value : REAL; END_VAR
Legacy := TRUNC(Value) + 8#7;
END_FUNCTION
"""
        result = compile_source(source, "c", standard="ed3")

        self.assertTrue(result.success, result.diagnostics)
        self.assertEqual(
            {item.code for item in result.diagnostics},
            {"edition3-deprecated-trunc", "edition3-deprecated-octal-literal"},
        )

    def test_edition3_typed_character_literals_and_long_time_types(self):
        source = """\
FUNCTION Character : WCHAR
VAR
    LongDelay : LTIME;
    LongDate : LDATE;
    LongTod : LTOD;
    LongStamp : LDT;
END_VAR
Character := WCHAR#"A";
END_FUNCTION
"""
        c_result = compile_source(source, "c", standard="ed3")
        rust_result = compile_source(source, "rust", standard="ed3")

        self.assertTrue(c_result.success, c_result.diagnostics)
        self.assertTrue(rust_result.success, rust_result.diagnostics)
        self.assertIn("Character = 65", c_result.output)
        self.assertIn("Character = (65) as u16", rust_result.output)

        invalid = compile_source(
            """\
FUNCTION BadCharacter : CHAR
VAR Value : CHAR; END_VAR
BadCharacter := CHAR#'AB';
END_FUNCTION
""",
            "c",
            standard="ed3",
        )
        self.assertFalse(invalid.success)
        self.assertIn("invalid-character-literal", {item.code for item in invalid.diagnostics})

    def test_edition4_only_standard_function_is_rejected_in_edition3(self):
        source = """\
FUNCTION Units : INT
VAR Text : STRING; END_VAR
Units := LEN_CODE_UNIT(Text);
END_FUNCTION
"""
        result = compile_source(source, "c", standard="ed3")

        self.assertFalse(result.success)
        self.assertIn("edition4-standard-function", {item.code for item in result.diagnostics})


if __name__ == "__main__":
    unittest.main()
