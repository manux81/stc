"""Parser, validation, rendering and compatibility tests for .gen backends."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from stc.codegen.common.templates.engine import GeneratorEngine
from stc.codegen.common.ir import Assignment
from stc.codegen.common.templates.loader import GeneratorError, bundled_generator, load_generator
from stc.codegen.common.templates.schema import generator_help
from stc.codegen.common.templates.tools import create_generator_skeleton
from stc.compiler import compile_source


class DataDrivenGeneratorTests(unittest.TestCase):
    def test_bundled_c_generator_is_complete(self):
        bundle = load_generator(bundled_generator("c"))
        self.assertEqual(bundle.coverage, 100.0)
        self.assertEqual(bundle.coverage_for_phase(2), 100.0)
        self.assertEqual(bundle.coverage_for_phase(3), 100.0)
        self.assertEqual(bundle.coverage_for_phase(4), 100.0)
        self.assertEqual(bundle.full_coverage, 100.0)
        self.assertTrue(bundle.is_complete)
        self.assertEqual(GeneratorEngine(bundle).map("type", "DINT"), "int32_t")

    def test_bundled_rust_generator_is_complete(self):
        bundle = load_generator(bundled_generator("rust"))
        self.assertEqual(bundle.coverage, 100.0)
        self.assertEqual(bundle.coverage_for_phase(2), 100.0)
        self.assertEqual(bundle.coverage_for_phase(3), 100.0)
        self.assertEqual(bundle.coverage_for_phase(4), 100.0)
        self.assertEqual(bundle.full_coverage, 100.0)
        self.assertTrue(bundle.is_complete)
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

    def test_phase_three_dispatch_renders_without_target_branches(self):
        engine = GeneratorEngine(load_generator(bundled_generator("c")))
        call = engine.render(
            "virtual_call", receiver="device", method="Reset",
            static_type="Counter", vptr="__vptr", arguments="", extra_arguments="",
        )
        self.assertIn("Counter__vtable", call)
        self.assertIn("->Reset((void *)&(device))", call)
        this_call = engine.render(
            "virtual_call_this", receiver="self", method="Reset",
            static_type="Counter", vptr="__vptr", arguments="", extra_arguments="",
        )
        self.assertIn("(self->__vptr)", this_call)
        interface_call = engine.render(
            "virtual_call_interface", receiver="handle", method="Reset",
            static_type="IResettable", vptr="", arguments="", extra_arguments="",
        )
        self.assertIn("(handle).vtable->Reset((handle).instance)", interface_call)
        getter = engine.render(
            "property_get_class", receiver="item", method="__property_get_Value",
            owner="Counter", arguments="", extra_arguments="", base_path="",
        )
        self.assertIn("Counter____property_get_Value((void *)&(item))", getter)

    def test_phase_three_layout_uses_backend_templates(self):
        engine = GeneratorEngine(load_generator(bundled_generator("c")))
        fields = engine.render(
            "class_fields",
            items=({"type": "int16_t", "name": "Count"}, {"type": "bool", "name": "Flag"}),
        )
        self.assertIn("int16_t Count;", fields)
        dispatch = engine.render(
            "dispatch_entry", name="Value", implementation="Derived__Value", is_null=""
        )
        self.assertIn(".Value = Derived__Value,", dispatch)
        null_dispatch = engine.render("dispatch_entry_null", name="Value")
        self.assertIn(".Value = NULL,", null_dispatch)
        rust_engine = GeneratorEngine(load_generator(bundled_generator("rust")))
        rust_fields = rust_engine.render(
            "class_fields", items=({"type": "i16", "name": "Count"},)
        )
        self.assertIn("pub Count: i16,", rust_fields)
        adapter = rust_engine.render(
            "adapter_entry", **{"class": "Counter", "interface": "ICounter"},
            name="Reset", implementation="", parameters="", arguments="", return_type="()",
        )
        self.assertIn("(&mut *(instance as *mut Counter)).Reset()", adapter)

    def test_phase_four_sfc_renders_deterministically(self):
        engine = GeneratorEngine(load_generator(bundled_generator("c")))
        fire = engine.render(
            "sfc_fire", fire="__sfc_0_fire_0", sources="self->__sfc_idle_active",
            condition="start", gate="", indent="    ",
        )
        self.assertIn("bool __sfc_0_fire_0", fire)
        transition = engine.render(
            "sfc_transition", fire="__sfc_0_fire_0", sources="", targets="",
            condition="start", priority=0,
            decl=fire, body="    self->__sfc_idle_active = false;\n", indent="    ",
        )
        self.assertIn("if (__sfc_0_fire_0)", transition)
        chart = engine.render(
            "sfc_chart", body=transition, indent="", steps="", transitions="", actions=""
        )
        self.assertIn("__sfc_0_fire_0", chart)

    def test_phase_four_il_renders_per_backend_control_flow(self):
        c_engine = GeneratorEngine(load_generator(bundled_generator("c")))
        jump = c_engine.render(
            "il_jump", target_label="done", target_index=3,
            condition="", has_condition="", indent="    ",
        )
        self.assertIn("goto done;", jump)
        rust_engine = GeneratorEngine(load_generator(bundled_generator("rust")))
        rust_jump = rust_engine.render(
            "il_jump", target_label="done", target_index=3,
            condition="", has_condition="", indent="    ",
        )
        self.assertIn("__il_pc = 3;", rust_jump)
        self.assertIn("continue '__il_dispatch;", rust_jump)
        dispatch = rust_engine.render(
            "il_dispatch", instructions="    0 => {\n    }\n", labels="",
            indent="    ", acc="x",
        )
        self.assertIn("'__il_dispatch: loop", dispatch)
        self.assertIn("let mut __il_acc = x;", dispatch)

    def test_phase_four_runtime_and_preamble_come_from_backend(self):
        for name, marker in (("c", "#include <stdbool.h>"), ("rust", "stc_deref")):
            engine = GeneratorEngine(load_generator(bundled_generator(name)))
            preamble = engine.render("preamble", source="demo.st", edition="3")
            self.assertIn("demo.st", preamble)
            self.assertIn(marker, preamble)
            primitive = engine.render(
                "runtime_primitive", name="CORE", dependencies="",
                declaration="", implementation="/* core */",
            )
            self.assertIn("/* core */", primitive)

    def test_based_literals_use_backend_prefix_mapping(self):
        c_engine = GeneratorEngine(load_generator(bundled_generator("c")))
        self.assertEqual(c_engine.map("based_prefix", "2"), "")
        rust_engine = GeneratorEngine(load_generator(bundled_generator("rust")))
        self.assertEqual(rust_engine.map("based_prefix", "2"), "0b")
        source = "FUNCTION f : INT\nVAR_INPUT x : INT; END_VAR\nLD 16#FF\nST f\nEND_FUNCTION"
        c_result = compile_source(source, "c", standard="ed2")
        rust_result = compile_source(source, "rust", standard="ed2")
        self.assertTrue(c_result.success, c_result.diagnostics)
        self.assertTrue(rust_result.success, rust_result.diagnostics)
        self.assertIn("0xFF", c_result.output)
        self.assertIn("0xFF", rust_result.output)

    def test_external_generator_customizes_phase_three_and_four(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "custom-phase34"
            shutil.copytree(bundled_generator("c"), root)
            oop = root / "oop.gen"
            oop.write_text(
                oop.read_text(encoding="utf-8").replace(
                    "static const {name}__vtable {name}__dispatch",
                    "static const {name}__vtable {name}__dispatch /* external-vtable */",
                ),
                encoding="utf-8",
            )
            sfc = root / "sfc.gen"
            sfc.write_text(
                sfc.read_text(encoding="utf-8").replace(
                    "{indent}bool {fire}", "{indent}bool {fire} /* external-sfc */"
                ),
                encoding="utf-8",
            )
            source = """\
