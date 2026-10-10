# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check encoding, diagnostics and execution for six byte-array conversions."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from stc import compile_source


class ByteArrayConversionTests(unittest.TestCase):
    def native(self, declarations, body, *, succeeds=True, preamble=""):
        source = f"{preamble}\nPROGRAM P VAR {declarations} Ok : BOOL; END_VAR {body} END_PROGRAM"
        for target in ("c", "rust"):
            with self.subTest(target=target):
                compiler = shutil.which("cc" if target == "c" else "rustc")
                if compiler is None:
                    self.skipTest(f"Missing native compiler for {target}")
                result = compile_source(source, target, standard="ed4")
                self.assertTrue(result.success, str(result.syntax_error or [(d.code, d.message) for d in result.diagnostics]))
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    path = root / ("test.c" if target == "c" else "test.rs")
                    harness = ("\nint main(void) { P p; P_cold_init(&p); P_run(&p); return p.Ok ? 0 : 1; }\n"
                               if target == "c" else "\nfn main() { let mut p = P::default(); p.run(); assert!(p.Ok); }\n")
                    path.write_text(result.output + harness, encoding="utf-8")
                    command = ([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(path), "-lm"]
                               if target == "c" else [compiler, "-D", "warnings", str(path)])
                    executable = root / "test"
                    compiled = subprocess.run(command + ["-o", str(executable)], capture_output=True, text=True, timeout=30)
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)
                    executed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=5)
                    if succeeds:
                        self.assertEqual(executed.returncode, 0, executed.stderr)
                    else:
                        self.assertNotEqual(executed.returncode, 0)

    def test_ascii_round_trips_all_six_functions(self):
        for family in ("STRING", "WSTRING", "USTRING"):
            with self.subTest(family=family):
                self.native("Bytes : ARRAY[-2..5] OF BYTE; Text : USTRING;",
                            f"Bytes := {family}_TO_ARRAY_OF_BYTE({family}#'ABC'); "
                            f"Text := ARRAY_OF_BYTE_TO_{family}(Bytes); Ok := Text = USTRING#'ABC';")

    def test_utf8_exact_capacity_and_nonzero_lower_bound(self):
        self.native("Bytes : ARRAY[4..8] OF BYTE; Text : USTRING;",
                    "Bytes := USTRING_TO_ARRAY_OF_BYTE(USTRING#'A🙂'); Text := ARRAY_OF_BYTE_TO_USTRING(Bytes); "
                    "Ok := Bytes[4] = 65 AND Bytes[5] = 240 AND Bytes[6] = 159 AND Bytes[7] = 153 "
                    "AND Bytes[8] = 130 AND Text = USTRING#'A🙂';")

    def test_utf16_little_endian_surrogate_pair(self):
        self.native("Bytes : ARRAY[1..8] OF BYTE; Text : USTRING;",
                    "Bytes := WSTRING_TO_ARRAY_OF_BYTE(WSTRING#'Ä🙂'); Text := ARRAY_OF_BYTE_TO_WSTRING(Bytes); "
                    "Ok := Bytes[1] = 196 AND Bytes[2] = 0 AND Bytes[3] = 61 AND Bytes[4] = 216 "
                    "AND Bytes[5] = 66 AND Bytes[6] = 222 AND Bytes[7] = 0 AND Text = USTRING#'Ä🙂';")

    def test_single_byte_string_encoding(self):
        self.native("Bytes : ARRAY[1..2] OF BYTE; Text : USTRING;",
                    "Bytes := STRING_TO_ARRAY_OF_BYTE(STRING#'Ä'); Text := ARRAY_OF_BYTE_TO_STRING(Bytes); "
                    "Ok := Bytes[1] = 196 AND Bytes[2] = 0 AND Text = USTRING#'Ä';")

    def test_named_array_zero_padding(self):
        self.native("Bytes : Payload; Text : USTRING;",
                    "Bytes[13] := 255; Bytes := USTRING_TO_ARRAY_OF_BYTE(USTRING#'AB'); "
                    "Text := ARRAY_OF_BYTE_TO_USTRING(Bytes); Ok := Bytes[10] = 65 AND Bytes[11] = 66 "
                    "AND Bytes[12] = 0 AND Bytes[13] = 0 AND Text = USTRING#'AB';",
                    preamble="TYPE Payload : ARRAY[10..13] OF BYTE; END_TYPE")

    def test_empty_string(self):
        self.native("Bytes : ARRAY[1..1] OF BYTE; Text : USTRING;",
                    "Bytes := USTRING_TO_ARRAY_OF_BYTE(USTRING#''); Text := ARRAY_OF_BYTE_TO_USTRING(Bytes); "
                    "Ok := Bytes[1] = 0 AND Text = USTRING#'';")

    def test_array_to_string_stops_at_zero(self):
        self.native("Bytes : ARRAY[1..3] OF BYTE; Text : USTRING;",
                    "Bytes[1] := 65; Bytes[2] := 0; Bytes[3] := 255; "
                    "Text := ARRAY_OF_BYTE_TO_USTRING(Bytes); Ok := Text = USTRING#'A';")

    def test_insufficient_destination_traps(self):
        self.native("Bytes : ARRAY[1..3] OF BYTE;",
                    "Bytes := USTRING_TO_ARRAY_OF_BYTE(USTRING#'🙂'); Ok := TRUE;", succeeds=False)

    def test_invalid_utf8_traps(self):
        for first, second in ((192, 128), (240, 159)):
            with self.subTest(bytes=(first, second)):
                self.native("Bytes : ARRAY[1..2] OF BYTE; Text : USTRING;",
                            f"Bytes[1] := {first}; Bytes[2] := {second}; "
                            "Text := ARRAY_OF_BYTE_TO_USTRING(Bytes); Ok := TRUE;", succeeds=False)

    def test_invalid_utf16_traps(self):
        self.native("Bytes : ARRAY[1..2] OF BYTE; Text : USTRING;",
                    "Bytes[1] := 0; Bytes[2] := 216; Text := ARRAY_OF_BYTE_TO_WSTRING(Bytes); Ok := TRUE;", succeeds=False)

    def test_odd_utf16_byte_traps(self):
        self.native("Bytes : ARRAY[1..1] OF BYTE; Text : USTRING;",
                    "Bytes[1] := 65; Text := ARRAY_OF_BYTE_TO_WSTRING(Bytes); Ok := TRUE;", succeeds=False)

    def test_decoded_results_remain_independent(self):
        self.native("Bytes : ARRAY[1..2] OF BYTE; First : USTRING; Second : USTRING;",
                    "Bytes := USTRING_TO_ARRAY_OF_BYTE(USTRING#'A'); First := ARRAY_OF_BYTE_TO_USTRING(Bytes); "
                    "Bytes := USTRING_TO_ARRAY_OF_BYTE(USTRING#'B'); Second := ARRAY_OF_BYTE_TO_USTRING(Bytes); "
                    "Ok := First = USTRING#'A' AND Second = USTRING#'B';")

    def test_out_of_range_single_byte_character_traps(self):
        self.native("Bytes : ARRAY[1..8] OF BYTE;",
                    "Bytes := STRING_TO_ARRAY_OF_BYTE(STRING#'🙂'); Ok := TRUE;", succeeds=False)

    def test_profile_gating_all_six_functions(self):
        for family in ("STRING", "WSTRING", "USTRING"):
            for body in (f"Bytes := {family}_TO_ARRAY_OF_BYTE({family}#'A');",
                         f"Text := ARRAY_OF_BYTE_TO_{family}(Bytes);"):
                for edition in ("ed2", "ed3"):
                    with self.subTest(family=family, body=body, edition=edition):
                        result = compile_source("PROGRAM P VAR Bytes : ARRAY[1..8] OF BYTE; Text : STRING; END_VAR " + body + " END_PROGRAM", "c", standard=edition)
                        self.assertFalse(result.success)
                        self.assertIn("edition4-byte-array-conversion", {d.code for d in result.diagnostics})
                        self.assertIsNone(result.output)

    def test_invalid_types_and_arity(self):
        for body, code in (
            ("Bytes := USTRING_TO_ARRAY_OF_BYTE(1);", "byte-array-conversion-type"),
            ("Text := ARRAY_OF_BYTE_TO_STRING(1);", "byte-array-conversion-type"),
            ("Text := ARRAY_OF_BYTE_TO_STRING(Bytes, 1);", "byte-array-conversion-arity"),
            ("Text := STRING_TO_ARRAY_OF_BYTE('A');", "byte-array-conversion-destination"),
            ("Bytes := WSTRING_TO_ARRAY_OF_BYTE(USTRING#'A');", "byte-array-conversion-type"),
        ):
            with self.subTest(body=body):
                result = compile_source("PROGRAM P VAR Bytes : ARRAY[1..8] OF BYTE; Text : STRING; END_VAR " + body + " END_PROGRAM", "c", standard="ed4")
                self.assertFalse(result.success)
                self.assertIn(code, {d.code for d in result.diagnostics})

    def test_wrong_element_type_and_multidimensional_arrays(self):
        for declaration in ("ARRAY[1..8] OF USINT", "ARRAY[1..2,1..2] OF BYTE"):
            with self.subTest(declaration=declaration):
                result = compile_source(f"PROGRAM P VAR Bytes : {declaration}; Text : STRING; END_VAR Text := ARRAY_OF_BYTE_TO_STRING(Bytes); END_PROGRAM", "c", standard="ed4")
                self.assertFalse(result.success)
                self.assertIn("byte-array-conversion-type", {d.code for d in result.diagnostics})


if __name__ == "__main__":
    unittest.main()
