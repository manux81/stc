# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Regression coverage for executable programs and function blocks."""

import unittest

from stc.compiler import compile_source


SOURCE = """
FUNCTION_BLOCK Counter
VAR_INPUT
    set_value : BOOL;
END_VAR
VAR_OUTPUT
    value : INT;
END_VAR
VAR_IN_OUT
    total : INT;
END_VAR
VAR
    count : INT;
END_VAR
IF set_value THEN
    count := count + 1;
END_IF;
value := count;
total := total + count;
END_FUNCTION_BLOCK

PROGRAM Main
VAR_OUTPUT
    result : INT;
END_VAR
FOR result := 1 TO 3 DO
    EXIT;
END_FOR;
END_PROGRAM
"""


class PouCodegenTests(unittest.TestCase):
    def test_c_backend_emits_program_fb_and_loop_control(self):
        result = compile_source(SOURCE, "c", check_semantics=False)
        self.assertTrue(result.success)
        output = result.output
        self.assertIn("typedef struct Counter", output)
        self.assertIn("void Counter_step(Counter *self, int16_t *total)", output)
        self.assertIn("void Main_run(Main *self)", output)
        self.assertIn("break;", output)

    def test_rust_backend_emits_program_fb_and_loop_control(self):
        result = compile_source(SOURCE, "rust", check_semantics=False)
        self.assertTrue(result.success)
        output = result.output
        self.assertIn("pub struct Counter", output)
        self.assertIn("pub fn step(&mut self, total: &mut i16)", output)
        self.assertIn("pub fn run(&mut self)", output)
        self.assertIn("break;", output)