CLASS Counter
VAR Count : INT; END_VAR
METHOD PUBLIC Get : INT
Get := Count;
END_METHOD
END_CLASS
PROGRAM Conveyor
VAR_INPUT start : BOOL; END_VAR
VAR C : Counter; END_VAR
INITIAL_STEP Idle: END_STEP
TRANSITION FROM Idle TO Run := start; END_TRANSITION
STEP Run: END_STEP
TRANSITION FROM Run TO Idle := NOT start; END_TRANSITION
END_PROGRAM
"""
            result = compile_source(source, "custom", generator_path=root, standard="ed3")
            self.assertTrue(result.success, result.diagnostics)
            self.assertIn("/* external-vtable */", result.output)
            self.assertIn("/* external-sfc */", result.output)
            self.assertIn("Counter__dispatch", result.output)

    def test_scaffold_covers_phase_three_and_four_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = create_generator_skeleton("zig", Path(temporary) / "zig")
            oop_text = (root / "oop.gen").read_text(encoding="utf-8")
            self.assertIn("[virtual_call_this]", oop_text)
            self.assertIn("[property_set_interface]", oop_text)
            self.assertIn("[adapter_entry]", oop_text)
            sfc_text = (root / "sfc.gen").read_text(encoding="utf-8")
            self.assertIn("[sfc_transition]", sfc_text)
            self.assertIn("[sfc_action_decl]", sfc_text)
            il_text = (root / "il.gen").read_text(encoding="utf-8")
            self.assertIn("[il_dispatch]", il_text)
            self.assertIn("[il_next]", il_text)
            language_text = (root / "language.gen").read_text(encoding="utf-8")
            self.assertIn("[preamble]", language_text)
            self.assertIn("[configuration]", language_text)

    def test_new_generator_is_runnable_for_both_reference_bases(self):
        source = "FUNCTION identity : INT VAR_INPUT value : INT; END_VAR identity := value; END_FUNCTION"
        for base in ("c", "rust"):
            with self.subTest(base=base), tempfile.TemporaryDirectory() as temporary:
                root = create_generator_skeleton("custom", Path(temporary) / "custom", base=base)
                bundle = load_generator(root)
                self.assertEqual(bundle.adapter, base)
                self.assertTrue(bundle.is_complete)
                result = compile_source(source, generator_path=root)
                reference = compile_source(source, base)
                self.assertTrue(result.success, result.diagnostics)
                self.assertEqual(result.output, reference.output)
                self.assertTrue((root / f"primitives.{bundle.extension}").is_file())

    def test_external_named_type_and_scheduler_templates_are_used(self):
        source = """TYPE Small : INT; Mode : (IDLE, RUN); Point : STRUCT X : INT; END_STRUCT; END_TYPE
