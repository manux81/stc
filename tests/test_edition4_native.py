# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Edition 4 acceptance tests: compile and execute both native targets.

These tests assert observable IEC results, rather than the backend's string
representation. Unimplemented features fail explicitly until the string/Unicode
ABI work is integrated; no expectedFailure masks implementation regressions.
Run with PYTHONPATH=src python3 -m unittest tests.test_edition4_native -v.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from stc.compiler import compile_source


class NativeEdition4Tests(unittest.TestCase):
    target = None

    def run_program(self, declarations, body, expected=(), *, debug=True, succeeds=True, preamble=""):
        compiler = shutil.which("cc" if self.target == "c" else "rustc")
        if compiler is None:
            self.skipTest(f"Native compiler for {self.target} is unavailable")
        source = f"{preamble}\nPROGRAM Verify\nVAR\n{declarations}\nEND_VAR\n{body}\nEND_PROGRAM\n"
        result = compile_source(source, self.target, standard="ed4")
        self.assertTrue(result.success, str(result.syntax_error or result.diagnostics))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            if self.target == "c":
                fields = ", ".join(f"(long long)p.{name}" for name, _ in expected)
                output = ('    printf("' + " ".join("%lld" for _ in expected) + '\\n", ' + fields + ');\n') if expected else ""
                harness = "\nint main(void) {\n    Verify p;\n    Verify_cold_init(&p);\n    Verify_run(&p);\n" + output + "    return 0;\n}\n"
                path = root / "verify.c"
                command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror"]
                if not debug:
                    command.append("-DNDEBUG")
                command += [str(path), "-lm", "-o", str(root / "verify")]
            else:
                fields = ", ".join(f"p.{name} as i64" for name, _ in expected)
                output = ('    println!("' + " ".join("{}" for _ in expected) + '", ' + fields + ');\n') if expected else ""
                harness = "\nfn main() {\n    let mut p = Verify::default();\n    p.run();\n" + output + "}\n"
                path = root / "verify.rs"
                command = [compiler, "--edition=2021", "-D", "warnings", "-C",
                           "debug-assertions=" + ("yes" if debug else "no"),
                           str(path), "-o", str(root / "verify")]
            path.write_text(result.output + harness, encoding="utf-8")
            compiled = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run([str(root / "verify")], capture_output=True, text=True, timeout=5)
            if succeeds:
                self.assertEqual(executed.returncode, 0, executed.stderr)
                if expected:
                    self.assertEqual(executed.stdout.strip(), " ".join(str(value) for _, value in expected))
            else:
                self.assertNotEqual(executed.returncode, 0, "ASSERT(FALSE) must stop debug execution")

    def test_unicode_scalar_and_utf8_lengths(self):
        self.run_program("Text : USTRING; Letter : UCHAR; Characters : INT; Units : INT;",
                         "Text := USTRING#'A${1F642}'; Letter := UCHAR#'${1F642}';\n"
                         "Characters := LEN(Text); Units := LEN_CODE_UNIT(Text);",
                         (("Characters", 2), ("Units", 5), ("Letter", 0x1F642)))

    def test_short_unicode_string_literal(self):
        self.run_program("Text : USTRING; Count : INT;", "Text := U#'ABC'; Count := LEN(Text);", (("Count", 3),))

    def test_short_unicode_character_literal(self):
        self.run_program("Letter : UCHAR; Equal : BOOL;", "Letter := U#'A'; Equal := Letter = UCHAR#'A';",
                         (("Equal", 1),))

    def test_len_max_declared_capacity(self):
        self.run_program("Text : STRING[100]; Capacity : INT;", "Text := 'Hello'; Capacity := LEN_MAX(Text);",
                         (("Capacity", 100),))

    def test_ustring_declared_capacity(self):
        self.run_program("Text : USTRING[100]; Capacity : INT;",
                         "Text := USTRING#'Hello'; Capacity := LEN_MAX(Text);", (("Capacity", 100),))

    def test_property_get_and_set_execute(self):
        preamble = """FUNCTION_BLOCK Accumulator
VAR _value : INT; END_VAR
PROPERTY_GET PUBLIC Value : INT
Value := _value;
END_PROPERTY
PROPERTY_SET PUBLIC Value : INT
_value := Value;
END_PROPERTY
_value := _value + 0;
END_FUNCTION_BLOCK
"""
        self.run_program("Counter : Accumulator; Result : INT;",
                         "Counter.Value := 41; Result := Counter.Value;", (("Result", 41),), preamble=preamble)

    def test_default_profile_remains_edition3(self):
        source = "PROGRAM P VAR Value : INT; END_VAR Value := 1; ASSERT(TRUE); END_PROGRAM"
        result = compile_source(source, self.target)
        self.assertFalse(result.success)
        self.assertIn("edition4-assert", {item.code for item in result.diagnostics})

    def test_wstring_code_units(self):
        self.run_program("Text : WSTRING; Characters : INT; Units : INT;",
                         "Text := WSTRING#'Ä'; Characters := LEN(Text); Units := LEN_CODE_UNIT(Text);",
                         (("Characters", 1), ("Units", 1)))

    def test_braced_escape_in_string(self):
        self.run_program("Text : STRING; Equal : BOOL;", "Text := '${9}'; Equal := Text = '$T';", (("Equal", 1),))

    def test_braced_escape_in_wstring(self):
        self.run_program("Text : WSTRING; Equal : BOOL;", "Text := WSTRING#'${2211}'; Equal := Text = WSTRING#'∑';",
                         (("Equal", 1),))

    def test_independent_string_values_survive_operations(self):
        self.run_program("First : USTRING; Second : USTRING; Scratch : USTRING; Equal : BOOL; i : INT;",
                         "First := CONCAT(USTRING#'A', USTRING#'🙂');\n"
                         "Second := CONCAT(USTRING#'B', USTRING#'🙂');\n"
                         "FOR i := 1 TO 32 DO Scratch := CONCAT(USTRING#'X', USTRING#'Y'); END_FOR;\n"
                         "Equal := First = USTRING#'A🙂' AND Second = USTRING#'B🙂';", (("Equal", 1),))

    def test_typed_truncation_executes(self):
        self.run_program("Value : REAL; Positive : DINT; Negative : DINT;",
                         "Value := REAL#7.75; Positive := REAL_TRUNC_DINT(Value);\n"
                         "Value := REAL#-7.75; Negative := TRUNC_DINT(Value);", (("Positive", 7), ("Negative", -7)))

    def test_bcd_helpers_execute_with_deprecation_warning(self):
        source = "PROGRAM P VAR Packed : WORD; Value : INT; END_VAR Value := BCD_TO_INT(Packed); END_PROGRAM"
        result = compile_source(source, self.target, standard="ed4")
        self.assertTrue(result.success, str(result.syntax_error or result.diagnostics))
        self.assertIn("edition4-deprecated-bcd", {item.code for item in result.diagnostics})
        self.run_program("Packed : WORD; Value : INT;",
                         "Packed := INT_TO_BCD(1234); Value := BCD_TO_INT(Packed);", (("Value", 1234),))

    def test_assert_true_executes(self):
        self.run_program("Value : INT;", "Value := 1; ASSERT(Value = 1);", (("Value", 1),))

    def test_assert_false_stops_debug(self):
        self.run_program("Value : INT;", "Value := 1; ASSERT(FALSE);", succeeds=False)

    def test_assert_false_is_disabled_in_release(self):
        self.run_program("Value : INT;", "ASSERT(FALSE); Value := 42;", (("Value", 42),), debug=False)


# Export two concrete classes so missing native compilers are visible as skips,
# and each feature has an independent result for C and Rust.
class Edition4NativeCTests(NativeEdition4Tests):
    target = "c"


class Edition4NativeRustTests(NativeEdition4Tests):
    target = "rust"


# unittest otherwise also discovers the abstract helper class.
del NativeEdition4Tests


if __name__ == "__main__":
    unittest.main()
