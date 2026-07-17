import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "src" / "main.py"
SAMPLE = ROOT / "examples" / "inter.st"
FIXTURES = ROOT / "tests" / "fixtures"
AST_COVERAGE = ROOT / "tools" / "ast_coverage.py"
PARSER_DOC_AUDIT = ROOT / "tools" / "parser_doc_audit.py"
ANNEX_B = ROOT / "tmp" / "pdfs" / "annex_b.txt"


def run_stc(*args):
    return subprocess.run(
        [sys.executable, str(MAIN), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def run_stc_input(source, *args, check=True):
    return subprocess.run(
        [sys.executable, str(MAIN), "-", *args],
        cwd=ROOT,
        input=source,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


class CLITests(unittest.TestCase):
    def test_ast_output_is_json(self):
        result = run_stc(str(SAMPLE), "-g", "ast")
        ast = json.loads(result.stdout)
        self.assertEqual(ast["name"], "library")

    def test_c_generator_emits_function_signature_and_return(self):
        result = run_stc(str(SAMPLE), "-g", "c")
        self.assertIn("int16_t inter(int16_t a_1, int16_t b_1, bool test)", result.stdout)
        self.assertIn("return inter;", result.stdout)
        self.assertNotIn("INT#10", result.stdout)

    def test_rust_generator_emits_function_signature_and_return_expression(self):
        result = run_stc(str(SAMPLE), "-g", "rust")
        self.assertIn(
            "pub fn inter(mut a_1: i16, mut b_1: i16, mut test: bool) -> i16",
            result.stdout,
        )
        self.assertTrue(result.stdout.rstrip().endswith("}"))
        self.assertNotIn("INT#10", result.stdout)

    def test_generators_emit_not_equal_operator(self):
        source = """\
FUNCTION differs : BOOL
VAR_INPUT
    left_value, right_value: INT;
END_VAR
    differs := left_value <> right_value;
END_FUNCTION
"""
        c_result = run_stc_input(source, "-g", "c")
        rust_result = run_stc_input(source, "-g", "rust")
        self.assertIn("left_value != right_value", c_result.stdout)
        self.assertIn("left_value != right_value", rust_result.stdout)

    def test_ast_accepts_based_integer_literals(self):
        source = """\
FUNCTION based_literals : INT
VAR_INPUT
    value_in: INT;
END_VAR
    based_literals := 2#1010 + 16#0A;
END_FUNCTION
"""
        result = run_stc_input(source, "-g", "ast")
        ast = json.loads(result.stdout)
        text = json.dumps(ast)
        self.assertIn("binary_integer", text)
        self.assertIn("hex_integer", text)

    def test_ast_accepts_direct_variables(self):
        source = """\
FUNCTION direct_read : INT
VAR_INPUT
    fallback_value: INT;
END_VAR
    direct_read := %IW0;
END_FUNCTION
"""
        result = run_stc_input(source, "-g", "ast")
        ast = json.loads(result.stdout)
        self.assertIn("direct_variable", json.dumps(ast))

    def test_code_generation_reports_undeclared_variables(self):
        source = """\
FUNCTION bad : INT
VAR_INPUT
    a: INT;
END_VAR
    bad := a + missing_var;
END_FUNCTION
"""
        result = run_stc_input(source, "-g", "c", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("semantic error", result.stderr)
        self.assertIn("missing_var", result.stderr)

    def test_syntax_error_reports_line_column_and_caret(self):
        source = """\
FUNCTION broken : INT
VAR_INPUT
    value_in: INT;
END_VAR
    IF value_in = 1
        broken := value_in;
    END_IF;
END_FUNCTION
"""
        result = run_stc_input(source, "-g", "ast", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("syntax error", result.stderr)
        self.assertIn("line 6, column", result.stderr)
        self.assertIn("broken := value_in;", result.stderr)
        self.assertIn("^", result.stderr)

    def test_syntax_error_reports_unexpected_eof(self):
        source = """\
FUNCTION broken : INT
VAR_INPUT
    value_in: INT;
END_VAR
    broken := value_in;
"""
        result = run_stc_input(source, "-g", "ast", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("unexpected end of input", result.stderr)
        self.assertIn("line 5, column", result.stderr)

    def test_ast_output_does_not_require_semantic_validity(self):
        source = """\
FUNCTION bad : INT
VAR_INPUT
    a: INT;
END_VAR
    bad := a + missing_var;
END_FUNCTION
"""
        result = run_stc_input(source, "-g", "ast")
        ast = json.loads(result.stdout)
        self.assertEqual(ast["name"], "library")

    def test_ast_output_covers_type_declarations(self):
        result = run_stc_input("TYPE MyInt : INT; END_TYPE\n", "-g", "ast")
        ast = json.loads(result.stdout)
        text = json.dumps(ast)
        self.assertIn("data_type_declaration", text)
        self.assertIn("simple_type_declaration", text)

    def test_ast_output_covers_function_blocks(self):
        source = """\
FUNCTION_BLOCK Counter
VAR_INPUT
    x : INT;
END_VAR
    x := x + 1;
END_FUNCTION_BLOCK
"""
        result = run_stc_input(source, "-g", "ast")
        ast = json.loads(result.stdout)
        text = json.dumps(ast)
        self.assertIn("function_block_declaration", text)
        self.assertIn("function_block_body", text)

    def test_ast_output_covers_expanded_grammar_constructs(self):
        result = run_stc(str(FIXTURES / "valid_ast" / "expanded_grammar.st"), "-g", "ast")
        ast = json.loads(result.stdout)
        text = json.dumps(ast)
        self.assertEqual(ast["name"], "library")
        self.assertEqual(len(ast["children"]), 3)
        for node_name in (
            "array_initialization",
            "structure_declaration",
            "single_byte_character_string",
            "date",
            "time_of_day",
            "date_and_time",
            "duration",
            "case_statement",
            "for_statement",
            "standard_function_name",
            "program_declaration",
        ):
            with self.subTest(node_name=node_name):
                self.assertIn(node_name, text)

    def test_ast_coverage_reports_complete_placeholder_elimination(self):
        result = subprocess.run(
            [sys.executable, str(AST_COVERAGE)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("parser_methods=", result.stdout)
        self.assertIn("placeholders=0", result.stdout)

    def test_parser_doc_audit_reports_no_missing_parser_productions(self):
        if not ANNEX_B.exists():
            self.skipTest("Annex B text extraction is not available")
        result = subprocess.run(
            [sys.executable, str(PARSER_DOC_AUDIT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("missing_from_parser=0", result.stdout)

    def test_valid_ast_fixtures_emit_json_ast(self):
        fixtures = sorted((FIXTURES / "valid_ast").glob("*.st"))
        self.assertTrue(fixtures)
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                result = run_stc(str(fixture), "-g", "ast")
                ast = json.loads(result.stdout)
                self.assertEqual(ast["name"], "library")

    def test_valid_codegen_fixtures_emit_c_and_rust(self):
        fixtures = sorted((FIXTURES / "valid_codegen").glob("*.st"))
        self.assertTrue(fixtures)
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name, generator="c"):
                c_result = run_stc(str(fixture), "-g", "c")
                self.assertIn("#include", c_result.stdout)
            with self.subTest(fixture=fixture.name, generator="rust"):
                rust_result = run_stc(str(fixture), "-g", "rust")
                self.assertIn("pub fn", rust_result.stdout)

    def test_invalid_semantic_fixtures_fail_codegen(self):
        fixtures = sorted((FIXTURES / "invalid_semantic").glob("*.st"))
        self.assertTrue(fixtures)
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                result = subprocess.run(
                    [sys.executable, str(MAIN), str(fixture), "-g", "c"],
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("semantic error", result.stderr)


if __name__ == "__main__":
    unittest.main()