PROGRAM P VAR Value : Small; END_VAR Value := Value + 1; END_PROGRAM
CONFIGURATION Config
RESOURCE R ON PLC
TASK Tick(INTERVAL := T#10ms, PRIORITY := 0);
PROGRAM Instance WITH Tick : P;
END_RESOURCE
END_CONFIGURATION
"""
        for base in ("c", "rust"):
            with self.subTest(base=base), tempfile.TemporaryDirectory() as temporary:
                root = create_generator_skeleton("custom", Path(temporary) / "custom", base=base)
                comment = "/* customized */" if base == "c" else "// customized"
                for filename, section in (("types.gen", "type_alias"), ("types.gen", "enum_type"),
                                          ("types.gen", "structure_type"), ("language.gen", "scheduler_fire")):
                    path = root / filename
                    text = path.read_text(encoding="utf-8")
                    marker = f"[{section}]\ntemplate = \""
                    self.assertIn(marker, text)
                    path.write_text(text.replace(marker, marker + comment + "\\n", 1), encoding="utf-8")
                result = compile_source(source, generator_path=root)
                self.assertTrue(result.success, result.diagnostics)
                self.assertEqual(result.output.count(comment), 4)

    def test_generator_adapter_is_explicit_and_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = create_generator_skeleton("custom", Path(temporary) / "custom", base="rust")
            path = root / "language.gen"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace('adapter = "rust"', 'adapter = "unknown"'), encoding="utf-8")
            with self.assertRaisesRegex(GeneratorError, "adapter"):
                load_generator(root)

    def test_external_declarator_and_zero_value_are_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = create_generator_skeleton("custom", Path(temporary) / "custom")
            path = root / "types.gen"
            text = path.read_text(encoding="utf-8")
            text = text.replace('template = "{type}{separator}{name}"',
                                'template = "{type}{separator}{name} /* declaration */"')
            text = text.replace('"bool" = "false"', '"bool" = "true"')
            path.write_text(text, encoding="utf-8")
            result = compile_source("FUNCTION f : INT VAR_INPUT x : INT; END_VAR f := x; END_FUNCTION", generator_path=root)
            self.assertTrue(result.success, result.diagnostics)
            self.assertIn("x /* declaration */", result.output)
            self.assertEqual(GeneratorEngine(load_generator(root)).map("zero_value", "bool"), "true")

    def test_invalid_layout_pattern_has_generator_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = create_generator_skeleton("custom", Path(temporary) / "custom")
            path = root / "types.gen"
            text = path.read_text(encoding="utf-8")
            text = text.replace('"vector" = "(?!)"', '"vector" = "["')
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(GeneratorError, "invalid layout pattern vector"):
                load_generator(root)

    def test_scaffold_preserves_existing_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "existing"
            root.mkdir()
            marker = root / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                create_generator_skeleton("custom", root)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
