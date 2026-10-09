# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate Rust code from the supported Structured Text AST subset."""

import re
import shutil
import subprocess

from .visitor import NodeVisitor
from .generator.engine import GeneratorEngine
from .generator.ir import Assignment, Call, Cast, IfBranch, Literal, RepeatLoop, UnaryExpression, WhileLoop
from .generator.loader import GeneratorBundle, bundled_generator, load_generator
from .sfc import charts as sfc_charts, field as sfc_field, state_declarations as sfc_state_declarations
from ..runtime.loader import render_primitives
from ..semantic.types import ArrayType, EnumType, ReferenceType


class RustCodeGenerator(NodeVisitor):
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
        return f"{self.generator_engine.map('operator', 'NOT')}({expression})"

    def _il_true(self):
        return self.generator_engine.map("boolean_literal", "TRUE")

    def _il_false(self):
        return self.generator_engine.map("boolean_literal", "FALSE")

    def _il_opcode_key(self, opcode):
        """Map an IL opcode to a backend-agnostic operator key.

        IL conjunction is bitwise; the backend operator mapping supplies the
        actual spelling, so no target keyword appears here.
        """
        table = {
            "AND": "BIT_AND", "&": "BIT_AND", "AN": "BIT_AND", "ANDN": "BIT_AND",
            "OR": "BIT_OR", "ORN": "BIT_OR", "XOR": "XOR", "XORN": "XOR",
            "ADD": "ADD", "SUB": "SUB", "MUL": "MUL", "DIV": "DIV", "MOD": "MOD",
            "GT": "GT", "GE": "GE", "EQ": "EQ", "LT": "LT", "LE": "LE",
            "NE": "NE",
        }
        return table.get(opcode, opcode)

    def _il_assignment(self, target, expression):
        return f"{target} = {expression};"

    def _il_emit_line(self, statement):
        self.text += f"{self.indent}{statement}\n"

    def _il_labels(self, instruction):
        return [
            item for item in instruction.get("children", [])
            if isinstance(item, dict) and item.get("name") == "label"
        ]

    def _il_operation(self, instruction):
        return next(
            (child for child in instruction.get("children", []) if isinstance(child, dict) and child.get("name") not in {"label", "token"}),
            None,
        )

    def _il_has_jumps(self, instructions):
        jump_opcodes = {"JMP", "JMPC", "JMPCN"}
        for instruction in instructions:
            for child in instruction.get("children", []):
                if isinstance(child, dict) and self._il_token(child) in jump_opcodes:
                    return True
        return False

    def _il_label_index(self, instructions, destination):
        wanted = str(destination or "").casefold()
        for index, instruction in enumerate(instructions):
            for label in self._il_labels(instruction):
                if str(label.get("value", "")).casefold() == wanted:
                    return index
        return len(instructions)

    def _il_call_arguments(self, operation, accumulator):
        arguments = [accumulator] if accumulator is not None else []
        for item in self._il_descendants(operation, "il_operand"):
            child = next((c for c in item.get("children", []) if isinstance(c, dict)), None)
            if child is not None:
                if child.get("name") == "enumerated_value":
                    child = {"name": "variable_name", "value": child.get("value", ""), "children": []}
                arguments.append(self.render(child))
        return arguments

    def _visit_instruction_list_with_jumps(self, node, instructions):
        """Lower IL control flow to a Rust program-counter loop.

        Rust deliberately has no ``goto``.  A small dispatcher preserves IL
        label/jump semantics without introducing a second backend module or a
        runtime panic.  IEC requires a consistent current-result type along a
        control-flow network, so the first LD operand also gives Rust the
        accumulator type.  All spellings come from the backend bundle; only
        the label/index resolution below is shared lowering.
        """
        engine = self.generator_engine
        labels = {}
        initial = None
        for index, instruction in enumerate(instructions):
            for label in self._il_labels(instruction):
                labels[str(label.get("value", "")).casefold()] = index
            operation = self._il_operation(instruction)
            if operation is not None and self._il_token(operation) in {"LD", "LDN"}:
                initial = initial or self._il_render_operand(operation)

        # A jump network without an LD is invalid IL.  Default keeps codegen
        # total while allowing the semantic diagnostics to remain authoritative.
        initial = initial or "Default::default()"
        stored_function_result = False
        arms = []
        for index, instruction in enumerate(instructions):
            body_indent = self.indent + "    "
            body = ""
            for label in self._il_labels(instruction):
                body += engine.render(
                    "il_label", name=label.get("value", ""), indent=body_indent
                )
            operation = self._il_operation(instruction)
            advances = True
            if operation is not None:
                opcode = self._il_token(operation)
                operand = self._il_render_operand(operation)
                if opcode in {"LD", "LDN"} and operand is not None:
                    value = self._il_boolean_not(operand) if opcode == "LDN" else operand
                    body += engine.render(
                        "il_assign", target="__il_acc", value=value, indent=body_indent
                    )
                elif opcode in {"ST", "STN"} and operand is not None:
                    value = self._il_boolean_not("__il_acc") if opcode == "STN" else "__il_acc"
                    body += engine.render(
                        "il_assign", target=operand, value=value, indent=body_indent
                    )
                    stored_function_result = stored_function_result or (
                        bool(self.current_function) and operand.casefold() == self.current_function.casefold()
                    )
                elif opcode == "NOT":
                    body += engine.render(
                        "il_assign", target="__il_acc",
                        value=self._il_boolean_not("__il_acc"), indent=body_indent,
                    )
                elif opcode in {"ANDN", "AN", "ORN", "XORN"} and operand is not None:
                    key = {"ANDN": "BIT_AND", "AN": "BIT_AND", "ORN": "BIT_OR", "XORN": "XOR"}[opcode]
                    operator = engine.map("operator", key)
                    body += engine.render(
                        "il_assign", target="__il_acc",
                        value=f"__il_acc {operator} {self._il_boolean_not(operand)}",
                        indent=body_indent,
                    )
                elif opcode in {"AND", "&", "OR", "XOR", "ADD", "SUB", "MUL", "DIV", "MOD", "GT", "GE", "EQ", "LT", "LE", "NE"} and operand is not None:
                    operator = engine.map("operator", self._il_opcode_key(opcode))
                    body += engine.render(
                        "il_assign", target="__il_acc",
                        value=f"__il_acc {operator} {operand}", indent=body_indent,
                    )
                elif opcode in {"S", "S1", "R", "R1"} and operand is not None:
                    value = self._il_true() if opcode in {"S", "S1"} else self._il_false()
                    inner = engine.render(
                        "il_assign", target=operand, value=value, indent=body_indent + "    "
                    )
                    body += engine.render(
                        "il_guarded", condition="__il_acc", body=inner, indent=body_indent
                    )
                elif opcode in {"JMP", "JMPC", "JMPCN"}:
                    targets = self._il_descendants(operation, "label")
                    destination = targets[0].get("value", "") if targets else ""
                    target = labels.get(str(destination).casefold(), len(instructions))
                    jump = engine.render(
                        "il_jump", target_label=destination, target_index=target,
                        condition="", has_condition="", indent=body_indent + "    " if opcode != "JMP" else body_indent,
                    )
                    if opcode == "JMP":
                        body += jump
                        advances = False
                    else:
                        condition = "__il_acc" if opcode == "JMPC" else self._il_boolean_not("__il_acc")
                        body += engine.render(
                            "il_guarded", condition=condition, body=jump, indent=body_indent
                        )
                elif opcode in {"RET", "RETC", "RETCN"}:
                    if self.current_function:
                        value = " __il_acc"
                    else:
                        value = ""
                    statement = engine.render(
                        "il_return", value=value, has_value="1" if value else "",
                        condition="", has_condition="", indent=body_indent + "    " if opcode != "RET" else body_indent,
                    )
                    if opcode == "RET":
                        body += statement
                        advances = False
                    else:
                        condition = "__il_acc" if opcode == "RETC" else self._il_boolean_not("__il_acc")
                        body += engine.render(
                            "il_guarded", condition=condition, body=statement, indent=body_indent
                        )
                else:
                    function_names = self._il_descendants(operation, "il_function_name")
                    if function_names:
                        name = function_names[0].get("value", "")
                        arguments = self._il_call_arguments(operation, "__il_acc")
                        body += engine.render(
                            "il_assign", target="__il_acc",
                            value=engine.render(
                                "il_call", name=name, arguments=", ".join(arguments)
                            ),
                            indent=body_indent,
                        )
            if advances:
                body += engine.render("il_next", index=index + 1, indent=body_indent)
            arms.append(
                engine.render(
                    "il_instruction", index=index,
                    label="", has_label="", body=body, indent=self.indent,
                )
            )
        self.text += engine.render(
            "il_dispatch", instructions="".join(arms), labels="",
            indent=self.indent, acc=initial,
        )
        if self.current_function and not stored_function_result:
            target = self.render({"name": "variable_name", "value": self.current_function, "children": []})
            self.text += engine.render(
                "il_assign", target=target, value="__il_acc", indent=self.indent
            )

    def visit_instruction_list(self, node):
        instructions = self._il_descendants(node, "il_instruction")
        if self._il_has_jumps(instructions):
            self._visit_instruction_list_with_jumps(node, instructions)
            return
        engine = self.generator_engine
        accumulator = None
        terminated = False
        stored_function_result = False
        for instruction in instructions:
            for label in self._il_labels(instruction):
                self.text += engine.render(
                    "il_label", name=label.get("value", ""), indent=self.indent
                )
            operation = self._il_operation(instruction)
            if operation is None:
                continue
            opcode = self._il_token(operation)
            operand = self._il_render_operand(operation)
            if opcode in {"LD", "LDN"} and operand is not None:
                accumulator = self._il_boolean_not(operand) if opcode == "LDN" else operand
            elif opcode in {"ST", "STN"} and operand is not None and accumulator is not None:
                value = self._il_boolean_not(accumulator) if opcode == "STN" else accumulator
                self.text += engine.render(
                    "il_assign", target=operand, value=value, indent=self.indent
                )
                stored_function_result = bool(self.current_function) and operand.casefold() == self.current_function.casefold()
            elif opcode == "NOT" and accumulator is not None:
                accumulator = self._il_boolean_not(accumulator)
            elif opcode in {"ANDN", "AN", "ORN", "XORN"} and accumulator is not None and operand is not None:
                key = {"ANDN": "BIT_AND", "AN": "BIT_AND", "ORN": "BIT_OR", "XORN": "XOR"}[opcode]
                operator = engine.map("operator", key)
                accumulator = f"({accumulator} {operator} {self._il_boolean_not(operand)})"
            elif opcode in {"AND", "&", "OR", "XOR", "ADD", "SUB", "MUL", "DIV", "MOD", "GT", "GE", "EQ", "LT", "LE", "NE"} and accumulator is not None and operand is not None:
                operator = engine.map("operator", self._il_opcode_key(opcode))
                accumulator = f"({accumulator} {operator} {operand})"
            elif opcode in {"S", "S1", "R", "R1"} and accumulator is not None and operand is not None:
                value = self._il_true() if opcode in {"S", "S1"} else self._il_false()
                inner = engine.render(
                    "il_assign", target=operand, value=value, indent=self.indent + "    "
                )
                self.text += engine.render(
                    "il_guarded", condition=accumulator, body=inner, indent=self.indent
                )
            elif opcode in {"RET", "RETC", "RETCN"}:
                condition = None
                if opcode == "RETC" and accumulator is not None:
                    condition = accumulator
                elif opcode == "RETCN" and accumulator is not None:
                    condition = self._il_boolean_not(accumulator)
                if self.current_function and accumulator is not None:
                    value = f" {accumulator}"
                else:
                    value = ""
                statement = engine.render(
                    "il_return", value=value, has_value="1" if value else "",
                    condition=condition or "", has_condition="1" if condition else "",
                    indent=self.indent + "    " if condition else self.indent,
                )
                if condition is None:
                    self.text += statement
                else:
                    self.text += engine.render(
                        "il_guarded", condition=condition, body=statement,
                        indent=self.indent,
                    )
                terminated = opcode == "RET"
            else:
                function_names = self._il_descendants(operation, "il_function_name")
                if function_names:
                    name = function_names[0].get("value", "")
                    arguments = self._il_call_arguments(operation, accumulator)
                    accumulator = engine.render(
                        "il_call", name=name, arguments=", ".join(arguments)
                    )

        # IEC functions return the current result when physical end-of-body is
        # reached. Assigning the generated return variable preserves the normal
        # backend epilogue and works for both C and Rust.
        if self.current_function and accumulator is not None and not terminated and not stored_function_result:
            target = self.render({"name": "variable_name", "value": self.current_function, "children": []})
            self.text += engine.render(
                "il_assign", target=target, value=accumulator, indent=self.indent
            )

    def __init__(self, context=None, source_name="<stdin>", native_implementations=None, generator_bundle: GeneratorBundle | None = None):
        self.context = context
        self.source_name = source_name
        self.native_implementations = native_implementations or {}
        display_source = str(source_name).replace("\n", " ").replace("\r", " ")
        standard_edition = context.standard_edition if context is not None else 3
        self.generator_engine = GeneratorEngine(
            generator_bundle or load_generator(bundled_generator("rust"))
        )
        self.text = self.generator_engine.render(
            "preamble", source=display_source, edition=str(standard_edition)
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
        if self.generator_engine is not None:
            return self.generator_engine.map("type", str(typein))
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
        if isinstance(datatype, ReferenceType):
            referenced = datatype.referenced_type
            return f"*mut {self.iecType2Rust(referenced.name if referenced else 'INT')}"
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
            return self.generator_engine.render(
                "cast", Cast(source_type, target_type, rendered)
            )
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
        reference = self._first_named(node, "reference_specification")
        if reference is not None:
            return f"*mut {self.extract_type(reference) or fallback}"
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
                size = f"{upper} - ({lower}) + 1"
                dimensions.append(self.generator_engine.render("cast", Cast("", "usize", size)))
        return dimensions

    def _declaration_type(self, node):
        reference = self._first_named(node, "reference_specification")
        if reference is not None:
            return f"*mut {self.extract_type(reference) or 'i16'}"
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
        if rust_type.startswith("*mut "):
            return "std::ptr::null_mut()"
        if rust_type == "bool":
            return "false"
        if rust_type in ("f32", "f64"):
            return "0.0"
        if rust_type in {"String", "&'static str"}:
            return '""'
        if rust_type.startswith("Vec<"):
            return "Vec::new()"
        if rust_type.startswith("[") and rust_type.endswith("]"):
            inner = rust_type[1:-1]
            element, separator, length = inner.rpartition(";")
            if separator:
                return f"[{self.zero_value(element.strip())}; {length.strip()}]"
            return "Default::default()"
        if self.context is not None:
            datatype = self.context.declared_types.get(rust_type.casefold())
            if isinstance(datatype, ArrayType):
                return "std::array::from_fn(|_| Default::default())"
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
            names_node = self._first_named(node, "var1_list")
            for child in self._named_nodes(names_node, "variable_name"):
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
                    if self._first_named(declaration, "reference_value") is not None:
                        continue
                    initializer = self._first_named(declaration, "constant")
                    if initializer is None:
                        continue
                    value = self.render(initializer)
                    for _, field in self.collect_var_decls(declaration):
                        result[field.casefold()] = value
        return result

    def _reference_initializers(self, node, declarations):
        result = {}
        previous_instance, previous_fields = self.current_instance, self.current_instance_fields
        self.current_instance = True
        self.current_instance_fields = {field.casefold() for _, field in declarations}
        try:
            for section_name in (
                "input_declarations", "output_declarations", "var_declarations",
                "retentive_var_declarations", "non_retentive_var_decls",
            ):
                for section in self._named_nodes(node, section_name):
                    for declaration in self._iter_named_set(section, {"var1_init_decl"}):
                        constructor = self._first_named(declaration, "reference_constructor")
                        if constructor is None:
                            continue
                        value = self.render(constructor)
                        for _, field in self.collect_var_decls(declaration):
                            result[field.casefold()] = value
        finally:
            self.current_instance, self.current_instance_fields = previous_instance, previous_fields
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

    def _capture_emission(self, callback):
        previous = self.text
        self.text = ""
        try:
            callback()
            return self.text
        finally:
            self.text = previous

    def _sfc_state_types(self):
        """Return backend-spelled (bool, time) types for SFC state fields."""
        return (
            self.generator_engine.map("type", "BOOL"),
            self.generator_engine.map("type", "TIME"),
        )

    def _emit_state_type(self, name, declarations, retained, initializers, entry_name, body_name, node):
        bool_type, time_type = self._sfc_state_types()
        declarations = self._unique_declarations(
            declarations + sfc_state_declarations(node, bool_type, time_type)
        )
        for chart in sfc_charts(node):
            for step in chart["steps"]:
                if step["initial"]:
                    initializers[sfc_field(step["name"], "active").casefold()] = "true"
        retained_names = {field.casefold() for _, field in retained}
        reference_initializers = self._reference_initializers(node, declarations)
        fields = "".join(f"    pub {field}: {var_type},\n" for var_type, field in declarations)
        defaults = ""
        for var_type, field in declarations:
            value = initializers.get(field.casefold(), self.zero_value(var_type))
            defaults += f"            {field}: {value},\n"
        cold_init = "        *self = Self::default();\n"
        for _, field in declarations:
            if field.casefold() in reference_initializers:
                cold_init += f"        self.{field} = {reference_initializers[field.casefold()]};\n"
        warm_init = ""
        for var_type, field in declarations:
            if field.casefold() not in retained_names:
                value = initializers.get(field.casefold(), self.zero_value(var_type))
                warm_init += f"        self.{field} = {value};\n"
        for _, field in declarations:
            if field.casefold() in reference_initializers:
                warm_init += f"        self.{field} = {reference_initializers[field.casefold()]};\n"
        properties = self._capture_emission(lambda: self._emit_function_block_properties(node, declarations))
        inouts = self.collect_sections(node, "input_output_declarations")
        parameters = ", " + ", ".join(f"{field}: &mut {var_type}" for var_type, field in inouts) if inouts else ""
        old_indent = self.indent
        old_instance, old_fields, old_refs = self.current_instance, self.current_instance_fields, self.current_reference_params
        self.indent = "        "
        self.current_reference_params = {field.casefold() for _, field in inouts}
        self.current_instance, self.current_instance_fields = True, {field.casefold() for _, field in declarations} - self.current_reference_params
        temporaries = ""
        for var_type, field in self.collect_sections(node, "temp_var_decls"):
            temporaries += f"{self.indent}let mut {field}: {var_type} = {self.zero_value(var_type)};\n"
        body_node = self._first_named(node, body_name)
        body = self.render(body_node) if body_node is not None else ""
        self.current_instance, self.current_instance_fields, self.current_reference_params = old_instance, old_fields, old_refs
        self.indent = old_indent
        rule = "function_block" if entry_name == "step" else "program"
        self.text += self.generator_engine.render(
            rule, name=name, fields=fields, defaults=defaults, properties=properties,
            setup="", cold_init=cold_init, warm_init=warm_init,
            parameters=parameters, entrypoint=entry_name,
            temporaries=temporaries, body=body,
        )

    def _emit_function_block_properties(self, node, declarations):
        field_paths = {field.casefold(): field for _, field in declarations}
        for prop in self._named_nodes(node, "property_declaration"):
            method = self._first_named(prop, "method_declaration")
            method_name_node = self._first_named(method, "method_name") if method is not None else None
            if method is None or method_name_node is None:
                continue
            method_name = method_name_node["value"]
            result, params = self._rust_method_signature(method)
            suffix = self._lowered_param_decl(params)
            old_instance, old_fields = self.current_instance, self.current_instance_fields
            old_paths, old_refs, old_indent = self.current_instance_field_paths, self.current_reference_params, self.indent
            self.current_instance = True
            self.current_instance_fields = set(field_paths)
            self.current_instance_field_paths = field_paths
            self.current_reference_params = {param.casefold() for param, _, pointer in params if pointer}
            self.indent = "        "
            locals_text = ""
            if result != "()":
                locals_text += f"{self.indent}let mut {method_name}: {result} = {self.zero_value(result)};\n"
            for var_type, local in (
                self.collect_sections(method, "function_var_decls")
                + self.collect_sections(method, "temp_var_decls")
            ):
                locals_text += f"{self.indent}let mut {local}: {var_type} = {self.zero_value(var_type)};\n"
            method_body = self._first_named(method, "function_body")
            if method_body is not None:
                body = self._capture_emission(lambda: self.visit(method_body))
            else:
                body = ""
            self.current_instance, self.current_instance_fields = old_instance, old_fields
            self.current_instance_field_paths, self.current_reference_params, self.indent = old_paths, old_refs, old_indent
            self.text += self.generator_engine.render(
                "property_method",
                owner="",
                name=method_name,
                return_type=result,
                parameters=suffix,
                locals=locals_text,
                body=body,
                return_stmt=(
                    self.generator_engine.render(
                        "method_return", name=method_name, indent="        "
                    )
                    if result != "()"
                    else ""
                ),
            )

    def collect_sections(self, node, section_name):
        if not isinstance(node, dict):
            return []
        if node.get("name") == "property_declaration":
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
        bundle = self.generator_engine.bundle
        self.text += render_primitives(
            bundle.extension, requested, self.generator_engine, bundle.path
        ) + "\n"
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
        comment = (
            f"/// Automatically generated conversion for enum `{node.get('enum_type')}`.\n"
            if node.get("synthetic") and node.get("generated_by") == "enum-conversions"
            else f"/// IEC function `{name}`.\n"
        )
        allowed_lints = ["non_snake_case", "unused_assignments", "unused_mut", "unused_variables"]
        if node.get("synthetic") and node.get("generated_by") == "enum-conversions":
            allowed_lints.append("unreachable_patterns")
        attributes = f"#[allow({', '.join(allowed_lints)})]"
        locals_text = ""
        if return_type != "()":
            locals_text += f"    let mut {name}: {return_type} = {self.zero_value(return_type)};\n"
        for var_type, var_name in local_decls:
            locals_text += f"    let mut {var_name}: {var_type} = {self.zero_value(var_type)};\n"
        if local_decls or return_type != "()":
            locals_text += "\n"
        old_indent = self.indent
        self.indent = "    "
        if native is not None:
            body = "".join(f"    {line.rstrip()}\n" if line.strip() else "\n" for line in (native.section("body") or "").splitlines())
        else:
            function_body = self._first_named(node, "function_body")
            body = self.render(function_body) if function_body is not None else ""
        self.indent = old_indent
        return_value = f"    {name}\n" if return_type != "()" else ""
        self.text += self.generator_engine.render(
            "function", name=name, emitted_name=emitted_name, comment=comment, attributes=attributes,
            return_type=return_type, parameters=", ".join(params), locals=locals_text,
            body=body, return_value=return_value,
        )
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
            self.indent_inc()
            body = self._capture_emission(
                lambda: self.accept(node, lambda child_name: child_name == "function_block_body")
            )
            self.indent_dec()
            self.text += self.generator_engine.render(
                "sfc_action_decl", name=name["value"], body=body
            )

    def _sfc_flag(self, field):
        return self.generator_engine.render("sfc_flag", field=field)

    def _sfc_step_condition(self, step, association):
        engine = self.generator_engine
        active = self._sfc_flag(sfc_field(step["name"], "active"))
        previous = self._sfc_flag(sfc_field(step["name"], "previous"))
        elapsed = self._sfc_flag(sfc_field(step["name"], "elapsed_ms"))
        and_op = engine.map("operator", "AND")
        not_op = engine.map("operator", "NOT")
        qualifier = association["qualifier"]
        time = self.render(association["time"]) if association["time"] is not None else "0"
        if qualifier in {"P", "P1"}:
            return f"({active} {and_op} {not_op}{previous})"
        if qualifier == "P0":
            return f"({not_op}{active} {and_op} {previous})"
        if qualifier == "L":
            return f"({active} {and_op} {elapsed} {engine.map('operator', 'LT')} ({time}))"
        if qualifier in {"D", "SD", "DS"}:
            return f"({active} {and_op} {elapsed} {engine.map('operator', 'GE')} ({time}))"
        if qualifier == "SL":
            return f"({active} {and_op} {elapsed} {engine.map('operator', 'LT')} ({time}))"
        return active

    def _sfc_variable(self, name):
        return self.render({"name": "variable_name", "value": name, "children": []})

    def visit_sequential_function_chart(self, node):
        engine = self.generator_engine
        and_op = engine.map("operator", "AND")
        or_op = engine.map("operator", "OR")
        not_op = engine.map("operator", "NOT")
        false_value = engine.map("boolean_literal", "FALSE")
        true_value = engine.map("boolean_literal", "TRUE")
        for chart_index, chart in enumerate(sfc_charts(node)):
            ordered = sorted(enumerate(chart["transitions"]), key=lambda item: (item[1]["priority"], item[0]))
            earlier_sources = []
            fire_names = {}
            decls = {}
            for ordinal, transition in ordered:
                fire = f"__sfc_{chart_index}_fire_{ordinal}"
                fire_names[ordinal] = fire
                sources = f" {and_op} ".join(
                    self._sfc_flag(sfc_field(name, "active")) for name in transition["sources"]
                ) or false_value
                condition = self.render(transition["condition"]) if transition["condition"] is not None else false_value
                current_sources = {item.casefold() for item in transition["sources"]}
                blocked = [
                    name for name, used in earlier_sources
                    if {item.casefold() for item in used} & current_sources
                ]
                gate = "" if not blocked else f" {and_op} " + f" {and_op} ".join(f"{not_op}{name}" for name in blocked)
                decls[ordinal] = engine.render(
                    "sfc_fire",
                    fire=fire,
                    sources=sources,
                    condition=condition,
                    gate=gate,
                    indent=self.indent,
                )
                earlier_sources.append((fire, transition["sources"]))

            chunks = []
            for ordinal, transition in enumerate(chart["transitions"]):
                fire = fire_names.get(ordinal)
                if fire is None:
                    continue
                self.indent_inc()
                body = ""
                for name in transition["sources"]:
                    body += engine.render(
                        "sfc_step_assign",
                        step=sfc_field(name, "active"),
                        value=false_value,
                        indent=self.indent,
                    )
                for name in transition["targets"]:
                    body += engine.render(
                        "sfc_step_assign",
                        step=sfc_field(name, "active"),
                        value=true_value,
                        indent=self.indent,
                    )
                self.indent_dec()
                chunks.append(
                    engine.render(
                        "sfc_transition",
                        fire=fire,
                        sources="",
                        targets="",
                        condition=(
                            self.render(transition["condition"])
                            if transition["condition"] is not None
                            else false_value
                        ),
                        priority=transition["priority"],
                        decl=decls[ordinal],
                        body=body,
                        indent=self.indent,
                    )
                )

            for step in chart["steps"]:
                chunks.append(
                    engine.render(
                        "sfc_elapsed",
                        step=step["name"],
                        active=sfc_field(step["name"], "active"),
                        previous=sfc_field(step["name"], "previous"),
                        elapsed=sfc_field(step["name"], "elapsed_ms"),
                        indent=self.indent,
                    )
                )

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
                            self.indent_inc()
                            action_body = self._capture_emission(
                                lambda: self.accept(action, lambda child_name: child_name == "function_block_body")
                            )
                            self.indent_dec()
                            chunks.append(
                                engine.render(
                                    "sfc_action",
                                    condition=condition,
                                    body=action_body,
                                    indent=self.indent,
                                )
                            )
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
                enabled = conditions[0] if len(conditions) == 1 else f" {or_op} ".join(f"({item})" for item in conditions)
                if name in variable_sets or name in variable_resets:
                    chunks.append(
                        engine.render(
                            "sfc_set",
                            target=self._sfc_variable(name),
                            condition=enabled,
                            value=true_value,
                            indent=self.indent,
                        )
                    )
                else:
                    chunks.append(
                        engine.render(
                            "sfc_assign",
                            target=self._sfc_variable(name),
                            condition=enabled,
                            indent=self.indent,
                        )
                    )
            for name, conditions in variable_sets.items():
                enabled = f" {or_op} ".join(f"({item})" for item in conditions)
                chunks.append(
                    engine.render(
                        "sfc_set",
                        target=self._sfc_variable(name),
                        condition=enabled,
                        value=true_value,
                        indent=self.indent,
                    )
                )
            for name, conditions in variable_resets.items():
                enabled = f" {or_op} ".join(f"({item})" for item in conditions)
                chunks.append(
                    engine.render(
                        "sfc_set",
                        target=self._sfc_variable(name),
                        condition=enabled,
                        value=false_value,
                        indent=self.indent,
                    )
                )
            for key, conditions in action_sets.items():
                enabled = f" {or_op} ".join(f"({item})" for item in conditions)
                chunks.append(
                    engine.render(
                        "sfc_stored",
                        action=sfc_field("action_" + key, "stored"),
                        condition=enabled,
                        value=true_value,
                        indent=self.indent,
                    )
                )
            for key, conditions in action_resets.items():
                enabled = f" {or_op} ".join(f"({item})" for item in conditions)
                chunks.append(
                    engine.render(
                        "sfc_stored",
                        action=sfc_field("action_" + key, "stored"),
                        condition=enabled,
                        value=false_value,
                        indent=self.indent,
                    )
                )
            for key in sorted(stored_actions):
                action = chart["actions"][key]
                state = self._sfc_flag(sfc_field("action_" + key, "stored"))
                self.indent_inc()
                stored_body = self._capture_emission(
                    lambda: self.accept(action, lambda child_name: child_name == "function_block_body")
                )
                self.indent_dec()
                chunks.append(
                    engine.render(
                        "sfc_action", condition=state, body=stored_body, indent=self.indent
                    )
                )
            for step in chart["steps"]:
                chunks.append(
                    engine.render(
                        "sfc_previous",
                        step=step["name"],
                        active=sfc_field(step["name"], "active"),
                        previous=sfc_field(step["name"], "previous"),
                        indent=self.indent,
                    )
                )
            self.text += engine.render(
                "sfc_chart", body="".join(chunks), indent=self.indent,
                steps="", transitions="", actions="",
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

    def _lowered_param_decl(self, params):
        """Render `name: type` declarations through the backend templates."""
        engine = self.generator_engine
        rendered = []
        for name, var_type, pointer in params:
            rule = "method_parameter_out" if pointer else "method_parameter"
            rendered.append(
                {"value": engine.render(rule, type=var_type, name=name, mode="")}
            )
        joined = engine.render("method_parameters", items=rendered)
        return ", " + joined if joined else ""

    def visit_interface_declaration(self, node):
        name_node = self._first_named(node, "interface_type_name")
        if name_node is None:
            return
        name = name_node["value"]
        iface = (self.context.oop_types.get("interfaces", {}).get(name.casefold()) if self.context is not None else None)
        methods = iface.get("methods", []) if iface else []
        engine = self.generator_engine
        slots = []
        defaults = []
        impls = []
        for method in methods:
            result, params = self._rust_method_signature(method["node"])
            types = ", ".join(("&mut " if pointer else "") + var_type for _, var_type, pointer in params)
            slot_suffix = ", " + types if types else ""
            slots.append(
                engine.render(
                    "interface_method",
                    name=method["name"],
                    return_type=result,
                    parameters=slot_suffix,
                )
            )
            placeholders = ", ".join("_" for _ in params)
            defaults.append(
                engine.render(
                    "interface_default",
                    interface=name,
                    name=method["name"],
                    parameters=", " + placeholders if placeholders else "",
                )
            )
            decl_suffix = self._lowered_param_decl(params)
            arguments = ", ".join(param for param, _, _ in params)
            impls.append(
                engine.render(
                    "interface_impl",
                    name=method["name"],
                    return_type=result,
                    parameters=decl_suffix,
                    arguments=", " + arguments if arguments else "",
                )
            )
        self.text += engine.render(
            "interface",
            name=name,
            bases="",
            methods="".join(slots),
            defaults="".join(defaults),
            impls="".join(impls),
        )

    def visit_class_declaration(self, node):
        name_node = self._first_named(node, "class_type_name")
        if name_node is None or self.context is None:
            return
        cls = self.context.oop_types.get("classes", {}).get(name_node["value"].casefold())
        if cls is None:
            return
        engine = self.generator_engine
        name = cls["name"]
        base = self._rust_class(cls.get("base"))
        has_base = "1" if base is not None else ""
        no_base = "" if base is not None else "1"
        fields = self._rust_own_fields(cls)
        fields_text = engine.render(
            "class_fields",
            items=[{"type": var_type, "name": field} for var_type, field in fields],
        )
        base_field = engine.render(
            "class_base_field", base=base["name"] if base else "", has_base=has_base
        )
        init_text = engine.render(
            "class_init",
            name=name,
            base=base["name"] if base else "",
            has_base=has_base,
            vptr="",
            base_init=(
                engine.render("class_base_init", base=base["name"]) if base else ""
            ),
            statements="",
            defaults="".join(
                engine.render(
                    "class_default", field=field, value=self.zero_value(var_type)
                )
                for var_type, field in fields
            ),
        )
        methods_text = ""
        for method in cls["methods"]:
            if method["abstract"]:
                continue
            result, params = self._rust_method_signature(method["node"])
            suffix = self._lowered_param_decl(params)
            old_instance, old_fields = self.current_instance, self.current_instance_fields
            old_paths, old_refs = self.current_instance_field_paths, self.current_reference_params
            self.current_instance = True
            self.current_instance_field_paths = self._rust_field_paths(cls)
            self.current_instance_fields = set(self.current_instance_field_paths)
            self.current_reference_params = {param.casefold() for param, _, pointer in params if pointer}
            self.indent = "        "
            locals_text = ""
            if result != "()":
                locals_text += f"{self.indent}let mut {method['name']}: {result} = {self.zero_value(result)};\n"
            for var_type, local in self.collect_sections(method["node"], "function_var_decls") + self.collect_sections(method["node"], "temp_var_decls"):
                locals_text += f"{self.indent}let mut {local}: {var_type} = {self.zero_value(var_type)};\n"
            body_node = self._first_named(method["node"], "function_body")
            if body_node is not None:
                body = self._capture_emission(lambda: self.visit(body_node))
            else:
                body = ""
            self.current_instance, self.current_instance_fields = old_instance, old_fields
            self.current_instance_field_paths, self.current_reference_params = old_paths, old_refs
            self.indent = ""
            methods_text += engine.render(
                "class_method",
                **{"class": name},
                name=method["name"],
                return_type=result,
                receiver=engine.render("method_receiver"),
                parameters=suffix,
                locals=locals_text,
                body=body,
                has_return="1" if result != "()" else "",
                return_stmt=(
                    engine.render(
                        "method_return", name=method["name"], indent="        "
                    )
                    if result != "()"
                    else ""
                ),
            )
        adapters = ""
        for iface in ([] if cls["abstract"] else self._rust_implemented_interfaces(cls)):
            entries = []
            for method in iface["methods"]:
                result, params = self._rust_method_signature(method["node"])
                decl_suffix = self._lowered_param_decl(params)
                arguments = ", ".join(param for param, _, _ in params)
                entries.append(
                    engine.render(
                        "adapter_entry",
                        **{"class": name, "interface": iface["name"]},
                        name=method["name"],
                        implementation="",
                        parameters=decl_suffix,
                        arguments=arguments,
                        return_type=result,
                    )
                )
            adapters += engine.render(
                "interface_adapter",
                **{"class": name, "interface": iface["name"]},
                methods="".join(entries),
            )
        self.text += engine.render(
            "class",
            name=name,
            base=base["name"] if base else "",
            has_base=has_base,
            no_base=no_base,
            has_fields="1" if fields else "",
            no_fields="" if fields else "1",
            fields=fields_text,
            base_field=base_field,
            vptr_field=engine.render("class_vptr_field", no_base=no_base),
            empty_field=engine.render("class_empty_field", empty=""),
            prototypes="",
            vtable="",
            dispatch="",
            adapters=adapters,
            init=init_text,
            methods=methods_text,
            interfaces="",
        )

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
        engine = self.generator_engine
        kind = resolution["receiver_kind"]
        if kind == "THIS":
            target = "self"
            rule = "virtual_call_this"
        elif kind == "SUPER":
            target = "self.__base"
            rule = "virtual_call_super"
        else:
            variable = self._first_named(receiver, "variable_name")
            target = self.render(variable) if variable is not None else "self"
            rule = (
                "virtual_call_interface"
                if resolution["interface"]
                else "virtual_call"
            )
        arguments = []
        for assignment in self._named_nodes(node, "param_assignment"):
            expressions = self._named_nodes(assignment, "expression")
            if expressions:
                arguments.append(self.render(expressions[-1]))
        bare = ", ".join(arguments)
        self.text += engine.render(
            rule,
            receiver=target,
            method=method["value"],
            static_type=resolution["receiver_type"],
            vptr="",
            arguments=bare,
            extra_arguments=", " + bare if bare else "",
        )

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
        for declaration in self._named_nodes(node, "reference_type_declaration"):
            self.visit_reference_type_declaration(declaration)

    def visit_reference_type_declaration(self, node):
        name = self._first_named(node, "reference_type_name")
        specification = self._first_named(node, "reference_specification")
        if name is not None and specification is not None:
            target = self.extract_type(specification) or "i16"
            self.text += f"/// IEC reference type `{name['value']}`.\n"
            self.text += self.generator_engine.render("reference_type", name=name["value"], referenced_type=target)

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
                size = f"{self.render(ints[1])} - ({self.render(ints[0])}) + 1"
                dimensions.append(self.generator_engine.render("cast", Cast("", "usize", size)))
        element = self.declaration_type(spec)
        for size in reversed(dimensions):
            element = self.generator_engine.render("array_dimension", value=element, size=size, lower="", upper="")
        self.text += f"/// IEC array type `{name}`.\n"
        self.text += self.generator_engine.render("array_type", name=name, element_type=self.declaration_type(spec), dimensions=element)

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
            self.text += self.generator_engine.render(
                "cast", Cast(self.rust_type_for_node(argument) or "", self.iecType2Rust(trunc_match.group(1)), self.render(argument))
            )
            return

        resolved = self.context.resolved_calls.get(id(node)) if self.context is not None else None
        name = self.context.generated_names.get(id(resolved), resolved.name) if resolved is not None else self.render(children[0])
        resolved_arguments = (
            self.context.resolved_arguments.get(id(node)) if self.context is not None else None
        )
        arguments = resolved_arguments or [child for child in children[1:] if child.get("name") == "param_assignment"]
        rendered_arguments = []
        for argument in arguments:
            if resolved_arguments is not None:
                rendered_arguments.append({"value": self.render(argument)})
            else:
                expressions = [child for child in argument.get("children", []) if child.get("name") == "expression"]
                if expressions:
                    rendered_arguments.append({"value": self.render(expressions[-1])})
        argument_text = self.generator_engine.render("parameter", items=rendered_arguments)
        self.text += self.generator_engine.render(
            "call", Call(name, tuple(item["value"] for item in rendered_arguments)), arguments=argument_text
        )

    def visit_standard_function_name(self, node):
        self.text += node["value"]

    def visit_derived_function_name(self, node):
        self.text += node["value"]

    def visit_integer_literal(self, node):
        value = node["value"].replace("_", "")
        self.text += self.generator_engine.render("integer_literal", Literal(value, self.rust_type_for_node(node)))

    def visit_real_literal(self, node):
        value = node["value"].replace("_", "")
        self.text += self.generator_engine.render("real_literal", Literal(value, self.rust_type_for_node(node)))

    def visit_integer(self, node):
        self.text += node["value"].replace("_", "")

    def visit_signed_integer(self, node):
        if node.get("value") is not None:
            self.text += str(node["value"]).replace("_", "")
        else:
            self.accept(node)

    def _visit_based_integer(self, node, base):
        value = self.render(node["children"][0]).replace("_", "")
        digits = value.split("#", 1)[-1]
        prefix = self.generator_engine.map("based_prefix", str(base))
        normalized = str(int(digits, base)) if prefix == "" else digits
        self.text += self.generator_engine.render(
            "based_literal", value=normalized, base=str(base), prefix=prefix
        )

    def visit_binary_integer(self, node):
        self._visit_based_integer(node, 2)

    def visit_octal_integer(self, node):
        self._visit_based_integer(node, 8)

    def visit_hex_integer(self, node):
        self._visit_based_integer(node, 16)

    def visit_boolean_literal(self, node):
        self.text += self.generator_engine.map("boolean_literal", node["value"].upper())

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

    def visit_structured_variable(self, node):
        info = self.context.resolved_properties.get(id(node)) if self.context is not None else None
        if info is None or info.get("accessor") != "get":
            self.accept(node)
            return
        receiver = self._first_named(node, "variable_name")
        base_path = "".join(f".{field}" for field in info.get("base_path", ()))
        rule = (
            "property_get_interface"
            if info["interface"]
            else "property_get_class"
            if info["owner_kind"] == "class"
            else "property_get"
        )
        self.text += self.generator_engine.render(
            rule,
            receiver=self.render(receiver),
            method=info["method"]["name"],
            owner=info["owner"],
            arguments="",
            extra_arguments="",
            base_path=base_path,
        )

    def _emit_property_assignment(self, node):
        if self.context is None:
            return False
        variable = self._first_named(node, "variable")
        structured = self._first_named(variable, "structured_variable")
        info = self.context.resolved_properties.get(id(structured)) if structured is not None else None
        if info is None or info.get("accessor") != "set":
            return False
        receiver = self._first_named(structured, "variable_name")
        expression = self._first_named(node, "expression")
        base_path = "".join(f".{field}" for field in info.get("base_path", ()))
        rule = (
            "property_set_interface"
            if info["interface"]
            else "property_set_class"
            if info["owner_kind"] == "class"
            else "property_set"
        )
        self.text += self.generator_engine.render(
            rule,
            receiver=self.render(receiver),
            method=info["method"]["name"],
            owner=info["owner"],
            value=self.render(expression),
            indent=self.indent,
            base_path=base_path,
        )
        return True

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
        array = self.render(subscripted)
        subscripts = [child for child in subscript_list.get("children", []) if isinstance(child, dict) and child.get("name") == "subscript"]
        indices = []
        for dimension, subscript in enumerate(subscripts):
            index = self.render(subscript)
            lower = lower_bounds[dimension] if dimension < len(lower_bounds) else "0"
            adjusted = index if lower == "0" else f"({index}) - ({lower})"
            indices.append({"value": adjusted})
        rendered_indices = self.generator_engine.render("array_index", items=indices)
        self.text += self.generator_engine.render("array_access", array=array, indices=rendered_indices)

    def visit_subscript_list(self, node):
        for subscript in self._named_nodes(node, "subscript"):
            self.text += f"[({self.render(subscript)}) as usize]"

    def visit_expression(self, node):
        self._join_children(node, f" {self.generator_engine.map('operator', 'OR')} ")

    def visit_xor_expression(self, node):
        self._join_children(node, f" {self.generator_engine.map('operator', 'XOR')} ")

    def visit_and_expression(self, node):
        self._join_children(node, f" {self.generator_engine.map('operator', 'AND')} ")

    def visit_comparison(self, node):
        self._visit_infix_coerced(node)

    def visit_comparison_equality_operator(self, node):
        op = self.generator_engine.map("operator", node["value"])
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
            op = self.generator_engine.map("operator", child.get("value"))
            self.text += f" {op} "
            self.visit(child)

    def visit_power_expression(self, node):
        children = node.get("children", [])
        if not children:
            return
        expression = self.render(children[-1])
        for child in reversed(children[:-1]):
            expression = self.generator_engine.render(
                "power_expression", left=self.render(child), right=expression
            )
        self.text += expression

    def visit_unary_expression(self, node):
        op = node.get("value")
        child = next((item for item in node.get("children", []) if isinstance(item, dict)), None)
        operator = self.generator_engine.map("operator", op) if op else ""
        self.text += self.generator_engine.render(
            "unary_expression", UnaryExpression(operator, self.render(child) if child else "")
        )

    def visit_add_operator(self, node):
        self.text += f" {self.generator_engine.map('operator', node['value'])} "

    def visit_comparison_operator(self, node):
        op = self.generator_engine.map("operator", node["value"])
        self.text += f" {op} "

    def visit_assignment_statement(self, node):
        if self._emit_property_assignment(node):
            return
        variable = next(child for child in node["children"] if child.get("name") == "variable")
        expression = next(child for child in node["children"] if child.get("name") == "expression")
        oop_assignment = self.context.oop_assignments.get(id(node)) if self.context is not None else None
        if oop_assignment is not None:
            self.text += self.generator_engine.render(
                "interface_assignment",
                target=self.render(variable),
                source=self.render(expression),
                indent=self.indent,
                **{"class": oop_assignment["class"], "interface": oop_assignment["interface"]},
            )
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
            rendered = self.generator_engine.render(
                "cast", Cast(expression_type, target_type, rendered)
            )
        elif target_type is not None and expression_type is None and target_type not in {"bool", "&'static str"} and not enum_value:
            rendered = self.generator_engine.render(
                "cast", Cast("", target_type, rendered)
            )
        variable_name = self._first_named(variable, "variable_name")
        symbol = (
            self.context.symbols.symbol_for_reference(variable_name)
            if self.context is not None and variable_name is not None
            else None
        )
        if symbol is not None and symbol.storage in {"external", "global"}:
            self.text += f"{self.indent}unsafe {{ {variable_name['value']} = {rendered}; }}\n"
        else:
            self.text += self.generator_engine.render(
                "assignment", Assignment(self.render(variable), rendered, self.indent)
            )

    def visit_reference_constructor(self, node):
        variable = self._first_named(node, "variable")
        self.text += self.generator_engine.render("reference", value=self.render(variable))

    def visit_reference_value(self, node):
        if node.get("value") == "NULL":
            self.text += self.generator_engine.render("null_reference")
        else:
            self.accept(node)

    def visit_dereferenced_variable(self, node):
        referenced = next(
            (child for child in node.get("children", []) if isinstance(child, dict)),
            None,
        )
        self.text += self.generator_engine.render("dereference", value=self.render(referenced))

    def visit_assert_statement(self, node):
        expression = next(child for child in node.get("children", []) if isinstance(child, dict))
        self.text += f"{self.indent}ASSERT({self.render(expression)});\n"

    def visit_exit_statement(self, node):
        self.text += self.generator_engine.render("exit", indent=self.indent)

    def visit_continue_statement(self, node):
        self.text += self.generator_engine.render("continue", indent=self.indent)

    def visit_return_statement(self, node):
        expression = self._first_named(node, "expression")
        value = " " + self.render(expression) if expression is not None else ""
        self.text += self.generator_engine.render(
            "return", indent=self.indent, value=value, has_value=bool(value)
        )

    def _render_nested_body(self, node):
        self.indent_inc()
        try:
            return self.render(node)
        finally:
            self.indent_dec()

    def visit_if_statement(self, node):
        lowered = IfBranch(self.render(node["children"][0]), self._render_nested_body(node["children"][1]), self.indent)
        self.text += self.generator_engine.render("if", lowered)
        self.accept(node, lambda name: name == "elseif_statement_list")
        self.accept(node, lambda name: name == "else_statement")

    def visit_elseif_statement(self, node):
        lowered = IfBranch(self.render(node["children"][0]), self._render_nested_body(node["children"][1]), self.indent)
        self.text += self.generator_engine.render("elseif", lowered)

    def visit_else_statement(self, node):
        self.indent_inc()
        previous = self.text
        self.text = ""
        try:
            self.accept(node)
            body = self.text
        finally:
            self.text = previous
            self.indent_dec()
        self.text += self.generator_engine.render("else", body=body, indent=self.indent)

    def visit_while_statement(self, node):
        lowered = WhileLoop(self.render(node["children"][0]), self._render_nested_body(node["children"][1]), self.indent)
        self.text += self.generator_engine.render("while", lowered)

    def visit_repeat_statement(self, node):
        lowered = RepeatLoop(self.render(node["children"][1]), self._render_nested_body(node["children"][0]), self.indent)
        self.text += self.generator_engine.render("repeat", lowered)

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
        comparator = ">=" if direction == "DOWNTO" else "<="
        operator = "-=" if direction == "DOWNTO" else "+="
        step = self.render(by) if by is not None else "1"
        lowered_body = self._render_nested_body(body)
        self.text += self.generator_engine.render(
            "for", variable=variable, start=self.render(start), end=self.render(end),
            step=step, direction="descending" if direction == "DOWNTO" else "ascending",
            comparator=comparator, update=f"{variable} {operator} {step}",
            body=lowered_body, indent=self.indent,
        )

    def visit_case_statement(self, node):
        children = node.get("children", [])
        expression = next(child for child in children if child.get("name") == "expression")
        selector = self.render(expression)
        elements = []
        default_statements = None
        self.indent_inc()
        try:
            for child in children:
                if child.get("name") == "case_element":
                    case_list = next(item for item in child["children"] if item.get("name") == "case_list")
                    statements = next(item for item in child["children"] if item.get("name") == "statement_list")
                    labels = []
                    for label in (item for item in case_list.get("children", []) if item.get("name") == "case_list_element"):
                        subrange = self._first_named(label, "subrange")
                        if subrange is not None:
                            bounds = self._named_nodes(subrange, "signed_integer")
                            if len(bounds) == 2:
                                labels.append({"value": self.generator_engine.render("case_range", selector=selector, lower=self.render(bounds[0]), upper=self.render(bounds[1]))})
                        else:
                            labels.append({"value": self.generator_engine.render("case_value", selector=selector, value=self.render(label))})
                    label_text = self.generator_engine.render("case_labels", items=labels)
                    body = self._render_nested_body(statements)
                    rule = "case_element_first" if not elements else "case_element"
                    elements.append(self.generator_engine.render(rule, labels=label_text, body=body, indent=self.indent))
                elif child.get("name") == "statement_list":
                    default_statements = child
            if default_statements is not None:
                default_body = self._render_nested_body(default_statements)
            else:
                default_body = ""
            else_body = self.generator_engine.render(
                "case_else" if elements else "case_else_first",
                body=default_body, indent=self.indent, has_elements=bool(elements),
            )
        finally:
            self.indent_dec()
        self.text += self.generator_engine.render(
            "case", selector=selector, elements="".join(elements), else_body=else_body, indent=self.indent
        )

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
