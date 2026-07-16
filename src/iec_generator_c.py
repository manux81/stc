from nodevisitor import NodeVisitor


class CCodeGenerator(NodeVisitor):
    def __init__(self):
        self.text = "#include <stdbool.h>\n#include <stdint.h>\n\n"
        self.indent = ""
        self.current_function = None
        self.current_return_type = None

    def iecType2C(self, typein):
        conv = {
            "SINT": "int8_t", "INT": "int16_t", "DINT": "int32_t", "LINT": "int64_t",
            "USINT": "uint8_t", "UINT": "uint16_t", "UDINT": "uint32_t", "ULINT": "uint64_t",
            "REAL": "float", "LREAL": "double",
            "BOOL": "bool", "BYTE": "uint8_t", "WORD": "uint16_t", "DWORD": "uint32_t",
            "LWORD": "uint64_t",
        }
        return conv.get(typein.upper(), typein)

    def indent_inc(self):
        self.indent += "    "

    def indent_dec(self):
        self.indent = self.indent[:-4]

    def render(self, node):
        previous = self.text
        self.text = ""
        self.visit(node)
        rendered = self.text
        self.text = previous
        return rendered

    def extract_type(self, node):
        if isinstance(node, dict):
            if node.get("name", "").endswith("_type_name") and node.get("value"):
                return self.iecType2C(node["value"])
            for child in node.get("children", []):
                found = self.extract_type(child)
                if found:
                    return found
        return None

    def zero_value(self, c_type):
        if c_type == "bool":
            return "false"
        if c_type in ("float", "double"):
            return "0.0"
        return "0"

    def collect_var_decls(self, node):
        declarations = []
        if not isinstance(node, dict):
            return declarations
        if node.get("name") == "var1_init_decl":
            names = []
            var_list = node["children"][0]
            for child in var_list.get("children", []):
                if child.get("name") == "variable_name":
                    names.append(child["value"])
            var_type = self.extract_type(node["children"][1]) or "int16_t"
            declarations.extend((var_type, name) for name in names)
            return declarations
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
        self.text += self.iecType2C(node["value"])

    def visit_unsigned_integer_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_real_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_bit_string_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_variable_name(self, node):
        self.text += node["value"]

    def visit_function_declaration(self, node):
        name = node["children"][0]["value"]
        return_type = self.extract_type(node["children"][1]) or "void"
        self.current_function = name
        self.current_return_type = return_type

        input_decls = self.collect_sections(node["children"][2], "input_declarations")
        local_decls = self.collect_sections(node["children"][2], "function_var_decls")
        params = [f"{var_type} {var_name}" for var_type, var_name in input_decls]

        self.text += f"{return_type} {name}({', '.join(params)})\n{{\n"
        self.indent_inc()
        if return_type != "void":
            self.text += f"{self.indent}{return_type} {name} = {self.zero_value(return_type)};\n"
        for var_type, var_name in local_decls:
            self.text += f"{self.indent}{var_type} {var_name} = {self.zero_value(var_type)};\n"
        if local_decls or return_type != "void":
            self.text += "\n"
        self.accept(node, lambda child_name: child_name == "function_body")
        if return_type != "void":
            self.text += f"{self.indent}return {name};\n"
        self.indent_dec()
        self.text += "}\n"
        self.current_function = None
        self.current_return_type = None

    def visit_var1_init_decl(self, node):
        var_type = self.extract_type(node) or "int16_t"
        names = [child["value"] for child in node["children"][0]["children"]]
        self.text += f"{var_type} {', '.join(names)}"

    def visit_expression(self, node):
        self._join_children(node, " || ")

    def visit_xor_expression(self, node):
        self._join_children(node, " ^ ")

    def visit_and_expression(self, node):
        self._join_children(node, " && ")

    def visit_comparison(self, node):
        self._join_children(node, " == ")

    def visit_equ_expression(self, node):
        self._visit_infix(node)

    def visit_add_expression(self, node):
        self._visit_infix(node)

    def visit_term(self, node):
        self._visit_infix_from_child_value(node)

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
        self.text += self.indent + "if ("
        self.visit(node["children"][0])
        self.text += ") {\n"
        self.indent_inc()
        self.visit(node["children"][1])
        self.indent_dec()
        self.text += self.indent + "}\n"
        self.accept(node, lambda name: name == "elseif_statement_list")
        self.accept(node, lambda name: name == "else_statement")

    def visit_elseif_statement(self, node):
        self.text += self.indent + "else if ("
        self.visit(node["children"][0])
        self.text += ") {\n"
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
        self.text += self.indent + "while ("
        self.visit(node["children"][0])
        self.text += ") {\n"
        self.indent_inc()
        self.visit(node["children"][1])
        self.indent_dec()
        self.text += self.indent + "}\n"

    def visit_repeat_statement(self, node):
        self.text += self.indent + "do {\n"
        self.indent_inc()
        self.visit(node["children"][0])
        self.indent_dec()
        self.text += self.indent + "} while (!("
        self.visit(node["children"][1])
        self.text += "));\n"

    def _join_children(self, node, separator):
        for index, child in enumerate(node["children"]):
            if index:
                self.text += separator
            self.visit(child)

    def _visit_infix(self, node):
        for child in node["children"]:
            self.visit(child)

    def _visit_infix_from_child_value(self, node):
        children = node["children"]
        if not children:
            return
        self.visit(children[0])
        for child in children[1:]:
            op = {"MOD": "%"}.get(child.get("value"), child.get("value"))
            self.text += f" {op} "
            self.visit(child)
