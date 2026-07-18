import unittest
import json
import tempfile
from pathlib import Path

from ast_builder import AstBuilder
from compiler import CompilationResult, compile_source, parse_tree


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


if __name__ == "__main__":
    unittest.main()
