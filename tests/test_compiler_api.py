# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify the result-based compiler API, libraries, and native pragmas."""

import unittest
import json
import tempfile
from pathlib import Path

from stc.frontend.ast_builder import AstBuilder
from stc.compiler import CompilationResult, compile_source, parse_tree


VALID_SOURCE = """\
FUNCTION increment : INT
VAR_INPUT
    value_in: INT;
END_VAR
    increment := value_in + 1;
END_FUNCTION
"""


class CompilerApiTests(unittest.TestCase):
    def test_success_result_exposes_all_compilation_products(self):
        result = compile_source(VALID_SOURCE, "c", source_name="increment.st")

        self.assertIsInstance(result, CompilationResult)
        self.assertTrue(result.success)
        self.assertEqual(result.target, "c")
        self.assertEqual(result.source_name, "increment.st")
        self.assertIsNotNone(result.parse_tree)
        self.assertEqual(result.ast["name"], "library")
        self.assertIsNot(result.parse_tree, result.ast)
        self.assertIsNotNone(result.context)
        self.assertIsNotNone(result.source_map)
        self.assertIn("int16_t increment(int16_t value_in)", result.output)
        self.assertEqual(result.diagnostics, ())

    def test_ast_result_does_not_require_semantic_validity(self):
        source = VALID_SOURCE.replace("value_in + 1", "missing_value + 1")
        result = compile_source(source, "ast")

        self.assertTrue(result.success)
        self.assertIsNone(result.context)
        self.assertIn('"name": "library"', result.output)

    def test_semantic_failure_is_returned_with_context_and_diagnostics(self):
        source = VALID_SOURCE.replace("value_in + 1", "missing_value + 1")
        result = compile_source(source, "c", source_name="bad.st")

        self.assertFalse(result.success)
        self.assertIsNone(result.output)
        self.assertIsNotNone(result.ast)
        self.assertIsNotNone(result.context)
        self.assertIsNotNone(result.source_map)
        self.assertTrue(any(item.code == "undeclared-variable" for item in result.diagnostics))

    def test_undeclared_assignment_target_suppresses_invalid_lvalue(self):
        source = VALID_SOURCE.replace("increment :=", "missing_target :=")
        result = compile_source(source, "c", source_name="bad.st")

        self.assertFalse(result.success)
        self.assertEqual(
            [item.code for item in result.diagnostics],
            ["undeclared-variable"],
        )

    def test_syntax_failure_is_returned_instead_of_raised(self):
        result = compile_source("FUNCTION broken : INT\n", "c", source_name="broken.st")

        self.assertFalse(result.success)
        self.assertIsNotNone(result.syntax_error)
        self.assertIsNone(result.ast)
        self.assertEqual(result.diagnostics, ())

    def test_unknown_target_is_an_api_usage_error(self):
        with self.assertRaises(ValueError):
            compile_source(VALID_SOURCE, "llvm")

    def test_ast_builder_is_a_separate_injectable_stage(self):
        class RecordingBuilder(AstBuilder):
            def __init__(self):
                self.parse_tree = None

            def build(self, tree):
                self.parse_tree = tree
                return super().build(tree)

        builder = RecordingBuilder()
        result = compile_source(VALID_SOURCE, "ast", ast_builder=builder)

        self.assertTrue(result.success)
        self.assertIs(builder.parse_tree, result.parse_tree)
        self.assertIsNot(result.parse_tree, result.ast)
        self.assertEqual(result.parse_tree, result.ast)

    def test_parse_tree_can_be_inspected_without_building_an_ast(self):
        tree = parse_tree(VALID_SOURCE)

        self.assertEqual(tree["name"], "library")

    def test_selective_library_import_with_native_c_function(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            package = root / "math"
            package.mkdir()
            (package / "native_add.st").write_text(
                """FUNCTION NativeAdd : INT
VAR_INPUT lhs, rhs: INT; END_VAR
{#native c body}
NativeAdd = lhs + rhs;
{#end_native}
NativeAdd := 0;
END_FUNCTION
""",
                encoding="utf-8",
            )
            (package / "stc-library.json").write_text(
                json.dumps({
                    "schema": 1,
                    "name": "math",
                    "exports": {
                        "NativeAdd": {"source": "native_add.st"}
                    },
                }),
                encoding="utf-8",
            )

            result = compile_source(
                "",
                "c",
                check_semantics=False,
                library_paths=[str(root)],
                imports=["math:NativeAdd"],
            )

        self.assertTrue(result.success)
        self.assertEqual([item.symbol for item in result.libraries.imports], ["NativeAdd"])
        self.assertIn("NativeAdd = lhs + rhs;", result.output)

    def test_native_function_block_emits_setup_and_loop(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            package = root / "blocks"
            package.mkdir()
            (package / "Latch.st").write_text(
                """FUNCTION_BLOCK Latch
VAR_INPUT set_value: BOOL; END_VAR
VAR_OUTPUT output_value: BOOL; END_VAR
{#native c setup}
self->output_value = false;
{#end_native}
{#native c loop}
if (self->set_value) self->output_value = true;
{#end_native}
output_value := set_value;
END_FUNCTION_BLOCK
""",
                encoding="utf-8",
            )
            (package / "stc-library.json").write_text(
                json.dumps({
                    "schema": 1,
                    "name": "blocks",
                    "exports": {
                        "Latch": {"source": "Latch.st"}
                    },
                }),
                encoding="utf-8",
            )

            result = compile_source(
                "",
                "c",
                check_semantics=False,
                library_paths=[str(root)],
                imports=["blocks:Latch"],
            )

        self.assertTrue(result.success)
        self.assertIn("typedef struct Latch", result.output)
        self.assertIn("void Latch_setup(Latch *self)", result.output)
        self.assertIn("void Latch_loop(Latch *self)", result.output)
        self.assertIn("if (self->set_value) self->output_value = true;", result.output)

    def test_iec_overload_resolution_mangles_declarations_and_selected_call(self):
        source = """\
FUNCTION caller : DINT
VAR_INPUT value : DINT; END_VAR
caller := choose(value);
END_FUNCTION
FUNCTION choose : INT
VAR_INPUT value : INT; END_VAR
choose := value;
END_FUNCTION
FUNCTION choose : DINT
VAR_INPUT value : DINT; END_VAR
choose := value;
END_FUNCTION
"""

        c_result = compile_source(source, "c")
        rust_result = compile_source(source, "rust")

        self.assertTrue(c_result.success)
        self.assertIn("caller = choose__input_DINT(value);", c_result.output)
        self.assertIn("int16_t choose__input_INT(int16_t value)", c_result.output)
        self.assertIn("int32_t choose__input_DINT(int32_t value)", c_result.output)
        self.assertTrue(rust_result.success)
        self.assertIn("caller = choose__input_DINT(value);", rust_result.output)
        self.assertIn("pub fn choose__input_INT", rust_result.output)

    def test_formal_arguments_are_emitted_in_declaration_order(self):
        source = """\
FUNCTION caller : INT
VAR_INPUT x, y : INT; END_VAR
caller := subtract(second := y, first := x);
END_FUNCTION
FUNCTION subtract : INT
VAR_INPUT first, second : INT; END_VAR
subtract := first - second;
END_FUNCTION
"""
        result = compile_source(source, "c")

        self.assertTrue(result.success)
        self.assertIn("caller = subtract(x, y);", result.output)

    def test_reports_ambiguous_no_match_and_duplicate_overloads(self):
        ambiguous = """\
FUNCTION caller : INT
VAR_INPUT unused : INT; END_VAR
caller := choose(unused);
END_FUNCTION
FUNCTION choose : INT
VAR_INPUT value : INT; END_VAR
choose := value;
END_FUNCTION
FUNCTION choose : INT
VAR_IN_OUT value : INT; END_VAR
choose := value;
END_FUNCTION
"""
        no_match = """\
FUNCTION caller : INT
VAR_INPUT value : REAL; END_VAR
caller := choose(value);
END_FUNCTION
FUNCTION choose : INT
VAR_INPUT value : INT; END_VAR
choose := value;
END_FUNCTION
"""
        duplicate = """\
FUNCTION choose : INT
VAR_INPUT first : INT; END_VAR
choose := first;
END_FUNCTION
FUNCTION choose : INT
VAR_INPUT second : INT; END_VAR
choose := second;
END_FUNCTION
"""

        self.assertIn("ambiguous-overload", [d.code for d in compile_source(ambiguous, "c").diagnostics])
        self.assertIn("no-matching-overload", [d.code for d in compile_source(no_match, "c").diagnostics])
        self.assertIn("duplicate-overload", [d.code for d in compile_source(duplicate, "c").diagnostics])


if __name__ == "__main__":
    unittest.main()
