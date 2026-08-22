# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""IEC 61131-3 Edition 3 object-oriented regression tests."""

import unittest

from stc.compiler import compile_source


SIMPLE_CLASS = """
CLASS Counter
VAR
    Count : INT;
END_VAR

METHOD PUBLIC Increment : INT
VAR_INPUT
    Delta : INT;
END_VAR
    Count := Count + Delta;
    Increment := Count;
END_METHOD
END_CLASS

PROGRAM Main
VAR
    C : Counter;
    Result : INT;
END_VAR
    Result := C.Increment(2);
END_PROGRAM
"""


INHERITANCE = """
CLASS BaseCounter
VAR
    Count : INT;
END_VAR

METHOD PUBLIC Value : INT
    Value := Count;
END_METHOD
END_CLASS

CLASS DerivedCounter EXTENDS BaseCounter
METHOD PUBLIC OVERRIDE Value : INT
    Value := Count + 1;
END_METHOD
END_CLASS

PROGRAM Main
VAR
    C : DerivedCounter;
    Result : INT;
END_VAR
    Result := C.Value();
END_PROGRAM
"""


INTERFACE = """
INTERFACE IResettable
METHOD Reset
END_METHOD
END_INTERFACE

CLASS Counter IMPLEMENTS IResettable
VAR
    Count : INT;
END_VAR

METHOD PUBLIC Reset
    Count := 0;
END_METHOD
END_CLASS

PROGRAM Main
VAR
    C : Counter;
    R : IResettable;
END_VAR
    R := C;
    R.Reset();
END_PROGRAM
"""


INVALID_OVERRIDE = """
CLASS Base
METHOD PUBLIC FINAL Value : INT
    Value := 1;
END_METHOD
END_CLASS

CLASS Derived EXTENDS Base
METHOD PUBLIC OVERRIDE Value : INT
    Value := 2;
END_METHOD
END_CLASS
"""


ABSTRACT_INTERFACE = """
INTERFACE IValue
METHOD Value : INT
END_METHOD
END_INTERFACE

CLASS Broken IMPLEMENTS IValue
END_CLASS
"""


class Edition3OopTests(unittest.TestCase):
    def test_class_method_codegen(self):
        result = compile_source(SIMPLE_CLASS, "c")
        self.assertTrue(result.success, result.diagnostics)
        self.assertIn("struct Counter", result.output)
        self.assertIn("Counter__Increment", result.output)
        self.assertIn("Counter__dispatch", result.output)
        self.assertIn("Counter__init(&self->C)", result.output)

    def test_inheritance_embeds_base_at_offset_zero(self):
        result = compile_source(INHERITANCE, "c")
        self.assertTrue(result.success, result.diagnostics)
        self.assertIn("BaseCounter __base;", result.output)
        self.assertIn("DerivedCounter__dispatch", result.output)
        self.assertIn(".Value = DerivedCounter__Value", result.output)
        self.assertIn("self->__base.Count", result.output)

    def test_interface_is_fat_pointer_and_has_adapter(self):
        result = compile_source(INTERFACE, "c")
        self.assertTrue(result.success, result.diagnostics)
        self.assertIn("void *instance;", result.output)
        self.assertIn("const IResettable__vtable *vtable;", result.output)
        self.assertIn("Counter__as_IResettable", result.output)
        self.assertIn("R = Counter__as_IResettable", result.output)

    def test_final_method_cannot_be_overridden(self):
        result = compile_source(INVALID_OVERRIDE, "c", generate_code=False)
        self.assertFalse(result.success)
        self.assertTrue(
            any(item.code == "override-final-method" for item in result.diagnostics)
        )

    def test_concrete_class_must_implement_interface(self):
        result = compile_source(ABSTRACT_INTERFACE, "c", generate_code=False)
        self.assertFalse(result.success)
        self.assertTrue(
            any(
                item.code == "unimplemented-interface-method"
                for item in result.diagnostics
            )
        )


if __name__ == "__main__":
    unittest.main()
