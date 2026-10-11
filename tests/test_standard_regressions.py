# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Regression cases from the IEC 61131-3 conformance review."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from stc import compile_source


class StandardRegressionTests(unittest.TestCase):
    def assert_error(self, source, code, standard="ed4"):
        for target in ("c", "rust"):
            with self.subTest(target=target, code=code):
                result = compile_source(source, target, standard=standard)
                self.assertIsNone(result.syntax_error)
                self.assertFalse(result.success)
                self.assertIn(code, {d.code for d in result.diagnostics})
                self.assertIsNone(result.output)

    def assert_success(self, source, standard="ed4"):
        for target in ("c", "rust"):
            with self.subTest(target=target):
                result = compile_source(source, target, standard=standard)
                self.assertTrue(result.success, result.diagnostics or result.syntax_error)

    def run_native(self, source, target, harness):
        compiler = shutil.which("cc" if target == "c" else "rustc")
        if compiler is None:
            self.skipTest(f"{target} compiler unavailable")
        result = compile_source(source, target, standard="ed4")
        self.assertTrue(result.success, result.diagnostics or result.syntax_error)
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory, "probe.c" if target == "c" else "probe.rs")
            executable = Path(directory, "probe")
            generated.write_text(result.output + harness, encoding="utf-8")
            flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-DNDEBUG"] if target == "c" else [
                "-D", "warnings", "-C", "debug-assertions=no",
            ]
            compiled = subprocess.run([compiler, *flags, str(generated), "-o", str(executable)],
                                      capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            return subprocess.run([str(executable)], cwd=directory, capture_output=True, text=True)

    def test_private_inherited_and_default_protected_methods_are_inaccessible(self):
        for standard in ("ed3", "ed4"):
            for access in ("PRIVATE", "PROTECTED", ""):
                source = f"""CLASS Base
METHOD {access} Hidden : INT
Hidden := 1;
END_METHOD
END_CLASS
CLASS Derived EXTENDS Base END_CLASS
PROGRAM P
VAR item : Derived; result : INT; END_VAR
result := item.Hidden();
END_PROGRAM"""
                with self.subTest(access=access, standard=standard):
                    self.assert_error(source, "inaccessible-member", standard)

    def test_private_method_can_be_called_inside_defining_class(self):
        self.assert_success("""CLASS Counter
METHOD PRIVATE Hidden : INT
Hidden := 1;
END_METHOD
METHOD PUBLIC Value : INT
Value := THIS.Hidden();
END_METHOD
END_CLASS
PROGRAM P
VAR item : Counter; result : INT; END_VAR
result := item.Value();
END_PROGRAM""")

    def test_protected_method_can_be_called_by_derived_class(self):
        self.assert_success("""CLASS Base
METHOD PROTECTED Hidden : INT
Hidden := 1;
END_METHOD
END_CLASS
CLASS Derived EXTENDS Base
METHOD PUBLIC Value : INT
Value := SUPER.Hidden();
END_METHOD
END_CLASS
PROGRAM P
VAR item : Derived; result : INT; END_VAR
result := item.Value();
END_PROGRAM""")

    def test_private_base_method_is_inaccessible_to_derived_class(self):
        self.assert_error("""CLASS Base
METHOD PRIVATE Hidden : INT
Hidden := 1;
END_METHOD
END_CLASS
CLASS Derived EXTENDS Base
METHOD PUBLIC Value : INT
Value := SUPER.Hidden();
END_METHOD
END_CLASS""", "inaccessible-member")

    def test_private_property_setter_is_checked_independently_of_getter(self):
        declaration = """FUNCTION_BLOCK Counter
VAR value : INT; END_VAR
PROPERTY_GET PUBLIC Number : INT
Number := value;
END_PROPERTY
PROPERTY_SET PRIVATE Number : INT
value := Number;
END_PROPERTY
value := value;
END_FUNCTION_BLOCK
PROGRAM P
VAR item : Counter; result : INT; END_VAR
"""
        self.assert_success(declaration + "result := item.Number; END_PROGRAM")
        self.assert_error(declaration + "item.Number := 2; END_PROGRAM", "inaccessible-member")

    def test_private_method_cannot_be_exposed_through_interface(self):
        self.assert_error("""INTERFACE IValue
METHOD Value : INT END_METHOD
END_INTERFACE
CLASS Counter IMPLEMENTS IValue
METHOD PRIVATE Value : INT
Value := 1;
END_METHOD
END_CLASS""", "interface-member-not-public")

    def test_override_cannot_reduce_public_access(self):
        self.assert_error("""CLASS Base
METHOD PUBLIC Value : INT
Value := 1;
END_METHOD
END_CLASS
CLASS Derived EXTENDS Base
METHOD PRIVATE OVERRIDE Value : INT
Value := 2;
END_METHOD
END_CLASS""", "override-access-mismatch")

    def test_edition2_rejects_class_and_interface_declarations(self):
        for source in ("CLASS A END_CLASS", "INTERFACE IA METHOD F END_METHOD END_INTERFACE"):
            self.assert_error(source, "edition3-oop", "ed2")
            self.assert_success(source, "ed3")

    def test_legacy_warnings_belong_only_to_edition3(self):
        source = """FUNCTION Legacy : INT
VAR value : REAL; END_VAR
Legacy := TRUNC(value) + 8#7;
END_FUNCTION"""
        for target in ("c", "rust"):
            ed2 = compile_source(source, target, standard="ed2")
            self.assertTrue(ed2.success, ed2.diagnostics)
            self.assertEqual(ed2.diagnostics, ())
            ed3 = compile_source(source, target, standard="ed3")
            self.assertTrue(ed3.success, ed3.diagnostics)
            self.assertEqual({d.code for d in ed3.diagnostics}, {
                "edition3-deprecated-octal-literal", "edition3-deprecated-trunc",
            })
        self.assert_error(source, "edition4-octal-literal")
        self.assert_error(source, "edition4-untyped-trunc")

    def test_wchar_hex_escape_decodes_the_full_four_digits(self):
        source = """FUNCTION Probe : WCHAR
VAR letter : WCHAR; END_VAR
letter := WCHAR#"$0041";
Probe := letter;
END_FUNCTION"""
        for target, harness in (
            ("c", '\nint main(void) { return Probe() == 65 ? 0 : 1; }\n'),
            ("rust", '\nfn main() { assert_eq!(Probe(), 65); }\n'),
        ):
            with self.subTest(target=target):
                self.assertEqual(self.run_native(source, target, harness).returncode, 0)

    def test_single_byte_escape_does_not_consume_following_hex_characters(self):
        source = """FUNCTION Probe : INT
VAR text : STRING[3]; END_VAR
text := STRING#'$4142';
Probe := LEN(text);
END_FUNCTION"""
        for target, harness in (
            ("c", '\nint main(void) { return Probe() == 3 ? 0 : 1; }\n'),
            ("rust", '\nfn main() { assert_eq!(Probe(), 3); }\n'),
        ):
            with self.subTest(target=target):
                self.assertEqual(self.run_native(source, target, harness).returncode, 0)

    def test_literal_assignments_and_initializers_cannot_exceed_capacity(self):
        for kind, literal in (("STRING", "'ABCDE'"), ("WSTRING", '"ABCDE"'),
                              ("USTRING", "USTRING#'ABCDE'")):
            with self.subTest(kind=kind):
                self.assert_error(f"""PROGRAM P
VAR text : {kind}[2]; END_VAR
text := {literal};
END_PROGRAM""", "string-capacity-exceeded")
                self.assert_error(f"""PROGRAM P
VAR text : {kind}[2] := {literal}; END_VAR
text := text;
END_PROGRAM""", "string-capacity-exceeded")

    def test_dynamic_assignment_enforces_capacity_in_release_builds(self):
        for kind, literal in (("STRING", "'ABCDE'"), ("WSTRING", '"ABCDE"'),
                              ("USTRING", "USTRING#'ABCDE'")):
            source = f"""FUNCTION Probe : INT
VAR text : {kind}[2]; original : {kind}[8]; END_VAR
original := {literal};
text := original;
Probe := LEN(text);
END_FUNCTION"""
            for target, harness in (
                ("c", '\nint main(void) { return Probe(); }\n'),
                ("rust", '\nfn main() { let _ = Probe(); }\n'),
            ):
                with self.subTest(target=target, kind=kind):
                    run = self.run_native(source, target, harness)
                    self.assertNotEqual(run.returncode, 0)
                    self.assertIn("string capacity exceeded", run.stderr)

    def test_unicode_capacity_does_not_count_utf8_bytes(self):
        source = """FUNCTION Probe : INT
VAR text : USTRING[2]; original : USTRING[8]; END_VAR
original := USTRING#'é🙂';
text := original;
Probe := LEN(text);
END_FUNCTION"""
        for target, harness in (
            ("c", '\nint main(void) { return Probe() == 2 ? 0 : 1; }\n'),
            ("rust", '\nfn main() { assert_eq!(Probe(), 2); }\n'),
        ):
            with self.subTest(target=target):
                self.assertEqual(self.run_native(source, target, harness).returncode, 0)

    def test_string_with_hash_in_its_content_is_not_a_typed_literal(self):
        self.assert_error("""PROGRAM P
VAR text : STRING[2]; END_VAR
text := 'a#b';
END_PROGRAM""", "string-capacity-exceeded")


if __name__ == "__main__":
    unittest.main()
