# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify synthetic conversions for user-defined enumerated types."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from compiler import compile_source
from semantic_types import EnumType


ENUM_SOURCE = """\
TYPE
    MachineMode : (MODE_IDLE, MODE_RUN, MODE_ERROR);
END_TYPE

FUNCTION EvaluateMode : DINT
VAR
    Current : MachineMode;
END_VAR
Current := STRING_TO_MachineMode('MODE_RUN');
EvaluateMode := MachineMode_TO_DINT(Current) + MachineMode_TO_INT(INT_TO_MachineMode(2));
END_FUNCTION
"""


class EnumConversionTests(unittest.TestCase):
    def test_injects_all_string_and_integer_conversions_into_the_ast(self):
        result = compile_source(ENUM_SOURCE, "c", source_name="enum_conversions.st")

        self.assertTrue(result.success, result.diagnostics)
        synthetic = [node for node in result.ast["children"] if node.get("synthetic")]
        self.assertEqual(len(synthetic), 18)
        self.assertTrue(all(node.get("generated_by") == "enum-conversions" for node in synthetic))

        datatype = result.context.declared_types["machinemode"]
        self.assertIsInstance(datatype, EnumType)
        self.assertEqual(datatype.elements, ("MODE_IDLE", "MODE_RUN", "MODE_ERROR"))

        generated_names = {
            symbol.name
            for symbol in result.context.symbols.iter_symbols()
            if symbol.kind.value == "function" and symbol.declaration.get("synthetic")
        }
        self.assertIn("STRING_TO_MachineMode", generated_names)
        self.assertIn("MachineMode_TO_STRING", generated_names)
        self.assertIn("LINT_TO_MachineMode", generated_names)
        self.assertIn("MachineMode_TO_ULINT", generated_names)

    def test_generated_enum_conversions_compile_for_c_and_rust(self):
        c_compiler = shutil.which("cc")
        rust_compiler = shutil.which("rustc")
        if c_compiler is None and rust_compiler is None:
            self.skipTest("Neither a C nor a Rust compiler is installed")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            if c_compiler is not None:
                result = compile_source(ENUM_SOURCE, "c", source_name="enum_conversions.st")
                self.assertTrue(result.success, result.diagnostics)
                generated = root / "generated.c"
                generated.write_text(result.output, encoding="utf-8")
                harness = root / "harness.c"
                harness.write_text(
                    """\
#include <string.h>
#include "generated.c"
int main(void)
{
    if (INT_TO_MachineMode(2) != MODE_ERROR) return 1;
    if (MachineMode_TO_DINT(MODE_RUN) != 1) return 2;
    if (STRING_TO_MachineMode("MODE_RUN") != MODE_RUN) return 3;
    if (strcmp(MachineMode_TO_STRING(MODE_ERROR), "MachineMode#MODE_ERROR") != 0) return 4;
    return 0;
}
""",
                    encoding="utf-8",
                )
                executable = root / "enum-conversions"
                subprocess.run(
                    [c_compiler, "-std=c11", str(harness), "-lm", "-o", str(executable)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run([str(executable)], check=True)

            if rust_compiler is not None:
                result = compile_source(ENUM_SOURCE, "rust", source_name="enum_conversions.st")
                self.assertTrue(result.success, result.diagnostics)
                generated = root / "generated.rs"
                generated.write_text(result.output, encoding="utf-8")
                subprocess.run(
                    [rust_compiler, "--crate-type", "lib", "-D", "warnings", str(generated),
                     "-o", str(root / "enum_conversions.rlib")],
                    check=True,
                    capture_output=True,
                    text=True,
                )

    def test_conversion_argument_types_are_checked_normally(self):
        result = compile_source(
            """\
TYPE MachineMode : (MODE_IDLE, MODE_RUN); END_TYPE
FUNCTION InvalidConversion : MachineMode
VAR Value : INT; END_VAR
Value := 1;
InvalidConversion := STRING_TO_MachineMode(Value);
END_FUNCTION
""",
            "c",
        )

        self.assertFalse(result.success)
        self.assertIn("no-matching-overload", {diagnostic.code for diagnostic in result.diagnostics})


if __name__ == "__main__":
    unittest.main()
