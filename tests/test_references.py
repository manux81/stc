# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""IEC 61131-3 Edition 3/4 reference type regression tests."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from stc.compiler import compile_source


REFERENCE_PROGRAM = """
TYPE
    Pair : STRUCT Left : INT; Right : INT; END_STRUCT;
    Values : ARRAY[1..4] OF INT;
    IntRef : REF_TO INT;
END_TYPE

PROGRAM Main
VAR
    X : INT := 1;
    P : Pair;
    A : Values;
    R : REF_TO INT := REF(X);
    Q : IntRef := REF(X);
    PR : REF_TO Pair := REF(P);
    AR : REF_TO Values := REF(A);
END_VAR
    IF R <> NULL THEN
        R^ := R^ + 1;
    END_IF;
    Q := R;
    PR^.Left := Q^;
    AR^[2] := PR^.Left;
    R := REF(A[3]);
END_PROGRAM
"""


class ReferenceTests(unittest.TestCase):
    def test_reference_support_is_edition_gated(self):
        edition2 = compile_source(REFERENCE_PROGRAM, "c", standard="ed2", generate_code=False)
        edition3 = compile_source(REFERENCE_PROGRAM, "c", standard="ed3", generate_code=False)
        edition4 = compile_source(REFERENCE_PROGRAM, "c", standard="ed4", generate_code=False)

        self.assertFalse(edition2.success)
        self.assertIn("edition3-reference", {item.code for item in edition2.diagnostics})
        self.assertTrue(edition3.success, edition3.diagnostics)
        self.assertTrue(edition4.success, edition4.diagnostics)

    def test_reference_codegen_compiles_for_c_and_rust(self):
        compilers = {"c": shutil.which("cc"), "rust": shutil.which("rustc")}
        for target, compiler in compilers.items():
            with self.subTest(target=target):
                result = compile_source(REFERENCE_PROGRAM, target, standard="ed3")
                self.assertTrue(result.success, result.diagnostics)
                self.assertIn("IntRef", result.output)
                if compiler is None:
                    continue
                with tempfile.TemporaryDirectory() as directory:
                    suffix = ".c" if target == "c" else ".rs"
                    generated = Path(directory, "references" + suffix)
                    generated.write_text(result.output, encoding="utf-8")
                    if target == "c":
                        command = [
                            compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-c", str(generated), "-o", str(Path(directory, "references.o")),
                        ]
                    else:
                        command = [
                            compiler, "--crate-type", "lib", "-D", "warnings",
                            str(generated), "-o", str(Path(directory, "references.rlib")),
                        ]
                    completed = subprocess.run(command, capture_output=True, text=True)
                    self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_reference_semantic_errors(self):
        cases = {
            "dereference-non-reference": """
                PROGRAM Main VAR X : INT; END_VAR X^ := 1; END_PROGRAM
            """,
            "incompatible-assignment": """
                PROGRAM Main VAR X : INT; R : REAL; P : REF_TO INT; Q : REF_TO REAL; END_VAR
                    P := REF(X); Q := P;
                END_PROGRAM
            """,
            "reference-to-temporary": """
                FUNCTION Bad : INT VAR X : INT; P : REF_TO INT; END_VAR
                    P := REF(X); Bad := 0;
                END_FUNCTION
            """,
            "reference-in-out": """
                FUNCTION_BLOCK Bad VAR_IN_OUT P : REF_TO INT; END_VAR P^ := 1; END_FUNCTION_BLOCK
            """,
            "incompatible-reference-initializer": """
                PROGRAM Main VAR X : REAL; P : REF_TO INT := REF(X); END_VAR
                    X := X;
                END_PROGRAM
            """,
        }
        for code, source in cases.items():
            with self.subTest(code=code):
                result = compile_source(source, "c", standard="ed3", generate_code=False)
                self.assertFalse(result.success)
                self.assertIn(code, {item.code for item in result.diagnostics})


if __name__ == "__main__":
    unittest.main()
