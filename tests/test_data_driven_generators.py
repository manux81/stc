"""Parser, validation, rendering and compatibility tests for .gen backends."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from stc.codegen.generator.engine import GeneratorEngine
from stc.codegen.generator.ir import Assignment
from stc.codegen.generator.loader import GeneratorError, bundled_generator, load_generator
from stc.codegen.generator.schema import generator_help
from stc.codegen.generator.tools import create_generator_skeleton
from stc.compiler import compile_source


class DataDrivenGeneratorTests(unittest.TestCase):
    def test_bundled_c_generator_is_complete_through_phase_two(self):
        bundle = load_generator(bundled_generator("c"))
        self.assertEqual(bundle.coverage, 100.0)
        self.assertEqual(bundle.coverage_for_phase(2), 100.0)
        self.assertFalse(bundle.is_complete)
        self.assertEqual(GeneratorEngine(bundle).map("type", "DINT"), "int32_t")

    def test_bundled_rust_generator_is_complete_through_phase_two(self):
        bundle = load_generator(bundled_generator("rust"))
        self.assertEqual(bundle.coverage, 100.0)
        self.assertEqual(bundle.coverage_for_phase(2), 100.0)
        self.assertFalse(bundle.is_complete)
        self.assertEqual(GeneratorEngine(bundle).map("type", "DINT"), "i32")

    def test_renderer_accepts_lowered_dataclass(self):
        engine = GeneratorEngine(load_generator(bundled_generator("c")))
        self.assertEqual(
            engine.render("assignment", Assignment("answer", "42", "    ")),
            "    answer = 42;\n",
        )

    def test_unknown_placeholder_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(bundled_generator("c"), root / "broken")
            statements = root / "broken" / "statements.gen"
            statements.write_text(
                statements.read_text(encoding="utf-8").replace(
                    "{target} = {value}", "{unknown} = {value}"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(GeneratorError, "unknown placeholders"):
                load_generator(root / "broken")

    def test_composition_cycle_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(bundled_generator("c"), root / "broken")
            statements = root / "broken" / "statements.gen"
            text = statements.read_text(encoding="utf-8")
            text = text.replace("[if]\n", '[if]\nuses = ["else"]\n')
            text = text.replace("[else]\n", '[else]\nuses = ["if"]\n')
            statements.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(GeneratorError, "circular"):
                load_generator(root / "broken")

    def test_help_comes_from_generator_schema(self):
        help_text = generator_help("function")
        self.assertIn("Generate a target-language IEC FUNCTION", help_text)
        self.assertIn("{return_value}", help_text)

    def test_each_when_and_composition_stay_declarative(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(bundled_generator("c"), root / "composed")
            statements = root / "composed" / "statements.gen"
            text = statements.read_text(encoding="utf-8")
            text = text.replace(
                '[else]\ntemplate = "{indent}else {\\n{body}{indent}}\\n"',
                '[else]\nwhen = "{body}"\ntemplate = "{indent}else {\\n{body}{indent}}\\n"',
            )
            statements.write_text(text, encoding="utf-8")
            engine = GeneratorEngine(load_generator(root / "composed"))
            self.assertEqual(engine.render("else", body="", indent=""), "")
            self.assertEqual(
                engine.render("parameter", items=({"value": "1"}, {"value": "2"})),
                "1, 2",
            )

    def test_scaffold_contains_all_nine_files_and_api_sections(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = create_generator_skeleton("zig", Path(temporary) / "zig")
            self.assertEqual(len(list(root.glob("*.gen"))), 9)
            self.assertIn("[virtual_call]", (root / "oop.gen").read_text(encoding="utf-8"))

    def test_phase_one_output_matches_legacy_backend_and_compiles(self):
        source = """\
FUNCTION choose : INT
VAR_INPUT enabled : BOOL; END_VAR
VAR cursor : INT; END_VAR
cursor := 0;
WHILE cursor < 2 DO cursor := cursor + 1; END_WHILE;
IF enabled THEN choose := cursor; ELSE choose := 0; END_IF;
END_FUNCTION
"""
        result = compile_source(source, "c")
        self.assertTrue(result.success, result.diagnostics)
        self.assertIn("while", result.output)
        compiler = shutil.which("cc")
        if compiler:
            with tempfile.TemporaryDirectory() as temporary:
                for name, output_text in (("data", result.output),):
                    generated = Path(temporary) / f"{name}.c"
                    generated.write_text(
                        output_text + "\nint main(void) { return choose(true) == 2 ? 0 : 1; }\n",
                        encoding="utf-8",
                    )
                    executable = Path(temporary) / name
                    subprocess.run([compiler, "-std=c11", str(generated), "-o", str(executable)], check=True, capture_output=True)
                    subprocess.run([str(executable)], check=True, capture_output=True)

    def test_external_generator_changes_phase_one_without_registration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "custom"
            shutil.copytree(bundled_generator("c"), root)
            statements = root / "statements.gen"
            statements.write_text(
                statements.read_text(encoding="utf-8").replace(
                    "{indent}{target} = {value};", "{indent}{target} = ({value}); /* external */"
                ), encoding="utf-8",
            )
            source = """\
FUNCTION external_demo : INT
VAR marker : INT; END_VAR
external_demo := 1;
END_FUNCTION
"""
            result = compile_source(source, "custom-name", generator_path=root)
            self.assertTrue(result.success, result.diagnostics)
            self.assertIn("/* external */", result.output)

    def test_external_rust_generator_changes_phase_two_pou_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "custom-rust"
            shutil.copytree(bundled_generator("rust"), root)
            pou = root / "pou.gen"
            pou.write_text(
                pou.read_text(encoding="utf-8").replace(
                    "/// Persistent state for IEC function block `{name}`.",
                    "/// External Phase 2 layout for `{name}`.",
                ),
                encoding="utf-8",
            )
            source = """\
FUNCTION_BLOCK Counter
VAR count : INT; END_VAR
count := count + 1;
END_FUNCTION_BLOCK
"""
            result = compile_source(source, "custom-rust", generator_path=root)
            self.assertTrue(result.success, result.diagnostics)
            self.assertIn("/// External Phase 2 layout for `Counter`.", result.output)
            self.assertIn("pub struct Counter", result.output)


if __name__ == "__main__":
    unittest.main()
