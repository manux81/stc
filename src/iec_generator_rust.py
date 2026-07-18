# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate Rust code from the supported Structured Text AST subset."""

from nodevisitor import NodeVisitor


class RustCodeGenerator(NodeVisitor):
    def __init__(self):
        self.text = ""
        self.indent = ""
        self.current_function = None
        self.current_return_type = None

    def iecType2Rust(self, typein):
        conv = {
            "SINT": "i8", "INT": "i16", "DINT": "i32", "LINT": "i64",
            "USINT": "u8", "UINT": "u16", "UDINT": "u32", "ULINT": "u64",
            "REAL": "f32", "LREAL": "f64",
            "BOOL": "bool", "BYTE": "u8", "WORD": "u16", "DWORD": "u32", "LWORD": "u64",
        }
        return conv.get(typein.upper(), typein)

    def indent_inc(self):
        self.indent += "    "

    def indent_dec(self):
        self.indent = self.indent[:-4]

    def extract_type(self, node):
        if isinstance(node, dict):
            if node.get("name", "").endswith("_type_name") and node.get("value"):
                return self.iecType2Rust(node["value"])
            for child in node.get("children", []):
                found = self.extract_type(child)
                if found:
                    return found
        return None

    def zero_value(self, rust_type):
        if rust_type == "bool":
            return "false"
        if rust_type in ("f32", "f64"):
            return "0.0"
        return "0"

    def collect_var_decls(self, node):
        declarations = []
        if not isinstance(node, dict):
            return declarations
        if node.get("name") == "var1_init_decl":
            names = [child["value"] for child in node["children"][0].get("children", [])]
            var_type = self.extract_type(node["children"][1]) or "i16"
            return [(var_type, name) for name in names]
        for child in node.get("children", []):
            declarations.extend(self.collect_var_decls(child))
        return declarations

    def collect_sections(self, node, section_name):
        if not isinstance(node, dict):
            return []
        if node.get("name") == section_name:
            return self.collect_var_decls(node)
        declarations = []
        for child in node.get("children", []):
            declarations.extend(self.collect_sections(child, section_name))
        return declarations

    def visit_function_declaration(self, node):
        name = node["children"][0]["value"]
        return_type = self.extract_type(node["children"][1]) or "()"
        self.current_function = name
        self.current_return_type = return_type

        input_decls = self.collect_sections(node["children"][2], "input_declarations")
        local_decls = self.collect_sections(node["children"][2], "function_var_decls")
        params = [f"mut {var_name}: {var_type}" for var_type, var_name in input_decls]

        self.text += f"pub fn {name}({', '.join(params)}) -> {return_type}\n{{\n"
        self.indent_inc()
        if return_type != "()":
            self.text += f"{self.indent}let mut {name}: {return_type} = {self.zero_value(return_type)};\n"
        for var_type, var_name in local_decls:
            self.text += f"{self.indent}let mut {var_name}: {var_type} = {self.zero_value(var_type)};\n"
        if local_decls or return_type != "()":
            self.text += "\n"
        self.accept(node, lambda child_name: child_name == "function_body")
        if return_type != "()":
            self.text += f"{self.indent}{name}\n"
        self.indent_dec()
        self.text += "}\n"
        self.current_function = None
        self.current_return_type = None

    def visit_integer_literal(self, node):
        self.text += node["value"].replace("_", "")

    def visit_real_literal(self, node):
        self.text += node["value"].replace("_", "")

    def visit_integer(self, node):
        self.text += node["value"].replace("_", "")

    def visit_boolean_literal(self, node):
        self.text += node["value"].lower()

    def visit_bit_string_literal(self, node):
        for child in node["children"]:
            self.visit(child)

    def visit_signed_integer_type_name(self, node):
        self.text += self.iecType2Rust(node["value"])

    def visit_unsigned_integer_type_name(self, node):
        self.text += self.iecType2Rust(node["value"])

    def visit_real_type_name(self, node):
        self.text += self.iecType2Rust(node["value"])

    def visit_bit_string_type_name(self, node):
        self.text += self.iecType2Rust(node["value"])

    def visit_variable_name(self, node):
        self.text += node["value"]

    def visit_expression(self, node):
        self._join_children(node, " || ")

    def visit_xor_expression(self, node):
        self._join_children(node, " ^ ")

    def visit_and_expression(self, node):
        self._join_children(node, " && ")

    def visit_comparison(self, node):
        self._visit_infix(node)

    def visit_comparison_equality_operator(self, node):
        op = {"=": "==", "NEQ": "!=", "<>": "!="}.get(node["value"], node["value"])
        self.text += f" {op} "

    def visit_equ_expression(self, node):
        self._visit_infix(node)

    def visit_add_expression(self, node):
        self._visit_infix(node)

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
        self.text += self.indent
        self.accept(node, lambda name: name == "variable")
        self.text += " = "
        self.accept(node, lambda name: name == "expression")
        self.text += ";\n"

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

    def _join_children(self, node, separator):
        for index, child in enumerate(node["children"]):
            if index:
                self.text += separator
            self.visit(child)

    def _visit_infix(self, node):
        for child in node["children"]:
            self.visit(child)
