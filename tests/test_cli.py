import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "src" / "main.py"
SAMPLE = ROOT / "examples" / "inter.st"
AST_COVERAGE = ROOT / "tools" / "ast_coverage.py"


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

    def test_ast_coverage_reports_placeholders(self):
        result = subprocess.run(
            [sys.executable, str(AST_COVERAGE)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("parser_methods=", result.stdout)
        self.assertIn("placeholders=", result.stdout)


if __name__ == "__main__":
    unittest.main()
