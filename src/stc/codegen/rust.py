# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate Rust code from the supported Structured Text AST subset."""

import re
import shutil
import subprocess

from .visitor import NodeVisitor
from .sfc import charts as sfc_charts, field as sfc_field, state_declarations as sfc_state_declarations
from ..runtime.loader import render_primitives
from ..semantic.types import EnumType


class RustCodeGenerator(NodeVisitor):
    il_target = "rust"
    def _il_descendants(self, node, name):
        if not isinstance(node, dict):
            return []
        found = [node] if node.get("name") == name else []
        for child in node.get("children", []):
            found.extend(self._il_descendants(child, name))
        return found

    def _il_token(self, node):
        tokens = self._il_descendants(node, "token")
        return next((str(item.get("value", "")).upper() for item in tokens if item.get("value") != "\u2029"), "")

    def _il_operand_node(self, operation):
        operands = self._il_descendants(operation, "il_operand")
        if not operands:
            return None
        children = [item for item in operands[0].get("children", []) if isinstance(item, dict)]
        return children[0] if children else None

    def _il_render_operand(self, operation):
        operand = self._il_operand_node(operation)
        if operand is None:
            return None
        # The grammar cannot distinguish an unqualified enumeration element
        # from a symbolic variable. Prefer a declared/current-instance name;
        # qualified enum values remain represented by their dedicated node.
        if operand.get("name") == "enumerated_value":
            operand = {"name": "variable_name", "value": operand.get("value", ""), "children": []}
        return self.render(operand)

    def _il_boolean_not(self, expression):
        return f"!({expression})"

    def _il_assignment(self, target, expression):
        return f"{target} = {expression};"

    def _il_emit_line(self, statement):
        self.text += f"{self.indent}{statement}\n"

    def _visit_instruction_list_with_jumps(self, node, instructions):
        """Lower IL control flow to a Rust program-counter loop.

        Rust deliberately has no ``goto``.  A small dispatcher preserves IL
        label/jump semantics without introducing a second backend module or a
        runtime panic.  IEC requires a consistent current-result type along a
        control-flow network, so the first LD operand also gives Rust the
        accumulator type.
        """
        labels = {}
        operations = []
        initial = None
        for index, instruction in enumerate(instructions):
            for label in (
                item for item in instruction.get("children", [])
                if isinstance(item, dict) and item.get("name") == "label"
            ):
                labels[str(label.get("value", "")).casefold()] = index
            operation = next(
                (child for child in instruction.get("children", [])
                 if isinstance(child, dict) and child.get("name") not in {"label", "token"}),
                None,
            )
            operations.append(operation)
            if operation is not None and self._il_token(operation) in {"LD", "LDN"}:
                initial = initial or self._il_render_operand(operation)

        # A jump network without an LD is invalid IL.  Default keeps codegen
        # total while allowing the semantic diagnostics to remain authoritative.
        initial = initial or "Default::default()"
        binary = {
            "AND": "&", "&": "&", "OR": "|", "XOR": "^",
            "ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%",
            "GT": ">", "GE": ">=", "EQ": "==", "LT": "<", "LE": "<=", "NE": "!=",
        }
        stored_function_result = False

        self._il_emit_line("let mut __il_pc: usize = 0;")
        self._il_emit_line(f"let mut __il_acc = {initial};")
        self._il_emit_line("'__il_dispatch: loop {")
        self.indent_inc()
        self._il_emit_line("match __il_pc {")
        self.indent_inc()
        for index, operation in enumerate(operations):
            self._il_emit_line(f"{index} => {{")
            self.indent_inc()
            opcode = self._il_token(operation) if operation is not None else ""
            operand = self._il_render_operand(operation) if operation is not None else None
            advances = True

            if opcode in {"LD", "LDN"} and operand is not None:
                value = self._il_boolean_not(operand) if opcode == "LDN" else operand
                self._il_emit_line(f"__il_acc = {value};")
            elif opcode in {"ST", "STN"} and operand is not None:
                value = self._il_boolean_not("__il_acc") if opcode == "STN" else "__il_acc"
                self._il_emit_line(self._il_assignment(operand, value))
                stored_function_result |= bool(self.current_function) and operand.casefold() == self.current_function.casefold()
            elif opcode == "NOT":
                self._il_emit_line("__il_acc = !(__il_acc);")
            elif opcode in {"ANDN", "AN", "ORN", "XORN"} and operand is not None:
                operator = {"ANDN": "&", "AN": "&", "ORN": "|", "XORN": "^"}[opcode]
                self._il_emit_line(f"__il_acc = __il_acc {operator} !({operand});")
            elif opcode in binary and operand is not None:
                self._il_emit_line(f"__il_acc = __il_acc {binary[opcode]} {operand};")
            elif opcode in {"S", "S1", "R", "R1"} and operand is not None:
                value = "true" if opcode in {"S", "S1"} else "false"
                self._il_emit_line(f"if __il_acc {{ {self._il_assignment(operand, value)} }}")
            elif opcode in {"JMP", "JMPC", "JMPCN"}:
                targets = self._il_descendants(operation, "label")
                destination = str(targets[0].get("value", "")).casefold() if targets else ""
                target = labels.get(destination, len(operations))
                if opcode == "JMP":
                    self._il_emit_line(f"__il_pc = {target};")
                    self._il_emit_line("continue '__il_dispatch;")
                    advances = False
                else:
                    condition = "__il_acc" if opcode == "JMPC" else "!(__il_acc)"
                    self._il_emit_line(f"if {condition} {{")
                    self.indent_inc()
                    self._il_emit_line(f"__il_pc = {target};")
                    self._il_emit_line("continue '__il_dispatch;")
                    self.indent_dec()
                    self._il_emit_line("}")
            elif opcode in {"RET", "RETC", "RETCN"}:
                statement = f"return __il_acc;" if self.current_function else "return;"
                if opcode == "RET":
                    self._il_emit_line(statement)
                    advances = False
                else:
                    condition = "__il_acc" if opcode == "RETC" else "!(__il_acc)"
                    self._il_emit_line(f"if {condition} {{ {statement} }}")
            elif operation is not None:
                function_names = self._il_descendants(operation, "il_function_name")
                if function_names:
                    name = function_names[0].get("value", "")
                    arguments = ["__il_acc"]
                    for item in self._il_descendants(operation, "il_operand"):
                        child = next((c for c in item.get("children", []) if isinstance(c, dict)), None)
                        if child is not None:
                            if child.get("name") == "enumerated_value":
                                child = {"name": "variable_name", "value": child.get("value", ""), "children": []}
                            arguments.append(self.render(child))
                    self._il_emit_line(f"__il_acc = {name}({', '.join(arguments)});")

            if advances:
                self._il_emit_line(f"__il_pc = {index + 1};")
            self.indent_dec()
            self._il_emit_line("}")
        self._il_emit_line("_ => break '__il_dispatch,")
        self.indent_dec()
        self._il_emit_line("}")
        self.indent_dec()
        self._il_emit_line("}")
        if self.current_function and not stored_function_result:
            target = self.render({"name": "variable_name", "value": self.current_function, "children": []})
            self._il_emit_line(self._il_assignment(target, "__il_acc"))

    def visit_instruction_list(self, node):
        instructions = self._il_descendants(node, "il_instruction")
        if any(
            self._il_token(operation) in {"JMP", "JMPC", "JMPCN"}
            for instruction in instructions
            for operation in instruction.get("children", [])
            if isinstance(operation, dict)
        ):
            self._visit_instruction_list_with_jumps(node, instructions)
            return
        accumulator = None
        terminated = False
        stored_function_result = False
        binary = {
            "AND": "&", "&": "&", "OR": "|", "XOR": "^",
            "ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%",
            "GT": ">", "GE": ">=", "EQ": "==", "LT": "<", "LE": "<=", "NE": "!=",
        }

        for instruction in instructions:
            labels = [item for item in instruction.get("children", []) if isinstance(item, dict) and item.get("name") == "label"]
            if labels:
                label = labels[0].get("value", "")
                if self.il_target == "c":
                    self._il_emit_line(f"{label}: ;")
                else:
                    self._il_emit_line(f"// IL label {label}")

            operation = next(
                (child for child in instruction.get("children", []) if isinstance(child, dict) and child.get("name") != "label" and child.get("name") != "token"),
                None,
            )
            if operation is None:
                continue
            opcode = self._il_token(operation)
            operand = self._il_render_operand(operation)

            if opcode in {"LD", "LDN"} and operand is not None:
                accumulator = self._il_boolean_not(operand) if opcode == "LDN" else operand
            elif opcode in {"ST", "STN"} and operand is not None and accumulator is not None:
                value = self._il_boolean_not(accumulator) if opcode == "STN" else accumulator
                self._il_emit_line(self._il_assignment(operand, value))
                stored_function_result = bool(self.current_function) and operand.casefold() == self.current_function.casefold()
            elif opcode == "NOT" and accumulator is not None:
                accumulator = self._il_boolean_not(accumulator)
            elif opcode in {"ANDN", "AN", "ORN", "XORN"} and accumulator is not None and operand is not None:
                base = {"ANDN": "&", "AN": "&", "ORN": "|", "XORN": "^"}[opcode]
                accumulator = f"({accumulator} {base} {self._il_boolean_not(operand)})"
            elif opcode in binary and accumulator is not None and operand is not None:
                accumulator = f"({accumulator} {binary[opcode]} {operand})"
            elif opcode in {"S", "S1", "R", "R1"} and accumulator is not None and operand is not None:
                value = "true" if opcode in {"S", "S1"} else "false"
                self._il_emit_line(f"if ({accumulator}) {{ {self._il_assignment(operand, value)} }}")
            elif opcode in {"RET", "RETC", "RETCN"}:
                condition = None
                if opcode == "RETC" and accumulator is not None:
                    condition = accumulator
                elif opcode == "RETCN" and accumulator is not None:
                    condition = self._il_boolean_not(accumulator)
                if self.current_function and accumulator is not None:
                    statement = f"return {accumulator};"
                else:
                    statement = "return;"
                self._il_emit_line(statement if condition is None else f"if ({condition}) {{ {statement} }}")
                terminated = opcode == "RET"
            else:
                function_names = self._il_descendants(operation, "il_function_name")
                if function_names:
                    name = function_names[0].get("value", "")
                    arguments = [accumulator] if accumulator is not None else []
                    for item in self._il_descendants(operation, "il_operand"):
                        child = next((c for c in item.get("children", []) if isinstance(c, dict)), None)
                        if child is not None:
                            if child.get("name") == "enumerated_value":
                                child = {"name": "variable_name", "value": child.get("value", ""), "children": []}
                            arguments.append(self.render(child))
                    accumulator = f"{name}({', '.join(arguments)})"

        # IEC functions return the current result when physical end-of-body is
        # reached. Assigning the generated return variable preserves the normal
        # backend epilogue and works for both C and Rust.
        if self.current_function and accumulator is not None and not terminated and not stored_function_result:
            target = self.render({"name": "variable_name", "value": self.current_function, "children": []})
            self._il_emit_line(self._il_assignment(target, accumulator))

    def __init__(self, context=None, source_name="<stdin>", native_implementations=None):
        self.context = context
        self.source_name = source_name
        self.native_implementations = native_implementations or {}
        display_source = str(source_name).replace("\n", " ").replace("\r", " ")
        standard_edition = context.standard_edition if context is not None else 3
        self.text = (
            "//! Portable Rust generated by STC.\n"
            f"//! Source: {display_source}.\n"
            f"//! IEC profile: IEC 61131-3 Edition {standard_edition}.\n"
            "//!\n"
            "//! This module contains the translated IEC program and its runtime glue.\n"
            "//! Regenerate this file from Structured Text instead of editing it directly.\n\n"
            "#![allow(non_snake_case, non_camel_case_types, non_upper_case_globals)]\n"
            "#![allow(unused_assignments, unused_mut, unused_variables, unused_unsafe)]\n\n"
        )
        self.indent = ""
        self.current_function = None
        self.current_return_type = None
        self.current_instance = False
        self.current_instance_fields = set()
        self.current_instance_field_paths = {}
        self.current_reference_params = set()
        self.current_synthetic_enum = None

    def formatted_text(self):
        """Return canonical Rust when rustfmt is installed, or readable raw output."""
        source = self.text.rstrip() + "\n"
        rustfmt = shutil.which("rustfmt")
        if rustfmt is None:
            return source
        try:
            result = subprocess.run(
                [rustfmt, "--emit", "stdout", "--edition", "2021"],
                input=source,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return source
        return result.stdout if result.returncode == 0 else source

    def _emit_section(self, title):
        self.text += f"// --- {title} {'-' * max(1, 68 - len(title))}\n\n"

    def render(self, node):
        previous = self.text
        self.text = ""
        self.visit(node)
        rendered = self.text
        self.text = previous
        return rendered

    def iecType2Rust(self, typein):
        conv = {
            "SINT": "i8", "INT": "i16", "DINT": "i32", "LINT": "i64",
            "USINT": "u8", "UINT": "u16", "UDINT": "u32", "ULINT": "u64",
            "REAL": "f32", "LREAL": "f64",
            "BOOL": "bool", "BYTE": "u8", "WORD": "u16", "DWORD": "u32", "LWORD": "u64",
            "CHAR": "u8", "WCHAR": "u16", "UCHAR": "u32",
            "STRING": "&'static str", "WSTRING": "&'static str", "USTRING": "&'static str",
            "TIME": "i64", "LTIME": "i64", "DATE": "i64", "LDATE": "i64",
            "TOD": "i64", "LTOD": "i64", "TIME_OF_DAY": "i64", "DT": "i64", "LDT": "i64",
        }
        return conv.get(typein.upper(), typein)

    def rust_type_for_node(self, node):
        if self.context is None:
            return None
        datatype = self.context.type_of(node)
        if datatype is None or datatype.name in {"<unknown>", "<error>"}:
            return None
        return self.iecType2Rust(datatype.name)

    def common_numeric_type(self, nodes):
        ranks = {
            "i8": (1, True), "u8": (1, False),
            "i16": (2, True), "u16": (2, False),
            "i32": (3, True), "u32": (3, False),
            "i64": (4, True), "u64": (4, False),
            "f32": (5, True), "f64": (6, True),
        }
        types = [self.rust_type_for_node(node) for node in nodes]
        types = [item for item in types if item in ranks]
        if not types:
            return None
        # IEC arithmetic promotes to the widest operand. At equal widths a
        # signed type is used, matching the frontend's assignment semantics.
        return max(types, key=lambda item: ranks[item])

    def render_as(self, node, target_type):
        rendered = self.render(node)
        source_type = self.rust_type_for_node(node)
        if target_type is not None and source_type is not None and source_type != target_type:
            return f"({rendered}) as {target_type}"
        return rendered

    def indent_inc(self):
        self.indent += "    "

    def indent_dec(self):
        self.indent = self.indent[:-4]

    def extract_type(self, node):
        if isinstance(node, str):
            return self.iecType2Rust(node)
        if isinstance(node, dict):
            if node.get("name", "").endswith("_type_name") and node.get("value"):
                return self.iecType2Rust(node["value"])
            for child in node.get("children", []):
                found = self.extract_type(child)
                if found:
                    return found
        return None

    def declaration_type(self, node, fallback="i16"):
        found = self.extract_type(node)
        if found:
            return found
        if self._first_named(node, "single_byte_string_spec") is not None:
            return "&'static str"
        if self._first_named(node, "double_byte_string_spec") is not None:
            return "Vec<u16>"
        return fallback

    def _array_dimensions(self, specification):
        dimensions = []
        for range_node in self._named_nodes(specification, "subrange"):
            bounds = self._named_nodes(range_node, "signed_integer")
            if len(bounds) == 2:
                lower, upper = self.render(bounds[0]), self.render(bounds[1])
                dimensions.append(f"({upper} - ({lower}) + 1) as usize")
        return dimensions

    def _declaration_type(self, node):
        if self._first_named(node, "single_byte_string_spec") is not None:
            return "&'static str"
        if self._first_named(node, "double_byte_string_spec") is not None:
            return "Vec<u16>"
        array = self._first_named(node, "array_specification")
        if array is not None:
            named = self._first_named(array, "array_type_name")
            if named is not None:
                return named["value"]
            result = self.declaration_type(array)
            for size in reversed(self._array_dimensions(array)):
                result = f"[{result}; {size}]"
            return result
        for kind in ("structure_type_name", "function_block_type_name"):
            named = self._first_named(node, kind)
            if named is not None:
                value = named.get("value")
                if value:
                    return self.iecType2Rust(value)
                leaf = next((item.get("value") for item in self._named_nodes(named, "derived_function_block_name") if item.get("value")), None)
                if leaf:
                    return leaf
        return self.declaration_type(node)

    def zero_value(self, rust_type):
        if rust_type == "bool":
            return "false"
        if rust_type in ("f32", "f64"):
            return "0.0"
        if rust_type in {"String", "&'static str"}:
            return '""'
        if rust_type.startswith("Vec<"):
            return "Vec::new()"
        if rust_type.startswith("["):
            return "Default::default()"
        if self.context is not None:
            datatype = self.context.declared_types.get(rust_type.casefold())
            if isinstance(datatype, EnumType) and datatype.elements:
                return f"{rust_type}::{datatype.elements[0]}"
        if rust_type in {"i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64"}:
            return "0"
        return "Default::default()"

    def visit_enumerated_value(self, node):
        value = str(node.get("value", ""))
        if self.current_synthetic_enum:
            self.text += f"{self.current_synthetic_enum}::{value}"
        else:
            self.text += value

    def visit_qualified_enumerated_value(self, node):
        enum_type = next(
            (item.get("value") for item in self._named_nodes(node, "enumerated_type_name") if item.get("value")),
            None,
        )
        value = next(
            (item.get("value") for item in self._named_nodes(node, "enumerated_value") if item.get("value")),
            None,
        )
        if enum_type and value:
            self.text += f"{enum_type}::{value}"
        elif value:
            self.text += value

    def collect_var_decls(self, node):
        declarations = []
        if not isinstance(node, dict):
            return declarations
        declaration_nodes = {
            "var1_init_decl", "var1_declaration", "array_var_init_decl",
            "array_var_declaration", "structured_var_init_decl", "structured_var_declaration",
            "string_var_declaration", "fb_name_decl", "located_var_decl",
        }
        if node.get("name") in declaration_nodes:
            names = []
            for child in self._named_nodes(node, "variable_name"):
                if child.get("value") and child["value"] not in names:
                    names.append(child["value"])
            if not names:
                for child in self._named_nodes(node, "fb_name"):
                    if child.get("value") and child["value"] not in names:
                        names.append(child["value"])
            var_type = self._declaration_type(node)
            return [(var_type, name) for name in names]
        for child in node.get("children", []):
            declarations.extend(self.collect_var_decls(child))
        return declarations

    def _section_declarations(self, node):
        declarations = []
        for section in ("input_declarations", "output_declarations", "input_output_declarations",
                        "var_declarations", "retentive_var_declarations", "non_retentive_var_decls",
                        "temp_var_decls", "function_var_decls"):
            declarations.extend(self.collect_sections(node, section))
        return declarations

    def _persistent_declarations(self, node):
        declarations = []
        for section in ("input_declarations", "output_declarations", "input_output_declarations",
                        "var_declarations", "retentive_var_declarations", "non_retentive_var_decls"):
            declarations.extend(self.collect_sections(node, section))
        return declarations

    def _retained_declarations(self, node):
        return self.collect_sections(node, "retentive_var_declarations")

    def _declaration_initializers(self, node):
        result = {}
        for section_name in ("input_declarations", "output_declarations", "input_output_declarations",
                             "var_declarations", "retentive_var_declarations", "non_retentive_var_decls"):
            for section in self._named_nodes(node, section_name):
                for declaration in self._iter_named_set(section, {"var1_init_decl", "string_var_declaration"}):
                    initializer = self._first_named(declaration, "constant")
                    if initializer is None:
                        continue
                    value = self.render(initializer)
                    for _, field in self.collect_var_decls(declaration):
                        result[field.casefold()] = value
        return result

    @staticmethod
    def _unique_declarations(declarations):
        result, seen = [], set()
        for declaration in declarations:
            key = declaration[1].casefold()
            if key not in seen:
                seen.add(key)
                result.append(declaration)
        return result

    def _emit_state_type(self, name, declarations, retained, initializers, entry_name, body_name, node):
        declarations = self._unique_declarations(
            declarations + sfc_state_declarations(node, "bool", "i64")
        )
        for chart in sfc_charts(node):
            for step in chart["steps"]:
                if step["initial"]:
                    initializers[sfc_field(step["name"], "active").casefold()] = "true"
        retained_names = {field.casefold() for _, field in retained}
        kind = "function block" if entry_name == "step" else "program"
        self.text += f"/// Persistent state for IEC {kind} `{name}`.\n"
        self.text += "#[allow(non_camel_case_types, non_snake_case)]\n"
        self.text += "pub struct " + name + " {\n"
        self.indent_inc()
        for var_type, var_name in declarations:
            self.text += f"{self.indent}pub {var_name}: {var_type},\n"
        self.indent_dec()
        self.text += "}\n\nimpl Default for " + name + " {\n    fn default() -> Self {\n        Self {\n"
        for var_type, field in declarations:
            value = initializers.get(field.casefold(), self.zero_value(var_type))
            self.text += f"            {field}: {value},\n"
        self.text += "        }\n    }\n}\n\nimpl " + name + " {\n"
        self.text += "    /// Reset all state, including retained variables.\n"
        self.text += "    pub fn cold_init(&mut self) {\n        *self = Self::default();\n    }\n\n"
        self.text += "    /// Reset non-retained state while preserving retained variables.\n"
        self.text += "    pub fn warm_init(&mut self) {\n"
        for var_type, field in declarations:
            if field.casefold() not in retained_names:
                value = initializers.get(field.casefold(), self.zero_value(var_type))
                self.text += f"        self.{field} = {value};\n"
        self.text += "    }\n\n"
        inouts = self.collect_sections(node, "input_output_declarations")
        params = ", " + ", ".join(f"{field}: &mut {var_type}" for var_type, field in inouts) if inouts else ""
        operation = "Execute one invocation" if entry_name == "step" else "Execute one program cycle"
        self.text += f"    /// {operation} of `{name}`.\n"
        self.text += f"    pub fn {entry_name}(&mut self{params}) {{\n"
        self.indent = "        "
        old_instance, old_fields, old_refs = self.current_instance, self.current_instance_fields, self.current_reference_params
        self.current_reference_params = {field.casefold() for _, field in inouts}
        self.current_instance, self.current_instance_fields = True, {field.casefold() for _, field in declarations} - self.current_reference_params
        for var_type, field in self.collect_sections(node, "temp_var_decls"):
            self.text += f"{self.indent}let mut {field}: {var_type} = {self.zero_value(var_type)};\n"
        self.accept(node, lambda child_name: child_name == body_name)
        self.current_instance, self.current_instance_fields, self.current_reference_params = old_instance, old_fields, old_refs
        self.indent = ""
        self.text += "    }\n}\n\n"

    def collect_sections(self, node, section_name):
        if not isinstance(node, dict):
            return []
        if node.get("name") == section_name:
            return self.collect_var_decls(node)
        declarations = []
        for child in node.get("children", []):
            declarations.extend(self.collect_sections(child, section_name))
        return declarations

    def visit_library(self, node):
        requested = {
            str(item.get("value", "")).upper()
            for item in self._named_nodes(node, "standard_function_name")
        }
        if self._named_nodes(node, "assert_statement"):
            requested.add("ASSERT")
        self._emit_section("IEC 61131-3 runtime support")
        self.text += render_primitives("rust", requested) + "\n"
        globals_ = self._named_nodes(node, "global_var_decl")
        if globals_:
            self._emit_section("Configuration global variables")
        for declaration in globals_:
            names = [item.get("value") for item in self._named_nodes(declaration, "global_var_name") if item.get("value")]
            var_type = self._declaration_type(declaration)
            initializer = self._first_named(declaration, "constant")
            value = self.render(initializer) if initializer is not None else self.zero_value(var_type)
            for name in names:
                self.text += f"/// IEC global variable `{name}`.\n"
                self.text += f"#[allow(non_upper_case_globals)]\npub static mut {name}: {var_type} = {value};\n"
        if globals_:
            self.text += "\n"
        self._emit_section("Generated IEC declarations and implementations")
        self.accept(node)

    def visit_function_declaration(self, node):
        name = node["children"][0]["value"]
        native = self.native_implementations.get(name.casefold())
        symbol = None
        if self.context is not None:
            symbol = self.context.symbols.symbol_for_declaration(node["children"][0])
        emitted_name = (
            self.context.generated_names.get(id(symbol), name)
            if self.context is not None and symbol is not None
            else name
        )
        return_type = self.extract_type(node["children"][1]) or "()"
        self.current_function = name
        self.current_return_type = return_type
        previous_synthetic_enum = self.current_synthetic_enum
        self.current_synthetic_enum = (
            node.get("enum_type")
            if node.get("synthetic") and node.get("generated_by") == "enum-conversions"
            else None
        )

        input_decls = self.collect_sections(node["children"][2], "input_declarations")
        output_decls = self.collect_sections(node["children"][2], "output_declarations")
        inout_decls = self.collect_sections(node["children"][2], "input_output_declarations")
        local_decls = self.collect_sections(node["children"][2], "function_var_decls")
        params = [f"mut {var_name}: {var_type}" for var_type, var_name in input_decls]
        params += [f"{var_name}: &mut {var_type}" for var_type, var_name in output_decls + inout_decls]

        # IEC variables have deterministic default values and remain mutable
        # even when a particular control-flow path overwrites them before the
        # first read. These are meaningful PLC semantics, but rustc reports
        # them as dead-store/unused-variable warnings in generated code.
        if node.get("synthetic") and node.get("generated_by") == "enum-conversions":
            self.text += f"/// Automatically generated conversion for enum `{node.get('enum_type')}`.\n"
        else:
            self.text += f"/// IEC function `{name}`.\n"
        allowed_lints = ["non_snake_case", "unused_assignments", "unused_mut", "unused_variables"]
        if node.get("synthetic") and node.get("generated_by") == "enum-conversions":
            allowed_lints.append("unreachable_patterns")
        self.text += f"#[allow({', '.join(allowed_lints)})]\n"
        self.text += f"pub fn {emitted_name}({', '.join(params)}) -> {return_type} {{\n"
        self.indent_inc()
        if return_type != "()":
            self.text += f"{self.indent}let mut {name}: {return_type} = {self.zero_value(return_type)};\n"
        for var_type, var_name in local_decls:
            self.text += f"{self.indent}let mut {var_name}: {var_type} = {self.zero_value(var_type)};\n"
        if local_decls or return_type != "()":
            self.text += "\n"
        if native is not None:
            self._emit_native_code(native.section("body") or "")
        else:
            self.accept(node, lambda child_name: child_name == "function_body")
        if return_type != "()":
            self.text += f"{self.indent}{name}\n"
        self.indent_dec()
        self.text += "}\n\n"
        self.current_function = None
        self.current_return_type = None
        self.current_synthetic_enum = previous_synthetic_enum

    def _emit_native_code(self, source):
        for line in source.splitlines():
            self.text += f"{self.indent}{line.rstrip()}\n" if line.strip() else "\n"

    def _first_named(self, node, name):
        if not isinstance(node, dict):
            return None
        if node.get("name") == name:
            return node
        for child in node.get("children", []):
            found = self._first_named(child, name)
            if found is not None:
                return found
        return None

    def _named_nodes(self, node, name):
        if not isinstance(node, dict):
            return []
        result = [node] if node.get("name") == name else []
        for child in node.get("children", []):
            result.extend(self._named_nodes(child, name))
        return result

    def _raw_values(self, node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            value = node.get("value")
            if isinstance(value, str):
                yield value
            for child in node.get("children", []):
                yield from self._raw_values(child)

    def visit_function_block_declaration(self, node):
        name_node = self._first_named(node, "derived_function_block_name")
        if name_node is None:
            return
        name = name_node["value"]
        self._emit_state_type(name, self._persistent_declarations(node), self._retained_declarations(node),
                              self._declaration_initializers(node), "step", "function_block_body", node)

    def visit_program_declaration(self, node):
        name_node = self._first_named(node, "program_type_name")
        if name_node is None:
            return
        name = name_node["value"]
        self._emit_state_type(name, self._persistent_declarations(node), self._retained_declarations(node),
                              self._declaration_initializers(node), "run", "function_block_body", node)

    def visit_action(self, node):
        name = self._first_named(node, "action_name")
        if name:
            self.text += f"/// IEC action `{name['value']}`.\n"
            self.text += f"pub fn {name['value']}() {{\n"
            self.indent_inc()
            self.accept(node, lambda child_name: child_name == "function_block_body")
            self.indent_dec()
            self.text += "}\n\n"

    def _sfc_step_condition(self, step, association):
        active = f"self.{sfc_field(step['name'], 'active')}"
        previous = f"self.{sfc_field(step['name'], 'previous')}"
        elapsed = f"self.{sfc_field(step['name'], 'elapsed_ms')}"
        qualifier = association["qualifier"]
        time = self.render(association["time"]) if association["time"] is not None else "0"
        if qualifier in {"P", "P1"}:
            return f"{active} && !{previous}"
        if qualifier == "P0":
            return f"!{active} && {previous}"
        if qualifier == "L":
            return f"{active} && {elapsed} < {time}"
        if qualifier in {"D", "SD", "DS"}:
            return f"{active} && {elapsed} >= {time}"
        if qualifier == "SL":
            return f"{active} && {elapsed} < {time}"
        return active

    def _sfc_variable(self, name):
        return self.render({"name": "variable_name", "value": name, "children": []})

    def visit_sequential_function_chart(self, node):
        for chart_index, chart in enumerate(sfc_charts(node)):
            ordered = sorted(enumerate(chart["transitions"]), key=lambda item: (item[1]["priority"], item[0]))
            earlier_sources = []
            fire_names = {}
            for ordinal, transition in ordered:
                fire = f"__sfc_{chart_index}_fire_{ordinal}"
                fire_names[ordinal] = fire
                sources = " && ".join(
                    f"self.{sfc_field(name, 'active')}" for name in transition["sources"]
                ) or "false"
                condition = self.render(transition["condition"]) if transition["condition"] is not None else "false"
                current_sources = {item.casefold() for item in transition["sources"]}
                blocked = [
                    name for name, used in earlier_sources
                    if {item.casefold() for item in used} & current_sources
                ]
                gate = "" if not blocked else " && " + " && ".join(f"!{name}" for name in blocked)
                self.text += f"{self.indent}let {fire}: bool = ({sources}) && ({condition}){gate};\n"
                earlier_sources.append((fire, transition["sources"]))

            for ordinal, transition in enumerate(chart["transitions"]):
                fire = fire_names.get(ordinal)
                if fire is None:
                    continue
                self.text += f"{self.indent}if {fire} {{\n"
                self.indent_inc()
                for name in transition["sources"]:
                    self.text += f"{self.indent}self.{sfc_field(name, 'active')} = false;\n"
                for name in transition["targets"]:
                    self.text += f"{self.indent}self.{sfc_field(name, 'active')} = true;\n"
                self.indent_dec()
                self.text += f"{self.indent}}}\n"

            for step in chart["steps"]:
                active = f"self.{sfc_field(step['name'], 'active')}"
                previous = f"self.{sfc_field(step['name'], 'previous')}"
                elapsed = f"self.{sfc_field(step['name'], 'elapsed_ms')}"
                self.text += f"{self.indent}{elapsed} = if {active} {{ if {previous} {{ {elapsed} + 1 }} else {{ 0 }} }} else {{ 0 }};\n"

            variable_conditions = {}
            indicator_conditions = {}
            variable_sets = {}
            variable_resets = {}
            action_sets = {}
            action_resets = {}
            stored_actions = set()
            for step in chart["steps"]:
                for association in step["associations"]:
                    condition = self._sfc_step_condition(step, association)
                    qualifier = association["qualifier"]
                    key = association["name"].casefold()
                    action = chart["actions"].get(key)
                    if action is not None:
                        if qualifier == "R":
                            action_resets.setdefault(key, []).append(condition)
                        elif qualifier in {"S", "SD", "DS"}:
                            action_sets.setdefault(key, []).append(condition)
                            stored_actions.add(key)
                        else:
                            self.text += f"{self.indent}if {condition} {{\n"
                            self.indent_inc()
                            self.accept(action, lambda child_name: child_name == "function_block_body")
                            self.indent_dec()
                            self.text += f"{self.indent}}}\n"
                    elif qualifier == "R":
                        variable_resets.setdefault(association["name"], []).append(condition)
                    elif qualifier in {"S", "SD", "DS"}:
                        variable_sets.setdefault(association["name"], []).append(condition)
                    else:
                        variable_conditions.setdefault(association["name"], []).append(condition)
                    for indicator in association["indicators"]:
                        indicator_name = self._first_named(indicator, "variable_name")
                        if indicator_name is not None:
                            indicator_conditions.setdefault(indicator_name["value"], []).append(condition)

            combined_conditions = dict(variable_conditions)
            for name, conditions in indicator_conditions.items():
                combined_conditions.setdefault(name, []).extend(conditions)
            for name, conditions in combined_conditions.items():
                enabled = conditions[0] if len(conditions) == 1 else " || ".join(f"({item})" for item in conditions)
                if name in variable_sets or name in variable_resets:
                    self.text += f"{self.indent}if {enabled} {{ {self._sfc_variable(name)} = true; }}\n"
                else:
                    self.text += f"{self.indent}{self._sfc_variable(name)} = {enabled};\n"
            for name, conditions in variable_sets.items():
                enabled = conditions[0] if len(conditions) == 1 else " || ".join(f"({item})" for item in conditions)
                self.text += f"{self.indent}if {enabled} {{ {self._sfc_variable(name)} = true; }}\n"
            for name, conditions in variable_resets.items():
                enabled = conditions[0] if len(conditions) == 1 else " || ".join(f"({item})" for item in conditions)
                self.text += f"{self.indent}if {enabled} {{ {self._sfc_variable(name)} = false; }}\n"
            for key, conditions in action_sets.items():
                enabled = conditions[0] if len(conditions) == 1 else " || ".join(f"({item})" for item in conditions)
                self.text += f"{self.indent}if {enabled} {{ self.{sfc_field('action_' + key, 'stored')} = true; }}\n"
            for key, conditions in action_resets.items():
                enabled = conditions[0] if len(conditions) == 1 else " || ".join(f"({item})" for item in conditions)
                self.text += f"{self.indent}if {enabled} {{ self.{sfc_field('action_' + key, 'stored')} = false; }}\n"
            for key in sorted(stored_actions):
                action = chart["actions"][key]
                state = f"self.{sfc_field('action_' + key, 'stored')}"
                self.text += f"{self.indent}if {state} {{\n"
                self.indent_inc()
                self.accept(action, lambda child_name: child_name == "function_block_body")
                self.indent_dec()
                self.text += f"{self.indent}}}\n"
            for step in chart["steps"]:
                self.text += (
                    f"{self.indent}self.{sfc_field(step['name'], 'previous')} = "
                    f"self.{sfc_field(step['name'], 'active')};\n"
                )

    def visit_configuration_declaration(self, node):
        name_node = self._first_named(node, "configuration_name")
        if name_node is None:
            return
        name = name_node["value"]
        tasks = {}
        for task in self._named_nodes(node, "task_configuration"):
            task_name = self._first_named(task, "task_name")
            initialization = self._first_named(task, "task_initialization")
            if task_name is None:
                continue
            duration = self._first_named(initialization, "duration") if initialization else None
            interval = max(int(self.render(duration)) if duration is not None else 1, 1)
            integers = self._named_nodes(initialization, "integer") if initialization else []
            priority = int(str(integers[-1].get("value", "0")).replace("_", "")) if integers else 0
            tasks[task_name["value"].casefold()] = {
                "name": task_name["value"], "interval": interval, "priority": priority,
            }
        programs = []
        for program in self._named_nodes(node, "program_configuration"):
            instance = self._first_named(program, "program_name")
            type_node = self._first_named(program, "program_type_name")
            if instance is None or type_node is None:
                continue
            task = self._first_named(program, "task_name")
            values = {str(value).upper() for value in self._raw_values(program)}
            programs.append({"instance": instance["value"], "type": type_node["value"],
                             "task": task["value"].casefold() if task else None,
                             "retain": "RETAIN" in values, "non_retain": "NON_RETAIN" in values})

        self.text += f"/// Scheduler state for IEC configuration `{name}`.\n"
        self.text += f"#[allow(non_snake_case)]\npub struct {name} {{\n"
        for program in programs:
            self.text += f"    pub {program['instance']}: {program['type']},\n"
        for task in tasks.values():
            self.text += f"    {task['name']}_elapsed_ms: u64,\n"
        self.text += "}\n\n"
        self.text += f"impl Default for {name} {{\n    fn default() -> Self {{ Self {{\n"
        for program in programs:
            self.text += f"        {program['instance']}: Default::default(),\n"
        for task in tasks.values():
            self.text += f"        {task['name']}_elapsed_ms: 0,\n"
        self.text += "    } }\n}\n\n"
        self.text += f"impl {name} {{\n"
        base = min((task["interval"] for task in tasks.values()), default=1)
        self.text += "    /// Smallest configured task interval, in milliseconds.\n"
        self.text += f"    pub const fn base_interval_ms() -> u64 {{ {base} }}\n\n"
        self.text += "    /// Reset the complete configuration state.\n"
        self.text += "    pub fn cold_start(&mut self) { *self = Self::default(); }\n\n"
        self.text += "    /// Restart execution while applying IEC retention rules.\n"
        self.text += "    pub fn warm_start(&mut self) {\n"
        for program in programs:
            if not program["retain"]:
                method = "cold_init" if program["non_retain"] else "warm_init"
                self.text += f"        self.{program['instance']}.{method}();\n"
        for task in tasks.values():
            self.text += f"        self.{task['name']}_elapsed_ms = 0;\n"
        self.text += "    }\n\n    /// Advance the configuration scheduler by `elapsed_ms`.\n"
        self.text += "    pub fn cycle(&mut self, elapsed_ms: u64) {\n"
        for program in programs:
            if program["task"] is None:
                self.text += f"        self.{program['instance']}.run();\n"
        scheduled = sorted(tasks.values(), key=lambda item: (item["priority"], item["name"].casefold()))
        if scheduled:
            self.text += "        let mut remaining_ms = elapsed_ms;\n        while remaining_ms > 0 {\n            let mut next_due_ms = u64::MAX;\n"
            for task in tasks.values():
                self.text += f"            next_due_ms = next_due_ms.min({task['interval']} - self.{task['name']}_elapsed_ms);\n"
            self.text += "            if next_due_ms > remaining_ms {\n"
            for task in tasks.values():
                self.text += f"                self.{task['name']}_elapsed_ms += remaining_ms;\n"
            self.text += "                break;\n            }\n"
            for task in tasks.values():
                self.text += f"            self.{task['name']}_elapsed_ms += next_due_ms;\n"
            self.text += "            remaining_ms -= next_due_ms;\n"
            for task in scheduled:
                self.text += f"            // Task {task['name']}: interval {task['interval']} ms, priority {task['priority']}.\n"
                self.text += f"            if self.{task['name']}_elapsed_ms >= {task['interval']} {{\n                self.{task['name']}_elapsed_ms -= {task['interval']};\n"
                for program in programs:
                    if program["task"] == task["name"].casefold():
                        self.text += f"                self.{program['instance']}.run();\n"
                self.text += "            }\n"
            self.text += "        }\n"
        self.text += "    }\n}\n\n"

    # IEC 61131-3 Edition 3 object-oriented lowering. It deliberately lives in
    # this backend so rust.py remains the single source of Rust generation.
    def _rust_class(self, value):
        classes = self.context.oop_types.get("classes", {}) if self.context is not None else {}
        if isinstance(value, dict):
            return value
        return classes.get(str(value or "").casefold())

    def _rust_own_fields(self, cls):
        result = []

        def collect(node):
            if not isinstance(node, dict) or node.get("name") in {"method_declaration", "method_prototype"}:
                return
            if node.get("name") in {
                "input_declarations", "output_declarations", "input_output_declarations",
                "var_declarations", "retentive_var_declarations", "non_retentive_var_decls",
            }:
                result.extend(self.collect_var_decls(node))
                return
            for child in node.get("children", []):
                collect(child)

        collect(cls["node"])
        return self._unique_declarations(result)

    def _rust_field_paths(self, cls):
        result = {}
        base = self._rust_class(cls.get("base"))
        if base is not None:
            result.update({key: "__base." + path for key, path in self._rust_field_paths(base).items()})
        for _, field in self._rust_own_fields(cls):
            result[field.casefold()] = field
        return result

    def _rust_implemented_interfaces(self, cls):
        interfaces = self.context.oop_types.get("interfaces", {}) if self.context is not None else {}
        result = {}
        base = self._rust_class(cls.get("base"))
        if base is not None:
            for interface in self._rust_implemented_interfaces(base):
                result[interface["key"]] = interface
        for interface_name in cls.get("interfaces", []):
            interface = interfaces.get(interface_name.casefold())
            if interface is None:
                continue
            result[interface["key"]] = interface
            for parent_name in interface.get("extends", []):
                parent = interfaces.get(parent_name.casefold())
                if parent is not None:
                    result[parent["key"]] = parent
        return list(result.values())

    def _rust_method_signature(self, node):
        return_node = self._first_named(node, "function_return_type")
        result = self.declaration_type(return_node, "()") if return_node is not None else "()"
        inputs = self.collect_sections(node, "input_declarations")
        outputs = self.collect_sections(node, "output_declarations")
        inouts = self.collect_sections(node, "input_output_declarations")
        params = [(name, var_type, False) for var_type, name in inputs]
        params += [(name, var_type, True) for var_type, name in outputs + inouts]
        return result, params

    def visit_interface_declaration(self, node):
        name_node = self._first_named(node, "interface_type_name")
        if name_node is None:
            return
        name = name_node["value"]
        iface = (self.context.oop_types.get("interfaces", {}).get(name.casefold()) if self.context is not None else None)
        methods = iface.get("methods", []) if iface else []
        self.text += f"/// Type-erased dispatch table for IEC interface `{name}`.\n"
        self.text += f"#[allow(non_snake_case)]\npub struct {name} {{\n    instance: *mut (),\n"
        for method in methods:
            result, params = self._rust_method_signature(method["node"])
            types = ", ".join(("&mut " if pointer else "") + var_type for _, var_type, pointer in params)
            suffix = ", " + types if types else ""
            self.text += f"    {method['name']}_fn: unsafe fn(*mut (){suffix}) -> {result},\n"
        self.text += "}\n"
        self.text += f"impl Default for {name} {{\n    fn default() -> Self {{ Self {{\n        instance: core::ptr::null_mut(),\n"
        for method in methods:
            params = self._rust_method_signature(method["node"])[1]
            placeholders = ", ".join("_" for _ in params)
            suffix = ", " + placeholders if placeholders else ""
            self.text += f"        {method['name']}_fn: |_{suffix}| panic!(\"unbound interface {name}\"),\n"
        self.text += "    } }\n}\n"
        self.text += f"impl {name} {{\n"
        for method in methods:
            result, params = self._rust_method_signature(method["node"])
            declarations = ", ".join(f"{param}: {'&mut ' if pointer else ''}{var_type}" for param, var_type, pointer in params)
            arguments = ", ".join(param for param, _, _ in params)
            decl_suffix = ", " + declarations if declarations else ""
            arg_suffix = ", " + arguments if arguments else ""
            self.text += f"    pub fn {method['name']}(&mut self{decl_suffix}) -> {result} {{ unsafe {{ (self.{method['name']}_fn)(self.instance{arg_suffix}) }} }}\n"
        self.text += "}\n"

    def visit_class_declaration(self, node):
        name_node = self._first_named(node, "class_type_name")
        if name_node is None or self.context is None:
            return
        cls = self.context.oop_types.get("classes", {}).get(name_node["value"].casefold())
        if cls is None:
            return
        name = cls["name"]
        base = self._rust_class(cls.get("base"))
        fields = self._rust_own_fields(cls)
        self.text += f"/// Runtime representation of IEC class `{name}`.\n"
        self.text += f"#[allow(non_snake_case)]\npub struct {name} {{\n"
        if base is not None:
            self.text += f"    pub __base: {base['name']},\n"
        for var_type, field in fields:
            self.text += f"    pub {field}: {var_type},\n"
        self.text += "}\n"
        self.text += f"impl Default for {name} {{\n    fn default() -> Self {{ Self {{\n"
        if base is not None:
            self.text += "        __base: Default::default(),\n"
        for var_type, field in fields:
            self.text += f"        {field}: {self.zero_value(var_type)},\n"
        self.text += "    } }\n}\n"
        self.text += f"impl {name} {{\n"
        for method in cls["methods"]:
            if method["abstract"]:
                continue
            result, params = self._rust_method_signature(method["node"])
            declarations = ", ".join(f"{param}: {'&mut ' if pointer else ''}{var_type}" for param, var_type, pointer in params)
            suffix = ", " + declarations if declarations else ""
            self.text += f"    pub fn {method['name']}(&mut self{suffix}) -> {result} {{\n"
            old_instance, old_fields = self.current_instance, self.current_instance_fields
            old_paths, old_refs = self.current_instance_field_paths, self.current_reference_params
            self.current_instance = True
            self.current_instance_field_paths = self._rust_field_paths(cls)
            self.current_instance_fields = set(self.current_instance_field_paths)
            self.current_reference_params = {param.casefold() for param, _, pointer in params if pointer}
            self.indent = "        "
            if result != "()":
                self.text += f"{self.indent}let mut {method['name']}: {result} = {self.zero_value(result)};\n"
            for var_type, local in self.collect_sections(method["node"], "function_var_decls") + self.collect_sections(method["node"], "temp_var_decls"):
                self.text += f"{self.indent}let mut {local}: {var_type} = {self.zero_value(var_type)};\n"
            body = self._first_named(method["node"], "function_body")
            if body is not None:
                self.visit(body)
            if result != "()":
                self.text += f"{self.indent}{method['name']}\n"
            self.current_instance, self.current_instance_fields = old_instance, old_fields
            self.current_instance_field_paths, self.current_reference_params = old_paths, old_refs
            self.indent = ""
            self.text += "    }\n"
        self.text += "}\n"
        for iface in ([] if cls["abstract"] else self._rust_implemented_interfaces(cls)):
            self.text += f"impl From<&mut {name}> for {iface['name']} {{\n    fn from(value: &mut {name}) -> Self {{ Self {{\n        instance: value as *mut {name} as *mut (),\n"
            for method in iface["methods"]:
                result, params = self._rust_method_signature(method["node"])
                args = ", ".join(param for param, _, _ in params)
                closure_params = ", ".join(["instance"] + [f"{param}" for param, _, _ in params])
                suffix = ", " + args if args else ""
                self.text += f"        {method['name']}_fn: |{closure_params}| unsafe {{ (&mut *(instance as *mut {name})).{method['name']}({args}) }},\n"
            self.text += "    } }\n}\n"

    def visit_method_declaration(self, node):
        return

    def visit_method_prototype(self, node):
        return

    def visit_method_invocation(self, node):
        resolution = self.context.resolved_methods.get(id(node)) if self.context is not None else None
        receiver = self._first_named(node, "method_receiver")
        method = self._first_named(node, "method_name")
        if resolution is None or receiver is None or method is None:
            self.text += "panic!(\"unresolved method\")"
            return
        kind = resolution["receiver_kind"]
        if kind == "THIS":
            target = "self"
        elif kind == "SUPER":
            target = "self.__base"
        else:
            variable = self._first_named(receiver, "variable_name")
            target = self.render(variable) if variable is not None else "self"
        arguments = []
        for assignment in self._named_nodes(node, "param_assignment"):
            expressions = self._named_nodes(assignment, "expression")
            if expressions:
                arguments.append(self.render(expressions[-1]))
        self.text += f"{target}.{method['value']}({', '.join(arguments)})"

    def visit_method_call_statement(self, node):
        invocation = self._first_named(node, "method_invocation")
        self.text += f"{self.indent}{self.render(invocation)};\n"

    def visit_simple_type_declaration(self, node):
        name = self._first_named(node, "simple_type_name")
        array, structure = self._first_named(node, "array_specification"), self._first_named(node, "structure_declaration")
        if name and array:
            self._emit_array_type(name["value"], array)
        elif name and structure:
            self._emit_structure_type(name["value"], structure)
        elif name:
            self.text += f"/// IEC derived type `{name['value']}`.\n"
            self.text += f"pub type {name['value']} = {self.declaration_type(node)};\n\n"

    def visit_data_type_declaration(self, node):
        for declaration in self._named_nodes(node, "simple_type_declaration"):
            self.visit_simple_type_declaration(declaration)
        for declaration in self._named_nodes(node, "subrange_type_declaration"):
            self.visit_subrange_type_declaration(declaration)
        for declaration in self._named_nodes(node, "enumerated_type_declaration"):
            self.visit_enumerated_type_declaration(declaration)
        for declaration in self._named_nodes(node, "array_type_declaration"):
            self.visit_array_type_declaration(declaration)
        for declaration in self._named_nodes(node, "structure_type_declaration"):
            self.visit_structure_type_declaration(declaration)
        for declaration in self._named_nodes(node, "string_type_declaration"):
            self.visit_string_type_declaration(declaration)

    def visit_subrange_type_declaration(self, node):
        name = self._first_named(node, "subrange_type_name")
        if name:
            self.text += f"/// IEC subrange type `{name['value']}`.\n"
            self.text += f"pub type {name['value']} = {self.declaration_type(node)};\n\n"

    def visit_enumerated_type_declaration(self, node):
        name = self._first_named(node, "enumerated_type_name")
        values = [item["value"] for item in self._named_nodes(node, "enumerated_value") if item.get("value")]
        if name and values:
            self.text += f"/// IEC enumeration `{name['value']}`.\n"
            self.text += "#[allow(non_camel_case_types)]\n"
            self.text += f"#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]\npub enum {name['value']} {{\n"
            for index, value in enumerate(values):
                self.text += f"    {'#[default] ' if index == 0 else ''}{value},\n"
            self.text += "}\n\n"

    def visit_array_type_declaration(self, node):
        name, spec = self._first_named(node, "array_type_name"), self._first_named(node, "array_specification")
        if name and spec:
            self._emit_array_type(name["value"], spec)

    def _emit_array_type(self, name, spec):
        dimensions = []
        for range_node in self._named_nodes(spec, "subrange"):
            ints = self._named_nodes(range_node, "signed_integer")
            if len(ints) == 2:
                dimensions.append(f"({self.render(ints[1])} - ({self.render(ints[0])}) + 1) as usize")
        element = self.declaration_type(spec)
        for size in reversed(dimensions):
            element = f"[{element}; {size}]"
        self.text += f"/// IEC array type `{name}`.\n"
        self.text += f"pub type {name} = {element};\n\n"

    def visit_string_type_declaration(self, node):
        name = self._first_named(node, "string_type_name")
        if name:
            self.text += f"/// IEC string type `{name['value']}`.\n"
            self.text += f"pub type {name['value']} = String;\n\n"

    def visit_structure_type_declaration(self, node):
        name = self._first_named(node, "structure_type_name")
        if name:
            self._emit_structure_type(name["value"], node)

    def _emit_structure_type(self, name, node):
        self.text += f"/// IEC structure `{name}`.\n"
        self.text += f"#[allow(non_snake_case)]\n#[derive(Default)]\npub struct {name} {{\n"
        self.indent_inc()
        for element in self._named_nodes(node, "structure_element_declaration"):
            field = self._first_named(element, "structure_element_name")
            if field:
                self.text += f"{self.indent}pub {field['value']}: {self.declaration_type(element)},\n"
        self.indent_dec()
        self.text += "}\n\n"

    def visit_primary_expression(self, node):
        children = node.get("children", [])
        if not children or children[0].get("name") != "function_name":
            self.accept(node)
            return


        standard_name = self._first_named(children[0], "standard_function_name")
        trunc_match = re.fullmatch(
            r"(?:(?:REAL|LREAL)_)?TRUNC_(SINT|INT|DINT|LINT|USINT|UINT|UDINT|ULINT)",
            str(standard_name.get("value", "")).upper() if standard_name else "",
        )
        if trunc_match:
            argument = self._first_named(node, "expression")
            self.text += f"({self.render(argument)}) as {self.iecType2Rust(trunc_match.group(1))}"
            return

        resolved = self.context.resolved_calls.get(id(node)) if self.context is not None else None
        if resolved is not None:
            self.text += self.context.generated_names.get(id(resolved), resolved.name)
        else:
            self.visit(children[0])
        self.text += "("
        resolved_arguments = (
            self.context.resolved_arguments.get(id(node)) if self.context is not None else None
        )
        arguments = resolved_arguments or [child for child in children[1:] if child.get("name") == "param_assignment"]
        for index, argument in enumerate(arguments):
            if index:
                self.text += ", "
            if resolved_arguments is not None:
                self.visit(argument)
            else:
                expressions = [child for child in argument.get("children", []) if child.get("name") == "expression"]
                if expressions:
                    self.visit(expressions[-1])
        self.text += ")"

    def visit_standard_function_name(self, node):
        self.text += node["value"]

    def visit_derived_function_name(self, node):
        self.text += node["value"]

    def visit_integer_literal(self, node):
        self.text += node["value"].replace("_", "")

    def visit_real_literal(self, node):
        self.text += node["value"].replace("_", "")

    def visit_integer(self, node):
        self.text += node["value"].replace("_", "")

    def visit_signed_integer(self, node):
        if node.get("value") is not None:
            self.text += str(node["value"]).replace("_", "")
        else:
            self.accept(node)

    def _visit_based_integer(self, node, base, prefix=""):
        value = self.render(node["children"][0]).replace("_", "")
        digits = value.split("#", 1)[-1]
        self.text += prefix + digits if prefix else str(int(digits, base))

    def visit_binary_integer(self, node):
        self._visit_based_integer(node, 2, "0b")

    def visit_octal_integer(self, node):
        self._visit_based_integer(node, 8, "0o")

    def visit_hex_integer(self, node):
        self._visit_based_integer(node, 16, "0x")

    def visit_boolean_literal(self, node):
        self.text += node["value"].lower()

    def _iec_string(self, node):
        token = self._first_named(node, "token")
        raw = str(token.get("value", "''")) if token else "''"
        content = raw[1:-1] if len(raw) >= 2 else raw
        content = content.replace("$N", "\n").replace("$n", "\n")
        content = content.replace("$T", "\t").replace("$t", "\t")
        content = content.replace("$$", "$").replace("$''", "'").replace("$'", "'")
        content = content.replace("''", "'")
        content = content.replace("\\", "\\\\").replace('"', '\\"')
        content = content.replace("\n", "\\n").replace("\t", "\\t")
        return f'"{content}"'

    @staticmethod
    def _unicode_content(raw):
        sharp = raw.find("#")
        quoted = raw[sharp + 1:].strip() if sharp >= 0 else raw
        content = quoted[1:-1] if len(quoted) >= 2 else quoted
        content = re.sub(
            r"\$\{([0-9A-Fa-f]{1,6})\}",
            lambda match: (
                chr(int(match.group(1), 16))
                if int(match.group(1), 16) <= 0x10FFFF
                and not 0xD800 <= int(match.group(1), 16) <= 0xDFFF
                else "\ufffd"
            ),
            content,
        )
        return content.replace("$N", "\n").replace("$n", "\n").replace("$$", "$").replace("''", "'")

    def visit_unicode_character_string(self, node):
        token = self._first_named(node, "token")
        raw = str(token.get("value", "U#''")) if token else "U#''"
        content = self._unicode_content(raw)
        if raw.lstrip().upper().startswith("UCHAR"):
            self.text += str(ord(content[0]) if content else 0)
            return
        escaped = content.replace("\\", "\\\\").replace('"', '\\"')
        escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")
        self.text += f'"{escaped}"'

    @staticmethod
    def _typed_character_content(raw):
        quoted = raw[raw.find("#") + 1:].strip()
        content = quoted[1:-1] if len(quoted) >= 2 else quoted
        content = re.sub(
            r"\$([0-9A-Fa-f]{2}|[0-9A-Fa-f]{4})",
            lambda match: chr(int(match.group(1), 16)),
            content,
        )
        return content.replace("$N", "\n").replace("$n", "\n").replace("$T", "\t").replace("$t", "\t").replace("$$", "$").replace("''", "'").replace('""', '"')

    def visit_typed_character_string(self, node):
        token = self._first_named(node, "token")
        raw = str(token.get("value", "STRING#''")) if token else "STRING#''"
        prefix = raw[:raw.find("#")].strip().upper()
        content = self._typed_character_content(raw)
        if prefix in {"CHAR", "WCHAR"}:
            self.text += str(ord(content[0]) if content else 0)
            return
        escaped = content.replace("\\", "\\\\").replace('"', '\\"')
        escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")
        self.text += f'"{escaped}"'

    def visit_single_byte_character_string(self, node):
        self.text += self._iec_string(node)

    def visit_double_byte_character_string(self, node):
        self.text += self._iec_string(node)

    def visit_bit_string_literal(self, node):
        for child in node["children"]:
            self.visit(child)

    def visit_duration(self, node):
        multipliers = {"d": 86400000, "h": 3600000, "m": 60000, "s": 1000, "ms": 1}
        total = 0.0
        for component in self._named_nodes(node, "duration_component"):
            number = self._first_named(component, "integer") or self._first_named(component, "real_literal")
            tokens = self._named_nodes(component, "token")
            unit = str(tokens[-1].get("value", "ms")).casefold() if tokens else "ms"
            try:
                total += float(number.get("value", 0)) * multipliers.get(unit, 1)
            except (AttributeError, ValueError):
                pass
        self.text += str(int(total))

    def visit_date(self, node):
        values = [int(item.get("value", 0)) for item in self._named_nodes(node, "integer")]
        self.text += str(values[0] * 10000 + values[1] * 100 + values[2] if len(values) >= 3 else 0)

    def visit_time_of_day(self, node):
        values = [int(float(item.get("value", 0))) for item in self._named_nodes(node, "integer")]
        self.text += str(((values[0] * 60 + values[1]) * 60 + values[2]) * 1000 if len(values) >= 3 else 0)

    def visit_date_and_time(self, node):
        values = [int(float(item.get("value", 0))) for item in self._named_nodes(node, "integer")]
        if len(values) >= 6:
            self.text += str((((values[0] * 100 + values[1]) * 100 + values[2]) * 1000000) + values[3] * 10000 + values[4] * 100 + values[5])
        else:
            self.text += "0"

    def visit_signed_integer_type_name(self, node):
        self.text += self.iecType2Rust(node["value"])

    def visit_unsigned_integer_type_name(self, node):
        self.text += self.iecType2Rust(node["value"])

    def visit_real_type_name(self, node):
        self.text += self.iecType2Rust(node["value"])

    def visit_bit_string_type_name(self, node):
        self.text += self.iecType2Rust(node["value"])

    def visit_variable_name(self, node):
        name = node["value"]
        if self.current_instance and name.casefold() in self.current_instance_fields:
            path = self.current_instance_field_paths.get(name.casefold(), name)
            self.text += f"self.{path}"
        elif name.casefold() in self.current_reference_params:
            self.text += f"*{name}"
        elif self.context is not None:
            symbol = self.context.symbols.symbol_for_reference(node)
            if symbol is not None and symbol.storage in {"output", "in_out"}:
                self.text += f"*{name}"
            elif symbol is not None and symbol.storage in {"external", "global"}:
                self.text += f"unsafe {{ {name} }}"
            else:
                self.text += name
        else:
            self.text += name

    def visit_field_selector(self, node):
        self.text += str(node.get("value", ""))

    def _iter_named_set(self, node, names):
        if not isinstance(node, dict):
            return
        if node.get("name") in names:
            yield node
            return
        for child in node.get("children", []):
            yield from self._iter_named_set(child, names)

    def _array_lower_bounds(self, variable_name):
        if self.context is None or variable_name is None:
            return ()
        symbol = self.context.symbols.symbol_for_reference(variable_name)
        if symbol is None:
            return ()
        specification = None
        declaration_nodes = {
            "var1_init_decl", "var1_declaration", "array_var_init_decl", "array_var_declaration",
            "structured_var_init_decl", "structured_var_declaration", "string_var_declaration",
            "fb_name_decl", "located_var_decl",
        }
        for declaration in self._iter_named_set(symbol.scope.node, declaration_nodes):
            names = self._named_nodes(declaration, "variable_name")
            if any(item is symbol.declaration for item in names):
                specification = self._first_named(declaration, "array_specification")
                break
        if specification is None and symbol.type_ref is not None and symbol.type_ref.name:
            type_name = symbol.type_ref.name.casefold()
            for declaration in self._named_nodes(self.context.symbols.global_scope.node, "array_type_declaration"):
                name = self._first_named(declaration, "array_type_name")
                if name is not None and str(name.get("value", "")).casefold() == type_name:
                    specification = self._first_named(declaration, "array_specification")
                    break
        if specification is None:
            return ()
        result = []
        for subrange in self._named_nodes(specification, "subrange"):
            bounds = self._named_nodes(subrange, "signed_integer")
            if len(bounds) == 2:
                result.append(self.render(bounds[0]))
        return tuple(result)

    def visit_array_variable(self, node):
        subscripted = self._first_named(node, "subscripted_variable")
        subscript_list = self._first_named(node, "subscript_list")
        if subscripted is None or subscript_list is None:
            self.accept(node)
            return
        lower_bounds = self._array_lower_bounds(self._first_named(subscripted, "variable_name"))
        self.visit(subscripted)
        subscripts = [child for child in subscript_list.get("children", []) if isinstance(child, dict) and child.get("name") == "subscript"]
        for dimension, subscript in enumerate(subscripts):
            index = self.render(subscript)
            lower = lower_bounds[dimension] if dimension < len(lower_bounds) else "0"
            adjusted = index if lower == "0" else f"({index}) - ({lower})"
            self.text += f"[({adjusted}) as usize]"

    def visit_subscript_list(self, node):
        for subscript in self._named_nodes(node, "subscript"):
            self.text += f"[({self.render(subscript)}) as usize]"

    def visit_expression(self, node):
        self._join_children(node, " || ")

    def visit_xor_expression(self, node):
        self._join_children(node, " ^ ")

    def visit_and_expression(self, node):
        self._join_children(node, " && ")

    def visit_comparison(self, node):
        self._visit_infix_coerced(node)

    def visit_comparison_equality_operator(self, node):
        op = {"=": "==", "NEQ": "!=", "<>": "!="}.get(node["value"], node["value"])
        self.text += f" {op} "

    def visit_equ_expression(self, node):
        self._visit_infix_coerced(node)

    def visit_add_expression(self, node):
        self._visit_infix_coerced(node)

    def visit_term(self, node):
        children = node["children"]
        if not children:
            return
        self.visit(children[0])
        for child in children[1:]:
            op = {"MOD": "%"}.get(child.get("value"), child.get("value"))
            self.text += f" {op} "
            self.visit(child)

    def visit_power_expression(self, node):
        self._join_children(node, " /* ** */ ")

    def visit_unary_expression(self, node):
        op = node.get("value")
        if op == "NOT":
            self.text += "!"
        elif op:
            self.text += op
        self.accept(node)

    def visit_add_operator(self, node):
        self.text += f" {node['value']} "

    def visit_comparison_operator(self, node):
        op = {"LE_EQ": "<=", "GE_EQ": ">="}.get(node["value"], node["value"])
        self.text += f" {op} "

    def visit_assignment_statement(self, node):
        variable = next(child for child in node["children"] if child.get("name") == "variable")
        expression = next(child for child in node["children"] if child.get("name") == "expression")
        oop_assignment = self.context.oop_assignments.get(id(node)) if self.context is not None else None
        if oop_assignment is not None:
            self.text += f"{self.indent}{self.render(variable)} = {oop_assignment['interface']}::from(&mut {self.render(expression)});\n"
            return
        target_type = self.rust_type_for_node(variable)
        rendered = self.render(expression)
        expression_type = self.rust_type_for_node(expression)
        target_datatype = (
            self.context.declared_types.get(target_type.casefold())
            if self.context is not None and target_type is not None
            else None
        )
        enum_value = isinstance(target_datatype, EnumType) and "::" in rendered
        if target_type is not None and expression_type is not None and target_type != expression_type and not enum_value:
            rendered = f"({rendered}) as {target_type}"
        elif target_type is not None and expression_type is None and target_type not in {"bool", "&'static str"} and not enum_value:
            rendered = f"({rendered}) as {target_type}"
        variable_name = self._first_named(variable, "variable_name")
        symbol = (
            self.context.symbols.symbol_for_reference(variable_name)
            if self.context is not None and variable_name is not None
            else None
        )
        if symbol is not None and symbol.storage in {"external", "global"}:
            self.text += f"{self.indent}unsafe {{ {variable_name['value']} = {rendered}; }}\n"
        else:
            self.text += f"{self.indent}{self.render(variable)} = {rendered};\n"

    def visit_assert_statement(self, node):
        expression = next(child for child in node.get("children", []) if isinstance(child, dict))
        self.text += f"{self.indent}ASSERT({self.render(expression)});\n"

    def visit_exit_statement(self, node):
        self.text += f"{self.indent}break;\n"

    def visit_if_statement(self, node):
        self.text += self.indent + "if "
        self.visit(node["children"][0])
        self.text += " {\n"
        self.indent_inc()
        self.visit(node["children"][1])
        self.indent_dec()
        self.text += self.indent + "}\n"
        self.accept(node, lambda name: name == "elseif_statement_list")
        self.accept(node, lambda name: name == "else_statement")

    def visit_elseif_statement(self, node):
        self.text += self.indent + "else if "
        self.visit(node["children"][0])
        self.text += " {\n"
        self.indent_inc()
        self.visit(node["children"][1])
        self.indent_dec()
        self.text += self.indent + "}\n"

    def visit_else_statement(self, node):
        self.text += self.indent + "else {\n"
        self.indent_inc()
        self.accept(node)
        self.indent_dec()
        self.text += self.indent + "}\n"

    def visit_while_statement(self, node):
        self.text += self.indent + "while "
        self.visit(node["children"][0])
        self.text += " {\n"
        self.indent_inc()
        self.visit(node["children"][1])
        self.indent_dec()
        self.text += self.indent + "}\n"

    def visit_repeat_statement(self, node):
        self.text += self.indent + "loop {\n"
        self.indent_inc()
        self.visit(node["children"][0])
        self.text += self.indent + "if "
        self.visit(node["children"][1])
        self.text += " { break; }\n"
        self.indent_dec()
        self.text += self.indent + "}\n"

    def visit_token(self, node):
        self.text += str(node.get("value", ""))

    def visit_control_variable(self, node):
        value = next((child.get("value") for child in node.get("children", []) if isinstance(child, dict)), "")
        if self.current_instance and isinstance(value, str) and value.casefold() in self.current_instance_fields:
            self.text += f"self.{value}"
        elif isinstance(value, str) and value.casefold() in self.current_reference_params:
            self.text += f"*{value}"
        else:
            self.accept(node)

    def visit_for_statement(self, node):
        control, for_list, body = node["children"][:3]
        parts = [child for child in for_list.get("children", []) if isinstance(child, dict)]
        start = parts[0]
        direction = str(parts[1].get("value", "TO")).upper() if len(parts) > 1 else "TO"
        end = parts[2] if len(parts) > 2 else parts[-1]
        by = parts[4] if len(parts) > 4 and parts[3].get("value") == "BY" else None
        variable = self.render(control)
        self.text += f"{self.indent}{variable} = {self.render(start)};\n"
        comparator = ">=" if direction == "DOWNTO" else "<="
        self.text += f"{self.indent}while {variable} {comparator} {self.render(end)} {{\n"
        self.indent_inc()
        self.visit(body)
        operator = "-=" if direction == "DOWNTO" else "+="
        step = self.render(by) if by is not None else "1"
        self.text += f"{self.indent}{variable} {operator} {step};\n"
        self.indent_dec()
        self.text += f"{self.indent}}}\n"

    def visit_case_statement(self, node):
        children = node.get("children", [])
        expression = next(child for child in children if child.get("name") == "expression")
        self.text += f"{self.indent}match {self.render(expression)} {{\n"
        self.indent_inc()
        for child in children:
            if child.get("name") == "case_element":
                self.visit(child)
            elif child.get("name") == "statement_list":
                self.text += f"{self.indent}_ => {{\n"
                self.indent_inc()
                self.visit(child)
                self.indent_dec()
                self.text += f"{self.indent}}},\n"
        if not any(child.get("name") == "statement_list" for child in children):
            self.text += f"{self.indent}_ => {{}},\n"
        self.indent_dec()
        self.text += f"{self.indent}}}\n"

    def visit_case_element(self, node):
        case_list = next(child for child in node["children"] if child.get("name") == "case_list")
        statements = next(child for child in node["children"] if child.get("name") == "statement_list")
        labels = [child for child in case_list.get("children", []) if child.get("name") == "case_list_element"]
        patterns = " | ".join(self.render(label) for label in labels)
        self.text += f"{self.indent}{patterns} => {{\n"
        self.indent_inc()
        self.visit(statements)
        self.indent_dec()
        self.text += f"{self.indent}}},\n"

    def _join_children(self, node, separator):
        for index, child in enumerate(node["children"]):
            if index:
                self.text += separator
            self.visit(child)

    def _visit_infix(self, node):
        for child in node["children"]:
            self.visit(child)

    def _visit_infix_coerced(self, node):
        operands = [
            child for child in node.get("children", [])
            if child.get("name") not in {
                "add_operator", "comparison_operator", "comparison_equality_operator"
            }
        ]
        target_type = self.common_numeric_type(operands)
        for child in node.get("children", []):
            if child in operands:
                self.text += self.render_as(child, target_type)
            else:
                self.visit(child)
