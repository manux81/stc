# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Instruction List parsing, edition gating, and shared code generation."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from stc import compile_source
from stc.compiler import normalize_standard_edition


IL_FUNCTION = """\
FUNCTION AddOne : INT
VAR_INPUT
    x : INT;
END_VAR
LD x
ADD 1
ST AddOne
END_FUNCTION
"""

IL_JUMP_FUNCTION = """\
FUNCTION Choose : BOOL
VAR_INPUT
    x : BOOL;
END_VAR
LD x
JMPC done
LD TRUE
done: ST Choose
END_FUNCTION
"""


class InstructionListTests(unittest.TestCase):
    def test_edition_alias_and_profile_diagnostics(self):
        self.assertEqual(normalize_standard_edition("iec61131-3:ed2"), 2)
        edition2 = compile_source(IL_FUNCTION, "c", standard="ed2")
        edition3 = compile_source(IL_FUNCTION, "c", standard="ed3")
        edition4 = compile_source(IL_FUNCTION, "c", standard="ed4")
        self.assertTrue(edition2.success, edition2.diagnostics)
        self.assertFalse(edition2.diagnostics)
        self.assertTrue(edition3.success, edition3.diagnostics)
        self.assertIn("edition3-deprecated-instruction-list", {item.code for item in edition3.diagnostics})
        self.assertFalse(edition4.success)
        self.assertIn("edition4-instruction-list", {item.code for item in edition4.diagnostics})

    def test_auto_detection_and_shared_lowering(self):
        c_result = compile_source(IL_FUNCTION, "c", standard="ed2")
        rust_result = compile_source(IL_FUNCTION, "rust", standard="ed2")
        self.assertTrue(c_result.success, c_result.diagnostics)
        self.assertTrue(rust_result.success, rust_result.diagnostics)
        self.assertIn("AddOne = (x + 1);", c_result.output)
        self.assertIn("AddOne = (x + 1);", rust_result.output)
        self.assertEqual(c_result.output.count("AddOne = (x + 1);"), 1)
        self.assertEqual(rust_result.output.count("AddOne = (x + 1);"), 1)

    def test_generated_il_compiles_for_both_targets(self):
        compilers = (("c", shutil.which("cc"), "generated.c"), ("rust", shutil.which("rustc"), "generated.rs"))
        with tempfile.TemporaryDirectory() as directory:
            for target, compiler, filename in compilers:
                if compiler is None:
                    continue
                result = compile_source(IL_FUNCTION, target, standard="ed2")
                self.assertTrue(result.success, result.diagnostics)
                path = Path(directory, filename)
                path.write_text(result.output, encoding="utf-8")
                output = Path(directory, f"{target}.out")
                command = (
                    [compiler, "-std=c11", "-c", str(path), "-o", str(output)]
                    if target == "c"
                    else [compiler, "--crate-type", "lib", str(path), "-o", str(output)]
                )
                completed = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_program_fields_are_qualified(self):
        source = """\
PROGRAM CounterProgram
VAR
    Count : INT;
END_VAR
LD Count
ADD 1
ST Count
END_PROGRAM
"""
        c_result = compile_source(source, "c", standard="ed2")
        rust_result = compile_source(source, "rust", standard="ed2")
        self.assertIn("self->Count = (self->Count + 1);", c_result.output)
        self.assertIn("self.Count = (self.Count + 1);", rust_result.output)

    def test_rust_lowers_il_jumps_without_runtime_panics(self):
        result = compile_source(IL_JUMP_FUNCTION, "rust", standard="ed2")
        self.assertTrue(result.success, result.diagnostics)
        self.assertIn("'__il_dispatch: loop", result.output)
        self.assertIn("continue '__il_dispatch", result.output)
        self.assertNotIn("panic!", result.output)
        compiler = shutil.which("rustc")
        if compiler is None:
            return
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "jump.rs")
            source.write_text(result.output, encoding="utf-8")
            completed = subprocess.run(
                [
                    compiler, "--crate-type", "lib", "-D", "warnings", str(source),
                    "-o", str(Path(directory, "jump.rlib")),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
