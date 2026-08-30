# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""IEC 61131-3 Edition 4 property regression tests."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from stc.compiler import compile_source


PROPERTY_SOURCE = """\
FUNCTION_BLOCK Accumulator
VAR
    _value : INT;
END_VAR
PROPERTY_GET PUBLIC Value : INT
    Value := _value;
END_PROPERTY
PROPERTY_SET PUBLIC Value : INT
    _value := Value;
END_PROPERTY
    _value := _value + 1;
END_FUNCTION_BLOCK

INTERFACE ICounter
PROPERTY_GET PUBLIC Count : INT;
END_PROPERTY
PROPERTY_SET PUBLIC Count : INT;
END_PROPERTY
END_INTERFACE

CLASS Counter IMPLEMENTS ICounter
VAR
    _count : INT;
END_VAR
PROPERTY_GET PUBLIC Count : INT
    Count := _count;
END_PROPERTY
PROPERTY_SET PUBLIC Count : INT
    _count := Count;
END_PROPERTY
END_CLASS

PROGRAM Main
VAR
    A : Accumulator;
    C : Counter;
    I : ICounter;
    Result : INT;
END_VAR
    A.Value := 10;
    Result := A.Value;
    I := C;
    I.Count := Result;
    Result := I.Count;
END_PROGRAM
"""


class Edition4PropertyTests(unittest.TestCase):
    def _assert_native_compiles(self, target, source=PROPERTY_SOURCE):
        result = compile_source(source, target, standard="ed4")
        self.assertTrue(result.success, result.diagnostics)
        compiler = shutil.which("cc" if target == "c" else "rustc")
        if compiler is None:
            return result
        with tempfile.TemporaryDirectory() as directory:
            suffix = "c" if target == "c" else "rs"
            generated = Path(directory, f"properties.{suffix}")
            generated.write_text(result.output, encoding="utf-8")
            if target == "c":
                command = [
                    compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-c", str(generated), "-o", str(Path(directory, "properties.o")),
                ]
            else:
                command = [
                    compiler, "--crate-type", "lib", "-D", "warnings",
                    str(generated), "-o", str(Path(directory, "properties.rlib")),
                ]
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
        return result

    def test_properties_generate_compilable_c_and_rust(self):
        c_result = self._assert_native_compiles("c")
        rust_result = self._assert_native_compiles("rust")

        self.assertIn("Accumulator____property_get_Value", c_result.output)
        self.assertIn("ICounter__vtable", c_result.output)
        self.assertIn(".__property_set_Count", rust_result.output)
        self.assertIn(".__property_get_Count", rust_result.output)

    def test_properties_require_edition4(self):
        result = compile_source(
            PROPERTY_SOURCE, "c", standard="ed3", generate_code=False
        )

        self.assertFalse(result.success)
        self.assertEqual(
            {diagnostic.code for diagnostic in result.diagnostics},
            {"edition4-property"},
        )

    def test_inherited_class_property_generates_for_both_targets(self):
        source = """\
CLASS Base
VAR _value : INT; END_VAR
PROPERTY_GET PUBLIC Value : INT
    Value := _value;
END_PROPERTY
PROPERTY_SET PUBLIC Value : INT
    _value := Value;
END_PROPERTY
END_CLASS
CLASS Derived EXTENDS Base
END_CLASS
PROGRAM Main
VAR Item : Derived; Result : INT; END_VAR
    Item.Value := 2;
    Result := Item.Value;
END_PROGRAM
"""
        for target in ("c", "rust"):
            with self.subTest(target=target):
                result = self._assert_native_compiles(target, source)
                if target == "rust":
                    self.assertIn(
                        "self.Item.__base.__property_set_Value(2)", result.output
                    )
                    self.assertIn(
                        "self.Item.__base.__property_get_Value()", result.output
                    )

    def test_getter_and_setter_types_must_match(self):
        source = """\
FUNCTION_BLOCK Broken
VAR Value : INT; END_VAR
PROPERTY_GET Number : INT
    Number := Value;
END_PROPERTY
PROPERTY_SET Number : REAL
    Value := Value;
END_PROPERTY
    Value := Value + 1;
END_FUNCTION_BLOCK
"""
        result = compile_source(source, "c", standard="ed4", generate_code=False)

        self.assertFalse(result.success)
        self.assertIn(
            "property-type-mismatch",
            {diagnostic.code for diagnostic in result.diagnostics},
        )

    def test_missing_accessors_are_diagnosed(self):
        read_only = """\
FUNCTION_BLOCK ReadOnly
VAR Value : INT; END_VAR
PROPERTY_GET Number : INT
    Number := Value;
END_PROPERTY
    Value := Value + 1;
END_FUNCTION_BLOCK
PROGRAM Main
VAR Item : ReadOnly; END_VAR
    Item.Number := 1;
END_PROGRAM
"""
        write_only = """\
FUNCTION_BLOCK WriteOnly
VAR Value : INT; END_VAR
PROPERTY_SET Number : INT
    Value := Number;
END_PROPERTY
    Value := Value + 1;
END_FUNCTION_BLOCK
PROGRAM Main
VAR Item : WriteOnly; Result : INT; END_VAR
    Result := Item.Number;
END_PROGRAM
"""

        read_result = compile_source(
            read_only, "c", standard="ed4", generate_code=False
        )
        write_result = compile_source(
            write_only, "c", standard="ed4", generate_code=False
        )

        self.assertIn("property-no-set", {d.code for d in read_result.diagnostics})
        self.assertIn("property-no-get", {d.code for d in write_result.diagnostics})


if __name__ == "__main__":
    unittest.main()
