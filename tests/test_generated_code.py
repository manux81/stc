# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compile backend output with the native C and Rust compilers."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from compiler import compile_source


ROOT = Path(__file__).resolve().parents[1]
CODEGEN_FIXTURES = ROOT / "tests" / "fixtures" / "valid_codegen"


class GeneratedCodeTests(unittest.TestCase):
    def test_all_codegen_fixtures_compile_as_c11(self):
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("A C compiler is not installed")
        self._compile_fixtures("c", compiler)

    def test_all_codegen_fixtures_compile_as_rust_library(self):
        compiler = shutil.which("rustc")
        if compiler is None:
            self.skipTest("rustc is not installed")
        self._compile_fixtures("rust", compiler)

    def _compile_fixtures(self, target, compiler):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            for source_path in sorted(CODEGEN_FIXTURES.glob("*.st")):
                with self.subTest(target=target, fixture=source_path.name):
                    result = compile_source(
                        source_path.read_text(encoding="utf-8"),
                        target,
                        source_name=str(source_path),
                    )
                    self.assertTrue(result.success, result.diagnostics)
                    extension = ".c" if target == "c" else ".rs"
                    generated = temporary_root / (source_path.stem + extension)
                    generated.write_text(result.output, encoding="utf-8")
                    output = temporary_root / (source_path.stem + ".out")
                    command = (
                        [compiler, "-std=c11", "-c", str(generated), "-o", str(output)]
                        if target == "c"
                        else [
                            compiler,
                            "--crate-type", "lib",
                            "-D", "warnings",
                            str(generated),
                            "-o", str(output),
                        ]
                    )
                    subprocess.run(command, check=True, capture_output=True, text=True)

    def test_rust_emits_for_case_and_based_literals(self):
        source = """\
FUNCTION classify : INT
VAR_INPUT value : INT; END_VAR
VAR cursor : INT; END_VAR
FOR cursor := 2#1 TO 16#03 DO
    CASE value OF
        1, 2: classify := cursor;
        ELSE classify := 0;
    END_CASE;
END_FOR;
END_FUNCTION
"""
        result = compile_source(source, "rust")

        self.assertTrue(result.success, result.diagnostics)
        self.assertIn("while cursor <= 0x03", result.output)
        self.assertIn("match value", result.output)
        self.assertIn("1 | 2 =>", result.output)

    def test_c_torture_constructs_compile_and_link(self):
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("A C compiler is not installed")
        source = """\
TYPE
    Small : INT;
    Mode : (IDLE, RUN);
    Values : ARRAY[0..2] OF INT := [3(0)];
    Point : STRUCT
        X : INT;
    END_STRUCT;
END_TYPE
FUNCTION exercise : Small
VAR_INPUT
    CurrentMode : Mode;
END_VAR
VAR
    Data : Values := [1, 2, 3];
    P : Point := (X := 1);
    Text : STRING[8];
    Delay : TIME;
END_VAR
    Text := 'ok';
    Delay := T#1s;
    CASE CurrentMode OF
        IDLE: exercise := Data[0] + P.X;
        RUN: exercise := LEN(Text);
    END_CASE;
END_FUNCTION
PROGRAM MainProgram
VAR
    Result : Small;
END_VAR
    Result := exercise(Mode#IDLE);
END_PROGRAM
CONFIGURATION MainConfiguration
    RESOURCE MainResource ON PLC
        TASK MainTask(INTERVAL := T#20ms, PRIORITY := 0);
        PROGRAM MainInstance WITH MainTask : MainProgram;
    END_RESOURCE
END_CONFIGURATION
"""
        result = compile_source(source, "c")
        self.assertTrue(result.success, result.diagnostics)
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "torture.c"
            executable = Path(temporary_directory) / "torture"
            source_path.write_text(result.output, encoding="utf-8")
            subprocess.run(
                [compiler, "-std=c11", str(source_path), "-o", str(executable)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
